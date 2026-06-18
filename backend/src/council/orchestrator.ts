/**
 * Council Orchestrator.
 *
 * Runs the protocols defined in /docs/COUNCIL.md:
 *   - Standard Session       (full review, all relevant roles)
 *   - Citation-Only Review   (Skeptic only)
 *   - Strategy Sanity Check  (Strategist + Translator + Judge)
 *
 * Every session is logged to the council_sessions table with full
 * provenance: charter, role outputs, decision memo, dissents.
 */

import type { SupabaseClient } from '@supabase/supabase-js';
import type Anthropic from '@anthropic-ai/sdk';
import { runSkeptic, type SkepticOutput } from './skeptic.js';
import { runJudge, type JudgeOutput } from './judge.js';
import type { VerifyOptions } from '../verification/pipeline.js';

export type Protocol = 'standard' | 'citation-only' | 'strategy-sanity-check';

export interface SessionInput {
  protocol: Protocol;
  matterId: string;
  artifactId: string;
  artifactText: string;
  charter: string;
  matter: { forum: string; description: string };
  verifyOpts: VerifyOptions;
  llm: Anthropic;
  supabase: SupabaseClient;
}

export interface SessionOutput {
  sessionId: string;
  status: 'cleared' | 'blocked-by-skeptic' | 'completed-with-conditional' | 'completed-clean';
  skeptic: SkepticOutput;
  judge?: JudgeOutput;
  // ... other roles wired in similarly
  decisionMemo?: string;
}

export async function runSession(input: SessionInput): Promise<SessionOutput> {
  // Open the session row so all role outputs land in one log.
  const { data: session, error } = await input.supabase
    .from('council_sessions')
    .insert({
      matter_id: input.matterId,
      artifact_id: input.artifactId,
      protocol: input.protocol,
      charter: input.charter,
      started_at: new Date().toISOString(),
    })
    .select()
    .single();
  if (error) throw error;

  // Stage 1: Skeptic ALWAYS runs first. If it vetoes, the session halts.
  const skeptic = await runSkeptic({
    draftText: input.artifactText,
    verifyOpts: input.verifyOpts,
  });
  await persistRoleOutput(session.id, 'skeptic', skeptic, input.supabase);

  if (skeptic.vetoed) {
    await closeSession(session.id, 'blocked-by-skeptic', input.supabase);
    return { sessionId: session.id, status: 'blocked-by-skeptic', skeptic };
  }

  // Stage 2+: protocol-specific roles.
  let judge: JudgeOutput | undefined;
  if (input.protocol === 'standard' || input.protocol === 'strategy-sanity-check') {
    const verifiedSources = skeptic.cleared.map((v) => ({
      citation: v.citation,
      holding: '', // filled by a follow-up service that pulls cached holdings
    }));
    judge = await runJudge(
      {
        artifactText: input.artifactText,
        verifiedSources,
        matter: input.matter,
      },
      input.llm,
    );
    await persistRoleOutput(session.id, 'judge', judge, input.supabase);
  }

  // (Other roles — opposing_counsel, strategist, etc. — invoked here in
  // production. Skeleton above shows the pattern.)

  const status = skeptic.conditional.length > 0 ? 'completed-with-conditional' : 'completed-clean';
  await closeSession(session.id, status, input.supabase);

  return {
    sessionId: session.id,
    status,
    skeptic,
    judge,
  };
}

async function persistRoleOutput(
  sessionId: string,
  role: string,
  output: unknown,
  supabase: SupabaseClient,
) {
  await supabase.from('council_role_outputs').insert({
    session_id: sessionId,
    role,
    payload: output,
    created_at: new Date().toISOString(),
  });
}

async function closeSession(
  sessionId: string,
  status: SessionOutput['status'],
  supabase: SupabaseClient,
) {
  await supabase
    .from('council_sessions')
    .update({ status, ended_at: new Date().toISOString() })
    .eq('id', sessionId);
}
