/**
 * LLM Council orchestrator (Karpathy-style).
 *
 * Pipeline:
 *   1. Frame the question (with workspace context).
 *   2. Spawn all 5 advisors IN PARALLEL on their assigned providers.
 *   3. Anonymize the 5 responses (random A-E mapping per session).
 *   4. Spawn 5 reviewers IN PARALLEL on the anonymized set.
 *   5. Chairman synthesizes everything into the verdict.
 *   6. Persist transcript + render HTML report.
 */

import type { SupabaseClient } from '@supabase/supabase-js';
import {
  callModel,
  DEFAULT_ROUTING,
  type AdvisorRole,
  type LLMClients,
  type ModelChoice,
} from './providers.js';
import {
  ADVISOR_PROMPTS,
  CHAIRMAN_PROMPT,
  REVIEWER_PROMPT,
} from './prompts.js';

export interface CouncilInput {
  /** The user's raw "council this: …" message. */
  rawQuestion: string;
  /** Optional context the framer should consider — matter summary, etc. */
  context?: string;
  /** Per-deployment override of the model routing. */
  routing?: typeof DEFAULT_ROUTING;
}

export interface AdvisorResponse {
  role: AdvisorRole;
  model: ModelChoice;
  text: string;
  /** Anonymized letter A-E for the peer-review round. */
  letter: 'A' | 'B' | 'C' | 'D' | 'E';
}

export interface ReviewerResponse {
  reviewerRole: AdvisorRole;
  text: string;
}

export interface CouncilOutput {
  framedQuestion: string;
  advisors: AdvisorResponse[];
  reviewers: ReviewerResponse[];
  chairmanVerdict: string;
}

const ROLES: AdvisorRole[] = [
  'contrarian',
  'first_principles',
  'expansionist',
  'outsider',
  'executor',
];

export async function runLLMCouncil(
  input: CouncilInput,
  clients: LLMClients,
  supabase?: SupabaseClient,
  projectId?: string,
): Promise<CouncilOutput> {
  const routing = input.routing ?? DEFAULT_ROUTING;

  // Step 1 — frame the question.
  const framedQuestion = await frameQuestion(input, clients);

  // Step 2 — five advisors, parallel.
  const advisorResults = await Promise.all(
    ROLES.map((role) =>
      callModel(routing[role], {
        system: ADVISOR_PROMPTS[role],
        user: framedQuestion,
        maxTokens: 800,
      }, clients).then((text) => ({ role, model: routing[role], text })),
    ),
  );

  // Step 3 — anonymize. Random shuffle of letters A-E.
  const letters: Array<'A' | 'B' | 'C' | 'D' | 'E'> = shuffle(['A', 'B', 'C', 'D', 'E']);
  const advisors: AdvisorResponse[] = advisorResults.map((r, i) => ({
    ...r,
    letter: letters[i],
  }));
  const anonymizedBlock = advisors
    .slice()
    .sort((a, b) => a.letter.localeCompare(b.letter))
    .map((a) => `**Response ${a.letter}:**\n${a.text}`)
    .join('\n\n');

  // Step 4 — five reviewers, parallel. Each reviewer is the SAME advisor
  // role but reading the anonymized set. (Karpathy's setup: each advisor
  // reviews the others.)
  const reviewers = await Promise.all(
    ROLES.map((reviewerRole) =>
      callModel(routing[reviewerRole], {
        system: REVIEWER_PROMPT,
        user: `
QUESTION:
${framedQuestion}

ANONYMIZED RESPONSES:
${anonymizedBlock}

Answer the three review questions per your instructions.
        `.trim(),
        maxTokens: 600,
      }, clients).then((text) => ({ reviewerRole, text })),
    ),
  );

  // Step 5 — chairman synthesis.
  const chairmanVerdict = await callModel(
    routing.chairman,
    {
      system: CHAIRMAN_PROMPT,
      user: buildChairmanContext(framedQuestion, advisors, reviewers),
      maxTokens: 2048,
    },
    clients,
  );

  // Step 6 — persist transcript.
  const output: CouncilOutput = {
    framedQuestion,
    advisors,
    reviewers,
    chairmanVerdict,
  };
  if (supabase && projectId) {
    await persistSession(output, projectId, supabase);
  }
  return output;
}

// ───── stage helpers ─────

async function frameQuestion(
  input: CouncilInput,
  clients: LLMClients,
): Promise<string> {
  const framerPrompt = `
You are framing a question for the Kingsfield LLM Council. Take the user's
raw input and any context provided, and produce a clear, neutral framing
that all 5 advisors will receive.

The framing must include:
1. The core decision or question.
2. Key context from the user.
3. Key context from the workspace (if provided).
4. What's at stake.

Do not add your own opinion. Do not steer it. Output ONLY the framed
question. No preamble.
  `.trim();

  return callModel(
    DEFAULT_ROUTING.chairman,
    {
      system: framerPrompt,
      user: `
RAW QUESTION:
${input.rawQuestion}

CONTEXT:
${input.context ?? '(none provided)'}
      `.trim(),
      maxTokens: 800,
    },
    clients,
  );
}

function buildChairmanContext(
  framed: string,
  advisors: AdvisorResponse[],
  reviewers: ReviewerResponse[],
): string {
  const advisorBlock = advisors
    .map(
      (a) =>
        `**The ${labelFor(a.role)}** (${a.model.provider} ${a.model.model}):\n${a.text}`,
    )
    .join('\n\n');
  const reviewBlock = reviewers
    .map((r, i) => `**Review ${i + 1} (from ${labelFor(r.reviewerRole)}):**\n${r.text}`)
    .join('\n\n');

  return `
FRAMED QUESTION:
${framed}

ADVISOR RESPONSES (de-anonymized):
${advisorBlock}

PEER REVIEWS:
${reviewBlock}

Produce the council verdict per your prompt's structure.
  `.trim();
}

function labelFor(role: AdvisorRole): string {
  return {
    contrarian: 'Contrarian',
    first_principles: 'First Principles Thinker',
    expansionist: 'Expansionist',
    outsider: 'Outsider',
    executor: 'Executor',
  }[role];
}

function shuffle<T>(arr: T[]): T[] {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

async function persistSession(
  out: CouncilOutput,
  projectId: string,
  supabase: SupabaseClient,
) {
  await supabase.from('llm_council_sessions').insert({
    project_id: projectId,
    framed_question: out.framedQuestion,
    advisors: out.advisors,
    reviewers: out.reviewers,
    chairman_verdict: out.chairmanVerdict,
    created_at: new Date().toISOString(),
  });
}
