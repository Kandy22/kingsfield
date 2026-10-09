"""Inferred page bounds (db/build_sqlite_index.py): last_page from the next case in the same
reporter + volume (+ section for Fla. L. Weekly), bounds_source marking, CAP precedence,
and the gate's pin check against the resulting rows. Tiny temp-dir fixtures only."""

import contextlib
import io
import sqlite3
import sys
import tempfile
import unittest
from array import array
from pathlib import Path
from unittest import mock

# Runnable as `-m unittest pipeline.builder_tests.test_bounds_inference` as well as by discovery.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _fixture import REPO_ROOT, _write  # noqa: E402  (also puts the repo root on sys.path)
from db import build_sqlite_index as bsi
from db.build_sqlite_index import build_index, infer_last_page
from pipeline import gate1

DOCKETS = [("1", "fla"), ("2", "fladistctapp"), ("3", "ala"), ("5", "flsd")]
CLUSTERS = [
    ("1", "Alpha v. One", "1"),
    ("2", "Bravo v. Two", "2"),
    ("3", "Charlie v. Alabama", "3"),
    ("4", "Delta v. Four", "2"),
    ("5", "Echo v. Five", "1"),
    ("6", "Foxtrot v. Six", "2"),
    ("7", "Weekly Seven v. Example", "5"),
    ("8", "Weekly Eight v. Example", "5"),
    ("9", "Weekly Nine v. Example", "5"),
    ("10", "Weekly Ten v. Example", "5"),
    ("11", "Supp One v. Example", "5"),
    ("12", "Supp Two v. Example", "5"),
    ("13", "Weekly Thirteen v. Example", "5"),
]
# (volume, reporter, page, cluster_id)
CITATIONS = [
    # So. 2d vol 10: 1@100, Alabama 3@150, 2@200, 4@300 and 6@300 (same page), 5@400.
    ("10", "So. 2d", "100", "1"),
    ("10", "So. 2d", "150", "3"),
    ("10", "So. 2d", "200", "2"),
    ("10", "So. 2d", "300", "4"),
    ("10", "So. 2d", "300", "6"),
    ("10", "So. 2d", "400", "5"),
    ("10", "So. 2d", "D5", "1"),        # bad page: ignored
    ("10", "F.3d", "110", "1"),         # not a tracked reporter: must not shorten cluster 1
    ("10", "So. 3d", "105", "5"),       # other reporter, same volume number: a separate sequence
    ("11", "So. 2d", "50", "2"),        # alone in its volume
    ("12", "So. 2d", "10", "1"),        # next case is in a cluster the clusters CSV never lists
    ("12", "So. 2d", "20", "999"),
    # Fla. L. Weekly vol 45, sections kept apart.
    ("45", "Fla. L. Weekly", "D100", "7"),
    ("45", "Fla. L. Weekly", "D105", "1"),   # parallel cite of cluster 1
    ("45", "Fla. L. Weekly", "D110", "8"),
    ("45", "Fla. L. Weekly", "S105", "9"),
    ("45", "Fla. L. Weekly", "S140", "13"),  # 35 pages after S105
    ("45", "Fla. L. Weekly", "103", "10"),   # no section: its own sequence
    ("45", "Fla. L. Weekly Supp.", "1", "11"),
    ("45", "Fla. L. Weekly Supp.", "5", "12"),
]
# CAP rows: cluster 2 has full bounds; cluster 4 has a first page but no last page.
BOUNDS = [("2", "200", "260"), ("4", "298", "")]


def write_corpus(directory: Path, bounds=None, citations=CITATIONS):
    _write(directory / "dockets-t.csv", ["id", "court_id", "docket_number"], [(i, c, "x") for i, c in DOCKETS])
    _write(directory / "opinion-clusters-t.csv", ["id", "case_name", "docket_id"], CLUSTERS)
    _write(directory / "citations-t.csv", ["id", "volume", "reporter", "page", "type", "cluster_id"],
           [(str(n), v, r, p, "1", c) for n, (v, r, p, c) in enumerate(citations, 1)])
    if bounds is not None:
        _write(directory / "page-bounds-t.csv", ["cluster_id", "first_page", "last_page"], bounds)


class _Built:
    def __init__(self, test, bounds=None, **kw):
        self.tmp = tempfile.TemporaryDirectory()
        test.addCleanup(self.tmp.cleanup)
        corpus = Path(self.tmp.name) / "c"
        corpus.mkdir()
        write_corpus(corpus, bounds=bounds)
        self.db = Path(self.tmp.name) / "out.db"
        self.stats = build_index(corpus, self.db, **kw)
        conn = sqlite3.connect(self.db)
        test.addCleanup(conn.close)
        self.conn = conn

    def row(self, reporter, volume, page, section="", cluster=None):
        sql = ("SELECT first_page, last_page, bounds_source FROM citation_index "
               "WHERE reporter=? AND volume=? AND page=? AND section=?")
        args = [reporter, volume, page, section]
        if cluster is not None:
            sql += " AND cluster_id=?"
            args.append(cluster)
        rows = self.conn.execute(sql, args).fetchall()
        assert len(rows) == 1, rows
        return rows[0]


class InferLastPageUnit(unittest.TestCase):
    def test_pure_function(self):
        a = array("i", [100, 150, 200])
        self.assertEqual(infer_last_page(a, 100), (149, None))
        self.assertEqual(infer_last_page(a, 100, "next_start"), (150, None))
        self.assertEqual(infer_last_page(a, 200), (None, "last_in_volume"))
        self.assertEqual(infer_last_page(a, 120), (149, None))      # between known starts
        self.assertEqual(infer_last_page(None, 5), (None, "last_in_volume"))
        self.assertEqual(infer_last_page(a, 100, max_span=49), (None, "span_exceeded"))
        self.assertEqual(infer_last_page(a, 100, max_span=50), (149, None))

    def test_last_never_below_first(self):
        a = array("i", [7, 8])
        self.assertEqual(infer_last_page(a, 7), (7, None))   # one-page case: last == first


class InferredBounds(unittest.TestCase):
    def setUp(self):
        self.b = _Built(self)

    def test_next_case_from_another_state_sets_last_page(self):
        # Alabama cluster 3 starts at 150 and is not in the output, but ends cluster 1.
        self.assertEqual(self.b.row("So. 2d", 10, 100), (100, 149, "inferred_next_case"))
        self.assertEqual(self.b.conn.execute("SELECT COUNT(*) FROM citation_index WHERE cluster_id=3").fetchone()[0], 0)

    def test_unlisted_cluster_still_counts_as_next_case(self):
        self.assertEqual(self.b.row("So. 2d", 12, 10), (10, 19, "inferred_next_case"))

    def test_duplicate_start_pages(self):
        # 4 and 6 both start at 300; both end before 400. Neither is the other's "next case".
        self.assertEqual(self.b.row("So. 2d", 10, 300, cluster=4), (300, 399, "inferred_next_case"))
        self.assertEqual(self.b.row("So. 2d", 10, 300, cluster=6), (300, 399, "inferred_next_case"))

    def test_no_later_case_is_null(self):
        self.assertEqual(self.b.row("So. 2d", 10, 400), (400, None, None))
        self.assertEqual(self.b.row("So. 2d", 11, 50), (50, None, None))   # other volumes do not leak in

    def test_other_reporter_and_other_volume_do_not_affect(self):
        self.assertEqual(self.b.row("So. 3d", 10, 105), (105, None, None))
        # F.3d 110 and the bad page D5 did not shorten cluster 1 (149, not 109).
        self.assertEqual(self.b.row("So. 2d", 10, 100)[1], 149)

    def test_weekly_sections_are_separate_sequences(self):
        self.assertEqual(self.b.row("Fla. L. Weekly", 45, 100, "D"), (100, 104, "inferred_next_case"))
        self.assertEqual(self.b.row("Fla. L. Weekly", 45, 105, "D"), (105, 109, "inferred_next_case"))   # parallel cite row
        self.assertEqual(self.b.row("Fla. L. Weekly", 45, 110, "D"), (110, None, None))   # S and plain pages are not "next"
        self.assertEqual(self.b.row("Fla. L. Weekly", 45, 103, ""), (103, None, None))

    def test_weekly_span_cap(self):
        self.assertEqual(self.b.row("Fla. L. Weekly", 45, 105, "S"), (105, None, None))   # 35 pages > 25
        self.assertEqual(self.b.stats["bounds_null_span_exceeded"], 1)

    def test_weekly_span_cap_configurable_and_disableable(self):
        wide = _Built(self, weekly_max_span=50)
        self.assertEqual(wide.row("Fla. L. Weekly", 45, 105, "S"), (105, 139, "inferred_next_case"))
        off = _Built(self, weekly_max_span=0)
        self.assertEqual(off.conn.execute(
            "SELECT COUNT(*) FROM citation_index WHERE reporter='Fla. L. Weekly' AND last_page IS NOT NULL").fetchone()[0], 0)
        self.assertEqual(off.row("So. 2d", 10, 100)[1], 149)   # Southern unaffected

    def test_weekly_supp_never_inferred(self):
        self.assertEqual(self.b.row("Fla. L. Weekly Supp.", 45, 1), (1, None, None))
        self.assertEqual(self.b.row("Fla. L. Weekly Supp.", 45, 5), (5, None, None))
        self.assertEqual(self.b.stats["bounds_null_not_inferred"], 2)

    def test_stats(self):
        s = self.b.stats
        self.assertEqual(s["bounds_rows"], 0 + 0)  # no CAP file in this build
        self.assertEqual(s["bounds_cap"], 0)
        total = self.b.conn.execute("SELECT COUNT(*) FROM citation_index").fetchone()[0]
        inferred = self.b.conn.execute(
            "SELECT COUNT(*) FROM citation_index WHERE bounds_source='inferred_next_case'").fetchone()[0]
        self.assertEqual(s["bounds_inferred"], inferred)
        self.assertEqual(s["last_page_null_total"], total - inferred)
        self.assertGreater(s["bounds_null_last_in_volume"], 0)
        # Distinct start pages across the five keys: So. 2d v10 {100,150,200,300,400}, v11 {50},
        # v12 {10,20}, So. 3d v10 {105}, Weekly D {100,105,110}, S {105,140}, '' {103}. Supp is not collected.
        self.assertEqual(s["start_pages_collected"], 5 + 1 + 2 + 1 + 3 + 2 + 1)

    def test_inferred_rows_never_have_last_below_first(self):
        n = self.b.conn.execute("SELECT COUNT(*) FROM citation_index WHERE last_page < first_page").fetchone()[0]
        self.assertEqual(n, 0)

    def test_schema_column_is_last_and_nullable(self):
        cols = self.b.conn.execute("PRAGMA table_info(citation_index)").fetchall()
        self.assertEqual(cols[-1][1], "bounds_source")
        self.assertEqual(cols[-1][3], 0)   # nullable
        self.assertEqual([c[1] for c in cols[:9]],
                         ["reporter", "volume", "page", "section", "cluster_id", "case_name", "court_id", "first_page", "last_page"])


class Conventions(unittest.TestCase):
    def test_next_start_convention(self):
        b = _Built(self, last_page_convention="next_start")
        self.assertEqual(b.row("So. 2d", 10, 100), (100, 150, "inferred_next_case"))
        self.assertEqual(b.row("Fla. L. Weekly", 45, 100, "D"), (100, 105, "inferred_next_case"))

    def test_default_is_fail_closed_prev_page(self):
        self.assertEqual(bsi.DEFAULT_LAST_PAGE_CONVENTION, "prev_page")

    def test_bad_convention_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                build_index(d, Path(d) / "x.db", last_page_convention="nope")

    def test_no_infer_flag_matches_old_behaviour(self):
        b = _Built(self, infer_bounds=False)
        self.assertEqual(b.conn.execute("SELECT COUNT(*) FROM citation_index WHERE last_page IS NOT NULL").fetchone()[0], 0)
        self.assertEqual(b.conn.execute("SELECT COUNT(*) FROM citation_index WHERE bounds_source IS NOT NULL").fetchone()[0], 0)
        self.assertEqual(b.stats["start_pages_collected"], 0)


class CapPrecedence(unittest.TestCase):
    def setUp(self):
        self.b = _Built(self, bounds=BOUNDS)

    def test_cap_overrides_inferred(self):
        # Inferred would be 299; CAP says 260.
        self.assertEqual(self.b.row("So. 2d", 10, 200), (200, 260, "cap"))

    def test_cap_row_without_last_page_falls_back_to_inference_keeping_cap_first(self):
        self.assertEqual(self.b.row("So. 2d", 10, 300, cluster=4), (298, 399, "inferred_next_case"))

    def test_uncovered_clusters_still_inferred(self):
        self.assertEqual(self.b.row("So. 2d", 10, 100), (100, 149, "inferred_next_case"))

    def test_stats_with_cap(self):
        self.assertEqual(self.b.stats["bounds_rows"], 2)
        # CAP bounds are per cluster (pre-existing behaviour), so both of cluster 2's rows carry them.
        self.assertEqual(self.b.stats["bounds_cap"], 2)


class GatePinChecks(unittest.TestCase):
    """The gate reads first_page/last_page only; inferred rows behave exactly like CAP rows."""

    def check(self, db, cite):
        r = gate1.check_citation(cite, db)
        return r.verdict, r.reason

    def test_pin_within_beyond_and_null(self):
        b = _Built(self)
        c = "Alpha v. One, 10 So. 2d 100, {} (Fla. 1950)"
        self.assertEqual(self.check(b.db, c.format(100)), ("pass", "verified"))
        self.assertEqual(self.check(b.db, c.format(149)), ("pass", "verified"))
        self.assertEqual(self.check(b.db, c.format("120-130")), ("pass", "verified"))
        self.assertEqual(self.check(b.db, c.format(150)), ("veto", "pin_out_of_bounds"))   # next case's first page
        self.assertEqual(self.check(b.db, c.format("140-155")), ("veto", "pin_out_of_bounds"))
        self.assertEqual(self.check(b.db, c.format(99)), ("veto", "pin_out_of_bounds"))
        # No pin: unaffected by bounds.
        self.assertEqual(self.check(b.db, "Alpha v. One, 10 So. 2d 100 (Fla. 1950)"), ("pass", "verified"))
        # last_page NULL (last case in its volume): the gate's existing behaviour, pin_unverifiable.
        self.assertEqual(self.check(b.db, "Echo v. Five, 10 So. 2d 400, 405 (Fla. 1950)"), ("veto", "pin_unverifiable"))
        self.assertEqual(self.check(b.db, "Echo v. Five, 10 So. 2d 400 (Fla. 1950)"), ("pass", "verified"))

    def test_next_start_convention_accepts_shared_page_pin(self):
        b = _Built(self, last_page_convention="next_start")
        self.assertEqual(self.check(b.db, "Alpha v. One, 10 So. 2d 100, 150 (Fla. 1950)"), ("pass", "verified"))
        self.assertEqual(self.check(b.db, "Alpha v. One, 10 So. 2d 100, 151 (Fla. 1950)"), ("veto", "pin_out_of_bounds"))

    def test_cap_bounds_drive_the_gate_when_present(self):
        b = _Built(self, bounds=BOUNDS)
        c = "Bravo v. Two, 10 So. 2d 200, {} (Fla. 2d DCA 1950)"
        self.assertEqual(self.check(b.db, c.format(260)), ("pass", "verified"))
        self.assertEqual(self.check(b.db, c.format(261)), ("veto", "pin_out_of_bounds"))   # inferred bound (299) would have passed it

    def test_old_db_without_bounds_source_column(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "old.db"
            conn = sqlite3.connect(db)
            conn.executescript(
                "CREATE TABLE citation_index (reporter TEXT NOT NULL, volume INTEGER NOT NULL, page INTEGER NOT NULL, "
                "section TEXT NOT NULL DEFAULT '', cluster_id INTEGER NOT NULL, case_name TEXT, court_id TEXT, "
                "first_page INTEGER, last_page INTEGER);"
                "INSERT INTO citation_index VALUES ('So. 2d', 10, 100, '', 1, 'Alpha v. One', 'fla', 100, 149);"
                "INSERT INTO citation_index VALUES ('So. 2d', 10, 400, '', 5, 'Echo v. Five', 'fla', 400, NULL);"
            )
            conn.commit()
            conn.close()
            self.assertEqual(self.check(db, "Alpha v. One, 10 So. 2d 100, 120 (Fla. 1950)"), ("pass", "verified"))
            self.assertEqual(self.check(db, "Alpha v. One, 10 So. 2d 100, 150 (Fla. 1950)"), ("veto", "pin_out_of_bounds"))
            self.assertEqual(self.check(db, "Echo v. Five, 10 So. 2d 400, 405 (Fla. 1950)"), ("veto", "pin_unverifiable"))

    def test_gate_sql_names_columns_explicitly(self):
        # Static guard: neither gate reads bounds_source or SELECT *, so old and new DBs both work.
        for path in (REPO_ROOT / "pipeline" / "gate1.py", REPO_ROOT / "backend" / "src" / "verification" / "local_sqlite_gate.ts"):
            text = path.read_text(encoding="utf-8")
            self.assertIn("SELECT cluster_id, case_name, first_page, last_page, court_id FROM citation_index", text, path.name)
            self.assertNotIn("SELECT * FROM citation_index", text, path.name)
            self.assertNotIn("bounds_source", text, path.name)


class CliAndAtomicity(unittest.TestCase):
    def test_cli_writes_to_out_and_prints_stats(self):
        with tempfile.TemporaryDirectory() as d:
            corpus = Path(d) / "c"
            corpus.mkdir()
            write_corpus(corpus)
            out = Path(d) / "new.db"
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = bsi.main(["--corpus", str(corpus), "--out", str(out), "--last-page-convention", "next_start",
                               "--weekly-max-span", "50"])
            self.assertEqual(rc, 0)
            self.assertIn("bounds_inferred: ", buf.getvalue())
            self.assertIn("bounds_null_last_in_volume: ", buf.getvalue())
            self.assertFalse(Path(str(out) + ".tmp").exists())
            conn = sqlite3.connect(out)
            self.assertEqual(conn.execute(
                "SELECT last_page FROM citation_index WHERE reporter='So. 2d' AND volume=10 AND page=100").fetchone()[0], 150)
            conn.close()

    def test_failed_build_leaves_existing_db_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            corpus = Path(d) / "c"
            corpus.mkdir()
            write_corpus(corpus)
            out = Path(d) / "live.db"
            out.write_bytes(b"previous good build")
            with mock.patch.object(bsi, "_flush", side_effect=RuntimeError("boom")):
                with self.assertRaises(RuntimeError):
                    build_index(corpus, out)
            self.assertEqual(out.read_bytes(), b"previous good build")
            self.assertFalse(Path(str(out) + ".tmp").exists())

    def test_deterministic(self):
        a, b = _Built(self), _Built(self)
        q = "SELECT * FROM citation_index ORDER BY 1,2,3,4,5"
        self.assertEqual(a.conn.execute(q).fetchall(), b.conn.execute(q).fetchall())


if __name__ == "__main__":
    unittest.main()
