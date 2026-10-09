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
        """Every runLLMStream caller under backend/src, the tabular chat call included (no exemption: merge blocker 4)."""
        callers = _llm_stream_callers()
        self.assertTrue(callers, "found no caller of runLLMStream; the test needs updating")
        # The tabular exemption is gone; make sure the call it covered is really being enforced.
        self.assertTrue(any(c[0] == TABULAR_TS and "TABULAR_TOOLS" in c[3] for c in callers),
                        "the tabular chat runLLMStream call (TABULAR_TOOLS) is not among the enforced callers")
        sys.stderr.write("runLLMStream callers enforced: %d\n" % len(callers))
        problems = _caller_problems(callers)
        self.assertEqual(problems, [], "LLM output can reach the client without Gate 1:\n" + "\n".join(problems))

    def test_tabular_chat_caller_of_run_llm_stream_buffers_and_finalizes(self):
        callers = [c for c in _llm_stream_callers() if c[0] == TABULAR_TS]
        self.assertTrue(callers, "found no runLLMStream caller in tabular.ts; the test needs updating")
        problems = _caller_problems(callers)
        self.assertEqual(problems, [], "tabular chat can reach the client without Gate 1:\n" + "\n".join(problems))

    def test_tabular_generate_does_not_stream_unverified_cells(self):
        # /:reviewId/generate does not go through runLLMStream: queryTabularAllColumns returns model-written cell
        # content that is saved and sent as cell_update. It must pass through Gate 1 before either.
        #
        # The gate is reached through gateCellContent( (hallucination_guard.ts), which calls finalizeHeldOutput( itself,
        # with a verify closure the route builds in cellGateOptions(). A bare textual "gateCellContent(" proves nothing
        # (any local function of that name would do), so the chain is proved link by link:
        #   1. the route calls the IMPORTED gateCellContent, before the first save or send of the cell;
        #   2. its options come from cellGateOptions(), whose verify is the production verifyDraftForSse (imported,
        #      not redefined in tabular.ts) with the real supabase client;
        #   3. gateCellContent awaits finalizeHeldOutput( with that same opts.verify, releases only a non-withheld,
        #      non-vetoed, non-error result, and otherwise returns a fixed marker.
        code = _code(TABULAR_TS.read_text(encoding="utf-8", errors="replace"))
        m = re.search(r"\bawait\s+queryTabularAllColumns\s*\(", code)
        self.assertIsNotNone(m, "found no queryTabularAllColumns call in tabular.ts; the test needs updating")
        tail = code[m.start():]
        cell_write = tail.find("cell_update")
        self.assertGreaterEqual(cell_write, 0, "no cell_update after queryTabularAllColumns; the test needs updating")
        save = tail.find('.from("tabular_cells")')
        first_sink = min(i for i in (cell_write, save) if i >= 0)

        # 1. the route's call, before any save or send
        g = re.search(r"(?<![\w.])gateCellContent\s*\(", tail)
        direct = [i for i in (tail.find("verifyDraftForSse("), tail.find("finalizeHeldOutput(")) if i >= 0]
        self.assertTrue(g or direct, "tabular generate sends/saves cell content before any Gate 1 call")
        gate_at = min([g.start()] if g else direct)
        self.assertLess(gate_at, first_sink, "tabular generate sends/saves cell content before any Gate 1 call")
        if not g:
            return  # a direct verifyDraftForSse / finalizeHeldOutput call before the sink is the old accepted shape

        # the name must be the one imported from the guard, not a local stand-in
        imp = re.search(r"import\s*\{([^}]*)\}\s*from\s*[\"']\.\./middleware/hallucination_guard[\"']", code)
        self.assertIsNotNone(imp, "tabular.ts no longer imports from ../middleware/hallucination_guard")
        imported = {s.strip() for s in imp.group(1).split(",") if s.strip()}
        for name in ("gateCellContent", "verifyDraftForSse"):
            self.assertIn(name, imported, "%s is not imported from the guard" % name)
            self.assertIsNone(re.search(r"(?:function|const|let|var)\s+%s\b" % name, code),
                              "tabular.ts defines its own %s; the gate is no longer the guard's" % name)

        # 2. the options passed are cellGateOptions(...), and its verify is the production closure
        args = _call_args(tail, g.end() - 1)
        self.assertIn("cellGateOptions(", args, "the gateCellContent call in generate is not given cellGateOptions(...): " + args[:200])
        fm = re.search(r"function\s+cellGateOptions\s*\(", code)
        self.assertIsNotNone(fm, "cellGateOptions is gone; the test needs updating")
        body = code[fm.start():fm.start() + 900]
        vm = re.search(r"\bverify\s*:\s*\(\s*text\b[^)]*\)\s*=>\s*verifyDraftForSse\s*\(\s*text\s*,", body)
        self.assertIsNotNone(vm, "cellGateOptions.verify is not (text) => verifyDraftForSse(text, ...): " + body[:300])
        vargs = _call_args(body, body.rfind("(", 0, vm.end()))
        self.assertRegex(vargs, r"supabase\s*:\s*db\b", "the production verifier is not given the route's database client")
        self.assertRegex(vargs, r"courtListenerToken", "the production verifier is not given the CourtListener token option")

        # 3. gateCellContent really runs finalizeHeldOutput over the cell with the verify it was handed
        guard = _code((BACKEND_SRC / "middleware" / "hallucination_guard.ts").read_text(encoding="utf-8", errors="replace"))
        gm = re.search(r"export\s+async\s+function\s+gateCellContent\s*\(", guard)
        self.assertIsNotNone(gm, "gateCellContent is not an exported async function of the guard")
        end = guard.find("\nexport ", gm.end())
        gbody = guard[gm.start():end if end > 0 else len(guard)]
        fin = re.search(r"await\s+finalizeHeldOutput\s*\(", gbody)
        self.assertIsNotNone(fin, "gateCellContent does not await finalizeHeldOutput(")
        fargs = _call_args(gbody, fin.end() - 1)
        self.assertRegex(fargs, r"verify\s*:\s*opts\.verify\b", "gateCellContent does not pass its caller's verify to finalizeHeldOutput")
        self.assertRegex(fargs, r"fullText\s*:\s*text\b")
        after = gbody[fin.end():]
        self.assertLess(after.find("out.withheld"), after.find("content: { summary, flag, reasoning"),
                        "gateCellContent builds the released cell before checking out.withheld")
        self.assertIn("out.verification.hasVetoes || out.verification.error", after)
        # the guard's own verifyDraftForSse is the production one: it calls verifyDraft and fails closed
        vd = re.search(r"export\s+async\s+function\s+verifyDraftForSse\s*\(", guard)
        self.assertIsNotNone(vd)
        self.assertIn("await verifyDraft(", guard[vd.start():vd.start() + 1200])
        self.assertIn("hasVetoes: true", guard[vd.start():vd.start() + 1200])


if __name__ == "__main__":
    unittest.main()
