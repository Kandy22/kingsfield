"""edit_document against the REAL tracked-changes engine, with a stub Gate 1 verifier (no Supabase, model or network).

Pins what the second gate pass relies on: the applied changes' contextBefore / contextAfter are the model's own strings
(not the text next to the change), so the pass gates windows of the document itself; the user's own text elsewhere is
not gated; a mutation of the user's cite that no model-written string contains is still caught.
"""

import json
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TSX = REPO_ROOT / "backend" / "node_modules" / ".bin" / "tsx"
CASES = REPO_ROOT / "pipeline" / "builder_tests" / "doc_write_engine_cases.ts"

EXPECTED = {
    "the_applied_changes_carry_the_models_context_not_the_documents",
    "a_changed_volume_in_the_users_cite_is_gated_from_the_document",
    "the_users_own_bad_cite_elsewhere_does_not_block_an_edit",
    "a_fragment_completed_by_the_text_next_to_it_is_gated",
    "a_clean_edit_next_to_a_clean_cite_is_written",
}


class EngineCases(unittest.TestCase):
    report = None

    @classmethod
    def setUpClass(cls):
        if not TSX.exists():
            raise unittest.SkipTest(f"tsx missing at {TSX}; report it, do not work around it")
        p = subprocess.run([str(TSX), str(CASES)], capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=120)
        if p.returncode != 0:
            raise AssertionError(f"tsx failed ({p.returncode}):\n{p.stderr[-3000:]}")
        marker = "ENGINE_REPORT="
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


if __name__ == "__main__":
    unittest.main()
