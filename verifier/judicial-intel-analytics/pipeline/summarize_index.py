#!/usr/bin/env python3
"""Summarize a channel index.json: how many videos look like single-case arguments
(title carries a case number like 5D2024-1234) vs sessions/ceremonies, and the date span."""
import json, os, re, sys, collections
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for ch in sys.argv[1:]:
    p = os.path.join(ROOT, "data", ch, "index.json")
    if not os.path.exists(p):
        print(f"{ch}: no index"); continue
    v = json.load(open(p))["videos"]
    cn = re.compile(r"\b(?:[1-6]D\s?)?(?:19|20)?\d{2}[-\s‑–]\d{3,5}\b", re.I)  # 2D2024-1234, 24-2509, "25 1145"
    one = [x for x in v if len(cn.findall(x.get("title") or "")) == 1]
    many = [x for x in v if len(cn.findall(x.get("title") or "")) > 1]
    dates = sorted(x["upload_date"] for x in v if x.get("upload_date"))
    yrs = collections.Counter((x.get("upload_date") or "????")[:4] for x in one)
    durs = sorted(x["duration"] for x in v if x.get("duration"))
    print(f"{ch}: {len(v)} videos | one case number in title: {len(one)} | several: {len(many)} | none: {len(v)-len(one)-len(many)}")
    print(f"   dates {dates[0] if dates else '?'} to {dates[-1] if dates else '?'} | median length {durs[len(durs)//2]//60 if durs else '?'} min")
    print(f"   single-case by year: {dict(sorted(yrs.items()))}")
    for x in v[:6]:
        print(f"   e.g. {(x.get('title') or '')[:90]}")
