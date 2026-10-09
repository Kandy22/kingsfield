"""Extended tier: the full list of fabricated-title forms through the production gate (main-verify tier split).

pipeline/tests/title_gate_bypass_cases.ts keeps six representatives of the 15 forms in
title_real_gate_obfuscated_and_near_miss_cites_fall_back; with TITLE_FULL=1 the same case runs all 15. Same body, nothing
weakened: the signoff tier still runs a plain cite, no court, width-folded digits, period-less, a real record under another
caption, and a cite hidden in a markdown link title.

Run on its own:  ~/.venv-cascade/bin/python -m unittest discover --durations 5 pipeline/tests_extended
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent.parent / "tests"
sys.path.insert(0, str(TESTS))
import gate1_fixture as fx  # noqa: E402
import test_title_gate_bypass as base  # noqa: E402


class TitleRealGateFullList(unittest.TestCase):
    report = None

    @classmethod
    def setUpClass(cls):
        if not base.TSX.exists():
            raise AssertionError("tsx is missing at %s; the title cases cannot run" % base.TSX)
        env = dict(os.environ)
        env["KINGSFIELD_FLORIDA_DB"] = str(fx.get_fixture().db)
        env["TITLE_FULL"] = "1"
        p = subprocess.run([str(base.TSX), str(base.CASES_TS)], capture_output=True, text=True, env=env,
                           cwd=str(fx.REPO), timeout=300)
        if p.returncode != 0:
            raise AssertionError("tsx failed (%s):\n%s" % (p.returncode, p.stderr[-2500:]))
        cls.report = json.loads([l for l in p.stdout.splitlines() if l.strip()][-1])["results"]

    def test_every_form_falls_back(self):
        name = "title_real_gate_obfuscated_and_near_miss_cites_fall_back"
        self.assertIn(name, self.report)
        self.assertIsNone(self.report[name], self.report[name])

    def test_every_other_case_still_passes(self):
        for name, failure in sorted(self.report.items()):
            with self.subTest(case=name):
                self.assertIsNone(failure, failure)


if __name__ == "__main__":
    unittest.main()
