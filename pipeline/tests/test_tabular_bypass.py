"""Tabular review routes (merge blocker 4, part A): bypass attacks on the Gate 1 wiring in
backend/src/routes/tabular.ts and the tabular parts of backend/src/middleware/hallucination_guard.ts
(adversary vector 3: no execution flow where LLM generation reaches the client or the database without Gate 1).

Behavioral part: pipeline/tests/tabular_bypass_cases.ts runs once under backend's tsx against the REAL tabular
router (handlers pulled out of the express stack) with the model, Supabase, auth and (except for the "real_gate"
cases) the Gate 1 verifier stubbed. The real_gate cases run the production verify closure and the Python gate against
the fixture database. No network. Assertions are on what can leave the server (writes, JSON bodies, database
payloads), not on the mechanism, so any fix that closes the hole passes.

Round 1 (2026-10-08) found the chip metadata leak, the ungated regenerate-cell and GET /:reviewId, and the open
POST /prompt sink. Round 2 (same day) re-runs them against the builder's fixes and attacks the new code: chip field
coercion, the gated POST /prompt (veto, throw, busy, malformed, timeout, 502 body), regenerate-cell failure paths,
GET re-gate (forged verification records, dedupe keys, non-allowlisted columns, odd stored shapes) and the limiter's
per-call timeout (slot freed once, late result or throw ignored).

Round 3 (Part C, same day) attacks the model-written chat title: the builder's gateTitleText over the exact string that is
saved and sent, the user's-message fallback, every way the title gate can fail, truncation and padding, the real gate on
obfuscated cites, and the failing title save (class TabularChatTitle). The chat.ts title (generate-title) is attacked in
test_title_gate_bypass.py.

Expected against the round-3 code: PASS everywhere except the one SKIPPED open item (titles stored before the title gate
existed are read back as saved, Part C follow-up).
"""

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate1_fixture as fx  # noqa: E402

REPO = fx.REPO
TSX = REPO / "backend" / "node_modules" / ".bin" / "tsx"
CASES_TS = Path(__file__).resolve().parent / "tabular_bypass_cases.ts"
TABULAR_TS = REPO / "backend" / "src" / "routes" / "tabular.ts"

_RUN = {}


def _run_cases():
    """One tsx process for the whole module."""
    if "data" not in _RUN:
        if not TSX.exists():
            raise AssertionError("tsx missing at %s; the tabular bypass cases cannot run (report it, do not skip it)" % TSX)
        env = dict(os.environ)
        env["KINGSFIELD_FLORIDA_DB"] = str(fx.get_fixture().db)
        proc = subprocess.run([str(TSX), str(CASES_TS)], capture_output=True, text=True, env=env,
                              cwd=str(REPO), timeout=120)
        if proc.returncode != 0:
            raise AssertionError("tsx failed (%d):\n%s" % (proc.returncode, proc.stderr[-2500:]))
        lines = [l for l in proc.stdout.splitlines() if l.strip()]
        _RUN["data"] = json.loads(lines[-1])
        if os.environ.get("KF_INFO"):
            sys.stderr.write("tabular_bypass_cases info: %s\n" % json.dumps(_RUN["data"]["info"], sort_keys=True))
    return _RUN["data"]


class _Cases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = _run_cases()["results"]

    def _case(self, name):
        self.assertIn(name, self.report, "the harness did not run %s" % name)
        if self.report[name] is not None:
            self.fail(str(self.report[name])[:450])


class TabularChipMetadata(_Cases):
    """The finalizer checks a tabular chip's `quote` only. The route builds the rest of the chip from the model's JSON,
    so ref / col_index / row_index must be safe non-negative integers (else the chip is dropped), the names come from the
    review's own columns and documents, and no other model key is copied (round-1 finding F1)."""

    def test_chip_metadata_cannot_carry_a_fabricated_cite(self):
        # A cite written with JSON unicode escapes is not present in fullText in readable form, so Gate 1 on fullText cannot see
        # it; the decoded value must therefore never be copied into a chip field.
        self._case("chat_chip_metadata_cannot_carry_a_fabricated_cite")

    def test_chip_metadata_cannot_carry_a_fabricated_cite_through_the_production_gate(self):
        # Same attack with a JSON-unicode-escaped capital S in "So." that the ASCII-only grammar cannot read in fullText.
        # The assertion is on the leak: a withheld reply or a dropped chip both pass.
        self._case("chat_chip_metadata_real_gate")

    def test_a_chip_quote_with_a_fabricated_florida_cite_does_not_survive_the_production_gate(self):
        self._case("chat_chip_quote_with_a_fabricated_florida_cite_real_gate")

    def test_chip_fields_are_coerced_floats_negatives_huge_ints_strings_and_extra_keys(self):
        # 25 hand-written chips: floats, -1, 1e300, 2^53+1, 1e400 (Infinity), numeric strings, null/bool/array/object
        # indexes, a missing or non-string quote, extra keys (col_name, doc_name, cluster_id, kind, type, citation, url)
        # and non-object entries. Only the valid ones may survive, with the fixed key set and the review's own names, in
        # both the sent chips and the saved annotations.
        self._case("chat_chip_fields_are_coerced_to_safe_integers_fixed_keys_and_own_names")


class TabularChatWiring(_Cases):
    def test_text_streamed_but_not_in_fulltext_is_withheld_whole(self):
        self._case("chat_streamed_text_that_is_not_in_fulltext_is_withheld_at_the_route")

    def test_saved_text_that_is_not_the_sent_text_is_withheld_whole(self):
        self._case("chat_saved_text_that_is_not_the_sent_text_is_withheld_at_the_route")

    def test_held_reasoning_error_unknown_and_unparseable_lines_never_reach_the_client_or_the_row(self):
        self._case("chat_held_non_content_events_never_carry_model_text")

    def test_a_busy_gate_withholds_the_reply(self):
        self._case("chat_gate_busy_veto_withholds_the_reply")

    def test_client_disconnect_mid_stream_saves_only_the_aborted_marker(self):
        self._case("chat_client_disconnect_mid_stream_saves_only_the_aborted_marker")

    def test_a_throwing_reply_save_means_the_reply_is_not_sent(self):
        self._case("chat_a_throwing_reply_save_means_the_reply_is_not_sent")

    def test_a_client_that_is_already_gone_before_the_model_starts_never_starts_it(self):
        # The close listener is registered after several awaits; a disconnect before that is never seen as an event.
        # Cost and load, not a leak: the reply would be gated and saved.
        self._case("chat_a_client_that_is_already_gone_before_the_model_starts_never_starts_it")


class TabularGenerateBypass(_Cases):
    def test_a_cite_in_the_reasoning_the_summary_a_json_array_the_flag_or_an_extra_field_never_reaches_the_client_or_the_row(self):
        self._case("generate_every_model_channel_is_gated_or_dropped")

    def test_busy_throwing_and_malformed_gate_results_fail_closed_cell_by_cell(self):
        self._case("generate_busy_throwing_and_malformed_gate_results_fail_closed_per_cell")

    def test_two_documents_keep_their_own_verdicts_when_verdicts_finish_out_of_order(self):
        self._case("generate_two_documents_keep_their_own_verdicts")

    def test_real_gate_obfuscated_cites_in_cells_are_withheld(self):
        self._case("generate_real_gate_obfuscated_cites_withhold_their_cells")


class UngatedStoredAndRegeneratedCells(_Cases):
    """Every path by which a cell's model-written content reaches the client or the database must pass Gate 1.
    Round 1 findings F2 (regenerate-cell) and F3 (GET /:reviewId), fixed in round 2. Expected to pass."""

    def test_regenerate_cell_a_vetoed_cell_never_reaches_the_client_or_the_database(self):
        self._case("regenerate_cell_a_vetoed_cell_never_reaches_the_client_or_the_database")

    def test_regenerate_cell_a_gate_failure_never_returns_the_raw_model_text(self):
        self._case("regenerate_cell_a_gate_failure_never_returns_the_raw_model_text")

    def test_regenerate_cell_a_clean_cell_is_gated_before_it_is_saved_and_still_returned(self):
        self._case("regenerate_cell_a_clean_cell_is_gated_before_it_is_saved_and_still_returned")

    def test_regenerate_cell_model_and_save_failures_return_fixed_text_and_never_the_cell(self):
        # Round 2: save returns an error, save throws, the model call throws, the model returns nothing. Each answers 500
        # {"detail": "Generation failed"}; the gated cell is not returned when it was not saved; no raw error text.
        self._case("regenerate_cell_model_and_save_failures_return_fixed_text_and_never_the_cell")

    def test_get_review_does_not_return_stored_cells_that_never_passed_gate_1(self):
        self._case("get_review_does_not_return_ungated_stored_cells")

    def test_get_review_forged_clean_records_extra_columns_and_extra_fields_never_reach_the_client(self):
        # Round 2: a stored verification record that says "verified" on a fabricated cite, a stored record carrying raw error
        # text, `citations` / `error` / `raw_response` columns, and extra JSON fields in the content. The response cell has
        # exactly seven keys, the content exactly four, and the database is not written.
        self._case("get_review_forged_records_extra_columns_and_extra_fields_never_reach_the_client")

    def test_get_review_dedupe_never_lends_one_cells_verdict_to_a_different_text(self):
        # Round 2: cells differing only in flag, only in reasoning, only in the stored record, or sharing the checked text
        # through a different (summary, reasoning) split; both orders.
        self._case("get_review_dedupe_never_lends_one_cells_verdict_to_a_different_text")

    def test_get_review_odd_stored_content_shapes_never_return_a_cite(self):
        self._case("get_review_odd_stored_content_shapes_never_return_a_cite")

    def test_get_review_real_gate_stored_obfuscated_cites_are_withheld(self):
        self._case("get_review_real_gate_stored_obfuscated_cites_are_withheld")


class PromptRouteGate(_Cases):
    """POST /tabular-review/prompt: the model-written column prompt goes through Gate 1 (round 1 open sink, closed in round 2)."""

    def test_a_vetoed_or_unverifiable_prompt_returns_the_fixed_502_and_never_the_prompt(self):
        # veto, gate throws, busy, malformed result, error result, pending verdict, unknown status with hasVetoes false.
        self._case("prompt_route_a_vetoed_or_unverifiable_prompt_is_never_returned")

    def test_model_failures_and_non_string_prompts_return_fixed_text_only(self):
        self._case("prompt_route_model_failures_and_non_string_prompts_return_fixed_text_only")

    def test_a_clean_prompt_is_gated_as_returned_and_nothing_else_the_model_wrote_comes_back(self):
        self._case("prompt_route_a_clean_prompt_is_gated_as_returned_and_nothing_else_comes_back")

    def test_real_gate_obfuscated_cites_in_a_prompt_are_withheld(self):
        self._case("prompt_route_real_gate_obfuscated_cites_are_withheld")


class GateTimeout(_Cases):
    """The limiter's per-call timeout (CELL_GATE_TIMEOUT_MS). The route cases scale the 75 s timer to 20 ms by wrapping
    setTimeout for delays of 30 s or more, and fail (instead of hanging) if the request is not freed."""

    def test_regenerate_cell_a_gate_that_never_answers_withholds_the_cell_and_ignores_the_late_result(self):
        self._case("regenerate_cell_a_gate_that_never_answers_withholds_the_cell_and_ignores_the_late_result")

    def test_prompt_route_a_gate_that_never_answers_returns_the_fixed_502_and_ignores_the_late_result(self):
        self._case("prompt_route_a_gate_that_never_answers_returns_the_fixed_502_and_ignores_the_late_result")

    def test_get_review_timed_out_gate_calls_free_their_slots_so_later_cells_are_still_gated(self):
        self._case("get_review_gate_calls_that_never_answer_free_their_slots_and_late_results_are_ignored")

    def test_limiter_a_timeout_frees_the_slot_once_and_a_late_result_or_throw_changes_nothing(self):
        self._case("limiter_a_timeout_frees_the_slot_once_and_a_late_result_or_throw_changes_nothing")

    def test_limiter_timeout_without_a_fallback_rejects_and_a_throwing_task_or_fallback_frees_its_slot(self):
        self._case("limiter_timeout_without_a_fallback_rejects_and_a_throwing_task_or_fallback_frees_its_slot")


class TabularChatTitle(_Cases):
    """POST /:reviewId/chat, the title block (Part C). The model's title is Gate 1 checked as the exact string that is saved
    and sent; on any veto, pending status, gate failure or timeout the title is the start of the user's first message (user
    text, not gated); a failed model call gives the same; the title is written after the reply is saved and sent, so a
    failing title save only logs."""

    def test_a_fabricated_cite_in_the_model_title_falls_back_to_the_users_message(self):
        self._case("chat_title_a_fabricated_cite_in_the_model_title_falls_back_to_the_users_message")

    def test_a_clean_title_is_gated_as_saved_and_sent_once(self):
        self._case("chat_title_a_clean_title_is_gated_as_saved_and_sent_once")

    def test_padding_markdown_and_truncation_cannot_hide_a_cite(self):
        # 9 paddings (quotes, bold, heading, quote marker, whitespace, link, trailing punctuation); a cite cut to "999 So. 3d 9" by the
        # 80-character cut is checked as cut; a cite beyond the cut is gone and is not put back.
        self._case("chat_title_padding_markdown_and_truncation_cannot_hide_a_cite")

    def test_every_gate_failure_mode_gives_the_users_message_and_nothing_else(self):
        # 15 gate answers: veto, pending, unknown or missing status, veto flag alone, whole-draft placeholder, busy, error
        # result (with and without the flag), throw, {}, null, a string, verdicts not an array, verified plus vetoed.
        self._case("chat_title_every_gate_failure_mode_gives_the_users_message_and_nothing_else")

    def test_a_gate_that_never_answers_falls_back_ignores_the_late_answer_and_ends(self):
        self._case("chat_title_a_gate_that_never_answers_falls_back_ignores_the_late_answer_and_ends")

    def test_model_failures_use_the_users_message_and_never_the_raw_error(self):
        self._case("chat_title_model_failures_use_the_users_message_and_never_the_raw_error")

    def test_a_failing_title_save_only_logs_and_leaves_the_reply_alone(self):
        self._case("chat_title_a_failing_save_only_logs_and_leaves_the_reply_alone")

    def test_fallback_is_only_the_requesters_message_flattened_and_cut(self):
        # The fallback is built from req.body.messages (client-supplied; the route does not read the stored chat). User
        # text, not model text. A message with nothing usable left (control characters only) gives no title at all.
        self._case("chat_title_fallback_is_only_the_requesters_message_flattened_and_cut")

    def test_real_gate_obfuscated_cites_fall_back_and_a_clean_title_passes(self):
        # plain, full-width digits, zero-width space, period-less, cite hidden in a markdown link title: one Python gate call each.
        self._case("chat_title_real_gate_obfuscated_cites_fall_back_and_a_clean_title_passes")


class ClockAndStoredTitles(_Cases):
    """The harness runs every case on a clock whose milliseconds are always 999 (the worst case for the fabricated cite's
    "999"); the first case proves the clock is in effect and that timestamp masking hides nothing but timestamps.
    Stored tabular chat titles are now re-gated on read (the open item of round 3 is closed: un-skipped, body unchanged)."""

    def test_the_999_ms_clock_is_in_effect_and_masking_hides_only_timestamps(self):
        self._case("clock_frozen_at_999_ms_is_in_effect_and_masking_hides_only_timestamps")

    def test_stored_tabular_chat_titles_are_gated_on_read(self):
        self._case("open_stored_tabular_chat_titles_are_gated_on_read")


# ───── static: every place tabular.ts calls a model, and where the output goes ─────

def _code(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", line) for line in src.splitlines())


ROUTE_RE = re.compile(r'tabularRouter\.(get|post|patch|delete)\(\s*"([^"]+)"')
SINK_RE = re.compile(
    r"(?<![\w.])(completeText|queryTabularCell|queryTabularAllColumns|runLLMStream|streamChatWithTools|"
    r"generateChatTitle|runCaseExtraction)\s*\("
)
# Model-text sinks that are NOT gated, recorded (route, sink). Anything else must sit in a route handler that
# calls gateCellContent( or awaits finalizeHeldOutput(.
OPEN_SINKS = {
    # POST /prompt left this list in round 2: it is gated (gateCellContent) and returns a fixed 502 on a veto.
    # generateChatTitle left it in round 3: its output goes through gateTitleText (see _gated and the title-order test below).
    ("POST /", "runCaseExtraction"):
        "auto case-extraction on review create writes model-derived rows with no Gate 1 "
        "(current-state.md open item: /analytics/extract)",
}


def _route_sinks():
    code = _code(TABULAR_TS.read_text(encoding="utf-8", errors="replace"))
    cut = code.index("function parseCellContent(")  # helpers (queryTabularCell, generateChatTitle...) are defined after the routes
    routes = code[:cut]
    heads = list(ROUTE_RE.finditer(routes))
    found = []
    for i, h in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(routes)
        section = routes[h.start():end]
        key = "%s %s" % (h.group(1).upper(), h.group(2))
        for m in SINK_RE.finditer(section):
            found.append((key, m.group(1), section))
    return found


def _gated(section, sink=""):
    # The chat title is a separate sink inside a handler that already gates the reply: the reply's gate says nothing
    # about the title, so a title sink is gated only by gateTitleText.
    if sink == "generateChatTitle":
        return "gateTitleText(" in section
    return "gateCellContent(" in section or "await finalizeHeldOutput(" in section


class StaticSinks(unittest.TestCase):
    def test_the_parser_sees_the_sinks_it_must_see(self):
        pairs = {(k, s) for k, s, _ in _route_sinks()}
        for want in (("POST /:reviewId/chat", "runLLMStream"), ("POST /:reviewId/generate", "queryTabularAllColumns"),
                     ("POST /:reviewId/regenerate-cell", "queryTabularCell")):
            self.assertIn(want, pairs, "the sink scan no longer finds %s; the test needs updating" % (want,))

    def test_every_model_sink_in_a_tabular_route_is_gated_or_a_recorded_open_item(self):
        problems = []
        for key, sink, section in _route_sinks():
            if (key, sink) in OPEN_SINKS:
                continue
            if not _gated(section, sink):
                problems.append("%s calls %s() in a handler with no gateCellContent( / finalizeHeldOutput( call "
                                "(gateTitleText( for the chat title)" % (key, sink))
        self.assertEqual(
            problems, [],
            "model text can reach the client or the database without Gate 1:\n"
            + "\n".join(problems),
        )

    def test_the_shared_limiter_keeps_its_per_call_timeout_and_cap(self):
        code = _code(TABULAR_TS.read_text(encoding="utf-8", errors="replace"))
        self.assertRegex(code, r"createLimiter\(\s*CELL_GATE_CONCURRENCY\s*,\s*\{\s*timeoutMs\s*:\s*CELL_GATE_TIMEOUT_MS\s*,?\s*\}\s*\)",
                         "the shared limiter is no longer created with the per-call timeout")
        m = re.search(r"const\s+CELL_GATE_CONCURRENCY\s*=\s*(\d+)", code)
        self.assertIsNotNone(m)
        self.assertLessEqual(int(m.group(1)), 4, "more concurrent cell gates than the gate's own 4-child cap")
        m = re.search(r"const\s+CELL_GATE_TIMEOUT_MS\s*=\s*([\d_]+)", code)
        self.assertIsNotNone(m)
        self.assertGreaterEqual(int(m.group(1).replace("_", "")), 60000,
                                "the gate timeout is below the gate's own worst case (30 s queue + 30 s child)")

    def test_the_recorded_open_sinks_still_exist_so_the_list_cannot_go_stale(self):
        pairs = {(k, s) for k, s, _ in _route_sinks()}
        stale = [p for p in OPEN_SINKS if p not in pairs]
        self.assertEqual(stale, [], "open-sink entries that no longer match the code (fixed or renamed?); update OPEN_SINKS: %s" % stale)

    def test_generate_saves_and_sends_the_gated_content_only_and_gates_before_saving(self):
        code = _code(TABULAR_TS.read_text(encoding="utf-8", errors="replace"))
        i = code.index('tabularRouter.post("/:reviewId/generate"')
        j = code.index('tabularRouter.get("/:reviewId/chats"')
        gen = code[i:j]
        m = re.search(r"\bawait\s+queryTabularAllColumns\s*\(", gen)
        self.assertIsNotNone(m)
        tail = gen[m.start():]
        gate = tail.find("gateCellContent(")
        save = tail.find('.from("tabular_cells")')
        send = tail.find("cell_update")
        self.assertTrue(0 <= gate < save < send, "gate, then save, then send")
        self.assertIn("JSON.stringify(gated.content)", tail)
        self.assertIn("content: gated.content", tail)
        self.assertNotIn("JSON.stringify(result)", tail)
        self.assertNotRegex(tail, r"content:\s*result\b")
        self.assertNotRegex(tail, r"JSON\.stringify\(\s*\{[^}]*\bresult\b")

    def test_prompt_route_returns_only_after_the_gate_and_only_the_gated_prompt_text(self):
        code = _code(TABULAR_TS.read_text(encoding="utf-8", errors="replace"))
        i = code.index('tabularRouter.post("/prompt"')
        j = code.index('tabularRouter.get("/:reviewId"')
        sec = code[i:j]
        gate = sec.find("gateCellContent(")
        ret = sec.find("res.json({ prompt")
        self.assertTrue(0 <= gate < ret, "POST /prompt answers with the prompt before (or without) Gate 1")
        # the one success response is the trimmed prompt that was gated, and a withheld result returns before it
        self.assertEqual(len(re.findall(r"res\.json\(\{\s*prompt", sec)), 1, "more than one success response in POST /prompt")
        self.assertRegex(sec, r"if\s*\(\s*gated\.withheld\s*\)\s*\{\s*return\s+void\s+res\s*\.status\(502\)")
        self.assertRegex(sec, r"summary:\s*prompt\b")
        self.assertNotRegex(sec, r"res\.json\(\s*(?:parsed|raw)\b")

    def test_every_gate_call_through_the_limiter_has_a_fixed_marker_fallback(self):
        # limitCellGate(task, onTimeout): without the fallback a timeout rejects, and in GET /:reviewId (Promise.all inside
        # an async handler with no catch) that is an unhandled rejection, not a withheld cell.
        code = _code(TABULAR_TS.read_text(encoding="utf-8", errors="replace"))
        calls = [m for m in re.finditer(r"(?<![\w.])limitCellGate\s*\(", code)]
        self.assertGreaterEqual(len(calls), 4, "expected limitCellGate calls in generate, regenerate-cell, prompt and GET")
        for m in calls:
            depth, end = 0, m.end() - 1
            for end in range(m.end() - 1, len(code)):
                depth += (code[end] == "(") - (code[end] == ")")
                if depth == 0:
                    break
            args = code[m.end() - 1:end + 1]
            self.assertRegex(args, r"\(\)\s*=>\s*unverifiableCell\(\)", "limitCellGate call without an unverifiableCell() fallback: " + args[:160])
            self.assertIn("gateCellContent(", args, "limitCellGate wraps something other than gateCellContent: " + args[:160])

    def test_get_review_never_returns_the_stored_cell_or_writes_back(self):
        code = _code(TABULAR_TS.read_text(encoding="utf-8", errors="replace"))
        i = code.index('tabularRouter.get("/:reviewId"')
        j = code.index('tabularRouter.get("/:reviewId/people"')
        sec = code[i:j]
        self.assertIn("gateCellContent(", sec)
        self.assertNotRegex(sec, r"\.(update|insert|upsert|delete)\(", "GET /:reviewId writes to the database")
        # the returned cells are rebuilt field by field; the raw row (`...cell`, `cells:` straight from the query) is not passed on
        self.assertNotRegex(sec, r"\.\.\.\s*cell\b")
        self.assertNotRegex(sec, r"cells:\s*cells\b")
        self.assertRegex(sec, r"content:\s*parsed\s*\?\s*\(\s*await\s+gateStoredCell\(\s*parsed\s*\)\s*\)\.content\s*:\s*null")

    def test_chat_catch_block_saves_only_the_fixed_marker(self):
        code = _code(TABULAR_TS.read_text(encoding="utf-8", errors="replace"))
        i = code.index('tabularRouter.post("/:reviewId/chat"')
        j = code.index("function parseCellContent(")
        chat = code[i:j]
        c0 = chat.index("} catch (err) {")
        c1 = chat.index("} finally {")
        catch = chat[c0:c1]
        for banned in ("fullText", "events", "finalized", "buffered", "extractTabularAnnotations", "err.message", "err.stack"):
            self.assertIsNone(re.search(r"(?<![\w.])%s(?!\w)" % re.escape(banned), catch), "%s in the chat catch block" % banned)
        self.assertIn("failedReplyRecord(", catch)
        self.assertIn("content: failedReply.events", catch)


if __name__ == "__main__":
    unittest.main()
