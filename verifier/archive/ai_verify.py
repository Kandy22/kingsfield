#!/usr/bin/env python3
"""
Kingsfield — AI Verify All 1979 Entries
Uses Claude Haiku directly. No CourtListener. No rate limit prison.
Merges with existing results.json, adds Claude verdict to every entry.
Resumable — saves every 25 entries.
"""
import json, re, time, os, sys
import requests
from datetime import datetime

ANTHROPIC_KEY = os.environ.get("ANTHROPIC_KEY", "")
GEMINI_KEY    = os.environ.get("GEMINI_KEY", "")
OPENAI_KEY    = os.environ.get("OPENAI_KEY", "")
GH_BASE       = "https://raw.githubusercontent.com/michaeljshowalter/showalters-law-dictionary/main/{}.md"
LETTERS       = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
OUTPUT_JSON   = "results_full.json"
DELAY         = 0.25

PROMPT = """You are a legal citation verifier with deep knowledge of US case law.

Legal term being defined: {term}
Citation(s): {citation}
Claimed quote from that case: "{quote}"

Based on your knowledge of this case, is this quote accurate — does it faithfully appear in or represent what the cited case actually says?

Reply in exactly this format with no other text:
VERDICT: [VERIFIED / REJECT / UNSURE]
REASON: [one concise sentence]"""

# ── Fetch all Showalter entries ───────────────────────────────
def fetch_all():
    entries = []
    for letter in LETTERS:
        try:
            r = requests.get(GH_BASE.format(letter), timeout=15)
            if r.status_code != 200:
                continue
            blocks = re.split(r'\n## ', r.text)[1:]
            for block in blocks:
                lines = block.strip().split('\n')
                term = lines[0].strip()
                body = '\n'.join(lines[1:])
                # Lenient quote extraction — straight or curly quotes
                quotes = re.findall(r'["“”]([^“”"]{15,600})["“”]', body)
                if not quotes:
                    quotes = re.findall(r'"([^"]{15,600})"', body)
                # Lenient citation extraction
                cites = re.findall(
                    r'\b(\d+\s+(?:U\.S\.|S\.?\s*Ct\.|F\.[\d]*[a-z]*|'
                    r'F\.?\s*Supp\.?\s*\d*|L\.?\s*Ed\.?\s*\d*)\s*\d+)', body)
                # Full case name pairs
                full_cites = re.findall(
                    r'([A-Z][A-Za-z\s&\.,\']+?v\.\s+[A-Z][A-Za-z\s&\.,\']+?),\s*'
                    r'(\d+\s+(?:U\.S\.|S\.\s*Ct\.|F\.\d+[a-z]*|F\.\s*Supp\.?\s*\d*)\s+\d+)', body)
                entries.append({
                    'term': term,
                    'quote': quotes[0] if quotes else '',
                    'all_quotes': quotes[:3],
                    'all_cites': cites[:5],
                    'primary_cite_pair': full_cites[0] if full_cites else None,
                    'body_snippet': body[:500],
                })
            time.sleep(0.15)
        except Exception as e:
            print(f"  {letter}: fetch error — {e}")
    return entries

# ── Shared helpers ───────────────────────────────────────────
def parse_verdict(text):
    verdict = 'unsure'
    reason = text.strip()[:200]
    m = re.search(r'VERDICT:\s*(VERIFIED|REJECT|UNSURE)', text, re.I)
    if m:
        v = m.group(1).upper()
        verdict = 'yes' if v == 'VERIFIED' else 'no' if v == 'REJECT' else 'unsure'
    m2 = re.search(r'REASON:\s*(.+)', text, re.I)
    if m2:
        reason = m2.group(1).strip()
    return {'verdict': verdict, 'reason': reason}

def has_verdict(agent_verdicts, agent):
    av = (agent_verdicts or {}).get(agent)
    return isinstance(av, dict) and av.get('verdict') in ('yes','no','unsure')

# ── Claude verdict ────────────────────────────────────────────
def ask_claude(term, quote, cites, retries=3):
    citation = ', '.join(cites[:2]) if cites else 'citation unavailable'
    if not quote:
        quote = '(no direct quote in entry — assess whether this term is accurately attributed to this citation)'

    for attempt in range(retries):
        try:
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 120,
                    "messages": [{"role": "user", "content": PROMPT.format(
                        term=term, citation=citation, quote=quote[:400]
                    )}]
                },
                timeout=20
            )
            if r.status_code == 200:
                text = r.json()['content'][0]['text'].strip()
                verdict = 'unsure'
                reason = text
                m = re.search(r'VERDICT:\s*(VERIFIED|REJECT|UNSURE)', text, re.I)
                if m:
                    v = m.group(1).upper()
                    verdict = 'yes' if v == 'VERIFIED' else 'no' if v == 'REJECT' else 'unsure'
                m2 = re.search(r'REASON:\s*(.+)', text, re.I)
                if m2:
                    reason = m2.group(1).strip()
                return {'verdict': verdict, 'reason': reason}
            elif r.status_code == 429:
                wait = int(r.headers.get('Retry-After', 15)) + 2
                print(f"    [Claude 429 — waiting {wait}s]")
                time.sleep(wait)
            elif r.status_code >= 500:
                time.sleep(5)
            else:
                print(f"    [Claude error {r.status_code}: {r.text[:100]}]")
                return None
        except Exception as e:
            print(f"    [Claude exception: {e}]")
            time.sleep(5)
    return None

# ── Gemini verdict ────────────────────────────────────────────
def ask_gemini(term, quote, cites, retries=3):
    citation = ', '.join(cites[:2]) if cites else 'citation unavailable'
    if not quote:
        quote = '(no direct quote)'
    prompt = PROMPT.format(term=term, citation=citation, quote=quote[:400])
    for attempt in range(retries):
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}",
                json={"contents": [{"parts": [{"text": prompt}]}],
                      "generationConfig": {"maxOutputTokens": 300}},
                timeout=20)
            if r.status_code == 200:
                text = r.json()['candidates'][0]['content']['parts'][0]['text']
                return parse_verdict(text)
            elif r.status_code == 429:
                wait = int(r.headers.get('Retry-After', 15)) + 2
                print(f"    [Gemini 429 — waiting {wait}s]")
                time.sleep(wait)
            else:
                print(f"    [Gemini error {r.status_code}]")
                return None
        except Exception as e:
            print(f"    [Gemini exception: {e}]")
            time.sleep(5)
    return None

# ── GPT verdict ───────────────────────────────────────────────
def ask_gpt(term, quote, cites, retries=3):
    citation = ', '.join(cites[:2]) if cites else 'citation unavailable'
    if not quote:
        quote = '(no direct quote)'
    prompt = PROMPT.format(term=term, citation=citation, quote=quote[:400])
    for attempt in range(retries):
        try:
            r = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
                json={"model": "gpt-4o-mini", "max_tokens": 120,
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=20)
            if r.status_code == 200:
                text = r.json()['choices'][0]['message']['content']
                return parse_verdict(text)
            elif r.status_code == 429:
                wait = int(r.headers.get('Retry-After', 15)) + 2
                print(f"    [GPT 429 — waiting {wait}s]")
                time.sleep(wait)
            else:
                print(f"    [GPT error {r.status_code}]")
                return None
        except Exception as e:
            print(f"    [GPT exception: {e}]")
            time.sleep(5)
    return None

# ── Main ──────────────────────────────────────────────────────
def main():
    print("="*60)
    print("KINGSFIELD — AI VERIFY ALL (Claude, no CourtListener)")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)

    # Load existing CL results to preserve fuzzy scores + human verdicts
    cl_data = {}
    if os.path.exists('results.json'):
        with open('results.json') as f:
            for r in json.load(f):
                cl_data[r['term']] = r
    print(f"\nExisting CL results to merge: {len(cl_data)}")

    redo_gemini = '--redo-gemini' in sys.argv

    # Resume if partial run exists — only skip entries with ALL THREE verdicts
    results = []
    done_terms = set()
    if os.path.exists(OUTPUT_JSON):
        with open(OUTPUT_JSON) as f:
            results = json.load(f)

        if redo_gemini:
            # Only rerun entries where Gemini verdict is unsure with truncated reason
            bad_gemini = [r for r in results
                          if isinstance(r.get('agent_verdicts',{}).get('gemini'), dict)
                          and r['agent_verdicts']['gemini'].get('verdict') == 'unsure'
                          and len(r['agent_verdicts']['gemini'].get('reason','')) < 20]
            print(f"Redo-gemini mode: {len(bad_gemini)} truncated Gemini entries to fix")
            idx_map = {r['term']: i for i, r in enumerate(results)}
            fixed = 0
            for r in bad_gemini:
                quote = r.get('quote','')
                cites = r.get('all_cites',[])
                if not quote and not cites:
                    continue
                v = ask_gemini(r['term'], quote, cites)
                if v:
                    results[idx_map[r['term']]]['agent_verdicts']['gemini'] = v
                    vstr = {'yes':'✓','no':'✗','unsure':'~'}.get(v['verdict'],'?')
                    print(f"  {r['term'][:50]:50s} gemini:{vstr}  {v['reason'][:60]}")
                    fixed += 1
                time.sleep(DELAY)
                if fixed % 25 == 0:
                    with open(OUTPUT_JSON, 'w') as f:
                        json.dump(results, f, indent=2)
                    print(f"  [saved at {fixed}]")
            with open(OUTPUT_JSON, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"\nFixed {fixed} Gemini entries.")
            return

        done_terms = {r['term'] for r in results
                      if has_verdict(r.get('agent_verdicts'), 'claude')
                      and has_verdict(r.get('agent_verdicts'), 'gemini')
                      and has_verdict(r.get('agent_verdicts'), 'gpt')}
        print(f"Resuming — {len(done_terms)} fully done, {len(results)-len(done_terms)} need more agents")

    # Fetch all Showalter entries
    print("\nFetching all Showalter entries from GitHub...")
    all_entries = fetch_all()
    print(f"Total entries: {len(all_entries)}")

    remaining = [e for e in all_entries if e['term'] not in done_terms]
    total = len(all_entries)
    print(f"Remaining to process: {len(remaining)}\n")

    for entry in remaining:
        term  = entry['term']
        quote = entry['quote']
        cites = entry['all_cites']
        idx   = len(results) + 1

        # Start with CL data if we have it, otherwise fresh record
        if term in cl_data:
            result = dict(cl_data[term])
            result['source'] = 'courtlistener'
        else:
            result = {
                'idx': idx, 'term': term, 'quote': quote,
                'all_cites': cites,
                'primary_cite_pair': entry.get('primary_cite_pair'),
                'cl_cluster': None, 'cl_url': None,
                'opinion_found': False, 'verification': None,
                'error': None, 'human_verdict': None,
                'agent_verdicts': {}, 'notes': '',
                'source': 'ai_direct'
            }

        # Always update quote/cites from fresh Showalter parse if missing
        if not result.get('quote') and quote:
            result['quote'] = quote
        if not result.get('all_cites') and cites:
            result['all_cites'] = cites

        if not isinstance(result.get('agent_verdicts'), dict):
            result['agent_verdicts'] = {}
        avs = result['agent_verdicts']
        verdicts_log = []

        for agent, ask_fn in [('claude', ask_claude), ('gemini', ask_gemini), ('gpt', ask_gpt)]:
            if has_verdict(avs, agent):
                verdicts_log.append(f"{agent}:{'✓' if avs[agent]['verdict']=='yes' else '✗' if avs[agent]['verdict']=='no' else '~'}")
            elif quote or cites:
                v = ask_fn(term, quote, cites)
                if v:
                    avs[agent] = v
                    verdicts_log.append(f"{agent}:{'✓' if v['verdict']=='yes' else '✗' if v['verdict']=='no' else '~'}")
                else:
                    verdicts_log.append(f"{agent}:?")
                time.sleep(DELAY)

        st = (result.get('verification') or {}).get('status', '')
        fuzzy_str = f" [CL:{st}]" if st else ''
        print(f"  [{idx:4d}/{total}] {term[:44]:44s} {' '.join(verdicts_log)}{fuzzy_str}")

        results.append(result)

        if len(results) % 25 == 0:
            with open(OUTPUT_JSON, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"         ↳ saved {len(results)} entries")

    # Final save
    with open(OUTPUT_JSON, 'w') as f:
        json.dump(results, f, indent=2)

    # Summary
    def vstats(agent):
        y = sum(1 for r in results if has_verdict(r.get('agent_verdicts'), agent) and r['agent_verdicts'][agent]['verdict']=='yes')
        n = sum(1 for r in results if has_verdict(r.get('agent_verdicts'), agent) and r['agent_verdicts'][agent]['verdict']=='no')
        u = sum(1 for r in results if has_verdict(r.get('agent_verdicts'), agent) and r['agent_verdicts'][agent]['verdict']=='unsure')
        return y, n, u

    cl_v  = sum(1 for r in results if (r.get('verification') or {}).get('status')=='verified')
    cy,cn,cu = vstats('claude')
    gy,gn,gu = vstats('gemini')
    oy,on_,ou = vstats('gpt')

    print(f"\n{'='*60}")
    print(f"Done. {len(results)} total entries → {OUTPUT_JSON}")
    print(f"Claude:  ✓ {cy}  ✗ {cn}  ~ {cu}")
    print(f"Gemini:  ✓ {gy}  ✗ {gn}  ~ {gu}")
    print(f"GPT:     ✓ {oy}  ✗ {on_}  ~ {ou}")
    print(f"CourtListener fuzzy-verified: {cl_v}")
    print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == '__main__':
    main()
