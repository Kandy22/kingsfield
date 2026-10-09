#!/usr/bin/env python3
"""Build the rows the review tool (sandbox.html) loads.

Two sources, one row format:
  benchmark       results_full.json entries with no human_verdict yet
                  (question: does the cited authority really support this term/quote?)
  citation_match  Florida Southern Reporter review queue from
                  judicial-intel-analytics/pipeline/fl_southern_reporter.py --stage match
                  (question: does this citation refer to this decision?)

  python3 prepare_review_rows.py --queue ~/Kingsfield_Corpus/flcourts/review_queue.jsonl --out review_rows.jsonl
Rows keep any existing Jev answer when the output file already has one (so re-running is safe).
"""
import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PDF_BASE = "https://flcourts-media.flcourts.gov"


def benchmark_rows(path: Path, include_labeled: bool):
    for e in json.load(open(path)):
        if e.get("human_verdict") and not include_labeled:
            continue
        cites = e.get("all_cites")
        cand_bits = [f"Cited as: {cites}" if cites else "No citation extracted"]
        v = e.get("verification")
        if v:
            cand_bits.append("Pipeline check: " + (json.dumps(v)[:160] if not isinstance(v, str) else v[:160]))
        yield {
            "id": f"bench:{e['idx']}", "kind": "benchmark",
            "heading": e.get("term") or "(no term)",
            "claim": e.get("quote") or "",
            "context": "",
            "candidate": {"text": " | ".join(cand_bits), "meta": f"source: {e.get('source') or 'n/a'}",
                          "url": e.get("cl_url") if e.get("cl_url") not in (None, "None") else ""},
            "question": "Does the cited authority actually contain this statement for this term?",
            "ref": {"idx": e["idx"], "term": e.get("term")},
        }


def queue_rows(path: Path):
    for n, line in enumerate(open(path, encoding="utf-8")):
        q = json.loads(line)
        cands = q.get("candidates") or []
        top = cands[0] if cands and isinstance(cands[0], dict) else {}
        pdf = top.get("pdf_uri") or ""
        yield {
            "id": f"cite:{n}", "kind": "citation_match",
            "heading": q["cite"],
            "claim": f"{q['cite']} as written: {q.get('as_written', '')} ({q.get('year')}, {q.get('court')})",
            "context": q.get("context", ""),
            "candidate": {"text": f"{top.get('case_style', '(no candidate)')}  (name score {top.get('score', 0):.0f})",
                          "meta": f"{top.get('court', '')} · {top.get('decided_date', '')} · case {top.get('case_number', '')}",
                          "url": (PDF_BASE + pdf) if pdf.startswith("/") else pdf},
            "question": "Does this citation refer to this decision?",
            "ref": {"cite": q["cite"], "case_number": top.get("case_number"), "court": top.get("court"),
                    "decided_date": top.get("decided_date"), "source": q.get("source")},
        }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--benchmark", default=str(HERE / "results_full.json"))
    ap.add_argument("--queue", default="")
    ap.add_argument("--out", default=str(HERE / "review_rows.jsonl"))
    ap.add_argument("--no-benchmark", action="store_true")
    ap.add_argument("--include-labeled", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="max rows per source (testing)")
    a = ap.parse_args()
    old = {}
    out = Path(a.out)
    if out.exists():
        for line in out.open(encoding="utf-8"):
            r = json.loads(line)
            if r.get("jev"):
                old[r["id"]] = r["jev"]
    rows = []
    if not a.no_benchmark:
        rows += list(benchmark_rows(Path(a.benchmark), a.include_labeled))[: a.limit or None]
    if a.queue:
        rows += list(queue_rows(Path(a.queue).expanduser()))[: a.limit or None]
    with out.open("w", encoding="utf-8") as f:
        for r in rows:
            r["jev"] = old.get(r["id"])
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(rows)} rows -> {out} ({sum(1 for r in rows if r['jev'])} already have a Jev answer)")


if __name__ == "__main__":
    main()
