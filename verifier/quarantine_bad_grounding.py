#!/usr/bin/env python3
"""
Quarantine mis-resolved groundings in results_full.json.

WHY
---
The benchmark has two grounding routes:

  * MCP `opinion_view` (52 entries) — 88.5% verified, median fuzzy score 100.0
  * old REST pipeline (87 entries)  — 80.5% not_found, median fuzzy score 52.8

That is not a data difference, it is a resolver bug. The REST route wrote
`cl_url` values with CourtListener cluster IDs in the 10.2M-10.7M range, which
are 2025-2026 filings. Entries citing e.g. 293 U.S. 474 (1935) or 378 U.S. 368
(1964) cannot resolve there. Spot-checking confirms it: an AEDPA-deference quote
was matched against an Oklahoma sheriff's-sale opinion, an adoptive-admission
quote against a Title VII retaliation opinion.

So the headline "139 grounded (7.0%)" is wrong in a way that matters: 87 of
those 139 were scored against the wrong case. Their low fuzzy scores are an
artifact of comparing a quote to an unrelated opinion, and they were dragging
the reported grounding quality down.

WHAT THIS DOES
--------------
Conservative and reversible. Nothing is deleted.

  * backs up results_full.json first
  * moves the bad `verification` block to `verification_quarantined`
  * sets opinion_found = False and grounding_status = "needs_refetch"
  * records why, so the entry re-enters the fetch queue
  * writes quarantine_report.json for audit

After this, `python3 ground.py --report` reports the honest number, and
re-fetching via the MCP route (which works) will re-ground these properly.

Usage:
    python3 quarantine_bad_grounding.py --dry-run   # show what would change
    python3 quarantine_bad_grounding.py             # apply
"""
import json, os, re, shutil, sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results_full.json")
REPORT = os.path.join(HERE, "quarantine_report.json")

GOOD_ROUTE = "mcp_opinion_view"
REASON = ("REST-route citation resolver mapped historical reporter cites to "
          "2025-2026 CourtListener clusters; quote was scored against an "
          "unrelated opinion")


def cluster_id(url):
    m = re.search(r"/opinion/(\d+)/", url or "")
    return int(m.group(1)) if m else None


def main():
    dry = "--dry-run" in sys.argv
    data = json.load(open(RESULTS))

    suspect = []
    for e in data:
        if not e.get("opinion_found"):
            continue
        v = e.get("verification") or {}
        if v.get("matched_via") == GOOD_ROUTE:
            continue
        suspect.append(e)

    print(f"entries               : {len(data)}")
    print(f"currently grounded    : {sum(1 for e in data if e.get('opinion_found'))}")
    print(f"good route ({GOOD_ROUTE}) : "
          f"{sum(1 for e in data if (e.get('verification') or {}).get('matched_via') == GOOD_ROUTE)}")
    print(f"to quarantine         : {len(suspect)}")

    if not suspect:
        print("nothing to do.")
        return

    ids = [c for c in (cluster_id(e.get("cl_url")) for e in suspect) if c]
    if ids:
        print(f"  their cl_url cluster IDs: min={min(ids)} max={max(ids)}")

    if dry:
        print("\n--dry-run: no changes written. Sample:")
        for e in suspect[:5]:
            print(f"  [{e['idx']}] {e['term'][:38]:<40} cites={e['all_cites']} "
                  f"score={(e.get('verification') or {}).get('score')}")
        return

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = f"{RESULTS}.bak.{stamp}"
    shutil.copy2(RESULTS, backup)
    print(f"\nbackup written: {os.path.basename(backup)}")

    report = []
    for e in suspect:
        v = e.pop("verification", None)
        report.append({
            "idx": e["idx"],
            "term": e.get("term"),
            "all_cites": e.get("all_cites"),
            "bad_cl_url": e.get("cl_url"),
            "bad_cluster_id": cluster_id(e.get("cl_url")),
            "discarded_verification": v,
        })
        e["verification_quarantined"] = v
        e["verification"] = None
        e["opinion_found"] = False
        e["grounding_status"] = "needs_refetch"
        e["quarantine_reason"] = REASON
        e.pop("grounded_verdict", None)
        e["cl_url"] = None
        e["cl_cluster"] = None

    json.dump(data, open(RESULTS, "w"), indent=1)
    json.dump({"quarantined_at": datetime.now().isoformat(timespec="seconds"),
               "reason": REASON, "count": len(report), "entries": report},
              open(REPORT, "w"), indent=2)

    grounded = sum(1 for e in data if e.get("opinion_found"))
    print(f"quarantined           : {len(report)} -> quarantine_report.json")
    print(f"grounded after        : {grounded}/{len(data)} ({100*grounded/len(data):.1f}%)")
    print(f"re-fetch queue        : {len(report)} entries flagged needs_refetch")


if __name__ == "__main__":
    main()
