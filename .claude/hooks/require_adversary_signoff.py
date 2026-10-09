#!/usr/bin/env python3
"""TaskCompleted hook: [module] tasks need a passing bypass suite and an adversary signoff."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tree_digest import tree_digest  # noqa: E402

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
VENV_PY = Path.home() / ".venv-cascade" / "bin" / "python"
TEST_DIR = "pipeline/tests"
REQUIRED = "pipeline/tests/test_gate1_bypass.py"


def block(msg):
    print(msg, file=sys.stderr)
    sys.exit(2)


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception as exc:
        block(f"Signoff hook could not read its input: {exc}")
    if not (payload.get("task_subject") or "").startswith("[module]"):
        sys.exit(0)
    task_id = str(payload.get("task_id") or "")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", task_id):
        block(f"Task id {task_id!r} is not a safe file name; cannot locate a signoff.")
    signoff = ROOT / ".claude" / "signoffs" / f"{task_id}.signoff"
    if not signoff.is_file():
        block(f"No adversary signoff at .claude/signoffs/{task_id}.signoff.")
    if signoff.read_text().strip() != tree_digest(ROOT):
        block("Signoff digest does not match the reviewed files. Code changed after review.")
    if not (ROOT / REQUIRED).is_file():
        block(f"{REQUIRED} does not exist.")
    if not VENV_PY.is_file():
        block(f"{VENV_PY} is missing; cannot run the bypass suite.")
    try:
        result = subprocess.run(
            [str(VENV_PY), "-m", "unittest", "discover", TEST_DIR],
            cwd=ROOT, capture_output=True, text=True, timeout=240,
        )
    except subprocess.TimeoutExpired:
        block(f"The {TEST_DIR} suite timed out.")
    if result.returncode != 0:
        # unittest prints its report to stderr.
        block(f"{TEST_DIR} exited {result.returncode}:\n{result.stderr[-2500:]}")
    sys.exit(0)


if __name__ == "__main__":
    main()
