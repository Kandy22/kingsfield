"""Gate 1 before document writes (tabular-docwrite-verify, part B): generate_docx, edit_document, replicate_document.

doc_write_cases.ts runs the REAL chatTools.ts (runToolCalls, and runLLMStream for the tabular / project shapes) once
under backend's tsx. Storage, Supabase, the tracked-changes engine, the model client, CourtListener / MCP and the
Gate 1 verifier are stubbed, so nothing needs Supabase, CourtListener, a model, the Python gate or the network; every
named case becomes a subTest. A second group checks the wiring in chatTools.ts statically: the gate precedes every
write in each tool, no other write path exists, and no caller reaches the writers around the gate.
"""

import json
import re
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TSX = REPO_ROOT / "backend" / "node_modules" / ".bin" / "tsx"
CASES = REPO_ROOT / "pipeline" / "builder_tests" / "doc_write_cases.ts"
SRC = REPO_ROOT / "backend" / "src"
CHAT_TOOLS = SRC / "lib" / "chatTools.ts"

FIXED = "The document was not written because its content contained a citation that could not be verified."

EXPECTED_CASES = {
    "generate_clean_content_is_written_as_before_and_gated_first",
    "generate_a_verified_and_a_conditional_cite_are_still_written",
    "generate_vetoed_cite_in_prose_writes_nothing_and_returns_the_fixed_result",
    "generate_a_cite_only_in_the_title_is_refused",
    "generate_a_cite_only_in_the_derived_filename_is_refused",
    "generate_a_cite_in_a_table_cell_header_or_across_cells_is_refused",
    "generate_a_cite_in_a_heading_or_in_an_unrendered_field_is_refused",
    "generate_pending_and_unknown_status_verdicts_are_refused",
    "generate_every_gate_failure_refuses_and_leaks_no_raw_error",
    "generate_malformed_shapes_are_refused_without_a_gate_call_or_a_write",
    "edit_clean_edits_are_written_as_before_and_gated_first",
    "edit_a_vetoed_replacement_writes_nothing_and_returns_the_fixed_result",
    "edit_a_cite_only_in_the_reason_or_the_context_is_refused",
    "edit_one_vetoed_edit_among_several_refuses_the_whole_call",
    "edit_the_reused_version_path_is_gated_too",
    "edit_a_cite_in_find_alone_does_not_block_a_clean_replacement",
    "edit_every_gate_failure_refuses",
    "edit_malformed_edits_are_refused_without_a_write",
    "edit_two_calls_in_one_batch_are_each_gated_on_their_own",
    "edit_the_users_own_unverifiable_cite_far_from_the_change_does_not_block_it",
    "edit_a_cite_next_to_the_change_is_gated_from_the_document_not_from_the_claimed_context",
    "edit_a_cite_completed_across_a_paragraph_break_is_gated",
    "edit_a_deletion_that_joins_two_halves_of_a_cite_is_gated",
    "edit_two_distant_changes_are_two_windows_with_a_gap_between",
    "edit_a_failing_second_pass_refuses_with_nothing_written",
    "edit_renderings_that_cannot_be_lined_up_are_refused",
    "edit_with_no_visible_text_change_asks_the_gate_only_once",
    "edit_does_not_gate_the_stored_filename_because_no_model_text_reaches_it",
    "editedNeighbourhoods_windows_widen_to_whole_words_and_merge",
    "replicate_clean_filenames_are_written_as_before_and_gated_first",
    "replicate_a_vetoed_new_filename_writes_nothing_and_returns_the_fixed_result",
    "replicate_a_cite_formed_only_in_the_final_filename_is_refused",
    "replicate_every_gate_failure_refuses",
    "replicate_without_a_new_filename_copies_under_the_users_own_name_without_asking_the_gate",
    "replicate_failures_that_are_not_the_gate_are_unchanged",
    "the_three_tools_return_the_identical_refused_result",
    "a_refusal_does_not_stop_the_next_tool_call_in_the_same_batch",
    "tabular_chat_shape_offers_generate_docx_and_the_gate_covers_it",
    "project_chat_shape_runs_all_three_tools_through_the_gate",
    "the_gate_is_serialised_by_a_capped_limiter",
}


class DocWriteCases(unittest.TestCase):
    report = None

    @classmethod
    def setUpClass(cls):
        if not TSX.exists():
            raise unittest.SkipTest(f"tsx missing at {TSX}; report it, do not work around it")
        p = subprocess.run([str(TSX), str(CASES)], capture_output=True, text=True,
                           cwd=str(REPO_ROOT), timeout=120)
        if p.returncode != 0:
            raise AssertionError(f"tsx failed ({p.returncode}):\n{p.stderr[-3000:]}")
        cls.report = json.loads(p.stdout)

    def test_required_cases_ran(self):
        self.assertTrue(EXPECTED_CASES <= set(self.report), EXPECTED_CASES - set(self.report))

    def test_every_case_passes(self):
        for name, failure in sorted(self.report.items()):
            with self.subTest(case=name):
                self.assertIsNone(failure, failure)


def _code(src):
    """Source with comments removed (a comment may name what the code must not do)."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", line) for line in src.splitlines())


WRITE = re.compile(r"\buploadFile\(|\.insert\(|\.update\(|\.upsert\(|\.delete\(|\.rpc\(")


class Wiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = CHAT_TOOLS.read_text(encoding="utf-8")
        cls.code = _code(cls.src)

    def _between(self, start, end):
        i = self.code.index(start)
        return self.code[i:self.code.index(end, i + len(start))]

    def _generate(self):
        return self._between("export async function generateDocx(", "export async function loadCurrentVersionBytes(")

    def _edit(self):
        return self._between("export async function runEditDocument(", "async function readDocumentContent(")

    def _replicate(self):
        return self._between('tc.function.name === "replicate_document"', 'tc.function.name === "generate_docx"')

    def test_the_fixed_message_is_one_string(self):
        self.assertIn(f'"{FIXED}"', self.code)
        self.assertEqual(self.code.count(FIXED), 1)
        self.assertIn("export const DOC_WRITE_REFUSED_MESSAGE", self.code)

    def test_generate_docx_gates_before_anything_else(self):
        gen = self._generate()
        gate = gen.index("await gateDocWriteText(")
        self.assertEqual(gen.count("gateDocWriteText("), 1)
        self.assertLess(gate, gen.index('await import("docx")'))
        for m in WRITE.finditer(gen):
            self.assertLess(gate, m.start(), f"write before the gate: {m.group(0)}")
        self.assertLess(gen.index("return { error: DOC_WRITE_REFUSED_MESSAGE }"), gen.index('await import("docx")'))
        # The stored filename is derived once, by the helper the gate also uses.
        self.assertIn("generatedDocxFilename(title)", gen)
        self.assertEqual(self.code.count("function generatedDocxFilename("), 1)

    def test_generate_docx_dispatch_maps_the_refusal_to_the_fixed_result(self):
        disp = self._between('tc.function.name === "generate_docx"', "if (shouldGroupFindInCase")
        self.assertIn("=== DOC_WRITE_REFUSED_MESSAGE", disp)
        self.assertIn("content: DOC_WRITE_REFUSED_RESULT", disp)
        self.assertLess(disp.index("await generateDocx("), disp.index("content: DOC_WRITE_REFUSED_RESULT"))
        self.assertLess(disp.index("content: DOC_WRITE_REFUSED_RESULT"), disp.index("safeToolResult"))

    def test_edit_document_gates_before_any_read_or_write(self):
        """First pass: the model's strings, before the document is read. Second pass: the text around each change."""
        edit = self._edit()
        gate = edit.index("await gateDocWriteText(")
        self.assertEqual(edit.count("gateDocWriteText("), 2)
        self.assertLess(gate, edit.index(".from("))
        self.assertLess(gate, edit.index("loadActiveVersion("))
        self.assertLess(gate, edit.index("loadCurrentVersionBytes("))
        self.assertLess(gate, edit.index("applyTrackedEdits("))
        self.assertIn("error: DOC_WRITE_REFUSED_MESSAGE", edit[gate: gate + 200])
        # The second pass runs on the engine's output, before the first write.
        second = edit.index("await gateDocWriteText(", gate + 1)
        self.assertGreater(second, edit.index("applyTrackedEdits("))
        for m in WRITE.finditer(edit):
            self.assertLess(second, m.start(), f"write before the second gate pass: {m.group(0)}")
        self.assertIn("editedNeighbourhoods(", edit[:second])
        self.assertIn("error: DOC_WRITE_REFUSED_MESSAGE", edit[second: second + 200])

    def test_edit_second_pass_gates_neighbourhoods_not_the_whole_document_or_claimed_context(self):
        edit = self._edit()
        # The old second pass gated the whole rendered document (and the filename).
        self.assertNotRegex(edit, r"gateDocWriteText\(\s*\[\s*editedText")
        self.assertNotIn("versionFilename]", edit)
        second = edit.index("await gateDocWriteText(", edit.index("applyTrackedEdits("))
        window = edit[second - 400: second + 200]
        self.assertIn("neighbourhoods", window)
        # The model-claimed contextBefore / contextAfter on the applied changes are not what is gated.
        self.assertNotIn("contextBefore", edit[:second])
        self.assertNotIn("contextAfter", edit[:second])

    def test_edit_gate_covers_replacement_reason_and_context_but_not_find(self):
        parts = self._between("function editDocumentGateParts(", "function buildReplicaFilenames(")
        self.assertIn("find: _find", parts)
        self.assertIn("collectModelStrings(written, parts)", parts)
        self.assertIn("context_before, replace, context_after", parts)

    def test_replicate_gates_before_any_read_or_write(self):
        rep = self._replicate()
        gate = rep.index("await gateDocWriteText(")
        self.assertEqual(rep.count("gateDocWriteText("), 1)
        self.assertIn("requestedFilename !== null", rep[:gate])
        self.assertLess(gate, rep.index("loadActiveVersion("))
        self.assertLess(gate, rep.index("downloadFile("))
        for m in WRITE.finditer(rep):
            self.assertLess(gate, m.start(), f"write before the gate: {m.group(0)}")
        self.assertIn("buildReplicaFilenames(", rep[:gate + 300])
        self.assertIn("fail(DOC_WRITE_REFUSED_MESSAGE)", rep)
        self.assertEqual(rep.count("buildReplicaFilenames("), 2, "one name builder, used by the gate and the write path")

    def test_there_is_no_other_write_in_chat_tools(self):
        """Every storage / table write in the module is inside one of the three gated tools."""
        rest = self.code
        for region in (self._generate(), self._edit(), self._replicate()):
            rest = rest.replace(region, "")
        left = [m.group(0) for m in WRITE.finditer(rest)]
        self.assertEqual(left, [], f"a write outside the three gated tools: {left}")
        # The writes that are in the gated regions are exactly the ones the report lists.
        self.assertEqual(len(WRITE.findall(self._generate())), 4)
        self.assertEqual(len(WRITE.findall(self._edit())), 6)
        self.assertEqual(len(WRITE.findall(self._replicate())), 5)

    def test_the_gate_reuses_the_guard_and_adds_no_parser(self):
        helper = self._between("async function gateDocWriteText(", "function generatedDocxFilename(")
        self.assertIn("gateCellContent(", helper)
        self.assertIn("verifyDraftForSse(", helper)
        self.assertIn("limitDocGate(", helper)
        self.assertIn("() => unverifiableCell()", helper)
        self.assertNotRegex(helper, r"\bverifyDraft\(")
        self.assertNotIn("eyecite", self.code.lower())
        self.assertRegex(self.code, r"const DOC_GATE_CONCURRENCY = [1-4];")
        self.assertRegex(self.code, r"createLimiter\(DOC_GATE_CONCURRENCY,\s*\{\s*timeoutMs: DOC_GATE_TIMEOUT_MS,?\s*\}\)")
        # Raw failures reach only the server log.
        self.assertIn("console.error(\"[doc-write-gate] error\", safeErrorLog(err))", helper)

    def test_callers_reach_the_writers_only_through_the_gated_tools(self):
        for name in ("chat.ts", "projectChat.ts", "tabular.ts"):
            code = _code((SRC / "routes" / name).read_text(encoding="utf-8"))
            self.assertIn("runLLMStream", code, name)
            for banned in ("generateDocx", "runEditDocument", "uploadFile", "DOC_WRITE"):
                self.assertNotIn(banned, code, f"{name} must not write documents itself ({banned})")
        # Only runToolCalls calls the two exported writers.
        for path in SRC.rglob("*.ts"):
            if path == CHAT_TOOLS:
                continue
            text = _code(path.read_text(encoding="utf-8"))
            for banned in ("generateDocx(", "runEditDocument("):
                self.assertNotIn(banned, text, f"{path} calls {banned}")
        self.assertEqual(len(re.findall(r"await generateDocx\(", self.code)), 1)
        self.assertEqual(len(re.findall(r"await runEditDocument\(", self.code)), 1)

    def test_tabular_chat_hands_the_same_tools_to_the_same_stream(self):
        """tabular.ts adds TABULAR_TOOLS on top of TOOLS (generate_docx included); the writers are the shared ones."""
        code = self.code
        i = code.index("const baseTools = [...TOOLS, ...researchTools, ...WORKFLOW_TOOLS];")
        self.assertIn("extraTools", code[i: i + 400])
        tab = _code((SRC / "routes" / "tabular.ts").read_text(encoding="utf-8"))
        self.assertIn("extraTools: TABULAR_TOOLS", tab)
        tools = self._between("export const TABULAR_TOOLS = [", "export const WORKFLOW_TOOLS")
        self.assertNotIn("generate_docx", tools)
        self.assertNotIn("edit_document", tools)


if __name__ == "__main__":
    unittest.main()
