"""Gate 1 over model-written chat titles (tabular-docwrite-verify, part C).

title_gate_cases.ts runs the REAL chat router (POST /chat/:chatId/generate-title) and the guard helpers
gateTitleText / userTitleFallback once under backend's tsx, with the model, Supabase, auth and the Gate 1 verifier
stubbed; every named case becomes a subTest. A second group checks the wiring statically in routes/chat.ts,
routes/projectChat.ts and routes/tabular.ts. The tabular chat title is exercised behaviourally in
test_tabular_route.py.
"""

import json
import re
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TSX = REPO_ROOT / "backend" / "node_modules" / ".bin" / "tsx"
CASES = REPO_ROOT / "pipeline" / "builder_tests" / "title_gate_cases.ts"
ROUTES = REPO_ROOT / "backend" / "src" / "routes"
GUARD = REPO_ROOT / "backend" / "src" / "middleware" / "hallucination_guard.ts"

EXPECTED_CASES = {
    "fallback_is_the_start_of_the_users_text_flattened_and_cut",
    "gate_clean_title_is_returned_unchanged_after_one_gate_call",
    "gate_veto_uses_the_fallback_and_never_the_model_text",
    "gate_pending_unknown_status_and_whole_draft_placeholder_use_the_fallback",
    "gate_error_throw_malformed_and_null_use_the_fallback_and_log_the_raw_error_only",
    "gate_busy_answer_from_the_real_gate_uses_the_fallback",
    "gate_timeout_uses_the_fallback_frees_the_slot_and_ignores_the_late_answer",
    "gate_blank_or_non_string_titles_use_the_fallback_without_calling_the_gate",
    "gate_a_non_string_fallback_becomes_an_empty_string_not_model_text",
    "gate_module_limiter_has_a_cap_and_the_75s_limit",
    "route_clean_title_is_gated_then_saved_and_returned_as_the_same_string",
    "route_vetoed_title_saves_and_returns_the_start_of_the_users_message",
    "route_fallback_is_cut_to_120_characters",
    "route_pending_unknown_gate_error_throw_malformed_and_null_use_the_fallback",
    "route_a_gate_that_never_answers_times_out_to_the_fallback",
    "route_the_exact_normalized_string_is_what_the_gate_sees_and_what_is_saved",
    "route_a_cite_that_truncation_leaves_at_the_end_is_checked_as_cut",
    "route_an_empty_model_title_becomes_the_fixed_misc_query_after_the_gate",
    "route_the_users_own_cite_in_the_fallback_is_not_gated",
    "route_a_failed_title_save_still_returns_only_the_gated_title_and_leaks_nothing",
    "route_model_failure_keeps_the_existing_fixed_500_and_saves_nothing",
    "route_missing_message_and_missing_chat_still_answer_before_any_model_or_gate_call",
}


class TitleGateCases(unittest.TestCase):
    report = None

    @classmethod
    def setUpClass(cls):
        if not TSX.exists():
            raise unittest.SkipTest(f"tsx missing at {TSX}; report it, do not work around it")
        p = subprocess.run([str(TSX), str(CASES)], capture_output=True, text=True,
                           cwd=str(REPO_ROOT), timeout=120)
        if p.returncode != 0:
            raise AssertionError(f"tsx failed ({p.returncode}):\n{p.stderr[-3000:]}")
        try:
            cls.report = json.loads(p.stdout)
        except ValueError:
            raise AssertionError(f"tsx printed no JSON report:\nstdout: {p.stdout[-1500:]!r}\nstderr: {p.stderr[-1500:]}")

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


class Wiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chat = _code((ROUTES / "chat.ts").read_text(encoding="utf-8"))
        cls.project = _code((ROUTES / "projectChat.ts").read_text(encoding="utf-8"))
        cls.tabular = _code((ROUTES / "tabular.ts").read_text(encoding="utf-8"))
        cls.guard = _code(GUARD.read_text(encoding="utf-8"))

    def test_chat_generate_title_gates_the_normalized_title_before_save_and_return(self):
        i = self.chat.index('chatRouter.post("/:chatId/generate-title"')
        j = self.chat.index('chatRouter.post("/", requireAuth')
        sec = self.chat[i:j]
        done = sec.index("completeText(")
        gate = sec.index("gateTitleText(", done)
        norm = sec.index("normalizeGeneratedTitle(titleText)", done)
        save = sec.index('.from("chats")', gate)
        send = sec.index("res.json({ title })", save)
        self.assertTrue(done < norm < gate or done < gate < norm)
        self.assertTrue(gate < save < send)
        self.assertIn("verifyDraftForSse(text", sec)
        self.assertIn("userTitleFallback(message)", sec)
        self.assertIn("const title = gated.title;", sec)
        # Nothing but the gated title is saved or returned.
        self.assertNotRegex(sec, r"update\(\{\s*title:\s*titleText")
        self.assertNotRegex(sec, r"json\(\{\s*title:\s*titleText")
        # Raw errors go to safeErrorLog only; the reply carries fixed text.
        for m in re.finditer(r"\berr\b", sec):
            before = sec[: m.start()]
            if before.endswith("catch ("):
                continue
            self.assertTrue(before.endswith("safeErrorLog("), sec[max(0, m.start() - 40): m.end() + 10])
        self.assertNotRegex(sec, r"detail:\s*(error|err)\b")
        self.assertNotRegex(sec, r"\b(?:err|error)\.message")

    def test_chat_route_title_has_no_other_model_title_writer(self):
        # The only model-written chat title is generate-title; the streaming route saves the user's own text.
        for name, src in (("chat.ts", self.chat), ("projectChat.ts", self.project)):
            self.assertEqual(src.count("completeText("), 1 if name == "chat.ts" else 0, name)
            for m in re.finditer(r"update\(\{\s*title:\s*([^}]*)\}", src):
                self.assertIn("lastUser.content", m.group(1), f"{name}: a title saved from something other than the user's text")

    def test_tabular_title_is_gated_before_it_is_saved_and_sent(self):
        i = self.tabular.index('tabularRouter.post("/:reviewId/chat"')
        j = self.tabular.index("function parseCellContent(")
        sec = self.tabular[i:j]
        gen = sec.index("await generateChatTitle(")
        gate = sec.index("gateTitleText(", gen)
        save = sec.index('.update({ title })', gate)
        send = sec.index('type: "chat_title"', save)
        self.assertTrue(gen < gate < save < send)
        self.assertIn("userTitleFallback(lastUser.content)", sec)
        self.assertIn("title = gatedTitle.title;", sec)
        self.assertIn('cellGateOptions(db, "tabular/chat")', sec)
        # Only one title save and one chat_title event, both of the gated `title`.
        self.assertEqual(sec.count('type: "chat_title"'), 1)
        self.assertEqual(sec.count(".update({ title })"), 1)
        self.assertIn('{ type: "chat_title", chatId, title }', sec)
        # A title failure only logs (the reply is already saved and sent) and falls back to the user's text.
        self.assertRegex(sec, r"\} catch \(titleErr\) \{\s*console\.error\(\"\[tabular/chat\] title\", safeErrorLog\(titleErr\)\);\s*title = fallbackTitle;")

    def test_guard_title_gate_is_total_and_limited(self):
        i = self.guard.index("export async function gateTitleText(")
        sec = self.guard[i: self.guard.index("export interface HallucinationGuardOptions", i)]
        self.assertIn("safeVerify(opts.verify, title)", sec)
        self.assertIn("isClean(r)", sec)
        self.assertIn("} catch (err: any) {", sec)
        self.assertRegex(self.guard, r"const limitTitleGate = createLimiter\(TITLE_GATE_CONCURRENCY, \{ timeoutMs: TITLE_GATE_TIMEOUT_MS \}\);")
        self.assertRegex(self.guard, r"export const TITLE_GATE_TIMEOUT_MS = 75_000;")
        # The fallback is returned, never the model title, on every non-clean path.
        self.assertEqual(sec.count("return { title, usedFallback: false, reason: null };"), 1)


if __name__ == "__main__":
    unittest.main()
