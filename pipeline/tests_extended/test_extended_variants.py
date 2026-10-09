"""Extended tier: redundant variants moved out of pipeline/tests so the signoff tier fits under 200 s
(chat-route-verify tier split). Bodies are byte-for-byte the originals; nothing is weakened or deleted.

Run on its own:  ~/.venv-cascade/bin/python -m unittest discover --durations 30 pipeline/tests_extended -v

Shared helpers are imported from pipeline/tests (gate1_fixture, draft_harness, the original test modules), never
copied, so a change to a helper changes both tiers. The original classes are borrowed by attribute, not subclassed,
so none of their remaining tests run again here.

Each moved test, the attack class it belongs to, and the tests of that class that stay in pipeline/tests:

  FabricatedCitationsExtended.test_supreme_court_record_cited_as_a_dca_veto            (9.5 s)
  FabricatedCitationsExtended.test_valid_dca_cite_passes_under_every_dca_form_...      (2.1 s)
      class 1/2: Florida-court mismatch and court-form variants of a Florida cite.
      Stay: FabricatedCitations.test_dca_record_cited_as_supreme_court_veto, test_court_mismatch_with_pin_or_wrong_caption_still_veto
      (a Florida Supreme Court record cited as a DCA), test_fabricated_under_every_florida_court_form_veto,
      test_valid_supreme_court_cite_passes, test_controls_pass_on_every_loaded_florida_series,
      CaptionMismatch.test_correct_caption_passes_control (a DCA record cited under Fla. 1st DCA passes),
      FloridaScope.test_rule_9_800_florida_court_forms_do_not_escape_scope.
  ObfuscatedCitationsExtended.test_valid_cite_variants_never_fall_through_or_pass_wrong_record   (4.9 s)
      class 1: OCR artifacts and Unicode homoglyphs of a REAL cite (single-cite entry point).
      Stay: ObfuscatedCitations.test_fabricated_cite_with_homoglyphs_or_invisible_chars_veto, test_pin_cite_obfuscation_cannot_defeat_bounds,
      test_unobfuscated_controls, and the same VALID_VARIANTS through the draft path:
      DraftExtractionHolesInProcess.test_valid_cite_variants_never_fall_through_or_pass_the_wrong_record,
      UnicodeAndHidingThroughTheWrapper.test_damaged_variants_of_a_real_cite_never_fall_through_or_pass_another_record.
  ConcurrencyCapExtended.test_when_every_child_hangs_every_call_still_settles_...      (6.4 s)
  ConcurrencyCapExtended.test_the_cap_is_exact_while_children_are_being_killed_by_the_timeout   (3.4 s)
      class 5/E: bounded child processes (at most 4) and timeouts.
      Stay: ConcurrencyCap.test_never_more_than_the_cap_of_children_alive_and_queued_calls_get_correct_verdicts,
      test_the_queue_wait_bound_sheds_waiting_calls_..., test_a_flood_of_calls_resolves_every_promise_...,
      DraftWrapperSource.test_the_child_slot_is_released_only_once_the_child_has_exited,
      WrapperFailsClosed.test_a_child_that_hangs_is_killed_at_the_timeout_and_vetoed.
  WrapperFailsClosedExtended.test_a_child_that_ignores_sigterm_is_still_killed_and_the_promise_still_settles   (3.4 s)
      class 1/3: wrapper fails closed on a hung child.
      Stay: WrapperFailsClosed.test_a_child_that_hangs_is_killed_at_the_timeout_and_vetoed and test_every_child_failure_yields_exactly_one_veto.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent.parent / "tests"
sys.path.insert(0, str(TESTS))
import gate1_fixture as fx  # noqa: E402
import draft_harness as dh  # noqa: E402
import test_gate1_bypass as gb  # noqa: E402
import test_gate1_draft_mode as dm  # noqa: E402
import test_boundaries_and_schema as bs  # noqa: E402

S = dm.S
FAB = dm.FAB
MAX_CHILDREN = dm.MAX_CHILDREN
_alive_pid = dm._alive_pid
VALID_VARIANTS = gb.VALID_VARIANTS
gb_glyphs = dm.FAB_HOMOGLYPHS


# ───── from test_gate1_bypass.py ─────

class FabricatedCitationsExtended(gb.GateCase):
    DCA_FORMS = gb.FabricatedCitations.DCA_FORMS

    def test_valid_dca_cite_passes_under_every_dca_form_and_any_district_number(self):
        # Control: gate must not simply veto everything. JONES is stored as fladistctapp. CourtListener lumps
        # all DCAs into one id, so a wrong district number must still pass.
        for court in self.DCA_FORMS:
            cite = "Jones v. Acme Insurance Co., 150 So. 3d 500 (%s 2014)" % court
            with self.subTest(court=court):
                self.assertBoth(cite, "pass", cluster=fx.JONES)

    def test_supreme_court_record_cited_as_a_dca_veto(self):
        # court_mismatch: stored fla, parenthetical names a DCA.
        for court in self.DCA_FORMS:
            for cite in ("Smith v. State, 100 So. 3d 200 (%s 2012)" % court,
                         "100 So. 3d 200 (%s 2012)" % court,
                         "Brown v. Florida Power Corp., 400 So. 2d 100 (%s 1981)" % court,
                         "State v. Williams, 150 So. 100 (%s 1933)" % court):
                with self.subTest(cite=cite):
                    self.assertBoth(cite, "veto")


class ObfuscatedCitationsExtended(gb.GateCase):
    def test_valid_cite_variants_never_fall_through_or_pass_wrong_record(self):
        for name, cite in VALID_VARIANTS.items():
            with self.subTest(variant=name):
                self.assertSafe(cite, ok_cluster=fx.SMITH)


# ───── from test_gate1_draft_mode.py ─────

class ConcurrencyCapExtended(unittest.TestCase):
    """Helpers are the original ConcurrencyCap's own (borrowed, not copied)."""
    maxDiff = None

    _env = staticmethod(dm.ConcurrencyCap._env)
    _peak = staticmethod(dm.ConcurrencyCap._peak)
    N_CALLS = dm.ConcurrencyCap.N_CALLS

    def test_when_every_child_hangs_every_call_still_settles_as_exactly_one_veto_within_a_bound(self):
        # Hanging children are killed at textTimeoutMs; calls waiting behind them either run and are killed in turn
        # or hit the queue's overall wait bound. Either way each promise resolves, once, with a single veto.
        code = ('import time\nd = os.environ["KF_ADV_LIVEDIR"]\nos.makedirs(d, exist_ok=True)\n'
                'open(os.path.join(d, str(os.getpid())), "w").close()\ntime.sleep(600)')
        env, marker = dh.make_sabotage(code)
        live = Path(env["KF_ADV_MARKER"]).parent / "live"
        env["KF_ADV_LIVEDIR"] = str(live)
        cases = {"h%02d" % i: S + ". " + FAB + "." for i in range(self.N_CALLS)}
        b = dh.Batch(cases, env_extra=env, timeout=420, concurrent=True, opts_extra={"textTimeoutMs": 3000})
        if not marker.exists():
            self.skipTest("the wrapper does not forward PYTHONPATH to its child; sabotage not applicable")
        self.assertEqual(b.unhandled, [], "unhandled rejection or uncaught exception: %r" % (b.unhandled,))
        reasons = set()
        for name in cases:
            with self.subTest(case=name):
                status, payload = b.raw[name][:2]
                self.assertEqual(status, "ok", "the promise rejected for %s: %s" % (name, payload))
                self.assertEqual(dh.contract_problems(payload), [], dh.compact(payload))
                self.assertEqual(len(payload), 1, "expected exactly one veto: " + dh.compact(payload))
                self.assertEqual(payload[0]["verdict"], "veto", dh.compact(payload))
                reasons.add(payload[0]["reason"])
                self.assertLess(b.ms(name), 120000, "call %s took %d ms to settle" % (name, b.ms(name)))
        # nothing left running: queued calls that never got a slot must not spawn later, killed ones must be gone
        import time
        pids = []
        if live.exists():
            pids = [int(p.name) for p in live.iterdir() if p.name.isdigit()]
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and any(_alive_pid(p) for p in pids):
            time.sleep(0.2)
        alive = [p for p in pids if _alive_pid(p)]
        for p in alive:
            try:
                import os
                import signal
                os.kill(p, signal.SIGKILL)
            except ProcessLookupError:
                pass
        self.assertEqual(alive, [], "orphaned Python children after every promise settled: %r (reasons seen: %r)" % (alive, reasons))

    def test_the_cap_is_exact_while_children_are_being_killed_by_the_timeout(self):
        # Every child hangs and is killed at textTimeoutMs, so slots turn over continuously. A killed child counts as
        # alive to signal 0 until it is reaped, so releasing a slot before the child exits shows up here as cap+1.
        env, marker, live, peaklog = self._env(600)
        cases = {"k%02d" % i: S + ". " + FAB + "." for i in range(self.N_CALLS)}
        b = dh.Batch(cases, env_extra=env, timeout=240, concurrent=True, opts_extra={"textTimeoutMs": 1500})
        if not marker.exists():
            self.skipTest("the wrapper does not forward PYTHONPATH to its child; sabotage not applicable")
        self.assertEqual(b.unhandled, [], "unhandled rejection or uncaught exception: %r" % (b.unhandled,))
        peak = self._peak(peaklog)
        self.assertLessEqual(peak, MAX_CHILDREN,
                             "%d interpreters were alive at once while children were being killed (cap %d)" % (peak, MAX_CHILDREN))
        self.assertGreaterEqual(peak, 2, "no concurrency observed; the test would be vacuous")
        for name in cases:
            status, payload = b.raw[name][:2]
            self.assertEqual(status, "ok", "%s: %s" % (name, payload))
            self.assertEqual(len(payload), 1, dh.compact(payload))
            self.assertEqual(payload[0]["verdict"], "veto", dh.compact(payload))
        import time
        pids = [int(p.name) for p in live.iterdir() if p.name.isdigit()] if live.exists() else []
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and any(_alive_pid(p) for p in pids):
            time.sleep(0.2)
        alive = [p for p in pids if _alive_pid(p)]
        for p in alive:
            import os
            import signal
            try:
                os.kill(p, signal.SIGKILL)
            except ProcessLookupError:
                pass
        self.assertEqual(alive, [], "orphaned children: %r" % alive)


class TsFallbackAndCliExtended(unittest.TestCase):
    CITES = bs.TsFallbackAndCli.CITES

    def test_cli_prints_gate_result_json_matching_check_citation(self):
        db = fx.get_fixture().db
        for cite in self.CITES:
            with self.subTest(cite=cite):
                proc = subprocess.run(
                    [sys.executable, str(fx.REPO / "pipeline" / "gate1.py"), "--db", str(db), "--citation", cite],
                    capture_output=True, text=True, timeout=60, cwd=str(fx.REPO))
                data = json.loads(proc.stdout.strip().splitlines()[-1])
                self.assertEqual(data["verdict"], fx.py_check(cite, db).verdict, proc.stdout + proc.stderr)


class UnicodeAndHidingThroughTheWrapperExtended(unittest.TestCase):
    """The homoglyph variants that left pipeline/tests (main-verify tier split): same body as
    UnicodeAndHidingThroughTheWrapper.test_fabricated_florida_cites_are_vetoed_through_the_wrapper, over the moved variants."""
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.variants = {"glyph_" + n: dm.wrap(gb_glyphs[n]) for n in dm.TS_GLYPHS_MOVED}
        cls.variants.update({"hide_" + n: dm.wrap(dm.FAB_HIDING[n]) for n in dm.TS_HIDING_MOVED})
        cls.batch = dh.Batch(cls.variants) if cls.variants else None

    def test_fabricated_florida_cites_are_vetoed_through_the_wrapper(self):
        for name in self.variants:
            with self.subTest(variant=name):
                r = self.batch.results(name)
                self.assertEqual(dh.contract_problems(r), [], dh.compact(r))
                verdicts = [x["verdict"] for x in r]
                self.assertTrue(r, "SILENTLY DROPPED: %r" % self.variants[name])
                self.assertIn("veto", verdicts, dh.compact(r))
                self.assertNotIn("pass", verdicts, dh.compact(r))
                self.assertNotIn("fall_through", verdicts, dh.compact(r))


class WrapperFailsClosedExtended(unittest.TestCase):
    """Helpers are the original WrapperFailsClosed's own (borrowed, not copied)."""
    maxDiff = None

    HANG_IGNORING_SIGTERM = dm.WrapperFailsClosed.HANG_IGNORING_SIGTERM
    _run_with_pid = dm.WrapperFailsClosed._run_with_pid
    _alive = staticmethod(dm.WrapperFailsClosed._alive)
    _reap = staticmethod(dm.WrapperFailsClosed._reap)
    _assert_child_dead_soon = dm.WrapperFailsClosed._assert_child_dead_soon

    def test_a_child_that_ignores_sigterm_is_still_killed_and_the_promise_still_settles(self):
        # execFile-style timeouts send SIGTERM; a child that ignores it must not leave the promise pending
        # (a caller awaiting it would hang) or the process orphaned.
        r, ms, pid = self._run_with_pid(self.HANG_IGNORING_SIGTERM, {"textTimeoutMs": 3000}, 90)
        self.assertEqual(dh.contract_problems(r), [], dh.compact(r))
        self.assertEqual(len(r), 1, "expected exactly one veto, got " + dh.compact(r))
        self.assertEqual(r[0]["verdict"], "veto", dh.compact(r))
        self.assertLess(ms, 15000, "a 3s timeout took %d ms to settle" % ms)
        self._assert_child_dead_soon(pid, "timeout with SIGTERM ignored")


if __name__ == "__main__":
    unittest.main()
