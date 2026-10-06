"""Draft mode (gate1.check_text): resolution of short cites / Id. / supra, and every phase-2 fix.

Fixture records (see _draft_fixture.py):
    Smith v. Jones     123 So. 3d 456-470   Florida Supreme Court
    Smith v. State     100 So. 3d 200-210   Florida Supreme Court
    State v. Rodriguez 100 So. 2d 20-35     a DCA
    Alpha Corp. v. Beta Holdings, Inc.  321 So. 3d 789-800   a DCA
"""

import json
import os
import subprocess
import time
import unittest
from pathlib import Path

from _fixture import REPO_ROOT
from _draft_fixture import build_draft_db
from pipeline import gate1
from pipeline.gate1 import check_text

PY = os.path.expanduser("~/.venv-cascade/bin/python")

SJ = "Smith v. Jones, 123 So. 3d 456 (Fla. 2013). "          # 456-470
SS = "Smith v. State, 100 So. 3d 200 (Fla. 2012). "          # 200-210
SJ_FULL = "Smith v. Jones, 123 So. 3d 456 (Fla. 2013)"
SS_FULL = "Smith v. State, 100 So. 3d 200 (Fla. 2012)"


def view(results):
    return [(r.kind, r.verdict, r.reason) for r in results]


class DraftCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp, cls.db = build_draft_db()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_text(self, text):
        return check_text(text, self.db)

    def assertView(self, text, expected):
        got = self.run_text(text)
        self.assertEqual(view(got), expected, [(r.text, r.full_citation) for r in got])
        return got

    def assertAllVeto(self, text):
        got = self.run_text(text)
        self.assertTrue(got, "citation vanished: %r" % text)
        self.assertTrue(all(r.verdict == "veto" for r in got), (text, view(got)))
        return got


class ResolutionTests(DraftCase):
    def test_short_cite_passes_and_inherits(self):
        got = self.assertView(SJ + "Smith, 123 So. 3d at 461.", [("full", "pass", "verified"), ("short", "pass", "verified")])
        self.assertEqual(got[1].full_citation, SJ_FULL)
        self.assertEqual((got[1].reporter, got[1].volume, got[1].page, got[1].cluster_id), ("So. 3d", 123, 456, 1))

    def test_id_passes_and_inherits(self):
        got = self.assertView(SJ + "Id. at 461.", [("full", "pass", "verified"), ("id", "pass", "verified")])
        self.assertEqual(got[1].full_citation, SJ_FULL)

    def test_supra_passes(self):
        self.assertView(SJ + "Smith, supra, at 461.", [("full", "pass", "verified"), ("supra", "pass", "verified")])

    def test_id_chain(self):
        self.assertView(SJ + "Id. at 460. Id. at 461. Id.",
                        [("full", "pass", "verified")] + [("id", "pass", "verified")] * 3)

    def test_id_chain_pin_failure_does_not_poison_later_ids(self):
        # An out-of-range pin vetoes that Id. only; the next Id. still resolves to the same record.
        self.assertView(SJ + "Id. at 460. Id. at 900. Id. at 461.",
                        [("full", "pass", "verified"), ("id", "pass", "verified"),
                         ("id", "veto", "pin_out_of_bounds"), ("id", "pass", "verified")])

    def test_id_after_statute_is_non_case_antecedent(self):
        got = self.assertView("See Fla. Stat. § 90.803 (2020). Id. at 5.",
                              [("id", "fall_through", "non_case_antecedent")])
        self.assertIsNone(got[0].full_citation)
        got = self.assertView("See 42 U.S.C. § 1983. Id.", [("id", "fall_through", "non_case_antecedent")])
        self.assertIsNone(got[0].full_citation)

    def test_id_after_statute_following_a_case(self):
        got = self.assertView(SJ + "See Fla. Stat. § 90.803 (2020). Id. at 5.",
                              [("full", "pass", "verified"), ("id", "fall_through", "non_case_antecedent")])
        self.assertIsNone(got[1].full_citation)

    def test_unresolved_id(self):
        self.assertView("Id. at 461.", [("id", "veto", "unresolved_short_cite")])

    def test_unresolved_short_cite(self):
        self.assertView("Smith, 123 So. 3d at 461.", [("short", "veto", "unresolved_short_cite")])

    def test_unresolved_supra(self):
        self.assertView("Smith, supra, at 461.", [("supra", "veto", "unresolved_short_cite")])

    def test_short_cite_to_a_different_volume_is_unresolved(self):
        got = self.run_text(SJ + "Smith, 124 So. 3d at 461.")
        self.assertEqual(got[-1].verdict, "veto")

    def test_antecedent_veto_propagates(self):
        got = self.assertView("Fake v. Case, 999 So. 3d 5 (Fla. 2012). Id. at 6. Fake, 999 So. 3d at 6.",
                              [("full", "veto", "not_found"), ("id", "veto", "antecedent_vetoed"),
                               ("short", "veto", "antecedent_vetoed")])
        self.assertTrue(all(r.verdict == "veto" for r in got))

    def test_pin_out_of_range_via_id_and_short(self):
        self.assertView(SJ + "Id. at 471.", [("full", "pass", "verified"), ("id", "veto", "pin_out_of_bounds")])
        self.assertView(SJ + "Id. at 455.", [("full", "pass", "verified"), ("id", "veto", "pin_out_of_bounds")])
        self.assertView(SJ + "Smith, 123 So. 3d at 499.", [("full", "pass", "verified"), ("short", "veto", "pin_out_of_bounds")])
        self.assertView(SJ + "Smith, supra, at 499.", [("full", "pass", "verified"), ("supra", "veto", "pin_out_of_bounds")])

    def test_pin_inside_range_via_id_and_range(self):
        self.assertView(SJ + "Id. at 460-465.", [("full", "pass", "verified"), ("id", "pass", "verified")])
        self.assertView(SJ + "Id. at 460-471.", [("full", "pass", "verified"), ("id", "veto", "pin_out_of_bounds")])

    def test_star_page_pin_is_not_read_as_a_page(self):
        got = self.run_text(SJ + "Id. at *4.")
        self.assertEqual((got[1].verdict, got[1].reason), ("veto", "pin_unparseable"))

    def test_mixed_florida_alabama_federal(self):
        text = (SJ + "Id. at 460. Doe v. Roe, 100 So. 3d 555 (Ala. 2015). Id. at 205. "
                "Roe v. Wade, 410 U.S. 113 (1973). Id. at 150. See also 5 F.3d 1 (11th Cir. 1999).")
        got = self.run_text(text)
        self.assertEqual([(r.kind, r.verdict) for r in got],
                         [("full", "pass"), ("id", "pass"), ("full", "fall_through"), ("id", "fall_through"),
                          ("full", "fall_through"), ("id", "fall_through"), ("full", "fall_through")])
        # An Id. after an Alabama / federal cite inherits that cite's window, not Florida's.
        self.assertEqual(got[3].full_citation, "Doe v. Roe, 100 So. 3d 555 (Ala. 2015)")
        self.assertEqual(got[5].full_citation, "Roe v. Wade, 410 U.S. 113 (1973)")
        self.assertEqual(got[1].full_citation, SJ_FULL)

    def test_florida_cite_after_alabama_cite_is_still_checked(self):
        self.assertView("Doe v. Roe, 100 So. 3d 555 (Ala. 2015). Fake v. Case, 999 So. 3d 5 (Fla. 2012).",
                        [("full", "fall_through", "non_florida_court"), ("full", "veto", "not_found")])

    def test_results_ordered_and_offsets_index_the_cleaned_draft(self):
        text = "*Smith v. Jones*, 123 So. 3d 456 (Fla. 2013). *Id.* at 461. Doe v. Roe, 100 So. 3d 555 (Ala. 2015)."
        got = self.run_text(text)
        cleaned = gate1._clean_draft(text)
        self.assertEqual([r.start for r in got], sorted(r.start for r in got))
        for r in got:
            self.assertEqual(cleaned[r.start:r.end], r.text)
        self.assertNotEqual(cleaned, text)

    def test_every_result_honours_the_contract(self):
        text = (SJ + "Id. Smith, 123 So. 3d at 461. Fake v. Case, 999 So. 3d 5 (Fla. 2012). Id. "
                "See 42 U.S.C. section 1983. Id. 999 So.3d (Fla.) lOO So. 3d 5")
        for r in self.run_text(text):
            self.assertIn(r.verdict, ("pass", "veto", "fall_through"))
            self.assertIn(r.kind, ("full", "short", "id", "supra", "unparsed"))
            self.assertTrue(r.reason)
            if r.verdict == "pass":
                self.assertIsNotNone(r.cluster_id)
                self.assertIsNotNone(r.full_citation)
            if r.verdict == "fall_through" and r.reason != "non_case_antecedent":
                self.assertIsNotNone(r.full_citation)

    def test_deterministic(self):
        text = SJ + "Smith, 123 So. 3d at 461. Id. Hernandez, supra. lOO So. 3d 5"
        self.assertEqual(self.run_text(text), self.run_text(text))

    def test_non_string_and_too_long(self):
        for bad in (None, 5, b"x", ["a"]):
            self.assertEqual(view(check_text(bad, self.db)), [("unparsed", "veto", "unparseable")])
        self.assertEqual(view(check_text("x" * (gate1.MAX_TEXT_CHARS + 1), self.db)), [("unparsed", "veto", "too_long")])

    def test_missing_db_vetoes_florida_cite(self):
        got = check_text(SJ + "Id. at 460.", Path(self.tmp.name) / "nope.db")
        self.assertTrue(got and all(r.verdict == "veto" for r in got), view(got))


class RenderedTextTests(DraftCase):
    """The cleaner removes markup syntax but never discards text a renderer can show."""

    FAKE = "Doe v. Roe, 999 So. 3d 999 (Fla. 2015)"
    REAL = "Smith v. State, 100 So. 3d 200 (Fla. 2012)"

    CARRIERS = {
        "html_title": '<span title="{}">hover</span>',
        "html_title_single_quote": "<span title='{}'>hover</span>",
        "html_title_unquoted": "<span title={}>hover</span>",
        "anchor_title": '<a href="https://example.com/x" title="{}">link</a>',
        "img_alt": '<img src="a.png" alt="{}"/>',
        "abbr_title": '<abbr title="{}">x</abbr>',
        "aria_label": '<button aria-label="{}">x</button>',
        "data_attr": '<div data-note="{}">x</div>',
        "md_link_title": '[link](https://example.com/x "{}")',
        "md_link_title_single": "[link](https://example.com/x '{}')",
        "md_image_title": '![pic](a.png "{}")',
        "md_angle_dest": "[link](<{}>)",
        "html_comment": "<!-- {} -->",
        "comment_in_code_fence": "```html\n<!-- {} -->\n```",
        "attr_in_code_fence": '```html\n<span title="{}">x</span>\n```',
        "entity_encoded_tag": '&lt;span title="{}"&gt;x&lt;/span&gt;',
        "entity_encoded_tag_numeric": '&#60;span title="{}"&#62;x&#60;/span&#62;',
        "entity_encoded_comment": "&lt;!-- {} --&gt;",
        "double_encoded_tag": '&amp;lt;span title="{}"&amp;gt;x',
        "entity_in_attr": '<span title="{}">x</span>',
        "nested_markup_in_attr": '<span title="&lt;b&gt;{}&lt;/b&gt;">x</span>',
        "comment_in_attr_entity": '<span title="&lt;!-- {} --&gt;">x</span>',
    }

    def test_hidden_fabricated_cite_is_vetoed_not_dropped(self):
        for label, carrier in self.CARRIERS.items():
            for pre in ("", "As the court said, "):
                text = pre + carrier.format(self.FAKE) + " That is the rule."
                with self.subTest(carrier=label, pre=pre):
                    got = self.run_text(text)
                    self.assertTrue(got, "cite in %s vanished: %r" % (label, text))
                    self.assertTrue(all(r.verdict == "veto" for r in got), view(got))

    def test_real_cite_in_a_hidden_place_is_checked(self):
        for label, carrier in self.CARRIERS.items():
            if label == "html_title_unquoted":
                continue  # invalid HTML: a browser shows only 'Smith'; the rest is kept and vetoed (veto test)
            text = "The rule is settled. " + carrier.format(self.REAL)
            with self.subTest(carrier=label):
                got = self.run_text(text)
                self.assertEqual([(r.verdict, r.reason) for r in got], [("pass", "verified")], view(got))

    def test_wrong_name_in_a_hidden_place_vetoes(self):
        got = self.run_text('<span title="Hernandez v. Walmart, 100 So. 3d 200 (Fla. 2012)">x</span>')
        self.assertEqual([(r.verdict, r.reason) for r in got], [("veto", "caption_mismatch")])

    def test_hidden_variants_inside_attributes_are_still_vetoed(self):
        for variant in ("999So. 3d 5 (Fla. 2012)", "___ So. 3d ___ (Fla. 2012)", "lOO So. 3d 5 (Fla. 2012)",
                        "999&nbsp;So. 3d 5 (Fla. 2012)", "999 So\\. 3d 5 (Fla. 2012)"):
            for carrier in ('<span title="{}">x</span>', '[a](u "{}")', "<!-- {} -->"):
                with self.subTest(variant=variant, carrier=carrier):
                    got = self.run_text(carrier.format(variant))
                    self.assertTrue(got and all(r.verdict == "veto" for r in got), view(got))

    def test_offsets_still_index_the_cleaned_text(self):
        text = '<span title="%s">x</span> %s [l](u "Id. at 205") <!-- 999So. 3d 5 -->' % (self.REAL, self.REAL)
        cleaned = gate1._clean_draft(text)
        got = self.run_text(text)
        self.assertTrue(got)
        for r in got:
            self.assertEqual(cleaned[r.start:r.end], r.text)
        self.assertIn(self.REAL, cleaned)
        self.assertIn("Id. at 205", cleaned)

    def test_segments_do_not_run_into_each_other(self):
        # Two titles that would form 'Smith v.' + 'State, 100 ...' if concatenated without a separator.
        text = '<i title="Smith v.">a</i><i title="State, 100 So. 3d 200 (Fla. 2012)">b</i>'
        got = self.run_text(text)
        self.assertEqual([r.verdict for r in got], ["veto"] if got and got[0].reason == "caption_unparseable" else
                         [r.verdict for r in got])
        self.assertNotEqual(got[0].full_citation, "Smith v. State, 100 So. 3d 200 (Fla. 2012)")

    def test_non_text_attributes_are_not_scanned(self):
        text = '<a href="https://x.example/opinion/so-3d/200" class="999 So. 3d 5" id="a">link</a> Plain prose.'
        self.assertEqual(self.run_text(text), [])

    def test_ordinary_markup_has_no_citation_residue(self):
        text = ('<img src="a.png" alt="A chart of filings"/> <b>Bold</b> [link](https://example.com "Example site") '
                '![pic](a.png "A picture") <!-- todo: rewrite --> Some prose.')
        self.assertEqual(self.run_text(text), [])

    def test_attribute_heavy_drafts_finish_fast(self):
        for text in ('<a ' + 'title="x" ' * 12000 + '>', ('<i title="a">' * 8000), '<a ' * 20000,
                     '[a](u "' * 15000, '<!--' + ' x' * 40000 + '-->' * 3):
            t0 = time.time()
            self.assertIsInstance(self.run_text(text[:150_000]), list)
            self.assertLess(time.time() - t0, 10.0)


class SouthernProseTests(DraftCase):
    """A loosely-Southern 'reporter' never falls through in draft mode without a positively identified court."""

    PROSE = [
        "She has served 12 So. Fla. counties since 2010.",
        "The firm opened 5 So. Cal. offices in 2019.",
        "He moved to 3 So. Carolina towns before 1999.",
        "She visited 4 South Florida cities in 2005.",
        "It has 7 Southern States since 1990.",
        "Over 9 S0. Fla. clinics in 2001.",
    ]

    def test_prose_vetoes(self):
        for text in self.PROSE:
            with self.subTest(text=text):
                got = self.run_text(text)
                self.assertTrue(got)
                self.assertTrue(all(r.verdict == "veto" for r in got), view(got))
                self.assertEqual(got[0].reason, "unparsed_citation")
                self.assertEqual(got[0].kind, "unparsed")

    def test_real_non_florida_southern_cites_still_fall_through(self):
        self.assertView("Ex parte Johnson, 175 So. 3d 700 (Ala. 2015)", [("full", "fall_through", "non_florida_court")])
        self.assertView("Doe v. Roe, 100 So. 2d 20 (La. Ct. App. 1950)", [("full", "fall_through", "non_florida_court")])

    def test_other_prose_with_numbers_still_falls_through_as_before(self):
        self.assertView("Roe v. Wade, 410 U.S. 113 (1973).", [("full", "fall_through", "not_florida_key")])

    def test_id_after_prose_veto_is_vetoed(self):
        got = self.run_text("She has served 12 So. Fla. counties since 2010. Id. at 5.")
        self.assertTrue(all(r.verdict == "veto" for r in got), view(got))

    def test_single_cite_path_unchanged(self):
        r = gate1.check_citation("12 So. Fla. counties since 2010", self.db)
        self.assertEqual((r.verdict, r.reason), ("fall_through", "not_florida_key"))


class EmptyDraftTests(DraftCase):
    def test_empty_and_whitespace_drafts_are_empty_lists(self):
        for d in ("", " ", "\n\t   ", "​", "﻿", "\x00\x01", "<!-- -->", "<br/>", "&nbsp;", "***", "[]"):
            with self.subTest(d=d):
                self.assertEqual(self.run_text(d), [])

    def test_prose_without_citations_is_never_vetoed(self):
        prose = ("The statute of limitations is four years. So 3 courts agreed; the So. reporter is old. "
                 "The Southern District of Florida and the Third District disagree. See the 2d edition. "
                 "Section 768.81 applies, as does Fla. Stat. § 95.11. Fla. L. Rev. has an article. "
                 "Fla. L. Weekly Fed. is a federal reporter. R&D costs 5 million; 1990-91 was a good year.")
        self.assertEqual(self.run_text(prose), [])


class CaptionDressingTests(DraftCase):
    """2a: a name dressed in markup must be compared, never skipped."""

    DRESSINGS = {
        "plain": "{}",
        "italic": "*{}*",
        "bold": "**{}**",
        "underscore": "_{}_",
        "html_i": "<i>{}</i>",
        "html_span": "<span class=\"c\">{}</span>",
        "link": "[{}](https://example.com/x)",
        "double_quotes": "\"{}\"",
        "curly_quotes": "“{}”",
        "single_quotes": "'{}'",
        "brackets": "[{}]",
        "backticks": "`{}`",
        "entities": "&lsquo;{}&rsquo;",
    }
    CITE = ", 100 So. 3d 200 (Fla. 2012)"

    def test_wrong_name_vetoes_under_every_dressing(self):
        for name in ("Hernandez v. Walmart Stores, Inc.", "Hernandez, et al. v. Walmart Stores, Inc.",
                     "Hernandez et ux. v. Walmart", "In re Hernandez"):
            for label, dress in self.DRESSINGS.items():
                text = dress.format(name) + self.CITE
                with self.subTest(name=name, dress=label):
                    got = self.run_text(text)
                    self.assertEqual([r.verdict for r in got], ["veto"], view(got))
                    self.assertIn(got[0].reason, ("caption_mismatch", "caption_unparseable"))

    def test_right_name_passes_under_every_dressing(self):
        for name in ("Smith v. State", "Smith, et al. v. State", "Smith et al. v. State"):
            for label, dress in self.DRESSINGS.items():
                text = dress.format(name) + self.CITE
                with self.subTest(name=name, dress=label):
                    self.assertView(text, [("full", "pass", "verified")])

    def test_marker_without_a_readable_caption_vetoes(self):
        for text in ("hernandez v. walmart stores" + self.CITE, "Hernandez v. walmart stores" + self.CITE,
                     "hernandez v Walmart" + self.CITE, "x v. y" + self.CITE):
            with self.subTest(text=text):
                got = self.run_text(text)
                self.assertEqual([r.verdict for r in got], ["veto"], view(got))

    def test_name_before_a_nameless_cite_belongs_to_an_earlier_sentence(self):
        # No name is attached to this cite, so there is nothing to compare (existence still holds).
        self.assertView("In Smith v. Jones the court held this. See 100 So. 3d 200 (Fla. 2012).",
                        [("full", "pass", "verified")])

    def test_appositive_name_is_compared(self):
        self.assertView("In Smith v. Jones, the court held that rule applies, 123 So. 3d 456 (Fla. 2013).",
                        [("full", "pass", "verified")])
        got = self.run_text("In Hernandez v. Walmart, the court held that rule applies, 123 So. 3d 456 (Fla. 2013).")
        self.assertEqual((got[0].verdict, got[0].reason), ("veto", "caption_mismatch"))

    def test_unreadable_name_cannot_launder_an_alabama_cite(self):
        self.assertView("*Hernandez v. Walmart*, 100 So. 3d 555 (Ala. 2015)", [("full", "fall_through", "non_florida_court")])


class ShortCiteNameTests(DraftCase):
    """2b: a short cite's own name must match its antecedent."""

    def test_wrong_name_vetoes(self):
        for tail in ("Hernandez, 100 So. 3d at 205.", "See Hernandez, 100 So. 3d at 205.", "*Hernandez*, 100 So. 3d at 205.",
                     "Hernandez v. Walmart, 100 So. 3d at 205.", "In Hernandez, 100 So. 3d at 205."):
            with self.subTest(tail=tail):
                got = self.assertView(SS + tail, [("full", "pass", "verified"), ("short", "veto", "caption_mismatch")])
                self.assertEqual(got[1].full_citation, SS_FULL)

    def test_right_name_passes(self):
        for tail in ("Smith, 100 So. 3d at 205.", "See Smith, 100 So. 3d at 205.", "*Smith*, 100 So. 3d at 205.",
                     "State, 100 So. 3d at 205.", "Smith v. State, 100 So. 3d at 205.", "100 So. 3d at 205.",
                     "However, Smith, 100 So. 3d at 205."):
            with self.subTest(tail=tail):
                self.assertView(SS + tail, [("full", "pass", "verified"), ("short", "pass", "verified")])

    def test_signals_are_not_names(self):
        for sig in ("See", "See also", "See generally", "Cf.", "Accord", "But see", "But cf.", "Compare", "Contra",
                    "E.g.,", "See, e.g.,", "*See*", "_See also_", "<i>See</i>", "*Cf.*", "**But see**", "*See generally*"):
            with self.subTest(sig=sig):
                self.assertView(SS + sig + " 100 So. 3d at 205.",
                                [("full", "pass", "verified"), ("short", "pass", "verified")])
                self.assertView("Ex parte Johnson, 100 So. 3d 555 (Ala. 2015). " + sig + " 100 So. 3d at 205.",
                                [("full", "fall_through", "non_florida_court"),
                                 ("short", "fall_through", "non_florida_court")])

    def test_a_signal_cannot_dodge_a_real_mismatch(self):
        for sig in ("See", "See also", "Cf.", "But see", "*See*", "E.g.,", "See, e.g.,", "Accord"):
            with self.subTest(sig=sig):
                self.assertView(SS + sig + " Hernandez, 100 So. 3d at 205.",
                                [("full", "pass", "verified"), ("short", "veto", "caption_mismatch")])
                self.assertView("Ex parte Johnson, 100 So. 3d 555 (Ala. 2015). " + sig + " Hernandez, 100 So. 3d at 205.",
                                [("full", "fall_through", "non_florida_court"), ("short", "veto", "caption_mismatch")])

    def test_only_a_whole_party_matches(self):
        # 'Smith' is a party of 'Smith v. State'; 'Smithson' is not.
        self.assertView(SS + "Smithson, 100 So. 3d at 205.", [("full", "pass", "verified"), ("short", "veto", "caption_mismatch")])

    def test_wrong_name_on_supra_vetoes(self):
        got = self.run_text(SS + "Hernandez, supra, at 205.")
        self.assertEqual(got[0].verdict, "pass")
        self.assertEqual(got[1].verdict, "veto")
        self.assertEqual(got[1].kind, "supra")

    def test_name_second_in_a_string_cite(self):
        got = self.run_text("Smith v. Jones, 123 So. 3d 456 (Fla. 2013); Smith v. State, 100 So. 3d 200 (Fla. 2012). "
                            "Smith, 100 So. 3d at 205. Jones, 123 So. 3d at 460. Hernandez, 123 So. 3d at 460.")
        self.assertEqual([(r.kind, r.verdict, r.reason) for r in got],
                         [("full", "pass", "verified"), ("full", "pass", "verified"), ("short", "pass", "verified"),
                          ("short", "pass", "verified"), ("short", "veto", "caption_mismatch")])

    def test_laundering_through_an_alabama_cite(self):
        got = self.assertView("Ex parte Johnson, 100 So. 3d 555 (Ala. 2015). Smith, 100 So. 3d at 205.",
                              [("full", "fall_through", "non_florida_court"), ("short", "veto", "caption_mismatch")])
        self.assertEqual(got[1].full_citation, "Ex parte Johnson, 100 So. 3d 555 (Ala. 2015)")

    def test_matching_name_after_an_alabama_cite_falls_through(self):
        self.assertView("Ex parte Johnson, 100 So. 3d 555 (Ala. 2015). Johnson, 100 So. 3d at 205.",
                        [("full", "fall_through", "non_florida_court"), ("short", "fall_through", "non_florida_court")])
        self.assertView("Doe v. Roe, 100 So. 3d 555 (Ala. 2015). Roe, 100 So. 3d at 205. 100 So. 3d at 206.",
                        [("full", "fall_through", "non_florida_court"), ("short", "fall_through", "non_florida_court"),
                         ("short", "fall_through", "non_florida_court")])

    def test_named_short_cite_to_a_nameless_fall_through_is_unverifiable(self):
        self.assertView("100 So. 3d 555 (Ala. 2015). Smith, 100 So. 3d at 205.",
                        [("full", "fall_through", "non_florida_court"), ("short", "veto", "caption_unverifiable")])

    def test_federal_laundering(self):
        self.assertView("Roe v. Wade, 410 U.S. 113 (1973). Smith, 410 U.S. at 150.",
                        [("full", "fall_through", "not_florida_key"), ("short", "veto", "caption_mismatch")])
        self.assertView("Roe v. Wade, 410 U.S. 113 (1973). Roe, 410 U.S. at 150.",
                        [("full", "fall_through", "not_florida_key"), ("short", "fall_through", "not_florida_key")])


class HiddenCitationTests(DraftCase):
    """2c: a fabricated Florida cite must never vanish."""

    FAKE_PRE = "Fabricated v. Case, "
    VARIANTS = {
        "md_escape": "999 So\\. 3d 5 (Fla. 2012)",
        "md_escape_reporter": "999 So\\.\\ 3d 5 (Fla. 2012)",
        "nbsp_entity": "999&nbsp;So. 3d&nbsp;5 (Fla. 2012)",
        "numeric_entity": "999&#160;So. 3d&#160;5 (Fla. 2012)",
        "hex_entity": "999&#xA0;So. 3d&#xa0;5 (Fla. 2012)",
        "double_escaped_entity": "999&amp;nbsp;So. 3d 5 (Fla. 2012)",
        "bold_tag": "999 <b>So.</b> 3d 5 (Fla. 2012)",
        "split_by_tag": "999 So<b></b>. 3d 5 (Fla. 2012)",
        "span_tag": "999 <span>So. 3d</span> 5 (Fla. 2012)",
        "comment_in_reporter": "999 So<!-- hidden -->. 3d 5 (Fla. 2012)",
        "comment_empty": "999 So.<!-- --> 3d 5 (Fla. 2012)",
        "emphasis_reporter": "999 *So. 3d* 5 (Fla. 2012)",
        "emphasis_volume": "*999* So. 3d 5 (Fla. 2012)",
        "emphasis_page": "999 So. 3d *5* (Fla. 2012)",
        "underscore_emphasis": "_999_ _So. 3d_ 5 (Fla. 2012)",
        "hyphen_break": "999 So. 3-\nd 5 (Fla. 2012)",
        "hyphen_break_volume": "9-\n99 So. 3d 5 (Fla. 2012)",
        "hyphen_after_period": "999 So.-\n3d 5 (Fla. 2012)",
        "hyphen_after_period_crlf": "999 So.-\r\n  3d 5 (Fla. 2012)",
        "unicode_hyphen_break": "999 So.‐\n3d 5 (Fla. 2012)",
        "non_breaking_hyphen_break": "999 So.‑\n3d 5 (Fla. 2012)",
        "soft_hyphen_break": "999 So.­\n3d 5 (Fla. 2012)",
        "soft_hyphen_inline": "999 So.­3d 5 (Fla. 2012)",
        "hyphen_before_dot": "999 So-\n.3d 5 (Fla. 2012)",
        "hyphen_before_page": "999 So.3d-\n5 (Fla. 2012)",
        "hyphen_weekly": "45 Fla. L.-\nWeekly D1",
        "missing_space_volume": "999So. 3d 5 (Fla. 2012)",
        "missing_space_page": "999 So. 3d5 (Fla. 2012)",
        "page_letter_suffix": "999 So. 3d 5a (Fla. 2012)",
        "volume_letter_suffix": "999a So. 3d 5 (Fla. 2012)",
        "control_char": "999 S\x00o. 3d 5 (Fla. 2012)",
        "control_char_2": "999 So.\x07 3d 5 (Fla. 2012)",
        "bidi": "999 So.‮ 3d 5 (Fla. 2012)",
        "placeholders": "___ So. 3d ___ (Fla. 2012)",
        "placeholder_page": "999 So. 3d ___ (Fla. 2012)",
        "placeholder_volume": "____ So. 3d 5 (Fla. 2012)",
        "single_blank": "_ So. 3d _ (Fla. 2012)",
        "ocr_lOO": "lOO So. 3d 5 (Fla. 2012)",
        "ocr_1OO": "1OO So. 3d 5 (Fla. 2012)",
        "ocr_2OO": "2OO So. 3d 5 (Fla. 2012)",
        "ocr_page": "999 So. 3d lOO (Fla. 2012)",
        "so_2d_ocr": "1OO So. 2d 5 (Fla. 1999)",
        "bare_so_glued": "9So. 5 (Fla. 1940)",
        "weekly_ocr": "45 FIa. L. Weekly D1",
        "weekly_placeholder": "45 Fla. L. Weekly D___",
        "weekly_glued": "45Fla. L. Weekly D1",
        "weekly_escape": "45 Fla\\. L\\. Weekly D1",
        "weekly_tag": "45 <i>Fla. L. Weekly</i> D9999",
        "uppercase": "999 SO. 3D 5 (Fla. 2012)",
        "lowercase": "999 so. 3d 5 (Fla. 2012)",
        "so_3d_spaced": "999 So . 3d 5 (Fla. 2012)",
    }

    def test_every_variant_is_vetoed_not_dropped(self):
        for name, cite in self.VARIANTS.items():
            for pre in ("", self.FAKE_PRE, "As the court said, " + self.FAKE_PRE):
                with self.subTest(variant=name, pre=pre[:12]):
                    got = self.run_text(pre + cite + ", the rule is clear.")
                    self.assertTrue(got, "fabricated cite vanished: %r" % (pre + cite))
                    self.assertTrue(all(r.verdict == "veto" for r in got), view(got))

    def test_residue_results_are_unparsed_vetoes_with_spans(self):
        for name in ("missing_space_volume", "missing_space_page", "placeholders", "ocr_lOO", "weekly_placeholder",
                     "page_letter_suffix", "volume_letter_suffix"):
            text = "As held, " + self.VARIANTS[name] + ", the rule is clear."
            cleaned = gate1._clean_draft(text)
            with self.subTest(variant=name):
                got = self.run_text(text)
                un = [r for r in got if r.kind == "unparsed"]
                self.assertTrue(un, view(got))
                for r in un:
                    self.assertEqual((r.verdict, r.reason), ("veto", "unparsed_citation"))
                    self.assertTrue(r.start < r.end)
                    self.assertEqual(cleaned[r.start:r.end], r.text)
                    self.assertIn("So.", r.text) if name != "weekly_placeholder" else self.assertIn("Weekly", r.text)

    def test_residue_never_overlaps_other_results_and_emits_once(self):
        text = SJ + "Smith, 123 So. 3d at 461. Id. at 462. 999So. 3d 5 and ___ So. 3d ___ and 45 Fla. L. Weekly D___."
        got = self.run_text(text)
        spans = sorted((r.start, r.end) for r in got)
        for (a1, b1), (a2, b2) in zip(spans, spans[1:]):
            self.assertLessEqual(b1, a2, view(got))
        self.assertEqual(len([r for r in got if r.kind == "unparsed"]), 3)

    def test_real_cites_produce_no_residue(self):
        text = (SJ + SS + "45 Fla. L. Weekly D123 (Fla. 2d DCA 2020). Roe v. Wade, 410 U.S. 113 (1973). "
                "Doe v. Roe, 100 So. 3d 555 (Ala. 2015). 35 Fla. L. Weekly Fed. D12. Smith, 123 So. 3d at 461. Id. at 462.")
        self.assertFalse([r for r in self.run_text(text) if r.kind == "unparsed"])

    def test_dressed_real_cite_gets_a_real_verdict(self):
        self.assertView("*Smith v. Jones*, *123* So.\\ 3d 456 (Fla. 2013)", [("full", "pass", "verified")])
        self.assertView("<b>Smith v. Jones</b>, 123&nbsp;So. 3d&#160;456 (Fla.&nbsp;2013)", [("full", "pass", "verified")])
        # A hyphen-newline between digits is kept as a hyphen ('4-56'): the cite is malformed, vetoed.
        self.assertView("Smith v. Jones, 123 So. 3d 4-\n56 (Fla. 2013)", [("full", "veto", "malformed")])
        # A hyphen-newline inside a word is a hyphenation and is joined.
        self.assertView("Smith v. Jo-\nnes, 123 So. 3d 456 (Fla. 2013)", [("full", "pass", "verified")])

    def test_homoglyph_scan_still_works(self):
        got = self.run_text("As held, 999 Sо. 3d 5 (Fla. 2012), the rule is clear.")
        self.assertTrue(got and all(r.verdict == "veto" for r in got))


class MarkdownIdTests(DraftCase):
    """2d: an emphasized Id. is recognized and pin-checked."""

    def test_emphasized_id_forms_pass(self):
        for idform in ("*Id.* at 461", "_Id._ at 461", "**Id.** at 461", "<i>Id.</i> at 461", "<em>Id.</em> at 461",
                       "*Id*. at 461", "[Id.](#x) at 461", "\"Id.\" at 461"):
            with self.subTest(idform=idform):
                got = self.run_text(SJ + idform + ".")
                self.assertEqual([(r.kind, r.verdict) for r in got], [("full", "pass"), ("id", "pass")], view(got))

    def test_emphasized_id_pin_is_checked(self):
        for idform in ("*Id.* at 499", "_Id._ at 499", "<i>Id.</i> at 499"):
            with self.subTest(idform=idform):
                self.assertView(SJ + idform + ".", [("full", "pass", "verified"), ("id", "veto", "pin_out_of_bounds")])

    def test_id_without_a_period_is_not_dropped(self):
        got = self.run_text(SJ + "Id at 499.")
        self.assertEqual(got[-1].verdict, "veto")
        self.assertEqual(got[-1].kind, "id")


class ReDoSTests(DraftCase):
    def test_source_has_no_quadratic_trailing_strip(self):
        src = (REPO_ROOT / "pipeline" / "gate1.py").read_text(encoding="utf-8")
        self.assertNotIn('re.sub(r"[ ,]+$"', src)
        self.assertNotIn("[ ,]+$", src)

    def test_pathological_drafts_finish_fast(self):
        n = 190_000
        cases = {
            "comma gap": "a" + ", " * (n // 2) + "123 So. 3d 456 (Fla. 2013)",
            "space comma gap": "Smith v. Jones" + " ," * (n // 2) + " 123 So. 3d 456 (Fla. 2013)",
            "unclosed comments": "<!--" * (n // 4),
            "unclosed tags": "<a " * (n // 3),
            "brackets": "[" * (n // 2) + "(" * 10,
            "bracket pairs": "[a" * (n // 2),
            "link openers": "[a](" * (n // 4),
            "underscores": "_ " * (n // 2),
            "stars": "*" * n,
            "hyphen newlines": "a- \n" * (n // 4),
            "digits": "1 " * (n // 2),
            "ocr run": "So. 3d " + "O" * (n // 2),
            "parens": "(" * n,
            "caption v": "A v. " * (n // 5) + "123 So. 3d 456 (Fla. 2013)",
            "caption caps": "Smith " * (n // 6) + "v. Jones, 123 So. 3d 456 (Fla. 2013)",
            "many pins": "123 So. 3d 456" + ", 1" * 60_000,
            "long word": "1 " + "A" * n,
            "entities": "&amp;" * (n // 5),
        }
        for name, text in cases.items():
            with self.subTest(name=name):
                t0 = time.time()
                got = self.run_text(text[:n])
                self.assertLess(time.time() - t0, 15.0, name)
                self.assertIsInstance(got, list)

    def test_id_chain_scales_linearly(self):
        def run(k):
            t0 = time.time()
            self.run_text(SJ + "Id. at 460. " * k)
            return time.time() - t0
        small, big = run(2000), run(8000)
        self.assertLess(big, max(small, 0.2) * 12, (small, big))


class CaptionWindowTests(DraftCase):
    """2g: prior-sentence junk must not leak into the window (it feeds CourtListener and the cache key)."""

    def test_windows_are_clean(self):
        cases = {
            "5. " + SJ_FULL: SJ_FULL,
            "Id. " + SJ_FULL: SJ_FULL,
            "See " + SJ_FULL: SJ_FULL,
            "See also " + SJ_FULL: SJ_FULL,
            "However, " + SJ_FULL: SJ_FULL,
            "The rule is old (Fla. 2012). " + SJ_FULL: SJ_FULL,
            "The rule is old. " + SJ_FULL: SJ_FULL,
            "The rule is old; " + SJ_FULL: SJ_FULL,
            "(citing X). " + SJ_FULL: SJ_FULL,
            "1. " + "*" + "Smith v. Jones" + "*" + ", 123 So. 3d 456 (Fla. 2013)": SJ_FULL,
            "in the case of Smith v. Jones, 123 So. 3d 456 (Fla. 2013)": SJ_FULL,
            "Fla. Stat. § 90.803. Smith v. Jones, 123 So. 3d 456 (Fla. 2013)": SJ_FULL,
            "Smith v. Jones, 123 So. 3d 456 (Fla. 2013), and Smith v. State, 100 So. 3d 200 (Fla. 2012)": SJ_FULL,
        }
        for text, want in cases.items():
            with self.subTest(text=text):
                got = [r for r in self.run_text(text) if r.kind == "full"]
                self.assertEqual(got[0].full_citation, want)
                self.assertEqual(got[0].verdict, "pass")

    def test_second_cite_window_excludes_the_first(self):
        got = self.run_text("Smith v. Jones, 123 So. 3d 456 (Fla. 2013), and Smith v. State, 100 So. 3d 200 (Fla. 2012)")
        self.assertEqual(got[1].full_citation, SS_FULL)
        self.assertEqual([r.verdict for r in got], ["pass", "pass"])

    def test_corporate_names_survive(self):
        got = self.run_text("Alpha Corp. v. Beta Holdings, Inc., 321 So. 3d 789, 790 (Fla. 3d DCA 2020)")
        self.assertEqual(got[0].full_citation, "Alpha Corp. v. Beta Holdings, Inc., 321 So. 3d 789, 790 (Fla. 3d DCA 2020)")
        self.assertEqual(got[0].verdict, "pass")

    def test_prologue_names(self):
        got = self.run_text("See In re Estate of Smith, 123 So. 3d 456 (Fla. 2013)")
        self.assertEqual(got[0].full_citation, "In re Estate of Smith, 123 So. 3d 456 (Fla. 2013)")


class SingleCitationParityGuard(DraftCase):
    """Draft-mode changes must not move single-citation verdicts: check_citation is untouched."""

    def test_check_citation_unchanged_on_dressed_prefixes(self):
        for cite, want in (
            ("*Hernandez v. Walmart Stores, Inc.*, 100 So. 3d 200 (Fla. 2012)", ("veto", "caption_mismatch")),
            ("Hernandez v. Walmart Stores, Inc., 100 So. 3d 200 (Fla. 2012)", ("veto", "caption_mismatch")),
            ("Smith v. State, 100 So. 3d 200 (Fla. 2012)", ("pass", "verified")),
            ("100 So. 3d 200 (Fla. 2012)", ("pass", "verified")),
            ("Smith v. State, 100 So. 3d 200, 205 (Fla. 2012)", ("pass", "verified")),
            ("Smith v. State, 100 So. 3d 200, 211 (Fla. 2012)", ("veto", "pin_out_of_bounds")),
        ):
            with self.subTest(cite=cite):
                r = gate1.check_citation(cite, self.db)
                self.assertEqual((r.verdict, r.reason), want)


class CliStdinTests(DraftCase):
    def run_cli(self, draft, extra=()):
        return subprocess.run([PY, str(REPO_ROOT / "pipeline" / "gate1.py"), "--db", str(self.db), "--text", "-", *extra],
                              input=draft.encode("utf-8"), capture_output=True, cwd="/")

    def test_stdin_matches_check_text(self):
        draft = "*Smith v. Jones*, 123 So. 3d 456 (Fla. 2013). *Id.* at 461. Café 中文 Id. at 999."
        p = self.run_cli(draft)
        self.assertEqual(p.returncode, 0, p.stderr)
        want = [r.to_dict() for r in check_text(draft, self.db)]
        self.assertEqual(json.loads(p.stdout), json.loads(json.dumps(want)))

    def test_empty_stdin_is_empty_list(self):
        p = self.run_cli("")
        self.assertEqual((p.returncode, json.loads(p.stdout)), (0, []))

    def test_bad_utf8_is_one_veto(self):
        p = subprocess.run([PY, str(REPO_ROOT / "pipeline" / "gate1.py"), "--db", str(self.db), "--text", "-"],
                           input=b"\xff\xfe\xfa 123 So. 3d 456", capture_output=True, cwd="/")
        out = json.loads(p.stdout)
        self.assertEqual([(r["verdict"], r["reason"]) for r in out], [("veto", "bad_encoding")])

    def test_text_dash_never_puts_the_draft_in_argv(self):
        src = (REPO_ROOT / "backend" / "src" / "verification" / "local_sqlite_gate.ts").read_text(encoding="utf-8")
        self.assertIn("'--text', '-'", src)
        self.assertNotIn("'--text', draft", src)
        self.assertNotIn("'--text=' + draft", src)


if __name__ == "__main__":
    unittest.main()
