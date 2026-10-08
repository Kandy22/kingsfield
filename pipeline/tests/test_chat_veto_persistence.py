"""Chat route, success path: a veto must survive a reload, and no model text may reach the client or the
saved row without passing Gate 1 (adversary vector 3).

Behavioral part: pipeline/tests/chat_veto_cases.ts runs once under backend's tsx. It drives the real
finalizeHeldOutput and the real hydrateEditStatuses (cut out of chat.ts and run against a stub db) with stub
gates, plus a handful of cases through the production verify closure and the real Python gate against the
fixture database. Supabase, CourtListener, LLMs and the network are unreachable.

Static part: the routes save exactly what finalizeHeldOutput returned, and every caller of runLLMStream holds
its output until finalizeHeldOutput has run.
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
BACKEND_SRC = REPO / "backend" / "src"
TSX = REPO / "backend" / "node_modules" / ".bin" / "tsx"
CASES_TS = Path(__file__).resolve().parent / "chat_veto_cases.ts"


class ChatReplyCases(unittest.TestCase):
    report = None
    info = None

    @classmethod
    def setUpClass(cls):
        if not TSX.exists():
            raise AssertionError("tsx missing at %s; the chat-route bypass cases cannot run (report it, do not skip it)" % TSX)
        env = dict(os.environ)
        env["KINGSFIELD_FLORIDA_DB"] = str(fx.get_fixture().db)
        proc = subprocess.run([str(TSX), str(CASES_TS)], capture_output=True, text=True, env=env,
                              cwd=str(REPO), timeout=240)
        if proc.returncode != 0:
            raise AssertionError("tsx failed (%d):\n%s" % (proc.returncode, proc.stderr[-2500:]))
        lines = [l for l in proc.stdout.splitlines() if l.strip()]
        data = json.loads(lines[-1])
        cls.report = data["results"]
        cls.info = data["info"]
        sys.stderr.write("chat_veto_cases info: %s\n" % json.dumps(cls.info, sort_keys=True))

    def _case(self, name):
        self.assertIn(name, self.report, "the harness did not run %s" % name)
        self.assertIsNone(self.report[name], self.report[name])

    # ----- a veto survives a reload -----

    def test_a_vetoed_reply_is_withheld_whole_saved_with_its_stripped_veto_and_a_reload_shows_it(self):
        self._case("vetoed_reply_saved_with_veto_and_reload_shows_it")

    def test_a_withheld_reply_is_saved_flagged_with_no_raw_error_and_a_reload_shows_it(self):
        self._case("withheld_reply_saved_flagged_and_reload_shows_it")

    def test_a_clean_reply_is_saved_with_a_clean_record(self):
        self._case("clean_reply_saved_with_a_clean_record")

    def test_a_reload_patches_edit_statuses_without_touching_the_veto_record(self):
        self._case("reload_patches_edits_and_keeps_the_record")

    # ----- nothing model-written leaves unchecked -----

    def test_a_model_chosen_document_filename_cannot_carry_a_flagged_cite_through_doc_read(self):
        # generate_docx names the file from the model's title; the follow-up read_document emits
        # doc_read_start / doc_read with that name. doc_read / doc_read_start are one Gate-1-checked family.
        self._case("generated_doc_filename_is_not_a_gate1_free_channel")

    def test_a_flagged_filename_in_doc_read_alone_drops_the_whole_doc_read_family(self):
        self._case("doc_read_alone_with_flagged_filename_is_dropped")

    def test_every_vetoed_pending_or_unknown_verdict_withholds_the_whole_reply(self):
        self._case("pending_unknown_and_draft_verdicts_withhold_whole_reply")

    def test_conditional_verdicts_still_pass_unchanged(self):
        self._case("conditional_verdict_passes_unchanged")

    def test_a_cite_present_only_in_the_sent_text_withholds(self):
        self._case("cite_only_in_sent_text_withholds")

    def test_blank_full_text_with_nonblank_sent_text_withholds(self):
        self._case("blank_fulltext_with_nonblank_sent_text_withholds")

    def test_sent_text_that_is_not_the_full_text_withholds_even_when_gate1_is_clean(self):
        self._case("sent_text_not_derived_from_fulltext_withholds")

    def test_hidden_citations_block_is_not_a_false_mismatch(self):
        self._case("hidden_citations_block_matches")

    def test_visible_matches_full_text_alignment_rules(self):
        self._case("visible_matches_full_text_rules")

    def test_real_gate_markdown_and_cites_split_across_deltas_withhold_the_whole_reply(self):
        self._case("real_gate_markdown_and_split_deltas")

    def test_real_gate_obfuscated_cites_withhold_the_whole_reply(self):
        self._case("real_gate_obfuscation_battery")

    def test_real_gate_plain_cite_with_a_pin_withholds_the_whole_reply_name_and_holding_included(self):
        self._case("real_gate_plain_cite_with_pin")

    def test_real_gate_cite_only_inside_the_citations_block_does_not_leak(self):
        self._case("real_gate_cite_only_in_the_citations_block")

    # ----- merge blocker 3: period-less reporter cites through the real gate (CourtListener stubbed to not-found,
    # Supabase cache lookup answers "no row"). The case also asserts the veto was the gate's own, not a caught error;
    # the info dump on stderr records which it was (info.real_gate_period_less_*.how). -----

    def test_real_gate_period_less_cites_in_one_reply_withhold_it_by_a_real_veto_not_an_error(self):
        self._case("real_gate_period_less_cites_combined")

    def test_real_gate_period_less_full_cite_alone_withholds_the_reply(self):
        self._case("real_gate_period_less_full_cite_alone")

    def test_real_gate_period_less_bare_cite_alone_withholds_the_reply(self):
        self._case("real_gate_period_less_bare_cite_alone")


# ───── static: who calls runLLMStream, and does the route save what finalizeHeldOutput returned ─────

def _code(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", line) for line in src.splitlines())


def _call_args(code, open_paren):
    depth = 0
    for i in range(open_paren, len(code)):
        if code[i] == "(":
            depth += 1
        elif code[i] == ")":
            depth -= 1
            if depth == 0:
                return code[open_paren:i + 1]
    return code[open_paren:]


TABULAR_TS = BACKEND_SRC / "routes" / "tabular.ts"
TABULAR_SKIP_REASON = (
    "KNOWN OPEN, own task (merge blocker 4 in docs/context/current-state.md, 'Tabular review chat streams and "
    "saves unverified model text'): tabular chat (backend/src/routes/tabular.ts ~1348) and "
    "/:reviewId/generate (~933-952) stream unverified model text. Un-skip when tabular.ts buffers and finalizes."
)


def _llm_stream_callers():
    """Every call site of runLLMStream under backend/src: (path, comment-stripped source, match, args)."""
    callers = []
    for p in sorted(BACKEND_SRC.rglob("*.ts")):
        if "node_modules" in p.parts:
            continue
        raw = p.read_text(encoding="utf-8", errors="replace")
        if "runLLMStream" not in raw:
            continue
        code = _code(raw)
        for m in re.finditer(r"\brunLLMStream\s*\(", code):
            if re.search(r"function\s*$", code[max(0, m.start() - 20):m.start()]):
                continue  # the definition
            callers.append((p, code, m, _call_args(code, m.end() - 1)))
    return callers


def _is_tabular_chat_caller(p, args):
    """The one call site covered by the tabular skip: tabular.ts, wired with TABULAR_TOOLS.
    A runLLMStream call anywhere else, or in tabular.ts without TABULAR_TOOLS, is NOT exempt."""
    return p == TABULAR_TS and "TABULAR_TOOLS" in args


def _caller_problems(callers):
    problems = []
    for p, code, m, args in callers:
        where = "%s:%d" % (p.relative_to(REPO), code.count("\n", 0, m.start()) + 1)
        if not re.search(r"\bwrite\s*:\s*(\w+)\.write\b", args):
            problems.append("%s passes the raw writer to runLLMStream (no buffered writer)" % where)
            continue
        for needle in ("createBufferingSseWriter(", "await finalizeHeldOutput(", ".takeHeld()"):
            if needle not in code:
                problems.append("%s: file never uses %s" % (where, needle))
        if re.search(r"\.flush\(\)", code):
            problems.append("%s: file releases held output with flush() instead of finalizeHeldOutput" % where)
        if code.find("await finalizeHeldOutput(") < m.start():
            problems.append("%s: finalizeHeldOutput runs before runLLMStream" % where)
    return problems


class EveryLlmStreamCallerHoldsItsOutput(unittest.TestCase):
    def test_every_caller_of_run_llm_stream_buffers_and_finalizes(self):
        """Every runLLMStream caller except the tabular chat call (skipped test below, merge blocker 4)."""
        all_callers = _llm_stream_callers()
        self.assertTrue(all_callers, "found no caller of runLLMStream; the test needs updating")
        callers = [c for c in all_callers if not _is_tabular_chat_caller(c[0], c[3])]
        exempt = [c for c in all_callers if _is_tabular_chat_caller(c[0], c[3])]
        # The exemption is narrow: only tabular.ts, only the TABULAR_TOOLS call. Say so when it is used.
        sys.stderr.write("runLLMStream callers: %d enforced, %d exempt (tabular chat, merge blocker 4)\n"
                         % (len(callers), len(exempt)))
        problems = _caller_problems(callers)
        self.assertEqual(problems, [], "LLM output can reach the client without Gate 1:\n" + "\n".join(problems))

    @unittest.skip(TABULAR_SKIP_REASON)
    def test_tabular_chat_caller_of_run_llm_stream_buffers_and_finalizes(self):
        callers = [c for c in _llm_stream_callers() if c[0] == TABULAR_TS]
        self.assertTrue(callers, "found no runLLMStream caller in tabular.ts; the test needs updating")
        problems = _caller_problems(callers)
        self.assertEqual(problems, [], "tabular chat can reach the client without Gate 1:\n" + "\n".join(problems))

    @unittest.skip(TABULAR_SKIP_REASON)
    def test_tabular_generate_does_not_stream_unverified_cells(self):
        # /:reviewId/generate does not go through runLLMStream: queryTabularAllColumns returns model-written cell
        # content that is saved and sent as cell_update. It must pass through Gate 1 before either.
        code = _code(TABULAR_TS.read_text(encoding="utf-8", errors="replace"))
        m = re.search(r"\bawait\s+queryTabularAllColumns\s*\(", code)
        self.assertIsNotNone(m, "found no queryTabularAllColumns call in tabular.ts; the test needs updating")
        tail = code[m.start():]
        cell_write = tail.find("cell_update")
        verify = [i for i in (tail.find("verifyDraftForSse("), tail.find("finalizeHeldOutput(")) if i >= 0]
        self.assertTrue(verify and min(verify) < cell_write,
                        "tabular generate sends/saves cell content before any Gate 1 call")


if __name__ == "__main__":
    unittest.main()
