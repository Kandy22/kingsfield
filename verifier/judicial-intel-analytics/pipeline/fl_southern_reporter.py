#!/usr/bin/env python3
"""Task 1 (INSTRUCTIONS_5_TASKS_2026-10-03.md): give every Florida appellate decision since 2008
its So. 2d / So. 3d citation, built the way LawDiver did: read the citations that LATER opinions
print for each decision, then match them back to the decision by court + year + case name.

Stages (resumable; every stage skips work already on disk):
  list    flcourts opinion/PCA listings per court and year          -> decisions.jsonl
  text    PDF -> text (pdftotext in memory; the PDF is never saved)  -> text/<court>/<id>.txt
  cites   eyecite over every text file, keep full So. 2d / So. 3d    -> cites.jsonl
  match   cite -> decision (name score >= 85 and beats runner-up by 5) -> fl_southern_citations.csv
                                                                          + review_queue.jsonl
LawDiver cross-check (1.6) needs a free LawDiver key and is not in this script.

Run with the dedicated venv (eyecite + rapidfuzz + requests), one process, low priority:
  nice -n 10 ~/.venv-flsr/bin/python fl_southern_reporter.py --stage list
Data goes to ~/Kingsfield_Corpus/flcourts by default (override with --out). No PDFs are stored.
"""
import argparse
import csv
import hashlib
import json
import re
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from enrich_flcourts import API, PAGE, UA, SLEEP, fetch_page, normalize, pdf_text  # noqa: E402

COURTS = {  # court key -> (siteaccess, scope)
    "1dca": ("1dca", "first_district_court_of_appeal"),
    "2dca": ("2dca", "second_district_court_of_appeal"),
    "3dca": ("3dca", "third_district_court_of_appeal"),
    "4dca": ("4dca", "fourth_district_court_of_appeal"),
    "5dca": ("5dca", "fifth_district_court_of_appeal"),
    "6dca": ("6dca", "sixth_district_court_of_appeal"),
    "supremecourt": ("supremecourt", "supreme_court"),
}
KINDS = ("opinions", "pca")
DEFAULT_OUT = Path.home() / "Kingsfield_Corpus" / "flcourts"
ACCEPT_SCORE, ACCEPT_MARGIN = 85, 5


def doc_id(rec: dict) -> str:
    cn = re.sub(r"[^A-Za-z0-9]+", "-", rec.get("case_number_raw") or "nocase").strip("-")
    h = hashlib.sha1((rec.get("pdf_uri") or "").encode()).hexdigest()[:8]
    return f"{cn}_{rec.get('decided_date') or 'nodate'}_{rec['listing_type']}_{h}"


def stage_list(out: Path, courts, since: int, until: int):
    path = out / "decisions.jsonl"
    seen = set()
    if path.exists():
        for line in path.open(encoding="utf-8"):
            try:
                seen.add(json.loads(line)["_key"])
            except Exception:
                pass
    s = requests.Session()
    n = 0
    with path.open("a", encoding="utf-8") as f:
        for court in courts:
            site, scope = COURTS[court]
            for year in range(since, until + 1):
                start = f"01/01/{year}"
                end = f"12/31/{year}" if year < date.today().year else date.today().strftime("%m/%d/%Y")
                for kind in KINDS:
                    offset = 0
                    while True:
                        data = fetch_page(s, site, scope, kind, start, end, offset)
                        time.sleep(SLEEP)
                        results = data.get("searchResults") or []
                        total = data.get("totalCount", 0)
                        for it in results:
                            rec = normalize(it, kind)
                            rec["court"] = court
                            rec["_key"] = f"{court}|{rec['case_number_raw']}|{rec['decided_date']}|{kind}|{rec.get('pdf_uri')}"
                            if rec["_key"] in seen:
                                continue
                            seen.add(rec["_key"])
                            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                            n += 1
                        offset += PAGE
                        if not results or offset >= total:
                            break
                    print(f"  {court} {year} {kind:<8} total={total}", flush=True)
                f.flush()
    print(f"list: {n} new decisions -> {path}")


def stage_text(out: Path, courts, limit: int):
    s = requests.Session()
    fails = (out / "failures.txt").open("a", encoding="utf-8")
    done = 0
    for line in (out / "decisions.jsonl").open(encoding="utf-8"):
        rec = json.loads(line)
        if rec["court"] not in courts or not rec.get("pdf_uri"):
            continue
        dest = out / "text" / rec["court"] / (doc_id(rec) + ".txt")
        if dest.exists():
            continue
        try:
            txt = pdf_text(s, rec["pdf_uri"])  # PDF stays in memory
        except Exception as ex:
            fails.write(f"{rec['_key']}\t{ex}\n")
            fails.flush()
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(txt, encoding="utf-8")
        done += 1
        if done % 200 == 0:
            print(f"  text: {done} files", flush=True)
        if limit and done >= limit:
            break
    print(f"text: {done} files written")


COURT_RE = [
    (re.compile(r"\b(\d)(?:st|nd|rd|th)\s+(?:D\.?\s?C\.?\s?A\.?|Dist)", re.I), lambda m: f"{m.group(1)}dca"),
    (re.compile(r"^\s*Fla\.?\s*$", re.I), lambda m: "supremecourt"),
]


def court_key(paren: str):
    for rx, fn in COURT_RE:
        m = rx.search(paren or "")
        if m:
            return fn(m)
    return None


def stage_cites(out: Path):
    from eyecite import get_citations
    from eyecite.models import FullCaseCitation

    seen = set()
    cpath = out / "cites.jsonl"
    if cpath.exists():
        for line in cpath.open(encoding="utf-8"):
            try:
                seen.add(json.loads(line)["source"])
            except Exception:
                pass
    n = 0
    with cpath.open("a", encoding="utf-8") as f:
        for t in sorted((out / "text").rglob("*.txt")):
            src = t.stem
            if src in seen:
                continue
            for c in get_citations(t.read_text(encoding="utf-8", errors="ignore")):
                if not isinstance(c, FullCaseCitation):
                    continue
                rep = c.corrected_reporter()
                if rep not in ("So. 2d", "So. 3d"):
                    continue
                md = c.metadata
                f.write(json.dumps({
                    "source": src, "volume": c.groups.get("volume"), "reporter": rep, "page": c.groups.get("page"),
                    "plaintiff": md.plaintiff, "defendant": md.defendant, "year": c.year, "court_paren": md.court,
                    "court": court_key(md.court),
                }) + "\n")
                n += 1
            seen.add(src)
    print(f"cites: {n} citations -> {cpath}")


def stage_match(out: Path):
    from rapidfuzz import fuzz

    dec = defaultdict(list)  # (court, year) -> [records]
    for line in (out / "decisions.jsonl").open(encoding="utf-8"):
        r = json.loads(line)
        if r.get("decided_date"):
            dec[(r["court"], r["decided_date"][:4])].append(r)
    groups = defaultdict(lambda: {"sources": set(), "rec": None, "scores": []})
    review = (out / "review_queue.jsonl").open("w", encoding="utf-8")
    for line in (out / "cites.jsonl").open(encoding="utf-8"):
        c = json.loads(line)
        if not (c["court"] and c["year"] and c["plaintiff"] and c["defendant"]):
            continue
        cands = dec.get((c["court"], str(c["year"])), [])
        name = f"{c['plaintiff']} v. {c['defendant']}"
        scored = sorted(((fuzz.token_set_ratio(name, r.get("case_style") or ""), r) for r in cands),
                        key=lambda x: -x[0])
        cite = f"{c['volume']} {c['reporter']} {c['page']}"
        if scored and scored[0][0] >= ACCEPT_SCORE and (len(scored) == 1 or scored[0][0] - scored[1][0] >= ACCEPT_MARGIN):
            g = groups[(cite, scored[0][1]["_key"])]
            g["rec"], g["sources"] = scored[0][1], g["sources"] | {c["source"]}
            g["scores"].append(scored[0][0])
        else:
            review.write(json.dumps({"cite": cite, "as_written": name, "year": c["year"], "court": c["court"],
                                     "source": c["source"],
                                     "candidates": [(s, r["case_style"], r["case_number_raw"], r["decided_date"])
                                                    for s, r in scored[:3]]}) + "\n")
    review.close()
    with (out / "fl_southern_citations.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["case_number", "court", "decided_date", "case_style", "reporter_cite", "source_opinion",
                    "name_score", "n_citing", "lawdiver_agrees", "status"])
        for (cite, _), g in sorted(groups.items()):
            r = g["rec"]
            w.writerow([r["case_number_raw"], r["court"], r["decided_date"], r["case_style"], cite,
                        sorted(g["sources"])[0], max(g["scores"]), len(g["sources"]), "", "accepted"])
    print(f"match: {len(groups)} accepted pairs -> fl_southern_citations.csv; review_queue.jsonl written")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", required=True, choices=["list", "text", "cites", "match"])
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--courts", default=",".join(COURTS))
    ap.add_argument("--since", type=int, default=2008)
    ap.add_argument("--until", type=int, default=date.today().year)
    ap.add_argument("--limit", type=int, default=0, help="text stage: stop after N files (testing)")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    courts = [c for c in a.courts.split(",") if c in COURTS]
    {"list": lambda: stage_list(out, courts, a.since, a.until),
     "text": lambda: stage_text(out, courts, a.limit),
     "cites": lambda: stage_cites(out),
     "match": lambda: stage_match(out)}[a.stage]()


if __name__ == "__main__":
    main()
