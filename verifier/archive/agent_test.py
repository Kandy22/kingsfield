#!/usr/bin/env python3
"""
Kingsfield — Agent Testing
Sends each entry to Claude, Gemini, and GPT.
Saves verdicts back into results.json.
No CourtListener calls — runs anytime.

Usage:
    python3 agent_test.py              # test all entries
    python3 agent_test.py --flagged    # only fuzzy/not_found/no_text
    python3 agent_test.py --redo       # redo entries already tested
"""

import json, os, re, time, sys
import requests
from datetime import datetime

INPUT_JSON    = "results.json"
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_KEY", "")
GEMINI_KEY    = os.environ.get("GEMINI_KEY", "")
OPENAI_KEY    = os.environ.get("OPENAI_KEY", "")

PROMPT = """You are a legal citation verifier. Given a legal term, a claimed quote, and its source citation, determine whether the quote accurately represents what the cited case or statute actually says.

Consider:
- Is the language accurate or paraphrased?
- Is the citation plausible for this quote?
- Does anything seem fabricated or misattributed?

Term: {term}
Citation: {citation}
Claimed quote: "{quote}"

Respond in exactly this format:
VERDICT: [VERIFIED / REJECT / UNSURE]
REASON: [one sentence explaining your verdict]"""

# ── API calls ─────────────────────────────────────────────────────────────────
def ask_claude(term, quote, citation):
    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 150,
                "messages": [{"role": "user", "content":
                    PROMPT.format(term=term, quote=quote[:300], citation=citation)}]
            },
            timeout=20)
        if r.status_code == 200:
            return parse_verdict(r.json()['content'][0]['text'])
        else:
            print(f"    [Claude {r.status_code}]")
    except Exception as e:
        print(f"    [Claude error: {e}]")
    return None

def ask_gemini(term, quote, citation):
    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}",
            json={"contents": [{"parts": [{"text":
                PROMPT.format(term=term, quote=quote[:300], citation=citation)}]}]},
            timeout=20)
        if r.status_code == 200:
            return parse_verdict(r.json()['candidates'][0]['content']['parts'][0]['text'])
        else:
            print(f"    [Gemini {r.status_code}: {r.text[:100]}]")
    except Exception as e:
        print(f"    [Gemini error: {e}]")
    return None

def ask_gpt(term, quote, citation):
    try:
        r = requests.post("https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "gpt-4o-mini",
                "max_tokens": 150,
                "messages": [{"role": "user", "content":
                    PROMPT.format(term=term, quote=quote[:300], citation=citation)}]
            },
            timeout=20)
        if r.status_code == 200:
            return parse_verdict(r.json()['choices'][0]['message']['content'])
        else:
            print(f"    [GPT {r.status_code}]")
    except Exception as e:
        print(f"    [GPT error: {e}]")
    return None

def parse_verdict(text):
    m = re.search(r'VERDICT:\s*(VERIFIED|REJECT|UNSURE)', text, re.I)
    verdict = 'yes'    if m and m.group(1).upper() == 'VERIFIED' else \
              'no'     if m and m.group(1).upper() == 'REJECT'   else 'unsure'
    m2 = re.search(r'REASON:\s*(.+)', text, re.I)
    reason = m2.group(1).strip() if m2 else text.strip()[:150]
    return {'verdict': verdict, 'reason': reason, 'raw': text.strip()[:300]}

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    flagged_only = '--flagged' in sys.argv
    redo         = '--redo'    in sys.argv

    print("="*60)
    print("KINGSFIELD AGENT TESTER")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if flagged_only: print("Mode: flagged entries only (fuzzy/not_found/no_text)")
    if redo:         print("Mode: redo all (including already tested)")
    print("="*60)

    with open(INPUT_JSON) as f:
        results = json.load(f)

    # Decide which entries to test
    def should_test(r):
        has_verdicts = bool(r.get('agent_verdicts'))
        if has_verdicts and not redo:
            return False
        if flagged_only:
            st = r.get('verification', {}).get('status') if r.get('verification') else None
            if st not in ('fuzzy', 'not_found', None):
                return False
        return True

    to_test = [r for r in results if should_test(r)]
    total   = len(results)

    print(f"\nTotal entries: {total}")
    print(f"To test:       {len(to_test)}")
    print(f"\nEstimated cost: ~${len(to_test)*0.003:.2f} (haiku+flash+mini)\n")

    if not to_test:
        print("Nothing to test. Use --redo to retest existing verdicts.")
        return

    # Build lookup by term for in-place update
    idx_map = {r['term']: i for i, r in enumerate(results)}

    tested = 0
    errors = {'claude': 0, 'gemini': 0, 'gpt': 0}

    for i, entry in enumerate(to_test, 1):
        term     = entry['term']
        quote    = entry['quote']
        citation = ', '.join(entry.get('all_cites', [])[:3]) or 'unknown'
        case     = entry.get('primary_cite_pair', [''])[0] if entry.get('primary_cite_pair') else ''
        if case:
            citation = f"{case}, {citation}"

        print(f"  [{i}/{len(to_test)}] {term[:50]}")

        verdicts = {}

        v = ask_claude(term, quote, citation)
        if v:
            verdicts['claude'] = v
            print(f"    Claude:  {v['verdict']:7s} — {v['reason'][:70]}")
        else:
            errors['claude'] += 1
        time.sleep(0.4)

        v = ask_gemini(term, quote, citation)
        if v:
            verdicts['gemini'] = v
            print(f"    Gemini:  {v['verdict']:7s} — {v['reason'][:70]}")
        else:
            errors['gemini'] += 1
        time.sleep(0.4)

        v = ask_gpt(term, quote, citation)
        if v:
            verdicts['gpt'] = v
            print(f"    GPT:     {v['verdict']:7s} — {v['reason'][:70]}")
        else:
            errors['gpt'] += 1
        time.sleep(0.4)

        # Update in results
        ri = idx_map.get(term)
        if ri is not None:
            if redo:
                results[ri]['agent_verdicts'] = verdicts
            else:
                results[ri]['agent_verdicts'].update(verdicts)

        tested += 1

        # Save every 5 entries
        if tested % 5 == 0:
            with open(INPUT_JSON, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"    [saved at {tested}]")

    # Final save
    with open(INPUT_JSON, 'w') as f:
        json.dump(results, f, indent=2)

    # Summary
    print(f"\n{'='*60}")
    print(f"DONE — {tested} entries tested")
    print(f"Errors — Claude: {errors['claude']} | Gemini: {errors['gemini']} | GPT: {errors['gpt']}")

    # Agreement stats
    all_tested = [r for r in results if r.get('agent_verdicts') and r.get('human_verdict')]
    if all_tested:
        print(f"\nVERDICT AGREEMENT (vs your human verdicts, {len(all_tested)} entries):")
        for agent in ['claude','gemini','gpt']:
            matches = sum(1 for r in all_tested
                         if r['agent_verdicts'].get(agent,{}).get('verdict') == r['human_verdict'])
            pct = matches/len(all_tested)*100
            print(f"  {agent:8s}: {matches}/{len(all_tested)} ({pct:.1f}% match)")

    # Disagreement report
    disagreements = [r for r in results
                    if r.get('agent_verdicts') and r.get('human_verdict')
                    and any(r['agent_verdicts'].get(a,{}).get('verdict') != r['human_verdict']
                           for a in ['claude','gemini','gpt'])]
    if disagreements:
        print(f"\nDISAGREEMENTS ({len(disagreements)} entries):")
        for r in disagreements[:20]:
            av = r['agent_verdicts']
            print(f"  {r['term'][:40]:40s} human={r['human_verdict']} | "
                  f"claude={av.get('claude',{}).get('verdict','—')} "
                  f"gemini={av.get('gemini',{}).get('verdict','—')} "
                  f"gpt={av.get('gpt',{}).get('verdict','—')}")

    print(f"\nResults saved to {INPUT_JSON}")
    print("Reload results.json in the sandbox to see agent verdicts.")

if __name__ == '__main__':
    main()
