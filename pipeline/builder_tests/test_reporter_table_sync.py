"""The reporter tables embedded in the TS gate must equal the ones derived from reporters_db."""

import json
import re
import unittest

from _fixture import REPO_ROOT
import json

from pipeline.gate1 import IN_SCOPE_LOOSE, KNOWN_REPORTERS, SOUTHERN_EXACT, _STATE_ABBREVS

TS_SRC = (REPO_ROOT / "backend" / "src" / "verification" / "local_sqlite_gate.ts").read_text(encoding="utf-8")


class TableSyncTests(unittest.TestCase):
    def test_southern_exact_table(self):
        block = re.search(r"const SOUTHERN_EXACT: Record<string, string> = \{(.*?)\n\};", TS_SRC, re.S).group(1)
        pairs = dict(re.findall(r"'([^']+)': '([^']+)'", block))
        self.assertEqual(pairs, SOUTHERN_EXACT)

    def test_in_scope_loose_set(self):
        block = re.search(r"const IN_SCOPE_LOOSE: ReadonlySet<string> = new Set\(\[(.*?)\]\);", TS_SRC, re.S).group(1)
        self.assertEqual(set(re.findall(r"'([^']+)'", block)), set(IN_SCOPE_LOOSE))

    def test_known_reporters(self):
        block = re.search(r"const KNOWN_REPORTERS: ReadonlySet<string> = new Set\(\[\n(.*?)\n\]\);", TS_SRC, re.S).group(1)
        self.assertEqual(frozenset(json.loads("[" + block + "]")), KNOWN_REPORTERS)

    def test_known_reporters_contents(self):
        for k in ["WL", "F.3d", "U.S.", "Fla.", "Fla. Supp.", "Fla. L. Weekly Fed. D", "So. 3d"]:
            self.assertIn(k, KNOWN_REPORTERS)
        for k in ["S0. 3d", "Zzz. 3d", "FIa. L. Weekly"]:
            self.assertNotIn(k, KNOWN_REPORTERS)

    def test_state_abbrevs(self):
        block = re.search(r"const STATE_ABBREVS = \[(.*?)\];", TS_SRC, re.S).group(1)
        self.assertEqual(tuple(re.findall(r"'([^']+)'", block)), _STATE_ABBREVS)

    def test_non_florida_court_regex_agrees(self):
        # Same positive-identification list, exercised through both gates in test_ts_parity;
        # here: the Python regex accepts and rejects what the lead's cases require.
        from pipeline.gate1 import _NON_FLORIDA_COURT as R
        for ok in ["Ala.", "Ala. Civ. App.", "Ala. Crim. App.", "La.", "La. App. 1 Cir.", "La. Ct. App.", "Miss.",
                   "Miss. Ct. App.", "5th Cir.", "S.D. Fla.", "Bankr. S.D. Fla.", "D.C. Cir.", "11th Cir."]:
            self.assertTrue(R.match(ok), ok)
        for bad in ["citation omitted", "Fia.", "F1a.", "Ga.", "S.D. Fia.", "Fla.", "La. App. 9 Cir.", "Floridian"]:
            self.assertFalse(R.match(bad), bad)

    def test_reporters_db_has_no_new_southern_edition(self):
        import reporters_db
        editions = set()
        for e in reporters_db.REPORTERS["So."]:
            editions.update(e["editions"])
        self.assertEqual(editions, {"So.", "So. 2d", "So. 3d"})


if __name__ == "__main__":
    unittest.main()
