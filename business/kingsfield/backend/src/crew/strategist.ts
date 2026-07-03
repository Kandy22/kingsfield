/**
 * Crew Role: Strategist.
 *
 * Looks at the question, the Researcher's authorities, and the Analyst's
 * findings, and produces a strategic view: risks, leverage, procedural
 * posture, recommended next steps.
 *
 * The Strategist is allowed to reason about case law but only authorities
 * that the Researcher has already verified. It cannot introduce new cites.
 */

import type Anthropic from '@anthropic-ai/sdk';
import type { VerifiedAuthority } from './researcher.js';
import type { AnalystOutput } from './contract-analyst.js';

export const STRATEGIST_SYSTEM_PROMPT = `
You are the Strategist on the Kingsfield Legal Crew. You take in verified
research and document findings and produce a strategic view.

Hard rules:
- You may discuss only authorities provided in the verified-research
  context. You never introduce new citations.
- You never produce filings or legal advice. You produce a strategic memo.
- You make tradeoffs explicit. "Option A is faster but burns judicial
  goodwill. Option B is slower but builds the record."

Your output is structured:

1. SITUATION (one paragraph) — what's happening, in plain English.
2. RISKS — top 3-5, each with severity (high/medium/low) and a one-line
   explanation.
3. LEVERAGE — what we have working for us (admissions, documents,
   procedural posture).
4. OPTIONS — 2-3 paths forward, each with cost, benefit, likely outcome.
5. RECOMMENDATION — your call, with reasoning.
6. PROCEDURAL NEXT STEPS — concrete actions with deadlines (use the
   matter's actual posture; don't invent dates).

Do not hedge. The Team Lead will integrate dissent if it exists.
`.trim();

export interface StrategistInput {
  question: string;
  matterContext: string;
  verifiedAuthorities: VerifiedAuthority[];
  analystFindings?: AnalystOutput;
}

export interface StrategistOutput {
  situation: string;
  risks: Array<{ severity: 'high' | 'medium' | 'low'; description: string }>;
  leverage: string[];
  options: Array<{
    name: string;
    cost: string;
    benefit: string;
    likelyOutcome: string;
  }>;
  recommendation: string;
  recommendationReasoning: string;
  proceduralSteps: Array<{ action: string; deadline: string }>;
}

export async function runStrategist(
  input: StrategistInput,
  llm: Anthropic,
): Promise<StrategistOutput> {
  const authBlock = input.verifiedAuthorities
    .map(
      (a) =>
        `- ${a.citation}\n  Holding: ${a.holdingSummary}\n  Relevance: ${a.relevanceNote}`,
    )
    .join('\n\n');

  const findingsBlock = input.analystFindings
    ? formatFindings(input.analystFindings)
    : '(No document findings — research-only question.)';

  const resp = await llm.messages.create({
    model: 'claude-opus-4-7',
    max_tokens: 3072,
    system: STRATEGIST_SYSTEM_PROMPT,
    messages: [
      {
        role: 'user',
        content: `
QUESTION:
${input.question}

MATTER CONTEXT:
${input.matterContext}

VERIFIED AUTHORITIES (these are the only ones you may discuss):
${authBlock || '(No authorities yet.)'}

DOCUMENT FINDINGS:
${findingsBlock}

Produce your structured output. Return as JSON with the schema implied by
your system prompt: situation, risks[], leverage[], options[],
recommendation, recommendationReasoning, proceduralSteps[]. Output ONLY
the JSON.
        `.trim(),
      },
    ],
  });

  const text = extractText(resp).trim();
  return JSON.parse(stripFences(text));
}

function formatFindings(f: AnalystOutput): string {
  const block = (label: string, items: any[]) =>
    items.length === 0
      ? ''
      : `${label}:\n${items
          .map((i) => `  - [${i.severity}] ${i.section}: ${i.issue}`)
          .join('\n')}`;
  return [
    block('Risks', f.risks),
    block('Ambiguities', f.ambiguities),
    block('Missing', f.missing),
    block('Compliance', f.compliance),
  ]
    .filter(Boolean)
    .join('\n\n');
}

function extractText(resp: any): string {
  return (resp.content ?? [])
    .filter((b: any) => b.type === 'text')
    .map((b: any) => b.text)
    .join('\n');
}

function stripFences(s: string): string {
  return s.replace(/^```(?:json)?\s*/i, '').replace(/\s*```\s*$/i, '').trim();
}
