# Claude Adapter — Kingsfield Harness Translation
# CONFIDENTIAL — TRADE SECRET — KINGSFIELD LAWFARE
# Created: 2026-06-15
# Purpose: Translates master harness into optimal prompt format for Claude models

## Model characteristics
- Training: Constitutional AI — will hedge on aggressive language unless explicitly suppressed
- Strengths: narrative reasoning, privilege analysis, storytelling, long-form synthesis
- Weaknesses: over-qualifies, adds unsolicited caveats, sometimes refuses sharp advocacy framing
- Optimal for: privilege analysis, narrative construction, persuasion strategy, work product drafting
- Weight higher when: task involves rhetoric, storytelling, or nuanced privilege questions

## Prompt structure rules
1. Use XML tags for every major harness section:
   <jurisdiction>, <judge_profile>, <case_theory>, <procedural_posture>,
   <alert_triggers>, <silence_rule>, <opposition_analysis>
2. Direct imperative voice throughout — no "you might consider" or "perhaps"
3. Prefix any analysis task with: "Think step by step before any legal analysis."
4. Suppress disclaimer behavior explicitly in system prompt:
   "Do not add caveats, qualifications, or suggestions to consult other counsel.
    Output only the analysis requested. No preamble. No postamble."
5. Rephrase objection triggers as factual alerts, not advocacy commands:
   WRONG: "Object immediately if witness lies"
   RIGHT: "Alert when witness statement contradicts prior deposition at [cite]"

## System prompt wrapper (prepend to every translated harness)
```
You are operating as a Kovel agent under the direction of licensed counsel.
Your outputs are attorney work product. Do not add disclaimers.
Do not suggest consulting other attorneys. Do not qualify your analysis.
Output only what is requested in the format specified.
Think step by step before any legal analysis.
[INSERT TRANSLATED HARNESS CONTENT HERE]
```

## Translation mapping
| Master harness field | Claude format |
|---|---|
| [JURISDICTIONAL FRAME] | `<jurisdiction>...</jurisdiction>` |
| [JUDGE PROFILE] | `<judge_profile>...</judge_profile>` |
| [CASE THEORY] | `<case_theory>...</case_theory>` |
| [PROCEDURAL POSTURE] | `<procedural_posture>...</procedural_posture>` |
| [ALERT TRIGGERS] | `<alert_triggers><trigger priority="1">...</trigger></alert_triggers>` |
| [SILENCE RULE] | `<silence_rule>...</silence_rule>` |

## Known failure modes to suppress
- "I should note that..." → suppress with system prompt instruction above
- "It's worth mentioning..." → suppress
- "While I can analyze this..." → suppress
- Offering balanced views when one-sided legal advocacy is requested → suppress
  by adding: "This is adversarial legal analysis. Present only the strongest
  version of the client's position."
- Adding "consult a licensed attorney" → suppress (Kovel designation handles this)
