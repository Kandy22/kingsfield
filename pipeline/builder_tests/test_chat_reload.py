"""A vetoed chat survives a reload: persisted by the real POST routes, read back by the real GET /chat/:chatId.

Why this exists: the title read-gate changed the shape of the GET handler's response line, which the adversary's static
check (pipeline/tests/test_boundaries_and_schema.py, test_a_veto_survives_a_reload_of_the_chat) pins with
`res.json({ chat, messages: hydrated })`. The behaviour is proven here at runtime instead, and the static half pins the
new shape (see GetShape) so a future change to it is noticed.
"""

import json
import re
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TSX = REPO_ROOT / "backend" / "node_modules" / ".bin" / "tsx"
CASES = REPO_ROOT / "pipeline" / "builder_tests" / "chat_reload_cases.ts"
CHAT = REPO_ROOT / "backend" / "src" / "routes" / "chat.ts"

EXPECTED = {
    "chat_route_a_vetoed_reply_is_stored_and_a_reload_shows_the_veto",
    "project_route_a_vetoed_reply_is_stored_and_a_reload_shows_the_veto",
    "a_withheld_reply_after_a_gate_error_reloads_as_unverified",
    "a_clean_reply_reloads_unchanged_with_a_clean_record",
    "a_failed_stream_reloads_as_the_fixed_marker_only",
    "the_title_read_gate_replaces_a_bad_stored_title_and_leaves_the_messages_alone",
    "a_failing_title_gate_does_not_hide_or_reshape_the_messages",
}


class ReloadCases(unittest.TestCase):
    report = None

    @classmethod
    def setUpClass(cls):
        if not TSX.exists():
            raise unittest.SkipTest(f"tsx missing at {TSX}; report it, do not work around it")
        p = subprocess.run([str(TSX), str(CASES)], capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=120)
        if p.returncode != 0:
            raise AssertionError(f"tsx failed ({p.returncode}):\n{p.stderr[-3000:]}")
        marker = "RELOAD_REPORT="
        i = p.stdout.rfind(marker)
        if i < 0:
            raise AssertionError(f"no report:\n{p.stdout[-1500:]}\n{p.stderr[-1500:]}")
        cls.report = json.loads(p.stdout[i + len(marker):].strip().splitlines()[0])

    def test_required_cases_ran(self):
        self.assertTrue(EXPECTED <= set(self.report), EXPECTED - set(self.report))

    def test_every_case_passes(self):
        for name, failure in sorted(self.report.items()):
            with self.subTest(case=name):
                self.assertIsNone(failure, failure)


class GetShape(unittest.TestCase):
    """The reload response line: messages go out as hydrated, untouched; only the chat row's title is gated."""

    def test_get_chat_returns_hydrated_messages_unchanged_and_a_gated_title(self):
        src = CHAT.read_text(encoding="utf-8")
        start = src.index('chatRouter.get("/:chatId"')
        end = src.index('chatRouter.patch("/:chatId"')
        reload_path = src[start:end]
        self.assertRegex(
            reload_path,
            r"res\.json\(\{\s*chat:\s*\{\s*\.\.\.chat\s*,\s*title:\s*await gatedStoredTitle\(chat\.title,\s*db\)\s*\}\s*,"
            r"\s*messages:\s*hydrated\s*\}\)",
        )
        self.assertRegex(reload_path, r"from\(\"chat_messages\"\)\s*\.select\(\"\*\"\)")
        self.assertIn("hydrateEditStatuses(messages ?? [], db)", reload_path)
        # the gate is applied to the title only
        self.assertEqual(len(re.findall(r"gatedStoredTitle\(", reload_path)), 1)


if __name__ == "__main__":
    unittest.main()
