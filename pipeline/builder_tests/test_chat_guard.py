"""Chat-route verification (Step 1b): finalizeHeldOutput, redaction, keepalive.

No TS test runner exists, so this runs chat_guard_cases.ts once under backend's tsx and turns each
named case into a subTest. The cases use stub verifiers only (no Supabase, CourtListener, LLM or
Python gate). A second group statically checks the route wiring, since the routes themselves cannot
be run without Supabase.
"""

import json
import re
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TSX = REPO_ROOT / "backend" / "node_modules" / ".bin" / "tsx"
CASES = REPO_ROOT / "pipeline" / "builder_tests" / "chat_guard_cases.ts"
ROUTES = [
    REPO_ROOT / "backend" / "src" / "routes" / "chat.ts",
    REPO_ROOT / "backend" / "src" / "routes" / "projectChat.ts",
]

EXPECTED_CASES = {
    "citation_split_across_deltas_is_redacted",
    "short_cite_after_removed_authority_withholds_via_reverify",
    "error_result_withholds_and_leaks_no_model_text",
    "throw_withholds",
    "draft_placeholder_veto_withholds",
    "conditional_and_verified_replay_unchanged",
    "vetoed_and_unmatched_entries_dropped_from_citations_and_case_citation",
    "saved_events_equal_what_was_sent",
    "keepalive_pings_each_interval_and_stops_on_flush",
    "keepalive_stops_on_abort_error_and_close_paths",
    "vetoed_and_pending_verdicts_have_no_citation_in_client_event",
    "note_containing_the_cite_is_scrubbed",
    "verified_and_conditional_verdicts_are_unchanged_by_client_safe",
    "error_event_survives_in_replay_with_generic_message",
    "error_event_survives_in_redact_with_generic_message",
    "error_event_survives_in_withhold_with_generic_message",
}


class GuardCases(unittest.TestCase):
    report = None

    @classmethod
    def setUpClass(cls):
        if not TSX.exists():
            raise unittest.SkipTest(f"tsx missing at {TSX}; report it, do not work around it")
        p = subprocess.run([str(TSX), str(CASES)], capture_output=True, text=True,
                           cwd=str(REPO_ROOT), timeout=120)
        if p.returncode != 0:
            raise AssertionError(f"tsx failed ({p.returncode}):\n{p.stderr[-3000:]}")
        cls.report = json.loads(p.stdout)

    def test_required_cases_ran(self):
        self.assertTrue(EXPECTED_CASES <= set(self.report), EXPECTED_CASES - set(self.report))
        self.assertGreaterEqual(len(self.report), 30, sorted(self.report))

    def test_every_case_passes(self):
        for name, failure in sorted(self.report.items()):
            with self.subTest(case=name):
                self.assertIsNone(failure, failure)


class RouteWiring(unittest.TestCase):
    """Both routes: buffered output goes through finalizeHeldOutput and the keepalive is stopped everywhere."""

    def test_routes(self):
        for path in ROUTES:
            src = path.read_text(encoding="utf-8")
            with self.subTest(route=path.name):
                self.assertNotIn("buffered.flush()", src, "held output must only leave via finalizeHeldOutput")
                self.assertIn("buffered.takeHeld()", src)
                self.assertEqual(src.count("await finalizeHeldOutput("), 1)
                self.assertEqual(src.count("startSseKeepalive(write)"), 1)
                # Persistence uses the finalized (sent) version, never the raw runLLMStream output.
                self.assertIn("content: finalized.savedEvents.length ? finalized.savedEvents : null", src)
                self.assertIn("finalized.savedAnnotations", src)
                # The verification event is built from the client-safe copy, never the raw gate result.
                self.assertIn("= finalized.verification;", src)
                self.assertNotIn("verifyDraftForSse(fullText", src)
                self.assertNotIn("const persistedEvents = stripTransientAssistantEvents(events);\n        await db.from", src)
                # stop() in the close handler, before the flush, in the catch block and in finally.
                close = re.search(r'res\.on\("close", \(\) => \{(.*?)\n    \}\);', src, re.S)
                self.assertIsNotNone(close)
                self.assertIn("keepalive.stop()", close.group(1))
                self.assertRegex(src, r"\} catch \(err\) \{\n\s+keepalive\.stop\(\);")
                self.assertRegex(src, r"\} finally \{\n\s+keepalive\.stop\(\);")
                stop_before_send = src.index("keepalive.stop();\n        for (const line of finalized.linesToSend)")
                self.assertLess(src.index("await finalizeHeldOutput("), stop_before_send)


if __name__ == "__main__":
    unittest.main()
