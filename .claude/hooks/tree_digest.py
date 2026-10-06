#!/usr/bin/env python3
"""Print a sha256 over the cascade's reviewed files."""
import hashlib
import os
from pathlib import Path

DIRS = ("db", "pipeline", "router")
EXTRA_FILES = ("backend/src/verification/local_sqlite_gate.ts",
    "backend/src/verification/pipeline.ts",
    "backend/src/crew/researcher.ts",)
SKIP_DIRS = {"__pycache__", ".pytest_cache", "node_modules"}
SKIP_SUFFIXES = (".pyc", ".db", ".db-journal", ".db-wal", ".db-shm", ".sqlite")


def _add(h, root, path):
    h.update(path.relative_to(root).as_posix().encode() + b"\0")
    h.update(path.read_bytes() + b"\0")


def tree_digest(root):
    root = Path(root)
    h = hashlib.sha256()
    for top in DIRS:
        base = root / top
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
            for name in sorted(filenames):
                if name.endswith(SKIP_SUFFIXES):
                    continue
                _add(h, root, Path(dirpath) / name)
    for rel in EXTRA_FILES:
        if (root / rel).is_file():
            _add(h, root, root / rel)
    return h.hexdigest()


if __name__ == "__main__":
    root = os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2]
    print(tree_digest(root))
