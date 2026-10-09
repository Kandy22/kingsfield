"""Adversary pass for tabular-docwrite-verify, part B: Gate 1 before document writes.

Targets generate_docx, edit_document and replicate_document in backend/src/lib/chatTools.ts.

Three groups:

  DocWriteBypassCases   docwrite_bypass_cases.ts under backend's tsx: the REAL chatTools.ts, the real tracked-changes
                        engine, the real Gate 1 (pipeline/gate1.py over the fixture database) and a read-back oracle.
                        A document that is written and then reads back with a vetoed citation is a leak, whatever the
                        tool arguments looked like. No Supabase, CourtListener, model or network.
  GatePremises          in-process checks on the real gate that the cases above stand on (what the gate calls a
                        citation, what it vetoes after the renderer's transformations), and the upper-case verdict.
  CallerSeams           static: nothing reaches runToolCalls / runLLMStream except through the buffering writer and
                        finalizeHeldOutput.

Why the cases fail when the gate is removed (the tool code cannot be mutated from here): every "refused" case asserts
the fixed refusal result AND zero storage objects AND zero non-select queries on every table, and the clean controls
assert the gate ran first (timeline[0] == "verify"). With gateDocWriteText() bypassed or called after the writes, the
refusal cases would see an upload and three table writes, and the read-back oracle would see the vetoed cite.
"""

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate1_fixture as fx  # noqa: E402

REPO_ROOT = fx.REPO
TSX = REPO_ROOT / "backend" / "node_modules" / ".bin" / "tsx"
CASES = REPO_ROOT / "pipeline" / "tests" / "docwrite_bypass_cases.ts"
SRC = REPO_ROOT / "backend" / "src"
CHAT_TOOLS = SRC / "lib" / "chatTools.ts"

EXPECTED_CASES = {
    "real_control_valid_cite_is_written_and_reads_back_clean",
    "real_fabricated_cite_in_prose_is_refused",
    "real_upper_case_fabricated_cite_is_refused",
    "real_missing_database_fails_closed_for_a_valid_cite",
    "real_cite_split_heading_then_content_is_refused",
    "real_cite_split_heading_then_content_in_unnatural_key_order_is_refused",
    "real_cite_split_table_then_content_in_unnatural_key_order_is_refused",
    "real_cite_split_down_a_table_column_is_refused",
    "edit_control_clean_edit_is_written_and_reads_back_clean",
    "edit_fabricated_replacement_is_refused",
    "edit_changing_one_token_of_the_users_real_cite_is_refused",
    "edit_changing_the_court_of_the_users_real_cite_is_refused",
    "edit_adding_an_out_of_range_pin_to_the_users_real_cite_is_refused",
    "edit_filling_a_citation_template_in_two_calls_never_stores_a_vetoed_cite",
    "seam_model_text_echoed_in_events_of_refused_and_failed_doc_tools_never_reaches_the_client",
    "find_text_is_never_persisted_anywhere",
    "malformed_generate_args_write_nothing_and_echo_nothing",
    "generate_everything_rendered_was_shown_to_the_gate",
    "mcp_connector_tool_arguments_with_a_vetoed_cite_are_not_sent_out",
    # main-verify round
    "edit_runs_the_matcher_cannot_see_complete_a_cite_on_the_page_is_refused_or_reads_back_clean",
    "edit_tab_or_break_between_the_users_runs_does_not_hide_a_completed_cite",
    "edit_inserted_tail_of_the_users_cite_behind_any_separator_is_refused",
    "edit_two_blanks_filled_in_one_call_never_store_a_vetoed_cite",
    "edit_with_misleading_context_still_gates_the_real_neighbourhood",
    "edit_a_cite_in_reason_or_context_strings_is_refused",
    "edit_a_deletion_that_fuses_a_cite_is_refused_or_reads_back_clean",
    "replicate_control_a_clean_filename_writes_the_copy_after_the_gate",
    "replicate_filename_forms_of_a_fabricated_cite_are_refused",
    "mcp_connector_arguments_with_a_cite_split_by_an_escaped_newline_or_tab_are_not_sent_out",
    "mcp_connector_control_clean_arguments_are_sent",
}


class DocWriteBypassCases(unittest.TestCase):
    report = None

    @classmethod
    def setUpClass(cls):
        # A missing tsx must fail, not skip: a skipped adversary suite is a silent pass.
        if not TSX.exists():
            raise AssertionError("tsx is missing at %s; the document-write bypass cases cannot run" % TSX)
        env = dict(os.environ)
        env["DOCWRITE_DB"] = str(fx.get_fixture().db)
        p = subprocess.run([str(TSX), str(CASES)], capture_output=True, text=True, env=env,
                           cwd=str(REPO_ROOT), timeout=170)
        if p.returncode != 0:
            raise AssertionError("tsx failed (%s):\n%s" % (p.returncode, p.stderr[-3000:]))
        marker = "DOCWRITE_REPORT="
        i = p.stdout.rfind(marker)
        if i < 0:
            raise AssertionError("no report from the harness:\nstdout tail: %s\nstderr tail: %s"
                                 % (p.stdout[-1500:], p.stderr[-1500:]))
        cls.report = json.loads(p.stdout[i + len(marker):].strip().splitlines()[0])

    def test_required_cases_ran(self):
        missing = EXPECTED_CASES - set(self.report)
        self.assertFalse(missing, "cases missing from the harness report: %s" % sorted(missing))

    def test_every_case_passes(self):
        for name, failure in sorted(self.report.items()):
            with self.subTest(case=name):
                if failure is not None:
                    self.fail(str(failure)[:450])


# ---------------------------------------------------------------------------
# In-process premises on the real gate
# ---------------------------------------------------------------------------


class GatePremises(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = fx.get_fixture().db

    def results(self, text):
        return fx.py_check_text(text, self.db)

    def assertVetoed(self, text, why):
        rs = self.results(text)
        if not any(r.verdict == "veto" for r in rs):
            self.fail("LEAK (%s): no veto for %r -> %r" % (why, text, [(r.verdict, r.reason) for r in rs]))

    # -- a cite broken across lines or parts is still one cite to the gate (the doc-write gate joins parts with a blank line)

    def test_cite_split_by_line_breaks_is_still_a_cite(self):
        for sep in ("\n", "\n\n", " \n ", "\r\n\r\n"):
            with self.subTest(sep=repr(sep)):
                self.assertVetoed("Doe v. Roe, 999 So." + sep + "3d 999 (Fla. 2015).", "split cite")

    # -- the premises of the edit cases: the gate vetoes each mutation of a real cite when it sees the whole paragraph

    def test_the_real_cite_in_the_edit_source_passes_and_each_mutation_is_vetoed(self):
        base = "See Smith v. State, 100 So. 3d 200 (Fla. 2012)."
        rs = self.results(base)
        self.assertTrue(rs and all(r.verdict == "pass" for r in rs), [(r.verdict, r.reason) for r in rs])
        for label, text in (
            ("volume", "See Smith v. State, 999 So. 3d 200 (Fla. 2012)."),
            ("court", "See Smith v. State, 100 So. 3d 200 (Fla. 1st DCA 2012)."),
            ("pin", "See Smith v. State, 100 So. 3d 200, 999 (Fla. 2012)."),
            ("caption", "See Doe v. Roe, 100 So. 3d 200 (Fla. 2012)."),
            ("template filled", "See Doe v. Roe, 999 So. 3d 999 (Fla. 2015)."),
        ):
            with self.subTest(mutation=label):
                self.assertVetoed(text, "mutation of a real cite: " + label)

    # -- renderer forms: upper-case (titles are rendered upper-case), stored-filename form (periods stripped),
    #    and the usual obfuscations. Every fabricated variant must produce at least one veto.

    FABRICATED_FORMS = (
        ("upper case", "DOE V. ROE, 999 SO. 3D 999 (FLA. 2015)"),
        ("lower case", "doe v. roe, 999 so. 3d 999 (fla. 2015)"),
        ("mixed case series", "Doe v. Roe, 999 So. 3D 999 (Fla. 2015)"),
        ("upper case reporter only", "Doe v. Roe, 999 SO. 3d 999 (Fla. 2015)"),
        ("period-less (stored filename form)", "Doe v Roe 999 So 3d 999 Fla 2015.docx"),
        ("period-less upper", "DOE V ROE 999 SO 3D 999 FLA 2015"),
        ("zero-width space", "Doe v. Roe, 999 So.​ 3d 999 (Fla. 2015)"),
        ("zero-width joiner in the volume", "Doe v. Roe, 9‍99 So. 3d 999 (Fla. 2015)"),
        ("full-width digits and letters", "Doe v. Roe, ９９９ Ｓｏ． ３ｄ ９９９ (Fla. 2015)"),
        ("cyrillic o", "Doe v. Roe, 999 Sо. 3d 999 (Fla. 2015)"),
        ("OCR zero for o", "Doe v. Roe, 999 S0. 3d 999 (Fla. 2015)"),
        ("no court parenthetical", "Doe v. Roe, 999 So. 3d 999"),
        ("soft hyphen", "Doe v. Roe, 999 So.­ 3d 999 (Fla. 2015)"),
        ("html entity period", "Doe v. Roe, 999 So&#46; 3d 999 (Fla. 2015)"),
        ("markdown emphasis", "Doe v. Roe, 999 *So.* 3d 999 (Fla. 2015)"),
    )

    def test_fabricated_florida_cites_in_renderer_and_obfuscated_forms_are_vetoed(self):
        for label, text in self.FABRICATED_FORMS:
            with self.subTest(form=label):
                self.assertVetoed(text, label)

    # -- verdict on the upper-case question: a real Florida cite, upper-cased the way titles and level-1 headings are
    #    rendered, must never fall through to CourtListener (which would route a Florida key around the local database).

    REAL_FORMS = (
        "SMITH V. STATE, 100 SO. 3D 200 (FLA. 2012)",
        "Smith v. State, 100 SO. 3D 200 (Fla. 2012)",
        "Smith v State 100 So 3d 200 Fla 2012.docx",
        "SMITH V STATE 100 SO 3D 200 FLA 2012",
    )

    def test_upper_case_and_stored_filename_forms_of_a_real_florida_cite_never_fall_through(self):
        for text in self.REAL_FORMS:
            with self.subTest(text=text):
                rs = self.results(text)
                bad = [(r.verdict, r.reason) for r in rs if r.verdict == "fall_through"]
                self.assertFalse(bad, "a Florida key fell through to CourtListener: %r -> %r" % (text, bad))
                self.assertTrue(rs, "the gate saw no citation at all in %r" % text)


# ---------------------------------------------------------------------------
# JSON-encoded text: analytics extraction, GET /analytics and MCP arguments are gated as JSON.stringify output, where a
# newline or tab inside a string is a literal backslash sequence. The reader of the value sees the real character.
# ---------------------------------------------------------------------------


class JsonEncodedText(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = fx.get_fixture().db

    def assertVetoed(self, text, why):
        rs = fx.py_check_text(text, self.db)
        if not any(r.verdict == "veto" for r in rs):
            self.fail("LEAK (%s): no veto for %r -> %r" % (why, text, [(r.verdict, r.reason) for r in rs]))

    def test_a_cite_split_by_a_json_escaped_whitespace_is_still_a_cite(self):
        for sep in ("\n", "\t", "\r\n", "\n\n", " \n "):
            value = "Doe v. Roe, 999 So." + sep + "3d 999 (Fla. 2015)."
            for label, blob in (
                ("object value", json.dumps({"claim": value}, ensure_ascii=False)),
                ("nested in a list", json.dumps({"allegations": [{"claim": "x", "authorities": [value]}]}, ensure_ascii=False)),
                ("double encoded", json.dumps({"body": json.dumps({"claim": value}, ensure_ascii=False)}, ensure_ascii=False)),
            ):
                with self.subTest(sep=repr(sep), shape=label):
                    self.assertVetoed(blob, "JSON-escaped whitespace inside a cite")

    def test_raw_control_characters_inside_a_cite_are_vetoed_premise(self):
        # The premise of test_case_extraction_gate: decoded, a control character glues the cite and the gate vetoes it.
        for ch in ("\x08", "\x0b", "\x1f"):
            with self.subTest(char=repr(ch)):
                self.assertVetoed("Doe v. Roe, 999%sSo. 3d 999 (Fla. 2015)." % ch, "raw control character")

    def test_escape_spellings_that_decode_to_a_separator_do_not_hide_a_cite(self):
        # Text that is itself JSON, or source code, and is decoded once more downstream.
        spellings = {
            "u000a": "\\u000a", "u000A": "\\u000A", "x0a": "\\x0a", "u000d u000a": "\\u000d\\u000a", "u0009": "\\u0009",
            "u0020": "\\u0020", "x20": "\\x20", "two backslashes n": "\\\\n", "three backslashes n": "\\\\\\n",
            "escaped slash then n": "\\/\\n", "slash u2028": "\\u2028",
        }
        leaks = []
        for label, sep in spellings.items():
            for template in ("Doe v. Roe, 999%sSo. 3d 999 (Fla. 2015).", "Doe v. Roe, 999 So.%s3d 999 (Fla. 2015).",
                             "Doe v. Roe, 999 So. 3d%s999 (Fla. 2015)."):
                text = template % sep
                if not any(r.verdict == "veto" for r in fx.py_check_text(text, self.db)):
                    leaks.append("%s: %r" % (label, text))
        if leaks:
            self.fail("%d spellings read as no citation at all; first: %s" % (len(leaks), "; ".join(leaks[:4])))

    def test_escapes_inside_the_court_parenthetical_or_pin_never_turn_a_bad_cite_into_a_pass(self):
        smith = "Smith v. State, 100 So. 3d 200"
        bad = []
        for sep in ("\\n", "\\b", "\\u0008", "\\u000a", "\\x0a", "\\t"):
            for text in (
                "%s, 999%s(Fla. 2012)" % (smith, sep),          # out-of-range pin after an escape
                "%s,%s999 (Fla. 2012)" % (smith, sep),
                "%s, 21%s0 (Fla. 2012)" % (smith, sep),         # digits split by an escape
                "%s (Fla.%s1st DCA 2012)" % (smith, sep),       # wrong court level after an escape
                "Doe v. Roe, 999 So. 3d 999 (Fla.%s2015)" % sep,
            ):
                if any(r.verdict == "pass" for r in fx.py_check_text(text, self.db)):
                    bad.append(text)
        if bad:
            self.fail("%d passed; first: %r" % (len(bad), bad[0]))

    def test_the_escape_handling_adds_no_false_veto_to_real_cites(self):
        smith = "Smith v. State, 100 So. 3d 200 (Fla. 2012)"
        for text in (
            "See\n" + smith + ".", json.dumps({"c": "See\n" + smith + "."}), "See\\n" + smith + ".",
            "Smith v. State,\\n100 So. 3d 200 (Fla. 2012).", json.dumps({"a": "x", "b": "Compare\t" + smith}),
            "Smith v. State, 100 So. 3d 200 \\(Fla. 2012\\).", "path C:\\new\\table has no citation",
        ):
            with self.subTest(text=text):
                rs = self.results(text) if hasattr(self, "results") else fx.py_check_text(text, self.db)
                self.assertFalse(any(r.verdict == "veto" and "Smith" in text and "C:" not in text for r in rs),
                                 [(r.verdict, r.reason) for r in rs])

    def test_a_cite_split_before_the_page_or_after_the_volume_by_a_json_escaped_newline(self):
        for value in ("Doe v. Roe, 999 So. 3d\n999 (Fla. 2015).", "Doe v. Roe, 999\nSo. 3d 999 (Fla. 2015)."):
            with self.subTest(value=value):
                self.assertVetoed(json.dumps({"claim": value}, ensure_ascii=False), "JSON-escaped newline inside a cite")


# ---------------------------------------------------------------------------
# Static: callers
# ---------------------------------------------------------------------------


def _code(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", line) for line in src.splitlines())


def _ts_files():
    for path in SRC.rglob("*.ts"):
        parts = set(path.parts)
        if "node_modules" in parts or "__tests__" in parts or ".test." in path.name or ".spec." in path.name:
            continue
        yield path


class CallerSeams(unittest.TestCase):
    def test_runToolCalls_is_called_only_inside_chatTools(self):
        offenders = [str(p) for p in _ts_files()
                     if p != CHAT_TOOLS and "runToolCalls(" in _code(p.read_text(encoding="utf-8"))]
        self.assertEqual(offenders, [], "a caller reaches the document writers around runLLMStream: %s" % offenders)

    def test_every_runLLMStream_caller_buffers_and_finalizes(self):
        offenders = []
        callers = []
        for p in _ts_files():
            if p == CHAT_TOOLS:
                continue
            code = _code(p.read_text(encoding="utf-8"))
            if "runLLMStream(" not in code:
                continue
            callers.append(p.name)
            if "createBufferingSseWriter(" not in code or "finalizeHeldOutput(" not in code:
                offenders.append(str(p))
        self.assertEqual(offenders, [], "a runLLMStream caller does not hold output behind finalizeHeldOutput: %s" % offenders)
        # The three known routes still exist and are the callers (a vanished caller must be noticed, not ignored).
        for name in ("chat.ts", "projectChat.ts", "tabular.ts"):
            self.assertIn(name, callers)

    def test_the_document_writers_are_not_exported_to_anything_but_the_dispatcher(self):
        offenders = []
        for p in _ts_files():
            if p == CHAT_TOOLS:
                continue
            code = _code(p.read_text(encoding="utf-8"))
            for banned in ("generateDocx(", "runEditDocument("):
                if banned in code:
                    offenders.append("%s calls %s" % (p, banned))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
