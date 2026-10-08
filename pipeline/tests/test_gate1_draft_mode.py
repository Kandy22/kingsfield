"""Adversarial suite for Gate 1 draft mode: localGate1Text(draft) -> Gate1TextResult[].

Task gate1-draft-mode. Contract under attack (approved design):
  * one result per case-cite occurrence (full, short, Id., supra), ordered by position
  * short/Id./supra resolve through eyecite and inherit the antecedent's verdict
      antecedent veto -> veto; fall_through -> fall_through (fullCitation = antecedent window);
      pass -> the short cite's own pin is checked against the same record
  * well-formed short cites and Id. are never vetoed as `malformed`
  * unresolved/ambiguous short cite -> veto; Id. resolving to a non-case cite ->
    fall_through `non_case_antecedent` with fullCitation null (the only non-veto allowed null)
  * full case cites the scan misses: Florida-ish -> veto `unparsed_citation`, else fall_through
  * the TS wrapper fails closed: any spawn error/timeout/non-zero exit/bad JSON/bad field ->
    exactly one veto result, never []

Three groups:
  A. in-process (pipeline.gate1.check_text): attacks that hold regardless of the new API
  B. through the TS wrapper (needs localGate1Text): short forms, laundering, ambiguity, drops
  C. the wrapper's own failure modes, driven by sabotaging the Python child from outside
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate1_fixture as fx  # noqa: E402
import draft_harness as dh  # noqa: E402
from test_gate1_bypass import FAB_HOMOGLYPHS, VALID_VARIANTS  # noqa: E402

S = "Smith v. State, 100 So. 3d 200 (Fla. 2012)"                       # real, fla, 200-215
FAB = "Doe v. Roe, 999 So. 3d 999 (Fla. 2015)"                          # fabricated Florida
FAB_H = "Hernandez v. Walmart Stores, Inc., 999 So. 3d 999, 1001 (Fla. 4th DCA 2019)"
ALA = "Ex parte Johnson, 175 So. 3d 700 (Ala. 2015)"
LA = "State v. Landry, 180 So. 3d 800 (La. 2016)"
MISS = "Doe v. Mississippi Department of Human Services, 190 So. 3d 900 (Miss. 2016)"
FED = "United States v. Perez, 600 F.3d 100 (11th Cir. 2010)"
GARCIA = "Garcia v. Miami-Dade County, 200 So. 3d 300 (Fla. 3d DCA 2016)"   # real, no page bounds
RODRIGUEZ = "Rodriguez v. State, 36 Fla. L. Weekly 1234 (Fla. 2011)"        # real, 1234-1240


def _db():
    return dh.get_draft_fixture().db


def py_text(draft):
    return fx.py_check_text(draft, _db())


def wrap(cite):
    return "The rule is settled. " + cite + ". It follows."


# ───── A. in-process: scope and extraction, independent of the new result shape ─────

class DraftScopeInProcess(unittest.TestCase):
    def test_every_cite_in_a_mixed_draft_gets_exactly_one_result_in_order(self):
        draft = "; ".join([FAB_H, S, ALA, LA, MISS, FED]) + "."
        got = [r.verdict for r in py_text(draft)]
        self.assertEqual(got, ["veto", "pass", "fall_through", "fall_through", "fall_through", "fall_through"],
                         "a cite was dropped, reordered or mis-scoped: %r" % got)

    def test_florida_scope_rules_hold_inside_a_draft(self):
        draft = "; ".join([
            "Doe v. Roe, 555 So. 3d 555 (Ala. 2015)",
            "Doe v. Roe, 556 So. 3d 556 (La. 2015)",
            "Doe v. Roe, 557 So. 3d 557 (Miss. 2015)",
            "Doe v. Roe, 558 So. 3d 558",                                       # Southern Reporter, no court
            "Doe v. Roe, 35 Fla. L. Weekly D999 (Fla. 3d DCA 2010)",            # not loaded yet
            "Doe v. Roe, 22 Fla. L. Weekly Fed. D100 (11th Cir. 2010)",         # federal
        ]) + "."
        got = [r.verdict for r in py_text(draft)]
        self.assertEqual(got, ["fall_through", "fall_through", "fall_through", "veto", "veto", "fall_through"], got)

    def test_florida_cite_after_a_veto_is_still_checked(self):
        got = [r.verdict for r in py_text("%s; %s; %s." % (FAB, S, FAB_H))]
        self.assertEqual(got, ["veto", "pass", "veto"], got)

    def test_controls(self):
        self.assertEqual([r.verdict for r in py_text(wrap(S))], ["pass"])
        self.assertEqual([r.verdict for r in py_text(wrap(FAB))], ["veto"])


# Fabricated Florida cites dressed so the extractor might not see them. In draft mode "not seen" means
# "released unverified", so each must come back as a veto (never pass, never fall_through, never silence).
FAB_HIDING = {
    "md_escaped_period": r"Doe v. Roe, 999 So\. 3d 999 (Fla. 2015)",
    "md_escaped_period_and_paren": r"Doe v. Roe, 999 So\. 3d 999 \(Fla\. 2015\)",
    "html_nbsp_entity": "Doe v. Roe, 999 So.&nbsp;3d 999 (Fla. 2015)",
    "html_numeric_entity": "Doe v. Roe, 999 So.&#160;3d 999 (Fla. 2015)",
    "html_tag_between_tokens": "Doe v. Roe, 999 So.<b></b> 3d 999 (Fla. 2015)",
    "html_tag_inside_reporter": "Doe v. Roe, 999 So<span>.</span> 3d 999 (Fla. 2015)",
    "html_comment_inside": "Doe v. Roe, 999 So.<!-- x --> 3d 999 (Fla. 2015)",
    "italic_reporter": "Doe v. Roe, 999 *So. 3d* 999 (Fla. 2015)",
    "bold_volume": "Doe v. Roe, **999** So. 3d 999 (Fla. 2015)",
    "nul_in_reporter": "Doe v. Roe, 999 So.\x00 3d 999 (Fla. 2015)",
    "unit_separator_as_space": "Doe v. Roe, 999\x1fSo. 3d 999 (Fla. 2015)",
    "del_in_reporter": "Doe v. Roe, 999 So.\x7f 3d 999 (Fla. 2015)",
    "backspace_in_reporter": "Doe v. Roe, 999 So.\x08 3d 999 (Fla. 2015)",
    "variation_selector": "Doe v. Roe, 999 So.️ 3d 999 (Fla. 2015)",
    "combining_dot_above": "Doe v. Roe, 999 Sȯ. 3d 999 (Fla. 2015)",
    "braille_blank_in_reporter": "Doe v. Roe, 999 So.⠀ 3d 999 (Fla. 2015)",
    "armenian_full_stop": "Doe v. Roe, 999 So։ 3d 999 (Fla. 2015)",
    "arabic_indic_page": "Doe v. Roe, 999 So. 3d ٩٩٩ (Fla. 2015)",
    "line_separator_in_reporter": "Doe v. Roe, 999 So.  3d 999 (Fla. 2015)",
    "mathematical_bold_reporter": "Doe v. Roe, 999 \U0001d412\U0001d428. 3d 999 (Fla. 2015)",
    "superscript_volume": "Doe v. Roe, ⁹⁹⁹ So. 3d 999 (Fla. 2015)",
    "all_caps": "DOE V. ROE, 999 SO. 3D 999 (FLA. 2015)",
    "ordinal_series": "Doe v. Roe, 999 So. 3rd 999 (Fla. 2015)",
    "ocr_zero_for_o_in_reporter": "Doe v. Roe, 999 S0. 3d 999 (Fla. 2015)",
    "ocr_one_for_l_in_court": "Doe v. Roe, 999 So. 3d 999 (F1a. 2015)",
    "ocr_i_for_l_in_court": "Doe v. Roe, 999 So. 3d 999 (Fia. 2015)",
    "hyphenated_line_break": "Doe v. Roe, 999 So.-\n3d 999 (Fla. 2015)",
    "in_table_cell": "| Doe v. Roe | 999 So. 3d 999 (Fla. 2015) |",
    "in_code_fence": "```\nDoe v. Roe, 999 So. 3d 999 (Fla. 2015)\n```",
    "in_footnote_definition": "[^1]: Doe v. Roe, 999 So. 3d 999 (Fla. 2015)",
    "in_nested_parens": "(see Doe v. Roe, 999 So. 3d 999 (Fla. 2015))",
    "florida_court_wrong_spelling_dca": "Doe v. Roe, 999 So. 3d 999 (Fla. 1st D.C.A. 2015)",
    "florida_court_no_period": "Doe v. Roe, 999 So. 3d 999 (Fla 2015)",
    "florida_court_full_word": "Doe v. Roe, 999 So. 3d 999 (Florida 2015)",
    "florida_court_fl": "Doe v. Roe, 999 So. 3d 999 (Fl. 2015)",
    "florida_court_district_form": "Doe v. Roe, 999 So. 3d 999 (Fla. App. 1 Dist. 2015)",
    "florida_court_upper": "Doe v. Roe, 999 So. 3d 999 (FLA. 2015)",
    "florida_circuit_court": "Doe v. Roe, 999 So. 3d 999 (Fla. 11th Cir. Ct. 2015)",
    "five_digit_volume": "Doe v. Roe, 12345 So. 3d 999 (Fla. 2015)",
    "seven_digit_page": "Doe v. Roe, 999 So. 3d 1234567 (Fla. 2015)",
    "trailing_letter_on_page": "Doe v. Roe, 999 So. 3d 999a (Fla. 2015)",
    "missing_space_before_reporter": "Doe v. Roe, 999So. 3d 999 (Fla. 2015)",
    "missing_space_before_page": "Doe v. Roe, 999 So. 3d999 (Fla. 2015)",
    "slip_opinion_blank_volume_and_page": "Doe v. Roe, ___ So. 3d ___ (Fla. 2015)",
    "slip_opinion_blank_volume": "Doe v. Roe, ___ So. 3d 999 (Fla. 2015)",
    "slip_opinion_blank_page": "Doe v. Roe, 999 So. 3d ___ (Fla. 2015)",
}


class DraftExtractionHolesInProcess(unittest.TestCase):
    maxDiff = None

    def _assert_vetoed(self, text):
        results = py_text(text)
        verdicts = [r.verdict for r in results]
        self.assertTrue(results, "SILENTLY DROPPED: no result at all, the cite would be released unverified: %r" % text)
        self.assertIn("veto", verdicts, "no veto for a fabricated Florida cite: %r -> %r" % (text, verdicts))
        self.assertNotIn("pass", verdicts, "fabricated Florida cite passed: %r" % text)
        for r in results:
            # eyecite can read a court parenthetical ("1 Dist. 2015") as a second, non-Florida citation; that
            # extra fall_through is noise. A fall_through that carries a Florida reporter is the real leak.
            if r.verdict == "fall_through":
                self.assertNotRegex(r.text, r"(?i)\bso\b\.?|weekly",
                                    "fabricated Florida cite routed to CourtListener: %r -> %r" % (text, r))

    def test_fabricated_florida_cite_is_never_dropped_passed_or_routed_around(self):
        for name, cite in FAB_HIDING.items():
            with self.subTest(variant=name):
                self._assert_vetoed(wrap(cite))

    def test_homoglyph_and_invisible_character_variants_inside_a_draft(self):
        for name, cite in FAB_HOMOGLYPHS.items():
            with self.subTest(variant=name):
                self._assert_vetoed(wrap(cite))

    def test_valid_cite_variants_never_fall_through_or_pass_the_wrong_record(self):
        # OCR-damaged or homoglyphed forms of a REAL cite. A veto is fine, a pass on SMITH is fine; silence,
        # fall_through and a pass on any other record are not. Single-cite mode vetoes every one of these.
        for name, cite in VALID_VARIANTS.items():
            with self.subTest(variant=name):
                results = py_text("The Court held as much in %s." % cite)
                self.assertTrue(results, "SILENTLY DROPPED (single-cite mode vetoes this as unparseable): %r" % cite)
                for r in results:
                    if r.verdict == "pass":
                        self.assertEqual(r.cluster_id, fx.SMITH, "passed the wrong record: %r -> %r" % (cite, r))
                    else:
                        self.assertEqual(r.verdict, "veto", "%r -> %r" % (cite, r))

    # Scaling shapes: draft builder(n). Every shape is a past or plausible ReDoS / quadratic input; n is kept small
    # because the property is the RATIO t(2n)/t(n), measured in this process on this machine, not an absolute time.
    SCALING_SHAPES = {
        # check_text once stripped trailing separators with re.sub(r"[ ,]+$", ...): quadratic on this run
        "comma_space_run_before_cite": (lambda n: (", " * n) + "x " + FAB + ".", 4000),
        "cite_start_flood": (lambda n: ("1 " * n) + FAB + ".", 4000),
        "long_prose_then_cite": (lambda n: ("The court held that the rule applies to every case. " * n) + FAB + ".", 200),
        "deep_parens": (lambda n: "(" * n + FAB + ")" * n, 1500),
        "many_fabricated_cites": (lambda n: " ".join(
            "Doe v. Roe, %d So. 3d %d (Fla. 2015)." % (900 + i, 1000 + i) for i in range(n)), 15),
        "valid_cite_flood": (lambda n: " ".join("Smith v. State, 100 So. 3d 200 (Fla. 2012)." for _ in range(n)), 15),
    }
    SCALING_FACTOR = 2.5      # doubling the draft may cost at most 2.5x (linear is 2x; quadratic is 4x)
    SCALING_NOISE_S = 0.05    # absolute slack for timer / scheduler noise on very small baselines

    @staticmethod
    def _best_of(draft, reps=3):
        import time
        best = None
        for _ in range(reps):
            t0 = time.perf_counter()
            py_text(draft)
            took = time.perf_counter() - t0
            best = took if best is None else min(best, took)
        return best

    def test_extraction_is_linear_in_the_draft_not_quadratic(self):
        py_text("warm up " + S)  # eyecite and the reporter tables are loaded once, outside the measurement
        for name, (build, n) in self.SCALING_SHAPES.items():
            with self.subTest(shape=name):
                t1 = self._best_of(build(n))
                t2 = self._best_of(build(2 * n))
                self.assertLessEqual(
                    t2, self.SCALING_FACTOR * t1 + self.SCALING_NOISE_S,
                    "%s: doubling n=%d took %.3f s -> %.3f s (x%.1f); scaling is worse than linear"
                    % (name, n, t1, t2, t2 / max(t1, 1e-9)))

    def test_a_draft_over_the_size_cap_is_one_too_long_veto(self):
        # The at-cap cost is not exercised with a 200 KB draft any more (that was the heaviest case in the suite);
        # the cap itself is cheap to prove from the far side of it.
        for draft in ("a" * (200_000 + 1), (S + " ") * 6000):
            r = py_text(draft)
            self.assertEqual([(x.verdict, x.reason) for x in r], [("veto", "too_long")], len(draft))

    def test_residue_detector_may_veto_prose_with_so_and_a_number_but_never_pass_or_route_it(self):
        # Ruling: Florida reporter tokens beside numbers in prose are vetoed as unparsed citations; "So." is also
        # an abbreviation of "South", so this over-veto is intended fail-safe behaviour. It must never become a
        # pass or a fall_through (nothing is cited, so nothing may be verified or sent to CourtListener).
        prose = (
            "She has served 12 So. Fla. counties since 2010.",
            "The firm opened 5 So. Cal. offices in 2019.",
            "He moved to 3 So. Carolina towns before 1999.",
            "Volume 2 of the So. Atlantic series was reissued in 2015.",
            "The 3d So. District court held a hearing on 14 motions.",
        )
        for text in prose:
            with self.subTest(text=text):
                got = [(r.verdict, r.reason) for r in py_text(text)]
                self.assertTrue(all(v == "veto" for v, _why in got),
                                "prose with no citation was passed or routed to CourtListener: %r" % (got,))

    def test_many_cites_none_dropped(self):
        n = 40
        text = " ".join("Doe v. Roe, %d So. 3d %d (Fla. 2015)." % (900 + i, 1000 + i) for i in range(n))
        got = py_text(text)
        self.assertEqual(len(got), n, "expected one result per cite, got %d" % len(got))
        self.assertTrue(all(r.verdict == "veto" for r in got))


# A REAL record (100 So. 3d 200 is Smith v. State) cited under a WRONG caption, with the caption dressed the way
# markdown / HTML / legal writing dress case names. In draft mode the caption is cut out of the surrounding prose
# by token shape; if the cut fails, the caption check is silently skipped and the cite passes on existence alone.
WRONG_CAPTION = "Hernandez v. Walmart Stores, Inc."
REAL_TAIL = "100 So. 3d 200 (Fla. 2012)"
CAPTION_DRESSINGS = {
    "plain_control": "{c}, " + REAL_TAIL,
    "italic_star": "*{c}*, " + REAL_TAIL,
    "bold_star": "**{c}**, " + REAL_TAIL,
    "bold_italic_star": "***{c}***, " + REAL_TAIL,
    "italic_underscore": "_{c}_, " + REAL_TAIL,
    "markdown_link": "[{c}](https://example.com/x), " + REAL_TAIL,
    "html_em": "<em>{c}</em>, " + REAL_TAIL,
    "signal_then_italic": "*See* *{c}*, " + REAL_TAIL,
    "parenthesized": "({c}, " + REAL_TAIL + ")",
    "bracketed": "[{c}, " + REAL_TAIL + "]",
    "straight_quotes": '"{c}," ' + REAL_TAIL,
    "curly_quotes": "“{c},” " + REAL_TAIL,
    "heading": "### {c}, " + REAL_TAIL,
}
ET_AL_VARIANTS = {
    "et_al": "Hernandez et al. v. Walmart Stores, Inc., " + REAL_TAIL,
    "comma_et_al": "Hernandez, et al. v. Walmart Stores, Inc., " + REAL_TAIL,
    "inc_et_al": "Hernandez Holdings, Inc. et al. v. Walmart Stores, Inc., " + REAL_TAIL,
    "ex_rel_lowercase_relator": "State ex rel. Hernandez v. Walmart Stores, Inc., " + REAL_TAIL,
    "italic_et_al": "*Hernandez et al. v. Walmart Stores, Inc.*, " + REAL_TAIL,
}


class CaptionCheckSurvivesFormattingInDrafts(unittest.TestCase):
    maxDiff = None

    def _wrong(self, cite):
        results = py_text("The rule is settled. See " + cite + ". It follows.")
        verdicts = [r.verdict for r in results]
        self.assertTrue(results, "SILENTLY DROPPED: %r" % cite)
        self.assertNotIn("pass", verdicts,
                         "WRONG CAPTION PASSED on a real record (caption check skipped): %r -> %r" % (cite, results))
        self.assertNotIn("fall_through", verdicts, "%r -> %r" % (cite, results))
        self.assertIn("veto", verdicts, "%r -> %r" % (cite, verdicts))

    def test_wrong_caption_is_vetoed_however_the_caption_is_dressed(self):
        for name, tpl in CAPTION_DRESSINGS.items():
            with self.subTest(dressing=name):
                self._wrong(tpl.format(c=WRONG_CAPTION))

    def test_wrong_plaintiff_with_the_right_defendant_is_vetoed_however_dressed(self):
        # "State" is the real defendant. A dressing that eats the plaintiff leaves " v. State", which matches.
        for name, tpl in CAPTION_DRESSINGS.items():
            with self.subTest(dressing=name):
                self._wrong(tpl.format(c="Hernandez v. State"))

    def test_et_al_and_lowercase_tokens_do_not_disable_the_caption_check(self):
        for name, cite in ET_AL_VARIANTS.items():
            with self.subTest(variant=name):
                self._wrong(cite)

    def test_the_same_dressings_with_the_right_caption_are_never_routed_around(self):
        for name, tpl in CAPTION_DRESSINGS.items():
            with self.subTest(dressing=name):
                results = py_text("See " + tpl.format(c="Smith v. State") + ".")
                self.assertTrue(results)
                for r in results:
                    if r.verdict == "pass":
                        self.assertEqual(r.cluster_id, fx.SMITH)
                    else:
                        self.assertEqual(r.verdict, "veto", repr(r))


# ───── B. through the TS wrapper: short forms, Id., supra, laundering, drops ─────

SHORT_CASES = {
    # --- Florida short cites and Id. resolving to a Florida antecedent are checked locally ---
    "fl_chain": S + ". Smith, 100 So. 3d at 205. Id. at 210. Id.",
    "fl_short_oob": S + ". Smith, 100 So. 3d at 460.",
    "fl_short_below": S + ". Smith, 100 So. 3d at 150.",
    "fl_short_ranges": S + ". Smith, 100 So. 3d at 215. Smith, 100 So. 3d at 205-210. Smith, 100 So. 3d at 205-216.",
    "fl_short_footnote": S + ". Smith, 100 So. 3d at 205 n.3. Smith, 100 So. 3d at 460 n.3.",
    "fl_id_chain": S + ". Id. at 205. Id. at 210. Id. at 460.",
    "fl_id_lowercase_signal": S + ". See id. at 460.",
    "fl_markdown_italics": "*Smith v. State*, 100 So. 3d 200 (Fla. 2012). *Smith*, 100 So. 3d at 460. *Id.* at 461.",
    "fl_supra": S + ". Smith, supra, at 205. Smith, supra, at 460.",
    "garcia_null_bounds": GARCIA + ". Garcia, 200 So. 3d at 305.",
    "weekly_chain": RODRIGUEZ + ". Rodriguez, 36 Fla. L. Weekly at 1236. Rodriguez, 36 Fla. L. Weekly at 1250.",
    "weekly_orphan": "Rodriguez, 36 Fla. L. Weekly at 1236.",
    "weekly_unloaded_chain": "Doe v. Roe, 35 Fla. L. Weekly D999 (Fla. 3d DCA 2010). Doe, 35 Fla. L. Weekly at D1000.",
    # --- antecedent vetoed -> every dependent form vetoed ---
    "id_after_vetoed_full": FAB + ". Id. at 1000.",
    "short_after_vetoed_full": FAB + ". Doe, 999 So. 3d at 1000.",
    "supra_after_vetoed_full": FAB + ". Doe, supra, at 1000.",
    "id_after_string_cite": S + "; " + FAB + ". Id. at 205.",
    # --- non-case antecedent ---
    "id_after_statute": S + ". See 42 U.S.C. § 1983. Id. at 460.",
    "id_chain_after_statute": S + ". See 42 U.S.C. § 1983. Id. at 460. Id. at 461.",
    # --- unresolved ---
    "id_before_antecedent": "Id. at 205. " + S + ".",
    "short_orphan": "Smith, 100 So. 3d at 205.",
    "short_orphan_bare": "See 100 So. 3d at 205.",
    "short_orphan_federal": "Perez, 600 F.3d at 105.",
    "supra_orphan": "Smith, supra, at 205.",
    "id_orphan": "See id. at 205.",
    "short_before_antecedent": "Smith, 100 So. 3d at 205. " + S + ".",
    "supra_before_antecedent": "Smith, supra, at 205. " + S + ".",
    "bare_short_after_florida": S + ". See 100 So. 3d at 205. See 100 So. 3d at 460.",
    # signal stripping must not become a way to dodge the name check
    "signal_right_name": S + ". See Smith, 100 So. 3d at 205.",
    "signal_wrong_name": S + ". See Hernandez, 100 So. 3d at 205.",
    "signal_also_wrong_name": S + ". See also Hernandez, 100 So. 3d at 205.",
    "signal_cf_wrong_name": S + ". Cf. Hernandez, 100 So. 3d at 205.",
    "signal_but_see_wrong_name": S + ". But see Hernandez, 100 So. 3d at 205.",
    "signal_wrong_name_after_alabama": "Ex parte Johnson, 100 So. 3d 555 (Ala. 2015). See Smith, 100 So. 3d at 205.",
    "signal_wrong_name_after_fed": FED + ". See Hernandez, 600 F.3d at 105.",
    # whole-word party containment: a longer or shorter near-match of a party name is a different name
    "short_name_superstring": S + ". Smithson, 100 So. 3d at 205.",
    "short_name_substring": S + ". Smit, 100 So. 3d at 205.",
    "short_name_prefix_of_word": S + ". Sta, 100 So. 3d at 205.",
    "short_name_defendant": S + ". State, 100 So. 3d at 205.",
    "short_name_case_variant": S + ". SMITH, 100 So. 3d at 205.",
    "short_wrong_series": S + ". Smith, 100 So. 2d at 205.",
    "short_wrong_volume": S + ". Smith, 101 So. 3d at 205.",
    # --- mismatch / laundering / ambiguity ---
    "supra_name_mismatch": S + ". Hernandez, supra, at 205.",
    "short_name_mismatch": S + ". Hernandez, 100 So. 3d at 205.",
    "launder_alabama_name": "Ex parte Johnson, 100 So. 3d 555 (Ala. 2015). Smith, 100 So. 3d at 205.",
    "launder_alabama_florida_paren": "Ex parte Johnson, 100 So. 3d 555 (Ala. 2015). Smith v. State, 100 So. 3d at 205 (Fla. 2012).",
    "launder_alabama_other_volume": "Ex parte Johnson, 175 So. 3d 700 (Ala. 2015). Smith, 100 So. 3d at 205.",
    "short_inherits_alabama": "Ex parte Johnson, 100 So. 3d 555 (Ala. 2015). See 100 So. 3d at 205.",
    "ambiguous_fl_fl": S + ". Davis v. State, 100 So. 3d 300 (Fla. 2012). See 100 So. 3d at 205.",
    "ambiguous_fl_ala": S + ". Jones v. Doe, 100 So. 3d 555 (Ala. 2015). See 100 So. 3d at 205.",
    "same_name_collision": S + ". Smith v. State, 100 So. 3d 555 (Ala. 2015). Smith, 100 So. 3d at 205.",
    "disambiguated_by_name": S + ". Jones v. Doe, 100 So. 3d 555 (Ala. 2015). Smith, 100 So. 3d at 205. Smith, 100 So. 3d at 556.",
    "supra_ambiguous": S + ". Smith v. Acme Corp., 101 So. 3d 600 (Fla. 2013). Smith, supra, at 205.",
    # --- mixed jurisdictions ---
    "federal_chain": FED + ". Perez, 600 F.3d at 105. Id. at 106.",
    "mixed": "; ".join([S, ALA, FED]) + ". Smith, 100 So. 3d at 210. Johnson, 175 So. 3d at 705. Perez, 600 F.3d at 105. Id. at 106.",
    "mixed_fabricated": FAB_H + "; " + ALA + ". Hernandez, 999 So. 3d at 1001. Johnson, 175 So. 3d at 705.",
    # --- the scan misses these; eyecite must not let them vanish ---
    "unparsed_five_digit_volume": "Doe v. Roe, 12345 So. 3d 999 (Fla. 2015).",
    "unparsed_seven_digit_page": "Doe v. Roe, 999 So. 3d 1234567 (Fla. 2015).",
    "unparsed_trailing_letter_page": "Doe v. Roe, 999 So. 3d 999a (Fla. 2015).",
    "slip_placeholder": "Smith v. State, ___ So. 3d ___ (Fla. 2023).",
    # --- trivial drafts ---
    "no_cites": "The plaintiff filed a motion on Tuesday.",
    "empty": "",
    "whitespace_only": "  \n\t  ",
}

_short_batch = None


def short_batch():
    global _short_batch
    if _short_batch is None:
        _short_batch = dh.Batch(SHORT_CASES)
    return _short_batch


class _TsCase(unittest.TestCase):
    maxDiff = None

    def batch(self):
        return short_batch()

    def res(self, name):
        return self.batch().results(name)

    def describe(self, name):
        return "%s\n  draft=%r\n  got=%s" % (name, self.batch().cases[name][:300], dh.compact(self.res(name)))

    def verdicts(self, name, expected):
        r = self.res(name)
        self.assertEqual(dh.contract_problems(r), [], "contract violation: " + self.describe(name))
        self.assertEqual([x["verdict"] for x in r], expected, self.describe(name))
        return r

    def shape(self, name, expected):
        r = self.res(name)
        self.assertEqual(dh.contract_problems(r), [], "contract violation: " + self.describe(name))
        self.assertEqual([(x["kind"], x["verdict"]) for x in r], expected, self.describe(name))
        return r


class ContractHoldsEverywhere(_TsCase):
    def test_every_result_of_every_scenario_honours_the_contract(self):
        for name in SHORT_CASES:
            with self.subTest(case=name):
                r = self.res(name)
                self.assertEqual(dh.contract_problems(r), [], self.describe(name))

    def test_no_pass_ever_without_a_matching_local_record(self):
        # A pass must carry the cluster of the Florida record the cite names. No scenario here cites
        # anything but SMITH/DAVIS/SMITH2/GARCIA/FLW as real Florida records.
        real = {fx.SMITH, dh.DAVIS, dh.SMITH2, fx.GARCIA, fx.FLW}
        for name in SHORT_CASES:
            with self.subTest(case=name):
                for x in self.res(name):
                    if x["verdict"] == "pass":
                        self.assertIn(x["clusterId"], real, self.describe(name))


class ShortFormsResolveToFloridaAntecedents(_TsCase):
    def test_short_cite_and_id_chain_pass_and_inherit_the_antecedent_record(self):
        r = self.shape("fl_chain", [("full", "pass"), ("short", "pass"), ("id", "pass"), ("id", "pass")])
        for x in r:
            self.assertEqual(x["clusterId"], fx.SMITH, self.describe("fl_chain"))
            self.assertIn("100 So. 3d 200", x["fullCitation"], self.describe("fl_chain"))

    def test_short_cite_pin_outside_the_record_is_vetoed_not_malformed(self):
        for name in ("fl_short_oob", "fl_short_below"):
            with self.subTest(case=name):
                r = self.shape(name, [("full", "pass"), ("short", "veto")])
                self.assertNotEqual(r[1]["reason"], "malformed", self.describe(name))
                self.assertNotEqual(r[1]["reason"], "unresolved_short_cite",
                                    "the antecedent resolved; the veto must come from the pin: " + self.describe(name))

    def test_short_cite_pin_ranges_and_footnotes(self):
        self.verdicts("fl_short_ranges", ["pass", "pass", "pass", "veto"])
        self.verdicts("fl_short_footnote", ["pass", "pass", "veto"])

    def test_id_chain_with_pins(self):
        self.shape("fl_id_chain", [("full", "pass"), ("id", "pass"), ("id", "pass"), ("id", "veto")])

    def test_lowercase_see_id_and_markdown_italics_are_not_dropped(self):
        self.verdicts("fl_id_lowercase_signal", ["pass", "veto"])
        self.verdicts("fl_markdown_italics", ["pass", "veto", "veto"])

    def test_supra_resolves_and_checks_the_pin(self):
        self.shape("fl_supra", [("full", "pass"), ("supra", "pass"), ("supra", "veto")])

    def test_short_pin_cannot_be_verified_when_the_record_has_no_page_bounds(self):
        self.verdicts("garcia_null_bounds", ["pass", "veto"])

    def test_florida_law_weekly_short_forms_are_not_dropped_or_waved_through(self):
        self.verdicts("weekly_chain", ["pass", "pass", "veto"])
        self.verdicts("weekly_orphan", ["veto"])
        r = self.res("weekly_unloaded_chain")
        self.assertEqual(dh.contract_problems(r), [], self.describe("weekly_unloaded_chain"))
        self.assertEqual([x["verdict"] for x in r], ["veto", "veto"], self.describe("weekly_unloaded_chain"))


class DependentFormsInheritVetoes(_TsCase):
    def test_id_short_and_supra_after_a_vetoed_cite_are_vetoed(self):
        for name in ("id_after_vetoed_full", "short_after_vetoed_full", "supra_after_vetoed_full"):
            with self.subTest(case=name):
                self.verdicts(name, ["veto", "veto"])

    def test_id_after_a_string_cite_is_never_routed_around_or_passed_on_a_foreign_record(self):
        r = self.res("id_after_string_cite")
        self.assertEqual(dh.contract_problems(r), [], self.describe("id_after_string_cite"))
        self.assertEqual([x["verdict"] for x in r[:2]], ["pass", "veto"], self.describe("id_after_string_cite"))
        self.assertEqual(len(r), 3, "the Id. was dropped: " + self.describe("id_after_string_cite"))
        last = r[2]
        self.assertIn(last["verdict"], ("veto", "pass"), self.describe("id_after_string_cite"))
        if last["verdict"] == "pass":
            self.assertEqual(last["clusterId"], fx.SMITH, self.describe("id_after_string_cite"))


class NonCaseAntecedent(_TsCase):
    def test_id_after_a_statute_is_fall_through_with_null_full_citation(self):
        r = self.shape("id_after_statute", [("full", "pass"), ("id", "fall_through")])
        self.assertEqual(r[1]["reason"], "non_case_antecedent", self.describe("id_after_statute"))
        self.assertIsNone(r[1]["fullCitation"], self.describe("id_after_statute"))

    def test_id_chain_after_a_statute_stays_non_case_and_never_reattaches_to_the_case(self):
        r = self.shape("id_chain_after_statute", [("full", "pass"), ("id", "fall_through"), ("id", "fall_through")])
        for x in r[1:]:
            self.assertEqual(x["reason"], "non_case_antecedent", self.describe("id_chain_after_statute"))


class UnresolvedShortForms(_TsCase):
    def test_id_before_any_antecedent_is_vetoed_even_if_a_full_cite_follows(self):
        r = self.shape("id_before_antecedent", [("id", "veto"), ("full", "pass")])
        self.assertEqual(r[0]["reason"], "unresolved_short_cite", self.describe("id_before_antecedent"))

    def test_orphan_short_cites_id_and_supra_are_vetoed_not_dropped_and_not_fall_through(self):
        for name in ("short_orphan", "short_orphan_bare", "short_orphan_federal", "supra_orphan", "id_orphan"):
            with self.subTest(case=name):
                r = self.verdicts(name, ["veto"])
                self.assertEqual(r[0]["reason"], "unresolved_short_cite", self.describe(name))

    def test_short_form_before_its_antecedent_is_unresolved_resolution_only_looks_backwards(self):
        for name in ("short_before_antecedent", "supra_before_antecedent"):
            with self.subTest(case=name):
                r = self.verdicts(name, ["veto", "pass"])
                self.assertEqual(r[0]["reason"], "unresolved_short_cite", self.describe(name))

    def test_unnamed_short_cite_with_a_signal_resolves_by_volume_and_its_pin_is_checked(self):
        # "See 100 So. 3d at 205" names no case; the signal word must not be read as a case name.
        r = self.verdicts("bare_short_after_florida", ["pass", "pass", "veto"])
        self.assertEqual(r[1]["clusterId"], fx.SMITH, self.describe("bare_short_after_florida"))
        self.assertNotEqual(r[2]["reason"], "caption_mismatch", self.describe("bare_short_after_florida"))

    def test_short_cite_in_another_series_or_volume_does_not_attach_to_the_florida_cite(self):
        for name in ("short_wrong_series", "short_wrong_volume"):
            with self.subTest(case=name):
                r = self.verdicts(name, ["pass", "veto"])
                self.assertEqual(r[1]["reason"], "unresolved_short_cite", self.describe(name))


class LaunderingAndAmbiguity(_TsCase):
    """A Florida cite must never reach fall_through (CourtListener) because it borrowed a non-Florida antecedent."""

    def test_short_cite_naming_a_different_case_than_its_antecedent_is_vetoed(self):
        # valid volume, valid page range, wrong caption: the hallucination pattern, in short form
        self.verdicts("short_name_mismatch", ["pass", "veto"])
        self.verdicts("supra_name_mismatch", ["pass", "veto"])

    def test_a_leading_signal_never_dodges_the_name_check(self):
        # Guard for signal stripping: "See Hernandez, 100 So. 3d at 205" after a Smith antecedent is still a
        # mismatch, whichever signal precedes it, and whatever the antecedent's jurisdiction.
        for name in ("signal_wrong_name", "signal_also_wrong_name", "signal_cf_wrong_name",
                     "signal_but_see_wrong_name"):
            with self.subTest(case=name):
                r = self.verdicts(name, ["pass", "veto"])
                self.assertNotEqual(r[1]["reason"], "unresolved_short_cite", self.describe(name))
        self.verdicts("signal_wrong_name_after_alabama", ["fall_through", "veto"])
        self.verdicts("signal_wrong_name_after_fed", ["fall_through", "veto"])

    def test_party_name_containment_is_whole_word_not_substring(self):
        for name in ("short_name_superstring", "short_name_substring", "short_name_prefix_of_word"):
            with self.subTest(case=name):
                self.verdicts(name, ["pass", "veto"])
        # either party may be used in a short cite; case differences are not a different case
        self.verdicts("short_name_defendant", ["pass", "pass"])
        r = self.res("short_name_case_variant")
        self.assertEqual(dh.contract_problems(r), [], self.describe("short_name_case_variant"))
        self.assertIn(r[1]["verdict"], ("pass", "veto"), self.describe("short_name_case_variant"))

    def test_a_leading_signal_with_the_right_name_is_not_over_vetoed(self):
        r = self.verdicts("signal_right_name", ["pass", "pass"])
        self.assertEqual(r[1]["clusterId"], fx.SMITH, self.describe("signal_right_name"))

    def test_florida_short_cite_cannot_launder_through_an_alabama_antecedent_in_the_same_volume(self):
        self.verdicts("launder_alabama_name", ["fall_through", "veto"])
        self.verdicts("launder_alabama_florida_paren", ["fall_through", "veto"])

    def test_florida_short_cite_with_no_antecedent_in_its_volume_is_unresolved(self):
        r = self.verdicts("launder_alabama_other_volume", ["fall_through", "veto"])
        self.assertEqual(r[1]["reason"], "unresolved_short_cite", self.describe("launder_alabama_other_volume"))

    def test_unnamed_short_cite_after_alabama_inherits_fall_through_with_the_antecedent_window(self):
        r = self.verdicts("short_inherits_alabama", ["fall_through", "fall_through"])
        self.assertIn("100 So. 3d 555", r[1]["fullCitation"], self.describe("short_inherits_alabama"))
        self.assertNotIn("100 So. 3d 200", r[1]["fullCitation"], self.describe("short_inherits_alabama"))

    def test_ambiguous_antecedents_are_vetoed(self):
        self.verdicts("ambiguous_fl_fl", ["pass", "pass", "veto"])
        self.verdicts("ambiguous_fl_ala", ["pass", "fall_through", "veto"])
        self.verdicts("same_name_collision", ["pass", "fall_through", "veto"])
        self.verdicts("supra_ambiguous", ["pass", "pass", "veto"])

    def test_two_cites_in_one_volume_never_let_a_short_cite_borrow_the_wrong_record(self):
        # A short cite naming Smith, with a Florida (Smith) and an Alabama (Jones) cite in the same volume. Vetoing
        # as ambiguous is acceptable (eyecite matches only the defendant name, so a plaintiff-named short cite is
        # ambiguous); passing on the Smith record is acceptable; fall_through, or a pin outside Smith's pages that is
        # not vetoed, is not.
        name = "disambiguated_by_name"
        r = self.res(name)
        self.assertEqual(dh.contract_problems(r), [], self.describe(name))
        self.assertEqual([x["verdict"] for x in r[:2]], ["pass", "fall_through"], self.describe(name))
        self.assertEqual(len(r), 4, self.describe(name))
        self.assertIn(r[2]["verdict"], ("pass", "veto"), self.describe(name))
        if r[2]["verdict"] == "pass":
            self.assertEqual(r[2]["clusterId"], fx.SMITH, self.describe(name))
        # 556 is inside the Alabama case's pages but outside Smith's 200-215
        self.assertEqual(r[3]["verdict"], "veto", self.describe(name))


class MixedJurisdictionDrafts(_TsCase):
    def test_florida_alabama_and_federal_citations_each_get_their_own_verdict(self):
        self.shape("mixed", [("full", "pass"), ("full", "fall_through"), ("full", "fall_through"),
                             ("short", "pass"), ("short", "fall_through"), ("short", "fall_through"),
                             ("id", "fall_through")])

    def test_short_forms_of_non_florida_cites_carry_the_antecedent_window(self):
        r = self.res("mixed")
        self.assertIn("175 So. 3d 700", r[4]["fullCitation"], self.describe("mixed"))
        self.assertIn("600 F.3d 100", r[5]["fullCitation"], self.describe("mixed"))
        self.assertIn("600 F.3d 100", r[6]["fullCitation"], self.describe("mixed"))

    def test_fabricated_florida_cite_and_its_short_form_are_vetoed_beside_a_valid_alabama_pair(self):
        self.verdicts("mixed_fabricated", ["veto", "fall_through", "veto", "fall_through"])

    def test_federal_chain_falls_through_throughout(self):
        r = self.verdicts("federal_chain", ["fall_through", "fall_through", "fall_through"])
        self.assertIn("600 F.3d 100", r[2]["fullCitation"], self.describe("federal_chain"))


class NothingFloridaIsDropped(_TsCase):
    def test_scan_misses_are_vetoed_when_florida_ish_never_silent(self):
        for name in ("unparsed_five_digit_volume", "unparsed_seven_digit_page", "unparsed_trailing_letter_page",
                     "slip_placeholder"):
            with self.subTest(case=name):
                r = self.res(name)
                self.assertTrue(r, "SILENTLY DROPPED: " + self.describe(name))
                self.assertEqual(dh.contract_problems(r), [], self.describe(name))
                self.assertTrue(all(x["verdict"] == "veto" for x in r), self.describe(name))

    def test_drafts_without_citations_have_no_results(self):
        r = self.res("no_cites")
        self.assertEqual(r, [], self.describe("no_cites"))

    def test_empty_and_whitespace_only_drafts_have_no_results(self):
        # Ruling: no citations means [], not a veto (the builder is fixing the internal_error veto).
        for name in ("empty", "whitespace_only"):
            with self.subTest(case=name):
                self.assertEqual(self.res(name), [], self.describe(name))


# Offsets: start/end are code-point offsets into the normalized (NFKC-folded, format-stripped) draft.
OFFSET_CASES = {
    "ascii": "The rule. " + S + ". Smith, 100 So. 3d at 460.",
    "astral_prefix": "\U0001F600 " + S + ". Smith, 100 So. 3d at 460.",
    "ligature_prefix": "The ﬁnal rule. " + S + ". Smith, 100 So. 3d at 460.",
    "zero_width_prefix": "The rule.​ " + S + ". Smith, 100 So. 3d at 460.",
    "fullwidth_digits_prefix": "Count １２３ filings. " + S + ". Smith, 100 So. 3d at 460.",
}


class OffsetsIndexTheNormalizedDraft(unittest.TestCase):
    """Ruling: start/end index the NORMALIZED draft in code points (documented on Gate1TextResult.text), and the
    caller never slices the original draft by them. So each result must satisfy text == normalized[start:end],
    and, whatever shifts the offsets (astral character, NFKC expansion, stripped zero-width character), no citation
    may be dropped and none may pass that should not: the Florida cite passes, its out-of-range short cite is vetoed."""

    @classmethod
    def setUpClass(cls):
        cls.batch = dh.Batch(OFFSET_CASES)

    def _check(self, name):
        draft = OFFSET_CASES[name]
        r = self.batch.results(name)
        self.assertEqual(dh.contract_problems(r), [], dh.compact(r))
        self.assertEqual([(x["kind"], x["verdict"]) for x in r], [("full", "pass"), ("short", "veto")],
                         "a citation was dropped or mis-judged after an offset shift: " + dh.compact(r))
        norm = dh.normalized(draft)
        for x in r:
            self.assertEqual(norm[x["start"]:x["end"]], x["text"],
                             "text != normalized[%d:%d] (=%r, text=%r)"
                             % (x["start"], x["end"], norm[x["start"]:x["end"]], x["text"]))

    def test_ascii(self):
        self._check("ascii")

    def test_astral_characters_before_the_cite(self):
        self._check("astral_prefix")

    def test_nfkc_expansion_before_the_cite(self):
        self._check("ligature_prefix")

    def test_stripped_format_characters_before_the_cite(self):
        self._check("zero_width_prefix")

    def test_nfkc_width_folding_before_the_cite(self):
        self._check("fullwidth_digits_prefix")


# Hiding attacks again, now through the real wrapper (representative subset; the full set runs in-process).
TS_HIDING = ("md_escaped_period", "md_escaped_period_and_paren", "html_nbsp_entity", "html_tag_between_tokens",
             "italic_reporter", "nul_in_reporter", "unit_separator_as_space", "five_digit_volume",
             "seven_digit_page", "slip_opinion_blank_volume_and_page", "missing_space_before_reporter", "all_caps",
             "florida_court_wrong_spelling_dca")
TS_DRAFT_VARIANTS = {}
TS_DRAFT_VARIANTS.update({"hide_" + n: wrap(FAB_HIDING[n]) for n in TS_HIDING})
TS_DRAFT_VARIANTS.update({"glyph_" + n: wrap(c) for n, c in FAB_HOMOGLYPHS.items()})
TS_DRAFT_VARIANTS.update({
    "caption_" + n: "See " + CAPTION_DRESSINGS[n].format(c=WRONG_CAPTION) + "." for n in ("italic_star", "parenthesized", "html_em")})
TS_DRAFT_VARIANTS["caption_et_al"] = "See " + ET_AL_VARIANTS["et_al"] + "."
TS_DRAFT_VARIANTS["valid_variants_combined"] = "\n\n".join(
    "The Court held as much in %s." % c for c in VALID_VARIANTS.values())


class UnicodeAndHidingThroughTheWrapper(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.batch = dh.Batch(TS_DRAFT_VARIANTS)

    def test_fabricated_florida_cites_are_vetoed_through_the_wrapper(self):
        for name in TS_DRAFT_VARIANTS:
            if name == "valid_variants_combined":
                continue
            with self.subTest(variant=name):
                r = self.batch.results(name)
                self.assertEqual(dh.contract_problems(r), [], dh.compact(r))
                verdicts = [x["verdict"] for x in r]
                self.assertTrue(r, "SILENTLY DROPPED: %r" % TS_DRAFT_VARIANTS[name])
                self.assertIn("veto", verdicts, dh.compact(r))
                self.assertNotIn("pass", verdicts, dh.compact(r))
                self.assertNotIn("fall_through", verdicts, dh.compact(r))

    def test_damaged_variants_of_a_real_cite_never_fall_through_or_pass_another_record(self):
        r = self.batch.results("valid_variants_combined")
        self.assertEqual(dh.contract_problems(r), [], dh.compact(r))
        self.assertGreaterEqual(len(r), len(VALID_VARIANTS), "a variant was dropped: " + dh.compact(r))
        for x in r:
            if x["verdict"] == "pass":
                self.assertEqual(x["clusterId"], fx.SMITH, dh.compact(r))
            else:
                self.assertEqual(x["verdict"], "veto", dh.compact(r))


# ───── C. the wrapper's own failure modes ─────

CLEAN_DRAFT = S + ". " + FAB + "."


def _signature(results):
    return [(x.get("kind"), x.get("verdict"), x.get("reason"), x.get("start"), x.get("end")) for x in results]


class WrapperFailsClosed(unittest.TestCase):
    """The Python child is sabotaged from outside (PYTHONPATH sitecustomize). Whatever it does, the wrapper
    must return exactly one veto result: never [], never a throw, never a pass."""
    maxDiff = None

    STRICT = {
        "exit_nonzero": "os._exit(3)",
        "exit_zero_empty_stdout": "os._exit(0)",
        "payload_not_json": 'sys.stdout.write("not json at all"); sys.stdout.flush(); os._exit(0)',
        "payload_truncated_json": 'sys.stdout.write(\'[{"verdict":"pass","reason":"verif\'); sys.stdout.flush(); os._exit(0)',
        "payload_object_not_array": 'sys.stdout.write(\'{"verdict":"pass","reason":"verified"}\'); sys.stdout.flush(); os._exit(0)',
        "payload_null": 'sys.stdout.write("null"); sys.stdout.flush(); os._exit(0)',
        "payload_bare_string": 'sys.stdout.write(\'"pass"\'); sys.stdout.flush(); os._exit(0)',
        "payload_array_of_numbers": 'sys.stdout.write("[1,2]"); sys.stdout.flush(); os._exit(0)',
        "payload_pass_missing_every_field": 'sys.stdout.write(\'[{"verdict":"pass"}]\'); sys.stdout.flush(); os._exit(0)',
        "payload_unknown_verdict": ('sys.stdout.write(\'[{"verdict":"maybe","reason":"x","kind":"full","text":"x",'
                                    '"fullCitation":null,"start":0,"end":1}]\'); sys.stdout.flush(); os._exit(0)'),
        "huge_stdout": 'sys.stdout.write("A" * 5000000); sys.stdout.flush(); os._exit(0)',
        # SIGKILL, not SIGSEGV: a segfault pops the macOS crash-reporter dialog on every run.
        "killed_by_signal": "import signal\nos.kill(os.getpid(), signal.SIGKILL)",
    }

    HANG = ('open(os.environ["KF_ADV_PIDFILE"], "w").write(str(os.getpid()))\n'
            "import time\ntime.sleep(600)")
    HANG_IGNORING_SIGTERM = ('open(os.environ["KF_ADV_PIDFILE"], "w").write(str(os.getpid()))\n'
                             "import signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\ntime.sleep(600)")

    TOLERANT = {
        # The child still produces the right answer; noise around it must not change a verdict or crash the wrapper.
        "banner_on_stdout_then_normal": 'print("WARNING: spoofed banner")',
        "stderr_flood_then_normal": 'sys.stderr.write("E" * 5000000)',
    }

    @classmethod
    def setUpClass(cls):
        cls.baseline = dh.Batch({"clean": CLEAN_DRAFT}).results("clean")

    def _run(self, code, opts_extra=None):
        env, marker = dh.make_sabotage(code)
        b = dh.Batch({"d": CLEAN_DRAFT}, env_extra=env, timeout=240, opts_extra=opts_extra)
        if not marker.exists():
            self.skipTest("the wrapper does not forward PYTHONPATH to its child (or starts python isolated); "
                          "this sabotage is not applicable")
        self.assertEqual(b.unhandled, [], "unhandled rejection/exception: %r" % (b.unhandled,))
        return b.results("d"), b.ms("d")

    def _run_with_pid(self, code, opts_extra, harness_timeout):
        """Run a hanging child; return (results, ms, pid). Always kills the child afterwards."""
        env, marker = dh.make_sabotage(code)
        pidfile = Path(env["KF_ADV_PIDFILE"])
        pid = None
        try:
            b = dh.Batch({"d": CLEAN_DRAFT}, env_extra=env, timeout=harness_timeout, opts_extra=opts_extra)
            if pidfile.exists():
                pid = int(pidfile.read_text())
            if not marker.exists():
                self.skipTest("the wrapper does not forward PYTHONPATH to its child; sabotage not applicable")
            self.assertEqual(b.unhandled, [], "unhandled rejection/exception: %r" % (b.unhandled,))
            return b.results("d"), b.ms("d"), pid
        finally:
            if pid is None and pidfile.exists():
                pid = int(pidfile.read_text())
            if pid is not None and self._alive(pid):
                self._reap(pid)

    @staticmethod
    def _alive(pid):
        import os
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    @staticmethod
    def _reap(pid):
        import os
        import signal
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def _assert_child_dead_soon(self, pid, why):
        import time
        self.assertIsNotNone(pid, "the sabotaged child never recorded its pid")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if not self._alive(pid):
                return
            time.sleep(0.1)
        self.fail("%s: child process %d is still running after the wrapper returned (orphaned)" % (why, pid))

    def test_a_child_that_hangs_is_killed_at_the_timeout_and_vetoed(self):
        # textTimeoutMs shortens the wrapper's own timeout; the mechanism under test is the same.
        r, ms, pid = self._run_with_pid(self.HANG, {"textTimeoutMs": 3000}, 90)
        self.assertEqual(dh.contract_problems(r), [], dh.compact(r))
        self.assertEqual(len(r), 1, "expected exactly one veto, got " + dh.compact(r))
        self.assertEqual(r[0]["verdict"], "veto", dh.compact(r))
        self.assertLess(ms, 15000, "a 3s timeout took %d ms to fire" % ms)
        self._assert_child_dead_soon(pid, "timeout")

    # test_a_child_that_ignores_sigterm_is_still_killed_and_the_promise_still_settles: moved to
    # pipeline/tests_extended/test_extended_variants.py (tier split; the plain hang above stays).

    def test_baseline_is_sane(self):
        self.assertEqual(dh.contract_problems(self.baseline), [], dh.compact(self.baseline))
        self.assertEqual([x["verdict"] for x in self.baseline], ["pass", "veto"], dh.compact(self.baseline))

    def test_every_child_failure_yields_exactly_one_veto(self):
        for name, code in self.STRICT.items():
            with self.subTest(failure=name):
                r, _ms = self._run(code)
                self.assertEqual(dh.contract_problems(r), [], "%s: %s" % (name, dh.compact(r)))
                self.assertEqual(len(r), 1, "%s: expected exactly one veto, got %s" % (name, dh.compact(r)))
                self.assertEqual(r[0]["verdict"], "veto", "%s: %s" % (name, dh.compact(r)))

    def test_noise_around_a_correct_answer_never_changes_a_verdict(self):
        for name, code in self.TOLERANT.items():
            with self.subTest(noise=name):
                r, _ms = self._run(code)
                clean = _signature(self.baseline)
                one_veto = len(r) == 1 and r[0].get("verdict") == "veto"
                self.assertTrue(_signature(r) == clean or one_veto,
                                "%s changed the outcome: %s" % (name, dh.compact(r)))

    def test_missing_interpreter_yields_exactly_one_veto(self):
        # The wrapper locates ~/.venv-cascade/bin/python through the home directory.
        b = dh.Batch({"d": CLEAN_DRAFT}, env_extra={"HOME": "/nonexistent-kf-adv-home"}, timeout=120)
        r = b.results("d")
        self.assertEqual(dh.contract_problems(r), [], dh.compact(r))
        self.assertEqual(len(r), 1, "expected exactly one veto, got " + dh.compact(r))
        self.assertEqual(r[0]["verdict"], "veto", dh.compact(r))

    def test_missing_database_vetoes_every_florida_cite_and_never_passes(self):
        missing = fx.new_tempdir("kf_adv_nodb_") / "none.db"
        b = dh.Batch({"d": "; ".join([S, ALA, FED, FAB]) + ". Smith, 100 So. 3d at 205."}, db=missing)
        r = b.results("d")
        self.assertEqual(dh.contract_problems(r), [], dh.compact(r))
        self.assertTrue(r, "no result at all with the database missing")
        self.assertNotIn("pass", [x["verdict"] for x in r], dh.compact(r))
        if len(r) > 1:
            by = [x["verdict"] for x in r]
            self.assertEqual(by[0], "veto", "Florida cite not vetoed with the database missing: " + dh.compact(r))
            self.assertEqual(by[3], "veto", dh.compact(r))
            self.assertEqual(by[4], "veto", "Florida short cite not vetoed with the database missing: " + dh.compact(r))


# ───── C1. the async contract: Promise<Gate1TextResult[]>, never rejects ─────

class AsyncContract(unittest.TestCase):
    """A rejected or unhandled promise would let a `try { r = await localGate1Text(d) } catch {}` style caller
    fall through with no veto in hand. The contract is that the promise ALWAYS resolves, with exactly one veto on
    any failure, so a caller that only ever reads the resolved value cannot proceed without a verdict."""
    maxDiff = None
    NON_STRING = {"null": None, "number": 42, "object": {"a": 1}, "array": ["x"], "bool": True, "nested": [[]]}

    @classmethod
    def setUpClass(cls):
        cases = {"resolves_pass": S + ".", "resolves_veto": FAB + ".", "resolves_empty": "No citations here."}
        cases.update({"nonstring_" + k: v for k, v in cls.NON_STRING.items()})
        cls.batch = dh.Batch(cases)
        # Three real children at once (one per verdict kind) check real verdicts under concurrency; the cross-talk
        # property at cap+2 calls is proved with cheap stub children in test_concurrent_calls_do_not_cross_talk.
        cls.concurrent_cases = {"c0_pass": S + ".", "c1_veto": "Doe v. Roe, 900 So. 3d 1000 (Fla. 2015).",
                                "c2_fed": FED + "."}
        cls.concurrent = dh.Batch(cls.concurrent_cases, concurrent=True)

    def test_returns_a_promise(self):
        for name in self.batch.cases:
            with self.subTest(case=name):
                self.assertTrue(self.batch.loop(name)["isPromise"],
                                "localGate1Text did not return a Promise for %s (it is still synchronous)" % name)

    def test_never_rejects_and_leaves_no_unhandled_rejection(self):
        for name in self.batch.cases:
            with self.subTest(case=name):
                status, payload = self.batch.raw[name][:2]
                self.assertEqual(status, "ok", "the promise rejected or threw for %s: %s" % (name, payload))
        self.assertEqual(self.batch.unhandled, [], "unhandled rejection or uncaught exception in the host process")

    def test_non_string_drafts_resolve_to_exactly_one_veto(self):
        for k in self.NON_STRING:
            name = "nonstring_" + k
            with self.subTest(case=name):
                r = self.batch.results(name)
                self.assertEqual(dh.contract_problems(r), [], dh.compact(r))
                self.assertEqual(len(r), 1, dh.compact(r))
                self.assertEqual(r[0]["verdict"], "veto", dh.compact(r))

    def test_resolved_values_are_the_contract_results(self):
        self.assertEqual([x["verdict"] for x in self.batch.results("resolves_pass")], ["pass"])
        self.assertEqual([x["verdict"] for x in self.batch.results("resolves_veto")], ["veto"])
        self.assertEqual(self.batch.results("resolves_empty"), [])

    def test_concurrent_calls_do_not_cross_talk(self):
        # Real children: three calls in flight at once, each must resolve with its own draft's verdict.
        self.assertEqual(self.concurrent.unhandled, [], "unhandled rejection or uncaught exception")
        want = {"pass": ["pass"], "veto": ["veto"], "fed": ["fall_through"]}
        for name in self.concurrent_cases:
            with self.subTest(case=name):
                r = self.concurrent.results(name)
                self.assertEqual(dh.contract_problems(r), [], dh.compact(r))
                self.assertEqual([x["verdict"] for x in r], want[name.split("_")[1]], "%s: %s" % (name, dh.compact(r)))

    def test_concurrent_stub_calls_beyond_the_cap_do_not_cross_talk(self):
        # cap+2 calls, cheap stub children that echo their own draft: each promise must carry ITS draft's verdict and
        # text, including the two calls that had to queue. No eyecite is imported, so this costs a few processes' startup.
        n = MAX_CHILDREN + 2
        kinds = [("P", "pass"), ("V", "veto"), ("F", "fall_through")]
        cases, want = {}, {}
        for i in range(n):
            k, verdict = kinds[i % 3]
            name = "s%02d_%s" % (i, verdict)
            cases[name] = dh.stub_draft(k, i)
            want[name] = verdict
        env, marker, _live, _rel, _peak = dh.stub_env(dh.stub_code(hold=0.2))
        b = dh.Batch(cases, env_extra=env, concurrent=True)
        if not marker.exists():
            self.skipTest("the wrapper does not forward PYTHONPATH to its child; sabotage not applicable")
        self.assertEqual(b.unhandled, [], "unhandled rejection or uncaught exception")
        for name, draft in cases.items():
            with self.subTest(case=name):
                r = b.results(name)
                self.assertEqual(dh.contract_problems(r), [], dh.compact(r))
                self.assertEqual([x["verdict"] for x in r], [want[name]], "%s: %s" % (name, dh.compact(r)))
                self.assertEqual(r[0]["text"], draft, "result belongs to another call: " + dh.compact(r))

    def test_every_sabotaged_failure_resolves_and_never_rejects(self):
        # WrapperFailsClosed runs each sabotage through the same awaited path and asserts one veto and no unhandled
        # rejection; this pins that the rejection channel itself stays empty for a failure the wrapper cannot parse.
        env, marker = dh.make_sabotage("os._exit(3)")
        b = dh.Batch({"d": CLEAN_DRAFT}, env_extra=env, timeout=120)
        if not marker.exists():
            self.skipTest("the wrapper does not forward PYTHONPATH to its child; sabotage not applicable")
        status, payload = b.raw["d"][:2]
        self.assertEqual(status, "ok", "promise rejected on a child failure: %s" % (payload,))
        self.assertEqual(b.unhandled, [])
        self.assertEqual([x["verdict"] for x in payload], ["veto"])


# ───── C1b. bounded concurrency: a semaphore around the Python children ─────

MAX_CHILDREN = 4          # the agreed cap ("about 4"); the test asserts the observed peak never exceeds it

# Runs inside every Python child: register as alive, count the live registered children (a child counts only if
# its pid answers signal 0), log that count, hold the slot for HOLD seconds, deregister. The largest logged
# count is the true peak, because the peak is reached right after some child registers.
_LIVE_CODE = """
d = os.environ["KF_ADV_LIVEDIR"]
os.makedirs(d, exist_ok=True)
open(os.path.join(d, str(os.getpid())), "w").close()
def _alive(p):
    try:
        os.kill(p, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
n = sum(1 for f in os.listdir(d) if f.isdigit() and _alive(int(f)))
open(os.environ["KF_ADV_PEAKLOG"], "a").write("%d\\n" % n)
import time
time.sleep(HOLD_SECONDS)
try:
    os.remove(os.path.join(d, str(os.getpid())))
except OSError:
    pass
"""


def _alive_pid(pid):
    import os
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class ConcurrencyCap(unittest.TestCase):
    """cap+2 simultaneous calls (the smallest count that queues) must never have more than MAX_CHILDREN Python
    interpreters alive at once, with the cap reached exactly; calls that
    wait for a slot still get their own correct verdict; every call settles within a bounded time as exactly one
    result (a veto when the wait bound or the child timeout is hit); nothing rejects; no child is left behind."""
    maxDiff = None

    @staticmethod
    def _env(hold_seconds):
        env, marker = dh.make_sabotage(_LIVE_CODE.replace("HOLD_SECONDS", repr(hold_seconds)))
        tmp = Path(env["KF_ADV_MARKER"]).parent
        env["KF_ADV_LIVEDIR"] = str(tmp / "live")
        env["KF_ADV_PEAKLOG"] = str(tmp / "peak.log")
        return env, marker, tmp / "live", tmp / "peak.log"

    @staticmethod
    def _peak(peaklog):
        if not peaklog.exists():
            return 0
        return max([int(x) for x in peaklog.read_text().split() if x.isdigit()] or [0])

    N_CALLS = MAX_CHILDREN + 2    # the smallest count that still queues: cap children run, two calls wait

    def _drafts(self, n):
        """n stub drafts (verdict letter + unique text) and the verdict each must resolve to."""
        cases, want = {}, {}
        for i in range(n):
            k, verdict = (("P", "pass"), ("V", "veto"), ("F", "fall_through"))[i % 3]
            name = "c%02d_%s" % (i, verdict)
            cases[name] = dh.stub_draft(k, i)
            want[name] = [verdict]
        return cases, want

    @staticmethod
    def _wait_for(cond, what, timeout=20.0):
        """Wait for a state the test itself drives; the bound only turns a hang into a failure."""
        import time
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if cond():
                return
            time.sleep(0.02)
        raise AssertionError("timed out waiting for: " + what)

    @staticmethod
    def _registered(peaklog):
        return len(peaklog.read_text().split()) if peaklog.exists() else 0

    @staticmethod
    def _live_pids(live):
        if not live.exists():
            return []
        return sorted(int(p.name) for p in live.iterdir() if p.name.isdigit() and _alive_pid(int(p.name)))

    @staticmethod
    def _release(rel, pid):
        (rel / str(pid)).write_text("go")

    def _cleanup(self, lb, live, rel):
        """Let every stub still waiting finish, stop node if it is still running, and kill any straggler."""
        import os
        import signal
        for pid in self._live_pids(live):
            self._release(rel, pid)
        if lb.proc.poll() is None:
            lb.kill()
        for pid in self._live_pids(live):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def test_never_more_than_the_cap_of_children_alive_and_queued_calls_get_correct_verdicts(self):
        # Deterministic: every stub child blocks until THIS TEST creates a file named after its pid, so the live set is
        # observed at known points instead of being raced against timers.
        #   point 1  cap+2 calls issued: exactly `cap` children registered, the other two have not been spawned
        #   point 2  one child released: exactly one queued call spawns, live stays at cap
        #   point 3  a second released: the last queued call spawns, live stays at cap
        #   point 4  everything released: all calls resolve with their own verdict, none shed
        import time
        cases, want = self._drafts(self.N_CALLS)
        env, marker, live, rel, peaklog = dh.stub_env(dh.stub_code(gated=True))
        lb = dh.LiveBatch(cases, env_extra=env)
        b = None
        try:
            try:
                self._wait_for(lambda: self._registered(peaklog) >= MAX_CHILDREN, "the first %d children" % MAX_CHILDREN)
            except AssertionError:
                if not marker.exists():
                    self.skipTest("the wrapper does not forward PYTHONPATH to its child; sabotage not applicable")
                raise
            time.sleep(0.5)   # absence window: a (buggy) fifth child would have registered by now
            self.assertEqual(self._registered(peaklog), MAX_CHILDREN, "more than the cap of children were spawned")
            self.assertEqual(len(self._live_pids(live)), MAX_CHILDREN)
            for step in (1, 2):
                self._release(rel, self._live_pids(live)[0])
                self._wait_for(lambda: self._registered(peaklog) >= MAX_CHILDREN + step,
                               "a queued call to spawn after release %d" % step)
                time.sleep(0.2)
                self.assertEqual(self._registered(peaklog), MAX_CHILDREN + step,
                                 "release %d freed one slot but a different number of calls spawned" % step)
                self.assertEqual(len(self._live_pids(live)), MAX_CHILDREN,
                                 "live children after release %d is not exactly the cap" % step)
            for pid in self._live_pids(live):
                self._release(rel, pid)
            b = lb.finish(timeout=60)
        finally:
            self._cleanup(lb, live, rel)
        self.assertEqual(b.unhandled, [], "unhandled rejection or uncaught exception: %r" % (b.unhandled,))
        peak = max(int(x) for x in peaklog.read_text().split())
        self.assertEqual(peak, MAX_CHILDREN, "peak live children was %d (cap %d, and the cap must be reached)"
                         % (peak, MAX_CHILDREN))
        self.assertEqual(self._registered(peaklog), self.N_CALLS)
        for name in cases:
            with self.subTest(case=name):
                status, payload = b.raw[name][:2]
                self.assertEqual(status, "ok", "the promise rejected for %s: %s" % (name, payload))
                self.assertEqual(dh.contract_problems(payload), [], dh.compact(payload))
                self.assertEqual([x["verdict"] for x in payload], want[name],
                                 "queued call got the wrong verdict (%s): %s" % (name, dh.compact(payload)))
                self.assertEqual(payload[0]["text"], cases[name], "result belongs to another call: " + name)
                self.assertNotIn("gate_busy", [x["reason"] for x in payload], "a call was shed while queued: " + name)

    # test_when_every_child_hangs_every_call_still_settles_as_exactly_one_veto_within_a_bound and
    # test_the_cap_is_exact_while_children_are_being_killed_by_the_timeout: moved to
    # pipeline/tests_extended/test_extended_variants.py (tier split; the cap, the queue bound, the flood and the plain
    # hang-and-kill in WrapperFailsClosed stay).

    def test_the_queue_wait_bound_sheds_waiting_calls_as_one_gate_busy_veto_and_spawns_nothing_for_them(self):
        # The cap slots are held by stub children that block on release files (no kill timer involved). The two calls
        # beyond the cap queue behind them with a SMALL textQueueWaitMs and must each be shed as exactly one gate_busy
        # veto within textQueueWaitMs plus a fixed margin measured from the call being issued, WITHOUT spawning a child.
        # Then the held children are released and must each give their own verdict.
        import time
        wait_ms, margin_ms = 400, 500
        cases, want = self._drafts(self.N_CALLS)
        env, marker, live, rel, peaklog = dh.stub_env(dh.stub_code(gated=True))
        lb = dh.LiveBatch(cases, env_extra=env, opts_extra={"textQueueWaitMs": wait_ms})
        b = None
        try:
            try:
                self._wait_for(lambda: self._registered(peaklog) >= MAX_CHILDREN, "the first %d children" % MAX_CHILDREN)
            except AssertionError:
                if not marker.exists():
                    self.skipTest("the wrapper does not forward PYTHONPATH to its child; sabotage not applicable")
                raise
            time.sleep((wait_ms + margin_ms + 300) / 1000.0)   # the two queued calls have been shed by now
            self.assertEqual(self._registered(peaklog), MAX_CHILDREN, "a shed call spawned a child")
            self.assertEqual(len(self._live_pids(live)), MAX_CHILDREN)
            for pid in self._live_pids(live):
                self._release(rel, pid)
            b = lb.finish(timeout=60)
        finally:
            self._cleanup(lb, live, rel)
        self.assertEqual(b.unhandled, [], "unhandled rejection or uncaught exception: %r" % (b.unhandled,))
        shed, ran = [], []
        for name in cases:
            status, payload = b.raw[name][:2]
            self.assertEqual(status, "ok", "the promise rejected for %s: %s" % (name, payload))
            self.assertEqual(dh.contract_problems(payload), [], dh.compact(payload))
            (shed if payload and payload[0]["reason"] == "gate_busy" else ran).append(name)
        self.assertEqual(len(shed), self.N_CALLS - MAX_CHILDREN, "shed: %r ran: %r" % (shed, ran))
        for name in shed:
            payload = b.raw[name][1]
            self.assertEqual(len(payload), 1, "expected exactly one veto: " + dh.compact(payload))
            self.assertEqual(payload[0]["verdict"], "veto", dh.compact(payload))
            self.assertGreaterEqual(b.ms(name), wait_ms - 10, "%s was shed before the wait bound (%d ms)" % (name, b.ms(name)))
            self.assertLessEqual(b.ms(name), wait_ms + margin_ms,
                                 "%s waited %d ms for a %d ms wait bound" % (name, b.ms(name), wait_ms))
        for name in ran:
            payload = b.raw[name][1]
            self.assertEqual([x["verdict"] for x in payload], want[name], "%s: %s" % (name, dh.compact(payload)))
            self.assertEqual(payload[0]["text"], cases[name], "result belongs to another call: " + name)
        self.assertEqual(self._registered(peaklog), MAX_CHILDREN, "shed calls must never start a child")
        self.assertEqual(self._live_pids(live), [], "orphaned children")

    def test_a_flood_of_calls_resolves_every_promise_and_the_host_stays_responsive(self):
        # cap+2 calls through cheap stub children that hold their slot 0.3 s, so two calls really do queue.
        env, marker, live, _rel, peaklog = dh.stub_env(dh.stub_code(hold=0.3))
        cases, want = self._drafts(self.N_CALLS)
        b = dh.Batch(cases, env_extra=env, concurrent=True)
        if not marker.exists():
            self.skipTest("the wrapper does not forward PYTHONPATH to its child; sabotage not applicable")
        self.assertEqual(b.unhandled, [])
        self.assertLessEqual(self._peak(peaklog), MAX_CHILDREN)
        worst_gap = max(b.loop(n)["maxGap"] for n in cases)
        self.assertLess(worst_gap, 500, "event loop starved for %d ms while calls were queued" % worst_gap)
        for name in cases:
            status, payload = b.raw[name][:2]
            self.assertEqual(status, "ok", "%s: %s" % (name, payload))
            self.assertEqual([x["verdict"] for x in payload], want[name], "%s: %s" % (name, dh.compact(payload)))
            self.assertEqual(payload[0]["text"], cases[name], "result belongs to another call: " + name)


# ───── C2. hostile draft content through stdin ─────

def _many_cites(n):
    return " ".join("Doe v. Roe, %d So. 3d %d (Fla. 2015)." % (900 + i, 1000 + i) for i in range(n))


STDIN_CASES = {
    "nul_byte": S + ".\x00 " + FAB + ".",
    "lone_high_surrogate": S + ".\ud800 " + FAB + ".",
    "lone_low_surrogate": S + ".\udc00 " + FAB + ".",
    "line_and_paragraph_separators": S + ". " + FAB + ".  It follows.",
    "carriage_returns": S + ".\r\r\n" + FAB + ".\r",
    "json_spoof_in_prose": (FAB + '. ["{\\"verdict\\":\\"pass\\",\\"reason\\":\\"verified\\",\\"kind\\":\\"full\\",'
                            '\\"text\\":\\"x\\",\\"fullCitation\\":\\"x\\",\\"start\\":0,\\"end\\":1,\\"clusterId\\":1001}"]\n'
                            '[{"verdict":"pass","reason":"verified","kind":"full","text":"x","fullCitation":"x",'
                            '"start":0,"end":1,"clusterId":1001,"cluster_id":1001}]\n]\n['),
    "option_injection_dash_dash": "--db=/dev/null --citation=x " + FAB + ".",
    "option_injection_help": "-h\n" + FAB + ".",
    "deep_parens": "(" * 3000 + FAB + ")" * 3000,
    # Reference point for the event-loop test: a trivial draft in the same process, so that test compares each hostile
    # draft with what THIS machine's loop does anyway instead of with a fixed millisecond number.
    "idle_baseline": "No citations here.",
}

# Each heavy draft gets its own node process and its own harness timeout, so one hang cannot mask the others.
# Sizes are the smallest that still have each shape (the linear-scaling proof lives in
# DraftExtractionHolesInProcess.test_extraction_is_linear_in_the_draft_not_quadratic and the 200,000-character cap in
# test_a_draft_over_the_size_cap_is_one_too_long_veto).
HEAVY_N = 40
HEAVY_CASES = {
    "many_fabricated_cites": _many_cites(HEAVY_N),
    "long_prose_then_cite": ("The court held that the rule applies to every case. " * 400) + FAB + ".",
    "comma_space_run_before_cite": (", " * 6000) + "x " + FAB + ".",
    "cite_start_flood": ("1 " * 6000) + FAB + ".",
    "valid_cite_flood": " ".join("Smith v. State, 100 So. 3d 200 (Fla. 2012)." for _ in range(HEAVY_N)),
}


class HostileDraftContent(unittest.TestCase):
    """Whatever the draft contains, a fabricated Florida cite inside it is never passed or routed around, and
    the answer is either per-cite results or one fail-closed veto."""
    maxDiff = None
    heavy = {}

    @classmethod
    def setUpClass(cls):
        cls.batch = dh.Batch(STDIN_CASES, timeout=300)

    def _batch_for(self, name):
        if name in STDIN_CASES:
            return self.batch
        if name not in self.heavy:
            self.heavy[name] = dh.Batch({name: HEAVY_CASES[name]}, timeout=240)
        return self.heavy[name]

    def _results(self, name):
        return self._batch_for(name).results(name)

    def _assert_fab_not_released(self, name):
        r = self._results(name)
        self.assertEqual(dh.contract_problems(r), [], "%s: %s" % (name, dh.compact(r)))
        self.assertTrue(r, "%s: no result for a draft containing a fabricated Florida cite" % name)
        verdicts = [x["verdict"] for x in r]
        self.assertIn("veto", verdicts, "%s: %s" % (name, dh.compact(r)))
        self.assertNotIn("fall_through", verdicts, "%s: %s" % (name, dh.compact(r)))
        return r

    def test_control_characters_and_separators(self):
        for name in ("nul_byte", "lone_high_surrogate", "lone_low_surrogate", "line_and_paragraph_separators",
                     "carriage_returns"):
            with self.subTest(case=name):
                r = self._assert_fab_not_released(name)
                if len(r) > 1:
                    self.assertEqual(r[-1]["verdict"], "veto", "fabricated cite (last) must be vetoed: " + dh.compact(r))

    def test_draft_content_cannot_spoof_the_wrapper_output(self):
        r = self._assert_fab_not_released("json_spoof_in_prose")
        self.assertNotIn("pass", [x["verdict"] for x in r], dh.compact(r))

    def test_draft_content_is_data_never_arguments(self):
        for name in ("option_injection_dash_dash", "option_injection_help"):
            with self.subTest(case=name):
                r = self._assert_fab_not_released(name)
                self.assertNotIn("pass", [x["verdict"] for x in r], dh.compact(r))

    def test_pathological_nesting(self):
        r = self._assert_fab_not_released("deep_parens")
        self.assertNotIn("pass", [x["verdict"] for x in r], dh.compact(r))

    def test_many_cites_yield_one_veto_each_or_a_single_fail_closed_veto(self):
        r = self._assert_fab_not_released("many_fabricated_cites")
        self.assertTrue(len(r) in (1, HEAVY_N), "neither one result per cite nor one fail-closed veto: %d results" % len(r))
        self.assertTrue(all(x["verdict"] == "veto" for x in r))

    def test_large_inputs_complete_or_fail_closed(self):
        for name in ("long_prose_then_cite", "comma_space_run_before_cite", "cite_start_flood"):
            with self.subTest(case=name):
                r = self._assert_fab_not_released(name)
                self.assertNotIn("pass", [x["verdict"] for x in r], dh.compact(r))
                self.assertTrue(len(r) == 1 or r[-1]["verdict"] == "veto", dh.compact(r))

    def test_a_flood_of_valid_cites_never_passes_anything_it_did_not_check(self):
        name = "valid_cite_flood"
        r = self._results(name)
        self.assertEqual(dh.contract_problems(r), [], dh.compact(r)[:600])
        self.assertTrue(r, "no result for %d citations" % HEAVY_N)
        self.assertTrue(len(r) in (1, HEAVY_N), "neither one result per cite nor one fail-closed veto: %d" % len(r))
        for x in r:
            self.assertIn(x["verdict"], ("pass", "veto"), dh.compact(r)[:600])
            if x["verdict"] == "pass":
                self.assertEqual(x["clusterId"], fx.SMITH)

    def test_no_draft_within_the_size_cap_takes_long_to_settle(self):
        # Absolute budget, restored: the drafts are ~10x smaller than before (40 cites, 6,000-repetition floods, ~20k
        # prose, 3,000 parens), so the original 10 s budget holds unchanged. Scaling is proved separately in-process.
        budget_ms = 10000
        slow = {}
        for name in list(STDIN_CASES) + list(HEAVY_CASES):
            self._results(name)
            ms = self._batch_for(name).ms(name)
            if ms > budget_ms:
                slow[name] = ms
        self.assertEqual(slow, {}, "gate call took longer than %d ms to settle (ms by case): %r" % (budget_ms, slow))

    def test_every_hostile_draft_is_answered_not_cut_off_by_the_wrapper(self):
        # No absolute millisecond budget (that measures the machine, not the gate). The property is that the child
        # FINISHED: the call did not end in the wrapper's own kill-at-timeout / shed / bad-output vetoes. How the
        # cost grows with the draft is proved by the in-process doubling test, which compares t(2n) with t(n).
        cut_off = {}
        for name in list(HEAVY_CASES) + ["deep_parens"]:
            r = self._results(name)
            bad =[x["reason"] for x in r if x["reason"] in ("python_text_failed", "python_text_bad_output", "gate_busy")]
            if bad:
                cut_off[name] = bad
        self.assertEqual(cut_off, {}, "the wrapper gave up on these drafts instead of getting an answer: %r" % cut_off)

    def test_the_event_loop_stays_responsive_while_a_draft_is_checked(self):
        # localGate1Text is async: a 50 ms setInterval in the host process must keep ticking while the child runs,
        # for every draft, however hostile. A gap this long means something synchronous is blocking the server.
        # The reference is measured in the same node process on a trivial draft: a hostile draft may not starve the
        # loop by more than 500 ms, or by more than 5x the longest gap that trivial draft itself saw (a loaded
        # machine stalls the loop for any draft, so only the excess over that is the gate's doing).
        idle = self._batch_for("idle_baseline").loop("idle_baseline")["maxGap"]
        max_gap_ms = max(500, 5 * idle)
        blocked = {}
        for name in list(STDIN_CASES) + list(HEAVY_CASES):
            if name == "idle_baseline":
                continue
            self._results(name)
            loop = self._batch_for(name).loop(name)
            if loop["maxGap"] > max_gap_ms:
                blocked[name] = loop["maxGap"]
        self.assertEqual(blocked, {}, "event loop starved for more than %d ms (idle baseline gap %d ms; max tick gap by "
                         "case): %r" % (max_gap_ms, idle, blocked))

    def test_a_long_draft_actually_yields_ticks_to_the_host(self):
        # Guards the previous test against vacuity: whatever the call duration, timers must have fired at roughly the
        # 50 ms cadence (at least half as often), so a call that blocked the loop for its whole duration fails here.
        name = "valid_cite_flood"
        self._results(name)
        b = self._batch_for(name)
        self.assertGreaterEqual(b.loop(name)["ticks"], b.ms(name) // 50 // 2,
                                "timers barely fired during a %d ms call (ticks=%d)" % (b.ms(name), b.loop(name)["ticks"]))


# ───── structure of the TS wrapper (static) ─────

import re  # noqa: E402


def _ts_code():
    raw = fx.TS_GATE.read_text(encoding="utf-8")
    raw = re.sub(r"/\*.*?\*/", "", raw, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", line) for line in raw.splitlines())


_SPAWN = r"(?:spawnSync|spawn|execFileSync|execFile)"


def _text_region():
    """Everything in the file from the draft-mode types onward: localGate1Text and any helper it uses."""
    code = _ts_code()
    m = re.search(r"export\s+type\s+Gate1CiteKind\b", code)
    if not m:
        raise AssertionError("draft mode (Gate1CiteKind) is not present in local_sqlite_gate.ts")
    return code[m.start():]


def _text_fn_body():
    code = _ts_code()
    m = re.search(r"export\s+(?:async\s+)?function\s+localGate1Text\b", code)
    if not m:
        raise AssertionError("localGate1Text is not exported from local_sqlite_gate.ts")
    rest = code[m.start():]
    nxt = re.search(r"\nexport\s", rest[10:])
    return rest if not nxt else rest[: nxt.start() + 10]


class DraftWrapperSource(unittest.TestCase):
    def test_exported_with_the_approved_async_signature(self):
        code = _ts_code()
        self.assertRegex(code, r"export\s+(?:async\s+)?function\s+localGate1Text\s*\(\s*draft\s*:\s*string\s*(?:,\s*opts\s*\?\s*:\s*LocalGate1Options\s*)?\)\s*:\s*Promise\s*<\s*Gate1TextResult\[\]\s*>")
        self.assertRegex(code, r"export\s+type\s+Gate1CiteKind\s*=")
        self.assertRegex(code, r"export\s+type\s+Gate1TextResult\s*=")
        for kind in ("full", "short", "id", "supra", "unparsed"):
            self.assertRegex(code, r"['\"]%s['\"]" % kind)

    def test_draft_goes_to_the_child_on_stdin_with_a_timeout_and_no_shell(self):
        region = _text_region()
        self.assertRegex(region, r"\b" + _SPAWN + r"\s*\(", "no child process is spawned by the text path")
        self.assertRegex(region, r"\binput\s*:\s*\w+|\.stdin\??\.(?:end|write)\s*\(", "draft must be written to the child's stdin")
        self.assertRegex(region, r"\btimeout\s*:|setTimeout\s*\(", "child call must have a timeout")
        self.assertRegex(region, r"\bmaxBuffer\s*:|MAX_[A-Z_]*(?:BUFFER|OUTPUT|BYTES)", "child output must be bounded")
        self.assertNotRegex(region, r"shell\s*:\s*true")
        argvs = re.findall(_SPAWN + r"\s*\(\s*[^,]+,\s*\[([^\]]*)\]", region)
        self.assertTrue(argvs, "could not find the child's argv array")
        for argv in argvs:
            # spec: `gate1.py --db <path> --text -` with the draft on stdin. The draft never reaches argv.
            self.assertNotRegex(argv, r"\bdraft\b|\btext\b(?!')", "the draft travels in argv: %r" % argv)
            self.assertIn("'-'", argv.replace('"', "'"), "stdin marker '-' missing from argv: %r" % argv)

    def test_draft_size_is_capped_before_the_child_is_spawned(self):
        body = _text_fn_body()
        cap = body.find("MAX_DRAFT_CHARS")
        self.assertNotEqual(cap, -1, "no draft size cap in localGate1Text")
        # The spawn may live in a helper closure defined above the checks (queue/semaphore code). What matters is the
        # first point it is INVOKED: a bare run() call (not its definition) if there is one, else the spawn itself.
        invoke = re.search(r"\brun\(\)", body) or re.search(r"\b" + _SPAWN + r"\s*\(", body)
        if invoke:
            self.assertLess(cap, invoke.start(), "size cap must run before the child is started")

    def test_the_child_slot_is_released_only_once_the_child_has_exited(self):
        # Exact cap: settle() sends SIGKILL, but the process is not gone until it is reaped. Releasing the slot at
        # settle time lets a queued call spawn while the killed child is still alive (cap+1 interpreters).
        region = _text_region()
        settle = re.search(r"const\s+settle\s*=[\s\S]*?\n\s{4}\};", region)
        self.assertIsNotNone(settle, "could not find settle() in the text path")
        for m in re.finditer(r"\breleaseSlot\s*\(\s*\)", settle.group(0)):
            before = settle.group(0)[max(0, m.start() - 200):m.start()]
            self.assertRegex(before, r"exitCode\s*!==\s*null|signalCode\s*!==\s*null|killed|exited",
                             "settle() releases the slot without checking that the child has exited")
        self.assertRegex(region, r"\.(?:on|once)\(\s*'(?:close|exit)'[\s\S]{0,900}?\breleaseSlot\b",
                         "no 'close'/'exit' handler releases the child slot")

    def test_no_second_typescript_parser_in_the_text_path(self):
        region = _text_region()
        for banned in ("scan(", "parseMatch(", "checkNormalized(", "eyecite", "matchAll(", "new RegExp("):
            self.assertNotIn(banned, region, "text path re-implements extraction (%s)" % banned)

    def test_the_promise_can_only_resolve_never_reject(self):
        region = _text_region()
        self.assertNotRegex(region, r"\breject\s*\(", "text path rejects its promise")
        self.assertNotRegex(region, r"\bthrow\b", "text path throws (a throw inside an async function becomes a rejection)")

    def test_wrapper_never_swallows_a_failure_into_an_empty_result(self):
        region = _text_region()
        for m in re.finditer(r"catch\s*(?:\([^)]*\))?\s*\{([^}]*)\}", region):
            inner = m.group(1)
            self.assertNotRegex(inner, r"return\s*\[\s*\]|resolve\s*\(\s*\[\s*\]\s*\)", "a catch block yields [] (fail-open)")
        body = _text_fn_body()
        for m in re.finditer(r"catch\s*(?:\([^)]*\))?\s*\{([^}]*)\}", body):
            inner = m.group(1)
            if inner.strip() == "" and ".kill(" in body[max(0, m.start() - 120):m.start()]:
                continue  # best-effort kill of a child that may already be gone; the verdict is settled elsewhere
            self.assertRegex(inner, r"(?i)veto|fail|=\s*null|resolve|settle", "a catch block in localGate1Text neither vetoes nor nulls: %r" % inner)


if __name__ == "__main__":
    unittest.main()
