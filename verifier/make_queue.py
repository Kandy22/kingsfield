#!/usr/bin/env python3
"""
Build/refresh fetch_queue.json: the prioritized list of citations still needing
CourtListener grounding. Ordered by number of benchmark entries each citation
unlocks (highest leverage first), with already-cached citations removed.

Run this whenever results_full.json or opinion_cache/ changes. Idempotent.
"""
import json, os, re, glob, collections

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results_full.json")
CACHE_DIR = os.path.join(HERE, "opinion_cache")
QUEUE = os.path.join(HERE, "fetch_queue.json")

def norm(c): return re.sub(r"\s+", " ", (c or "").strip())
def slug(c): return re.sub(r"[^A-Za-z0-9]+", "_", (c or "").strip()).strip("_")

def main():
    data = json.load(open(RESULTS))
    cite_to_entries = collections.defaultdict(list)
    for e in data:
        if e.get("opinion_found"):
            continue
        cites = []
        p = e.get("primary_cite_pair")
        if p and len(p) == 2 and p[1]:
            cites.append(norm(p[1]))
        for c in (e.get("all_cites") or []):
            c = norm(c)
            if c and c not in cites:
                cites.append(c)
        if cites:
            cite_to_entries[cites[0]].append(e["idx"])

    cached = {os.path.splitext(os.path.basename(p))[0]
              for p in glob.glob(os.path.join(CACHE_DIR, "*.txt"))}

    queue = []
    for cite, idxs in cite_to_entries.items():
        if slug(cite) in cached:
            continue
        # only queue citations that look retrievable (a reporter pattern)
        if not re.search(r"\d+\s+[A-Za-z.]+(?:\s*\d?[a-z]+)?\s+\d+", cite):
            continue
        queue.append({"cite": cite, "unlocks": len(idxs), "entry_idxs": idxs})
    queue.sort(key=lambda x: -x["unlocks"])

    json.dump(queue, open(QUEUE, "w"), indent=1)

    # cite_to_entries.json — all citations (grounded or not), for ground.py
    all_cite_map = collections.defaultdict(list)
    for e in data:
        cites = []
        p = e.get("primary_cite_pair")
        if p and len(p) == 2 and p[1]:
            cites.append(norm(p[1]))
        for c in (e.get("all_cites") or []):
            c = norm(c)
            if c and c not in cites:
                cites.append(c)
        if cites:
            all_cite_map[cites[0]].append(e["idx"])
    json.dump(dict(all_cite_map), open(os.path.join(HERE, "cite_to_entries.json"), "w"), indent=1)

    grounded = sum(1 for e in data if e.get("opinion_found"))
    print(f"grounded: {grounded}/{len(data)} ({grounded/len(data)*100:.1f}%)")
    print(f"citations still queued: {len(queue)}  (entries they would unlock: {sum(q['unlocks'] for q in queue)})")
    print(f"top of queue: {[ (q['cite'], q['unlocks']) for q in queue[:8] ]}")

if __name__ == "__main__":
    main()
