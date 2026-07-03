#!/usr/bin/env python3
"""
Merge human_verdict labels from export files into canonical results_full.json.
Idempotent — only overwrites when export has a non-null human_verdict.
"""
import json
import os
import shutil
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
FULL = os.path.join(HERE, "results_full.json")
EXPORTS = [
    os.path.join(HERE, "kingsfield-verified-2026-06-01.json"),
    os.path.join(HERE, "kingsfield-verified-2026-05-30.json"),
]

def main():
    if not os.path.exists(FULL):
        raise SystemExit(f"Missing {FULL}")

    backup = FULL + f".bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy(FULL, backup)
    print(f"Backup: {backup}")

    full = json.load(open(FULL))
    by_term = {e["term"]: e for e in full}

    merged = 0
    for path in EXPORTS:
        if not os.path.exists(path):
            continue
        for ex in json.load(open(path)):
            term = ex.get("term")
            hv = ex.get("human_verdict")
            if not term or not hv or term not in by_term:
                continue
            entry = by_term[term]
            if entry.get("human_verdict") != hv:
                entry["human_verdict"] = hv
                merged += 1
            for field in ("notes", "correct_definition"):
                if ex.get(field):
                    entry[field] = ex[field]

    json.dump(full, open(FULL, "w"), indent=1)
    for path in EXPORTS:
        if os.path.exists(path):
            json.dump(full, open(path, "w"), indent=1)

    human = sum(1 for e in full if e.get("human_verdict"))
    print(f"Merged/confirmed {merged} human labels")
    print(f"Total human_verdict in results_full.json: {human}/{len(full)}")

if __name__ == "__main__":
    main()