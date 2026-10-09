import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _fixture import REPO_ROOT, build_fixture_db  # noqa: F401  (sets sys.path)
from _cases import CASES, fuzz_cases
from pipeline import gate1
from pipeline.gate1 import check_citation, check_text

PY = os.path.expanduser("~/.venv-cascade/bin/python")


class Gate1PythonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp, cls.db, _ = build_fixture_db()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_table_cases(self):
        for cite, verdict, reason in CASES:
            with self.subTest(cite=cite[:80]):
                r = check_citation(cite, self.db)
                self.assertEqual(r.verdict, verdict, r)
                if reason is not None:
                    self.assertEqual(r.reason, reason, r)

    def test_pass_carries_cluster_and_key(self):
        r = check_citation("123 So. 3d 456 (Fla. 2013)", self.db)
        self.assertEqual((r.reporter, r.volume, r.page, r.cluster_id), ("So. 3d", 123, 456, 1))

    def test_alabama_row_excluded_from_index(self):
        # Cluster 5 (Alabama) shares the key So. 2d 100/20 with Florida cluster 2.
        r = check_citation("100 So. 2d 20 (Fla. 1950)", self.db)
        self.assertEqual(r.cluster_id, 2)

    def test_deterministic(self):
        cases = [c for c, _, _ in CASES] + fuzz_cases(100)
        a = [check_citation(c, self.db) for c in cases]
        b = [check_citation(c, self.db) for c in cases]
        self.assertEqual(a, b)

    def test_never_raises_on_junk(self):
        for junk in [None, 5, b"123 So. 3d 456", "\x00" * 10, "(" * 500, "9" * 3000, "123 So. 3d 456 (Fla. 2013)\x00"]:
            r = check_citation(junk, self.db)
            self.assertIn(r.verdict, ("veto", "pass", "fall_through"))
            if junk is None or junk in (5, b"123 So. 3d 456", "\x00" * 10, "(" * 500, "9" * 3000):
                self.assertEqual(r.verdict, "veto")

    # --- fail closed -----------------------------------------------------
    def test_missing_db_vetoes(self):
        r = check_citation("123 So. 3d 456 (Fla. 2013)", Path(self.tmp.name) / "nope.db")
        self.assertEqual((r.verdict, r.reason), ("veto", "db_unavailable"))

    def test_missing_db_does_not_create_file(self):
        p = Path(self.tmp.name) / "must_not_exist.db"
        check_citation("123 So. 3d 456 (Fla. 2013)", p)
        self.assertFalse(p.exists())

    def test_empty_db_file_vetoes(self):
        p = Path(self.tmp.name) / "empty.db"
        p.write_bytes(b"")
        self.assertEqual(check_citation("123 So. 3d 456 (Fla. 2013)", p).verdict, "veto")

    def test_garbage_db_file_vetoes(self):
        p = Path(self.tmp.name) / "garbage.db"
        p.write_bytes(b"this is not sqlite" * 100)
        self.assertEqual(check_citation("123 So. 3d 456 (Fla. 2013)", p).verdict, "veto")

    def test_missing_table_vetoes(self):
        p = Path(self.tmp.name) / "notable.db"
        conn = sqlite3.connect(p)
        conn.execute("CREATE TABLE other(x)")
        conn.commit()
        conn.close()
        r = check_citation("123 So. 3d 456 (Fla. 2013)", p)
        self.assertEqual((r.verdict, r.reason), ("veto", "db_unavailable"))

    def test_fall_through_needs_no_db(self):
        r = check_citation("123 F.3d 456 (11th Cir. 1999)", Path(self.tmp.name) / "nope.db")
        self.assertEqual(r.verdict, "fall_through")

    def test_db_is_not_modified(self):
        before = self.db.read_bytes()
        for c, _, _ in CASES:
            check_citation(c, self.db)
        self.assertEqual(self.db.read_bytes(), before)

    def test_readonly_connection(self):
        # The gate must not be able to write even if asked to.
        uri = self.db.resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        with self.assertRaises(sqlite3.OperationalError):
            conn.execute("DELETE FROM citation_index")
        conn.close()

    # --- text extraction -------------------------------------------------
    def test_check_text(self):
        text = ("The court in Smith v. Jones, 123 So. 3d 456, 460 (Fla. 2013), held; see also "
                "Roe v. Wade, 410 U.S. 113 (1973). Also Fake v. Thing, 999 So. 2d 5 (Fla. 2d DCA 2000). "
                "And 45 Fla. L. Weekly D123 and Alpha Corp. v. Beta Holdings, Inc., 321 So. 3d 789, 790 "
                "(Fla. 3d DCA 2020). See Fake v. Case, 123 So. 3d 456 (Fla. 2013).")
        got = [(r.verdict, r.reason) for r in check_text(text, self.db)]
        self.assertEqual(got, [("pass", "verified"), ("fall_through", "not_florida_key"), ("veto", "not_found"),
                               ("pass", "verified"), ("pass", "verified"), ("veto", "caption_mismatch")])

    def test_check_text_no_citations(self):
        self.assertEqual(check_text("No citations here.", self.db), [])

    def test_check_text_hidden_fabricated_cites_never_vanish(self):
        fake = "Fake v. Thing, 999 So. 3d 5 (Fla. 2012)"
        variants = {
            "zero_width_in_reporter": "999 So.\u200b 3d 5 (Fla. 2012)",
            "zero_width_before_dot": "999 So\u200b. 3d 5 (Fla. 2012)",
            "bom": "999 \ufeffSo. 3d 5 (Fla. 2012)",
            "soft_hyphen": "999 So.\u00ad 3d 5 (Fla. 2012)",
            "cyrillic_o": "999 S\u043e. 3d 5 (Fla. 2012)",
            "cyrillic_s": "999 \u0405o. 3d 5 (Fla. 2012)",
            "greek_omicron": "999 S\u03bf. 3d 5 (Fla. 2012)",
            "cyrillic_weekly": "45 Fla. L. W\u0435ekly D9",
            "arabic_digits_volume": "\u0669\u0669\u0669 So. 3d 5 (Fla. 2012)",
        }
        self.assertEqual(check_text(fake, self.db)[0].verdict, "veto")
        for name, cite in variants.items():
            with self.subTest(name):
                got = check_text("As the court said, " + cite + ", the rule is clear.", self.db)
                self.assertTrue(got, "fabricated cite vanished")
                self.assertTrue(all(r.verdict == "veto" for r in got), got)

    def test_check_text_prose_with_non_ascii_is_not_flagged(self):
        got = check_text("The caf\u00e9 sold 5 \u00fcber 7 items; Smith v. Jones, 123 So. 3d 456 (Fla. 2013).", self.db)
        self.assertEqual([r.verdict for r in got], ["pass"])

    def test_check_text_zero_width_stripped_real_cite_still_checked(self):
        got = check_text("123 So.\u200b 3d 456 (Fla. 2013)", self.db)
        self.assertEqual([(r.verdict, r.cluster_id) for r in got], [("pass", 1)])

    def test_check_text_catches_what_eyecite_misses(self):
        # eyecite does not report a Southern Reporter variant like 'South. 3d'... the scan does.
        got = check_text("As held, 123 SO. 3D 456 (Fla. 2013) controls.", self.db)
        self.assertEqual([r.verdict for r in got], ["veto"])

    # --- CLI ---------------------------------------------------------------
    def test_cli_json(self):
        out = subprocess.run(
            [PY, str(REPO_ROOT / "pipeline" / "gate1.py"), "--db", str(self.db), "--citation=123 So. 3d 456 (Fla. 2013)"],
            capture_output=True, text=True, check=True, cwd="/",
        ).stdout
        j = json.loads(out)
        self.assertEqual((j["verdict"], j["cluster_id"], j["reporter"]), ("pass", 1, "So. 3d"))


class CaptionTests(unittest.TestCase):
    def test_similarity_rules(self):
        ok = gate1.caption_matches
        self.assertTrue(ok("Smith v. Jones", "Smith v. Jones")[0])
        self.assertTrue(ok("SMITH V. JONES", "Smith v. Jones, et al.")[0])
        self.assertTrue(ok("Smith & Sons v. Jones", "Smith and Sons v. Jones")[0])
        self.assertTrue(ok("O\u2019Brien v. State", "O'Brien v. State")[0])
        self.assertFalse(ok("Totally Fake v. Case", "Smith v. Jones")[0])
        self.assertFalse(ok("Smith v. Jones", None)[0])
        self.assertFalse(ok("Smith v. Jones", "   ")[0])
        self.assertFalse(ok("Sm\u0456th v. Jones", "Smith v. Jones")[0])


if __name__ == "__main__":
    unittest.main()
