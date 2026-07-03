#!/usr/bin/env python3
"""
Kingsfield grounding harness.

Grounds benchmark quotes against REAL CourtListener opinion text.

Design note (why this exists):
The original pipeline called the CourtListener REST API directly from Python and
kept failing on rate limits / transient errors, so only 87 / 1,979 entries (4.4%)
ever got grounded. This harness decouples *fetching* from *matching*:

  - Fetching is done by the agent via the CourtListener MCP `opinion_view` tool
    (which routes through working infrastructure) and cached to opinion_cache/<slug>.txt
  - Matching is done here, deterministically and reproducibly, with fuzzy scoring.

Because fetch and match are decoupled, the job is fully RESUMABLE: drop more
<slug>.txt files into opinion_cache/ and re-run. Already-grounded entries are skipped.

Usage:
    python3 ground.py            # match everything cached, update results_full.json
    python3 ground.py --report   # just print coverage, change nothing
"""
import json, re, os, sys, glob

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results_full.json")
CACHE_DIR = os.path.join(HERE, "opinion_cache")
CITE_MAP = os.path.join(HERE, "cite_to_entries.json")

try:
    from rapidfuzz import fuzz
except ImportError:
    sys.exit("rapidfuzz not installed: pip install rapidfuzz --break-system-packages")

# ---- thresholds (mirror dataset README schema) ----
VERIFIED = 80   # >=80 fuzzy -> 'verified'  -> grounded verdict 'yes'
FUZZY    = 55   # 55-79      -> 'fuzzy'     -> grounded verdict 'unsure'
                # <55        -> 'not_found' -> grounded verdict 'no'

def cite_to_slug(cite):
    return re.sub(r"[^A-Za-z0-9]+", "_", cite.strip()).strip("_")

def strip_html(t):
    t = re.sub(r"<[^>]+>", " ", t)          # drop tags
    t = re.sub(r"&amp;", "&", t)
    t = re.sub(r"&[a-z]+;", " ", t)
    return t

def norm(t):
    t = strip_html(t)
    t = t.replace("‘", "'").replace("’", "'")
    t = t.replace("“", '"').replace("”", '"')
    t = t.replace("—", "-").replace("–", "-")
    t = re.sub(r"[^a-z0-9 ]+", " ", t.lower())
    t = re.sub(r"\s+", " ", t).strip()
    return t

def best_score(quote, body):
    """Best fuzzy alignment of `quote` anywhere in `body`."""
    q = norm(quote)
    if not q:
        return 0.0, ""
    b = norm(body)
    if not b:
        return 0.0, ""
    # partial_ratio finds best substring alignment; token_set_ratio is order-robust
    s1 = fuzz.partial_ratio(q, b)
    s2 = fuzz.token_set_ratio(q, b)
    score = max(s1, s2)
    # pull a short passage around the best partial-ratio window for the record
    passage = ""
    qi = q.split()
    if qi:
        anchor = qi[0]
        pos = b.find(anchor)
        if pos >= 0:
            passage = b[pos:pos + max(len(q) + 40, 80)]
    return round(float(score), 1), passage[:300]

def status_for(score):
    if score >= VERIFIED: return "verified", "yes"
    if score >= FUZZY:    return "fuzzy", "unsure"
    return "not_found", "no"

def load_cache():
    cache = {}
    for path in glob.glob(os.path.join(CACHE_DIR, "*.txt")):
        slug = os.path.splitext(os.path.basename(path))[0]
        with open(path, encoding="utf-8", errors="ignore") as f:
            cache[slug] = f.read()
    return cache

def main():
    report_only = "--report" in sys.argv
    data = json.load(open(RESULTS))
    by_idx = {e["idx"]: e for e in data}

    grounded = sum(1 for e in data if e.get("opinion_found"))
    if report_only:
        print(f"total={len(data)} grounded={grounded} ({grounded/len(data)*100:.1f}%)")
        return

    cache = load_cache()
    if not cache:
        print("opinion_cache/ is empty — nothing to match yet.")
        print(f"current coverage: {grounded}/{len(data)} ({grounded/len(data)*100:.1f}%)")
        return

    cite_map = json.load(open(CITE_MAP)) if os.path.exists(CITE_MAP) else {}
    # invert: slug -> cite -> entry idxs
    slug_to_idxs = {}
    for cite, idxs in cite_map.items():
        slug_to_idxs.setdefault(cite_to_slug(cite), []).extend(idxs)

    newly = 0
    for slug, body in cache.items():
        idxs = slug_to_idxs.get(slug, [])
        for idx in idxs:
            e = by_idx.get(idx)
            if not e or e.get("opinion_found"):
                continue
            score, passage = best_score(e.get("quote", ""), body)
            st, verdict = status_for(score)
            e["opinion_found"] = True
            e["source"] = "courtlistener"
            e["verification"] = {
                "score": score, "status": st, "passage": passage,
                "matched_via": "mcp_opinion_view",
            }
            e["grounded_verdict"] = verdict
            newly += 1

    json.dump(data, open(RESULTS, "w"), indent=1)
    grounded2 = sum(1 for e in data if e.get("opinion_found"))
    print(f"cached opinions: {len(cache)}")
    print(f"newly grounded entries: {newly}")
    print(f"coverage: {grounded} -> {grounded2} / {len(data)} ({grounded2/len(data)*100:.1f}%)")
    # verdict breakdown among grounded-by-text
    vb = {}
    for e in data:
        if (e.get("verification") or {}).get("matched_via") == "mcp_opinion_view":
            v = e.get("grounded_verdict", "?"); vb[v] = vb.get(v, 0) + 1
    print("grounded verdict breakdown:", vb)

if __name__ == "__main__":
    main()
