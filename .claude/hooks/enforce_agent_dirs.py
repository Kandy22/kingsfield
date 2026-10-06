#!/usr/bin/env python3
"""PreToolUse hook: confine each cascade agent to its own paths."""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2]).resolve()
GATE_TS = "backend/src/verification/local_sqlite_gate.ts"

WRITE_DIRS = {
    "backend_builder": ("db/", "pipeline/", GATE_TS),
    "decision_router": ("router/",),
    "adversary": ("pipeline/tests/", ".claude/signoffs/"),
}
# The builder must not touch the suite it has to pass.
DENY_DIRS = {"backend_builder": ("pipeline/tests/",)}
# Only the assigned cascade agent may write these; every other session is refused.
PROTECTED = ("db/", "pipeline/", "router/", GATE_TS, ".claude/signoffs/", ".claude/hooks/",
             ".claude/settings.json", ".claude/settings.local.json")
# The venv interpreter, spelled with ~ or as an absolute path.
VENV_PY = r"(?:~|" + re.escape(str(Path.home())) + r")/\.venv-cascade/bin/python"
RUN_TESTS = re.compile(VENV_PY + r" -m unittest discover pipeline/tests( -v)?")
RUN_DIGEST = re.compile(VENV_PY + r" \.claude/hooks/tree_digest\.py")
BUILDER_BASH_DENY = re.compile(
    r"\bgit\s+(commit|push|checkout|switch|reset|rebase|merge)\b|\binstall\b"
    r"|\b(uv|bun)\s+add\b|\bdocker\b|\bvon\s+serve\b|\b(curl|wget)\b"
    r"|\bhf\s+download\b|huggingface-cli|pipeline/tests|\.claude/"
)


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
        if agent in ("backend_builder", "decision_router") and not RUN_TESTS.fullmatch(cmd) and BUILDER_BASH_DENY.search(cmd.lower()):
            block(f"{agent} may not commit, install, download, start servers, or touch tests or .claude/: {cmd}")
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
