"""runCaseExtraction gates the extraction BEFORE it is saved (adversary class e, main-verify round 2).

caseIntelligence.ts gates JSON.stringify(intel). A control character in a model string (backspace, \\u000b, \\u001f) is spelled as a
backslash sequence there, so a cite it splits is not read; the row is saved and only the read-time re-check (GET /analytics) and the
POST /analytics/extract re-check stop it. Either fix passes: gate the decoded strings in caseIntelligence.ts (outside the builder's
write scope), or make gate1.py read JSON control escapes.
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate1_fixture as fx  # noqa: E402

TSX = fx.REPO / "backend" / "node_modules" / ".bin" / "tsx"
CASES = Path(__file__).resolve().parent / "case_extraction_cases.ts"


class CaseExtractionGate(unittest.TestCase):
    report = None

    @classmethod
    def setUpClass(cls):
        if not TSX.exists():
            raise AssertionError("tsx missing at %s" % TSX)
        env = dict(os.environ)
        env["KINGSFIELD_FLORIDA_DB"] = str(fx.get_fixture().db)
        p = subprocess.run([str(TSX), str(CASES)], capture_output=True, text=True, env=env, cwd=str(fx.REPO), timeout=150)
        if p.returncode != 0:
            raise AssertionError("tsx failed (%d):\n%s" % (p.returncode, p.stderr[-2000:]))
        cls.report = json.loads([l for l in p.stdout.splitlines() if l.strip()][-1])["results"]

    def _case(self, name):
        self.assertIn(name, self.report)
        if self.report[name] is not None:
            self.fail(str(self.report[name])[:500])

    def test_control(self):
        self._case("control_a_clean_extraction_is_saved")

    def test_a_fabricated_cite_is_not_saved(self):
        self._case("a_fabricated_cite_is_not_saved")

    def test_a_cite_glued_by_a_control_character_is_not_saved(self):
        self._case("a_cite_glued_by_a_control_character_is_not_saved")


    def test_a_cite_in_an_object_key_is_not_saved(self):
        self._case("a_cite_in_an_object_key_is_not_saved")

    def test_escaped_separator_spellings_are_not_saved(self):
        self._case("escaped_separator_spellings_are_not_saved")


if __name__ == "__main__":
    unittest.main()
