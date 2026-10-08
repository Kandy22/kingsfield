"""Adversarial bypass suite for Gate 1 (Constraint A).

Every test asserts that a hostile or malformed input is vetoed (or, for
out-of-scope keys, falls through) by BOTH the Python reference gate
(pipeline.gate1.check_citation) and the TS gate (localGate1 via node), and
that the two agree. Controls (valid cites that must pass) are included so a
gate that vetoes everything cannot satisfy the suite.
"""

import os
import shutil
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate1_fixture as fx  # noqa: E402


class GateCase(unittest.TestCase):
    maxDiff = None

    # -- helpers --

    def run_both(self, cite, db=None):
        db = db if db is not None else fx.get_fixture().db
        return fx.py_check(cite, db), fx.ts_check(cite, db)

    def assertBoth(self, cite, expected, db=None, cluster=None):
        py, ts = self.run_both(cite, db)
        problems = []
        if py.verdict != expected:
            problems.append("python gate: expected %r got %r (reason=%r)" % (expected, py.verdict, py.reason))
        if ts.get("verdict") != expected:
            problems.append("ts gate: expected %r got %r (reason=%r)" % (expected, ts.get("verdict"), ts.get("reason")))
        if cluster is not None and expected == "pass":
            if py.cluster_id != cluster:
                problems.append("python gate: cluster_id %r != %r" % (py.cluster_id, cluster))
            if ts.get("clusterId") != cluster:
                problems.append("ts gate: clusterId %r != %r" % (ts.get("clusterId"), cluster))
        if problems:
            self.fail("LEAK/MISMATCH on %r\n  %s\n  py=%r\n  ts=%r" % (cite, "\n  ".join(problems), py, ts))

    def assertSafe(self, cite, ok_cluster=None, db=None):
        """Variant of a Florida cite: must be veto, or pass on the *correct* record.
        Never fall_through (that would route a Florida-looking cite around the
        local DB) and never pass on a wrong record."""
        py, ts = self.run_both(cite, db)
        problems = []
        for name, verdict, cluster in (("python", py.verdict, py.cluster_id), ("ts", ts.get("verdict"), ts.get("clusterId"))):
            if verdict == "veto":
                continue
            if verdict == "pass" and ok_cluster is not None and cluster == ok_cluster:
                continue
            problems.append("%s gate returned %r (cluster=%r)" % (name, verdict, cluster))
        if problems:
            self.fail("LEAK on %r\n  %s\n  py=%r\n  ts=%r" % (cite, "\n  ".join(problems), py, ts))

    def assertNotPass(self, cite, db=None):
        py, ts = self.run_both(cite, db)
        bad = []
        if py.verdict == "pass":
            bad.append("python gate passed it")
        if ts.get("verdict") == "pass":
            bad.append("ts gate passed it")
        if bad:
            self.fail("LEAK on %r: %s\n  py=%r\n  ts=%r" % (cite, "; ".join(bad), py, ts))
        self.assertEqual(py.verdict, ts.get("verdict"), "verdict parity broken on %r: py=%r ts=%r" % (cite, py, ts))


# ───── vector 1a: fabricated and near-miss citations ─────

class FabricatedCitations(GateCase):
    def test_fabricated_volume_page_florida_veto(self):
        for cite in (
            "999 So. 3d 999 (Fla. 2015)",
            "Doe v. Roe, 999 So. 3d 999 (Fla. 4th DCA 2015)",
            "Doe v. Roe, 999 So. 3d 999, 1001 (Fla. 2015)",
            "999 So. 2d 999 (Fla. 1999)",
            "999 So. 999 (Fla. 1930)",
            "Hernandez v. Walmart Stores, Inc., 888 So. 3d 777 (Fla. 1st DCA 2019)",
        ):
            with self.subTest(cite=cite):
                self.assertBoth(cite, "veto")

    def test_near_miss_keys_veto(self):
        # Real record is 100 So. 3d 200 (Fla. 2012). Every neighbour is fabricated.
        for cite in (
            "Smith v. State, 100 So. 3d 201 (Fla. 2012)",    # page inside the opinion, not its first page
            "Smith v. State, 100 So. 3d 199 (Fla. 2012)",
            "Smith v. State, 101 So. 3d 200 (Fla. 2012)",    # wrong volume
            "Smith v. State, 100 So. 2d 200 (Fla. 2012)",    # wrong series
            "Smith v. State, 100 So. 200 (Fla. 2012)",       # first series
        ):
            with self.subTest(cite=cite):
                self.assertBoth(cite, "veto")

    def test_fabricated_under_every_florida_court_form_veto(self):
        for court in ("Fla.", "Fla. 1st DCA", "Fla. 2d DCA", "Fla. 3d DCA", "Fla. 4th DCA",
                      "Fla. 5th DCA", "Fla. 6th DCA", "Fla. Dist. Ct. App."):
            cite = "Doe v. Roe, 999 So. 3d 999 (%s 2015)" % court
            with self.subTest(court=court):
                self.assertBoth(cite, "veto")

    DCA_FORMS = ("Fla. 1st DCA", "Fla. 2d DCA", "Fla. 3d DCA", "Fla. 4th DCA", "Fla. 5th DCA",
                 "Fla. 6th DCA", "Fla. Dist. Ct. App.", "Fla. 1st Dist. Ct. App.")

    # test_valid_dca_cite_passes_under_every_dca_form_and_any_district_number: moved to
    # pipeline/tests_extended/test_extended_variants.py (tier split; Jones under Fla. 1st DCA still passes in
    # CaptionMismatch.test_correct_caption_passes_control).

    def test_valid_supreme_court_cite_passes(self):
        self.assertBoth("Smith v. State, 100 So. 3d 200 (Fla. 2012)", "pass", cluster=fx.SMITH)
        self.assertBoth("Brown v. Florida Power Corp., 400 So. 2d 100 (Fla. 1981)", "pass", cluster=fx.BROWN)

    def test_dca_record_cited_as_supreme_court_veto(self):
        # court_mismatch: stored fladistctapp, parenthetical names the Florida Supreme Court.
        self.assertBoth("Jones v. Acme Insurance Co., 150 So. 3d 500 (Fla. 2014)", "veto")
        self.assertBoth("150 So. 3d 500 (Fla. 2014)", "veto")
        self.assertBoth("Garcia v. Miami-Dade County, 200 So. 3d 300 (Fla. 2016)", "veto")

    # test_supreme_court_record_cited_as_a_dca_veto: moved to pipeline/tests_extended/test_extended_variants.py
    # (tier split; the direction stays covered by test_court_mismatch_with_pin_or_wrong_caption_still_veto below).

    def test_court_mismatch_with_pin_or_wrong_caption_still_veto(self):
        self.assertBoth("Smith v. State, 100 So. 3d 200, 210 (Fla. 1st DCA 2012)", "veto")
        self.assertBoth("Jones v. Acme Insurance Co., 150 So. 3d 500, 505 (Fla. 2014)", "veto")

    def test_controls_pass_on_every_loaded_florida_series(self):
        self.assertBoth("Smith v. State, 100 So. 3d 200 (Fla. 2012)", "pass", cluster=fx.SMITH)
        self.assertBoth("Brown v. Florida Power Corp., 400 So. 2d 100 (Fla. 1981)", "pass", cluster=fx.BROWN)
        self.assertBoth("State v. Williams, 150 So. 100 (Fla. 1933)", "pass", cluster=fx.WILLIAMS)

    def test_verdicts_are_deterministic(self):
        cite = "Smith v. State, 100 So. 3d 200, 210 (Fla. 2012)"
        results = {fx.py_check(cite, fx.get_fixture().db).verdict for _ in range(5)}
        self.assertEqual(results, {"pass"})


# ───── vector 1b: caption mismatch ─────

class CaptionMismatch(GateCase):
    def test_caption_of_a_different_real_case_veto(self):
        # 100 So. 3d 200 exists, but it is Smith v. State, not any of these.
        for cite in (
            "Hernandez v. Walmart Stores, Inc., 100 So. 3d 200 (Fla. 2012)",
            "Jones v. Acme Insurance Co., 100 So. 3d 200 (Fla. 2012)",   # real caption of cluster 1002
            "Roe v. Wade, 100 So. 3d 200 (Fla. 2012)",
        ):
            with self.subTest(cite=cite):
                self.assertBoth(cite, "veto")

    def test_swapped_captions_veto(self):
        self.assertBoth("Smith v. State, 150 So. 3d 500 (Fla. 1st DCA 2014)", "veto")
        self.assertBoth("Jones v. Acme Insurance Co., 400 So. 2d 100 (Fla. 1981)", "veto")

    def test_correct_caption_passes_control(self):
        self.assertBoth("Smith v. State, 100 So. 3d 200 (Fla. 2012)", "pass", cluster=fx.SMITH)
        self.assertBoth("Jones v. Acme Insurance Co., 150 So. 3d 500 (Fla. 1st DCA 2014)", "pass", cluster=fx.JONES)

    def test_bare_cite_is_existence_only(self):
        self.assertBoth("100 So. 3d 200 (Fla. 2012)", "pass", cluster=fx.SMITH)
        self.assertBoth("200 So. 3d 300 (Fla. 3d DCA 2016)", "pass", cluster=fx.GARCIA)

    def test_caption_does_not_rescue_a_missing_record(self):
        self.assertBoth("Smith v. State, 999 So. 3d 999 (Fla. 2012)", "veto")

    def test_valid_pin_does_not_rescue_wrong_caption(self):
        self.assertBoth("Hernandez v. Walmart Stores, Inc., 100 So. 3d 200, 210 (Fla. 2012)", "veto")


# ───── vector 1c: pin cites ─────

class PinCites(GateCase):
    def test_pin_in_bounds_passes(self):
        for pin in (200, 201, 210, 214, 215):  # includes both inclusive boundaries
            cite = "Smith v. State, 100 So. 3d 200, %d (Fla. 2012)" % pin
            with self.subTest(pin=pin):
                self.assertBoth(cite, "pass", cluster=fx.SMITH)

    def test_pin_below_first_page_veto(self):
        for pin in (199, 150, 1, 0):
            cite = "Smith v. State, 100 So. 3d 200, %d (Fla. 2012)" % pin
            with self.subTest(pin=pin):
                self.assertBoth(cite, "veto")

    def test_pin_above_last_page_veto(self):
        for pin in (216, 217, 460, 9999):
            cite = "Smith v. State, 100 So. 3d 200, %d (Fla. 2012)" % pin
            with self.subTest(pin=pin):
                self.assertBoth(cite, "veto")

    def test_pin_with_null_last_page_veto(self):
        # Garcia has no page-bounds row, so last_page is NULL and the pin cannot be verified.
        for pin in (300, 301, 305, 999):
            cite = "Garcia v. Miami-Dade County, 200 So. 3d 300, %d (Fla. 3d DCA 2016)" % pin
            with self.subTest(pin=pin):
                self.assertBoth(cite, "veto")

    def test_null_last_page_without_pin_still_passes(self):
        self.assertBoth("Garcia v. Miami-Dade County, 200 So. 3d 300 (Fla. 3d DCA 2016)", "pass", cluster=fx.GARCIA)

    def test_pin_on_other_series(self):
        self.assertBoth("Brown v. Florida Power Corp., 400 So. 2d 100, 125 (Fla. 1981)", "pass", cluster=fx.BROWN)
        self.assertBoth("Brown v. Florida Power Corp., 400 So. 2d 100, 131 (Fla. 1981)", "veto")
        self.assertBoth("Brown v. Florida Power Corp., 400 So. 2d 100, 99 (Fla. 1981)", "veto")

    def test_pin_on_fabricated_cite_veto(self):
        self.assertBoth("Doe v. Roe, 999 So. 3d 999, 1000 (Fla. 2015)", "veto")


# ───── vector 2: Florida scope ─────

class FloridaScope(GateCase):
    def test_southern_reporter_without_court_parenthetical_is_malformed_veto(self):
        for cite in (
            "100 So. 3d 200",                       # a real Florida record, but no court named
            "Smith v. State, 100 So. 3d 200",
            "Smith v. State, 100 So. 3d 200, 210",
            "999 So. 3d 999",
            "400 So. 2d 100",
            "150 So. 100",
            "175 So. 3d 700",                        # real Alabama record, still malformed without a court
            "Smith v. State, 100 So. 3d 200 (2012)",  # year only, no court
            "100 So. 3d 200 (citation omitted)",
        ):
            with self.subTest(cite=cite):
                self.assertBoth(cite, "veto")

    def test_other_southern_states_fall_through_not_veto(self):
        for cite in (
            "Ex parte Johnson, 175 So. 3d 700 (Ala. 2015)",
            "State v. Landry, 180 So. 3d 800 (La. 2016)",
            "Doe v. Mississippi Department of Human Services, 190 So. 3d 900 (Miss. 2016)",
            "Doe v. Roe, 555 So. 3d 555 (Ala. 2015)",
            "Doe v. Roe, 555 So. 2d 555 (La. 1990)",
            "Doe v. Roe, 555 So. 555 (Miss. 1940)",
            "Doe v. Roe, 555 So. 3d 555 (Ala. Civ. App. 2015)",
            "Doe v. Roe, 555 So. 3d 555 (Ala. Crim. App. 2015)",
            "Doe v. Roe, 555 So. 3d 555 (La. Ct. App. 2015)",
            "Doe v. Roe, 555 So. 3d 555 (La. App. 1 Cir. 2015)",
            "Doe v. Roe, 555 So. 3d 555 (Miss. Ct. App. 2015)",
        ):
            with self.subTest(cite=cite):
                self.assertBoth(cite, "fall_through")

    def test_other_state_cite_colliding_with_a_florida_key_does_not_pass(self):
        # 100 So. 3d 200 is a Florida record. The same volume/page under Ala./La./Miss. is a different case.
        for court in ("Ala.", "La.", "Miss."):
            cite = "Smith v. State, 100 So. 3d 200 (%s 2012)" % court
            with self.subTest(court=court):
                self.assertBoth(cite, "fall_through")

    def test_federal_and_other_reporters_fall_through(self):
        for cite in (
            "United States v. Perez, 600 F.3d 100 (11th Cir. 2010)",
            "Doe v. Roe, 555 F. Supp. 2d 555 (S.D. Fla. 2010)",
            "Doe v. Roe, 555 U.S. 555 (2009)",
            "Doe v. Roe, 555 S.W.3d 555 (Tex. 2018)",
        ):
            with self.subTest(cite=cite):
                self.assertBoth(cite, "fall_through")

    def test_federal_court_in_florida_on_southern_reporter_does_not_pass(self):
        # Not a Florida state court. Whether the gate calls this fall_through or veto,
        # it must never pass it on the strength of the Florida record at 100 So. 3d 200.
        self.assertNotPass("Smith v. State, 100 So. 3d 200 (S.D. Fla. 2012)")
        self.assertNotPass("Smith v. State, 100 So. 3d 200 (11th Cir. 2012)")

    def test_fla_l_weekly_unloaded_veto(self):
        for cite in (
            "Doe v. Roe, 35 Fla. L. Weekly 999 (Fla. 2010)",
            "35 Fla. L. Weekly 999 (Fla. 3d DCA 2010)",
            "Doe v. Roe, 35 Fla. L. Weekly D999 (Fla. 3d DCA 2010)",
            "Doe v. Roe, 35 Fla. L. Weekly S555 (Fla. 2010)",
            "Doe v. Roe, 48 Fla. L. Weekly S101 (Fla. 2023)",
            "35 Fla. L. Weekly D999",                              # no parenthetical at all
        ):
            with self.subTest(cite=cite):
                self.assertBoth(cite, "veto")

    def test_fla_l_weekly_loaded_passes(self):
        self.assertBoth("Rodriguez v. State, 36 Fla. L. Weekly 1234 (Fla. 2011)", "pass", cluster=fx.FLW)
        self.assertBoth("36 Fla. L. Weekly 1234 (Fla. 2011)", "pass", cluster=fx.FLW)

    def test_fla_l_weekly_loaded_with_lettered_page_passes(self):
        # Real Fla. L. Weekly cites carry a section letter (S/D/C). The loaded row was ingested as "D500".
        self.assertBoth("Peterson v. Tallahassee Housing Authority, 37 Fla. L. Weekly D500 (Fla. 1st DCA 2012)",
                        "pass", cluster=fx.FLW_LETTERED)

    def test_fla_l_weekly_section_letter_must_match_exactly(self):
        # Loaded row is 37 Fla. L. Weekly D500 (section 'D'). Wrong, missing or look-alike sections must not match.
        for cite in (
            "Peterson v. Tallahassee Housing Authority, 37 Fla. L. Weekly S500 (Fla. 1st DCA 2012)",
            "Peterson v. Tallahassee Housing Authority, 37 Fla. L. Weekly C500 (Fla. 1st DCA 2012)",
            "Peterson v. Tallahassee Housing Authority, 37 Fla. L. Weekly 500 (Fla. 1st DCA 2012)",
            "37 Fla. L. Weekly S500 (Fla. 1st DCA 2012)",
            "37 Fla. L. Weekly 500",
        ):
            with self.subTest(cite=cite):
                self.assertBoth(cite, "veto")

    def test_fla_l_weekly_numeric_row_does_not_match_a_lettered_cite(self):
        # Loaded numeric row is 36 Fla. L. Weekly 1234 (section ''). A lettered cite at the same page is a different key.
        for cite in (
            "Rodriguez v. State, 36 Fla. L. Weekly D1234 (Fla. 2011)",
            "Rodriguez v. State, 36 Fla. L. Weekly S1234 (Fla. 2011)",
        ):
            with self.subTest(cite=cite):
                self.assertBoth(cite, "veto")

    def test_fla_l_weekly_loaded_with_wrong_caption_veto(self):
        self.assertBoth("Hernandez v. Walmart Stores, Inc., 36 Fla. L. Weekly 1234 (Fla. 2011)", "veto")

    def test_fla_l_weekly_supp_unloaded_veto(self):
        for cite in (
            "Doe v. Roe, 20 Fla. L. Weekly Supp. 999 (Fla. 11th Cir. Ct. 2012)",
            "Doe v. Roe, 20 Fla. L. Weekly Supp. 999a (Fla. 11th Cir. Ct. 2012)",
            "20 Fla. L. Weekly Supp. 999",
        ):
            with self.subTest(cite=cite):
                self.assertBoth(cite, "veto")

    def test_fla_l_weekly_supp_loaded_passes(self):
        self.assertBoth("Doe v. Board of Trustees, 20 Fla. L. Weekly Supp. 300 (Fla. 11th Cir. Ct. 2012)",
                        "pass", cluster=fx.FLW_SUPP)

    def test_fla_l_weekly_fed_falls_through(self):
        for cite in (
            "Acme Corp. v. Widget LLC, 22 Fla. L. Weekly Fed. 500 (11th Cir. 2010)",
            "Doe v. Roe, 22 Fla. L. Weekly Fed. D100 (11th Cir. 2010)",
            "Doe v. Roe, 22 Fla. L. Weekly Fed. S50 (U.S. 2010)",
            "Doe v. Roe, 22 Fla. L. Weekly Fed. C100 (Bankr. S.D. Fla. 2010)",
            # same numbers as the loaded (non-Fed.) rows, must not be matched against them
            "Rodriguez v. State, 36 Fla. L. Weekly Fed. 1234 (11th Cir. 2011)",
        ):
            with self.subTest(cite=cite):
                self.assertBoth(cite, "fall_through")

    def test_fla_l_weekly_fed_is_not_ingested(self):
        con = sqlite3.connect("file:%s?mode=ro" % fx.get_fixture().db, uri=True)
        try:
            n = con.execute("SELECT COUNT(*) FROM citation_index WHERE cluster_id = ?", (fx.FLW_FED,)).fetchone()[0]
        finally:
            con.close()
        self.assertEqual(n, 0, "Fla. L. Weekly Fed. row leaked into the Florida index")

    def test_rule_9_800_florida_court_forms_do_not_escape_scope(self):
        # Rule 9.800 style court and year forms. A fabricated cite must be vetoed under all of them.
        for paren in (
            "(Fla. 1st Dist. Ct. App. 2015)",
            "(Fla. Dist. Ct. App. 2015)",
            "(Fla. 2d Dist. Ct. App. 2015)",
            "(Fla. 6th DCA 2024)",
            "(Fla. 4th DCA Jan. 7, 2015)",
            "(Fla. Jan. 7, 2015)",
        ):
            cite = "Doe v. Roe, 999 So. 3d 999 %s" % paren
            with self.subTest(paren=paren):
                self.assertBoth(cite, "veto")

    def test_slip_opinion_placeholders_never_pass(self):
        # Florida slip opinions have no volume/page yet ("___ So. 3d ___"). Nothing to verify locally.
        for cite in (
            "Smith v. State, ___ So. 3d ___ (Fla. 2023)",
            "Smith v. State, ___ So. 3d ___, 2023 WL 1234567 (Fla. Mar. 2, 2023)",
            "Smith v. State, No. SC2022-1234 (Fla. Mar. 2, 2023)",
            "Smith v. State, No. 1D22-1234, slip op. at 5 (Fla. 1st DCA Mar. 2, 2023)",
        ):
            with self.subTest(cite=cite):
                self.assertNotPass(cite)

    def test_slip_opinion_with_florida_court_and_southern_reporter_is_vetoed(self):
        # Southern Reporter + Florida court + nothing resolvable is a Florida key that fails existence.
        for cite in (
            "Smith v. State, ___ So. 3d ___ (Fla. 2023)",
            "Smith v. State, ___ So. 3d ___ (Fla. 1st DCA 2023)",
        ):
            with self.subTest(cite=cite):
                self.assertBoth(cite, "veto")


# ───── fail-closed behaviour ─────

class FailClosed(GateCase):
    VALID = "Smith v. State, 100 So. 3d 200 (Fla. 2012)"

    def _tmp(self):
        return fx.new_tempdir("kf_adv_fc_")

    def test_missing_db_file_veto_and_not_created(self):
        missing = self._tmp() / "does_not_exist.db"
        self.assertBoth(self.VALID, "veto", db=missing)
        self.assertFalse(missing.exists(), "gate created a database file (not read-only)")

    def test_db_path_is_a_directory_veto(self):
        self.assertBoth(self.VALID, "veto", db=self._tmp())

    def test_empty_db_file_veto(self):
        p = self._tmp() / "empty.db"
        p.write_bytes(b"")
        self.assertBoth(self.VALID, "veto", db=p)

    def test_garbage_db_file_veto(self):
        p = self._tmp() / "garbage.db"
        p.write_bytes(b"this is not a sqlite database" * 100)
        self.assertBoth(self.VALID, "veto", db=p)

    def test_db_without_citation_index_table_veto(self):
        p = self._tmp() / "no_table.db"
        con = sqlite3.connect(p)
        con.execute("CREATE TABLE something_else (id INTEGER)")
        con.commit()
        con.close()
        self.assertBoth(self.VALID, "veto", db=p)

    def test_citation_index_missing_columns_veto(self):
        p = self._tmp() / "bad_columns.db"
        con = sqlite3.connect(p)
        con.execute("CREATE TABLE citation_index (reporter TEXT, volume INTEGER, page INTEGER, cluster_id INTEGER)")
        con.execute("INSERT INTO citation_index VALUES ('So. 3d', 100, 200, 1001)")
        con.commit()
        con.close()
        self.assertBoth(self.VALID, "veto", db=p)
        self.assertBoth("100 So. 3d 200 (Fla. 2012)", "veto", db=p)

    def test_empty_citation_index_veto(self):
        p = self._tmp() / "empty_index.db"
        con = sqlite3.connect(p)
        con.execute("CREATE TABLE citation_index (reporter TEXT, volume INTEGER, page INTEGER, cluster_id INTEGER, "
                    "case_name TEXT, court_id TEXT, first_page INTEGER, last_page INTEGER)")
        con.commit()
        con.close()
        self.assertBoth(self.VALID, "veto", db=p)

    def test_locked_db_veto(self):
        src = fx.get_fixture().db
        copy = self._tmp() / "locked.db"
        shutil.copy(src, copy)
        con = sqlite3.connect(copy, isolation_level=None)
        try:
            mode = con.execute("PRAGMA journal_mode").fetchone()[0]
            if str(mode).lower() == "wal":
                self.skipTest("fixture DB is WAL; readers are not blocked by a writer lock")
            con.execute("BEGIN EXCLUSIVE")
            self.assertBoth(self.VALID, "veto", db=copy)
        finally:
            con.close()

    def test_gate_never_mutates_the_database(self):
        db = fx.get_fixture().db
        before = Path(db).read_bytes()
        names_before = sorted(os.listdir(Path(db).parent))
        for cite in (self.VALID, "Doe v. Roe, 999 So. 3d 999 (Fla. 2015)", "100 So. 3d 200"):
            fx.py_check(cite, db)
            fx.ts_check(cite, db)
        self.assertEqual(before, Path(db).read_bytes(), "gate modified the database file")
        self.assertEqual(names_before, sorted(os.listdir(Path(db).parent)),
                         "gate left journal/wal/shm files next to the database")

    def test_sql_injection_in_citation_text_does_not_pass_or_mutate(self):
        db = fx.get_fixture().db
        before = Path(db).read_bytes()
        for cite in (
            "Doe v. Roe', 999 So. 3d 999 (Fla. 2015); DROP TABLE citation_index;--",
            "Doe v. Roe, 999 So. 3d 999' OR '1'='1 (Fla. 2015)",
            "Doe v. Roe, 999 So. 3d 999 (Fla. 2015) UNION SELECT 1, 'So. 3d', 100, 200, 'x', 'fla', 1, 1",
            "Smith v. State'; DROP TABLE citation_index;-- , 100 So. 3d 200 (Fla. 2012)",
        ):
            with self.subTest(cite=cite):
                py, ts = self.run_both(cite, db)
                if "999" in cite:
                    self.assertNotEqual(py.verdict, "pass", repr(py))
                    self.assertNotEqual(ts.get("verdict"), "pass", repr(ts))
                self.assertNotEqual(ts.get("verdict"), "THROW", repr(ts))
        self.assertEqual(before, Path(db).read_bytes())
        # table still intact and the control still passes
        self.assertBoth(self.VALID, "pass", cluster=fx.SMITH)


# ───── vector 1d: OCR artifacts and Unicode homoglyphs ─────

FAB_BASE = "Doe v. Roe, 999 So. 3d 999 (Fla. 2015)"
FAB_HOMOGLYPHS = {
    "cyrillic_o_in_reporter": "Doe v. Roe, 999 Sо. 3d 999 (Fla. 2015)",
    "greek_omicron_in_reporter": "Doe v. Roe, 999 Sο. 3d 999 (Fla. 2015)",
    "cyrillic_a_in_court": "Doe v. Roe, 999 So. 3d 999 (Flа. 2015)",
    "fullwidth_digits": "Doe v. Roe, ９９９ So. 3d ９９９ (Fla. 2015)",
    "zero_width_space_in_reporter": "Doe v. Roe, 999 So.​ 3d 999 (Fla. 2015)",
    "zero_width_space_in_volume": "Doe v. Roe, 9​99 So. 3d 999 (Fla. 2015)",
    "zero_width_joiner_in_court": "Doe v. Roe, 999 So. 3d 999 (Fl‍a. 2015)",
    "nbsp_separators": "Doe v. Roe, 999 So. 3d 999 (Fla. 2015)",
    "soft_hyphen_in_series": "Doe v. Roe, 999 So. 3­d 999 (Fla. 2015)",
    "bom_prefix": "﻿Doe v. Roe, 999 So. 3d 999 (Fla. 2015)",
}

VALID_BASE = "Smith v. State, 100 So. 3d 200 (Fla. 2012)"
VALID_VARIANTS = {
    # OCR artifacts
    "ocr_l_and_O_in_volume": "Smith v. State, lOO So. 3d 200 (Fla. 2012)",
    "ocr_O_in_volume": "Smith v. State, 1OO So. 3d 200 (Fla. 2012)",
    "ocr_O_in_page": "Smith v. State, 100 So. 3d 2OO (Fla. 2012)",
    "ocr_zero_in_reporter": "Smith v. State, 100 S0. 3d 200 (Fla. 2012)",
    "ocr_digit_one_for_l_in_court": "Smith v. State, 100 So. 3d 200 (F1a. 2012)",
    "ocr_i_for_l_in_court": "Smith v. State, 100 So. 3d 200 (Fia. 2012)",
    "ocr_split_page_digits": "Smith v. State, 100 So. 3d 20 0 (Fla. 2012)",
    "ocr_comma_in_page": "Smith v. State, 100 So. 3d 2,00 (Fla. 2012)",
    # Unicode
    "cyrillic_o_in_reporter": "Smith v. State, 100 Sо. 3d 200 (Fla. 2012)",
    "greek_omicron_in_reporter": "Smith v. State, 100 Sο. 3d 200 (Fla. 2012)",
    "cyrillic_a_in_court": "Smith v. State, 100 So. 3d 200 (Flа. 2012)",
    "cyrillic_es_in_caption": "Smith v. Ѕtate, 100 So. 3d 200 (Fla. 2012)",
    "fullwidth_digits": "Smith v. State, １００ So. 3d ２００ (Fla. 2012)",
    "zero_width_space_in_reporter": "Smith v. State, 100 So.​ 3d 200 (Fla. 2012)",
    "zero_width_space_in_court": "Smith v. State, 100 So. 3d 200 (F​la. 2012)",
    "nbsp_separators": "Smith v. State, 100 So. 3d 200 (Fla. 2012)",
    "soft_hyphen": "Smith v. State, 100 So. 3­d 200 (Fla. 2012)",
    "arabic_indic_digits": "Smith v. State, ١٠٠ So. 3d 200 (Fla. 2012)",
}


class ObfuscatedCitations(GateCase):
    def test_fabricated_cite_with_homoglyphs_or_invisible_chars_veto(self):
        for name, cite in FAB_HOMOGLYPHS.items():
            with self.subTest(variant=name):
                self.assertBoth(cite, "veto")

    # test_valid_cite_variants_never_fall_through_or_pass_wrong_record: moved to
    # pipeline/tests_extended/test_extended_variants.py (tier split; the same VALID_VARIANTS still run through the
    # draft path in test_gate1_draft_mode.py).

    def test_unobfuscated_controls(self):
        self.assertBoth(VALID_BASE, "pass", cluster=fx.SMITH)
        self.assertBoth(FAB_BASE, "veto")

    def test_pin_cite_obfuscation_cannot_defeat_bounds(self):
        for name, cite in {
            "fullwidth_pin": "Smith v. State, 100 So. 3d 200, ４６０ (Fla. 2012)",
            "zwsp_pin": "Smith v. State, 100 So. 3d 200, 4​60 (Fla. 2012)",
        }.items():
            with self.subTest(variant=name):
                self.assertSafe(cite, ok_cluster=None)  # pin 460 is out of bounds, so only veto is acceptable


# ───── vector 1e / 3: free-text extraction (what an LLM draft actually looks like) ─────

class CheckText(unittest.TestCase):
    maxDiff = None

    def _db(self):
        return fx.get_fixture().db

    def _find(self, results, volume):
        return [r for r in results if r.volume == volume]

    def test_paragraph_with_fabricated_florida_cite_is_vetoed(self):
        text = (
            "As the court held in Hernandez v. Walmart Stores, Inc., 999 So. 3d 999, 1001 (Fla. 4th DCA 2019), "
            "the duty is non-delegable. See also Smith v. State, 100 So. 3d 200, 210 (Fla. 2012); "
            "United States v. Perez, 600 F.3d 100 (11th Cir. 2010)."
        )
        results = fx.py_check_text(text, self._db())
        fab = self._find(results, 999)
        self.assertTrue(fab, "fabricated Florida cite was not even extracted: %r" % results)
        self.assertTrue(all(r.verdict == "veto" for r in fab), repr(fab))
        real = self._find(results, 100)
        self.assertTrue(real and all(r.verdict == "pass" for r in real), "control failed: %r" % results)
        fed = self._find(results, 600)
        self.assertTrue(fed and all(r.verdict == "fall_through" for r in fed), "federal cite must fall through: %r" % results)

    def test_paragraph_with_only_a_fabricated_cite_has_a_veto(self):
        text = "The Third District squarely rejected that argument in Doe v. Roe, 999 So. 3d 999 (Fla. 3d DCA 2015)."
        results = fx.py_check_text(text, self._db())
        self.assertTrue(any(r.verdict == "veto" for r in results), repr(results))
        self.assertFalse(any(r.verdict == "pass" for r in results), repr(results))

    def test_other_state_and_unmarked_southern_cites_in_text(self):
        text = (
            "Compare Ex parte Johnson, 175 So. 3d 700 (Ala. 2015), with Doe v. Roe, 555 So. 3d 555, which names no court."
        )
        results = fx.py_check_text(text, self._db())
        ala = self._find(results, 175)
        self.assertTrue(ala and all(r.verdict == "fall_through" for r in ala), repr(results))
        unmarked = self._find(results, 555)
        self.assertTrue(unmarked and all(r.verdict == "veto" for r in unmarked), repr(results))

    def test_fla_l_weekly_in_text(self):
        text = (
            "See Doe v. Roe, 35 Fla. L. Weekly D999 (Fla. 3d DCA 2010); "
            "Doe v. Roe, 22 Fla. L. Weekly Fed. D100 (11th Cir. 2010)."
        )
        results = fx.py_check_text(text, self._db())
        weekly = self._find(results, 35)
        self.assertTrue(weekly and all(r.verdict == "veto" for r in weekly), repr(results))
        fed = self._find(results, 22)
        self.assertTrue(fed and all(r.verdict == "fall_through" for r in fed), repr(results))

    def test_formatting_and_whitespace_tricks_cannot_hide_a_fabricated_cite(self):
        tricks = {
            "newline_in_reporter": "The rule is settled. Doe v. Roe, 999 So.\n3d 999 (Fla. 2015). It follows.",
            "newline_before_page": "The rule is settled. Doe v. Roe, 999 So. 3d\n999 (Fla. 2015). It follows.",
            "newline_in_parenthetical": "The rule is settled. Doe v. Roe, 999 So. 3d 999 (Fla.\n2015). It follows.",
            "double_spaces": "The rule is settled. Doe v. Roe,  999  So.  3d  999  (Fla.  2015). It follows.",
            "tab_separators": "The rule is settled. Doe v. Roe, 999\tSo. 3d\t999 (Fla. 2015). It follows.",
            "bold_markdown": "The rule is settled. **Doe v. Roe, 999 So. 3d 999 (Fla. 2015)**. It follows.",
            "markdown_link": "The rule is settled. [Doe v. Roe, 999 So. 3d 999 (Fla. 2015)](https://example.com/x). It follows.",
            "blockquote": "> Doe v. Roe, 999 So. 3d 999 (Fla. 2015)\n> follows.",
            "nbsp": "The rule is settled. Doe v. Roe, 999 So. 3d 999 (Fla. 2015). It follows.",
            "zero_width_space": "The rule is settled. Doe v. Roe, 999 So.​ 3d 999 (Fla. 2015). It follows.",
            "zero_width_in_volume": "The rule is settled. Doe v. Roe, 9​99 So. 3d 999 (Fla. 2015). It follows.",
            "cyrillic_o": "The rule is settled. Doe v. Roe, 999 Sо. 3d 999 (Fla. 2015). It follows.",
            "fullwidth_digits": "The rule is settled. Doe v. Roe, ９９９ So. 3d ９９９ (Fla. 2015). It follows.",
            "smart_punctuation": "The rule is settled. Doe v. Roe, 999 So.  3d 999 （Fla. 2015）. It follows.",
        }
        for name, text in tricks.items():
            with self.subTest(trick=name):
                results = fx.py_check_text(text, self._db())
                self.assertTrue(
                    any(r.verdict == "veto" for r in results),
                    "fabricated Florida cite slipped through unflagged (results=%r)" % (results,),
                )
                self.assertFalse(any(r.verdict == "pass" for r in results), repr(results))

    def test_text_with_no_citations_is_not_a_pass_by_accident(self):
        results = fx.py_check_text("The plaintiff filed a motion on Tuesday.", self._db())
        self.assertFalse(any(r.verdict == "pass" for r in results), repr(results))

    def test_missing_db_vetoes_every_florida_cite_in_text(self):
        missing = fx.new_tempdir("kf_adv_txt_") / "nope.db"
        results = fx.py_check_text("See Smith v. State, 100 So. 3d 200 (Fla. 2012).", missing)
        self.assertTrue(results, "no result for a Florida cite when the DB is missing")
        self.assertTrue(all(r.verdict == "veto" for r in results), repr(results))


if __name__ == "__main__":
    unittest.main()
