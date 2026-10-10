#!/usr/bin/env python3
"""Join CourtListener's Florida So. 2d / So. 3d citations to the Florida courts' own decision records.

Why: reading citations out of later opinions (fl_southern_reporter.py) can only recover a small slice. CourtListener
already stores the reporter citation for each Florida cluster AND the docket number, so this is a direct join.

  citation (kingsfield_florida.db) -> cluster id -> docket id (clusters file) -> docket number + court (dockets file)
  docket number + court (+ date)   -> flcourts decision (decisions.jsonl: case_number_raw, court, decided_date, pdf)

  ~/.venv-flsr/bin/python fl_cl_join.py --stage extract   # streams the two big bz2 files, ~30-40 min, resumable output
  ~/.venv-flsr/bin/python fl_cl_join.py --stage join      # seconds
"""
import argparse
import bz2
import csv
import json
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

csv.field_size_limit(sys.maxsize)
HOME = Path.home()
CORPUS = HOME / "Kingsfield_Corpus"
DB = HOME / "kingsfield" / "kingsfield_florida.db"
OUT = CORPUS / "flcourts"


def stream(path):
    import io
    return csv.DictReader(io.TextIOWrapper(bz2.open(path, "rb"), encoding="utf-8", errors="replace", newline=""))


def find(prefix):
    return sorted(p for p in CORPUS.iterdir() if p.name.startswith(prefix) and ".csv" in p.name)[0]


def stage_extract():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    want = {str(r[0]) for r in con.execute("select distinct cluster_id from citation_index where reporter in ('So. 2d','So. 3d')")}
    print(f"{len(want):,} Florida clusters with a So. 2d/3d citation", flush=True)
    cl = {}                                            # cluster id -> (docket_id, date_filed)
    for i, r in enumerate(stream(find("opinion-clusters"))):
        cid = r.get("id")                              # a few rows are misaligned by stray quotes in the source: skipped
        if cid in want:
            cl[cid] = (r["docket_id"], r.get("date_filed", ""))
        if i % 2_000_000 == 0:
            print(f"  clusters scanned {i:,} | kept {len(cl):,}", flush=True)
    dk_ids = {d for d, _ in cl.values()}
    dk = {}                                            # docket id -> (docket_number, court_id)
    for i, r in enumerate(stream(find("dockets"))):
        if r["id"] in dk_ids:
            dk[r["id"]] = (r["docket_number"], r["court_id"])
        if i % 5_000_000 == 0:
            print(f"  dockets scanned {i:,} | kept {len(dk):,}", flush=True)
    with (OUT / "cl_cluster_docket.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cluster_id", "docket_id", "docket_number", "court_id", "date_filed"])
        for cid, (did, df) in cl.items():
            num, court = dk.get(did, ("", ""))
            w.writerow([cid, did, num, court, df])
    print(f"wrote cl_cluster_docket.csv: {len(cl):,} clusters, {sum(1 for c in cl.values() if c[0] in dk):,} with a docket number")


NUM = re.compile(r"(?:(\d)D)?\s*(\d{2}|\d{4})\s*-\s*(\d+)", re.I)


def norm(num, court_digit=None):
    """'1D2024-2289' / '07-3598' / '2D07-3598' -> (district digit or None, 4-digit year, number as int)"""
    m = NUM.search(num or "")
    if not m:
        return None
    d, y, n = m.group(1), m.group(2), int(m.group(3))
    y = int(y)
    if y < 100:
        y += 2000 if y <= 40 else 1900
    return (d or court_digit, y, n)


def stage_join():
    cl = {}
    with (OUT / "cl_cluster_docket.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            cl[int(r["cluster_id"])] = r
    cites = defaultdict(list)                          # cluster id -> citations
    with (CORPUS / "fl_courtlistener_citations_so2d_so3d.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            cites[int(r["cluster_id"])].append(r)
    # index CourtListener clusters by (court group, district, year, number)
    idx = defaultdict(list)
    for cid, r in cl.items():
        court = r["court_id"]
        key = norm(r["docket_number"])
        if key is None:
            continue
        group = "fla" if court == "fla" else "dca"
        idx[(group, key[1], key[2])].append((cid, key[0], r["date_filed"]))
    out, matched_dec, total_dec, ambiguous = [], 0, 0, 0
    for line in (OUT / "decisions.jsonl").open(encoding="utf-8"):
        d = json.loads(line)
        if d["listing_type"] != "opinions" or not d.get("decided_date"):
            continue
        total_dec += 1
        court = d["court"]
        digit = court[0] if court.endswith("dca") else None
        key = norm(d["case_number_raw"], digit)
        if key is None:
            continue
        group = "fla" if court == "supremecourt" else "dca"
        cands = idx.get((group, key[1], key[2]), [])
        # same district (when both sides say) and a decision date that agrees with CourtListener's date_filed
        good = [c for c in cands if (c[1] in (None, key[0]) or key[0] is None) and (not c[2] or c[2][:4] == d["decided_date"][:4])]
        if len(good) > 1:
            exact = [c for c in good if c[2] == d["decided_date"]]
            good = exact or good
        if len(good) != 1:
            ambiguous += 1 if len(good) > 1 else 0
            continue
        cid = good[0][0]
        for c in cites.get(cid, []):
            out.append({"case_number": d["case_number_raw"], "court": court, "decided_date": d["decided_date"],
                        "case_style": d.get("case_style"), "reporter_cite": f"{c['volume']} {c['reporter']} {c['page']}",
                        "cl_case_name": c["case_name"], "cluster_id": cid, "pdf_uri": d.get("pdf_uri")})
        if cites.get(cid):
            matched_dec += 1
    p = OUT / "fl_southern_citations_courtlistener.csv"
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["case_number", "court", "decided_date", "case_style", "reporter_cite",
                                          "cl_case_name", "cluster_id", "pdf_uri"])
        w.writeheader(); w.writerows(out)
    print(f"opinions in the court listing: {total_dec:,} | with a So. 2d/3d citation via CourtListener: {matched_dec:,} "
          f"({100 * matched_dec / max(total_dec, 1):.1f}%) | ambiguous (skipped): {ambiguous:,} | rows written: {len(out):,} -> {p}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", required=True, choices=["extract", "join", "all"])
    {"extract": stage_extract, "join": stage_join, "all": lambda: (stage_extract(), stage_join())}[ap.parse_args().stage]()
