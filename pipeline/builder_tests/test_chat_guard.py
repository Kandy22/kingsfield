"""Chat-route verification: finalizeHeldOutput (withhold-whole on any veto), keepalive, sent-text check.

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
    "veto_withholds_whole_reply_with_the_veto_message_sent_and_saved",
    "veto_message_is_distinct_from_the_generic_withheld_message",
    "veto_in_the_hidden_citations_block_withholds",
    "veto_withholds_the_whole_reply_including_short_forms",
    "visible_verify_error_or_throw_withholds_with_the_generic_message",
    "pending_status_counts_as_vetoed",
    "doc_read_with_a_flagged_filename_is_dropped_sent_and_saved",
    "doc_read_with_a_clean_filename_passes_unchanged",
    "doc_read_is_dropped_when_withholding",
    "cite_only_in_the_sent_text_withholds",
    "blank_full_text_with_non_blank_sent_text_withholds",
    "sent_text_that_is_not_the_full_text_withholds_even_when_every_check_is_clean",
    "normal_stream_with_a_trailing_citations_block_passes",
    "multi_iteration_stream_with_hidden_blocks_passes",
    "visible_matches_full_text_alignment",
    "alignment_work_budget_is_bounded_and_exhaustion_is_never_a_match",
    "honest_long_replies_stay_far_under_the_work_budget",
    "veto_withhold_always_sends_and_saves_hasvetoes_true",
    "error_result_withholds_and_leaks_no_model_text",
    "throw_withholds",
    "draft_placeholder_veto_withholds",
    "conditional_and_verified_replay_unchanged",
    "unmatched_entries_dropped_from_citations_and_case_citation",
    "saved_events_equal_what_was_sent",
    "keepalive_pings_each_interval_and_stops_on_flush",
    "keepalive_stops_on_abort_error_and_close_paths",
    "vetoed_and_pending_verdicts_have_no_citation_in_client_event",
    "note_containing_the_cite_is_scrubbed",
    "verified_and_conditional_verdicts_are_unchanged_by_client_safe",
    "error_event_survives_in_replay_with_generic_message",
    "error_event_survives_in_veto_withhold_with_generic_message",
    "error_event_survives_in_withhold_with_generic_message",
    "client_safe_replaces_any_error_with_generic_text",
    "every_verification_failure_path_sends_and_saves_only_the_generic_error",
    "saved_annotations_hold_exactly_one_verification_record_in_replay_veto_withhold",
    "vetoed_verdict_in_the_saved_record_has_empty_citation_and_scrubbed_notes",
    "raw_verification_error_goes_to_the_logger_once_per_failure",
    "failed_reply_record_aborted_is_one_fixed_content_event_and_sends_nothing",
    "failed_reply_record_failed_saves_fixed_strings_and_sends_generic_error_then_done",
    "failed_reply_record_takes_no_input_and_carries_only_the_fixed_strings",
    "failed_reply_record_returns_fresh_objects",
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
                # The saved annotations already carry the one client-safe verification record,
                # so the route saves them as they are (never null on the success path).
                self.assertIn("annotations: finalized.savedAnnotations,", src)
                self.assertNotIn("finalized.savedAnnotations.length", src)
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

    def test_catch_saves_only_the_fixed_marker(self):
        """W4: nothing the model wrote and no raw error text reaches chat_messages or the browser from the catch."""
        for path in ROUTES:
            src = path.read_text(encoding="utf-8")
            with self.subTest(route=path.name):
                # The stream handler's catch is the last one (chat.ts has an earlier one in generate-title).
                i = src.rindex("} catch (err) {")
                j = src.index("} finally {")
                self.assertLess(i, j)
                raw_catch = src[i:j]
                # Comments may name what is dropped; only code counts.
                catch = "\n".join(l for l in raw_catch.splitlines() if not l.strip().startswith("//"))

                for banned in ("err.fullText", "err.events", "fullText", "events", "annotations: partial",
                               "buildCancelledAssistantMessage", "stripTransientAssistantEvents",
                               "extractAnnotations", "safeErrorMessage", "AssistantStreamError",
                               "finalized", "buffered", "docIndex", "message"):
                    self.assertIsNone(
                        re.search(rf"(?<![\w.]){re.escape(banned)}(?!\w)", catch), banned)
                for banned in ("err.fullText", "err.events", "err.message", "err.stack"):
                    self.assertNotIn(banned, catch, banned)
                # And none of those are even imported any more.
                for banned in ("buildCancelledAssistantMessage", "stripTransientAssistantEvents",
                               "extractAnnotations", "safeErrorMessage", "AssistantStreamError"):
                    self.assertNotIn(banned, src, banned)

                # One helper for both abort and error, chosen by isAbortError.
                self.assertIn("    failedReplyRecord,\n", src)  # imported
                self.assertEqual(catch.count("failedReplyRecord("), 1)
                self.assertIn('failedReplyRecord(aborted ? "aborted" : "failed")', catch)
                self.assertIn("const aborted = isAbortError(err);", catch)
                # What is saved is exactly the helper's output.
                self.assertIn("content: failedReply.events,", catch)
                self.assertIn("annotations: failedReply.annotations,", catch)
                # What is sent is exactly the helper's lines (empty for an abort), and nothing else.
                self.assertIn("for (const line of failedReply.sseLines) write(line);", catch)
                self.assertEqual(catch.count("write("), 1, "the catch writes only the helper's lines")
                self.assertNotIn("data:", catch)
                self.assertNotIn("JSON.stringify", catch)
                self.assertNotIn(".flush(", catch)
                self.assertNotIn("takeHeld", catch)

                # The raw error goes only to the server log: every use of `err` is isAbortError(err) or safeErrorLog(err).
                for m in re.finditer(r"\berr\b", catch):
                    before = catch[: m.start()]
                    if before.endswith("catch ("):
                        continue
                    self.assertTrue(
                        before.endswith("isAbortError(") or before.endswith("safeErrorLog("),
                        f"err used outside isAbortError/safeErrorLog: ...{catch[max(0, m.start() - 40): m.end() + 10]!r}",
                    )
                self.assertGreaterEqual(catch.count("safeErrorLog("), 2)
                # Save failures are logged through safeErrorLog too, never the raw object.
                self.assertNotRegex(catch, r"console\.error\([^;]*,\s*(saveError|saveErr)\s*\)")

    def test_catch_does_not_double_save_after_the_verified_reply(self):
        """W4: once the finalized reply is stored the catch only logs; a failed finalized save falls through to the marker."""
        for path in ROUTES:
            src = path.read_text(encoding="utf-8")
            with self.subTest(route=path.name):
                self.assertEqual(src.count("let replySaved = false;"), 1)
                self.assertEqual(src.count("replySaved = true;"), 1)
                insert = src.index("content: finalized.savedEvents.length ? finalized.savedEvents : null")
                err_check = src.index("if (replySaveError) {", insert)
                throw = src.index("throw new Error", err_check)
                flag = src.index("replySaved = true;")
                send = src.index("for (const line of finalized.linesToSend) write(line);")
                # Save, check the save result (a failed save throws into the catch), only then mark saved and send.
                self.assertLess(insert, err_check)
                self.assertLess(err_check, throw)
                self.assertLess(throw, flag)
                self.assertLess(flag, send)
                self.assertIn("const { error: replySaveError }", src)
                i = src.rindex("} catch (err) {")
                j = src.index("} finally {")
                catch = src[i:j]
                guard = catch.index("if (replySaved) {")
                ret = catch.index("return;", guard)
                marker = catch.index("failedReplyRecord(")
                # The guard comes first, only logs, and returns before anything is saved or sent.
                self.assertLess(guard, ret)
                self.assertLess(ret, marker)
                body = catch[guard:ret]
                self.assertIn("safeErrorLog(err)", body)
                self.assertNotIn("insert(", body)
                self.assertNotIn("write(", body)
                # The title update runs after the flag is set, so a failure there lands in the guard.
                self.assertLess(flag, src.index(".update({ title:", flag))
                # No insert of an assistant row on the success path other than the finalized one.
                try_body = src[src.index("    try {\n        write(`data: ${JSON.stringify({ type: \"chat_id\""):i]
                self.assertEqual(try_body.count('role: "assistant"'), 1)


if __name__ == "__main__":
    unittest.main()
