/**
 * Crew Role: Team Lead + Coordinator.
 *
 * The Team Lead synthesizes the Researcher, Analyst, and Strategist into
 * a single coherent answer for the user. It also flags places where the
 * three roles disagreed — those flags surface in the UI as "things to
 * double-check before relying on this."
 *
 * The Coordinator is the entry point. It decides which crew roles to
 * spawn for a given user message, runs them in the right order, and
 * returns the Team Lead's synthesis plus a structured trace.
 *
 * Heuristics for which roles to spawn:
 *   - If there's a document attached → Researcher + Analyst + Strategist + Lead
 *   - If pure question / research → Researcher + Strategist + Lead
 *   - If casual / factual / "what is" → no crew, just answer directly
 *     (the Coordinator will return null and the chat falls back to
 *     single-agent mode)
 */

import type Anthropic from '@anthropic-ai/sdk';
import type { SupabaseClient } from '@supabase/supabase-js';
import {
  runResearcher,
  type ResearcherOutput,
  type ResearcherDeps,
  type VerifiedAuthority,
} from './researcher.js';
import {
  runContractAnalyst,
  type AnalystOutput,
} from './contract-analyst.js';
import { runStrategist, type StrategistOutput } from './strategist.js';

export const TEAM_LEAD_SYSTEM_PROMPT = `
You are the Team Lead on the Kingsfield Legal Crew. Three specialists
have produced inputs: the Researcher (verified authorities), the Contract
Analyst (document findings, if any), and the Strategist (situation,
options, recommendation).

Your job is to produce the single response the user actually sees.

Hard rules:
- You may cite only authorities the Researcher verified.
- If the Strategist and Analyst disagreed, surface it explicitly under
  "Watchouts." Do not paper over disagreement.
- Plain English. Translate Latin and terms of art the first time they
  appear. No filler. No "I hope this helps."
- Structure your response so the user can scan in 30 seconds and read
  in 3 minutes.

Output structure:

  ## Bottom line
  One paragraph. What we found, what we recommend.

  ## Authority
  Bulleted list of verified cites with one-line relevance.

  ## Document findings (if any)
  Top issues by severity.

  ## Recommendation
  The Strategist's recommendation, refined for clarity.

  ## Watchouts
  Any disagreement between roles, or any gap the Researcher flagged.

  ## Next step
  ONE concrete action.
`.trim();

export interface CrewInput {
  userMessage: string;
  matterContext: string;
  documentName?: string;
  documentText?: string;
  jurisdiction?: string;
}

export interface CrewDeps extends ResearcherDeps {}

export interface CrewOutput {
  /** Markdown response shown to the user. */
  reply: string;
  /** Full structured trace for debugging / audit. */
  trace: {
    researcher?: ResearcherOutput;
    analyst?: AnalystOutput;
    strategist?: StrategistOutput;
    decision: 'crew' | 'simple';
    rolesSpawned: string[];
  };
  /** Verified authorities surfaced in the reply, for downstream chips. */
  authorities: VerifiedAuthority[];
}

/**
 * Decide whether to spawn the crew for this message. Returns false for
 * casual / factual / one-liner questions where a single-agent reply is
 * better.
 */
export function shouldSpawnCrew(input: CrewInput): boolean {
  if (input.documentText) return true;
  const msg = input.userMessage.toLowerCase().trim();
  // Heuristic: short, casual, or definitional questions skip the crew.
  if (msg.length < 40) return false;
  if (/^(hi|hello|hey|thanks|thank you)\b/.test(msg)) return false;
  if (/^(what (does|is)|define|how do i spell)\b/.test(msg)) return false;
  return true;
}

export async function runCrew(input: CrewInput, deps: CrewDeps): Promise<CrewOutput> {
  if (!shouldSpawnCrew(input)) {
    return {
      reply: '',
      trace: { decision: 'simple', rolesSpawned: [] },
      authorities: [],
    };
  }

  const rolesSpawned: string[] = [];
  let researcher: ResearcherOutput | undefined;
  let analyst: AnalystOutput | undefined;
  let strategist: StrategistOutput | undefined;

  // Researcher always runs.
  rolesSpawned.push('researcher');
  researcher = await runResearcher(
    {
      query: input.userMessage,
      jurisdiction: input.jurisdiction,
      matterContext: input.matterContext,
    },
    deps,
  );

  // Analyst runs only when there's a document.
  if (input.documentText && input.documentName) {
    rolesSpawned.push('analyst');
    analyst = await runContractAnalyst(
      {
        documentName: input.documentName,
        documentText: input.documentText,
        task: input.userMessage,
      },
      deps.llm,
    );
  }

  // Strategist always runs.
  rolesSpawned.push('strategist');
  strategist = await runStrategist(
    {
      question: input.userMessage,
      matterContext: input.matterContext,
      verifiedAuthorities: researcher?.authorities ?? [],
      analystFindings: analyst,
    },
    deps.llm,
  );

  // Team Lead synthesizes.
  rolesSpawned.push('team_lead');
  const reply = await runTeamLead(
    {
      userMessage: input.userMessage,
      researcher: researcher!,
      analyst,
      strategist: strategist!,
    },
    deps.llm,
  );

  return {
    reply,
    trace: { decision: 'crew', rolesSpawned, researcher, analyst, strategist },
    authorities: researcher?.authorities ?? [],
  };
}

interface TeamLeadInput {
  userMessage: string;
  researcher: ResearcherOutput;
  analyst?: AnalystOutput;
  strategist: StrategistOutput;
}

async function runTeamLead(input: TeamLeadInput, llm: Anthropic): Promise<string> {
  const authBlock = input.researcher.authorities
    .map((a) => `- ${a.citation}: ${a.relevanceNote}`)
    .join('\n');

  const resp = await llm.messages.create({
    model: 'claude-opus-4-7',
    max_tokens: 3072,
    system: TEAM_LEAD_SYSTEM_PROMPT,
    messages: [
      {
        role: 'user',
        content: `
USER QUESTION:
${input.userMessage}

VERIFIED AUTHORITIES:
${authBlock || '(none)'}

GAPS FLAGGED BY RESEARCHER:
${input.researcher.gaps.join('\n') || '(none)'}

ANALYST FINDINGS:
${input.analyst ? JSON.stringify(input.analyst, null, 2) : '(no document)'}

STRATEGIST OUTPUT:
${JSON.stringify(input.strategist, null, 2)}

Produce the user-facing response per your system prompt's structure.
        `.trim(),
      },
    ],
  });
  return extractText(resp);
}

function extractText(resp: any): string {
  return (resp.content ?? [])
    .filter((b: any) => b.type === 'text')
    .map((b: any) => b.text)
    .join('\n');
}
