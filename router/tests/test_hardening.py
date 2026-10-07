"""Round 2 hardening: response validation, gate1 pre-check, mass floor,
tokenization boundary, and hang / circuit-breaker behaviour. Stub model only.
"""
import math
import os
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from router import jev_cpu_inference as jev  # noqa: E402
from router import system_one_client as so  # noqa: E402
from router.jev_cpu_inference import (  # noqa: E402
    InferenceTimeout, JevCPURouter, LocalLlamaClient, ModelUnavailable, ScoringError,
)
from router.system_one_client import route  # noqa: E402
from router.tests import stub_llama as st  # noqa: E402

_PATCHES = []


def setUpModule():
    class RealModelLoadForbidden(BaseException):
        pass

    def forbid(*a, **k):
        raise RealModelLoadForbidden("hardening tests must never load a real model")

    for p in (mock.patch.object(jev, "_import_llama_class", forbid),
              mock.patch.dict(os.environ, {}, clear=False)):
        p.start()
        _PATCHES.append(p)
    os.environ.pop("VON_BASE_URL", None)
    os.environ.pop("JEV_MODEL_PATH", None)
    jev.reset_shared_router()


def tearDownModule():
    jev.reset_shared_router()
    for p in reversed(_PATCHES):
        p.stop()


class Fixed:
    def __init__(self, reply=None):
        self.reply, self.calls = reply, []

    def query(self, q):
        self.calls.append(q)
        return self.reply


def resp(answer="vector_search", conf=0.95, raw=0.02, score=0.95, options=so.ROUTES):
    return so.SystemOneResponse(
        so.Choice(so.CHOICE_QUESTION, options, answer, conf),
        so.Noul(so.NOUL_QUESTION, raw, "low"),
        so.Score(so.SCORE_QUESTION, score))


def assert_fb(tc, d):
    tc.assertEqual((d.route, d.fallback), ("direct_db", True))
    tc.assertTrue(d.requires_gate1)


class ResponseValidation(unittest.TestCase):
    """Fix 1 and 2: every SystemOneResponse object is validated by route()."""

    BAD_NUMBERS = (float("nan"), float("inf"), float("-inf"), True, False, "0.9", None,
                   1.5, -0.1, [0.9], 2)

    def test_each_numeric_field_rejects_non_real_finite_unit_values(self):
        for field in ("conf", "score", "raw"):
            for bad in self.BAD_NUMBERS:
                with self.subTest(field=field, value=bad):
                    assert_fb(self, route("landlord duty", Fixed(resp(**{field: bad}))))

    def test_nan_in_one_field_cannot_hide_behind_min(self):
        # min(0.95, nan) used to pass the threshold comparison.
        assert_fb(self, route("landlord duty", Fixed(resp(conf=0.95, score=float("nan")))))
        assert_fb(self, route("landlord duty", Fixed(resp(conf=float("nan"), score=0.95))))

    def test_boundary_values_zero_and_one_are_accepted_as_numbers(self):
        d = route("landlord duty", Fixed(resp(conf=1.0, score=1, raw=0.0)))
        self.assertEqual((d.route, d.fallback), ("vector_search", False))

    def test_options_must_be_exactly_the_allowed_set(self):
        R = list(so.ROUTES)
        bad = [
            R[:2], R[:1], [], R + ["llm_search"], R + [R[0]], [R[0], R[0], R[1]],
            [R[0], R[1], "direct_db "], ["boolean", "vector", "direct"],
            "boolean_search,vector_search,direct_db", None, 3,
            [R[0], R[1], 5], {"boolean_search", "vector_search", "direct_db"},
        ]
        for opts in bad:
            with self.subTest(options=opts):
                assert_fb(self, route("landlord duty", Fixed(resp(options=opts))))

    def test_option_order_and_container_type_do_not_matter(self):
        for opts in (so.ROUTES, list(so.ROUTES), tuple(reversed(so.ROUTES))):
            with self.subTest(options=opts):
                d = route("landlord duty", Fixed(resp(options=opts)))
                self.assertEqual((d.route, d.fallback), ("vector_search", False))

    def test_wrong_part_types_fall_back(self):
        r = resp()
        for parts in ((None, r.noul, r.score), (r.choice, "x", r.score), (r.choice, r.noul, 0.9)):
            with self.subTest(parts=[type(p).__name__ for p in parts]):
                assert_fb(self, route("landlord duty", Fixed(so.SystemOneResponse(*parts))))

    def test_invalid_threshold_falls_back(self):
        for t in (float("nan"), 0, -1, 1.5, None, True, "0.8"):
            with self.subTest(threshold=t):
                assert_fb(self, route("landlord duty", Fixed(resp()), threshold=t))


class CalibratedIsForced(unittest.TestCase):
    """F6: RouteDecision.calibrated is always CALIBRATION_RECORDED (False)."""

    def claiming(self, **kw):
        r = resp(**kw)
        return so.SystemOneResponse(r.choice, r.noul, r.score, calibrated=True)

    def test_client_claim_is_ignored_on_every_route_path(self):
        cases = [
            self.claiming(),                                   # model route
            self.claiming(raw=0.97),                           # noul_citation
            self.claiming(conf=0.5),                           # below_threshold
            self.claiming(raw=0.5),                            # noul_uncertain
            self.claiming(conf=float("nan")),                  # invalid response
        ]
        for r in cases:
            self.assertTrue(r.calibrated)
            d = route("landlord duty", Fixed(r))
            self.assertIs(d.calibrated, False)
        self.assertIs(route("房东", Fixed(cases[0])).calibrated, False)
        self.assertIs(route("Pull 98 So. 2d 1021", Fixed(cases[0])).calibrated, False)

    def test_single_documented_switch_stays_false(self):
        self.assertIs(so.CALIBRATION_RECORDED, False)
        with open(so.__file__, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("recorded measurement", src)
        self.assertIn("decisions.md", src)
        self.assertFalse("bool(resp.calibrated)" in src, "client claim must not be copied")

    def test_the_constant_is_the_only_source(self):
        with mock.patch.object(so, "CALIBRATION_RECORDED", True):
            # _fallback and route() read the constant at call time; nothing else sets it.
            self.assertIs(route("landlord duty", Fixed(resp())).calibrated, True)
        self.assertIs(route("landlord duty", Fixed(resp())).calibrated, False)

    def test_decision_is_immutable(self):
        d = route("landlord duty", Fixed(self.claiming()))
        with self.assertRaises(Exception):
            d.calibrated = True


class DecisionCause(unittest.TestCase):
    def test_causes(self):
        self.assertEqual(route("landlord duty", Fixed(resp())).cause, "model")
        self.assertEqual(route("landlord duty", Fixed(resp(raw=0.97))).cause, "noul_citation")
        self.assertEqual(route("landlord duty", Fixed(resp(conf=0.5))).cause, "below_threshold")
        self.assertEqual(route("landlord duty", Fixed(resp(raw=0.5))).cause, "noul_uncertain")
        self.assertEqual(route("landlord duty", Fixed(resp(conf=float("nan")))).cause, "invalid_response")
        self.assertEqual(route("房东", Fixed(resp())).cause, "english_gate")
        self.assertEqual(route("landlord duty", Fixed(resp()), threshold=0).cause, "invalid_threshold")
        self.assertEqual(route("Pull 98 So. 2d 1021", Fixed(resp())).cause, "citation_precheck")
        with mock.patch("pipeline.gate1.check_text", side_effect=RuntimeError("x")):
            self.assertEqual(route("landlord duty", Fixed(resp())).cause, "precheck_error")

        class Boom:
            def query(self, q):
                raise RuntimeError("x")
        self.assertEqual(route("landlord duty", Boom()).cause, "error")

    def test_local_exceptions_carry_their_cause(self):
        self.assertEqual(jev.MassFloorError.cause, "mass_floor")
        self.assertEqual(jev.InferenceTimeout.cause, "timeout")
        self.assertEqual(jev.CircuitOpen.cause, "breaker")
        self.assertEqual(jev.ModelUnavailable.cause, "unavailable")
        self.assertTrue(issubclass(jev.CircuitOpen, jev.ModelUnavailable))
        self.assertTrue(issubclass(jev.MassFloorError, jev.ScoringError))


class CitationPrecheck(unittest.TestCase):
    """Fix 6: gate1.check_text runs before any client or model is consulted."""

    CITATION_SHAPED = [
        "Pull the opinion at 98 So. 2d 1021 (Fla. 1st DCA 1957)",       # Florida full cite
        "Pull the opinion at 123 So. 3d 456 (Ala. 2013)",               # other state, Southern
        "Pull the opinion at 45 Fla. L. Weekly Fed. D123",              # federal Weekly
        "see 123 So. 3d 456 and Id. at 460",                            # short form
        "She has served 12 So. Fla. counties since 2010",               # gate1 vetoes: unparsed
        "Pull 410 U.S. 113 (1973)",                                     # federal reporter
        "Is 123 So. 3d 456 still good law",                             # no court parenthetical
    ]

    def test_citation_shaped_queries_skip_the_client(self):
        for q in self.CITATION_SHAPED:
            with self.subTest(q=q):
                client = Fixed(resp())
                d = route(q, client)
                self.assertEqual((d.route, d.fallback), ("direct_db", False))
                self.assertIn("pre-check", d.reason)
                self.assertEqual(client.calls, [], "model/client must not be consulted")
                self.assertTrue(d.requires_gate1)
                self.assertIsNone(d.choice)

    def test_clean_query_reaches_the_client(self):
        client = Fixed(resp())
        d = route("when is a landlord liable for a fall on the stairs", client)
        self.assertEqual(d.route, "vector_search")
        self.assertEqual(len(client.calls), 1)

    def test_any_verdict_and_kind_counts(self):
        for verdict in ("pass", "veto", "fall_through", "weird"):
            for kind in ("full", "short", "id", "supra", "unparsed"):
                with self.subTest(verdict=verdict, kind=kind):
                    fake = [SimpleNamespace(verdict=verdict, kind=kind, reason="x")]
                    client = Fixed(resp())
                    with mock.patch("pipeline.gate1.check_text", return_value=fake):
                        d = route("landlord duty", client)
                    self.assertEqual((d.route, d.fallback), ("direct_db", False))
                    self.assertEqual(client.calls, [])

    def test_empty_result_list_means_nothing_citation_shaped(self):
        client = Fixed(resp())
        with mock.patch("pipeline.gate1.check_text", return_value=[]):
            self.assertEqual(route("landlord duty", client).route, "vector_search")

    def test_precheck_errors_fall_back_without_the_client(self):
        for exc in (RuntimeError("boom"), OSError("db"), MemoryError(), ValueError("v")):
            with self.subTest(exc=type(exc).__name__):
                client = Fixed(resp())
                with mock.patch("pipeline.gate1.check_text", side_effect=exc):
                    d = route("landlord duty", client)
                assert_fb(self, d)
                self.assertIn("pre-check failed", d.reason)
                self.assertEqual(client.calls, [])

    def test_gate1_import_failure_falls_back(self):
        client = Fixed(resp())
        with mock.patch.dict(sys.modules, {"pipeline.gate1": None}):
            d = route("landlord duty", client)
        assert_fb(self, d)
        self.assertEqual(client.calls, [])

    def test_reuses_gate1_check_text_not_a_second_parser(self):
        import inspect
        src = inspect.getsource(so.citation_precheck)
        self.assertIn("from pipeline.gate1 import check_text", src)
        self.assertNotIn("re.compile", src)

    def test_precheck_is_lazy(self):
        import subprocess
        code = ("import sys; import router.system_one_client; "
                "assert 'pipeline.gate1' not in sys.modules and 'eyecite' not in sys.modules; print('ok')")
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True,
                             text=True, timeout=30)
        self.assertEqual(out.stdout.strip(), "ok", out.stderr)

    def test_local_model_never_called_for_a_citation(self):
        llm = st.FakeLlama(st.oracle_policy())
        client = LocalLlamaClient(router=JevCPURouter(llm))
        d = route("Pull the opinion at 98 So. 2d 1021", client)
        self.assertEqual((d.route, d.fallback), ("direct_db", False))
        self.assertEqual(llm.tokenize_calls, [])
        self.assertEqual(llm.eval_calls, [])


def make_router(policy, **kw):
    router_kw = {k: kw.pop(k) for k in list(kw) if k in
                 ("timeout", "lock_timeout", "choice_mass_floor", "noul_mass_floor")}
    llm = st.FakeLlama(policy, **kw)
    return JevCPURouter(llm, **router_kw), llm


def pol(choice, noul=None):
    return st.static_policy(choice=choice, noul=noul or {"Yes": [0.03], "No": [0.97]})


CHOICE_OK = st.choice_probs("vector_search")


class MassFloor(unittest.TestCase):
    """Fix 5: the un-normalized mass of the allowed options must clear a floor."""

    # Normalized, vector_search wins with about 0.92, but the model put only
    # about 1e-8 of its probability on any allowed route.
    TINY = {"boolean_search": [1e-9, 0.5], "vector_search": [1e-8, 0.9],
            "direct_db": [1e-9, 0.5, 0.5]}

    def healthy(self, total):
        """Choice distribution whose option mass sums to `total`, vector_search winning."""
        return {"boolean_search": [total * 0.05, 1.0], "vector_search": [total * 0.9, 1.0],
                "direct_db": [total * 0.05, 1.0, 1.0]}

    def test_scale_healthy_masses_pass_and_one_e_minus_seven_vetoes(self):
        for total in (0.5, 0.7, 0.9):
            with self.subTest(total=total):
                router, _ = make_router(pol(self.healthy(total)))
                res = router.choice("landlord duty")
                self.assertAlmostEqual(res.mass, total, places=9)
                self.assertEqual(res.answer, "vector_search")
        for total in (1e-7, 1e-9):
            with self.subTest(total=total):
                router, _ = make_router(pol(self.healthy(total)))
                with self.assertRaises(ScoringError):
                    router.choice("landlord duty")
        self.assertGreater(jev.CHOICE_MASS_FLOOR, 1e-7 * 100)
        self.assertLess(jev.CHOICE_MASS_FLOOR, 0.5 / 10)
        self.assertGreater(jev.NOUL_MASS_FLOOR, 1e-7 * 100)
        self.assertLessEqual(jev.NOUL_MASS_FLOOR, 0.5 / 10)

    def test_noul_scale(self):
        for yes, no, ok in ((0.3, 0.6, True), (0.05, 0.85, True), (5e-8, 5e-8, False)):
            with self.subTest(yes=yes, no=no):
                router, _ = make_router(pol(CHOICE_OK, {"Yes": [yes], "No": [no]}))
                if ok:
                    router.noul("landlord duty")
                else:
                    with self.assertRaises(ScoringError):
                        router.noul("landlord duty")

    def test_low_mass_falls_back_even_though_normalized_confidence_is_high(self):
        router, _ = make_router(pol(self.TINY))
        with self.assertRaises(ScoringError) as cm:
            router.choice("landlord duty")
        self.assertIn("mass", str(cm.exception))
        client = LocalLlamaClient(router=router)
        assert_fb(self, route("landlord duty", client))

    def test_the_floor_is_what_blocked_it(self):
        router, _ = make_router(pol(self.TINY), choice_mass_floor=1e-12)
        res = router.choice("landlord duty")
        self.assertEqual(res.answer, "vector_search")
        self.assertGreater(res.confidence, 0.9)
        self.assertLess(res.mass, 1e-7)

    def test_noul_mass_floor_is_separate_and_stricter(self):
        # 0.03 of mass: passes the Choice floor (0.01), fails the Noul floor (0.05).
        self.assertLess(jev.CHOICE_MASS_FLOOR, 0.03)
        self.assertGreater(jev.NOUL_MASS_FLOOR, 0.03)
        noul_low = {"Yes": [0.02], "No": [0.01]}
        router, _ = make_router(pol(CHOICE_OK, noul_low))
        self.assertEqual(router.choice("landlord duty").answer, "vector_search")
        with self.assertRaises(ScoringError):
            router.noul("landlord duty")
        assert_fb(self, route("landlord duty", LocalLlamaClient(router=router)))

    def test_choice_floor_does_not_borrow_the_noul_result(self):
        router, _ = make_router(pol(self.TINY, {"Yes": [0.02], "No": [0.98]}))
        with self.assertRaises(ScoringError):
            router.choice("landlord duty")
        self.assertAlmostEqual(router.noul("landlord duty").mass, 1.0, places=9)

    def test_healthy_mass_passes_and_is_reported(self):
        router, _ = make_router(pol(CHOICE_OK))
        res = router.choice("landlord duty")
        self.assertGreater(res.mass, jev.CHOICE_MASS_FLOOR)
        self.assertLessEqual(res.mass, 1.0)

    def test_mass_above_one_fails_closed(self):
        # option tokens nest: vector_search = (10,), boolean_search = (10, 11)
        toks = dict(st.OPTION_TOKENS)
        toks["vector_search"] = (10,)

        def policy(kind, flags, prefix):
            if kind == st.KIND_NOUL:
                return {17: 0.03, 18: 0.97} if prefix == () else {0: 1.0}
            if prefix == ():
                return {10: 0.9, 14: 0.05}
            if prefix == (10,):
                return {11: 0.6}
            if prefix == (14,):
                return {15: 0.5}
            if prefix == (14, 15):
                return {16: 0.5}
            return {0: 1.0}
        router, _ = make_router(policy, tokens=toks)
        with self.assertRaises(ScoringError):
            router.choice("landlord duty")

    def test_constants_are_named_documented_placeholders(self):
        self.assertIn("PLACEHOLDER", jev.__doc__)
        self.assertIn("CHOICE_MASS_FLOOR", jev.__doc__)
        self.assertIn("NOUL_MASS_FLOOR", jev.__doc__)
        self.assertGreater(jev.CHOICE_MASS_FLOOR, 0)
        self.assertGreater(jev.NOUL_MASS_FLOOR, 0)
        res = make_router(pol(CHOICE_OK))[0].choice("landlord duty")
        self.assertFalse(res.calibrated)


class TokenizationBoundary(unittest.TestCase):
    """Fix 4: tokenize(prompt + ' ' + opt) == tokenize(prompt) + tokenize(' ' + opt)."""

    def test_merge_on_any_choice_option_falls_back_before_any_eval(self):
        for opt in so.ROUTES:
            with self.subTest(option=opt):
                router, llm = make_router(pol(CHOICE_OK))
                llm.merge_options = {opt}
                with self.assertRaises(ScoringError) as cm:
                    router.choice("landlord duty")
                self.assertIn("boundary", str(cm.exception))
                self.assertEqual(llm.eval_calls, [])
                assert_fb(self, route("landlord duty", LocalLlamaClient(router=router)))

    def test_merge_on_noul_option_falls_back(self):
        for opt in ("Yes", "No"):
            with self.subTest(option=opt):
                router, llm = make_router(pol(CHOICE_OK))
                llm.merge_options = {opt}
                with self.assertRaises(ScoringError):
                    router.noul("landlord duty")

    def test_missing_bos_in_the_joint_tokenization_is_a_mismatch(self):
        class NoBosJoint(st.FakeLlama):
            def tokenize(self, text, add_bos=True, special=False):
                out = super().tokenize(text, add_bos, special)
                if add_bos and out and text.endswith((b" boolean_search", b" vector_search",
                                                      b" direct_db")):
                    return out[1:]
                return out
        llm = NoBosJoint(pol(CHOICE_OK))
        with self.assertRaises(ScoringError):
            JevCPURouter(llm).choice("landlord duty")

    def test_extra_bos_on_the_continuation_is_a_mismatch(self):
        class BosOnContinuation(st.FakeLlama):
            def tokenize(self, text, add_bos=True, special=False):
                out = super().tokenize(text, add_bos, special)
                return [st.BOS] + out if add_bos is False else out
        llm = BosOnContinuation(pol(CHOICE_OK))
        with self.assertRaises(ScoringError):
            JevCPURouter(llm).choice("landlord duty")

    def test_consistent_tokenizer_passes(self):
        router, _ = make_router(pol(CHOICE_OK))
        self.assertEqual(router.choice("landlord duty").answer, "vector_search")


class _Hang:
    """Collects events to release at cleanup so worker threads always finish."""

    def __init__(self, tc):
        self.events = []
        tc.addCleanup(self.release)

    def event(self):
        e = threading.Event()
        self.events.append(e)
        return e

    def release(self):
        for e in self.events:
            e.set()


class HangsAndCircuitBreaker(unittest.TestCase):
    """Fix 3."""

    def setUp(self):
        self.hang = _Hang(self)
        jev.reset_shared_router()
        self.addCleanup(jev.reset_shared_router)

    def test_hung_eval_times_out_and_trips_the_breaker(self):
        router, llm = make_router(pol(CHOICE_OK), timeout=0.3)
        llm.hang = self.hang.event()
        t0 = time.monotonic()
        with self.assertRaises(InferenceTimeout):
            router.choice("landlord duty")
        self.assertLess(time.monotonic() - t0, 3.0)
        self.assertIsNotNone(router.unhealthy)

    def test_after_a_timeout_the_hung_instance_is_never_reused(self):
        router, llm = make_router(pol(CHOICE_OK), timeout=0.3)
        llm.hang = self.hang.event()
        with self.assertRaises(InferenceTimeout):
            router.choice("landlord duty")
        llm.hang.set()                      # even once it "recovers" it is not reused
        time.sleep(0.3)                     # let the orphaned worker finish touching the stub
        calls = (len(llm.tokenize_calls), len(llm.eval_calls))
        for call in (lambda: router.choice("landlord duty"),
                     lambda: router.noul("landlord duty")):
            t0 = time.monotonic()
            with self.assertRaises(ModelUnavailable):
                call()
            self.assertLess(time.monotonic() - t0, 0.2, "open breaker must fail immediately")
        self.assertEqual((len(llm.tokenize_calls), len(llm.eval_calls)), calls)

    def test_no_lock_is_left_held_after_a_timeout(self):
        router, llm = make_router(pol(CHOICE_OK), timeout=0.3)
        llm.hang = self.hang.event()
        with self.assertRaises(InferenceTimeout):
            router.choice("landlord duty")
        self.assertTrue(router._lock.acquire(blocking=False))
        router._lock.release()

    def test_route_returns_direct_db_quickly_and_keeps_doing_so(self):
        router, llm = make_router(pol(CHOICE_OK), timeout=0.3)
        llm.hang = self.hang.event()
        client = LocalLlamaClient(router=router)
        t0 = time.monotonic()
        first = route("landlord duty", client)
        second = route("landlord duty", client)
        self.assertLess(time.monotonic() - t0, 3.0)
        assert_fb(self, first)
        assert_fb(self, second)
        self.assertIn("circuit open", second.reason)

    def test_lock_acquire_times_out_instead_of_wedging(self):
        router, _ = make_router(pol(CHOICE_OK), lock_timeout=0.1)
        self.assertTrue(router._lock.acquire(timeout=1))
        try:
            t0 = time.monotonic()
            with self.assertRaises(ScoringError) as cm:
                router.choice("landlord duty")
            self.assertLess(time.monotonic() - t0, 2.0)
            self.assertIn("lock", str(cm.exception))
        finally:
            router._lock.release()
        self.assertIsNone(router.unhealthy, "a contended lock alone is not a hang")
        self.assertEqual(router.choice("landlord duty").answer, "vector_search")

    def test_soft_deadline_also_trips_the_breaker(self):
        router, _ = make_router(pol(CHOICE_OK))
        st.wait_for_workers()
        with mock.patch.object(jev.time, "monotonic", st.scripted_clock([0.0, 1000.0])):
            with self.assertRaises(InferenceTimeout):
                router.choice("landlord duty")
        self.assertIsNotNone(router.unhealthy)
        with self.assertRaises(ModelUnavailable):
            router.choice("landlord duty")

    def test_worker_exception_is_carried_back_not_lost(self):
        router, llm = make_router(pol(CHOICE_OK))
        llm.raise_in_eval = RuntimeError("boom")
        with self.assertRaises(RuntimeError):
            router.choice("landlord duty")
        self.assertIsNone(router.unhealthy, "an exception is not a hang")


class SharedSingletonHangs(unittest.TestCase):
    def setUp(self):
        self.hang = _Hang(self)
        jev.reset_shared_router()
        self.addCleanup(jev.reset_shared_router)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.model = os.path.join(self.tmp.name, "fake.gguf")
        with open(self.model, "wb") as fh:
            fh.write(b"not a real model")
        self.env = mock.patch.dict(os.environ, {"JEV_MODEL_PATH": self.model})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.instances = []

    def stub_class(self, hang_load=None, hang_eval_first_instance=False):
        outer = self

        class Stub(st.FakeLlama):
            def __init__(inner, **kw):
                outer.instances.append(inner)
                if hang_load is not None and len(outer.instances) == 1:
                    hang_load.wait(10)
                super().__init__(st.oracle_policy(), n_ctx=kw["n_ctx"])
                if hang_eval_first_instance and len(outer.instances) == 1:
                    inner.hang = outer.hang.event()
        return Stub

    def test_hung_inference_opens_the_process_breaker_until_reset(self):
        with mock.patch.object(jev, "LOCAL_INFERENCE_TIMEOUT_S", 0.3), \
                mock.patch.object(jev, "_import_llama_class",
                                  return_value=self.stub_class(hang_eval_first_instance=True)):
            d1 = route("landlord duty")
            self.assertEqual(len(self.instances), 1)
            assert_fb(self, d1)
            first = jev._SHARED
            self.assertIsNotNone(first.unhealthy)
            for _ in range(3):
                assert_fb(self, route("landlord duty"))
            self.assertEqual(len(self.instances), 1, "no new load and no reuse while open")
            with self.assertRaises(ModelUnavailable):
                jev.get_shared_router(self.model)
            jev.reset_shared_router()
            d2 = route("landlord duty")
            self.assertEqual((d2.route, d2.fallback), ("vector_search", False))
            self.assertEqual(len(self.instances), 2)
            self.assertIsNot(jev._SHARED.llm, first.llm, "the hung instance is never reused")

    def test_hung_load_times_out_and_stays_direct_db(self):
        release = self.hang.event()
        with mock.patch.object(jev, "LOCAL_LOAD_TIMEOUT_S", 0.3), \
                mock.patch.object(jev, "_import_llama_class",
                                  return_value=self.stub_class(hang_load=release)):
            t0 = time.monotonic()
            d1 = route("landlord duty")
            self.assertLess(time.monotonic() - t0, 3.0)
            assert_fb(self, d1)
            self.assertIn("timed out", d1.reason)
            self.assertFalse(jev._LOAD_LOCK.locked(), "load lock must not stay held")
            d2 = route("landlord duty")
            assert_fb(self, d2)
            self.assertIn("circuit open", d2.reason)
            self.assertEqual(len(self.instances), 1, "no second load while the breaker is open")
            release.set()                   # the abandoned load finishes; its result is discarded
            time.sleep(0.1)
            self.assertIsNone(jev._SHARED)
            assert_fb(self, route("landlord duty"))
            jev.reset_shared_router()
            d3 = route("landlord duty")
            self.assertEqual((d3.route, d3.fallback), ("vector_search", False))
            self.assertEqual(len(self.instances), 2)

    def test_concurrent_callers_during_a_hung_load_do_not_wedge(self):
        release = self.hang.event()
        results = []
        with mock.patch.object(jev, "LOCAL_LOAD_TIMEOUT_S", 0.4), \
                mock.patch.object(jev, "_import_llama_class",
                                  return_value=self.stub_class(hang_load=release)):
            ts = [threading.Thread(target=lambda: results.append(route("landlord duty")))
                  for _ in range(4)]
            t0 = time.monotonic()
            for t in ts:
                t.start()
            for t in ts:
                t.join(10)
            self.assertLess(time.monotonic() - t0, 5.0)
        self.assertEqual(len(results), 4)
        for d in results:
            assert_fb(self, d)
        self.assertEqual(len(self.instances), 1)


if __name__ == "__main__":
    unittest.main()
