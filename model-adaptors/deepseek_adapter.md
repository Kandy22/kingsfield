# DeepSeek Adapter — Kingsfield Harness Translation
# CONFIDENTIAL — TRADE SECRET — KINGSFIELD LAWFARE
# Created: 2026-06-15
# Purpose: Translates master harness into optimal prompt format for DeepSeek models
# Applies to: deepseek-v4-pro, deepseek-v4-flash, deepseek-v3.2

## Model characteristics
- Training: Chinese MoE architecture — strong logical/mathematical reasoning
- Strengths: statutory element analysis, logical decomposition, code, structured output
- Weaknesses: English legal idiom nuance, narrative persuasion, US procedural subtleties
- Optimal for: element-by-element statutory analysis, logical flaw detection, contradiction mapping
- Weight higher when: task is statutory interpretation, logical chain analysis, or element testing

## Critical warnings
1. ALWAYS include "Respond in English only." as first line of system prompt
   — Chinese token patterns degrade legal English output without this
2. DO NOT use translated framing or bilingual examples in the harness
   — pure English system prompt throughout
3. Legal idiom that is obvious to US lawyers may be unknown — define it:
   "Motion in limine: pretrial motion to exclude evidence before trial begins"
   "Voir dire: jury selection process"
   "Pro se: party representing themselves without attorney"
4. Model is strong on formal logic — frame tasks as logical problems where possible

## Prompt structure rules
1. Use structured markdown with explicit headers:
   ## Jurisdiction, ## Case Theory, ## Alert Triggers, ## Output Format
2. Ask for numbered logical steps in analysis:
   "Analyze in numbered steps: 1) identify the legal rule, 2) apply rule to facts,
    3) identify any deviation, 4) state conclusion."
3. Request explicit confidence scores:
   "For each finding, state confidence: HIGH / MEDIUM / LOW"
4. Use JSON output for structured data (citation lists, element checks):
   "Output citation verification results as JSON array:
    [{citation, verified: true/false, source, deviation_if_any}]"

## System prompt wrapper
```
Respond in English only. You are a legal analysis engine operating as a
Kovel agent under licensed counsel direction. Your output is attorney work product.
No disclaimers. No qualifications. Analyze only what is requested.
Use numbered logical steps. State confidence level for each finding.
[INSERT TRANSLATED HARNESS CONTENT HERE]
```

## Translation mapping
| Master harness field | DeepSeek format |
|---|---|
| [JURISDICTIONAL FRAME] | ## Jurisdiction\n**Court:** ...\n**Rules:** ... |
| [JUDGE PROFILE] | ## Judge Profile\n**Name:** ...\n**Tendencies:** ... |
| [CASE THEORY] | ## Case Theory\n**Client position:** ...\n**Opposition:** ... |
| [ALERT TRIGGERS] | ## Alert Triggers (ranked)\n1. [highest priority]\n2. ... |
| [SILENCE RULE] | ## Output Rule\nDefault: output nothing. Alert only when confidence = HIGH. |

## Optimal task framing for DeepSeek
- Statutory analysis: "Apply the following statute elements to the following facts.
  For each element: state the element, state the relevant fact, state whether
  satisfied (YES/NO/UNCLEAR), cite the authority."
- Contradiction detection: "Compare statement A and statement B.
  Identify every logical contradiction. For each: quote the contradiction,
  explain why it is contradictory, state the legal significance."
- Element testing: "The prosecution must prove elements [list].
  For each element: identify weakness in the evidence, identify best defense argument."
