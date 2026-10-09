"""Gate 1 over the tabular review routes (merge blocker 4, part A): chat and /:reviewId/generate.

tabular_route_cases.ts runs the REAL tabular router (handlers pulled out of the express stack) once under
backend's tsx. Its dependencies (Supabase, runLLMStream, model calls, auth, access) and the Gate 1 verifier
are stubbed, so nothing needs Supabase, CourtListener, a model, the Python gate or the network; every named
case becomes a subTest. A second group checks the wiring in routes/tabular.ts statically (the same checks the
chat routes get in test_chat_guard.py).
"""

import json
import re
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TSX = REPO_ROOT / "backend" / "node_modules" / ".bin" / "tsx"
CASES = REPO_ROOT / "pipeline" / "builder_tests" / "tabular_route_cases.ts"
TABULAR = REPO_ROOT / "backend" / "src" / "routes" / "tabular.ts"

EXPECTED_CASES = {
    "cell_clean_text_passes_unchanged_with_a_clean_record",
    "cell_veto_in_the_summary_replaces_the_whole_cell_with_the_fixed_marker",
    "cell_veto_only_in_the_reasoning_withholds",
    "cell_pending_unknown_and_conditional_statuses",
    "cell_gate_error_throw_and_malformed_result_withhold_with_the_generic_marker",
    "cell_malformed_input_withholds_without_calling_the_gate",
    "cell_flag_is_reduced_to_its_four_values_and_extra_keys_are_dropped",
    "cell_marker_strings_are_fixed_and_distinct",
    "limiter_runs_at_most_max_tasks_in_order_and_survives_failures",
    "tabular_chips_are_kept_only_when_asked_and_only_if_the_quote_is_clean",
    "chat_buffers_model_output_and_uses_the_buffering_writer",
    "chat_vetoed_reply_sends_and_saves_only_the_withheld_message",
    "chat_gate_error_withholds_with_the_generic_message_and_leaks_nothing",
    "chat_clean_reply_is_sent_and_saved_unchanged_with_its_chips_and_a_verification_record",
    "chat_chip_with_a_flagged_quote_is_dropped_but_the_clean_reply_is_sent",
    "chat_abort_saves_only_the_aborted_marker_and_sends_nothing",
    "chat_abort_case_does_not_depend_on_the_wall_clock",
    "chat_error_saves_only_the_failed_marker_and_sends_only_the_generic_error",
    "chat_a_failed_save_of_the_reply_means_the_reply_is_not_sent",
    "chat_reply_is_saved_before_it_is_sent",
    "chat_an_error_after_the_reply_is_saved_saves_no_second_message",
    "generate_one_vetoed_cell_is_replaced_and_the_clean_cell_is_untouched",
    "generate_a_gate_error_on_one_cell_fails_closed_for_that_cell_only",
    "generate_pending_and_reasoning_only_vetoes_withhold_their_cells",
    "generate_gate_calls_are_capped_not_unbounded",
    "generate_a_model_failure_marks_cells_errored_and_sends_no_error_text",
    "generate_a_stream_level_error_sends_only_the_generic_message",
    "generate_a_cell_that_could_not_be_saved_is_not_sent_as_done",
    "generate_cells_not_returned_by_the_model_stay_errored_with_no_content",
    # round 2: limiter timeout, chips (F1), regenerate-cell (F2), GET re-gate (F3), /prompt
    "limiter_timeout_abandons_the_task_frees_the_slot_and_ignores_the_late_result",
    "limiter_timeout_counts_run_time_only_and_leaves_fast_tasks_alone",
    "limiter_timeout_timer_is_cleared_when_the_task_finishes",
    "limiter_timeout_is_not_what_the_gate_returns_for_an_unverifiable_cell",
    "route_limiter_is_one_module_level_limiter_with_a_cap_and_a_timeout",
    "chip_fields_are_built_from_integers_and_the_reviews_own_names",
    "chip_with_a_non_integer_index_or_ref_or_quote_is_dropped_whole",
    "chip_names_never_come_from_a_non_string_or_blank_review_name",
    "chat_a_fabricated_cite_in_chip_metadata_never_reaches_the_client_or_the_row",
    "regenerate_cell_a_vetoed_cell_is_replaced_by_the_fixed_marker_and_the_verdict_recorded",
    "regenerate_cell_a_gate_failure_withholds_with_the_generic_marker_and_leaks_nothing",
    "regenerate_cell_a_clean_cell_is_gated_before_it_is_saved_and_returned_with_its_record",
    "regenerate_cell_a_timed_out_gate_withholds_with_the_generic_marker",
    "regenerate_cell_failures_answer_with_fixed_text_and_save_nothing_unverified",
    "get_review_regates_every_stored_cell_shape_and_returns_markers_for_the_bad_ones",
    "get_review_returns_only_the_cell_columns_the_client_reads",
    "get_review_gates_identical_cell_texts_once_and_caps_gate_calls",
    "get_review_a_hung_gate_call_times_out_and_does_not_block_the_other_cells",
    "get_review_a_late_clean_answer_after_the_timeout_is_ignored",
    "get_review_still_404s_without_access_and_gates_nothing",
    "prompt_a_clean_prompt_is_gated_then_returned_in_the_shape_the_frontend_reads",
    "prompt_a_vetoed_prompt_returns_one_fixed_message_and_no_model_text",
    "prompt_any_gate_failure_returns_the_same_fixed_message",
    "prompt_model_failures_keep_their_existing_fixed_answers_and_leak_nothing",
    # part C: the chat title
    "chat_title_clean_model_title_is_gated_then_saved_and_sent_as_the_same_string",
    "chat_title_vetoed_model_title_falls_back_to_the_users_message_in_the_row_and_the_event",
    "chat_title_pending_unknown_gate_error_throw_malformed_and_timeout_fall_back_without_leaking",
    "chat_title_the_exact_final_string_is_gated_trimmed_and_cut_to_80_characters",
    "chat_title_a_model_failure_or_blank_title_falls_back_to_the_users_message",
    "chat_title_fallback_is_flattened_and_cut_to_120_characters",
    "chat_title_a_failure_after_the_reply_still_only_logs_and_sends_no_model_text",
}


class TabularRouteCases(unittest.TestCase):
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

    def test_every_case_passes(self):
        for name, failure in sorted(self.report.items()):
            with self.subTest(case=name):
                self.assertIsNone(failure, failure)


def _code(src):
    """Source with comments removed (a comment may name what the code must not do)."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", line) for line in src.splitlines())


class RouteWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = TABULAR.read_text(encoding="utf-8")
        cls.code = _code(cls.src)

    def _chat(self):
        i = self.code.index('tabularRouter.post("/:reviewId/chat"')
        j = self.code.index("function parseCellContent(")
        return self.code[i:j]

    def _generate(self):
        i = self.code.index('tabularRouter.post("/:reviewId/generate"')
        j = self.code.index('tabularRouter.get("/:reviewId/chats"')
        return self.code[i:j]

    def test_chat_buffers_and_finalizes(self):
        chat = self._chat()
        m = re.search(r"\brunLLMStream\s*\(", chat)
        self.assertIsNotNone(m)
        self.assertRegex(chat[m.start():], r"\bwrite\s*:\s*buffered\.write\b")
        self.assertNotRegex(chat[m.start(): chat.index("});", m.start())], r"(?<![\w.])write\s*,")
        self.assertNotIn("buffered.flush()", self.code, "held output must only leave via finalizeHeldOutput")
        self.assertNotRegex(self.code, r"\.flush\(\)")
        self.assertEqual(self.code.count("buffered.takeHeld()"), 1)
        self.assertEqual(self.code.count("await finalizeHeldOutput("), 1)
        self.assertEqual(self.code.count("startSseKeepalive(write)"), 1)
        self.assertEqual(self.code.count("createBufferingSseWriter(write)"), 1)
        self.assertLess(chat.index("runLLMStream("), chat.index("await finalizeHeldOutput("))
        self.assertIn("allowTabularCitations: true", chat)
        # Gate 1 runs over the whole reply through the shared verifier.
        self.assertIn("verifyDraftForSse(text", chat)
        self.assertNotIn("verifyDraftForSse(fullText", chat)

    def test_chat_saves_what_it_sends_and_saves_before_sending(self):
        chat = self._chat()
        self.assertIn("finalized.savedEvents.length", chat)
        self.assertIn("annotations: finalized.savedAnnotations,", chat)
        self.assertNotIn("stripTransientAssistantEvents", self.code)
        self.assertNotIn("extractTabularAnnotations(fullText", chat)
        insert = chat.index("finalized.savedEvents.length")
        err = chat.index("if (replySaveError) {", insert)
        throw = chat.index("throw new Error", err)
        flag = chat.index("replySaved = true;")
        send = chat.index("for (const line of finalized.linesToSend) write(line);")
        self.assertLess(insert, err)
        self.assertLess(err, throw)
        self.assertLess(throw, flag)
        self.assertLess(flag, send)
        self.assertIn("= finalized.verification;", chat)
        self.assertEqual(chat[: chat.index("} catch (err) {")].count('role: "assistant"'), 1,
                         "one assistant insert on the success path")

    def test_chat_keepalive_is_stopped_on_every_path(self):
        chat = self._chat()
        close = re.search(r'res\.on\("close", \(\) => \{(.*?)\n    \}\);', chat, re.S)
        self.assertIsNotNone(close)
        self.assertIn("keepalive.stop()", close.group(1))
        self.assertRegex(chat, r"\} catch \(err\) \{\n\s+keepalive\.stop\(\);")
        self.assertRegex(chat, r"\} finally \{\n\s+keepalive\.stop\(\);")
        self.assertLess(chat.index("await finalizeHeldOutput("),
                        chat.index("keepalive.stop();\n        for (const line of finalized.linesToSend)"))

    def test_chat_catch_saves_only_the_fixed_marker(self):
        chat = self._chat()
        i = chat.index("} catch (err) {")
        j = chat.index("} finally {")
        catch = chat[i:j]
        for banned in ("err.fullText", "err.events", "err.message", "err.stack", "fullText", "annotations: partial",
                       "buildCancelledAssistantMessage", "stripTransientAssistantEvents", "safeErrorMessage",
                       "AssistantStreamError", "finalized", "buffered", "extractTabularAnnotations", "message"):
            self.assertIsNone(re.search(rf"(?<![\w.]){re.escape(banned)}(?!\w)", catch), banned)
        for name in ("buildCancelledAssistantMessage", "stripTransientAssistantEvents", "safeErrorMessage",
                     "AssistantStreamError"):
            self.assertNotIn(name, self.src, f"{name} must not be imported or used in tabular.ts")
        self.assertEqual(catch.count("failedReplyRecord("), 1)
        self.assertIn('failedReplyRecord(aborted ? "aborted" : "failed")', catch)
        self.assertIn("content: failedReply.events,", catch)
        self.assertIn("annotations: failedReply.annotations,", catch)
        self.assertIn("for (const line of failedReply.sseLines) write(line);", catch)
        self.assertEqual(catch.count("write("), 1, "the catch writes only the helper's lines")
        self.assertNotIn("data:", catch)
        self.assertNotIn("JSON.stringify", catch)
        # The raw error goes only to the server log: every use of `err` is isAbortError(err) or safeErrorLog(err).
        for m in re.finditer(r"\berr\b", catch):
            before = catch[: m.start()]
            if before.endswith("catch ("):
                continue
            self.assertTrue(before.endswith("isAbortError(") or before.endswith("safeErrorLog("),
                            f"err used outside isAbortError/safeErrorLog: ...{catch[max(0, m.start() - 40): m.end() + 10]!r}")
        # Once the verified reply is saved the catch only logs.
        guard = catch.index("if (replySaved) {")
        ret = catch.index("return;", guard)
        self.assertLess(guard, ret)
        self.assertLess(ret, catch.index("failedReplyRecord("))
        self.assertNotIn("insert(", catch[guard:ret])
        self.assertNotIn("write(", catch[guard:ret])

    def test_generate_gates_every_cell_before_it_is_saved_or_sent(self):
        gen = self._generate()
        m = re.search(r"\bawait\s+queryTabularAllColumns\s*\(", gen)
        self.assertIsNotNone(m)
        tail = gen[m.start():]
        cell_write = tail.find("cell_update")
        self.assertGreater(cell_write, 0)
        # (verifyDraftForSse is wired in by cellGateOptions, which every gate call is given.)
        verify = [i for i in (tail.find("gateCellContent("), tail.find("finalizeHeldOutput(")) if i >= 0]
        self.assertIn("cellGateOptions(db,", tail)
        helper = self.code[self.code.index("function cellGateOptions("):]
        self.assertLess(helper.index("verifyDraftForSse("), helper.index("logError:"))
        self.assertTrue(verify and min(verify) < cell_write, "no Gate 1 call before the first cell_update")
        gate = tail.find("gateCellContent(")
        save = tail.find('.from("tabular_cells")')
        self.assertTrue(0 <= gate < save < cell_write, "gate, then save, then send")
        # What is saved and sent is the gated content, never the model's raw `result`.
        self.assertIn("JSON.stringify(gated.content)", tail)
        self.assertIn("content: gated.content", tail)
        self.assertNotIn("JSON.stringify(result)", tail)
        self.assertNotRegex(tail, r"content:\s*result\b")
        # A cell that could not be saved is not reported as done.
        self.assertLess(tail.index("if (cellSaveError) {"), tail.index("receivedColumns.add(columnIndex)"))
        # The cap on concurrent gate calls.
        self.assertRegex(self.code, r"createLimiter\(CELL_GATE_CONCURRENCY,\s*\{\s*timeoutMs: CELL_GATE_TIMEOUT_MS,?\s*\}\)")
        self.assertRegex(self.code, r"const CELL_GATE_CONCURRENCY = [1-4];")
        self.assertRegex(self.code, r"const CELL_GATE_TIMEOUT_MS = 75_000;")
        self.assertIn("limitCellGate(", tail)
        # A timed-out gate call withholds the cell with the unverifiable marker.
        self.assertIn("unverifiableCell()", tail)

    def _section(self, start, end):
        i = self.code.index(start)
        return self.code[i:self.code.index(end, i + len(start))]

    def test_regenerate_cell_gates_before_saving_and_returns_only_gated_content(self):
        sec = self._section('"/:reviewId/regenerate-cell"', 'tabularRouter.post("/:reviewId/generate"')
        q = sec.index("await queryTabularCell(")
        gate = sec.index("gateCellContent(", q)
        save = sec.index('.from("tabular_cells")', gate)
        ret = sec.index("res.json(gated.content)", save)
        self.assertTrue(q < gate < save < ret, "model call, gate, save, return")
        self.assertIn("JSON.stringify(gated.content)", sec)
        self.assertIn("limitCellGate(", sec)
        self.assertIn("unverifiableCell()", sec)
        self.assertNotIn("res.json(result)", sec)
        self.assertNotIn("JSON.stringify(result)", sec)
        self.assertLess(sec.index("if (cellSaveError) {"), ret)
        # Raw errors go to safeErrorLog only; replies carry fixed text.
        for m in re.finditer(r"\berr\b", sec):
            before = sec[: m.start()]
            if before.endswith("catch ("):
                continue
            self.assertTrue(before.endswith("safeErrorLog("),
                            f"err used outside safeErrorLog: ...{sec[max(0, m.start() - 40): m.end() + 10]!r}")
        self.assertNotRegex(sec, r"detail:\s*(error|err)\b")
        self.assertNotRegex(sec, r"\.message")

    def test_get_review_regates_every_stored_cell_and_trusts_no_stored_record(self):
        sec = self._section('tabularRouter.get("/:reviewId", requireAuth', 'tabularRouter.get("/:reviewId/people"')
        self.assertIn("gateCellContent(", sec)
        self.assertIn("limitCellGate(", sec)
        self.assertIn("unverifiableCell()", sec)
        self.assertIn("parseCellContent(cell.content)", sec)
        self.assertNotIn("...cell", sec, "cell columns are listed, not spread")
        self.assertNotRegex(sec, r"content:\s*parseCellContent\(")
        self.assertNotIn(".verification", sec, "a stored verification record is never read")
        self.assertNotRegex(sec, r"\.(update|insert|upsert|delete)\(", "no write on read")

    def test_prompt_route_gates_the_model_prompt_and_returns_a_fixed_message(self):
        sec = self._section('tabularRouter.post("/prompt"', 'tabularRouter.get("/:reviewId", requireAuth')
        done = sec.index("completeText(")
        gate = sec.index("gateCellContent(", done)
        send = sec.index('source: "llm"', gate)
        self.assertTrue(done < gate < send)
        self.assertIn("if (gated.withheld)", sec)
        self.assertIn("PROMPT_WITHHELD_MESSAGE", sec)
        self.assertIn("The generated prompt was withheld because it could not be verified.", self.src)
        self.assertNotRegex(sec, r"json\(\{\s*detail:\s*(raw|parsed|prompt)\b")

    def test_chip_fields_are_not_copied_from_model_json(self):
        sec = self._section("function extractTabularAnnotations(", "function buildTabularMessages(")
        for banned in ("ref: c.ref", "col_index: c.col_index", "row_index: c.row_index", "quote: c.quote", "`Col ${", "`Row ${"):
            self.assertNotIn(banned, sec)
        self.assertIn("isChipIndex(ref)", sec)
        self.assertIn("isChipIndex(col_index)", sec)
        self.assertIn("isChipIndex(row_index)", sec)
        self.assertIn("Number.isSafeInteger(v) && v >= 0", self.code)

    def test_generate_sends_only_generic_error_text(self):
        gen = self._generate()
        self.assertNotIn("safeErrorMessage", self.src)
        self.assertIn('message: GENERIC_ERROR_MESSAGE', gen)
        for m in re.finditer(r"\berr\b", gen):
            before = gen[: m.start()]
            if before.endswith("catch ("):
                continue
            self.assertTrue(before.endswith("safeErrorLog("),
                            f"err used outside safeErrorLog: ...{gen[max(0, m.start() - 40): m.end() + 10]!r}")


if __name__ == "__main__":
    unittest.main()
