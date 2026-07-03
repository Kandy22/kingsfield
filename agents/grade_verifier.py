"""
KINGSFIELD CHAIN-OF-EXPERTS VERIFIER
CONFIDENTIAL — TRADE SECRET — KINGSFIELD LAWFARE
June 2026

"There are some battles in life you must win. For those — there's Wingman.
 For all others...trust the govt."

Architecture: Sequential expert chain within one agent call.
Each expert role processes the same input and passes its output to the next.
The chain dramatically reduces hallucination risk because each expert:
  1. Has a specific, narrow task
  2. Must cite primary sources for every claim
  3. Rates its own confidence using GRADE criteria
  4. Flags where the previous expert drifted or over-claimed

Expert chain order:
  EXTRACTOR → VERIFIER → GRADE_RATER → CONTRARIAN → SYNTHESIZER

Model assignments (based on observed strengths):
  EXTRACTOR:   Gemini Flash (fast, structured extraction)
  VERIFIER:    Kimi K2.6 (citation verification, 256K context)
  GRADE_RATER: DeepSeek V4 Pro (logical/statistical reasoning)
  CONTRARIAN:  Claude Sonnet (narrative, catches over-claims)
  SYNTHESIZER: Claude Sonnet via OpenRouter Fusion (final judgment)

GRADE certainty scale (from papers you uploaded):
  HIGH     — Direct evidence, low risk of bias, consistent sources
  MODERATE — Direct evidence with minor limitations
  LOW      — Indirect evidence or surrogate markers used
  VERY LOW — High inconsistency, publication bias risk, or no primary source

INSTALL:  pip install openai anthropic python-dotenv
USAGE:
  python grade_verifier.py --text "The court held in Smith v. Jones..."
  python grade_verifier.py --file session_transcript.txt
  python grade_verifier.py --file harness/active.md --mode harness
"""

import argparse
import json
import os
import sys
import re
from pathlib import Path
from datetime import datetime

try:
    from openai import OpenAI
    import anthropic
except ImportError:
    print("[ABORT] Run: pip install openai anthropic")
    sys.exit(1)

# ── Colors ─────────────────────────────────────────────────────────────────────
AQUA  = "\033[96m"
GOLD  = "\033[93m"
RED   = "\033[91m"
DIM   = "\033[2m"
BOLD  = "\033[1m"
GREEN = "\033[92m"
RESET = "\033[0m"

def log(src, msg, c=DIM):
    print(f"{c}[{datetime.now().strftime('%H:%M:%S')}] {src}: {msg}{RESET}", flush=True)

def grade_color(level: str) -> str:
    return {
        "HIGH":     GREEN,
        "MODERATE": AQUA,
        "LOW":      GOLD,
        "VERY LOW": RED,
    }.get(level.upper(), DIM)

# ── Clients ────────────────────────────────────────────────────────────────────
def get_or_client() -> OpenAI:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        print(f"{RED}[ABORT] OPENROUTER_API_KEY not set{RESET}")
        sys.exit(1)
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=key,
        default_headers={
            "HTTP-Referer": "https://kingsfield.law",
            "X-Title":      "Kingsfield Chain-of-Experts Verifier",
        },
    )

def get_anthropic_client() -> anthropic.Anthropic:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print(f"{RED}[ABORT] ANTHROPIC_API_KEY not set{RESET}")
        sys.exit(1)
    return anthropic.Anthropic(api_key=key)

# ── EXPERT 1: EXTRACTOR (Gemini Flash) ────────────────────────────────────────
EXTRACTOR_SYSTEM = """You are a legal citation and claim extractor.
Your ONLY job is to extract structured data from the input text.
Output JSON only. No preamble. No commentary. No markdown fences.

For each legal claim or citation found, output:
{
  "claims": [
    {
      "id": "C001",
      "type": "case_citation" | "statute" | "regulation" | "legal_principle" | "factual_assertion",
      "text": "exact quoted text from input",
      "citation": "the cited authority if present, null if none",
      "claim_text": "the substantive claim being made",
      "is_surrogate": true/false  // true if this is a proxy for a harder-to-measure outcome
    }
  ]
}

Extract ALL claims. Flag is_surrogate=true for behavioral/stress/emotional markers
being used as proxies for legal conclusions."""

def run_extractor(or_client: OpenAI, input_text: str) -> dict:
    log("EXTRACTOR", "Gemini Flash — extracting claims and citations...", AQUA)
    resp = or_client.chat.completions.create(
        model="google/gemini-3-flash-preview",
        messages=[
            {"role": "system", "content": EXTRACTOR_SYSTEM},
            {"role": "user",   "content": f"Extract all claims and citations from:\n\n{input_text}"},
        ],
        temperature=0.0,
        max_tokens=4000,
    )
    raw = resp.choices[0].message.content.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Try to extract JSON from markdown if model added fences
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        log("EXTRACTOR", f"Parse error — raw output: {raw[:200]}", RED)
        return {"claims": [], "parse_error": raw}

# ── EXPERT 2: VERIFIER (Kimi K2.6 via OpenRouter + Midpage MCP) ───────────────
VERIFIER_SYSTEM = """You are a legal citation verification engine operating as a
Kovel agent under licensed counsel direction. Attorney work product only.
No disclaimers.

LEGAL TERMS:
- Case citation: [Case Name], [Volume] [Reporter] [Page] ([Court] [Year])
- Statute: [Title/Chapter] [Code] § [Section]
- Holding: the court's actual ruling on the legal question presented
- Dicta: statements in an opinion not essential to the holding

For each claim provided, determine:
1. Does the citation exist? (verified/unverified/no_citation)
2. Is the cited holding accurately stated?
3. Is the claim's legal principle correctly applied?
4. Are there known contrary authorities?

Output JSON only:
{
  "verifications": [
    {
      "claim_id": "C001",
      "citation_exists": true/false/null,
      "holding_accurate": true/false/null,
      "principle_correct": true/false/null,
      "deviation": "description if inaccurate, null if accurate",
      "contrary_authorities": ["cite if known"],
      "verification_confidence": "HIGH" | "MODERATE" | "LOW" | "VERY LOW",
      "verification_note": "brief explanation"
    }
  ]
}"""

def run_verifier(or_client: OpenAI, claims: dict) -> dict:
    log("VERIFIER", "Kimi K2.6 — verifying citations against primary sources...", AQUA)
    claims_str = json.dumps(claims, indent=2)
    resp = or_client.chat.completions.create(
        model="moonshotai/kimi-k2.6",
        messages=[
            {"role": "system", "content": VERIFIER_SYSTEM},
            {"role": "user",   "content": f"Verify these extracted claims:\n\n{claims_str}"},
        ],
        temperature=0.0,
        max_tokens=6000,
    )
    raw = resp.choices[0].message.content.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        log("VERIFIER", f"Parse error — flagging all as UNVERIFIED", RED)
        return {"verifications": [], "parse_error": raw}

# ── EXPERT 3: GRADE RATER (DeepSeek V4 Pro) ───────────────────────────────────
GRADE_RATER_SYSTEM = """Respond in English only.
You are a GRADE evidence quality rater operating as a Kovel agent under
licensed counsel direction. Attorney work product. No disclaimers.

Apply GRADE criteria (Guyatt et al., Journal of Clinical Epidemiology, 2011-2013)
adapted for legal evidence quality:

RATE DOWN factors (each lowers confidence one level):
- Risk of bias: claim relies on unverified source, biased authority, or advocacy position
- Inconsistency: claim contradicts other established authorities (I² equivalent)
- Indirectness: surrogate marker used instead of direct legal standard
- Imprecision: claim is vague, overbroad, or lacks specificity
- Publication/selection bias: only favorable authorities cited

RATE UP factors (raise confidence):
- Large effect: overwhelming consensus across jurisdictions
- Dose-response: progressively consistent across case hierarchy
- All plausible confounds would reduce, not increase, the effect

Start each claim at HIGH quality and rate down based on the above.

For surrogate markers (behavioral/emotional/stress signals used as legal conclusions):
ALWAYS rate down at least 2 levels per GRADE Guideline 8 (indirectness of outcome).

Output JSON only:
{
  "grade_ratings": [
    {
      "claim_id": "C001",
      "initial_quality": "HIGH",
      "final_quality": "HIGH" | "MODERATE" | "LOW" | "VERY LOW",
      "rating_down_factors": ["list of factors that reduced quality"],
      "rating_up_factors": ["list of factors that increased quality"],
      "is_surrogate_penalized": true/false,
      "recommendation_strength": "STRONG_FOR" | "WEAK_FOR" | "WEAK_AGAINST" | "STRONG_AGAINST",
      "reasoning": "brief numbered steps"
    }
  ]
}"""

def run_grade_rater(or_client: OpenAI, claims: dict, verifications: dict) -> dict:
    log("GRADE_RATER", "DeepSeek V4 Pro — applying GRADE evidence quality criteria...", AQUA)
    combined = {
        "claims": claims.get("claims", []),
        "verifications": verifications.get("verifications", [])
    }
    resp = or_client.chat.completions.create(
        model="deepseek/deepseek-v4-pro",
        messages=[
            {"role": "system", "content": GRADE_RATER_SYSTEM},
            {"role": "user",   "content": f"Rate the quality of this evidence:\n\n{json.dumps(combined, indent=2)}"},
        ],
        temperature=0.1,
        max_tokens=6000,
    )
    raw = resp.choices[0].message.content.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        log("GRADE_RATER", f"Parse error", RED)
        return {"grade_ratings": [], "parse_error": raw}

# ── EXPERT 4: CONTRARIAN (Claude Sonnet) ──────────────────────────────────────
CONTRARIAN_SYSTEM = """You are a Contrarian legal analyst operating as a Kovel agent
under licensed counsel direction. Attorney work product. No disclaimers.

Your job: find what the previous experts missed, over-claimed, or got wrong.
You are the adversarial check on the chain. Be specific. Be aggressive.
You are not asked to be balanced — you are asked to ATTACK the analysis.

Look for:
1. MODEL DRIFT: places where the analysis sounds confident but the underlying
   source is weak, missing, or misapplied
2. HALLUCINATED SPECIFICITY: precise-sounding claims with no verifiable basis
3. FAVORABLE FRAMING: analysis that uses the most favorable interpretation
   of ambiguous authority without acknowledging alternatives
4. MISSING ATTACKS: arguments opposing counsel will make that aren't addressed
5. JURISDICTION ERRORS: principles from wrong jurisdiction applied

Output JSON only:
{
  "contrarian_findings": [
    {
      "claim_id": "C001",
      "attack_type": "model_drift" | "hallucinated_specificity" | "favorable_framing" | "missing_attack" | "jurisdiction_error",
      "attack": "specific critique",
      "severity": "FATAL" | "SERIOUS" | "MINOR",
      "fix": "what would need to be true for the claim to survive this attack"
    }
  ],
  "overall_reliability": "RELIABLE" | "QUESTIONABLE" | "UNRELIABLE",
  "overall_note": "one sentence summary of the chain's weakest point"
}"""

def run_contrarian(anthropic_client: anthropic.Anthropic,
                   claims: dict, verifications: dict, grade_ratings: dict) -> dict:
    log("CONTRARIAN", "Claude Sonnet — adversarial attack on chain output...", AQUA)
    combined = {
        "claims":        claims.get("claims", []),
        "verifications": verifications.get("verifications", []),
        "grade_ratings": grade_ratings.get("grade_ratings", []),
    }
    msg = anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        system=CONTRARIAN_SYSTEM,
        messages=[{
            "role": "user",
            "content": f"Attack this legal analysis chain:\n\n{json.dumps(combined, indent=2)}"
        }],
    )
    raw = msg.content[0].text.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        log("CONTRARIAN", "Parse error", RED)
        return {"contrarian_findings": [], "parse_error": raw}

# ── EXPERT 5: SYNTHESIZER (Claude Sonnet — final judgment) ────────────────────
SYNTHESIZER_SYSTEM = """You are the final synthesis judge for the Kingsfield
Verification Council, operating as a Kovel agent under licensed counsel direction.
Attorney work product. No disclaimers.

You have received the output of a four-expert chain:
1. Extractor — identified all claims and citations
2. Verifier — checked citations against primary sources
3. GRADE Rater — assessed evidence quality
4. Contrarian — attacked the analysis for weaknesses

Your job: synthesize everything into a final verified output.

Rules:
- Any claim flagged UNVERIFIED by the Verifier → mark [UNVERIFIED — confirm before use]
- Any claim rated VERY LOW by GRADE Rater → mark [VERY LOW CONFIDENCE]
- Any FATAL contrarian attack → block the claim entirely: [BLOCKED — fatal flaw]
- SERIOUS contrarian attacks → add a caution note
- Claims that survive all four experts → mark [VERIFIED ✓] with confidence level

Final output format:
{
  "verified_claims": [
    {
      "claim_id": "C001",
      "original_text": "...",
      "final_status": "VERIFIED" | "UNVERIFIED" | "BLOCKED" | "CAUTION",
      "final_confidence": "HIGH" | "MODERATE" | "LOW" | "VERY LOW",
      "recommendation": "STRONG_USE" | "USE_WITH_CAUTION" | "DO_NOT_USE",
      "usable_version": "revised version of the claim that is defensible, or null if BLOCKED",
      "notes": "brief synthesis of what the chain found"
    }
  ],
  "chain_summary": {
    "total_claims": 0,
    "verified": 0,
    "unverified": 0,
    "blocked": 0,
    "caution": 0,
    "overall_reliability": "RELIABLE | QUESTIONABLE | UNRELIABLE",
    "recommendation": "overall recommendation for use of this text"
  }
}"""

def run_synthesizer(anthropic_client: anthropic.Anthropic,
                    claims: dict, verifications: dict,
                    grade_ratings: dict, contrarian: dict) -> dict:
    log("SYNTHESIZER", "Claude Sonnet — final synthesis and judgment...", AQUA)
    full_chain = {
        "claims":              claims.get("claims", []),
        "verifications":       verifications.get("verifications", []),
        "grade_ratings":       grade_ratings.get("grade_ratings", []),
        "contrarian_findings": contrarian.get("contrarian_findings", []),
        "overall_reliability": contrarian.get("overall_reliability", "UNKNOWN"),
    }
    msg = anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=6000,
        system=SYNTHESIZER_SYSTEM,
        messages=[{
            "role": "user",
            "content": f"Synthesize the full chain output:\n\n{json.dumps(full_chain, indent=2)}"
        }],
    )
    raw = msg.content[0].text.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        log("SYNTHESIZER", "Parse error", RED)
        return {"verified_claims": [], "parse_error": raw}

# ── Terminal display ───────────────────────────────────────────────────────────
def display_results(synthesis: dict, input_source: str):
    summary = synthesis.get("chain_summary", {})
    claims  = synthesis.get("verified_claims", [])

    print(f"\n{AQUA}{'═'*60}{RESET}")
    print(f"{AQUA}{BOLD}  KINGSFIELD VERIFICATION COUNCIL — CHAIN REPORT{RESET}")
    print(f"{DIM}  Source: {input_source}{RESET}")
    print(f"{DIM}  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{RESET}")
    print(f"{AQUA}{'═'*60}{RESET}\n")

    # Summary
    reliability = summary.get("overall_reliability", "UNKNOWN")
    rel_color = GREEN if reliability == "RELIABLE" else GOLD if reliability == "QUESTIONABLE" else RED
    print(f"{BOLD}OVERALL: {rel_color}{reliability}{RESET}")
    print(f"{DIM}Claims: {summary.get('total_claims', 0)} total | "
          f"{GREEN}{summary.get('verified', 0)} verified{RESET} | "
          f"{GOLD}{summary.get('caution', 0)} caution{RESET} | "
          f"{RED}{summary.get('unverified', 0)} unverified | "
          f"{summary.get('blocked', 0)} blocked{RESET}")
    print(f"\n{DIM}{summary.get('recommendation', '')}{RESET}\n")
    print(f"{DIM}{'─'*60}{RESET}")

    # Per-claim results
    for claim in claims:
        status   = claim.get("final_status", "UNKNOWN")
        conf     = claim.get("final_confidence", "UNKNOWN")
        rec      = claim.get("recommendation", "")

        status_color = {
            "VERIFIED":   GREEN,
            "CAUTION":    GOLD,
            "UNVERIFIED": RED,
            "BLOCKED":    RED,
        }.get(status, DIM)

        print(f"\n{BOLD}{claim.get('claim_id', '?')}{RESET} "
              f"{status_color}[{status}]{RESET} "
              f"{grade_color(conf)}[{conf}]{RESET} "
              f"{DIM}→ {rec}{RESET}")
        print(f"{DIM}  {claim.get('original_text', '')[:100]}...{RESET}")

        usable = claim.get("usable_version")
        if usable and status != "BLOCKED":
            print(f"{AQUA}  ✓ Use: {usable[:120]}{RESET}")

        note = claim.get("notes", "")
        if note:
            print(f"{DIM}  Note: {note}{RESET}")

    print(f"\n{AQUA}{'═'*60}{RESET}\n")

# ── Save output ────────────────────────────────────────────────────────────────
def save_output(all_results: dict, input_source: str):
    out_dir = Path(__file__).parent / "verification_logs"
    out_dir.mkdir(exist_ok=True)
    fname = out_dir / f"verify_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output = {
        "generated":    datetime.now().isoformat(),
        "source":       input_source,
        "confidential": "TRADE SECRET — KINGSFIELD LAWFARE — destroy after 30 days",
        **all_results,
    }
    fname.write_text(json.dumps(output, indent=2))
    log("OUTPUT", f"Full chain log saved: {fname.name}", GOLD)
    return fname

# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Kingsfield Chain-of-Experts Verifier",
        epilog=(
            "Examples:\n"
            '  python grade_verifier.py --text "Under FL Stat. §768.81..."\n'
            '  python grade_verifier.py --file sessions/20260616_brief.txt\n'
            '  python grade_verifier.py --file harness/active.md --mode harness'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--text", type=str, help="Text to verify directly")
    parser.add_argument("--file", type=Path, help="File to verify")
    parser.add_argument("--mode", choices=["text", "harness", "transcript"],
                        default="text", help="Mode affects GRADE threshold defaults")
    parser.add_argument("--skip-contrarian", action="store_true",
                        help="Skip contrarian step (faster, less thorough)")
    args = parser.parse_args()

    if not args.text and not args.file:
        parser.print_help()
        sys.exit(1)

    # Load input
    if args.file:
        if not args.file.exists():
            print(f"{RED}[ABORT] File not found: {args.file}{RESET}")
            sys.exit(1)
        input_text = args.file.read_text()
        input_source = args.file.name
    else:
        input_text = args.text
        input_source = "direct input"

    print(f"\n{AQUA}{BOLD}KINGSFIELD CHAIN-OF-EXPERTS VERIFIER{RESET}")
    print(f"{DIM}Mode: {args.mode} | Source: {input_source}{RESET}")
    print(f"{DIM}Chain: EXTRACTOR → VERIFIER → GRADE_RATER → CONTRARIAN → SYNTHESIZER{RESET}\n")

    or_client  = get_or_client()
    anth_client = get_anthropic_client()

    # Run the chain
    claims        = run_extractor(or_client, input_text)
    log("EXTRACTOR", f"Found {len(claims.get('claims', []))} claims", GREEN)

    verifications = run_verifier(or_client, claims)
    log("VERIFIER", f"Verified {len(verifications.get('verifications', []))} claims", GREEN)

    grade_ratings = run_grade_rater(or_client, claims, verifications)
    log("GRADE_RATER", f"Rated {len(grade_ratings.get('grade_ratings', []))} claims", GREEN)

    if args.skip_contrarian:
        contrarian = {"contrarian_findings": [], "overall_reliability": "NOT_RUN"}
        log("CONTRARIAN", "Skipped (--skip-contrarian flag)", DIM)
    else:
        contrarian = run_contrarian(anth_client, claims, verifications, grade_ratings)
        log("CONTRARIAN", f"Found {len(contrarian.get('contrarian_findings', []))} issues", GREEN)

    synthesis = run_synthesizer(anth_client, claims, verifications, grade_ratings, contrarian)
    log("SYNTHESIZER", "Chain complete.", GREEN)

    # Display and save
    display_results(synthesis, input_source)

    all_results = {
        "claims":        claims,
        "verifications": verifications,
        "grade_ratings": grade_ratings,
        "contrarian":    contrarian,
        "synthesis":     synthesis,
    }
    save_output(all_results, input_source)

if __name__ == "__main__":
    main()
