#!/usr/bin/env python3
"""
Kingsfield Citation Verifier — complete pipeline
1. Fetches all Showalter entries from GitHub
2. Looks up each on CourtListener (multiple strategies for opinion text)
3. Fuzzy matches quotes against opinion text
4. Saves results.json after every entry (resumable)
5. Optionally runs agent testing (Claude/Gemini/GPT) on flagged entries
"""

import json, re, time, os, sys
import requests
from rapidfuzz import fuzz
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────
CL_BASE       = "https://www.courtlistener.com/api/rest/v4"
GH_BASE       = "https://raw.githubusercontent.com/michaeljshowalter/showalters-law-dictionary/main/{}.md"
CL_TOKEN      = os.environ.get("CL_TOKEN", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_KEY", "")
GEMINI_KEY    = os.environ.get("GEMINI_KEY", "")
OPENAI_KEY    = os.environ.get("OPENAI_KEY", "")

HEADERS_CL    = {"User-Agent": "Kingsfield/1.0", "Authorization": f"Token {CL_TOKEN}"}
LETTERS       = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
TARGET        = 9999
DELAY         = 2.0
THRESHOLD_V   = 80
THRESHOLD_F   = 55
PASSAGE_CHARS = 1500
OUTPUT_JSON   = "results.json"
OUTPUT_TXT    = "report.txt"

# ── GitHub fetch ──────────────────────────────────────────────────────────────
def fetch_entries(target=9999):
    entries = []
    for letter in LETTERS:
        if len(entries) >= target:
            break
        try:
            r = requests.get(GH_BASE.format(letter), timeout=15)
            if r.status_code == 200:
                parsed = parse_md(r.text)
                entries.extend(parsed)
                print(f"  {letter}: {len(parsed)} entries (total: {len(entries)})")
            time.sleep(0.3)
        except Exception as e:
            print(f"  {letter}: {e}")
    return entries[:target]

def parse_md(md_text):
    entries = []
    for block in re.split(r'\n## ', md_text)[1:]:
        lines = block.strip().split('\n')
        term = lines[0].strip()
        body = '\n'.join(lines[1:])
        quotes = re.findall(r'"([^"]{20,500})"', body)
        cites = re.findall(
            r'\b(\d+\s+(?:U\.S\.|S\.\s*Ct\.|F\.\d*[a-z]*|F\.\s*Supp\.?\s*\d*|L\.\s*Ed\.?\s*\d*)\s+\d+)',
            body)
        full_cites = re.findall(
            r'([A-Z][A-Za-z\s&\.,\']+?v\.\s+[A-Z][A-Za-z\s&\.,\']+?),\s*'
            r'(\d+\s+(?:U\.S\.|S\.\s*Ct\.|F\.\d+[a-z]*|F\.\s*Supp\.?\s*\d*)\s+\d+)', body)
        if quotes and cites:
            entries.append({
                'term': term, 'quote': quotes[0], 'all_quotes': quotes[:3],
                'primary_cite_pair': full_cites[0] if full_cites else None,
                'all_cites': cites[:5]
            })
    return entries

# ── CourtListener ─────────────────────────────────────────────────────────────
_cl_call_count = 0

def cl_get(endpoint, params, retries=3):
    global _cl_call_count
    _cl_call_count += 1
    for attempt in range(retries):
        try:
            r = requests.get(f"{CL_BASE}/{endpoint}", params=params,
                             headers=HEADERS_CL, timeout=15)
            if r.status_code == 200:
                return r.json()
            elif r.status_code == 429:
                wait = int(r.headers.get('Retry-After', 30)) + 5
                print(f"    [rate limited — waiting {wait}s]")
                time.sleep(wait)
            elif r.status_code in (500, 502, 503):
                time.sleep(15)
            else:
                return None
        except Exception as e:
            print(f"    [network error: {e}]")
            time.sleep(10)
    return None

def get_opinion_text_from_cluster(cluster_id):
    """Try multiple fields to get opinion text."""
    # Strategy 1: opinions endpoint
    data = cl_get("opinions/", {'cluster': cluster_id, 'format': 'json'})
    time.sleep(DELAY)
    if data:
        for op in data.get('results', []):
            for field in ['plain_text', 'html_with_citations', 'html_columbia',
                          'html_lawbox', 'html', 'xml_harvard']:
                text = op.get(field) or ''
                if text:
                    text = re.sub(r'<[^>]+>', ' ', text)
                    text = re.sub(r'\s+', ' ', text).strip()
                    if len(text) > 300:
                        return text[:80000]
    # Strategy 2: cluster endpoint directly
    data = cl_get(f"clusters/{cluster_id}/", {})
    time.sleep(DELAY)
    if data:
        for field in ['syllabus', 'headnotes', 'summary']:
            text = data.get(field) or ''
            if len(text) > 100:
                return text[:80000]
    return None

def find_opinion(case_name, raw_cite):
    """Return (cluster_id, cl_url, opinion_text)."""
    queries = [q for q in [raw_cite, case_name] if q]
    for q in queries:
        data = cl_get("search/", {'q': q[:100], 'type': 'o', 'format': 'json'})
        time.sleep(DELAY)
        if not data:
            continue
        hits = data.get('results', [])
        if not hits:
            continue
        h = hits[0]
        cluster_id = h.get('cluster_id') or h.get('id')
        cl_url = 'https://www.courtlistener.com' + h.get('absolute_url', '')
        # Try search snippet first
        snippet = re.sub(r'<[^>]+>', ' ', h.get('snippet') or '')
        snippet = re.sub(r'\s+', ' ', snippet).strip()
        if len(snippet) > 200:
            return cluster_id, cl_url, snippet
        # Full text
        text = get_opinion_text_from_cluster(cluster_id)
        if text:
            return cluster_id, cl_url, text
        # no text from this query — try next one
    return None, None, None

# ── Fuzzy match ───────────────────────────────────────────────────────────────
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
    qlen = len(nq)
    step = max(5, qlen // 4)
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
    status = 'verified' if best_score >= THRESHOLD_V else 'fuzzy' if best_score >= THRESHOLD_F else 'not_found'
    return {'score': round(best_score, 1), 'status': status, 'passage': passage}

# ── Agent testing ─────────────────────────────────────────────────────────────
AGENT_PROMPT = """You are a legal citation verifier. Given a legal term, a claimed quote, and its citation, determine if the quote accurately represents what the cited case actually says.

Term: {term}
Citation: {citation}
Claimed quote: "{quote}"

Respond with exactly this format:
VERDICT: [VERIFIED / REJECT / UNSURE]
REASON: [one sentence explanation]"""

def ask_claude(term, quote, citation):
    if not ANTHROPIC_KEY:
        return None
    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 150,
                  "messages": [{"role": "user", "content":
                      AGENT_PROMPT.format(term=term, quote=quote, citation=citation)}]},
            timeout=20)
        if r.status_code == 200:
            text = r.json()['content'][0]['text']
            return parse_agent_response(text)
    except Exception as e:
        print(f"    [Claude error: {e}]")
    return None

def ask_gemini(term, quote, citation):
    if not GEMINI_KEY:
        return None
    try:
        prompt = AGENT_PROMPT.format(term=term, quote=quote, citation=citation)
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}",
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=20)
        if r.status_code == 200:
            text = r.json()['candidates'][0]['content']['parts'][0]['text']
            return parse_agent_response(text)
    except Exception as e:
        print(f"    [Gemini error: {e}]")
    return None

def ask_gpt(term, quote, citation):
    if not OPENAI_KEY:
        return None
    try:
        r = requests.post("https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_KEY}",
                     "Content-Type": "application/json"},
            json={"model": "gpt-4o-mini", "max_tokens": 150,
                  "messages": [{"role": "user", "content":
                      AGENT_PROMPT.format(term=term, quote=quote, citation=citation)}]},
            timeout=20)
        if r.status_code == 200:
            text = r.json()['choices'][0]['message']['content']
            return parse_agent_response(text)
    except Exception as e:
        print(f"    [GPT error: {e}]")
    return None

def parse_agent_response(text):
    verdict = 'unsure'
    reason = text.strip()
    m = re.search(r'VERDICT:\s*(VERIFIED|REJECT|UNSURE)', text, re.I)
    if m:
        v = m.group(1).upper()
        verdict = 'yes' if v == 'VERIFIED' else 'no' if v == 'REJECT' else 'unsure'
    m2 = re.search(r'REASON:\s*(.+)', text, re.I)
    if m2:
        reason = m2.group(1).strip()
    return {'verdict': verdict, 'reason': reason}

def run_agents(result):
    term = result['term']
    quote = result['quote']
    citation = ', '.join(result.get('all_cites', [])[:2])
    verdicts = {}
    if ANTHROPIC_KEY:
        v = ask_claude(term, quote, citation)
        if v: verdicts['claude'] = v
        time.sleep(1)
    if GEMINI_KEY:
        v = ask_gemini(term, quote, citation)
        if v: verdicts['gemini'] = v
        time.sleep(1)
    if OPENAI_KEY:
        v = ask_gpt(term, quote, citation)
        if v: verdicts['gpt'] = v
        time.sleep(1)
    return verdicts

# ── Per-entry ─────────────────────────────────────────────────────────────────
def verify_entry(entry, idx, total, run_agent_tests=False):
    term = entry['term']
    result = {
        'idx': idx, 'term': term, 'quote': entry['quote'],
        'all_cites': entry['all_cites'],
        'primary_cite_pair': entry['primary_cite_pair'],
        'cl_cluster': None, 'cl_url': None,
        'opinion_found': False, 'verification': None,
        'error': None, 'human_verdict': None, 'agent_verdicts': {}, 'notes': ''
    }
    try:
        case_name = entry['primary_cite_pair'][0] if entry['primary_cite_pair'] else None
        raw_cite  = entry['all_cites'][0] if entry['all_cites'] else None
        cluster_id, cl_url, opinion_text = find_opinion(case_name, raw_cite)
        result['cl_cluster']    = cluster_id
        result['cl_url']        = cl_url
        result['opinion_found'] = bool(opinion_text)
        if opinion_text:
            result['verification'] = fuzzy_verify(entry['quote'], opinion_text)
            s = result['verification']
            status = s['status']
            print(f"  [{idx}/{total}] {term[:48]:48s} {s['score']:5.1f} {status}  [CL calls: {_cl_call_count}]")
            # Run agents on flagged entries only
            if run_agent_tests and status in ('fuzzy', 'not_found'):
                print(f"           → running agent tests…")
                result['agent_verdicts'] = run_agents(result)
        else:
            label = 'no text' if cluster_id else 'not found'
            print(f"  [{idx}/{total}] {term[:48]:48s} {label}  [CL calls: {_cl_call_count}]")
            # Still run agents on entries with no opinion text
            if run_agent_tests:
                result['agent_verdicts'] = run_agents(result)
    except Exception as e:
        result['error'] = str(e)
        print(f"  [{idx}/{total}] {term[:48]:48s} ERROR: {e}")
    return result

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    run_agents_flag = '--agents' in sys.argv

    print("="*60)
    print("KINGSFIELD CITATION VERIFIER")
    if run_agents_flag:
        agents_on = [a for a, k in [('Claude',ANTHROPIC_KEY),('Gemini',GEMINI_KEY),('GPT',OPENAI_KEY)] if k]
        print(f"Agent testing: {', '.join(agents_on) if agents_on else 'no keys set'}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)

    print("\n[1/3] Fetching Showalter entries…")
    entries = fetch_entries(TARGET)
    print(f"      {len(entries)} entries\n")

    results = []
    done_terms = set()
    if os.path.exists(OUTPUT_JSON):
        with open(OUTPUT_JSON) as f:
            results = json.load(f)
        done_terms = {r['term'] for r in results}
        print(f"      Resuming — {len(done_terms)} already done\n")

    remaining = [e for e in entries if e['term'] not in done_terms]
    total = len(entries)
    print(f"[2/3] Verifying {len(remaining)} entries…\n")

    for i, entry in enumerate(remaining, start=len(results) + 1):
        r = verify_entry(entry, i, total, run_agent_tests=run_agents_flag)
        results.append(r)
        with open(OUTPUT_JSON, 'w') as f:
            json.dump(results, f, indent=2)

    print(f"\n[3/3] Writing report…")
    write_report(results)
    print(f"\nDone. {OUTPUT_JSON} | {OUTPUT_TXT}")
    print(f"Total CourtListener API calls this run: {_cl_call_count}")

def write_report(results):
    v  = [r for r in results if r.get('verification',{}).get('status')=='verified']
    f  = [r for r in results if r.get('verification',{}).get('status')=='fuzzy']
    n  = [r for r in results if r.get('verification',{}).get('status')=='not_found']
    nc = [r for r in results if not r.get('cl_cluster')]
    nt = [r for r in results if r.get('cl_cluster') and not r.get('opinion_found')]

    lines = [
        "KINGSFIELD CITATION VERIFIER — REPORT",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Total: {len(results)}",
        f"  Verified:          {len(v)}",
        f"  Fuzzy:             {len(f)}",
        f"  Not found:         {len(n)}",
        f"  No opinion text:   {len(nt)}",
        f"  Not on CL:         {len(nc)}",
        "", "─"*60, "FLAGGED — NEEDS HUMAN REVIEW", "─"*60
    ]
    for r in f + n:
        vv = r.get('verification', {})
        av = r.get('agent_verdicts', {})
        lines.append(f"\n{r['term']} (score {vv.get('score','?')})")
        lines.append(f"  Quote:   {r['quote'][:120]}")
        if vv.get('passage'):
            lines.append(f"  Passage: {vv['passage'][:120]}")
        for agent, data in av.items():
            lines.append(f"  {agent}: {data.get('verdict','?')} — {data.get('reason','')[:80]}")

    with open(OUTPUT_TXT, 'w') as ff:
        ff.write('\n'.join(lines))

if __name__ == '__main__':
    main()
