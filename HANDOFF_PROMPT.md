# KINGSFIELD SESSION HANDOFF PROMPT
# Copy this entire block as the FIRST message in your next Claude session.
# Upload KINGSFIELD_MASTER_REF.md alongside this message.

---

I'm Aaron Ray, building Kingsfield Lawfare — an AI-powered litigation intelligence platform.

**Upload this file first: KINGSFIELD_MASTER_REF.md** — it is the canonical context for this project. Read it completely before responding to anything.

## State as of June 16, 2026

Wingman is WORKING. The pipeline is confirmed end-to-end: mic → Gemini 3.1 Flash Live → audio response to earpiece. Agent selector runs 3 agents (Court Pro Se, Broadcast/Market Watch, Deposition). Harness auto-injects from active.md at session start.

**Files on my Mac at ~/code/kingsfield/:**
- `wingman/wingman_live.py` — working, 3-agent selector
- `wingman/harness_gen.py` — pre-session Fusion harness generator (normal + --deep)
- `wingman/session_brief.py` — post-session audio brief via Podcastfy
- `wingman/run.sh` — one-line launcher
- `wingman/harness/court_pro_se.md` — Court agent harness template
- `wingman/harness/broadcast_market.md` — Broadcast agent harness template
- `wingman/harness/deposition.md` — Deposition agent harness template
- `grade_verifier.py` — 5-expert chain-of-experts GRADE verifier
- `KINGSFIELD_MASTER_REF.md` — this file
- `KINGSFIELD_FUSION_AND_LEGAL_REF.md` — Fusion + legal wrapper reference
- `MASTER_HARNESS_TEMPLATE.md` — model-agnostic canonical harness
- `wingman/harness/adapters/` — claude, deepseek, gemini, kimi adapter files (TRADE SECRETS)

**Run Wingman:**
```bash
cd ~/code/kingsfield/wingman && set -a && source ../.env && set +a && .venv/bin/python wingman_live.py
```

## What I need next (pick one or I'll tell you):

**Option A — Build Wingman PWA UI**
Monologue-styled iPhone-ready HTML file. Single page, opens in Safari, captures mic, runs Gemini Live WebSocket directly from browser. Displays waveform, agent name, advisory callouts in Electric Aqua (#19d0e8), session log in DM Mono, start/stop pill button, Wingman wordmark in Instrument Serif. No server needed. Design tokens are in theme-_Monologue.css in the project.

**Option B — Build FL Court Hearing Scraper**
Python script to scrape FL circuit court hearing videos (Zoom recordings posted on case portals). Audio extraction, metadata tagging (judge, case#, date, attorneys), saves to judicial-intel/data/fl_2dca/manifest.json format. Also rebuild the Google Scholar scraper (FL filter: as_sdt=4,9) for case law.

**Option C — Wire Midpage into grade_verifier.py**
The VERIFIER step in grade_verifier.py currently calls Kimi K2.6 which relies on training data for citation verification. Replace/augment with direct Midpage SQL queries against the opinions.citations and laws.statutes tables. Midpage MCP is already connected in this Claude project. SQL replica available at read replica URL.

**Option D — Something else I'll tell you**

## Key context that is NOT in the master ref
- Paper I need you to read if I upload it: "Code as Agent Harness" (arXiv:2605.18747, May 2026). I only had screenshots last session, not the full text. Read it when I upload.
- Shazam-style audio fingerprinting for the Broadcast agent: pre-loads broadcast context by identifying the video track before live telemetry fires. Need to integrate a web-audio fingerprinting library client-side in the PWA.
- Google AI Studio billing: I'm on Tier 1. Create a separate Google Cloud project and add $10-20 for clean Gemini API access. Do NOT use main Google account (billing mess from Google One/Play/AI Cloud).
- Siri Extensions framework: hidden in iOS 27 developer beta (Claude, Gemini, ChatGPT inside Siri) but APIs not yet public. Will matter when iOS 27 ships fall 2026.
- The "Code as Agent Harness" paper validates that my harness architecture is at the 2026 research frontier (Figure 3: Code for Reasoning, ReCode/ExecVerify/FunPRM tier; Figure 4: Meta-Harness/AutoHarness category).

## DO NOT do these things
- Do not re-explain the architecture to me — it's in the master ref
- Do not suggest Coword for build tasks
- Do not route real-time Wingman audio through OpenRouter (kills latency)
- Do not use Opus for tasks Sonnet handles (tokenizer bloat, 35% more tokens, no quality gain)
- Do not create files without verifying byte count before saying they're done
- Do not tell me "I can't access prior conversations" without searching first

