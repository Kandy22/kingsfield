#!/usr/bin/env python3
"""Merge human labels into the canonical data. Idempotent: running it twice changes nothing.

LEGACY (no arguments): merge `human_verdict` from the old kingsfield-verified-*.json exports into
results_full.json, exactly as before.

NEW (review tool, sandbox.html v2): merge exported labels files
  python3 merge_human_labels.py --labels labels-2026-10-09.json [more files] \
      [--full results_full.json] [--csv ~/Kingsfield_Corpus/flcourts/fl_southern_citations.csv]
  * benchmark rows      -> results_full.json: `human_verdict` (yes / no / unsure) + `human_review` {reviewer, at, jev_shown}
  * citation_match rows -> the CSV (columns human_label, human_reviewer, human_date added; status becomes
                           human_confirmed / human_rejected / human_na). A "yes" for a pair not in the CSV is appended.
                           Every label is also appended to human_citation_reviews.jsonl next to the CSV.
  * the labeling protocol (who, whether Jev's answer was shown, when, how many) is appended to
    labeling_protocol.json next to results_full.json: the benchmark card says this record is missing.
Mapping: Correct = yes, Incorrect = no, N/A = unsure. A backup of each file is written before it changes.
"""
import argparse
import csv
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
STATUS = {"yes": "human_confirmed", "no": "human_rejected", "unsure": "human_na"}


def backup(path):
    b = path + f".bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy(path, b)
    print(f"Backup: {b}")


def legacy(full_path):
    if not os.path.exists(full_path):
        raise SystemExit(f"Missing {full_path}")
    backup(full_path)
    full = json.load(open(full_path))
    by_term = {e["term"]: e for e in full}
    merged = 0
    for path in EXPORTS:
        if not os.path.exists(path):
            continue
        for ex in json.load(open(path)):
            term, hv = ex.get("term"), ex.get("human_verdict")
            if not term or not hv or term not in by_term:
                continue
            entry = by_term[term]
            if entry.get("human_verdict") != hv:
                entry["human_verdict"] = hv
                merged += 1
            for field in ("notes", "correct_definition"):
                if ex.get(field):
                    entry[field] = ex[field]
    json.dump(full, open(full_path, "w"), indent=1)
    for path in EXPORTS:
        if os.path.exists(path):
            json.dump(full, open(path, "w"), indent=1)
    human = sum(1 for e in full if e.get("human_verdict"))
    print(f"Merged/confirmed {merged} human labels")
    print(f"Total human_verdict in results_full.json: {human}/{len(full)}")


def merge_labels(label_files, full_path, csv_path):
    full = json.load(open(full_path)) if os.path.exists(full_path) else []
    by_idx = {str(e.get("idx")): e for e in full}
    csv_rows, csv_cols = [], []
    if csv_path and os.path.exists(csv_path):
        with open(csv_path, newline="", encoding="utf-8") as f:
            rd = csv.DictReader(f)
            csv_cols, csv_rows = list(rd.fieldnames or []), list(rd)
        for c in ("human_label", "human_reviewer", "human_date"):
            if c not in csv_cols:
                csv_cols.append(c)
    key = lambda r: (r.get("reporter_cite") or "", r.get("case_number") or "")  # None and "" are the same key
    by_key = {key(r): r for r in csv_rows}
    reviews_path = os.path.join(os.path.dirname(csv_path), "human_citation_reviews.jsonl") if csv_path else None
    seen_reviews = set()
    if reviews_path and os.path.exists(reviews_path):
        seen_reviews = {json.loads(l)["id"] + json.loads(l)["at"] for l in open(reviews_path) if l.strip()}
    proto_path = os.path.join(os.path.dirname(full_path), "labeling_protocol.json")
    protocol = json.load(open(proto_path)) if os.path.exists(proto_path) else []
    n_bench = n_cite = n_new = 0
    new_reviews = []
    for lf in label_files:
        d = json.load(open(lf))
        labs = d.get("labels", [])
        sig = f"{os.path.basename(lf)}|{d.get('exported_at')}"
        if not any(p.get("signature") == sig for p in protocol):
            protocol.append({"signature": sig, "labels_file": os.path.basename(lf), "tool": d.get("tool"),
                             "exported_at": d.get("exported_at"), "merged_at": datetime.now().isoformat(timespec="seconds"),
                             "reviewers": sorted({l.get("reviewer") for l in labs if l.get("reviewer")}),
                             "jev_shown_for": sum(1 for l in labs if l.get("jev_shown")), "n_labels": len(labs),
                             "source_file": d.get("source_file")})
        for l in labs:
            v = l.get("human_verdict")
            if v not in STATUS:
                continue
            ref = l.get("ref") or {}
            if l.get("kind") == "benchmark":
                e = by_idx.get(str(ref.get("idx")))
                if e is None:
                    continue
                if e.get("human_verdict") != v:
                    e["human_verdict"] = v
                    e["human_review"] = {"reviewer": l.get("reviewer"), "at": l.get("at"), "jev_shown": bool(l.get("jev_shown"))}
                    n_bench += 1
            elif l.get("kind") == "citation_match":
                if reviews_path and (l["id"] + l["at"]) not in seen_reviews:
                    new_reviews.append(l)
                    seen_reviews.add(l["id"] + l["at"])
                if csv_path:
                    k = (ref.get("cite") or "", ref.get("case_number") or "")
                    r = by_key.get(k)
                    if r is None and v == "yes":
                        r = {c: "" for c in csv_cols}
                        r.update({"case_number": ref.get("case_number"), "court": ref.get("court"),
                                  "decided_date": ref.get("decided_date"), "reporter_cite": ref.get("cite"),
                                  "source_opinion": ref.get("source")})
                        csv_rows.append(r); by_key[k] = r; n_new += 1
                    if r is not None and r.get("human_label") != v:
                        r["human_label"], r["human_reviewer"] = v, l.get("reviewer")
                        r["human_date"] = (l.get("at") or "")[:10]
                        r["status"] = STATUS[v]
                        n_cite += 1
    if os.path.exists(full_path):
        backup(full_path)
    json.dump(full, open(full_path, "w"), indent=1)
    if csv_path and os.path.exists(csv_path):
        backup(csv_path)
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=csv_cols)
            w.writeheader(); w.writerows(csv_rows)
    if new_reviews and reviews_path:
        with open(reviews_path, "a", encoding="utf-8") as f:
            for l in new_reviews:
                f.write(json.dumps(l, ensure_ascii=False) + "\n")
    json.dump(protocol, open(proto_path, "w"), indent=1)
    human = sum(1 for e in full if e.get("human_verdict"))
    print(f"benchmark labels changed: {n_bench} | citation rows updated: {n_cite} (new rows added: {n_new}) | "
          f"protocol entries: {len(protocol)}")
    print(f"Total human_verdict in {os.path.basename(full_path)}: {human}/{len(full)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--labels", nargs="*", help="labels-*.json files exported by sandbox.html")
    ap.add_argument("--full", default=FULL)
    ap.add_argument("--csv", default="")
    a = ap.parse_args()
    if a.labels:
        merge_labels(a.labels, a.full, os.path.expanduser(a.csv) if a.csv else "")
    else:
        legacy(a.full)


if __name__ == "__main__":
    main()
