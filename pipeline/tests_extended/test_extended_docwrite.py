"""Extended tier: the full variant lists of the document-write / MCP egress cases (main-verify tier split).

pipeline/tests/docwrite_bypass_cases.ts keeps one or two representatives per attack class in the signoff tier (each variant is a
real Gate 1 call). With DOCWRITE_FULL=1 the same file runs every variant: all five wrappers that hide runs from the matcher
(hyperlink, fldSimple, smartTag, moveTo, in-paragraph content control), tab and break, all eight separators, every reason / context
string, all seven replicate_document filename forms and all ten MCP argument encodings. Nothing in the signoff tier is weakened:
its cases are the same bodies over fewer variants, and the representatives named in the cases file stay there.

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
import test_docwrite_bypass as base  # noqa: E402


class DocWriteFullVariants(unittest.TestCase):
    report = None

    @classmethod
    def setUpClass(cls):
        if not base.TSX.exists():
            raise AssertionError("tsx is missing at %s; the document-write cases cannot run" % base.TSX)
        env = dict(os.environ)
        env["DOCWRITE_DB"] = str(fx.get_fixture().db)
        env["DOCWRITE_FULL"] = "1"
        p = subprocess.run([str(base.TSX), str(base.CASES)], capture_output=True, text=True, env=env,
                           cwd=str(fx.REPO), timeout=420)
        if p.returncode != 0:
            raise AssertionError("tsx failed (%s):\n%s" % (p.returncode, p.stderr[-3000:]))
        marker = "DOCWRITE_REPORT="
        i = p.stdout.rfind(marker)
        if i < 0:
            raise AssertionError("no report from the harness:\nstdout tail: %s" % p.stdout[-1500:])
        cls.report = json.loads(p.stdout[i + len(marker):].strip().splitlines()[0])

    def test_required_cases_ran(self):
        missing = base.EXPECTED_CASES - set(self.report)
        self.assertFalse(missing, "cases missing from the harness report: %s" % sorted(missing))

    def test_every_case_passes_over_every_variant(self):
        for name, failure in sorted(self.report.items()):
            with self.subTest(case=name):
                self.assertIsNone(failure, failure)


if __name__ == "__main__":
    unittest.main()
