"""Gate 1 over POST /crew/chat, POST /council and the stored-session GETs (chat-route verification, findings 1-3).

route_gate_cases.ts runs finalizeCrewReply / gateCouncilOutput once under backend's tsx with stub verifiers
(no real gate, no network, no Supabase) and each named case becomes a subTest. A second group checks the
route wiring in routes/index.ts statically, since the routes cannot be run without Supabase.
"""

import json
import re
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TSX = REPO_ROOT / "backend" / "node_modules" / ".bin" / "tsx"
CASES = REPO_ROOT / "pipeline" / "builder_tests" / "route_gate_cases.ts"
INDEX = REPO_ROOT / "backend" / "src" / "routes" / "index.ts"

EXPECTED_CASES = {
    "crew_clean_reply_passes_unchanged_with_citations",
    "crew_streams_in_80_char_chunks_and_a_citations_event_is_always_sent",
    "crew_veto_in_the_reply_withholds_with_the_veto_message_and_no_citations",
    "crew_veto_only_in_a_relevance_note_withholds",
    "crew_veto_only_in_an_authority_citation_withholds",
    "crew_pending_verdict_counts_as_a_veto",
    "crew_short_form_in_a_relevance_note_is_checked_alone",
    "crew_gate_error_withholds_with_the_generic_message",
    "crew_raw_gate_error_goes_to_the_logger_not_the_client",
    "crew_verification_record_is_client_safe",
    "crew_chip_without_a_matching_verdict_is_dropped_from_a_clean_reply",
    "crew_malformed_input_withholds",
    "council_clean_output_passes_unchanged_and_in_the_frontend_shape",
    "council_a_veto_in_any_one_field_withholds_the_whole_output",
    "council_a_short_form_field_is_checked_alone",
    "council_pending_verdict_withholds",
    "council_gate_error_withholds_with_the_generic_message_and_leaks_nothing",
    "council_withheld_shape_is_five_advisors_five_reviewers_and_one_fixed_message",
    "council_malformed_output_withholds_without_calling_the_gate",
    "council_passed_output_has_only_the_known_keys",
    "council_empty_strings_do_not_throw",
}


class RouteGateCases(unittest.TestCase):
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
    """Source with // line comments and /* */ blocks removed (a comment may name what the code must not do)."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(re.sub(r"(?<![:'\"`])//.*$", "", l) for l in src.splitlines())


def _handler(code, start_pat):
    m = re.search(start_pat, code)
    assert m, start_pat
    rest = code[m.start():]
    ends = [e.start() + 20 for e in re.finditer(r"\n  (?:r\.(?:post|get|put|delete|use)\(|// ──)", rest[20:])]
    return rest[: ends[0]] if ends else rest


class RouteWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = INDEX.read_text(encoding="utf-8")
        cls.code = _code(cls.src)
        cls.crew = _handler(cls.code, r"r\.post\(\s*'/crew/chat'")
        cls.council = _handler(cls.code, r"r\.post\(\s*'/council'\s*,")
        cls.gets = {
            "json": _handler(cls.code, r"r\.get\(\s*'/council/:id'\s*,"),
            "html": _handler(cls.code, r"r\.get\(\s*'/council/:id/html'"),
            "markdown": _handler(cls.code, r"r\.get\(\s*'/council/:id/markdown'"),
        }

    # ----- /crew/chat -----

    def test_crew_gates_before_anything_model_written_is_sent(self):
        h = self.crew
        run = h.index("await runCrew(")
        fallback = h.index("await completeText(")
        gate = h.index("await finalizeCrewReply(")
        self.assertLess(run, fallback)
        self.assertLess(fallback, gate)
        # A literal Gate 1 call inside the handler, with the sent verification record after it.
        self.assertIn("verifyDraftForSse(", h)
        self.assertRegex(h[gate:], r"hasVetoes")
        # Nothing is written between the crew run and the gate, and the gate sees the chips too.
        between = h[run:gate]
        self.assertNotRegex(between, r"\bsse\(|res\.(?:write|json|send|end|status)\(|\bwrite\(")
        self.assertRegex(between, r"authorities")
        self.assertIn("authorities,", h[gate:gate + 200])
        self.assertIn("reply,", h[gate:gate + 200])
        # Everything sent comes from the finalized lines, after the gate.
        sends = [m.start() for m in re.finditer(r"for \(const line of finalized\.linesToSend\) write\(line\);", h)]
        self.assertEqual(len(sends), 1)
        self.assertLess(gate, sends[0])
        # No model call after the gate.
        after = h[gate:]
        for banned in ("runCrew(", "completeText(", "runLLMStream(", "runLLMCouncil("):
            self.assertNotIn(banned, after)

    def test_crew_sends_no_ungated_text_and_no_raw_error(self):
        h = self.crew
        self.assertNotRegex(h, r"\bsse\(")
        self.assertNotIn("content_delta", h, "chunking lives in finalizeCrewReply")
        self.assertNotIn("relevanceNote", h.replace("relevanceNote: string", ""), "chips are built inside the gate helper")
        self.assertNotRegex(h, r"err\??\.message")
        self.assertNotIn("error: err", h)
        # Catch: fixed error event then [DONE] (the helper's lines), raw error only through safeErrorLog.
        catch = h[h.rindex("} catch (err) {"): h.index("} finally {")]
        # A client that is gone gets nothing ('aborted' has no SSE lines); otherwise the fixed error event.
        self.assertIn("failedReplyRecord(gone ? 'aborted' : 'failed').sseLines", catch)
        self.assertIn("safeErrorLog(err)", catch)
        for m in re.finditer(r"\berr\b", catch):
            before = catch[: m.start()]
            self.assertTrue(before.endswith("catch (") or before.endswith("safeErrorLog("), catch[m.start() - 30: m.end() + 5])

    def test_crew_keepalive_runs_while_the_crew_works_and_stops_everywhere(self):
        h = self.crew
        self.assertEqual(h.count("startSseKeepalive(write)"), 1)
        self.assertLess(h.index("startSseKeepalive(write)"), h.index("await runCrew("))
        close = re.search(r"res\.on\('close', \(\) => keepalive\.stop\(\)\);", h)
        self.assertIsNotNone(close)
        gate = h.index("await finalizeCrewReply(")
        stop_before_send = h.index("keepalive.stop();", gate)
        self.assertLess(stop_before_send, h.index("write(line)", gate))
        catch = h[h.rindex("} catch (err) {"): h.index("} finally {")]
        self.assertIn("keepalive.stop();", catch)
        self.assertIn("keepalive.stop();", h[h.index("} finally {"):])
        self.assertIn("res.end()", h[h.index("} finally {"):])

    def test_crew_mock_goes_through_the_same_gate(self):
        h = self.crew
        mock = h[h.index("if (MOCK_ENABLED) {"): h.index("} else {")]
        self.assertIn("MOCK_CREW.reply", mock)
        self.assertNotRegex(mock, r"write\(|res\.")
        self.assertEqual(h.count("await finalizeCrewReply("), 1)

    # ----- /council -----

    def test_council_runs_without_supabase_or_project_id_and_saves_after_the_gate(self):
        h = self.council
        m = re.search(r"await runLLMCouncil\((.*?)\n\s*\)\s*;", h, re.S)
        self.assertIsNotNone(m, "runLLMCouncil call not found")
        args = m.group(1)
        self.assertNotIn("supabase", args)
        self.assertNotIn("projectId", args)
        self.assertIn("rawQuestion", args)
        gate = h.index("await gateCouncilOutput(")
        insert = h.index(".from('llm_council_sessions').insert(")
        send = h.index("res.json({ ...gated.output")
        self.assertLess(h.index("runLLMCouncil("), gate)
        self.assertLess(gate, insert)
        self.assertLess(insert, send)
        # The saved row is what is sent: built from gated.output only, same columns as persistSession.
        row = h[insert: h.index("});", insert)]
        for col, val in (("project_id", "projectId"), ("framed_question", "gated.output.framedQuestion"),
                         ("advisors", "gated.output.advisors"), ("reviewers", "gated.output.reviewers"),
                         ("chairman_verdict", "gated.output.chairmanVerdict")):
            self.assertRegex(row, rf"{col}: {re.escape(val)}")
        self.assertNotRegex(row, r"\bout\b")
        self.assertIn("created_at", row)

    def test_council_gates_before_sending_and_sends_the_record(self):
        h = self.council
        self.assertIn("verifyDraftForSse(", h)
        gate = h.index("await gateCouncilOutput(")
        self.assertRegex(h[gate:], r"hasVetoes")
        self.assertIn("verification: gated.verification", h)
        self.assertIn("withheld: gated.withheld", h)
        # Only the gated object is ever sent.
        self.assertNotRegex(h, r"res\.json\((?:out|MOCK_COUNCIL)\)")
        self.assertEqual(len(re.findall(r"res\.json\(\{ \.\.\.gated\.output", h)), 1)
        for i in [m.start() for m in re.finditer(r"res\.(?:json|send)\(", h)]:
            if h[i:].startswith("res.json({ ...gated.output") or "status(400)" in h[max(0, i - 30): i] \
                    or "status(500)" in h[max(0, i - 30): i]:
                continue
            self.fail("unexpected response: " + h[i:i + 60])

    def test_council_error_paths_send_no_raw_error(self):
        h = self.council
        self.assertNotRegex(h, r"err\??\.message")
        self.assertNotIn("console.error('[council] error', err)", h)
        self.assertIn("safeErrorLog(err)", h)
        self.assertIn("res.status(500).json({ error: GENERIC_ERROR_MESSAGE })", h)

    def test_council_mock_goes_through_the_same_gate(self):
        h = self.council
        self.assertIn("MOCK_COUNCIL", h)
        self.assertEqual(h.count("await gateCouncilOutput("), 1)
        self.assertLess(h.index("MOCK_COUNCIL"), h.index("await gateCouncilOutput("))
        self.assertIn("!MOCK_ENABLED &&\n        typeof projectId === 'string'", h, "the mock session is not saved")
        # Saved only under a project the caller owns.
        self.assertLess(h.index("await ownedProject("), h.index(".from('llm_council_sessions').insert("))

    # ----- stored sessions -----

    def test_stored_session_gets_gate_before_sending(self):
        helper = _handler(self.code, r"const gateStoredCouncilRow")
        self.assertIn("gateCouncilOutput(", helper)
        self.assertIn("verifyDraftForSse(", helper)
        for name, h in self.gets.items():
            with self.subTest(route=name):
                gate = h.index("await gateStoredCouncilRow(data)")
                send = re.search(r"res(?:\.type\([^)]*\))?\.(?:json|send)\(", h[gate:])
                self.assertIsNotNone(send)
                # The only 200 response is built from the gated output.
                self.assertIn("gated.output", h[gate:])
                self.assertNotRegex(h, r"res\.json\(data\)")
                self.assertNotRegex(h, r"data\.(?:framed_question|advisors|reviewers|chairman_verdict)")
                self.assertNotIn("select('*')", h)
                self.assertIn("COUNCIL_ROW_COLUMNS", h)

    def test_no_ungated_council_text_anywhere_in_the_file(self):
        self.assertEqual(len(re.findall(r"\brunLLMCouncil\(", self.code)), 1)
        self.assertEqual(len(re.findall(r"\brunCrew\(", self.code)), 1)
        self.assertNotIn("select('*')", self.code.split("r.post('/council'")[1].split("/research/case-law")[0])


if __name__ == "__main__":
    unittest.main()
