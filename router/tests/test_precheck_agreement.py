"""Labels in the calibration set must agree with the deterministic pre-check.

Every non-gated item that route()'s pre-check (system_one_client.citation_precheck,
which wraps pipeline.gate1.check_text) flags is labeled citation_present=True and
choice_label="direct_db", exactly as production routes it; and every item labeled
citation_present is flagged. Runs the REAL pre-check. No model is involved.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from router import calibration as cal  # noqa: E402
from router import system_one_client as so  # noqa: E402


class LabelsAgreeWithPrecheck(unittest.TestCase):
    def test_flagged_iff_labeled_citation_and_direct_db(self):
        bad = []
        for p in cal.CONTRASTIVE_PAIRS:
            for side, item in (("a", p.a), ("b", p.b)):
                if item.gate:
                    continue
                flagged = so.citation_precheck(item.text) is not None
                if flagged and not (item.citation_present and item.choice_label == "direct_db"):
                    bad.append((p.pair_id + side, "flagged but labeled otherwise", item.text))
                if not flagged and item.citation_present:
                    bad.append((p.pair_id + side, "labeled citation_present but not flagged", item.text))
                if not flagged and item.final_route == "direct_db" and not (
                        item.choice_label == "direct_db"):
                    bad.append((p.pair_id + side, "final route direct_db without a label", item.text))
        self.assertEqual(bad, [], "\n".join(map(str, bad)))

    def test_every_item_text_is_unique(self):
        texts = [i.text for i in cal.all_items()]
        dups = sorted({t for t in texts if texts.count(t) > 1})
        self.assertEqual(dups, [], "duplicate item texts double-count toward MIN_RELIABLE_N")

    def test_gated_items_are_rejected_by_the_english_gate(self):
        for item in cal.all_items():
            if item.gate:
                self.assertFalse(so._is_english_scriptable(item.text), item.text)

    def test_pair_flips_survive_the_precheck(self):
        # Under shipped routing, route and citation pairs still flip the final route
        # (a citation pair whose plain member is already direct_db flips Noul only).
        for p in cal.CONTRASTIVE_PAIRS:
            with self.subTest(pair=p.pair_id):
                if p.kind in ("route", "surface"):
                    self.assertNotEqual(p.a.final_route, p.b.final_route)
                elif p.kind == "citation":
                    self.assertNotEqual(p.a.citation_present, p.b.citation_present)
                    if "direct_db" not in (p.a.choice_label, p.b.choice_label):
                        self.assertNotEqual(p.a.final_route, p.b.final_route)
                else:
                    self.assertEqual(p.a.final_route, p.b.final_route)

    def test_evaluate_reports_no_label_mismatch_with_a_perfect_stub(self):
        by_text = {i.text: i for i in cal.all_items()}

        class Perfect:
            def query(self, q):
                it = by_text[q]
                return so.SystemOneResponse(
                    so.Choice(so.CHOICE_QUESTION, so.ROUTES, it.choice_label, 0.95, 0.9),
                    so.Noul(so.NOUL_QUESTION, 0.03, "low", 0.9),
                    so.Score(so.SCORE_QUESTION, 0.95))
        rep = cal.evaluate(Perfect())
        self.assertEqual(rep.label_mismatches, [])
        self.assertEqual(rep.route_accuracy, 1.0)


if __name__ == "__main__":
    unittest.main()
