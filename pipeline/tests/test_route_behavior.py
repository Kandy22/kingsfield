"""POST /crew/chat and POST /council withhold on a veto and on a gate error: behavioral proof (adversary vector 3).

Replaces the old static check that only looked for 'verification' / 'hasVetoes' / 'vetoed' somewhere after the gate call
(a console.warn line satisfied it). Here the REAL route handlers from buildRoutes(deps) in backend/src/routes/index.ts are
taken out of the express router stack and driven with fake req/res objects, with the real Gate 1 (verifyDraftForSse ->
verifyDraft -> localGate1Text -> pipeline/gate1.py against the fixture database) and stubs only for what would leave the
machine: the model clients (Anthropic / Gemini / DeepSeek / Kimi), Supabase and fetch (CourtListener answers "not found").

route_behavior_cases.ts runs under backend's tsx once per mode, because routes/index.ts reads MOCK_ENABLED once at import:
  * crew mode    MOCK_LLM=true   /crew/chat uses MOCK_CREW.reply (the only model-free path; lib/llm is not injectable)
  * council mode MOCK_LLM=false  /council calls the stubbed model clients and saves the session it sends

The static wiring tests stay in test_gate1_review_findings.py.
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
CASES_TS = Path(__file__).resolve().parent / "route_behavior_cases.ts"


def _run_mode(mode, mock_llm):
    if not TSX.exists():
        raise AssertionError("tsx missing at %s; the route behavior cases cannot run (report it, do not skip it)" % TSX)
    env = dict(os.environ)
    env["KINGSFIELD_FLORIDA_DB"] = str(fx.get_fixture().db)
    env["ROUTE_CASES_MODE"] = mode
    env["MOCK_LLM"] = mock_llm
    proc = subprocess.run([str(TSX), str(CASES_TS)], capture_output=True, text=True, env=env,
                          cwd=str(REPO), timeout=240)
    if proc.returncode != 0:
        raise AssertionError("tsx failed in %s mode (%d):\n%s" % (mode, proc.returncode, proc.stderr[-2500:]))
    lines = [l for l in proc.stdout.splitlines() if l.strip()]
    data = json.loads(lines[-1])
    if os.environ.get("KF_INFO"):
        sys.stderr.write("route_behavior_cases[%s] info: %s\n" % (mode, json.dumps(data.get("info"), sort_keys=True)))
    return data["results"]


class _Cases(unittest.TestCase):
    MODE = None
    MOCK = None
    EXPECTED = ()
    report = None

    @classmethod
    def setUpClass(cls):
        if cls.MODE is None:
            return
        cls.report = _run_mode(cls.MODE, cls.MOCK)
        if "__harness_setup__" in cls.report:
            raise AssertionError("harness setup failed in %s mode: %s" % (cls.MODE, cls.report["__harness_setup__"]))

    def _case(self, name):
        self.assertIn(name, self.report, "the harness did not run %s (ran: %s)" % (name, sorted(self.report)))
        self.assertIsNone(self.report[name], self.report[name])


class CrewChatRouteWithholds(_Cases):
    MODE = "crew"
    MOCK = "true"

    def test_a_vetoed_reply_is_withheld_whole_with_a_recorded_veto_and_no_citation_text(self):
        self._case("crew_chat_vetoed_mock_reply_is_withheld_whole_with_a_recorded_veto")

    def test_a_clean_reply_is_sent_unchanged_with_a_clean_record(self):
        self._case("crew_chat_clean_reply_is_sent_unchanged_with_a_clean_record")

    def test_a_gate_error_withholds_with_the_generic_message_and_no_raw_error(self):
        self._case("crew_chat_gate_error_withholds_with_the_generic_message_and_no_raw_error")

    def test_a_malformed_reply_withholds_with_the_generic_message(self):
        self._case("crew_chat_malformed_reply_withholds_with_the_generic_message")


class CouncilRouteWithholds(_Cases):
    MODE = "council"
    MOCK = "false"

    def test_a_vetoed_advisor_withholds_the_whole_output_and_the_saved_row_holds_only_the_withheld_text(self):
        self._case("council_vetoed_advisor_withholds_the_whole_output_and_saves_only_the_withheld_text")

    def test_a_vetoed_advisor_without_a_project_id_saves_nothing(self):
        self._case("council_vetoed_advisor_without_a_project_id_saves_nothing")

    def test_a_clean_output_passes_through_unchanged_and_is_saved_as_sent(self):
        self._case("council_clean_output_passes_through_unchanged_and_is_saved_as_sent")

    def test_a_gate_error_withholds_with_the_generic_message_and_leaks_no_raw_error(self):
        self._case("council_gate_error_withholds_with_the_generic_message_and_leaks_no_raw_error")

    def test_a_project_the_caller_does_not_own_is_never_saved_into(self):
        self._case("council_a_project_the_caller_does_not_own_is_never_saved_into")

    def test_a_model_failure_sends_the_fixed_500_and_saves_nothing(self):
        self._case("council_model_failure_sends_the_fixed_500_and_saves_nothing")


# unittest would try to run the abstract base; it has no test methods, so there is nothing to collect.

if __name__ == "__main__":
    unittest.main()
