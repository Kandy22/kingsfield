"""Calibration harness tests. Stub model only; the real model is never loaded."""
import math
import os
import re
import sys
import threading
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from router import calibration as cal  # noqa: E402
from router import jev_cpu_inference as jev  # noqa: E402
from router import system_one_client as so  # noqa: E402
from router.jev_cpu_inference import JevCPURouter, LocalLlamaClient  # noqa: E402
from router.tests import stub_llama as st  # noqa: E402

CITE = re.compile(r"\d+\s+So\.\s*(2d|3d)\s+\d+|\d+\s+Fla\. L\. Weekly")
OPS = re.compile(r'"|\b(AND|OR|NOT)\b')

_PATCH = None


def setUpModule():
    global _PATCH

    class RealModelLoadForbidden(BaseException):
        pass

    def forbid(*a, **k):
        raise RealModelLoadForbidden("calibration tests must never load a real model")

    _PATCH = mock.patch.object(jev, "_import_llama_class", forbid)
    _PATCH.start()


def tearDownModule():
    _PATCH.stop()


def resp(answer, conf, raw, cmass=None, nmass=None):
    return so.SystemOneResponse(
        so.Choice(so.CHOICE_QUESTION, so.ROUTES, answer, conf, cmass),
        so.Noul(so.NOUL_QUESTION, raw, "low", nmass), so.Score(so.SCORE_QUESTION, conf))


class FakeClient:
    def __init__(self, fn):
        self.fn, self.calls = fn, []

    def query(self, q):
        self.calls.append(q)
        return self.fn(q)


LABELS = {i.text: i for i in cal.all_items()}
FLAGGED = {i.text for i in cal.all_items() if not i.gate and i.citation_present}
N_NONGATED = sum(1 for i in cal.all_items() if not i.gate)
N_GATED = sum(1 for i in cal.all_items() if i.gate)
N_STAGE = N_NONGATED - len(FLAGGED)


def perfect(q):
    item = LABELS[q]
    return resp(item.choice_label, 0.95, 0.97 if item.citation_present else 0.03, 0.9, 0.9)


def letters(i):
    return "".join(chr(97 + (i // 26 ** k) % 26) for k in range(3))


class Dataset(unittest.TestCase):
    def test_ids_kinds_and_edge_classes(self):
        ids = [p.pair_id for p in cal.CONTRASTIVE_PAIRS]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual({p.kind for p in cal.CONTRASTIVE_PAIRS},
                         {"route", "citation", "surface", "edge"})
        self.assertGreaterEqual(sum(p.kind == "surface" for p in cal.CONTRASTIVE_PAIRS), 4)
        feats = " | ".join(p.feature for p in cal.CONTRASTIVE_PAIRS if p.kind == "edge")
        for needle in ("OCR", "Ala.", "La.", "Miss.", "Fla. L. Weekly Fed.", "homoglyph",
                       "non-Latin", "injection"):
            self.assertIn(needle, feats)

    def test_every_text_is_unique(self):
        texts = [i.text for i in cal.all_items()]
        self.assertEqual(len(texts), len(set(texts)))

    def test_pairs_obey_their_kind(self):
        for p in cal.CONTRASTIVE_PAIRS:
            with self.subTest(pair=p.pair_id, kind=p.kind):
                self.assertNotEqual(p.a.text, p.b.text)
                for item in (p.a, p.b):
                    self.assertIn(item.choice_label, cal.ROUTES)
                if p.kind in ("route", "surface"):
                    self.assertNotEqual(p.a.choice_label, p.b.choice_label)
                    self.assertEqual(p.a.citation_present, p.b.citation_present)
                elif p.kind == "citation":
                    self.assertNotEqual(p.a.citation_present, p.b.citation_present)
                    cited, plain = (p.a, p.b) if p.a.citation_present else (p.b, p.a)
                    self.assertEqual(cited.choice_label, "direct_db")  # as production routes it
                    if plain.choice_label != "direct_db":
                        self.assertNotEqual(p.a.final_route, p.b.final_route)
                else:  # edge: invariance
                    self.assertEqual(p.a.choice_label, p.b.choice_label)
                    self.assertEqual(p.a.citation_present, p.b.citation_present)

    def test_labels_follow_the_prompt_definitions(self):
        for p in cal.CONTRASTIVE_PAIRS:
            for item in (p.a, p.b):
                with self.subTest(pair=p.pair_id, text=item.text):
                    if item.gate:
                        continue
                    if item.choice_label == "boolean_search":
                        self.assertTrue(OPS.search(item.text), "boolean needs operators/quotes")
                    if p.kind == "route" and item.choice_label == "vector_search":
                        self.assertFalse(OPS.search(item.text))
        for pid in ("c01", "c02", "c03", "c05"):
            p = next(q for q in cal.CONTRASTIVE_PAIRS if q.pair_id == pid)
            self.assertEqual((p.a.choice_label, p.b.choice_label), ("direct_db", "direct_db"))

    def test_surface_pairs_mislead_on_the_plain_side(self):
        for p in (q for q in cal.CONTRASTIVE_PAIRS if q.kind == "surface"):
            with self.subTest(pair=p.pair_id):
                self.assertEqual(p.a.choice_label, "vector_search")
                self.assertTrue(OPS.search(p.a.text), "plain side must carry a misleading cue")
                self.assertEqual(p.b.choice_label, "boolean_search")

    def test_gating_and_english(self):
        gated = [i for i in cal.all_items() if i.gate]
        self.assertGreaterEqual(len(gated), 2)
        for item in gated:
            self.assertEqual(item.gate, "english")
            self.assertFalse(so._is_english_scriptable(item.text), item.text)
        for item in cal.all_items():
            if not item.gate:
                self.assertTrue(so._is_english_scriptable(item.text), item.text)

    def test_final_route_follows_routes_rule(self):
        self.assertEqual(cal.Item("x", "boolean_search", True).final_route, "direct_db")
        self.assertEqual(cal.Item("x", "boolean_search", False).final_route, "boolean_search")


class Maths(unittest.TestCase):
    def test_reliability_and_ece_by_hand(self):
        recs = [(0.95, True), (0.95, True), (0.95, False), (0.95, True),
                (0.55, True), (0.55, False)]
        r = cal.reliability(recs)
        self.assertEqual(r.n, 6)
        self.assertAlmostEqual(r.ece, (4 / 6) * abs(0.75 - 0.95) + (2 / 6) * abs(0.5 - 0.55), places=9)
        self.assertEqual([b.n for b in r.bins], [2, 4])
        self.assertAlmostEqual(r.accuracy, 4 / 6)

    def test_confidence_one_goes_in_the_top_bin(self):
        self.assertEqual(cal.reliability([(1.0, True)]).bins[0].high, 1.0)

    def test_empty_records(self):
        r = cal.reliability([])
        self.assertEqual(r.n, 0)
        self.assertTrue(math.isnan(r.ece))

    def test_wilson_lower_bound(self):
        self.assertEqual(cal.wilson_lower(0, 0), 0.0)
        self.assertAlmostEqual(cal.wilson_lower(30, 30), 0.8865, places=3)
        self.assertGreater(cal.wilson_lower(300, 300), 0.98)
        self.assertLess(cal.wilson_lower(5, 5), 0.6)

    def test_threshold_is_none_with_a_note_below_min_reliable_n(self):
        recs = [(0.96, True)] * 50
        notes = []
        self.assertIsNone(cal.suggest_threshold(recs, notes=notes))
        self.assertEqual(len(notes), 1)
        self.assertIn("n=50", notes[0])
        self.assertIsNone(cal.suggest_threshold([(0.96, True)] * (cal.MIN_RELIABLE_N - 1)))

    def test_threshold_on_a_fixed_grid_not_observed_confidences(self):
        recs = [(0.96, True)] * 100 + [(0.62, True)] * 50 + [(0.62, False)] * 50
        t = cal.suggest_threshold(recs)
        self.assertEqual(t, 0.65)
        self.assertIn(t, cal.THRESHOLD_GRID)
        self.assertNotIn(0.62, cal.THRESHOLD_GRID)

    def test_no_cherry_picking_a_small_perfect_slice(self):
        recs = [(0.99, True)] * 30 + [(0.7, True)] * 100 + [(0.7, False)] * 70
        notes = []
        self.assertIsNone(cal.suggest_threshold(recs, notes=notes))
        self.assertTrue(notes)

    def test_abstentions_in_the_denominator_block_a_biased_subset(self):
        recs = [(0.96, True)] * 200
        notes = []
        self.assertIsNone(cal.suggest_threshold(recs, n_total=300, notes=notes))  # 33% abstained
        self.assertIn("abstain", notes[0])
        self.assertEqual(cal.suggest_threshold(recs, n_total=250), 0.5)         # 20% abstained

    def test_abstentions_count_against_coverage(self):
        recs = [(0.96, True)] * 250
        self.assertEqual(cal.suggest_threshold(recs, n_total=300, min_coverage=0.8), 0.5)
        self.assertIsNone(cal.suggest_threshold(recs, n_total=300, min_coverage=0.9))

    def test_no_threshold_when_confidence_is_not_informative(self):
        recs = [(0.96, i % 2 == 0) for i in range(300)]
        notes = []
        self.assertIsNone(cal.suggest_threshold(recs, notes=notes))
        self.assertTrue(notes)


class EvaluateThroughRoute(unittest.TestCase):
    """F2: evaluate() measures what route() ships."""

    def test_perfect_client_shipped_behaviour(self):
        client = FakeClient(perfect)
        rep = cal.evaluate(client)
        gated = {i.text for i in cal.all_items() if i.gate}
        self.assertFalse(gated & set(client.calls), "gated items must never reach the client")
        self.assertFalse(FLAGGED & set(client.calls),
                         "pre-check-flagged items must never reach the client")
        self.assertEqual(sorted(client.calls), sorted(set(client.calls)))
        self.assertEqual(rep.n_items, N_NONGATED)
        self.assertEqual(len(rep.items), N_NONGATED)
        self.assertEqual(rep.precheck_routed, len(FLAGGED))
        self.assertEqual(rep.n_model_stage, N_STAGE)
        self.assertEqual(len(client.calls), N_STAGE)
        self.assertEqual((rep.answered, rep.abstained, rep.abstain_rate, rep.coverage),
                         (N_STAGE, 0, 0.0, 1.0))
        self.assertEqual(rep.gated_checked, N_GATED)
        self.assertEqual(rep.gated_failures, [])
        self.assertEqual(rep.label_mismatches, [])
        self.assertEqual(rep.route_accuracy, 1.0)
        self.assertEqual(rep.pair_flip_accuracy, 1.0)
        self.assertEqual(rep.choice.accuracy, 1.0)
        self.assertEqual(rep.noul.accuracy, 1.0)
        self.assertEqual(rep.choice.n, N_STAGE)
        self.assertEqual(rep.threshold, so.DEFAULT_THRESHOLD)
        self.assertIsNone(rep.suggested_threshold)
        self.assertTrue(any("n=" in n for n in rep.notes))
        self.assertTrue(any("false positives only" in n for n in rep.notes))
        self.assertFalse(rep.calibrated)

    def test_item_results_carry_route_flag_cause_reason_and_mass(self):
        rep = cal.evaluate(FakeClient(perfect))
        self.assertEqual(rep.causes.get("citation_precheck"), len(FLAGGED))
        self.assertEqual(rep.causes.get("model", 0) + rep.causes.get("noul_citation", 0), N_STAGE)
        for r in rep.items:
            self.assertIsInstance(r, cal.ItemResult)
            self.assertTrue(r.reason)
            if r.precheck_flagged:
                self.assertEqual((r.route, r.fallback, r.cause), ("direct_db", False, "citation_precheck"))
                self.assertIn("pre-check", r.reason)
                self.assertIsNone(r.choice_mass)
                self.assertIsNone(r.noul_mass)
                self.assertIsNone(r.choice_answer)
            else:
                self.assertEqual((r.choice_mass, r.noul_mass), (0.9, 0.9))
                self.assertFalse(r.fallback)
                self.assertEqual(r.cause, "model")
                self.assertEqual(r.route, r.choice_answer)

    def test_local_model_mass_is_reported_from_the_real_scoring_path(self):
        client = LocalLlamaClient(router=JevCPURouter(st.FakeLlama(st.oracle_policy())))
        rep = cal.evaluate(client)
        answered = [r for r in rep.items if r.choice_answer is not None]
        self.assertEqual(len(answered), N_STAGE)
        for r in answered:
            self.assertGreater(r.choice_mass, jev.CHOICE_MASS_FLOOR)
            self.assertLessEqual(r.choice_mass, 1.0)
            self.assertGreater(r.noul_mass, jev.NOUL_MASS_FLOOR)

    def test_surface_keyed_stub_is_caught_by_surface_pairs(self):
        client = LocalLlamaClient(router=JevCPURouter(st.FakeLlama(st.oracle_policy())))
        rep = cal.evaluate(client)
        self.assertLess(rep.route_accuracy, 1.0)
        self.assertLess(rep.pair_flip_accuracy, 1.0)
        self.assertEqual(rep.abstained, 0)
        wrong = {r.pair_id for r in rep.items if not r.correct_route}
        self.assertTrue({"s01", "s02", "s03", "s04", "s05"} <= wrong)

    def test_below_threshold_items_are_abstentions_but_keep_their_records(self):
        rep = cal.evaluate(FakeClient(lambda q: resp("vector_search", 0.5, 0.03, 0.9, 0.9)))
        self.assertEqual(rep.abstention_breakdown["below_threshold"], N_STAGE)
        self.assertEqual(rep.abstention_breakdown["precheck"], len(FLAGGED))
        self.assertEqual(rep.abstained, 0)                  # the model DID answer
        self.assertEqual(rep.choice.n, N_STAGE)             # threshold must not truncate its own data
        self.assertTrue(all(r.fallback for r in rep.items if not r.precheck_flagged))
        self.assertLess(rep.route_accuracy, 1.0)

    def test_noul_uncertain_has_its_own_breakdown_key(self):
        rep = cal.evaluate(FakeClient(lambda q: resp("vector_search", 0.95, 0.5)))
        self.assertEqual(rep.abstention_breakdown["noul_uncertain"], N_STAGE)

    def test_mass_floor_abstentions(self):
        tiny = {"boolean_search": [1e-9, 0.5], "vector_search": [1e-8, 0.9],
                "direct_db": [1e-9, 0.5, 0.5]}
        policy = st.static_policy(choice=tiny, noul={"Yes": [0.03], "No": [0.97]})
        client = LocalLlamaClient(router=JevCPURouter(st.FakeLlama(policy)))
        rep = cal.evaluate(client)
        self.assertEqual(rep.abstention_breakdown["mass_floor"], N_STAGE)
        self.assertEqual(rep.abstained, N_STAGE)
        self.assertEqual(rep.answered, 0)
        self.assertEqual(rep.choice.n, 0)
        self.assertEqual(rep.choice_accuracy_overall, 0.0)
        self.assertIsNone(rep.suggested_threshold)
        self.assertTrue(all("mass" in r.reason for r in rep.items if r.cause == "mass_floor"))

    def test_breaker_abstentions_after_a_hang(self):
        policy = st.oracle_policy()
        llm = st.FakeLlama(policy)
        llm.hang = threading.Event()
        self.addCleanup(llm.hang.set)
        client = LocalLlamaClient(router=JevCPURouter(llm, timeout=0.2))
        rep = cal.evaluate(client)
        self.assertEqual(rep.abstention_breakdown["breaker"], N_STAGE)   # timeout + breaker
        self.assertEqual(rep.causes.get("timeout"), 1)
        self.assertEqual(rep.causes.get("breaker"), N_STAGE - 1)
        self.assertEqual(rep.answered, 0)

    def test_error_and_invalid_response_abstentions(self):
        def boom(q):
            raise RuntimeError("down")
        rep = cal.evaluate(FakeClient(boom))
        self.assertEqual(rep.abstention_breakdown["error"], N_STAGE)
        for bad in (lambda q: resp("llm_search", 0.9, 0.1),
                    lambda q: resp("vector_search", float("nan"), 0.1),
                    lambda q: resp("vector_search", 0.9, 1.5),
                    lambda q: resp("vector_search", True, 0.1),
                    lambda q: None):
            with self.subTest():
                r = cal.evaluate(FakeClient(bad))
                self.assertEqual(r.abstained, N_STAGE)
                self.assertEqual(r.abstention_breakdown["error"], N_STAGE)

    def test_abstentions_do_not_inflate_accuracy_or_ece(self):
        seen = {"n": 0}

        def flaky(q):
            seen["n"] += 1
            if seen["n"] % 2 == 0:
                raise so.SystemOneError("abstain")
            return perfect(q)
        rep = cal.evaluate(FakeClient(flaky))
        self.assertEqual(rep.answered + rep.abstained, rep.n_model_stage)
        self.assertGreater(rep.abstained, 0)
        self.assertEqual(rep.choice.n, rep.answered)
        self.assertEqual(rep.choice.accuracy, 1.0)                       # conditional on answering
        self.assertAlmostEqual(rep.choice_accuracy_overall, rep.answered / rep.n_model_stage)
        self.assertLess(rep.choice_accuracy_overall, rep.choice.accuracy)
        self.assertAlmostEqual(rep.noul_accuracy_overall, rep.answered / rep.n_model_stage)
        self.assertAlmostEqual(rep.coverage, rep.answered / rep.n_model_stage)
        self.assertAlmostEqual(rep.abstain_rate, rep.abstained / rep.n_model_stage)
        self.assertLess(rep.pair_flip_accuracy, 1.0)
        self.assertLess(rep.route_accuracy, 1.0)
        self.assertTrue(any("no usable model response" in n for n in rep.notes))
        self.assertIsNone(rep.suggested_threshold)

    def test_precheck_error_is_not_a_model_abstention(self):
        with mock.patch("pipeline.gate1.check_text", side_effect=RuntimeError("db")):
            rep = cal.evaluate(FakeClient(perfect))
        self.assertEqual(rep.causes.get("precheck_error"), N_NONGATED)
        self.assertEqual(rep.abstention_breakdown["error"], N_NONGATED)

    def test_duplicate_texts_are_rejected(self):
        item = cal.Item("landlord duty", "vector_search", False)
        other = cal.Item("tenant rights", "vector_search", False)
        pairs = [cal.Pair("p1", "edge", "x", item, other), cal.Pair("p2", "edge", "x", other, item)]
        with self.assertRaises(ValueError):
            cal.evaluate(FakeClient(perfect), pairs=pairs)

    def test_gate_that_does_not_reject_is_reported(self):
        latin = cal.Item("plain english text", "vector_search", False, gate="english")
        pairs = [cal.Pair("x1", "edge", "bad gate", cal.Item("hello world", "vector_search", False), latin)]
        client = FakeClient(lambda q: resp("vector_search", 0.9, 0.1))
        rep = cal.evaluate(client, pairs=pairs)
        self.assertEqual(rep.gated_failures, ["plain english text"])
        self.assertEqual(rep.pair_flip_accuracy, 0.0)
        self.assertTrue(any("English gate" in n for n in rep.notes))

    def test_a_label_that_disagrees_with_the_precheck_is_reported(self):
        wrong = cal.Item("Pull the opinion at 98 So. 2d 1021", "vector_search", False)  # flagged
        other = cal.Item("landlord duty topic", "vector_search", False)
        rep = cal.evaluate(FakeClient(lambda q: resp("vector_search", 0.95, 0.03)),
                           pairs=[cal.Pair("x", "edge", "x", wrong, other)])
        self.assertEqual(len(rep.label_mismatches), 1)
        self.assertEqual(rep.label_mismatches[0].text, wrong.text)

    def test_large_clean_run_can_suggest_a_threshold(self):
        pairs = [cal.Pair(f"p{i}", "edge", "x",
                          cal.Item(f"landlord duty topic {letters(2 * i)}", "vector_search", False),
                          cal.Item(f"landlord duty topic {letters(2 * i + 1)}", "vector_search", False))
                 for i in range(100)]
        rep = cal.evaluate(FakeClient(lambda q: resp("vector_search", 0.95, 0.03)), pairs=pairs)
        self.assertEqual(rep.n_model_stage, 200)
        self.assertEqual(rep.suggested_threshold, 0.5)
        self.assertFalse(rep.calibrated)

    def test_below_min_reliable_n_never_suggests_even_when_perfect(self):
        rep = cal.evaluate(FakeClient(perfect))
        self.assertLess(rep.n_model_stage, cal.MIN_RELIABLE_N)
        self.assertIsNone(rep.suggested_threshold)
        self.assertIsNone(rep.suggested_choice_threshold)
        self.assertIsNone(rep.suggested_noul_threshold)

    def test_high_abstain_rate_blocks_a_suggestion(self):
        pairs = [cal.Pair(f"p{i}", "edge", "x",
                          cal.Item(f"landlord duty topic {letters(2 * i)}", "vector_search", False),
                          cal.Item(f"landlord duty topic {letters(2 * i + 1)}", "vector_search", False))
                 for i in range(100)]
        seen = {"n": 0}

        def mostly_down(q):
            seen["n"] += 1
            if seen["n"] % 3:
                raise so.SystemOneError("down")
            return resp("vector_search", 0.95, 0.03)
        rep = cal.evaluate(FakeClient(mostly_down), pairs=pairs)
        self.assertGreater(rep.abstain_rate, cal.MAX_ABSTAIN_RATE)
        self.assertIsNone(rep.suggested_threshold)
        self.assertTrue(any("abstain" in n for n in rep.notes))


if __name__ == "__main__":
    unittest.main()
