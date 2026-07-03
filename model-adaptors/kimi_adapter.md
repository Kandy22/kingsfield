# Kimi Adapter — Kingsfield Harness Translation
# CONFIDENTIAL — TRADE SECRET — KINGSFIELD LAWFARE
# Created: 2026-06-15
# Purpose: Translates master harness into optimal format for Kimi K2.6 / K2.7
# Applies to: moonshotai/kimi-k2.6, moonshotai/kimi-k2.7-code

## Model characteristics
- Architecture: Native multimodal MoE, 256K context window, always-on thinking mode
- Strengths: long-context document analysis, citation verification, multi-turn reasoning,
  code generation, structured extraction from large document sets
- Weaknesses: US-specific legal nuance, colloquialisms, informal legal shorthand
- Optimal for: citation checking, long document analysis, cross-referencing
  multiple case files, extracting specific passages from large records
- Weight higher when: task requires citation verification, cross-referencing
  multiple documents, or extracting specific data from large records

## Critical notes
1. 256K context = can receive entire case file, all prior deposition transcripts,
   and the full harness in a single call — use this aggressively
2. Always-on thinking mode means it reasons before responding — latency is higher
   but output quality for complex tasks is strong — do not use for real-time Wingman
3. Define US legal shorthand explicitly — model knows law but may not know
   US-specific abbreviations and shorthand
4. Request English-language legal citation format explicitly:
   "Use neutral citation format: [Case Name], [Volume] [Reporter] [Page] ([Court] [Year])"

## Legal idiom glossary to include in every Kimi harness
```
Include this glossary in every prompt sent to Kimi:
LEGAL TERMS REFERENCE:
- Hearsay: out-of-court statement offered for truth of matter asserted (FRE 801)
- Motion in limine: pretrial motion to exclude evidence
- Work product: materials prepared in anticipation of litigation (FRCP 26(b)(3))
- Kovel agent: non-attorney agent operating under attorney direction, covered by privilege
- Pro se: self-represented party
- DCA: District Court of Appeal (Florida appellate structure)
- FRE: Federal Rules of Evidence
- FRCP: Federal Rules of Civil Procedure
- FRCrimP: Federal Rules of Criminal Procedure
```

## Prompt structure rules
1. Front-load all documents — Kimi handles long context well, put everything first
2. Request JSON output for citation extraction:
   ```json
   {
     "citations": [
       {
         "citation_text": "...",
         "verified": true/false,
         "correct_citation": "...",
         "source": "CourtListener/Justia/Westlaw",
         "deviation": "..."
       }
     ]
   }
   ```
3. For cross-referencing tasks: "Compare document A and document B.
   Identify every instance where a claim in document A is contradicted
   or unsupported by document B. Output as numbered list."
4. For long document extraction: "From the following [N] pages of deposition,
   extract every statement by [witness] about [topic]. Quote verbatim.
   Include page and line number."

## System prompt wrapper
```
You are a legal document analysis engine operating as a Kovel agent
under licensed counsel direction. Your output is attorney work product.
No disclaimers. Use neutral citation format for all case citations.
[INSERT LEGAL TERMS GLOSSARY]
[INSERT TRANSLATED HARNESS CONTENT HERE]
```

## Optimal task framing for Kimi
- Citation verification: "Verify every legal citation in the following document.
  For each citation: confirm it exists, confirm the page/holding cited is accurate,
  flag any deviation. Output as JSON."
- Long document cross-reference: "The following are [N] deposition transcripts
  and [M] prior filings. Identify every inconsistency between witness statements
  across these documents. Organize by witness, then by topic."
- Record extraction: "Extract all statements about [specific topic] from the
  following hearing transcript. Quote verbatim. Note speaker, timestamp if available."
