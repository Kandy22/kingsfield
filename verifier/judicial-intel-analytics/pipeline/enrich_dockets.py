#!/usr/bin/env python3
"""
Resolve each argued case to its decision on CourtListener and extract the
ground-truth fields the YouTube index lacks: case name, disposition, panel,
author, trial judge, county, counsel, dissent. Resumable.

    export CL_TOKEN=...            (Verifier/.env has it)
    python3 pipeline/enrich_dockets.py --channel fl_2dca
    python3 pipeline/enrich_dockets.py --channel fl_2dca --video eLU5je2C12I

Reads : data/<channel>/transcripts/<id>.turns.json   (for the title / case number)
Writes: data/<channel>/dockets/<video_id>.json         one per video, incl. misses
        data/<channel>/dockets/dockets.csv             flat join table

Why CourtListener and not Google Scholar: Scholar has no API and blocks
scraping; CourtListener ingests the 2DCA opinion feed including one-line
PCAs ("Affirmed."), so affirmances are not under-counted, and it has a
documented, tokened REST API.

Case-number formats. The court switched to a four-digit year in 2023 and
CourtListener stores the two styles differently:
    "25 1145"   -> 2D2025-1145                (new style, prefix kept)
    "2D19 852"  -> 19-0852                    (old style, prefix dropped, zero-padded)
Old-style numbers collide across the five DCAs, so every hit is checked for
"SECOND DISTRICT" in the opinion text before it is accepted.
"""
import argparse
import csv
import json
import os
import re
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import channel_dir, channel_config, parse_case_numbers, format_case_number  # noqa: E402

CL = "https://www.courtlistener.com/api/rest/v4"
COURT = "fladistctapp"
# This token is throttled to 100 requests/hour (the API says so in its 429
# body). One request per video, spaced to stay just under that. A CourtListener
# membership raises the limit: https://donate.free.law/forms/membership
SLEEP = 37.0


def case_candidates(title: str, prefix: str) -> list:
    """All case numbers in a title (consolidated appeals have two), each with
    the docket-number spellings to try, most likely first."""
    out = []
    for year, num in parse_case_numbers(title):
        yy = f"{year % 100:02d}"
        # every hit so far matched the first spelling; a miss costs one request per
        # spelling against a 100/hour budget, so keep the list short
        if year >= 2023:
            cands = [format_case_number(prefix, year, num), f"{year}-{num:04d}"]
        else:
            cands = [f"{yy}-{num:04d}", f"{prefix}{yy}-{num:04d}"]
        out.append({"case_number": format_case_number(prefix, year, num), "year": year, "seq": num, "try": cands})
    return out


# ---- opinion text parsing --------------------------------------------------

DISPO_RE = re.compile(
    r"^\s*((?:Affirmed|Reversed|Dismissed|Denied|Granted|Quashed|Vacated|Remanded|Petition (?:denied|granted|dismissed))"
    r"[^\n]{0,160}?\.)\s*$", re.M)
# "LUCAS, C.J., and KELLY and SMITH, JJ., Concur."  /  "KELLY, J., Concurs specially."
# "LABRIT, J., Dissents with opinion."  — any line whose verb is concur/dissent
# Two cheap steps instead of one clever regex (a nested quantifier here
# backtracked exponentially on all-caps citation lines): find short lines whose
# verb is Concur/Dissent, then require the prefix to be an all-caps name list
# with mandatory separators.
VERB_LINE_RE = re.compile(r"^\s*(.{1,140}?)\s*,?\s*\b(Concur|Dissent)[a-z]*\.?(.*)$")
NAME_LIST_RE = re.compile(r"^[A-Z][A-Z.'\-]*(?:(?:,\s*|\s+)(?:and\s+)?[A-Z][A-Z.'\-]*)*$")
TITLE_TOKEN_RE = re.compile(
    r"\b(?:C\.\s?J\.|JJ\.|J\.|Judges?|Senior Judge|Associate (?:Senior )?Judge)(?![A-Za-z])", re.I)


def panel_lines(text: str):
    """Yield (names, rest) for every 'X, Y, and Z, JJ., Concur.' style line."""
    for line in text.splitlines():
        m = VERB_LINE_RE.match(line)
        if not m:
            continue
        prefix = m.group(1).strip()
        if not NAME_LIST_RE.match(prefix):
            continue
        yield prefix, m.group(3)
AUTHOR_RE = re.compile(r"^\s*([A-Z][A-Z .'\-]+?),\s+(?:Judge|J\.)\.?\s*$", re.M)
PER_CURIAM_RE = re.compile(r"^\s*PER CURIAM\.", re.M)
TRIAL_RE = re.compile(r"Appeal from the (?:Circuit|County) Court for (\w[\w .]+?) County;\s*(.+?),\s*(?:Acting\s+)?(?:Judge|Senior Judge)", re.S)
DISSENT_RE = re.compile(r"\b(dissent(?:s|ing)?)\b", re.I)
SPECIAL_RE = re.compile(r"concur(?:s|ring)?\s+(?:specially|in result|in part)", re.I)
APPELLANT_COUNSEL_RE = re.compile(r"^(.+?),?\s+for Appellants?\.", re.M | re.S)
APPELLEE_COUNSEL_RE = re.compile(r"^(.+?),?\s+for Appellees?", re.M | re.S)
HEADER_END_RE = re.compile(r"\n(PER CURIAM\.|[A-Z][A-Z .'\-]+, (?:Judge|J)\.)", re.M)


CAPTION_RE = re.compile(r"SECOND DISTRICT\s*\n(.+?)\n\s*(?:Appellants?|Petitioners?),?\s*\n\s*v\.\s*\n(.+?)\n\s*(?:Appellees?|Respondents?)\.?", re.S)
CASENO_DATE_RE = re.compile(r"No\.\s*(\S+)\s*\n\s*\n?\s*([A-Z][a-z]+ \d{1,2}, \d{4})")
MONTHS = {m: i for i, m in enumerate(["January","February","March","April","May","June","July","August","September","October","November","December"], 1)}


def _short_party(block: str) -> str:
    first = " ".join(block.strip().split("\n")[0].split())
    return first.rstrip(",").strip()


def parse_caption(text: str) -> dict:
    out = {"case_name": None, "decided_date": None, "docket_in_text": None}
    m = CAPTION_RE.search(text[:3000])
    if m:
        out["case_name"] = f"{_short_party(m.group(1))} v. {_short_party(m.group(2))}"
    m = CASENO_DATE_RE.search(text[:3000])
    if m:
        out["docket_in_text"] = m.group(1)
        try:
            mon, day, year = m.group(2).replace(",", "").split()
            out["decided_date"] = f"{year}-{MONTHS[mon]:02d}-{int(day):02d}"
        except Exception:
            pass
    return out


def classify(dispo: str) -> str:
    d = (dispo or "").lower()
    if not d:
        return "unknown"
    if "in part" in d and ("revers" in d or "vacat" in d):
        return "mixed"
    if d.startswith(("reversed", "vacated", "quashed", "remanded")):
        return "reverse"
    if d.startswith("affirmed"):
        return "affirm"
    if d.startswith(("dismissed", "petition dismissed")):
        return "dismissed"
    if d.startswith(("denied", "petition denied")):
        return "denied"
    if d.startswith(("granted", "petition granted")):
        return "granted"
    return "other"


def parse_opinion(text: str) -> dict:
    out = {}
    # the last disposition-shaped line is the operative one
    dispos = DISPO_RE.findall(text)
    out["disposition_text"] = dispos[-1].strip() if dispos else None
    out["disposition"] = classify(out["disposition_text"])
    out["per_curiam"] = bool(PER_CURIAM_RE.search(text))
    m = AUTHOR_RE.search(text)
    out["author"] = " ".join(m.group(1).split()).title() if m and not out["per_curiam"] else None
    judges = [out["author"]] if out["author"] else []
    dissenters, special = [], []
    for names, rest in panel_lines(text[-4000:]):
        cleaned = TITLE_TOKEN_RE.sub("", names)
        found = [" ".join(j.split()).title() for j in re.split(r",|\band\b", cleaned) if j.strip()]
        judges += found
        if "dissent" in rest.lower() or re.search(r"dissent", names, re.I):
            dissenters += found
        if "specially" in rest.lower() or "in result" in rest.lower():
            special += found
    out["panel_judges"] = "; ".join(dict.fromkeys(judges)) or None
    out["dissenting_judges"] = "; ".join(dict.fromkeys(dissenters)) or None
    out["special_concurrence_judges"] = "; ".join(dict.fromkeys(special)) or None
    m = TRIAL_RE.search(text)
    out["county"] = " ".join(m.group(1).split()) if m else None
    out["trial_judge"] = " ".join(m.group(2).split()) if m else None
    body_start = HEADER_END_RE.search(text)
    header = text[: body_start.start()] if body_start else text[:3000]
    m = APPELLANT_COUNSEL_RE.search(header)
    out["appellant_counsel"] = " ".join(m.group(1).split())[-300:] if m else None
    m = APPELLEE_COUNSEL_RE.search(header)
    out["appellee_counsel"] = " ".join(m.group(1).split())[-300:] if m else None
    tail = text[-1500:]
    out["has_dissent"] = bool(DISSENT_RE.search(tail))
    out["has_special_concurrence"] = bool(SPECIAL_RE.search(tail))
    out["is_pca"] = out["per_curiam"] and out["disposition"] == "affirm" and len(text.strip()) < 2500
    out["opinion_chars"] = len(text)
    return out


# ---- CourtListener ---------------------------------------------------------

def cl_get(session, url, params, token):
    for attempt in range(10):
        r = session.get(url, params=params, headers={"Authorization": f"Token {token}"}, timeout=60)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429:
            wait = int(r.headers.get("retry-after", "5") or 5) + 1
            time.sleep(wait)
            continue
        if r.status_code in (500, 502, 503, 504):
            time.sleep(2 ** attempt)
            continue
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    raise RuntimeError("exhausted retries")


def find_decision(session, token, cand: dict, district_name: str = "SECOND DISTRICT") -> dict:
    """One request per spelling: the opinions endpoint filtered through the
    docket returns the text directly. Accept the first result whose text says
    SECOND DISTRICT (old-style numbers collide across the five DCAs)."""
    tried = []
    for dn in cand["try"]:
        tried.append(dn)
        res = cl_get(session, f"{CL}/opinions/", {
            "cluster__docket__court": COURT,
            "cluster__docket__docket_number": dn,
            "fields": "id,cluster,type,per_curiam,plain_text,html_with_citations",
        }, token)
        time.sleep(SLEEP)
        hits = []
        for op in res.get("results", []):
            text = op.get("plain_text") or re.sub(r"<[^>]+>", " ", op.get("html_with_citations") or "")
            if district_name.upper() not in text.upper()[:1500]:
                continue
            hits.append((op, text))
        if not hits:
            continue
        # a cluster can hold majority + dissent as separate opinions; take the one with the disposition
        hits.sort(key=lambda h: (bool(DISPO_RE.search(h[1])), len(h[1])), reverse=True)
        op, text = hits[0]
        cluster_url = op.get("cluster") or ""
        cluster_id = re.search(r"/clusters/(\d+)/", cluster_url)
        parsed = parse_opinion(text)
        cap = parse_caption(text)
        return {
            "found": True,
            "matched_docket_number": cap["docket_in_text"] or dn,
            "case_name": cap["case_name"],
            "decided_date": cap["decided_date"],
            "cl_cluster_id": int(cluster_id.group(1)) if cluster_id else None,
            "cl_opinion_id": op.get("id"),
            "cl_url": f"https://www.courtlistener.com/opinion/{cluster_id.group(1)}/x/" if cluster_id else None,
            "n_opinions_in_cluster": len(res.get("results", [])),
            **parsed,
            "_tried": tried,
        }
    return {"found": False, "_tried": tried}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="fl_2dca")
    ap.add_argument("--video")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--rebuild-csv", action="store_true")
    args = ap.parse_args()

    token = os.environ.get("CL_TOKEN")
    if not token and not args.rebuild_csv:
        sys.exit("CL_TOKEN not set (see Verifier/.env)")

    base = channel_dir(args.channel)
    tr_dir = os.path.join(base, "transcripts")
    out_dir = os.path.join(base, "dockets")
    os.makedirs(out_dir, exist_ok=True)
    cfg = channel_config(args.channel)
    prefix = cfg.get("district_prefix", "2D")
    district_name = cfg.get("district_name", "SECOND DISTRICT")
    scored = set()
    jp = os.path.join(base, "panel", "oa_results.jsonl")
    if os.path.exists(jp):
        for line in open(jp, encoding="utf-8"):
            try:
                scored.add(json.loads(line)["video_id"])
            except Exception:
                pass

    vids = sorted(n[: -len(".turns.json")] for n in os.listdir(tr_dir) if n.endswith(".turns.json"))
    if args.video:
        vids = [v for v in vids if v == args.video]
    def needs_lookup(v):
        p = os.path.join(out_dir, f"{v}.json")
        if args.force or not os.path.exists(p):
            return True
        try:
            return bool(json.load(open(p)).get("error"))   # transient failures retry
        except Exception:
            return True
    todo = [v for v in vids if needs_lookup(v)]
    # already-scored videos first, so the calibration join fills in soonest
    todo.sort(key=lambda v: (v not in scored, v))
    if args.limit:
        todo = todo[: args.limit]

    if not args.rebuild_csv:
        print(f"{len(vids)} transcripts, {len(vids) - len(todo)} already resolved, {len(todo)} to look up "
              f"(~{len(todo) * SLEEP / 3600:.1f} h at {3600 / SLEEP:.0f}/h; district {prefix} / {district_name})")
        session = requests.Session()
        n_found = 0
        for k, vid in enumerate(todo, 1):
            doc = json.load(open(os.path.join(tr_dir, f"{vid}.turns.json")))
            title = doc.get("title", "")
            cands = case_candidates(title, prefix)
            rec = {"video_id": vid, "title": title, "case_number": cands[0]["case_number"] if cands else None,
                   "case_numbers_all": [c["case_number"] for c in cands], "found": False}
            try:
                for cand in cands:
                    hit = find_decision(session, token, cand, district_name)
                    if hit["found"]:
                        rec.update(hit)
                        rec["case_number"] = cand["case_number"]
                        break
                    rec["_tried"] = rec.get("_tried", []) + hit["_tried"]
            except Exception as ex:
                rec["error"] = str(ex)[:300]
            rec["looked_up_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            with open(os.path.join(out_dir, f"{vid}.json"), "w") as f:
                json.dump(rec, f, indent=1, ensure_ascii=False)
            n_found += bool(rec.get("found"))
            if k % 25 == 0 or k == len(todo):
                print(f"  {k}/{len(todo)} looked up, {n_found} found", flush=True)

    # ---- flat table
    rows = []
    for n in sorted(os.listdir(out_dir)):
        if n.endswith(".json"):
            rows.append(json.load(open(os.path.join(out_dir, n))))
    cols = ["video_id", "title", "case_number", "found", "case_name", "decided_date", "disposition",
            "disposition_text", "is_pca", "per_curiam", "author", "panel_judges", "has_dissent",
            "dissenting_judges", "has_special_concurrence", "special_concurrence_judges", "trial_judge", "county", "appellant_counsel", "appellee_counsel",
            "matched_docket_number", "cl_url", "cl_cluster_id", "cl_opinion_id", "opinion_chars", "error"]
    with open(os.path.join(out_dir, "dockets.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    found = [r for r in rows if r.get("found")]
    from collections import Counter
    print(f"\n{len(rows)} videos | {len(found)} decisions found ({100*len(found)/max(1,len(rows)):.0f}%) | "
          f"{sum(1 for r in rows if r.get('error'))} errors")
    if found:
        print("disposition:", dict(Counter(r["disposition"] for r in found)))
        print(f"PCA: {sum(1 for r in found if r.get('is_pca'))}  dissent: {sum(1 for r in found if r.get('has_dissent'))}  "
              f"special concurrence: {sum(1 for r in found if r.get('has_special_concurrence'))}")
        print(f"panel parsed: {sum(1 for r in found if r.get('panel_judges'))}/{len(found)}  "
              f"trial judge parsed: {sum(1 for r in found if r.get('trial_judge'))}/{len(found)}")
    print(f"-> {os.path.join(out_dir, 'dockets.csv')}")


if __name__ == "__main__":
    main()
