/**
 * Crew Role: Contract Analyst.
 *
 * Reads documents already in the project and flags risks, ambiguities,
 * missing terms, and compliance issues. This role does NOT cite case law —
 * that's the Researcher's job. The Analyst's output is grounded in the
 * actual document text, with span pointers so the UI can highlight.
 *
 * The Analyst never edits documents. It produces a structured report that
 * the Team Lead synthesizes.
 */

import type Anthropic from '@anthropic-ai/sdk';

export const CONTRACT_ANALYST_SYSTEM_PROMPT = `
You are the Contract Analyst on the Kingsfield Legal Crew. You read
documents and produce structured findings.

Hard rules:
- Every finding must reference a specific span in the source document
  (paragraph or section number). No vague "somewhere in the contract."
- You do not invent terms. If a clause is missing, say it is missing —
  don't paraphrase what you wish it said.
- You do not give legal advice. You surface issues. The Strategist decides
  what to do about them.
- You do not cite case law. That is the Researcher's role.

Your output is a JSON object with these arrays (each item structured below):

  risks:        clauses that create downside exposure
  ambiguities:  language that could be read multiple ways
  missing:      terms or sections you'd expect but don't see
  compliance:   regulatory or rule-based issues
  key_terms:    defined terms and where they're used

Each finding has:
  - section: a pointer like "§ 4.2" or "para 12"
  - quote: a verbatim snippet (≤ 25 words) — for finding the spot
  - issue: one sentence on what the issue is
  - severity: "high" | "medium" | "low"
`.trim();

export interface AnalystInput {
  documentText: string;
  documentName: string;
  task: string; // e.g., "review for one-sided indemnity clauses"
}

export type Severity = 'high' | 'medium' | 'low';

export interface Finding {
  section: string;
  quote: string;
  issue: string;
  severity: Severity;
}

export interface AnalystOutput {
  documentName: string;
  task: string;
  risks: Finding[];
  ambiguities: Finding[];
  missing: Finding[];
  compliance: Finding[];
  key_terms: Finding[];
}

export async function runContractAnalyst(
  input: AnalystInput,
  llm: Anthropic,
): Promise<AnalystOutput> {
  const resp = await llm.messages.create({
    model: 'claude-opus-4-7',
    max_tokens: 4096,
    system: CONTRACT_ANALYST_SYSTEM_PROMPT,
    messages: [
      {
        role: 'user',
        content: `
DOCUMENT NAME: ${input.documentName}
TASK: ${input.task}

DOCUMENT TEXT:
---
${input.documentText}
---

Return a JSON object with the keys: risks, ambiguities, missing,
compliance, key_terms. Each is an array of findings as defined in your
system prompt. Output ONLY the JSON. No preamble, no markdown fences.
        `.trim(),
      },
    ],
  });
  const text = extractText(resp).trim();
  const json = stripFences(text);
  const parsed = JSON.parse(json);
  return {
    documentName: input.documentName,
    task: input.task,
    risks: parsed.risks ?? [],
    ambiguities: parsed.ambiguities ?? [],
    missing: parsed.missing ?? [],
    compliance: parsed.compliance ?? [],
    key_terms: parsed.key_terms ?? [],
  };
}

function extractText(resp: any): string {
  return (resp.content ?? [])
    .filter((b: any) => b.type === 'text')
    .map((b: any) => b.text)
    .join('\n');
}

function stripFences(s: string): string {
  return s
    .replace(/^```(?:json)?\s*/i, '')
    .replace(/\s*```\s*$/i, '')
    .trim();
}
