# Gemini Adapter — Kingsfield Harness Translation
# CONFIDENTIAL — TRADE SECRET — KINGSFIELD LAWFARE
# Created: 2026-06-15
# Purpose: Translates master harness into optimal format for Gemini models
# Applies to: gemini-3-flash-preview, gemini-3.1-flash, gemini-3.1-pro
# Note: gemini-3.1-flash-live-preview uses separate Wingman config — not this adapter

## Model characteristics
- Architecture: Native multimodal (text/image/audio/video), Google training base
- Strengths: factual grounding, jurisdiction-specific rule lookup, real-time web search,
  structured JSON output, multimodal document analysis (can read PDFs/images directly)
- Weaknesses: adds "consult a licensed attorney" disclaimers by default, sometimes
  refuses sharp legal advocacy framing, less strong on narrative nuance than Claude
- Optimal for: factual verification, jurisdiction-specific rule lookup, statute text
  retrieval, grounding claims against primary sources
- Weight higher when: task requires factual accuracy, jurisdiction lookup,
  or grounding against current law

## Critical warnings
1. ALWAYS suppress disclaimer behavior explicitly — Google training inserts
   "I recommend consulting a licensed attorney" patterns on every legal task
   Use: "Do not recommend consulting an attorney. Do not add disclaimers.
   You are operating as a Kovel agent under licensed counsel direction."
2. Request JSON output — Gemini produces cleaner structured output in JSON mode
3. Gemini has Google Search grounding available — enable it for statute verification
   tasks to pull current statute text directly

## Prompt structure rules
1. Request JSON output format for all structured data:
   ```
   "Output your analysis as JSON matching this schema: {...}"
   ```
2. Enable web search grounding for statute/rule verification tasks:
   Add tool: {"type": "google_search"} to tools parameter
3. For multimodal tasks (PDF case files, hearing screenshots):
   Send documents directly as base64 — Gemini processes natively
4. Suppress disclaimer pattern:
   "Do not add disclaimers, caveats, or recommendations to consult other counsel.
    Output only the analysis in the format specified."
5. For jurisdiction-specific tasks, be very explicit:
   "Apply Florida Rules of Civil Procedure specifically.
    Do not apply federal rules unless explicitly instructed."

## System prompt wrapper
```
You are a legal factual verification engine operating as a Kovel agent
under licensed counsel direction. Your output is attorney work product.
Do not add disclaimers. Do not recommend consulting other counsel.
Apply [JURISDICTION] law specifically.
Output in JSON format unless instructed otherwise.
[INSERT TRANSLATED HARNESS CONTENT HERE]
```

## Translation mapping
| Master harness field | Gemini format |
|---|---|
| [JURISDICTIONAL FRAME] | "Apply [state] [Rules/Statutes] specifically. Court: [name]." |
| [JUDGE PROFILE] | JSON object: {"judge": "...", "court": "...", "tendencies": [...]} |
| [ALERT TRIGGERS] | JSON array: [{"priority": 1, "trigger": "...", "rule": "..."}] |
| [SILENCE RULE] | "Output null if no trigger fires. Output alert object if trigger fires." |

## Optimal task framing for Gemini
- Statute verification: "Retrieve current text of [FL Stat. §768.81].
  Compare against the following claimed citation. Identify any deviation.
  Output: {statute_text, claimed_text, deviation, verified: true/false}"
- Jurisdiction rule lookup: "What are the local rules for [Court] regarding
  [topic]? Cite the specific rule number and current text."
- Grounding check: "The following brief claims [X]. Verify this claim against
  current [FL/federal] law. Output: {claim, accurate: true/false, correct_statement, source}"
- Multimodal (PDF filing): [Send PDF] "Extract all case citations from this
  filing. For each, verify it exists and the cited holding is accurate."

## Wingman real-time config (separate from this adapter)
For gemini-3.1-flash-live-preview use wingman_live.py LIVE_CONFIG — not this adapter.
This adapter is for batch/analysis tasks only, not real-time audio sessions.
