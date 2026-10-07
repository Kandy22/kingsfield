#!/usr/bin/env python3
"""PreToolUse hook: confine each cascade agent to its own paths."""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2]).resolve()
GATE_TS = "backend/src/verification/local_sqlite_gate.ts"
# Chat-route task (W2-W4, findings 1-3). Lowercase because rel() lowercases paths.
ROUTE_FILES = (
    "backend/src/routes/chat.ts",
    "backend/src/routes/projectchat.ts",
    "backend/src/routes/index.ts",
    "backend/src/middleware/hallucination_guard.ts",
)

WRITE_DIRS = {
    "backend_builder": ("db/", "pipeline/", GATE_TS) + ROUTE_FILES,
    "decision_router": ("router/",),
    "adversary": ("pipeline/tests/", "pipeline/tests_extended/", ".claude/signoffs/"),
}
# The builder must not touch the suite it has to pass.
DENY_DIRS = {"backend_builder": ("pipeline/tests/", "pipeline/tests_extended/")}
# Only the assigned cascade agent may write these; every other session is refused.
PROTECTED = ("db/", "pipeline/", "router/", GATE_TS, ".claude/signoffs/", ".claude/hooks/",
             ".claude/settings.json", ".claude/settings.local.json")
# The venv interpreter, spelled with ~ or as an absolute path.
VENV_PY = r"(?:~|" + re.escape(str(Path.home())) + r")/\.venv-cascade/bin/python"
RUN_TESTS = re.compile(
    VENV_PY + r" -m unittest discover( --durations [0-9]{1,3})? pipeline/tests(_extended)?( -v)?")
RUN_DIGEST = re.compile(VENV_PY + r" \.claude/hooks/tree_digest\.py")
# Builders get an allowlist, like the adversary: any other command could run a script that writes anywhere.
SHELL_META = re.compile(r"[;&|<>`\n\r]|\$\(|--output")
READ_ONLY = re.compile(r"(ls|cat|head|tail|wc|grep|pwd|git (status|diff|log|show))(\s.*)?")
BUILDER_BASH = {
    "backend_builder": re.compile(
        VENV_PY + r" -m unittest (discover pipeline/builder_tests|pipeline\.builder_tests\.[\w.]+)( -v)?"
        r"|npx tsc --noEmit( -p backend)?"),
    "decision_router": re.compile(
        VENV_PY + r" -m unittest (discover router/tests|router\.tests\.[\w.]+)( -v)?"),
}


def block(msg):
    print(msg, file=sys.stderr)
    sys.exit(2)


def rel(path_str):
    # Lowercased because APFS here is case-insensitive: DB/ and db/ are one folder.
    try:
        return Path(path_str).resolve().relative_to(ROOT).as_posix().lower()
    except ValueError:
        return None


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception as exc:
        block(f"Directory hook could not read its input: {exc}")
    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}
    agent = payload.get("agent_type") or ""

    if tool == "Bash":
        cmd = (tool_input.get("command") or "").strip()
        if agent == "adversary" and not (RUN_TESTS.fullmatch(cmd) or RUN_DIGEST.fullmatch(cmd)):
            block(f"adversary may only run the bypass suite or tree_digest.py, not: {cmd}")
        if agent in BUILDER_BASH and not (
            BUILDER_BASH[agent].fullmatch(cmd) or RUN_TESTS.fullmatch(cmd)
            or (not SHELL_META.search(cmd) and READ_ONLY.fullmatch(cmd))
        ):
            block(f"{agent} may run only its own tests, tsc, or read-only commands, not: {cmd}")
        sys.exit(0)

    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not path:
        sys.exit(0)
    r = rel(path)
    if agent in WRITE_DIRS:
        if r is None or not r.startswith(WRITE_DIRS[agent]) or r.startswith(DENY_DIRS.get(agent, ())):
            block(f"{agent} may not write {path}")
        sys.exit(0)
    if r is not None and r.startswith(PROTECTED):
        block(f"Only the assigned cascade agent may write {r}.")
    sys.exit(0)


if __name__ == "__main__":
    main()
