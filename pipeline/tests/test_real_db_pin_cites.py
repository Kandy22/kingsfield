"""Real-database pin-cite attacks on Gate 1 (Constraint A), tabular-docwrite-verify Part D.

Every other Gate 1 test runs against a tiny fixture DB. This module runs the production gate
path against the REAL kingsfield_florida.db at the repo root, read-only, to prove that the
inferred page bounds (bounds_source = 'inferred_next_case', or 'cap') veto what they must:

    * pins past the case's last page, before its first page, reversed or ranged out of bounds;
    * pins on the last case of a volume (last_page NULL -> pin_unverifiable);
    * Fla. L. Weekly Supp. (never inferred) and span-capped Fla. L. Weekly pins;
    * fabricated cites, wrong captions, wrong court level, a page that is not a start page;
    * short-form Id. pins resolved against the same stored bounds.

The database is a merge requirement. If it is missing, empty or lacks citation_index.bounds_source,
setUpModule raises and EVERY test in this module errors with a message saying why. Nothing here
skips. Bounds are read from the DB inside the tests, never hard-coded, so a rebuilt DB with
different inferred bounds is still attacked at exactly its edges.

Cost: a few dozen indexed SQLite lookups, one full-table aggregate scan, and one node child
(the TS gate, batched). No Python children.
"""

import inspect
import os
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate1_fixture as fx  # noqa: E402  (also puts the repo root on sys.path)

from pipeline import gate1  # noqa: E402

REAL_DB = fx.REPO / "kingsfield_florida.db"
BOUNDS_SOURCES_OK = ("inferred_next_case", "cap")
FACTS = {}


# ---------------------------------------------------------------------------
# DB helpers (read-only, own connections)
# ---------------------------------------------------------------------------

def _ro():
    conn = sqlite3.connect(REAL_DB.resolve().as_uri() + "?mode=ro", uri=True, timeout=2.0)
    conn.execute("PRAGMA query_only = 1")
    return conn


def _snapshot():
    st = os.stat(REAL_DB)
    sib = tuple(Path(str(REAL_DB) + s).exists() for s in ("-wal", "-shm", "-journal"))
    return (st.st_mtime_ns, st.st_size, st.st_ino, sib)


def _court_text(court_id, year):
    if court_id == "fla":
        return "Fla. %d" % year
    if court_id == "fladistctapp":
        return "Fla. 2d DCA %d" % year
    raise AssertionError("unexpected court_id %r in the Florida index" % (court_id,))


def _fail_db(msg):
    raise AssertionError(
        "REAL DB GUARD: %s\n  The real kingsfield_florida.db is a merge requirement (Constraint A); "
        "this module does not skip. Rebuild it with the current db/build_sqlite_index.py." % msg)


def _find_unique_row(conn, sql, args):
    """First row of `sql` whose (reporter, volume, page, section) key is held by exactly one row."""
    for row in conn.execute(sql, args).fetchall():
        reporter, volume, page, section = row[0], row[1], row[2], row[3]
        n = conn.execute(
            "SELECT COUNT(*) FROM citation_index WHERE reporter=? AND volume=? AND page=? AND section=?",
            (reporter, volume, page, section)).fetchone()[0]
        if n == 1:
            return row
    return None


_COLS = "reporter, volume, page, section, cluster_id, case_name, court_id, first_page, last_page, bounds_source"


def setUpModule():
    if not REAL_DB.is_file():
        _fail_db("%s does not exist." % REAL_DB)
    if REAL_DB.stat().st_size < 4096:
        _fail_db("%s is empty or truncated (%d bytes)." % (REAL_DB, REAL_DB.stat().st_size))
    FACTS["snapshot"] = _snapshot()
    try:
        conn = _ro()
    except sqlite3.Error as e:
        _fail_db("cannot open %s read-only: %s" % (REAL_DB, e))
    try:
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(citation_index)").fetchall()]
        except sqlite3.Error as e:
            _fail_db("%s is not a SQLite database: %s" % (REAL_DB, e))
        if not cols:
            _fail_db("%s has no citation_index table." % REAL_DB)
        if "bounds_source" not in cols:
            _fail_db("%s lacks citation_index.bounds_source (old build, columns=%s): every pin cite "
                     "against it vetoes pin_unverifiable." % (REAL_DB, cols))

        # Tanner v. Hartog, 618 So. 2d 177 (Fla. 1993).
        rows = [r for r in conn.execute(
            "SELECT " + _COLS + " FROM citation_index WHERE reporter='So. 2d' AND volume=618 AND page=177 AND section=''"
        ).fetchall() if r[5] and "tanner" in r[5].lower() and "hartog" in r[5].lower()]
        if len(rows) != 1:
            _fail_db("expected exactly one Tanner v. Hartog row at 618 So. 2d 177, found %d: %r" % (len(rows), rows))
        t = rows[0]
        FACTS["tanner"] = dict(cluster_id=t[4], case_name=t[5], court_id=t[6], first=t[7], last=t[8], source=t[9])

        # Last Florida case of a So. 2d volume with last_page NULL and no bounds_source.
        tail = None
        for vol in range(618, 0, -1):
            cand = _find_unique_row(
                conn,
                "SELECT " + _COLS + " FROM citation_index WHERE reporter='So. 2d' AND volume=? AND section='' "
                "AND last_page IS NULL AND bounds_source IS NULL ORDER BY page DESC LIMIT 5", (vol,))
            if cand is not None:
                # It must really be the last Florida row of the volume.
                top = conn.execute(
                    "SELECT MAX(page) FROM citation_index WHERE reporter='So. 2d' AND volume=? AND section=''",
                    (vol,)).fetchone()[0]
                if cand[2] == top:
                    tail = cand
                    break
        FACTS["tail"] = (dict(volume=tail[1], page=tail[2], court_id=tail[6], first=tail[7]) if tail else None)

        # A DCA case in the same volume as Tanner (for the wrong-court-level attack).
        dca = _find_unique_row(
            conn,
            "SELECT " + _COLS + " FROM citation_index WHERE reporter='So. 2d' AND volume=618 AND section='' "
            "AND court_id='fladistctapp' ORDER BY page LIMIT 20", ())
        FACTS["dca"] = dict(volume=dca[1], page=dca[2], case_name=dca[5]) if dca else None

        # Fla. L. Weekly Supp. and plain Fla. L. Weekly rows, if the DB holds any.
        supp = _find_unique_row(
            conn,
            "SELECT " + _COLS + " FROM citation_index WHERE reporter='Fla. L. Weekly Supp.' AND last_page IS NULL LIMIT 20",
            ())
        FACTS["supp"] = (dict(volume=supp[1], page=supp[2], section=supp[3], court_id=supp[6], last=supp[8])
                         if supp else None)
        wk = _find_unique_row(
            conn,
            "SELECT " + _COLS + " FROM citation_index WHERE reporter='Fla. L. Weekly' AND last_page IS NULL LIMIT 20",
            ())
        FACTS["weekly_null"] = (dict(volume=wk[1], page=wk[2], section=wk[3], court_id=wk[6]) if wk else None)
    finally:
        conn.close()


def tearDownModule():
    after = _snapshot()
    if after != FACTS.get("snapshot"):
        raise AssertionError(
            "REAL DB WAS MODIFIED during the pin-cite tests: (mtime_ns, size, inode, wal/shm/journal) "
            "before=%r after=%r" % (FACTS.get("snapshot"), after))


# ---------------------------------------------------------------------------
# Test base
# ---------------------------------------------------------------------------

class RealDbCase(unittest.TestCase):
    maxDiff = None

    @property
    def tanner(self):
        t = FACTS["tanner"]
        if t["first"] is None or t["last"] is None:
            self.fail("Tanner v. Hartog has NULL bounds in the real DB (first=%r last=%r source=%r): "
                      "inferred bounds are missing" % (t["first"], t["last"], t["source"]))
        return t

    def cite(self, pin, court="Fla.", year=1993):
        return "Tanner v. Hartog, 618 So. 2d 177, %s (%s %d)" % (pin, court, year)

    def one(self, text):
        res = gate1.check_text(text, str(REAL_DB))
        self.assertEqual(len(res), 1, "expected exactly one citation result for %r, got %r" % (text, res))
        return res[0]

    def assertVeto(self, text, reason=None):
        r = self.one(text)
        if r.verdict != "veto" or (reason is not None and r.reason != reason):
            self.fail("LEAK on %r\n  expected veto%s, got %s (reason=%r)\n  full result: %r" % (
                text, " (%s)" % reason if reason else "", r.verdict, r.reason, r))
        return r

    def assertPass(self, text):
        r = self.one(text)
        if r.verdict != "pass":
            self.fail("CONTROL FAILED (valid cite did not pass) %r -> %s (%s)\n  full result: %r" % (
                text, r.verdict, r.reason, r))
        return r


# ---------------------------------------------------------------------------
# The DB itself: bounds columns are populated the way the decision says
# ---------------------------------------------------------------------------

class RealDbShape(RealDbCase):
    def test_tanner_bounds_are_inferred_or_cap_and_sane(self):
        t = self.tanner
        self.assertIn(t["source"], BOUNDS_SOURCES_OK,
                      "Tanner's bounds_source is %r: the DB was not built with bounds inference" % (t["source"],))
        self.assertEqual(t["court_id"], "fla", "Tanner v. Hartog is a Florida Supreme Court case")
        self.assertIsNotNone(t["first"])
        self.assertIsNotNone(t["last"], "Tanner has no last_page: every pin cite to it would veto pin_unverifiable")
        self.assertLessEqual(t["first"], 177)
        self.assertGreaterEqual(t["last"], 181, "Tanner's pin 181 is outside its own bounds %r" % (t,))
        # An inferred bound should be a modest span; a runaway bound would pass fabricated pins.
        self.assertLess(t["last"] - t["first"], 200, "implausibly wide Tanner bounds: %r" % (t,))

    def test_global_bounds_invariants(self):
        conn = _ro()
        try:
            row = conn.execute(
                "SELECT COUNT(*), "
                "SUM(CASE WHEN bounds_source='inferred_next_case' THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN last_page < first_page THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN bounds_source IS NOT NULL AND bounds_source NOT IN ('cap','inferred_next_case') THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN bounds_source IS NULL AND last_page IS NOT NULL THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN bounds_source='inferred_next_case' AND last_page IS NULL THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN bounds_source='inferred_next_case' AND last_page < page THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN last_page IS NULL THEN 1 ELSE 0 END) "
                "FROM citation_index").fetchone()
        finally:
            conn.close()
        total, inferred, inverted, bad_source, unmarked, inferred_null, inferred_below_page, null_last = row
        self.assertGreater(total, 1000, "implausibly small real DB: %d rows" % total)
        self.assertGreater(inferred or 0, 0, "no inferred_next_case rows: the DB was built without bounds inference")
        self.assertEqual(inverted, 0, "rows with last_page < first_page: a pin check against them is meaningless")
        self.assertEqual(bad_source, 0, "unknown bounds_source values present")
        self.assertEqual(unmarked, 0, "rows carry a last_page but no bounds_source (unprovenanced bounds)")
        self.assertEqual(inferred_null, 0, "inferred rows with NULL last_page")
        self.assertEqual(inferred_below_page, 0, "inferred rows whose last_page is below their own start page")
        self.assertGreater(null_last or 0, 0, "no NULL last_page rows at all: 'last case in a volume' is not represented")

    def test_weekly_span_cap_and_supp_never_inferred(self):
        conn = _ro()
        try:
            wide = conn.execute(
                "SELECT COUNT(*) FROM citation_index WHERE reporter='Fla. L. Weekly' "
                "AND bounds_source='inferred_next_case' AND last_page - page > 24").fetchone()[0]
            supp = conn.execute(
                "SELECT COUNT(*) FROM citation_index WHERE reporter='Fla. L. Weekly Supp.' "
                "AND bounds_source='inferred_next_case'").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(wide, 0, "inferred Fla. L. Weekly bounds wider than the 25-page span cap")
        self.assertEqual(supp, 0, "Fla. L. Weekly Supp. rows must never carry inferred bounds")

    def test_gate_default_db_is_the_repo_root_db(self):
        self.assertEqual(Path(gate1.DEFAULT_DB).resolve(), REAL_DB.resolve())


# ---------------------------------------------------------------------------
# Tanner v. Hartog: the named acceptance cases
# ---------------------------------------------------------------------------

class TannerAcceptance(RealDbCase):
    def test_tanner_pin_181_passes(self):
        r = self.assertPass(self.cite(181))
        self.assertEqual(r.cluster_id, self.tanner["cluster_id"])

    def test_tanner_pin_181_passes_inside_prose(self):
        r = self.assertPass("The Court addressed this in Tanner v. Hartog, 618 So. 2d 177, 181 (Fla. 1993), and affirmed.")
        self.assertEqual(r.cluster_id, self.tanner["cluster_id"])

    def test_tanner_pin_950_vetoes(self):
        self.assertVeto(self.cite(950), "pin_out_of_bounds")
        self.assertVeto("As held in Tanner v. Hartog, 618 So. 2d 177, 950 (Fla. 1993), the rule is settled.",
                        "pin_out_of_bounds")

    def test_nonexistent_999_so_3d_999_vetoes(self):
        self.assertVeto("999 So. 3d 999 (Fla. 2015)", "not_found")
        self.assertVeto("Doe v. Roe, 999 So. 3d 999 (Fla. 2015)", "not_found")
        self.assertVeto("Doe v. Roe, 999 So. 3d 999, 1001 (Fla. 2015)", "not_found")


# ---------------------------------------------------------------------------
# Edge attacks against the inferred bounds
# ---------------------------------------------------------------------------

class PinEdges(RealDbCase):
    def test_pin_exactly_at_last_page_passes_and_one_past_vetoes(self):
        t = self.tanner
        self.assertPass(self.cite(t["last"]))
        self.assertVeto(self.cite(t["last"] + 1), "pin_out_of_bounds")   # the next case's start page

    def test_pin_exactly_at_first_page_passes_and_one_before_vetoes(self):
        t = self.tanner
        self.assertPass(self.cite(t["first"]))
        self.assertVeto(self.cite(t["first"] - 1), "pin_out_of_bounds")

    def test_assorted_out_of_bounds_pins_all_veto(self):
        t = self.tanner
        for pin in (0, 1, t["first"] - 1, t["last"] + 1, t["last"] + 2, t["last"] + 150, 999999):
            with self.subTest(pin=pin):
                self.assertVeto(self.cite(pin), "pin_out_of_bounds")

    def test_pin_range_ending_past_last_vetoes(self):
        t = self.tanner
        self.assertPass(self.cite("%d-%d" % (t["first"], t["last"])))           # control: whole opinion
        for rng in ("%d-%d" % (181, t["last"] + 1),
                    "%d-%d" % (t["first"] + 1, t["last"] + 5),
                    "%d-%d" % (t["last"], t["last"] + 1),
                    "%d-%d" % (181, 950)):
            with self.subTest(pin=rng):
                self.assertVeto(self.cite(rng), "pin_out_of_bounds")

    def test_pin_range_starting_before_first_or_reversed_vetoes(self):
        t = self.tanner
        self.assertVeto(self.cite("%d-%d" % (t["first"] - 1, 181)), "pin_out_of_bounds")
        self.assertVeto(self.cite("%d-%d" % (t["last"], t["first"] + 1)), "pin_out_of_bounds")   # b < a

    def test_multiple_pins_one_out_of_bounds_vetoes(self):
        t = self.tanner
        self.assertPass(self.cite("%d, %d" % (181, t["last"])))
        self.assertVeto(self.cite("%d, %d" % (181, t["last"] + 1)), "pin_out_of_bounds")
        self.assertVeto(self.cite("181, 950"), "pin_out_of_bounds")

    def test_next_case_start_page_under_tanner_caption_vetoes(self):
        # Tanner's name stapled to the page where the following opinion starts.
        t = self.tanner
        self.assertVeto("Tanner v. Hartog, 618 So. 2d %d (Fla. 1993)" % (t["last"] + 1))
        self.assertVeto("Tanner v. Hartog, 618 So. 2d %d, %d (Fla. 1993)" % (t["last"] + 1, t["last"] + 1))

    def test_pin_page_is_not_a_start_page(self):
        # 181 lies inside Tanner; as a *start* page nothing is indexed there.
        self.assertVeto("Tanner v. Hartog, 618 So. 2d 181 (Fla. 1993)", "not_found")
        self.assertVeto("618 So. 2d 181, 181 (Fla. 1993)", "not_found")

    def test_wrong_caption_with_valid_cite_and_pin_vetoes(self):
        self.assertVeto("Smith v. Jones, 618 So. 2d 177, 181 (Fla. 1993)", "caption_mismatch")

    def test_pin_far_inside_inferred_bound_does_not_bridge_into_next_volume(self):
        # Same page, wrong volume: 619 So. 2d 177 is a different case (or nothing) and never Tanner.
        r = self.one("Tanner v. Hartog, 619 So. 2d 177, 181 (Fla. 1993)")
        self.assertEqual(r.verdict, "veto", "LEAK: Tanner caption passed on volume 619: %r" % (r,))


class LastCaseOfVolume(RealDbCase):
    def test_pin_on_last_case_of_a_volume_vetoes_pin_unverifiable(self):
        tail = FACTS["tail"]
        self.assertIsNotNone(tail, "no So. 2d volume in 1..618 ends in a Florida case with NULL bounds: "
                                   "'last case in a volume' cannot be attacked, and the DB should have many")
        court = _court_text(tail["court_id"], 1990)
        base = "%d So. 2d %d" % (tail["volume"], tail["page"])
        self.assertPass("%s (%s)" % (base, court))                       # control: the cite itself exists
        for pin in (tail["page"], tail["page"] + 1, tail["page"] + 40, 950):
            with self.subTest(pin=pin):
                self.assertVeto("%s, %d (%s)" % (base, pin, court), "pin_unverifiable")
        self.assertVeto("%s, %d-%d (%s)" % (base, tail["page"], tail["page"] + 3, court), "pin_unverifiable")

    def test_short_form_pin_on_last_case_of_a_volume_vetoes(self):
        tail = FACTS["tail"]
        self.assertIsNotNone(tail)
        court = _court_text(tail["court_id"], 1990)
        text = "See %d So. 2d %d (%s). Id. at %d." % (tail["volume"], tail["page"], court, tail["page"] + 1)
        res = gate1.check_text(text, str(REAL_DB))
        self.assertTrue(res and res[0].verdict == "pass", "control failed: %r" % (res,))
        leaked = [r for r in res if r.kind == "id" and r.verdict != "veto"]
        self.assertEqual(leaked, [], "LEAK: Id. pin on a NULL-bounds case passed: %r" % (res,))


class WeeklyPins(RealDbCase):
    def test_fla_l_weekly_supp_pin_vetoes(self):
        supp = FACTS["supp"]
        if supp is None:
            # No Supp data loaded: the key is still in scope, so it vetoes (not_found).
            self.assertVeto("20 Fla. L. Weekly Supp. 300, 301 (Fla. 2012)", "not_found")
            return
        self.assertIsNone(supp["last"], "Fla. L. Weekly Supp. row carries a last_page: %r" % (supp,))
        court = _court_text(supp["court_id"], 2012)
        base = "%d Fla. L. Weekly Supp. %s%d" % (supp["volume"], supp["section"], supp["page"])
        for pin in (supp["page"], supp["page"] + 1, 950):
            with self.subTest(pin=pin):
                self.assertVeto("%s, %d (%s)" % (base, pin, court), "pin_unverifiable")

    def test_fla_l_weekly_null_bound_pin_vetoes(self):
        wk = FACTS["weekly_null"]
        if wk is None:
            self.assertVeto("36 Fla. L. Weekly D1234, 1236 (Fla. 2d DCA 2011)", "not_found")
            return
        court = _court_text(wk["court_id"], 2012)
        base = "%d Fla. L. Weekly %s%d" % (wk["volume"], wk["section"], wk["page"])
        self.assertPass("%s (%s)" % (base, court))                      # control: the cite itself exists
        for pin in (wk["page"], wk["page"] + 1, wk["page"] + 30):
            with self.subTest(pin=pin):
                self.assertVeto("%s, %d (%s)" % (base, pin, court), "pin_unverifiable")

    def test_fla_l_weekly_fabricated_still_vetoes(self):
        self.assertVeto("999 Fla. L. Weekly D9999, 9999 (Fla. 4th DCA 2099)", "not_found")


class CourtLevel(RealDbCase):
    def test_supreme_court_case_cited_as_dca_vetoes(self):
        self.assertVeto(self.cite(181, court="Fla. 3d DCA"), "court_mismatch")
        self.assertVeto(self.cite(181, court="Fla. 1st DCA"), "court_mismatch")

    def test_dca_case_cited_as_supreme_court_vetoes(self):
        dca = FACTS["dca"]
        self.assertIsNotNone(dca, "no unique DCA row in So. 2d volume 618 to attack")
        self.assertPass("%d So. 2d %d (Fla. 2d DCA 1993)" % (dca["volume"], dca["page"]))      # control
        self.assertVeto("%d So. 2d %d (Fla. 1993)" % (dca["volume"], dca["page"]), "court_mismatch")


class ShortFormPins(RealDbCase):
    def test_id_pin_checked_against_stored_bounds(self):
        t = self.tanner
        head = "See Tanner v. Hartog, 618 So. 2d 177, 181 (Fla. 1993)."
        ok = gate1.check_text("%s Id. at %d." % (head, t["last"]), str(REAL_DB))
        self.assertEqual([r.verdict for r in ok], ["pass", "pass"], "controls failed: %r" % (ok,))
        for pin in (t["last"] + 1, 950):
            with self.subTest(pin=pin):
                res = gate1.check_text("%s Id. at %d." % (head, pin), str(REAL_DB))
                self.assertEqual(len(res), 2, res)
                self.assertEqual(res[0].verdict, "pass", res)
                if res[1].verdict != "veto" or res[1].reason != "pin_out_of_bounds":
                    self.fail("LEAK: Id. at %d after Tanner -> %s (%s)\n  %r" % (pin, res[1].verdict, res[1].reason, res))


# ---------------------------------------------------------------------------
# Read-only access
# ---------------------------------------------------------------------------

class ReadOnly(RealDbCase):
    def test_gate_calls_do_not_touch_the_database_file(self):
        before = _snapshot()
        for text in (self.cite(181), self.cite(950), "999 So. 3d 999 (Fla. 2015)"):
            gate1.check_text(text, str(REAL_DB))
            gate1.check_citation(text, REAL_DB)
        self.assertEqual(_snapshot(), before, "gate calls changed the DB file or left a wal/shm/journal beside it")

    def test_gate_lookup_is_opened_read_only(self):
        src = inspect.getsource(gate1._lookup)
        self.assertIn("mode=ro", src)
        self.assertIn("query_only", src)

    def test_database_rejects_writes_when_opened_the_gates_way(self):
        conn = _ro()
        try:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("DELETE FROM citation_index")
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("UPDATE citation_index SET last_page = 999999")
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# TS gate parity on the real DB (one batched node child)
# ---------------------------------------------------------------------------

class TsGateParity(RealDbCase):
    def test_ts_gate_matches_python_gate_on_real_db(self):
        t = self.tanner
        tail = FACTS["tail"]
        cases = [
            (self.cite(181), "pass"),
            (self.cite(950), "veto"),
            (self.cite(t["last"]), "pass"),
            (self.cite(t["last"] + 1), "veto"),
            (self.cite(t["first"] - 1), "veto"),
            (self.cite("181-%d" % (t["last"] + 1)), "veto"),
            (self.cite("181, 950"), "veto"),
            (self.cite(181, court="Fla. 3d DCA"), "veto"),
            ("999 So. 3d 999 (Fla. 2015)", "veto"),
            ("Tanner v. Hartog, 618 So. 2d 181 (Fla. 1993)", "veto"),
            ("Smith v. Jones, 618 So. 2d 177, 181 (Fla. 1993)", "veto"),
            ("20 Fla. L. Weekly Supp. 300, 301 (Fla. 2012)", "veto"),
        ]
        if tail:
            court = _court_text(tail["court_id"], 1990)
            cases.append(("%d So. 2d %d, %d (%s)" % (tail["volume"], tail["page"], tail["page"] + 1, court), "veto"))
        if FACTS["supp"]:
            s = FACTS["supp"]
            cases.append(("%d Fla. L. Weekly Supp. %s%d, %d (%s)" % (
                s["volume"], s["section"], s["page"], s["page"], _court_text(s["court_id"], 2012)), "veto"))
        cites = [c for c, _v in cases]
        ts = fx.ts_check_many(cites, REAL_DB)
        self.assertEqual(len(ts), len(cites))
        problems = []
        for (cite, expected), tr in zip(cases, ts):
            pr = gate1.check_citation(cite, REAL_DB)
            if pr.verdict != expected:
                problems.append("python %r: expected %s got %s (%s)" % (cite, expected, pr.verdict, pr.reason))
            if tr.get("verdict") != expected:
                problems.append("ts     %r: expected %s got %s (%s)" % (cite, expected, tr.get("verdict"), tr.get("reason")))
            if (pr.verdict, pr.reason) != (tr.get("verdict"), tr.get("reason")):
                problems.append("PARITY %r: py=(%s,%s) ts=(%s,%s)" % (
                    cite, pr.verdict, pr.reason, tr.get("verdict"), tr.get("reason")))
            if pr.verdict == "pass" and pr.cluster_id != tr.get("clusterId"):
                problems.append("PARITY cluster %r: py=%r ts=%r" % (cite, pr.cluster_id, tr.get("clusterId")))
        if problems:
            self.fail("TS/Python gate disagreement or leak on the real DB:\n  " + "\n  ".join(problems))


if __name__ == "__main__":
    unittest.main()
