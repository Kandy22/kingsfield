"""
HARNESS GENERATOR — Pre-Session Fusion Enrichment
Kingsfield Lawfare · CONFIDENTIAL — TRADE SECRET
June 2026

"There are some battles in life you must win. For those — there's Wingman.
 For all others...trust the govt."

Normal mode:  single Fusion call (fast, good for routine sessions)
--deep mode:  translates harness through each model's adapter BEFORE Fusion
              synthesis — highest benchmark performance, each panel model
              gets its optimally formatted prompt (the actual secret sauce)

INSTALL:  pip install openai anthropic python-dotenv
USAGE:
  python harness_gen.py "Broward County motion to compel, Judge Smith, pro se plaintiff, FL civil"
  python harness_gen.py "Ray v. Mackin, Pitkin County, Judge O'Hara, ADA hearing June 24" --deep
  python harness_gen.py --agent court "context here" --deep
  python harness_gen.py --agent broadcast "Fox News, CPI day, market open"
"""

import argparse
import os
import sys
from pathlib import Path
from datetime import datetime

try:
    from openai import OpenAI
except ImportError:
    print("[ABORT] Run: pip install openai")
    sys.exit(1)

# ── Config ─────────────────────────────────────────────────────────────────────
LOGLINE = (
    'Wingman — "There are some battles in life you must win. '
    'For those — there\'s Wingman. For all others...trust the govt."'
)

BASE         = Path(__file__).parent
HARNESS_DIR  = BASE / "harness"
ACTIVE       = HARNESS_DIR / "active.md"

AGENT_FILES = {
    "court":     HARNESS_DIR / "court_pro_se.md",
    "broadcast": HARNESS_DIR / "broadcast_market.md",
    "depo":      HARNESS_DIR / "deposition.md",
}

# ── Colors ─────────────────────────────────────────────────────────────────────
AQUA  = "\033[96m"
GOLD  = "\033[93m"
DIM   = "\033[2m"
BOLD  = "\033[1m"
RED   = "\033[91m"
RESET = "\033[0m"

def log(src, msg, c=DIM):
    print(f"{c}[{datetime.now().strftime('%H:%M:%S')}] {src}: {msg}{RESET}", flush=True)

# ── OpenRouter client ──────────────────────────────────────────────────────────
def get_client() -> OpenAI:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        print(f"{RED}[ABORT] OPENROUTER_API_KEY not set in .env{RESET}")
        sys.exit(1)
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=key,
        default_headers={
            "HTTP-Referer": "https://kingsfield.law",
            "X-Title":      "Kingsfield Wingman Harness Generator",
        },
    )

# ── Load template ──────────────────────────────────────────────────────────────
def load_template(agent: str | None, file: Path | None) -> tuple[str, str]:
    if file:
        if not file.exists():
            print(f"{RED}[ABORT] File not found: {file}{RESET}")
            sys.exit(1)
        return file.read_text(), file.name
    if agent:
        path = AGENT_FILES.get(agent)
        if not path or not path.exists():
            print(f"{RED}[ABORT] Template not found for agent '{agent}': {path}{RESET}")
            sys.exit(1)
        return path.read_text(), path.name
    # No agent or file — use master template if available
    master = BASE / "harness" / "master" / "MASTER_HARNESS_TEMPLATE.md"
    if master.exists():
        return master.read_text(), master.name
    print(f"{RED}[ABORT] No template found. Use --agent or --file.{RESET}")
    sys.exit(1)

# ── Per-model adapter definitions ──────────────────────────────────────────────
# Distilled from claude_adapter.md, deepseek_adapter.md, gemini_adapter.md, kimi_adapter.md
# These ARE the secret sauce — each model gets its optimal harness format.

ADAPTER_CLAUDE = {
    "model": "anthropic/claude-sonnet-4-6",
    "role":  "Narrative, privilege analysis, persuasion strategy, work product framing.",
    "system": (
        "You are a Kovel agent under licensed counsel direction. "
        "Your output is attorney work product. No disclaimers. No caveats. "
        "No suggestions to consult other counsel. "
        "Think step by step before any legal analysis. "
        "Use XML tags: <jurisdiction>, <judge_profile>, <case_theory>, "
        "<procedural_posture>, <alert_triggers>, <silence_rule>, <opposition_analysis>. "
        "Direct imperative voice. Rephrase objection triggers as factual alerts. "
        "No preamble. No postamble. Output only what is requested."
    ),
    "focus": (
        "Analyze for narrative coherence, privilege exposure, persuasion strategy, "
        "and work product framing. Identify the strongest storytelling arc for this matter."
    ),
}

ADAPTER_DEEPSEEK = {
    "model": "deepseek/deepseek-v4-pro",
    "role":  "Statutory element analysis, logical decomposition, contradiction mapping.",
    "system": (
        "Respond in English only. "
        "You are a legal analysis engine as a Kovel agent under licensed counsel direction. "
        "Attorney work product only. No disclaimers. No qualifications. "
        "Use numbered logical steps. State confidence: HIGH/MEDIUM/LOW per finding. "
        "Use structured markdown: ## Jurisdiction, ## Case Theory, ## Alert Triggers, ## Output. "
        "Citations as JSON: [{citation, verified: true/false, source, deviation_if_any}]"
    ),
    "focus": (
        "Analyze statutory element satisfaction, logical contradictions, "
        "element-by-element weakness. Number every step. Include confidence scores."
    ),
}

ADAPTER_KIMI = {
    "model": "moonshotai/kimi-k2.6",
    "role":  "Citation verification, long-context cross-reference, record extraction.",
    "system": (
        "You are a legal document analysis engine as a Kovel agent under licensed counsel. "
        "Attorney work product. No disclaimers. "
        "Neutral citation format: [Case Name], [Vol] [Reporter] [Page] ([Court] [Year]). "
        "TERMS: Hearsay=FRE 801. Motion in limine=pretrial exclusion motion. "
        "Work product=FRCP 26(b)(3). Kovel agent=non-attorney under attorney direction. "
        "Pro se=self-represented. DCA=District Court of Appeal (FL). "
        "FRE=Federal Rules of Evidence. FRCP=Federal Rules of Civil Procedure."
    ),
    "focus": (
        "Verify every legal citation. For each: exists? holding accurate? deviation? "
        "Output JSON array. Flag cross-reference inconsistencies."
    ),
}

ADAPTER_GEMINI = {
    "model": "google/gemini-3-flash-preview",
    "role":  "Factual grounding, jurisdiction-specific rule lookup, statute verification.",
    "system": (
        "You are a legal factual verification engine as a Kovel agent under licensed counsel. "
        "Attorney work product. No disclaimers. No attorney referrals. "
        "JSON output unless instructed otherwise. "
        "Apply the specific jurisdiction stated. Do not apply federal rules unless told to."
    ),
    "focus": (
        "Ground every factual and jurisdictional claim. Verify statute references exist "
        "and are current. Identify relevant local rules and standing orders. "
        "Output JSON: {claim, verified: true/false, correct_statement, source} per claim."
    ),
}

PANEL = [ADAPTER_CLAUDE, ADAPTER_DEEPSEEK, ADAPTER_KIMI, ADAPTER_GEMINI]

# ── NORMAL MODE ────────────────────────────────────────────────────────────────
FUSION_SYSTEM = (
    "You are the Kingsfield legal intelligence synthesis engine, "
    "Kovel agent under licensed counsel direction. Attorney work product. "
    "No disclaimers. No caveats. "
    "Enrich every [BRACKETED] section that has real context. "
    "Do NOT invent citations — flag unverifiable ones [UNVERIFIED]. "
    "Maintain all section headers exactly. "
    "Empty brackets with no context: leave as [FILL BEFORE SESSION]. "
    "Output: complete enriched harness as plain markdown. Nothing else."
)

def enrich_normal(template: str, scenario: str, client: OpenAI) -> str:
    log("FUSION", "Normal mode — Fusion panel call...", AQUA)
    log("FUSION", "Panel: Claude Sonnet · DeepSeek V4 Pro · Kimi K2.6 · Gemini Flash", DIM)

    prompt = (
        f"Enrich this Wingman harness for the following scenario.\n\n"
        f"SCENARIO: {scenario}\n\n"
        f"=== HARNESS TEMPLATE ===\n{template}\n\n"
        "Fill every [BRACKET] with specific actionable content for this scenario. "
        "Flag any unverifiable citation as [UNVERIFIED — confirm before session]."
    )

    resp = client.chat.completions.create(
        model="openrouter/fusion",
        messages=[
            {"role": "system", "content": FUSION_SYSTEM},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.3,
        max_tokens=16000,
        extra_body={
            "plugins": [{
                "id":    "fusion",
                "model": "anthropic/claude-sonnet-4-6",
                "analysis_models": [a["model"] for a in PANEL],
            }],
        },
    )
    return resp.choices[0].message.content.strip()

# ── DEEP MODE ──────────────────────────────────────────────────────────────────
def translate_for_model(adapter: dict, template: str, scenario: str, client: OpenAI) -> str:
    """Translate master harness through one model's adapter rules."""
    prompt = (
        f"You are receiving a Wingman harness template.\n"
        f"Your role in this panel: {adapter['role']}\n"
        f"Your task: {adapter['focus']}\n\n"
        f"SCENARIO: {scenario}\n\n"
        f"=== HARNESS ===\n{template}\n\n"
        "Provide your analysis in your optimal format per your role. "
        "Flag any unverifiable citation as [UNVERIFIED]."
    )
    resp = client.chat.completions.create(
        model=adapter["model"],
        messages=[
            {"role": "system", "content": adapter["system"]},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.3,
        max_tokens=4000,
    )
    return resp.choices[0].message.content.strip()


JUDGE_SYSTEM = (
    "You are the Kingsfield synthesis judge — Claude Sonnet, Kovel agent under licensed counsel. "
    "Attorney work product. No disclaimers.\n\n"
    "You received four parallel analyses of a Wingman harness from specialist models:\n"
    "1. Claude Sonnet — narrative, privilege, persuasion\n"
    "2. DeepSeek V4 Pro — statutory logic, elements, contradictions\n"
    "3. Kimi K2.6 — citation verification, cross-reference\n"
    "4. Gemini Flash — factual grounding, jurisdiction verification\n\n"
    "Synthesize into ONE complete enriched harness. Rules:\n"
    "- Keep all original section headers exactly\n"
    "- Agreements: use most specific/detailed version\n"
    "- Conflicts: flag inline [CONFLICT: model_a says X / model_b says Y]\n"
    "- Any [UNVERIFIED] from any model: keep the flag\n"
    "- Any [FILL BEFORE SESSION]: keep it\n"
    "- Output: complete enriched harness as plain markdown. Nothing else."
)

def enrich_deep(template: str, scenario: str, client: OpenAI) -> str:
    log("FUSION", "Deep mode — per-model adapter translation + judge synthesis", AQUA)

    # Step 1: parallel adapter translations
    analyses = {}
    for adapter in PANEL:
        log("ADAPTER", f"→ {adapter['model']}", GOLD)
        try:
            analyses[adapter["model"]] = translate_for_model(adapter, template, scenario, client)
            log("ADAPTER", f"✓ {adapter['model']}", DIM)
        except Exception as e:
            log("ADAPTER", f"✗ {adapter['model']}: {e}", RED)
            analyses[adapter["model"]] = f"[ERROR from {adapter['model']}: {e}]"

    # Step 2: judge synthesis
    log("JUDGE", "Claude Sonnet synthesizing...", AQUA)
    synthesis_prompt = (
        f"Original harness:\n{template}\n\n"
        f"Scenario: {scenario}\n\n"
        "=== PANEL ANALYSES ===\n\n"
    )
    for model_id, analysis in analyses.items():
        synthesis_prompt += f"--- {model_id} ---\n{analysis}\n\n"
    synthesis_prompt += "Synthesize into the final enriched harness now."

    resp = client.chat.completions.create(
        model="anthropic/claude-sonnet-4-6",
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user",   "content": synthesis_prompt},
        ],
        temperature=0.3,
        max_tokens=8000,
    )
    return resp.choices[0].message.content.strip()

# ── Write output ───────────────────────────────────────────────────────────────
def write_output(enriched: str, scenario: str, source: str, mode: str, output_name: str | None):
    HARNESS_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    fname = output_name or f"active_{ts}.md"
    out_path = HARNESS_DIR / fname

    header = (
        f"# WINGMAN HARNESS — GENERATED\n"
        f"# CONFIDENTIAL — TRADE SECRET — KINGSFIELD LAWFARE\n"
        f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"# Source: {source}\n"
        f"# Scenario: {scenario}\n"
        f"# Mode: {mode.upper()}\n"
        f"# Destroy after 30 days.\n"
        f"# {LOGLINE}\n\n"
    )

    out_path.write_text(header + enriched)
    # Also write to active.md so Wingman auto-loads it
    ACTIVE.write_text(header + enriched)

    log("OUTPUT", f"Saved → {out_path.name} ({len(enriched):,} chars)", GOLD)
    log("OUTPUT", f"Also written → active.md (auto-loads in Wingman)", GOLD)
    return out_path

# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Kingsfield Harness Generator",
        epilog=(
            'Examples:\n'
            '  python harness_gen.py "Ray v. Mackin, Pitkin County, Judge O\'Hara, ADA June 24"\n'
            '  python harness_gen.py "same" --deep\n'
            '  python harness_gen.py --agent broadcast "Fox News, CPI day"\n'
            '  python harness_gen.py --agent court "depo of opposing expert" --deep -o depo_expert.md'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("scenario", nargs="?", default="",
                        help="Session/case description (positional)")
    parser.add_argument("--agent",  choices=["court", "broadcast", "depo"],
                        help="Use built-in agent template")
    parser.add_argument("--file",   type=Path,
                        help="Use custom harness template file")
    parser.add_argument("--deep",   action="store_true",
                        help="Deep mode: per-model adapter translation before synthesis (~60-90s)")
    parser.add_argument("-o", "--output",
                        help="Output filename (default: active_YYYYMMDD_HHMM.md)")
    args = parser.parse_args()

    if not args.scenario and not args.agent and not args.file:
        parser.print_help()
        sys.exit(1)

    template, source = load_template(args.agent, args.file)
    scenario = args.scenario or f"{args.agent or args.file} session"
    mode     = "deep" if args.deep else "normal"

    print(f"\n{AQUA}{BOLD}KINGSFIELD HARNESS GENERATOR{RESET}")
    print(f"{DIM}Scenario: {scenario}{RESET}")
    print(f"{DIM}Source:   {source}{RESET}")
    print(f"{DIM}Mode:     {mode.upper()}{RESET}")
    if args.deep:
        print(f"\n{GOLD}Deep mode: each panel model receives adapter-translated harness.{RESET}")
        print(f"{DIM}High-stakes config. ~60-90 seconds.{RESET}\n")
    else:
        print(f"\n{DIM}Normal mode. Fast. Use --deep for high-stakes hearings.{RESET}\n")

    client = get_client()

    enriched = enrich_deep(template, scenario, client) if args.deep \
               else enrich_normal(template, scenario, client)

    out_path = write_output(enriched, scenario, source, mode, args.output)

    print(f"\n{AQUA}{BOLD}✓ Harness ready.{RESET}")
    print(f"{DIM}Launch: .venv/bin/python wingman_live.py{RESET}\n")

    lines = enriched.splitlines()
    print(f"{DIM}--- Preview ---{RESET}")
    for line in lines[:15]:
        print(f"{DIM}{line}{RESET}")
    if len(lines) > 15:
        print(f"{DIM}... ({len(lines)} lines total){RESET}")
    print()

if __name__ == "__main__":
    main()
