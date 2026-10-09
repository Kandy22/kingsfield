"""Crew abort propagation (adversary class f, main-verify): once the client has disconnected, every later crew role and every
model call must see the abort, so no role starts and no provider call is made for a reply nobody receives.

Static, over backend/src/crew/**/*.ts and backend/src/lib/llm/*.ts:

  * runCrew passes deps.signal to every role it calls (researcher, analyst, strategist, team lead, writing coach,
    impeacher, opposition mapper, triage, clause review, DMCA, specialists), or checks deps.signal.aborted before the call;
  * every completeText({...}) call in a crew role forwards a signal;
  * each provider's completeXText forwards the signal to the SDK call.

The behavioural half (route level: runCrew's signal is aborted, nothing is written after the disconnect, the fallback
completeText is skipped) is in test_crew_chat_bypass.py.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate1_fixture as fx  # noqa: E402

SRC = fx.REPO / "backend" / "src"
CREW = SRC / "crew"
LLM = SRC / "lib" / "llm"


def _code(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", line) for line in src.splitlines())


def _balanced(code, open_idx):
    depth = 0
    for i in range(open_idx, len(code)):
        c = code[i]
        depth += (c == "(") - (c == ")")
        if depth == 0:
            return code[open_idx:i + 1]
    return code[open_idx:]


class CrewAbortPropagation(unittest.TestCase):
    def test_run_crew_hands_the_signal_to_every_role_it_calls(self):
        code = _code((CREW / "coordinator.ts").read_text(encoding="utf-8"))
        start = code.index("export async function runCrew(")
        end = code.index("function extractWitnessName(", start)
        body = code[start:end]
        calls = [m for m in re.finditer(r"(?<![\w.])(run[A-Z]\w*)\s*\(", body) if m.group(1) != "runCrew"]
        self.assertGreaterEqual(len(calls), 10, "expected the role calls in runCrew; the parser needs updating")
        missing = []
        for m in calls:
            args = _balanced(body, m.end() - 1)
            if "deps.signal" not in args:
                missing.append(m.group(1))
        if missing:
            self.fail("runCrew starts roles without handing them deps.signal (%d of %d): a disconnect does not stop them"
                      % (len(missing), len(calls)))

    def test_every_model_call_in_a_crew_role_forwards_a_signal(self):
        offenders = []
        seen = 0
        for path in sorted(CREW.rglob("*.ts")):
            code = _code(path.read_text(encoding="utf-8"))
            for m in re.finditer(r"(?<![\w.])completeText\s*\(", code):
                if code[max(0, m.start() - 20):m.start()].strip().endswith("import"):
                    continue
                seen += 1
                args = _balanced(code, m.end() - 1)
                if not re.search(r"\bsignal\b", args):
                    offenders.append("%s: completeText(...) without a signal" % path.relative_to(SRC))
        self.assertGreaterEqual(seen, 10, "expected completeText calls in the crew roles; the parser needs updating")
        if offenders:
            self.fail("crew model calls that a client disconnect cannot cancel: " + "; ".join(offenders))

    def test_every_provider_completion_forwards_the_signal_to_the_sdk_call(self):
        problems = []
        for name, fn in (("claude.ts", "completeClaudeText"), ("gemini.ts", "completeGeminiText"), ("openai.ts", "completeOpenAIText")):
            code = _code((LLM / name).read_text(encoding="utf-8"))
            i = code.find("export async function %s(" % fn)
            if i < 0:
                problems.append("%s: %s not found" % (name, fn))
                continue
            nxt = code.find("\nexport ", i + 10)
            body = code[i:nxt if nxt > 0 else len(code)]
            parts = re.split(r"Promise<string>\s*\{", body, maxsplit=1)
            self.assertEqual(len(parts), 2, "%s: cannot find the body of %s" % (name, fn))
            if not re.search(r"\bsignal\b", parts[1]):
                problems.append("%s: %s never uses its signal" % (name, fn))
        self.assertEqual(problems, [], "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
