import sqlite3
import tempfile
import unittest
from pathlib import Path

from _fixture import build_fixture_db, write_corpus
from db.build_sqlite_index import build_index, canonical_reporter


class BuildIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.db, self.stats = build_fixture_db()
        self.conn = sqlite3.connect(self.db)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def rows(self, sql, *a):
        return self.conn.execute(sql, a).fetchall()

    def test_btree_index_on_reporter_volume_page(self):
        idx = self.rows("SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_citation_rvp'")
        self.assertEqual(len(idx), 1)
        self.assertIn("ON citation_index(reporter, volume, page, section)", idx[0][0])
        plan = " ".join(str(r) for r in self.rows(
            "EXPLAIN QUERY PLAN SELECT * FROM citation_index WHERE reporter=? AND volume=? AND page=?", "So. 3d", 123, 456))
        self.assertIn("idx_citation_rvp", plan)

    def test_citation_index_columns(self):
        cols = [r[1] for r in self.rows("PRAGMA table_info(citation_index)")]
        self.assertEqual(cols, ["reporter", "volume", "page", "section", "cluster_id", "case_name", "court_id", "first_page", "last_page"])

    def test_only_florida_keys_kept(self):
        self.assertEqual({r[0] for r in self.rows("SELECT DISTINCT reporter FROM citation_index")},
                         {"So.", "So. 2d", "So. 3d", "Fla. L. Weekly", "Fla. L. Weekly Supp."})
        # Alabama cluster 5 and the F.3d row are gone; duplicate row collapsed.
        self.assertEqual(self.rows("SELECT COUNT(*) FROM citation_index WHERE cluster_id=5")[0][0], 0)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM citation_index WHERE cluster_id=8")[0][0], 1)

    def test_weekly_kept_regardless_of_court(self):
        r = self.rows("SELECT court_id, last_page FROM citation_index WHERE cluster_id IN (6, 9, 10)")
        self.assertEqual(r, [(None, None)] * 3)
        r = self.rows("SELECT cluster_id, court_id FROM citation_index WHERE cluster_id IN (11, 12) ORDER BY 1")
        self.assertEqual(r, [(11, "fladistctapp"), (12, "fla")])

    def test_weekly_section_split(self):
        rows = self.rows("SELECT volume, page, section, cluster_id FROM citation_index "
                         "WHERE reporter='Fla. L. Weekly' ORDER BY cluster_id")
        self.assertEqual(rows, [(45, 123, "D", 6), (45, 123, "S", 9), (45, 123, "", 10), (46, 7, "D", 11)])

    def test_section_empty_for_southern(self):
        self.assertEqual(self.rows("SELECT DISTINCT section FROM citation_index WHERE reporter LIKE 'So.%'"), [("",)])

    def test_split_page(self):
        from db.build_sqlite_index import split_page
        self.assertEqual(split_page("Fla. L. Weekly", "D500"), ("D", 500))
        self.assertEqual(split_page("Fla. L. Weekly", "500"), ("", 500))
        self.assertIsNone(split_page("Fla. L. Weekly", "DD500"))
        self.assertIsNone(split_page("Fla. L. Weekly", "d500"))
        self.assertIsNone(split_page("So. 3d", "D5"))
        self.assertIsNone(split_page("Fla. L. Weekly Supp.", "D5"))
        self.assertEqual(split_page("So. 3d", "456"), ("", 456))

    def test_missing_bounds_means_null_last_page(self):
        self.assertEqual(self.rows("SELECT first_page, last_page FROM citation_index WHERE cluster_id=4"), [(1, None)])
        self.assertEqual(self.rows("SELECT first_page, last_page FROM citation_index WHERE cluster_id=1"), [(456, 470)])

    def test_bad_page_skipped_and_counted(self):
        self.assertEqual(self.stats["skipped_bad_page"], 1)

    def test_schema_separation(self):
        # Constraint B: opinion text only in caselaw_opinion; caselaw_analysis created empty.
        self.assertEqual(self.rows("SELECT COUNT(*) FROM caselaw_analysis")[0][0], 0)
        self.assertEqual(self.rows("SELECT plain_text FROM caselaw_opinion")[0][0], "Plain text of Smith v. Jones.")
        self.assertEqual(self.rows("SELECT COUNT(*) FROM caselaw_opinion WHERE cluster_id=5")[0][0], 0)
        opinion_cols = {r[1] for r in self.rows("PRAGMA table_info(caselaw_opinion)")}
        analysis_cols = {r[1] for r in self.rows("PRAGMA table_info(caselaw_analysis)")}
        self.assertEqual(opinion_cols & analysis_cols, {"cluster_id"})
        self.assertNotIn("summary", opinion_cols)
        self.assertNotIn("plain_text", analysis_cols)
        index_cols = {r[1] for r in self.rows("PRAGMA table_info(citation_index)")}
        self.assertFalse(index_cols & {"plain_text", "summary", "goodlaw_tag"})

    def test_no_editorial_content_ingested(self):
        dump = "\n".join(self.conn.iterdump())
        self.assertNotIn("HEADNOTE", dump)

    def test_unicode_case_name_roundtrip(self):
        self.assertEqual(self.rows("SELECT case_name FROM citation_index WHERE cluster_id=7")[0][0], "Peña v. State")

    def test_optional_files_absent(self):
        with tempfile.TemporaryDirectory() as d:
            corpus = Path(d) / "c"
            corpus.mkdir()
            write_corpus(corpus, with_bounds=False, with_opinions=False)
            stats = build_index(corpus, Path(d) / "x.db")
            self.assertEqual(stats["opinions_inserted"], 0)
            c = sqlite3.connect(Path(d) / "x.db")
            self.assertEqual(c.execute("SELECT COUNT(*) FROM citation_index WHERE last_page IS NOT NULL").fetchone()[0], 0)
            c.close()

    def test_missing_required_file_raises_and_leaves_no_db(self):
        with tempfile.TemporaryDirectory() as d:
            corpus = Path(d) / "c"
            corpus.mkdir()
            out = Path(d) / "x.db"
            with self.assertRaises(FileNotFoundError):
                build_index(corpus, out)
            self.assertFalse(out.exists())

    def test_failed_build_leaves_no_partial_db(self):
        with tempfile.TemporaryDirectory() as d:
            corpus = Path(d) / "c"
            corpus.mkdir()
            write_corpus(corpus)
            (corpus / "citations-2026-01-01.csv").write_bytes(b"id,volume,reporter,page,type,cluster_id\n1,1,So. 3d,1,1,1\n\xff\xfe")
            out = Path(d) / "x.db"
            try:
                build_index(corpus, out)
            except Exception:
                pass
            self.assertFalse(Path(str(out) + ".tmp").exists())

    def test_huge_field_does_not_break_csv(self):
        with tempfile.TemporaryDirectory() as d:
            corpus = Path(d) / "c"
            corpus.mkdir()
            write_corpus(corpus, with_opinions=False)
            big = "x" * 500_000
            (corpus / "opinions-big.csv").write_text(f'id,cluster_id,plain_text\n900,1,"{big}"\n', encoding="utf-8")
            stats = build_index(corpus, Path(d) / "x.db")
            self.assertEqual(stats["opinions_inserted"], 1)

    def test_canonical_reporter(self):
        self.assertEqual(canonical_reporter("So.3d"), "So. 3d")
        self.assertEqual(canonical_reporter("So. 2d"), "So. 2d")
        self.assertEqual(canonical_reporter("Fla. L. Weekly Supp."), "Fla. L. Weekly Supp.")
        self.assertIsNone(canonical_reporter("Fla. L. Weekly Fed. D"))
        self.assertIsNone(canonical_reporter("F.3d"))

    def test_build_is_deterministic(self):
        t2, db2, _ = build_fixture_db()
        try:
            c2 = sqlite3.connect(db2)
            a = self.rows("SELECT * FROM citation_index ORDER BY 1,2,3,4")
            b = c2.execute("SELECT * FROM citation_index ORDER BY 1,2,3,4").fetchall()
            c2.close()
            self.assertEqual(a, b)
        finally:
            t2.cleanup()


if __name__ == "__main__":
    unittest.main()
