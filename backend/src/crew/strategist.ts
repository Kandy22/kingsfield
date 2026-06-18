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

import { completeText } from '../lib/llm/index.js';
import type { VerifiedAuthority } from './researcher.js';
import type { AnalystOutput } from './contract-analyst.js';

export const STRATEGIST_SYSTEM_PROMPT = `
You are the Strategist on the Kingsfield Legal Crew. You take in verified
research and document findings and produce a strategic view.

Hard rules:
- You may discuss only authorities provided in the verified-research
  context. You never introduce new citations.
- You produce a strategic memo with direct, concrete recommendations.
  Never recommend the user "consult an attorney" or "seek counsel" —
  that is not a strategy. Give them the actual strategy.
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
  model: string,
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

  // Cap matterContext so it doesn't eat the whole token budget.
  const safeContext = (input.matterContext ?? '').slice(0, 8000);

  const text = await completeText({
    model,
    systemPrompt: STRATEGIST_SYSTEM_PROMPT,
    user: `
QUESTION:
${input.question}

MATTER CONTEXT:
${safeContext}

VERIFIED AUTHORITIES (these are the only ones you may discuss):
${authBlock || '(No authorities yet.)'}

DOCUMENT FINDINGS:
${findingsBlock}

Produce your structured output. Return as JSON with the schema implied by
your system prompt: situation, risks[], leverage[], options[],
recommendation, recommendationReasoning, proceduralSteps[]. Output ONLY
the JSON. Keep each field concise — total response must fit in 4000 tokens.
    `.trim(),
    maxTokens: 6144,
  });

  const raw = stripFences(text.trim());
  try {
    return JSON.parse(raw);
  } catch {
    // JSON was truncated — attempt to recover a partial object by closing
    // open brackets/braces, then parse again.
    const recovered = recoverTruncatedJson(raw);
    try {
      return JSON.parse(recovered);
    } catch {
      // Fall back to a minimal safe structure so the Team Lead can still run.
      console.error('[strategist] JSON parse failed, using fallback structure');
      return {
        situation: raw.slice(0, 500),
        risks: [],
        leverage: [],
        options: [],
        recommendation: 'Analysis was too large to parse fully — see situation summary above.',
        recommendationReasoning: '',
        proceduralSteps: [],
      };
    }
  }
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

function stripFences(s: string): string {
  return s.replace(/^```(?:json)?\s*/i, '').replace(/\s*```\s*$/i, '').trim();
}

/**
 * Attempt to close an unterminated JSON string by counting open brackets
 * and braces and appending the right closers. Not perfect, but handles the
 * common case of an LLM hitting its token limit mid-object.
 */
function recoverTruncatedJson(s: string): string {
  // Find the last valid JSON boundary — cut off any dangling partial value.
  let truncated = s;
  // Remove trailing incomplete string (unclosed quote after last complete value)
  truncated = truncated.replace(/,?\s*"[^"]*$/, '');
  // Remove trailing comma before a closing bracket
  truncated = truncated.replace(/,(\s*[}\]])/, '$1');

  // Count unmatched openers and close them in reverse order.
  const stack: string[] = [];
  let inString = false;
  let escape = false;
  for (const ch of truncated) {
    if (escape) { escape = false; continue; }
    if (ch === '\\') { escape = true; continue; }
    if (ch === '"') { inString = !inString; continue; }
    if (inString) continue;
    if (ch === '{') stack.push('}');
    else if (ch === '[') stack.push(']');
    else if (ch === '}' || ch === ']') stack.pop();
  }
  return truncated + stack.reverse().join('');
}
