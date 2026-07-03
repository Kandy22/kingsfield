#!/usr/bin/env python3
"""
Kingsfield — finish remaining entries.
Uses correct CourtListener API per official docs:
- html_with_citations is the preferred text field
- sub_opinions links from cluster give opinion URLs
- 5000 req/hour authenticated limit
"""
import json, re, time, os, sys
import requests
from rapidfuzz import fuzz
from datetime import datetime

CL_TOKEN      = os.environ.get("CL_TOKEN", "")
HEADERS       = {"User-Agent": "Kingsfield/1.0", "Authorization": f"Token {CL_TOKEN}"}
GH_BASE       = "https://raw.githubusercontent.com/michaeljshowalter/showalters-law-dictionary/main/{}.md"
LETTERS       = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
OUTPUT_JSON   = "results.json"
THRESHOLD_V   = 80
THRESHOLD_F   = 55
PASSAGE_CHARS = 1500
DELAY         = 0.8   # safe at 5000/hr

ANTHROPIC_KEY = os.environ.get("ANTHROPIC_KEY", "")
GEMINI_KEY    = os.environ.get("GEMINI_KEY", "")
OPENAI_KEY    = os.environ.get("OPENAI_KEY", "")

# ── GitHub ────────────────────────────────────────────────────────────────────
def fetch_all():
    entries = []
    for letter in LETTERS:
        try:
            r = requests.get(GH_BASE.format(letter), timeout=15)
            if r.status_code == 200:
                entries.extend(parse_md(r.text))
            time.sleep(0.2)
        except Exception as e:
            print(f"  {letter}: {e}")
    return entries

def parse_md(md_text):
    entries = []
    for block in re.split(r'\n## ', md_text)[1:]:
        lines = block.strip().split('\n')
        term = lines[0].strip()
        body = '\n'.join(lines[1:])
        quotes = re.findall(r'"([^"]{20,500})"', body)
        cites = re.findall(
            r'\b(\d+\s+(?:U\.S\.|S\.\s*Ct\.|F\.\d*[a-z]*|F\.\s*Supp\.?\s*\d*|L\.\s*Ed\.?\s*\d*)\s+\d+)', body)
        full_cites = re.findall(
            r'([A-Z][A-Za-z\s&\.,\']+?v\.\s+[A-Z][A-Za-z\s&\.,\']+?),\s*'
            r'(\d+\s+(?:U\.S\.|S\.\s*Ct\.|F\.\d+[a-z]*|F\.\s*Supp\.?\s*\d*)\s+\d+)', body)
        if quotes and cites:
            entries.append({
                'term': term, 'quote': quotes[0],
                'primary_cite_pair': full_cites[0] if full_cites else None,
                'all_cites': cites[:5]
            })
    return entries

# ── CourtListener — correct per docs ─────────────────────────────────────────
_cl_call_count = 0

def cl_get(url, params=None):
    global _cl_call_count
    _cl_call_count += 1
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                return r.json()
            elif r.status_code == 429:
                wait = int(r.headers.get('Retry-After', 30)) + 5
                print(f"    [429 — waiting {wait}s]")
                time.sleep(wait)
            else:
                return None
        except Exception as e:
            print(f"    [error: {e}]")
            time.sleep(5)
    return None

def get_opinion_text_from_sub_opinions(sub_opinions):
    """Fetch text from sub_opinion URLs — correct method per docs."""
    for url in sub_opinions[:3]:
        data = cl_get(url)
        time.sleep(DELAY)
        if not data:
            continue
        # Per docs: prefer html_with_citations
        for field in ['html_with_citations', 'html_columbia', 'html_lawbox',
                      'xml_harvard', 'html_anon_2020', 'html', 'plain_text']:
            text = data.get(field) or ''
            if text:
                text = re.sub(r'<[^>]+>', ' ', text)
                text = re.sub(r'\s+', ' ', text).strip()
                if len(text) > 300:
                    return text[:80000]
    return None

def find_opinion(case_name, raw_cite):
    """
    Search → get cluster → follow sub_opinions → get html_with_citations.
    Returns (cluster_id, cl_url, opinion_text)
    """
    queries = [q for q in [raw_cite, case_name] if q]
    for q in queries:
        # Search
        data = cl_get("https://www.courtlistener.com/api/rest/v4/search/",
                      {'q': q[:100], 'type': 'o', 'format': 'json'})
        time.sleep(DELAY)
        if not data or not data.get('results'):
            continue

        hit = data['results'][0]
        cluster_id = hit.get('cluster_id') or hit.get('id')
        if not cluster_id:
            continue

        # Build correct URL with slug per docs
        abs_url = hit.get('absolute_url', '')
        cl_url = f"https://www.courtlistener.com{abs_url}" if abs_url else \
                 f"https://www.courtlistener.com/opinion/{cluster_id}/"

        # Get cluster to find sub_opinions
        cluster = cl_get(f"https://www.courtlistener.com/api/rest/v4/clusters/{cluster_id}/")
        time.sleep(DELAY)
        if cluster:
            sub_opinions = cluster.get('sub_opinions', [])
            if sub_opinions:
                text = get_opinion_text_from_sub_opinions(sub_opinions)
                if text:
                    return cluster_id, cl_url, text
        return cluster_id, cl_url, None

    return None, None, None

# ── Fuzzy ─────────────────────────────────────────────────────────────────────
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

# ── Agents ────────────────────────────────────────────────────────────────────
PROMPT = """You are a legal citation verifier.
Term: {term}
Citation: {citation}
Claimed quote: "{quote}"
Does this quote accurately appear in the cited case?
VERDICT: [VERIFIED / REJECT / UNSURE]
REASON: [one sentence]"""

def parse_verdict(text):
    m = re.search(r'VERDICT:\s*(VERIFIED|REJECT|UNSURE)', text, re.I)
    verdict = 'yes' if m and m.group(1).upper()=='VERIFIED' else \
              'no' if m and m.group(1).upper()=='REJECT' else 'unsure'
    m2 = re.search(r'REASON:\s*(.+)', text, re.I)
    return {'verdict': verdict, 'reason': (m2.group(1).strip() if m2 else text[:100])}

def ask_claude(term, quote, citation):
    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 100,
                  "messages": [{"role": "user", "content":
                      PROMPT.format(term=term, quote=quote, citation=citation)}]},
            timeout=20)
        if r.status_code == 200:
            return parse_verdict(r.json()['content'][0]['text'])
    except Exception as e: print(f"  [Claude: {e}]")
    return None

def ask_gemini(term, quote, citation):
    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}",
            json={"contents": [{"parts": [{"text": PROMPT.format(term=term, quote=quote, citation=citation)}]}]},
            timeout=20)
        if r.status_code == 200:
            return parse_verdict(r.json()['candidates'][0]['content']['parts'][0]['text'])
    except Exception as e: print(f"  [Gemini: {e}]")
    return None

def ask_gpt(term, quote, citation):
    try:
        r = requests.post("https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
            json={"model": "gpt-4o-mini", "max_tokens": 100,
                  "messages": [{"role": "user", "content":
                      PROMPT.format(term=term, quote=quote, citation=citation)}]},
            timeout=20)
        if r.status_code == 200:
            return parse_verdict(r.json()['choices'][0]['message']['content'])
    except Exception as e: print(f"  [GPT: {e}]")
    return None

def run_agents(term, quote, citation):
    verdicts = {}
    v = ask_claude(term, quote, citation)
    if v: verdicts['claude'] = v
    time.sleep(0.5)
    v = ask_gemini(term, quote, citation)
    if v: verdicts['gemini'] = v
    time.sleep(0.5)
    v = ask_gpt(term, quote, citation)
    if v: verdicts['gpt'] = v
    time.sleep(0.5)
    return verdicts

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    retry_notext = '--retry-notext' in sys.argv

    print("="*60)
    print("KINGSFIELD — FINISH REMAINING + AGENTS")
    if retry_notext:
        print("Mode: retry no-text entries")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)

    results = []
    if os.path.exists(OUTPUT_JSON):
        with open(OUTPUT_JSON) as f:
            results = json.load(f)
    done_terms = {r['term'] for r in results}
    print(f"\nLoaded: {len(results)} entries")

    if retry_notext:
        # Re-process entries where case was found on CL but no text retrieved
        notext = [r for r in results if r.get('cl_cluster') and not r.get('opinion_found')]
        print(f"No-text entries to retry: {len(notext)}\n")
        if not notext:
            print("Nothing to retry.")
            return
        total = len(results)
        for r in notext:
            term = r['term']
            cite = r['all_cites'][0] if r.get('all_cites') else ''
            case_name = r['primary_cite_pair'][0] if r.get('primary_cite_pair') else None
            cluster_id = r['cl_cluster']
            try:
                # Use the cluster we already know — skip search, go straight to sub_opinions
                cluster = cl_get(f"https://www.courtlistener.com/api/rest/v4/clusters/{cluster_id}/")
                time.sleep(DELAY)
                opinion_text = None
                if cluster:
                    sub_opinions = cluster.get('sub_opinions', [])
                    if sub_opinions:
                        opinion_text = get_opinion_text_from_sub_opinions(sub_opinions)
                if opinion_text:
                    r['opinion_found'] = True
                    r['verification'] = fuzzy_verify(r['quote'], opinion_text)
                    s = r['verification']
                    print(f"  [{r['idx']}/{total}] {term[:48]:48s} {s['score']:5.1f} {s['status']}  [CL calls: {_cl_call_count}]")
                    if s['status'] in ('fuzzy', 'not_found'):
                        r['agent_verdicts'] = run_agents(term, r['quote'], cite)
                else:
                    print(f"  [{r['idx']}/{total}] {term[:48]:48s} still no text  [CL calls: {_cl_call_count}]")
            except Exception as e:
                print(f"  [{r['idx']}/{total}] {term[:48]:48s} ERROR: {e}")
            with open(OUTPUT_JSON, 'w') as f:
                json.dump(results, f, indent=2)
        return

    print("Fetching Showalter entries…")
    all_entries = fetch_all()
    remaining = [e for e in all_entries if e['term'] not in done_terms]
    total = len(all_entries)
    print(f"Remaining: {len(remaining)}\n")

    if not remaining:
        print("All done.")
        return

    start_idx = len(results) + 1

    for i, entry in enumerate(remaining, start=start_idx):
        term = entry['term']
        quote = entry['quote']
        cite = entry['all_cites'][0] if entry['all_cites'] else ''
        case_name = entry['primary_cite_pair'][0] if entry['primary_cite_pair'] else None

        result = {
            'idx': i, 'term': term, 'quote': quote,
            'all_cites': entry['all_cites'],
            'primary_cite_pair': entry['primary_cite_pair'],
            'cl_cluster': None, 'cl_url': None,
            'opinion_found': False, 'verification': None,
            'error': None, 'human_verdict': None, 'agent_verdicts': {}, 'notes': ''
        }

        try:
            cluster_id, cl_url, opinion_text = find_opinion(case_name, cite)
            result['cl_cluster'] = cluster_id
            result['cl_url'] = cl_url
            result['opinion_found'] = bool(opinion_text)

            if opinion_text:
                result['verification'] = fuzzy_verify(quote, opinion_text)
                s = result['verification']
                print(f"  [{i}/{total}] {term[:48]:48s} {s['score']:5.1f} {s['status']}  [CL calls: {_cl_call_count}]")
                if s['status'] in ('fuzzy', 'not_found'):
                    result['agent_verdicts'] = run_agents(term, quote, cite)
            else:
                label = 'no text' if cluster_id else 'not found'
                print(f"  [{i}/{total}] {term[:48]:48s} {label}  [CL calls: {_cl_call_count}]")
                result['agent_verdicts'] = run_agents(term, quote, cite)

        except Exception as e:
            result['error'] = str(e)
            print(f"  [{i}/{total}] {term[:48]:48s} ERROR: {e}")

        results.append(result)
        with open(OUTPUT_JSON, 'w') as f:
            json.dump(results, f, indent=2)

    print(f"\nDone. {len(results)} total in {OUTPUT_JSON}")
    print(f"Total CourtListener API calls this run: {_cl_call_count}")

if __name__ == '__main__':
    main()
