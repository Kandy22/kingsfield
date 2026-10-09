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
                self.assertIsNone(failure, failure)


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
