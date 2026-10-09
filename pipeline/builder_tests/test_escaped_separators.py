"""Escaped-separator spellings (\\n, \\u000a, \\x0a, ...) read as a space, never glue a cite together."""

import unittest

from _draft_fixture import build_draft_db
from pipeline import gate1
from pipeline.gate1 import check_text

SPELLINGS = ["\\n", "\\r", "\\t", "\\u000a", "\\u000A", "\\u000d\\u000a", "\\u000D\\u000A", "\\x0a", "\\x0A",
             "\\x0d\\x0a", "\\u2028", "\\u2029", "\\u0085", "\\u00a0", "\\x85", "\\xa0", "\\u0009"]


class EscapedSeparators(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp, cls.db = build_draft_db()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_each_spelling_becomes_a_separator(self):
        for sp in SPELLINGS:
            cleaned = gate1._clean_draft("Doe v. Roe, 999" + sp + "So. 3d 999 (Fla. 2015).")
            self.assertIn("999 So. 3d 999", cleaned, sp)

    def test_each_spelling_cannot_hide_a_nonexistent_cite(self):
        for sp in SPELLINGS:
            got = check_text("Doe v. Roe, 999" + sp + "So. 3d 999 (Fla. 2015).", self.db)
            self.assertTrue(got, sp)
            self.assertTrue(all(r.verdict == "veto" for r in got), (sp, [(r.verdict, r.reason) for r in got]))

    def test_literal_control_escapes_read_as_separators(self):
        for sp in ["\\b", "\\u0008", "\\u0000", "\\u001f", "\\u001F", "\\x08", "\\x00", "\\x1f"]:
            cleaned = gate1._clean_draft("Doe v. Roe, 999" + sp + "So. 3d 999 (Fla. 2015).")
            self.assertIn("999 So. 3d 999", cleaned, sp)
            got = check_text("Doe v. Roe, 999" + sp + "So. 3d 999 (Fla. 2015).", self.db)
            self.assertTrue(got and all(r.verdict == "veto" for r in got), sp)

    def test_regexish_and_path_text_keeps_real_cite_passing(self):
        for txt in ["\\bword\\b Smith v. Jones, 123 So. 3d 456 (Fla. 2013).",
                    "C:\\Users\\bob\\file.txt Smith v. Jones, 123 So. 3d 456 (Fla. 2013).",
                    "Smith v. Jones, 123 So. 3d 456 (Fla. 2013)\\b."]:
            ok = check_text(txt, self.db)
            self.assertEqual([r.verdict for r in ok], ["pass"], txt)

    def test_real_cite_and_legitimate_backslashes_unchanged(self):
        ok = check_text("Smith v. Jones, 123 So. 3d 456 (Fla. 2013).", self.db)
        self.assertEqual([r.verdict for r in ok], ["pass"])
        esc = check_text("Smith v. Jones, 123 So. 3d 456 \\(Fla. 2013\\).", self.db)
        self.assertEqual([r.verdict for r in esc], ["pass"])
        self.assertEqual(gate1._clean_draft("a\\/b"), "a/b")


if __name__ == "__main__":
    unittest.main()
