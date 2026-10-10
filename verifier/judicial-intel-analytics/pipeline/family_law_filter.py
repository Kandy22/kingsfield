#!/usr/bin/env python3
"""Task 4 steps 1-2: list the family-law appellate decisions and what their opinions say about trial hearings.

Reads the opinion texts from fl_southern_reporter.py (~/Kingsfield_Corpus/flcourts/text) and the decision listing,
flags family-law cases from the case style and the opening of the opinion, and records the hearing types and whether
the OPINION mentions a transcript. IMPORTANT: this is read from the opinion text only. Whether a transcript was
actually filed in the appellate record is NOT verified here; that needs the court's docket or the clerk.

  ~/.venv-flsr/bin/python family_law_filter.py
Output: ~/Kingsfield_Corpus/flcourts/family_law_cases.csv
"""
import csv
import json
import re
from pathlib import Path

HOME = Path.home()
O = HOME / "Kingsfield_Corpus" / "flcourts"
STYLE = re.compile(r"(in re[: ]+(?:the )?marriage|dissolution|paternity|custody|former (?:husband|wife)|department of children|dep'?t of children|d\.c\.f|"
                   r"in the interest of|in re[: ]+[a-z]\.[a-z]\.|adoption|guardianship|child support|\bminor\b)", re.I)
TEXT = [  # strong phrases in the opening of the opinion
    r"dissolution of marriage", r"former husband", r"former wife", r"time-?sharing", r"parenting plan", r"paternity",
    r"alimony", r"child support", r"equitable distribution", r"shelter petition", r"dependency", r"termination of parental rights",
    r"domestic violence injunction", r"custody", r"relocation", r"supplemental petition",
]
TEXT_RX = [re.compile(t, re.I) for t in TEXT]
HEARINGS = {
    "final hearing / trial": r"final hearing|\btrial\b|bench trial",
    "evidentiary hearing": r"evidentiary hearing",
    "temporary hearing": r"temporary (?:support |relief )?hearing|temporary order",
    "shelter hearing": r"shelter hearing",
    "adjudicatory / disposition hearing": r"adjudicatory hearing|disposition hearing|adjudicatory trial",
    "case management / pretrial": r"case management|pretrial",
    "contempt hearing": r"contempt hearing",
}
HEAR_RX = {k: re.compile(v, re.I) for k, v in HEARINGS.items()}
TRANS = re.compile(r"transcript", re.I)


def doc_id_from_name(name):
    return name[:-4] if name.endswith(".txt") else name


def main():
    # decision records keyed the same way fl_southern_reporter.doc_id() builds file names
    import hashlib
    idx = {}
    for line in (O / "decisions.jsonl").open(encoding="utf-8"):
        d = json.loads(line)
        if d["listing_type"] != "opinions" or not d.get("pdf_uri"):
            continue
        cn = re.sub(r"[^A-Za-z0-9]+", "-", d.get("case_number_raw") or "nocase").strip("-")
        h = hashlib.sha1((d.get("pdf_uri") or "").encode()).hexdigest()[:8]
        idx[f"{cn}_{d.get('decided_date') or 'nodate'}_{d['listing_type']}_{h}"] = d
    cites = {}
    p = O / "FL_SOUTHERN_REPORTER_CITATIONS_FINAL.csv"
    if p.exists():
        for r in csv.DictReader(p.open(encoding="utf-8")):
            cites[r["pdf_uri"]] = r["reporter_cite"]
    rows = []
    scanned = 0
    for court_dir in sorted((O / "text").iterdir()):
        for t in court_dir.glob("*.txt"):
            scanned += 1
            d = idx.get(t.stem)
            if not d:
                continue
            head = t.read_text(encoding="utf-8", errors="ignore")[:6000]
            style = d.get("case_style") or ""
            why = []
            if STYLE.search(style):
                why.append("case style")
            hits = [x.pattern for x in TEXT_RX if x.search(head)]
            if len(hits) >= 2 or (hits and "case style" in why):
                why.append("opinion text: " + ", ".join(h.replace("\\", "") for h in hits[:3]))
            if not why:
                continue
            full = t.read_text(encoding="utf-8", errors="ignore")
            hear = [k for k, rx in HEAR_RX.items() if rx.search(full)]
            rows.append({
                "case_number": d["case_number_raw"], "court": court_dir.name, "decided_date": d["decided_date"],
                "case_style": style, "reporter_cite": cites.get(d.get("pdf_uri"), ""),
                "hearing_types_mentioned": "; ".join(hear),
                "opinion_mentions_transcript": "yes" if TRANS.search(full) else "no",
                "matched_on": " | ".join(why), "pdf_uri": d.get("pdf_uri"),
            })
    out = O / "family_law_cases.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    tr = sum(1 for r in rows if r["opinion_mentions_transcript"] == "yes")
    print(f"scanned {scanned:,} opinions | family-law cases found: {len(rows):,} | opinion mentions a transcript: {tr:,} | with a So. cite: {sum(1 for r in rows if r['reporter_cite']):,} -> {out}")


if __name__ == "__main__":
    main()
