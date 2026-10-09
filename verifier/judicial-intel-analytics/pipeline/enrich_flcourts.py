#!/usr/bin/env python3
"""
Ground truth from the Florida courts' own opinion search API — the endpoint
each DCA's "Opinions" page calls, and the one Free Law's Juriscraper wraps
(juriscraper/opinions/united_states/state/fladistctapp_1.py).

    python3 pipeline/enrich_flcourts.py --channel fl_2dca --since 2019
    python3 pipeline/enrich_flcourts.py --channel fl_6dca --since 2023
    python3 pipeline/enrich_flcourts.py --channel fl_2dca --with-pdf   # panel / trial judge / counsel

Step 1  pulls EVERY decision (written opinions + PCAs) for the district, by
        year, into data/<channel>/flcourts/decisions.jsonl. That file is the
        court's complete disposition list — the base rates — independent of
        which cases were argued on video.
Step 2  joins decisions to videos on case number and writes
        data/<channel>/dockets/<video_id>.json in the same shape
        enrich_dockets.py (CourtListener) uses, so run_oa_panel.py --rebuild-csv
        picks it up unchanged. Existing CourtListener records are kept and the
        flcourts fields fill in alongside them (source column says which).
Step 3  (--with-pdf) downloads the opinion PDF for matched cases and parses
        panel, author, trial judge, county, counsel, dissent with the same
        parser as enrich_dockets.py.

Why this and not the CourtListener API: the CL token is throttled to
100 requests/hour; this is unauthenticated, paged 100 at a time, and returns
the disposition as a field rather than something to regex out of the text.
Politeness: one identifying user-agent, ~2 requests/second, no retries on 4xx.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import date

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import channel_dir, channel_config, parse_case_numbers, format_case_number  # noqa: E402
from enrich_dockets import parse_opinion, classify  # noqa: E402

API = "https://flcourts-media.flcourts.gov/_search/opinions/"
UA = "Mozilla/5.0 (Macintosh) kingsfield-judicial-research/0.1 (contact: aray.aaron@gmail.com)"
SLEEP = 0.5
PAGE = 100

SITE = {  # siteaccess / scope per channel, as Juriscraper has them
    "fl_2dca": ("2dca", "second_district_court_of_appeal"),
    "fl_6dca": ("6dca", "sixth_district_court_of_appeal"),
    "fl_1dca": ("1dca", "first_district_court_of_appeal"),
    "fl_5dca": ("5dca", "fifth_district_court_of_appeal"),
}


def fetch_page(session, site, scope, kind, start, end, offset):
    r = session.get(API, params={
        "siteaccess": site, "scopes": scope, "type": kind, "searchtype": "opinions",
        "startdate": start, "enddate": end, "limit": PAGE, "offset": offset, "query": "",
    }, headers={"User-Agent": UA}, timeout=60)
    r.raise_for_status()
    return r.json()


def normalize(it: dict, kind: str) -> dict:
    c = it.get("content") or {}
    f = c.get("fields") or {}
    dd = ((f.get("disposition_date") or {}).get("date") or {}).get("date")
    op = f.get("opinion") or {}
    return {
        "case_number_raw": f.get("case_number"),
        "case_style": f.get("case_style"),
        "note": f.get("note"),                       # the disposition text
        "opinion_type": f.get("disposition"),        # "Appeal - Authored Opinion", "Appeal - Per Curiam Affirmed", ...
        "opinion_type_label": it.get("opinionTypeLabel"),   # Written / PCA
        "decided_date": dd[:10] if dd else None,
        "pdf_uri": op.get("uri"),
        "pdf_size": op.get("fileSize"),
        "ctrack_id": (f.get("remote_id") or "").split("|")[0] or None,
        "page_url": (c.get("url") or (it.get("link") or {}).get("url")),
        "video_external_link": f.get("video_external_link") or it.get("externalVideoLink") or None,
        "oral_argument_field": f.get("oral_argument"),
        "listing_type": kind,
    }


def pull_decisions(channel: str, since: int, out_path: str) -> int:
    site, scope = SITE[channel]
    seen = set()
    if os.path.exists(out_path):
        for line in open(out_path, encoding="utf-8"):
            try:
                seen.add(json.loads(line)["_key"])
            except Exception:
                pass
    session = requests.Session()
    n_new = 0
    with open(out_path, "a", encoding="utf-8") as outf:
        for year in range(since, date.today().year + 1):
            start, end = f"01/01/{year}", (f"12/31/{year}" if year < date.today().year else date.today().strftime("%m/%d/%Y"))
            for kind in ("opinions", "pca"):
                offset, total = 0, None
                while True:
                    data = fetch_page(session, site, scope, kind, start, end, offset)
                    time.sleep(SLEEP)
                    results = data.get("searchResults") or []
                    total = data.get("totalCount", 0)
                    for it in results:
                        rec = normalize(it, kind)
                        rec["_key"] = f"{rec['case_number_raw']}|{rec['decided_date']}|{kind}"
                        if rec["_key"] in seen:
                            continue
                        seen.add(rec["_key"])
                        outf.write(json.dumps(rec, ensure_ascii=False) + "\n")
                        n_new += 1
                    offset += PAGE
                    if not results or offset >= total:
                        break
                print(f"  {year} {kind:<9} total={total}", flush=True)
    return n_new


DISPO_WORDS = ("affirmed", "reversed", "denied", "dismissed", "granted", "quashed", "vacated", "remanded")


def disposition_text(rec: dict) -> str:
    """The API's `disposition` field is the disposition itself in older records
    ("Affirmed", "Reversed", "Affirmed in Part/Reversed in Part") with `note` as
    a continuation ("and remanded."), and an opinion-type label in 2026 records
    ("Appeal - Authored Opinion") with the disposition in `note`. Reassemble."""
    typ = (rec.get("opinion_type") or "").strip()
    note = (rec.get("note") or "").strip()
    if typ and typ.lower().split()[0].rstrip(".;,") in DISPO_WORDS:
        return (typ + (" " + note if note and not note.startswith("**") else "")).strip()
    if note and not note.startswith("**"):
        return note
    if "Per Curiam Affirmed" in typ or "PC Affirmed" in typ:
        return "Affirmed"
    if "PC Denied" in typ:
        return "Denied"
    return ""


def is_pca_record(rec: dict) -> bool:
    typ = rec.get("opinion_type") or ""
    return rec.get("opinion_type_label") == "PCA" or "Per Curiam Affirmed" in typ or rec.get("listing_type") == "pca"


CASE_KEY_RE = re.compile(r"^\s*(?:[1-6]D)?(\d{2}|\d{4})-(\d{1,5})\s*$")


def case_key(raw: str):
    """(year, seq) from any spelling the API uses: '15-2489', '16-545', '16-36',
    '2016-4714', '2025-1145'. Two-digit years are 20YY."""
    m = CASE_KEY_RE.match(raw or "")
    if not m:
        return None
    y = int(m.group(1))
    return (2000 + y if y < 100 else y, int(m.group(2)))


def load_decisions(path: str) -> dict:
    """{ (2025, 1145): [rec, ...] } — a case can have several entries (rehearing, corrected opinion)."""
    by = {}
    if not os.path.exists(path):
        return by
    for line in open(path, encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        k = case_key(r.get("case_number_raw"))
        if k:
            by.setdefault(k, []).append(r)
    return by


def pick_dispositive(recs: list) -> dict:
    """Prefer the entry with a disposition note; latest date wins among those."""
    with_note = [r for r in recs if disposition_text(r)]
    pool = with_note or recs
    return sorted(pool, key=lambda r: r.get("decided_date") or "")[-1]


def pdf_text(session, uri: str) -> str:
    url = "https://flcourts-media.flcourts.gov" + uri if uri.startswith("/") else uri
    r = session.get(url, headers={"User-Agent": UA}, timeout=120)
    r.raise_for_status()
    time.sleep(SLEEP)
    # pdftotext keeps the layout the parser expects; fall back to pypdf
    try:
        p = subprocess.run(["pdftotext", "-layout", "-", "-"], input=r.content, capture_output=True, timeout=60)
        if p.returncode == 0 and p.stdout.strip():
            return p.stdout.decode("utf-8", "ignore")
    except FileNotFoundError:
        pass
    try:
        from pypdf import PdfReader
        import io
        return "\n".join((pg.extract_text() or "") for pg in PdfReader(io.BytesIO(r.content)).pages)
    except Exception as ex:
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="fl_2dca")
    ap.add_argument("--since", type=int, default=2019, help="first year of decisions to pull")
    ap.add_argument("--skip-pull", action="store_true", help="reuse decisions.jsonl on disk")
    ap.add_argument("--with-pdf", action="store_true", help="download + parse opinion PDFs for matched cases")
    ap.add_argument("--video")
    args = ap.parse_args()

    if args.channel not in SITE:
        sys.exit(f"no siteaccess mapping for {args.channel}; add it to SITE in this script")
    base = channel_dir(args.channel)
    fl_dir = os.path.join(base, "flcourts")
    os.makedirs(fl_dir, exist_ok=True)
    dec_path = os.path.join(fl_dir, "decisions.jsonl")
    tr_dir = os.path.join(base, "transcripts")
    dk_dir = os.path.join(base, "dockets")
    os.makedirs(dk_dir, exist_ok=True)
    prefix = channel_config(args.channel).get("district_prefix", "2D")

    if not args.skip_pull:
        print(f"pulling {args.channel} decisions {args.since}–{date.today().year} from flcourts …")
        n = pull_decisions(args.channel, args.since, dec_path)
        print(f"  {n} new decision records → {dec_path}")

    by_case = load_decisions(dec_path)
    print(f"{sum(len(v) for v in by_case.values())} decision records, {len(by_case)} distinct case numbers")

    vids = sorted(n[: -len(".turns.json")] for n in os.listdir(tr_dir) if n.endswith(".turns.json"))
    if args.video:
        vids = [v for v in vids if v == args.video]
    session = requests.Session()
    matched = pdf_parsed = 0
    for vid in vids:
        doc = json.load(open(os.path.join(tr_dir, f"{vid}.turns.json")))
        title = doc.get("title", "")
        nums = parse_case_numbers(title)
        dp = os.path.join(dk_dir, f"{vid}.json")
        rec = json.load(open(dp)) if os.path.exists(dp) else {"video_id": vid, "title": title, "found": False}
        rec["case_numbers_all"] = [format_case_number(prefix, y, s) for y, s in nums]
        hit = None
        for y, s in nums:
            if (y, s) in by_case:
                hit = pick_dispositive(by_case[(y, s)])
                rec["case_number"] = format_case_number(prefix, y, s)
                break
        if hit:
            matched += 1
            rec.update({
                "found": True,
                "source": ("courtlistener+flcourts" if rec.get("cl_opinion_id") else "flcourts"),
                "case_name": hit.get("case_style") or rec.get("case_name"),
                "decided_date": hit.get("decided_date") or rec.get("decided_date"),
                "disposition_text": disposition_text(hit) or rec.get("disposition_text"),
                "disposition": classify(disposition_text(hit)) if disposition_text(hit) else rec.get("disposition", "unknown"),
                "opinion_type": hit.get("opinion_type"),
                "is_pca": is_pca_record(hit),
                "per_curiam": rec.get("per_curiam") if rec.get("per_curiam") is not None else ("Per Curiam" in (hit.get("opinion_type") or "")),
                "flcourts_pdf": hit.get("pdf_uri"),
                "flcourts_page": hit.get("page_url"),
                "ctrack_id": hit.get("ctrack_id"),
                "n_decision_records": len(by_case.get((y, s), [])),
            })
            if args.with_pdf and hit.get("pdf_uri") and not rec.get("panel_judges"):
                text = pdf_text(session, hit["pdf_uri"])
                if text:
                    parsed = parse_opinion(text)
                    for k in ("author", "panel_judges", "dissenting_judges", "special_concurrence_judges",
                              "trial_judge", "county", "appellant_counsel", "appellee_counsel",
                              "has_dissent", "has_special_concurrence", "opinion_chars"):
                        if parsed.get(k) is not None:
                            rec[k] = parsed[k]
                    pdf_parsed += 1
        elif not rec.get("found"):
            rec["source"] = "flcourts:no-match"
        rec["looked_up_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with open(dp, "w", encoding="utf-8") as f:
            json.dump(rec, f, indent=1, ensure_ascii=False)

    print(f"{len(vids)} videos | {matched} matched to a decision ({100*matched/max(1,len(vids)):.0f}%)"
          + (f" | {pdf_parsed} PDFs parsed" if args.with_pdf else ""))
    # base rates for the whole court, argued or not
    from collections import Counter
    disp = Counter(classify(disposition_text(pick_dispositive(v))) for v in by_case.values())
    print("court-wide disposition base rates:", dict(disp.most_common()))


if __name__ == "__main__":
    main()
