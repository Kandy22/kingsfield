#!/usr/bin/env python3
"""
Kingsfield — Batch Citation Lookup
Sends ALL citations in ONE request to CourtListener citation-lookup API.
Gets cluster IDs + absolute URLs back. Then fetches opinion text via sub_opinions.
No per-entry search calls — dramatically fewer API calls.
"""
import json, os, re, time
import requests
from rapidfuzz import fuzz
from datetime import datetime

CL_TOKEN      = os.environ.get("CL_TOKEN", "")
HEADERS       = {"User-Agent": "Kingsfield/1.0", "Authorization": f"Token {CL_TOKEN}"}
INPUT_JSON    = "results.json"
THRESHOLD_V   = 80
THRESHOLD_F   = 55
PASSAGE_CHARS = 1500
DELAY         = 1.0

def cl_get(url, retries=4):
    """Robust GET with retry on 429, backs off properly."""
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                return r.json()
            elif r.status_code == 429:
                wait = int(r.headers.get('Retry-After', 30)) + 5
                print(f"    [429 — waiting {wait}s (attempt {attempt+1}/{retries})]")
                time.sleep(wait)
            elif r.status_code in (500, 502, 503):
                time.sleep(15)
            else:
                return None
        except Exception as e:
            print(f"    [network error: {e}]")
            time.sleep(10)
    return None

def get_opinion_text(cluster_id):
    """Follow sub_opinions from cluster — correct per CL docs."""
    try:
        cluster = cl_get(f"https://www.courtlistener.com/api/rest/v4/clusters/{cluster_id}/")
        if not cluster:
            return None
        sub_opinions = cluster.get('sub_opinions', [])
        time.sleep(DELAY)
        for url in sub_opinions[:3]:
            op = cl_get(url)
            time.sleep(DELAY)
            if not op:
                continue
            for field in ['html_with_citations','html_columbia','html_lawbox',
                          'xml_harvard','html','plain_text']:
                text = op.get(field) or ''
                if text:
                    text = re.sub(r'<[^>]+>', ' ', text)
                    text = re.sub(r'\s+', ' ', text).strip()
                    if len(text) > 300:
                        return text[:80000]
    except Exception as e:
        print(f"    [error: {e}]")
    return None

def normalize(t):
    t = re.sub(r'\[.*?\]', ' ', t)
    t = re.sub(r'\.\s*\.\s*\.', ' ', t)
    t = re.sub(r'[^\w\s]', ' ', t)
    return re.sub(r'\s+', ' ', t).lower().strip()

def fuzzy_verify(quote, opinion_text):
    if not opinion_text or not quote:
        return {'score': 0, 'status': 'no_text', 'passage': None}
    nq, no = normalize(quote), normalize(opinion_text)
    if len(nq) < 15:
        return {'score': 0, 'status': 'quote_too_short', 'passage': None}
    qlen = len(nq); step = max(5, qlen // 4)
    best_score, best_pos = 0, 0
    for i in range(0, max(1, len(no) - qlen + 1), step):
        s = fuzz.partial_ratio(nq[:120], no[i:i + qlen + 40])
        if s > best_score: best_score, best_pos = s, i
    for i in range(max(0, best_pos - step), min(len(no), best_pos + step + 1)):
        s = fuzz.partial_ratio(nq[:120], no[i:i + qlen + 40])
        if s > best_score: best_score, best_pos = s, i
    ratio = len(opinion_text) / max(len(no), 1)
    raw_pos = int(best_pos * ratio)
    start = max(0, raw_pos - PASSAGE_CHARS // 2)
    passage = opinion_text[start:start + PASSAGE_CHARS].strip()
    status = 'verified' if best_score >= THRESHOLD_V else \
             'fuzzy' if best_score >= THRESHOLD_F else 'not_found'
    return {'score': round(best_score, 1), 'status': status, 'passage': passage}

def main():
    print("="*60)
    print("KINGSFIELD — BATCH CITATION LOOKUP")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)

    with open(INPUT_JSON) as f:
        results = json.load(f)

    # Find entries with cluster but no opinion text
    no_text = [r for r in results if r.get('cl_cluster') and not r.get('opinion_found')]
    print(f"\nEntries with cluster but no text: {len(no_text)}")

    if not no_text:
        print("Nothing to do.")
        return

    # Build ONE text blob with all citations for batch lookup
    # Format: "TERM: citation1, citation2"
    lines = []
    for r in no_text:
        cites = ' '.join(r.get('all_cites', [])[:3])
        if r.get('primary_cite_pair'):
            cites = r['primary_cite_pair'][1] + ' ' + cites
        if cites.strip():
            lines.append(cites.strip())

    text_blob = '\n'.join(lines)
    print(f"Sending {len(lines)} citation lines in ONE request...")
    print(f"Text blob size: {len(text_blob)} chars\n")

    # Single batch request — counts as ONE API call
    try:
        r = requests.post(
            "https://www.courtlistener.com/api/rest/v4/citation-lookup/",
            headers=HEADERS,
            data={'text': text_blob},
            timeout=30
        )
        print(f"Batch lookup status: {r.status_code}")
        if r.status_code == 429:
            wait = int(r.headers.get('Retry-After', 60))
            print(f"Still rate limited — wait {wait}s ({wait//60} min)")
            return
        if r.status_code != 200:
            print(f"Error: {r.text[:300]}")
            return
        citations_found = r.json()
        print(f"Citations resolved: {len(citations_found)}\n")
    except Exception as e:
        print(f"Batch request failed: {e}")
        return

    # Build map: normalized citation string → cluster data
    cite_map = {}
    for item in citations_found:
        if not isinstance(item, dict): continue
        cite_str = item.get('citation','')
        cluster = item.get('cluster') or {}
        cluster_id = cluster.get('id') or item.get('cluster_id')
        abs_url = cluster.get('absolute_url','') or item.get('absolute_url','')
        if cluster_id:
            cite_map[cite_str] = {
                'cluster_id': cluster_id,
                'cl_url': f"https://www.courtlistener.com{abs_url}" if abs_url else f"https://www.courtlistener.com/opinion/{cluster_id}/"
            }

    print(f"Mapped {len(cite_map)} citations to clusters\n")

    # Build results index
    idx_map = {r['term']: i for i, r in enumerate(results)}
    total = len(no_text)
    updated = 0

    for j, entry in enumerate(no_text, 1):
        term = entry['term']
        cluster_id = entry.get('cl_cluster')
        ri = idx_map.get(term)
        if ri is None: continue

        print(f"  [{j}/{total}] {term[:50]}")

        # Get opinion text via sub_opinions
        opinion_text = get_opinion_text(cluster_id)

        if opinion_text:
            verification = fuzzy_verify(entry['quote'], opinion_text)
            results[ri]['opinion_found'] = True
            results[ri]['verification'] = verification
            s = verification['score']
            st = verification['status']
            print(f"         → {s:.1f} {st}")
        else:
            print(f"         → still no text")

        # Update cl_url from batch map if available
        for cite_str, data in cite_map.items():
            if data['cluster_id'] == cluster_id:
                results[ri]['cl_url'] = data['cl_url']
                break

        updated += 1

        # Save every 10
        if updated % 10 == 0:
            with open(INPUT_JSON, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"    [saved at {updated}]")

    with open(INPUT_JSON, 'w') as f:
        json.dump(results, f, indent=2)

    verified = sum(1 for r in results if r.get('verification',{}).get('status')=='verified')
    fuzzy    = sum(1 for r in results if r.get('verification',{}).get('status')=='fuzzy')
    nf       = sum(1 for r in results if r.get('verification',{}).get('status')=='not_found')
    no_t     = sum(1 for r in results if r.get('cl_cluster') and not r.get('opinion_found'))

    print(f"\nDone. Updated {updated} entries.")
    print(f"Verified: {verified} | Fuzzy: {fuzzy} | Not found: {nf} | Still no text: {no_t}")

if __name__ == '__main__':
    main()
