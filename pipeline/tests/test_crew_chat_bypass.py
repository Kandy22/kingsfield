"""POST /api/crew/chat: ownership of attached documents and behaviour after a client disconnect (adversary, main-verify).

Behavioral: crew_chat_cases.ts drives the REAL handler from buildRoutes() (backend/src/routes/index.ts) with fake req/res,
a Supabase fake that honours eq / in filters, and stubs for the crew, document versions and storage.

  * documentIds: the route loads the documents named in the request body with the service-role client. A document that
    belongs to another user must never be read for the requester (class c: ownership).
  * disconnect (class f): once the client has gone, nothing is written, the fallback model call is skipped, and the
    abort reaches runCrew.
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate1_fixture as fx  # noqa: E402

REPO = fx.REPO
TSX = REPO / "backend" / "node_modules" / ".bin" / "tsx"
CASES_TS = Path(__file__).resolve().parent / "crew_chat_cases.ts"


class CrewChatCases(unittest.TestCase):
    report = None

    @classmethod
    def setUpClass(cls):
        if not TSX.exists():
            raise AssertionError("tsx missing at %s; the crew chat cases cannot run (report it, do not skip it)" % TSX)
        env = dict(os.environ)
        env["KINGSFIELD_FLORIDA_DB"] = str(fx.get_fixture().db)
        env["MOCK_LLM"] = "false"
        proc = subprocess.run([str(TSX), str(CASES_TS)], capture_output=True, text=True, env=env, cwd=str(REPO), timeout=150)
        if proc.returncode != 0:
            raise AssertionError("tsx failed (%d):\n%s" % (proc.returncode, proc.stderr[-2500:]))
        lines = [l for l in proc.stdout.splitlines() if l.strip()]
        cls.report = json.loads(lines[-1])["results"]

    def _case(self, name):
        self.assertIn(name, self.report, "the harness did not run %s (ran: %s)" % (name, sorted(self.report)))
        if self.report[name] is not None:
            self.fail(str(self.report[name])[:700])

    def test_document_ids_of_another_user_are_never_read(self):
        self._case("crew_chat_document_ids_of_another_user_are_never_read")

    def test_the_owner_can_still_attach_their_own_document(self):
        self._case("crew_chat_the_owner_can_still_attach_their_own_document")

    def test_nothing_is_sent_after_the_client_disconnects_and_the_fallback_model_call_is_skipped(self):
        self._case("crew_chat_nothing_is_sent_after_the_client_disconnects_and_the_fallback_model_call_is_skipped")

    def test_a_throwing_crew_after_a_disconnect_writes_nothing(self):
        self._case("crew_chat_a_throwing_crew_after_disconnect_writes_nothing")

    def test_council_does_not_save_a_session_under_a_project_the_caller_does_not_own(self):
        self._case("council_does_not_save_a_session_under_a_project_the_caller_does_not_own")

    def test_a_cite_in_an_object_key_of_a_stored_analytics_row_is_withheld_on_read(self):
        self._case("analytics_a_cite_in_an_object_key_of_a_stored_row_is_withheld_on_read")

    def test_a_stored_analytics_row_with_a_cite_split_by_a_newline_is_withheld_on_read(self):
        # GET /analytics gates JSON.stringify(row): a newline inside a string is a literal backslash-n there.
        self._case("analytics_a_stored_row_with_a_cite_split_by_a_newline_is_withheld_on_read")


class OpenItems(unittest.TestCase):
    """Model text with no Gate 1 that is outside the main-verify diff. Body intact: un-skip when fixed."""

    @unittest.skip(
        "OPEN ITEM (found by the adversary during main-verify; pre-existing, outside the diff since 540e748): the docket watcher "
        "(backend/src/services/docket-watcher/{deadline-mapper,reporter}.ts) and the IP renewal watcher "
        "(services/ip-renewal-watcher) build report_md from LLM-written fields (deadline_type, rule_basis, ...). The report is "
        "returned by POST /projects/:id/docket/watch, stored in docket_checks / ip_renewal_checks, returned again by the "
        "GET .../checks routes and emailed through Resend, with no Gate 1 on any of it. Fix: gate report_md (and the stored "
        "rows on read) like GET /analytics does. docs/context/current-state.md must record it."
    )
    def test_watcher_reports_pass_gate_1_before_they_are_stored_returned_or_emailed(self):
        src = (REPO / "backend" / "src" / "services" / "docket-watcher" / "reporter.ts").read_text(encoding="utf-8")
        self.assertTrue(
            "verifyDraftForSse" in src or "finalizeHeldOutput" in src or "gateCellContent" in src,
            "reporter.ts stores, returns and emails model-written report text with no Gate 1",
        )


if __name__ == "__main__":
    unittest.main()
