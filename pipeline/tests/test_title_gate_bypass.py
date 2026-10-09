"""Chat titles (merge blocker 4, part C): bypass attacks on Gate 1 over model-written chat titles in
backend/src/routes/chat.ts (POST /chat/:chatId/generate-title) and the title code in
backend/src/middleware/hallucination_guard.ts (gateTitleText, userTitleFallback, TITLE_GATE_*)
(adversary vector 3: no execution flow where LLM generation reaches the client or the database without Gate 1).
The tabular chat title is attacked in test_tabular_bypass.py (class TabularChatTitle).

Behavioral part: pipeline/tests/title_gate_bypass_cases.ts runs once under backend's tsx against the REAL chat router
(the generate-title handler pulled out of the express stack) with the model, Supabase, auth and (except for the
"real_gate" cases) the Gate 1 verifier stubbed. The real_gate cases run the production verify closure and the Python
gate against the fixture database. No network. Assertions are on what can leave the server (the JSON body and the
database payloads), not on the mechanism, so any fix that closes the hole passes.

Static part: every database write of a chat title anywhere in backend/src is listed here. A new writer fails the test until
someone reviews whether its text is model text and adds it.

Expected against the current code: PASS everywhere except the one SKIPPED open item (stored titles are read back
as they were saved, including model-written titles saved before the gate existed).
"""

import json
import os
import re
import subprocess
import sys
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate1_fixture as fx  # noqa: E402

REPO = fx.REPO
TSX = REPO / "backend" / "node_modules" / ".bin" / "tsx"
CASES_TS = Path(__file__).resolve().parent / "title_gate_bypass_cases.ts"
SRC = REPO / "backend" / "src"
CHAT_TS = SRC / "routes" / "chat.ts"

_RUN = {}


def _run_cases():
    """One tsx process for the whole module."""
    if "data" not in _RUN:
        if not TSX.exists():
            raise AssertionError("tsx missing at %s; the title bypass cases cannot run (report it, do not skip it)" % TSX)
        env = dict(os.environ)
        env["KINGSFIELD_FLORIDA_DB"] = str(fx.get_fixture().db)
        proc = subprocess.run([str(TSX), str(CASES_TS)], capture_output=True, text=True, env=env,
                              cwd=str(REPO), timeout=120)
        if proc.returncode != 0:
            raise AssertionError("tsx failed (%d):\n%s" % (proc.returncode, proc.stderr[-2500:]))
        lines = [l for l in proc.stdout.splitlines() if l.strip()]
        _RUN["data"] = json.loads(lines[-1])
        if os.environ.get("KF_INFO"):
            sys.stderr.write("title_gate_bypass_cases info: %s\n" % json.dumps(_RUN["data"]["info"], sort_keys=True))
    return _RUN["data"]


class _Cases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = _run_cases()["results"]

    def _case(self, name):
        self.assertIn(name, self.report, "the harness did not run %s" % name)
        self.assertIsNone(self.report[name], self.report[name])


class FabricatedCiteInTheModelTitle(_Cases):
    """The model's title is saved and returned only if Gate 1 passed the exact normalized string."""

    def test_a_plain_fabricated_cite_never_reaches_the_json_or_the_database(self):
        self._case("title_plain_fabricated_cite_never_reaches_the_json_or_the_database")

    def test_quotes_markdown_whitespace_and_punctuation_do_not_hide_the_cite_and_the_gated_string_is_the_saved_string(self):
        self._case("title_padded_with_quotes_markdown_and_whitespace_is_gated_as_it_is_saved")

    def test_a_cite_cut_by_the_80_character_truncation_is_checked_as_cut_and_never_re_expanded(self):
        self._case("title_a_cite_cut_by_truncation_is_checked_as_cut_and_never_re_expanded")


class GateFailureModes(_Cases):
    def test_veto_pending_unknown_busy_error_throw_malformed_and_inconsistent_results_all_give_the_fallback_only(self):
        # 15 gate answers. Each: 200, body exactly {title: <the user's message>}, one write of exactly that,
        # no model word, no raw error text, nothing outside the chats table.
        self._case("title_every_gate_failure_mode_gives_the_fallback_and_nothing_else")

    def test_a_gate_that_never_answers_falls_back_ignores_its_late_answer_and_frees_the_slot(self):
        self._case("title_a_gate_that_never_answers_falls_back_ignores_the_late_answer_and_frees_the_slot")

    def test_more_hung_gates_than_limiter_slots_still_end_each_in_its_own_fallback(self):
        self._case("title_more_hung_gates_than_slots_still_end_each_in_its_own_fallback")

    def test_concurrent_requests_keep_their_own_verdicts(self):
        self._case("title_concurrent_requests_keep_their_own_verdicts")


class ModelCallAndSave(_Cases):
    def test_model_failures_save_nothing_return_the_fixed_500_and_empty_titles_become_the_fixed_title(self):
        self._case("title_model_failures_save_nothing_return_the_fixed_500_and_empty_titles_become_the_fixed_title")

    def test_a_failing_save_returns_only_fixed_text_or_the_gated_title(self):
        self._case("title_a_failing_save_returns_only_fixed_text_or_the_gated_title")


class FallbackIsUserText(_Cases):
    """The fallback is built from req.body.message. That is client-supplied (the route never reads the chat's stored
    messages), so it is user-controlled text, not model text. Recorded here, not a leak."""

    def test_fallback_is_only_the_requesters_message_flattened_and_cut(self):
        self._case("title_fallback_is_only_the_requesters_message_flattened_and_cut")

    def test_a_chat_the_user_cannot_reach_is_never_titled_and_the_model_is_never_called(self):
        self._case("title_a_chat_the_user_cannot_reach_is_never_titled")


class RealGate(_Cases):
    """The production verify closure against the fixture database. A title that survives these is a fabricated cite
    shown in the sidebar."""

    def test_obfuscated_and_near_miss_cites_fall_back(self):
        # Signoff tier: plain, no court parenthetical, full-width digits, period-less, a real record under another caption, a
        # markdown link title. The other nine forms run in pipeline/tests_extended/test_extended_title.py. Full list of 15:
        # plain, no court parenthetical, full-width digits, zero-width space (reporter and volume),
        # period-less, upper-case, Cyrillic o, OCR zero, Fla. L. Weekly, a real volume/page under another case's
        # caption, a real cite with a pin past the last page, a cite hidden in a markdown link title and in an HTML
        # attribute, a numeric-entity cite. One Python gate call each.
        self._case("title_real_gate_obfuscated_and_near_miss_cites_fall_back")

    def test_a_cite_cut_in_half_by_truncation_does_not_survive(self):
        self._case("title_real_gate_a_cite_cut_in_half_by_truncation_does_not_survive")

    def test_clean_titles_pass_and_a_cite_without_the_rest_of_the_pipeline_fails_closed(self):
        self._case("title_real_gate_clean_titles_pass_and_a_cite_without_the_rest_of_the_pipeline_fails_closed")


class StoredTitlesAreGatedOnRead(_Cases):
    """Titles saved before the title gate existed may be model-written. The read paths now re-gate them (the open item of
    round 3, un-skipped with its body unchanged): GET /chat/:chatId, GET /chat (the sidebar list) and, for tabular,
    GET /tabular-review/:reviewId/chats (test_tabular_bypass.py). GET /projects/:projectId/chats is checked statically below."""

    def test_stored_chat_titles_are_gated_on_read(self):
        self._case("open_stored_chat_titles_are_gated_on_read")

    def test_stored_chat_titles_are_gated_on_the_sidebar_list(self):
        self._case("stored_chat_titles_are_gated_on_the_list_route")

    def test_the_project_chat_list_gates_each_stored_title(self):
        code = _code((SRC / "routes" / "projects.ts").read_text(encoding="utf-8"))
        i = code.index("/:projectId/chats")
        sec = code[i:i + 3500]
        self.assertIn("gateTitleText(", sec, "GET /projects/:projectId/chats returns stored titles without Gate 1")


# ───── static: every writer of a chat title, and the shape of the generate-title handler ─────

def _code(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", line) for line in src.splitlines())


def _balanced(code, open_idx):
    """The text inside the parenthesis opened at code[open_idx] (strings are not parsed; none of the writers hold a stray paren)."""
    depth = 0
    for i in range(open_idx, len(code)):
        c = code[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return code[open_idx + 1:i]
    return code[open_idx + 1:]


CHAT_TABLE_RE = re.compile(r"""\.from\(\s*["'`](chats|tabular_review_chats)["'`]\s*\)""")
WRITE_RE = re.compile(r"\.(update|insert|upsert)\s*\(")
TITLE_KEY_RE = re.compile(r"(?<![\w.])title\b(?!\w)\s*(?=[:,}])")

# Every writer of a title column in backend/src: (file under backend/src, normalized argument) -> how many times.
# chat.ts: PATCH /:chatId (the client's own title) and generate-title (model title, gated).
# chat.ts, projectChat.ts: the streaming route saves the start of the user's own first message.
# tabular.ts: the model title, gated, in the tabular chat route.
ALLOWED_TITLE_WRITERS = Counter({
    ("routes/chat.ts", "{ title }"): 2,
    ("routes/chat.ts", "{ title: lastUser.content.slice(0, 120) }"): 1,
    ("routes/projectChat.ts", "{ title: lastUser.content.slice(0, 120) }"): 1,
    ("routes/tabular.ts", "{ title }"): 1,
})


def _title_writers():
    found = Counter()
    for path in sorted(SRC.rglob("*.ts")):
        if "node_modules" in path.parts:
            continue
        code = _code(path.read_text(encoding="utf-8", errors="replace"))
        rel = str(path.relative_to(SRC))
        for m in CHAT_TABLE_RE.finditer(code):
            tail = code[m.end():m.end() + 1500].split(";")[0]
            tail = re.split(r"\.from\(", tail)[0]
            for w in WRITE_RE.finditer(tail):
                arg = re.sub(r"\s+", " ", _balanced(tail, w.end() - 1)).strip()
                if arg.startswith("{"):
                    # An object literal without a `title` key and without a spread cannot set the title.
                    if not TITLE_KEY_RE.search(arg) and "..." not in arg:
                        continue
                found[(rel, arg)] += 1
    return found


class TitleWriters(unittest.TestCase):
    def test_the_only_writers_of_a_chat_title_are_the_reviewed_ones(self):
        found = _title_writers()
        unknown = {k: v for k, v in (found - ALLOWED_TITLE_WRITERS).items()}
        missing = {k: v for k, v in (ALLOWED_TITLE_WRITERS - found).items()}
        self.assertEqual(
            (unknown, missing), ({}, {}),
            "a database write of chats.title / tabular_review_chats.title that is not in the reviewed list "
            "(new writer: is its text model text? is it gated?) or a reviewed one that moved:\n"
            "unknown: %s\nmissing: %s" % (unknown, missing),
        )

    def test_the_scan_sees_the_writers_it_must_see(self):
        # Guards the scan itself: if the regexes stop matching, the test above would pass on an empty set.
        found = _title_writers()
        self.assertGreaterEqual(sum(found.values()), 5, found)

    def test_the_patch_route_saves_the_clients_own_title_and_calls_no_model(self):
        code = _code(CHAT_TS.read_text(encoding="utf-8"))
        i = code.index('chatRouter.patch("/:chatId"')
        j = code.index('chatRouter.delete("/:chatId"')
        sec = code[i:j]
        self.assertRegex(sec, r"const title = \(req\.body\.title \?\? \"\"\)\.trim\(\)")
        self.assertNotIn("completeText(", sec)
        self.assertNotIn("gateTitleText(", sec)


class GenerateTitleShape(unittest.TestCase):
    """Order and data flow in chat.ts generate-title (the behavior is in the cases above)."""

    @classmethod
    def setUpClass(cls):
        code = _code(CHAT_TS.read_text(encoding="utf-8"))
        i = code.index('chatRouter.post("/:chatId/generate-title"')
        j = code.index('chatRouter.post("/", requireAuth')
        cls.sec = code[i:j]

    def test_model_title_is_gated_before_it_is_saved_or_returned(self):
        sec = self.sec
        done = sec.index("await completeText(")
        gate = sec.index("gateTitleText(", done)
        save = sec.index('.from("chats")', gate)
        send = sec.index("res.json({ title })", save)
        self.assertTrue(done < gate < save < send)

    def test_the_raw_model_text_is_only_ever_passed_to_the_normalizer(self):
        # `titleText` is declared once and read once (normalizeGeneratedTitle(titleText)); a third mention is a new use.
        self.assertEqual(len(re.findall(r"\btitleText\b", self.sec)), 2, "titleText is used somewhere other than the normalizer")
        self.assertIn("normalizeGeneratedTitle(titleText)", self.sec)

    def test_the_saved_and_returned_title_is_the_gated_title(self):
        self.assertIn("const title = gated.title;", self.sec)
        self.assertRegex(self.sec, r"\.update\(\{\s*title\s*\}\)")
        self.assertEqual(len(re.findall(r"\.update\(", self.sec)), 1, "more than one write in generate-title")
        self.assertEqual(len(re.findall(r"res\.json\(", self.sec)), 1, "more than one success response in generate-title")
        # every assignment to a variable called `title` takes the gated title
        rhs = {m.group(1).strip() for m in re.finditer(r"(?<![\w.])title\s*=\s*([^;=]+);", self.sec)}
        self.assertEqual(rhs, {"gated.title"}, rhs)

    def test_the_fallback_is_built_from_the_request_message_only(self):
        self.assertRegex(self.sec, r"userTitleFallback\(message\)\s*\|\|\s*TITLE_FALLBACK")
        self.assertRegex(self.sec, r"const message =\s*typeof req\.body\?\.message === \"string\" \? req\.body\.message\.trim\(\) : \"\"")

    def test_errors_answer_with_fixed_text_and_log_through_safeErrorLog(self):
        self.assertRegex(self.sec, r"res\.status\(500\)\.json\(\{ detail: \"Failed to generate title\" \}\)")
        self.assertNotRegex(self.sec, r"\b(?:err|error)\.message")
        self.assertNotRegex(self.sec, r"detail:\s*(?:err|error)\b")


if __name__ == "__main__":
    unittest.main()
