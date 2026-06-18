/**
 * Crew Role: Researcher.
 *
 * Pulls authority from CourtListener, Caselaw Access Project, eCFR, and
 * Congress.gov. EVERY citation that comes back from this role has already
 * been verified through Gate 1 (existence). Quote accuracy (Gate 2),
 * currency (Gate 3), and jurisdiction fit (Gate 4) are checked downstream
 * by the Skeptic before any output ships.
 *
 * The Researcher is forbidden from citing anything it has not actually
 * pulled. If the model wants to "remember" a case, it gets refused and
 * told to search for it.
 */

import { completeText } from '../lib/llm/index.js';
import { citationLookup, getCluster, getOpinion } from '../research/courtlistener.js';
import type { SupabaseClient } from '@supabase/supabase-js';

export const RESEARCHER_SYSTEM_PROMPT = `
You are the Researcher on the Kingsfield Legal Crew. Your job is to find
and surface relevant primary authority for the question at hand.

Hard rules:
- You do NOT cite cases, statutes, or regulations from memory. Ever.
- For every authority you reference, you must have first asked the system
  to PULL it from a primary source (CourtListener, Caselaw Access Project,
  eCFR, Congress.gov, or an official state legislature site).
- If you want to cite something but haven't pulled it, the correct output
  is: "I want to look up [search query]. Please run the search."
- Cases that come back from the search are passed to you with a verified
  flag. Use only those. If a case lacks the flag, do not cite it.

Your output for any question:
1. SEARCH PLAN — what queries should we run, against which sources?
2. RESULTS — for each pulled authority, a one-paragraph neutral summary of
   the holding, with the pin cites that matter.
3. RELEVANCE — for each authority, why it matters for the user's question.
4. GAPS — what we still don't have and would need to find.

You produce no legal advice. You produce research. The Strategist and
Team Lead use what you find.
`.trim();

export interface ResearcherInput {
  query: string;
  jurisdiction?: string;
  matterContext?: string;
}

export interface VerifiedAuthority {
  citation: string;
  shortName: string;
  jurisdiction: string;
  year?: number;
  holdingSummary: string;
  relevanceNote: string;
  sourceUrl: string;
  cl_cluster_id?: number;
  cl_opinion_id?: number;
  fetchedAt: string;
  /** sha256 of the document text we relied on. */
  sha256: string;
}

export interface ResearcherOutput {
  searchPlan: string[];
  authorities: VerifiedAuthority[];
  gaps: string[];
}

export interface ResearcherDeps {
  model: string;
  supabase: SupabaseClient;
  courtListenerToken: string;
}

/**
 * Run the Researcher.
 *
 * Two-phase:
 *   1. Ask the model what to search for (search plan).
 *   2. For each search, hit CourtListener, persist the source, summarize.
 *
 * Phase 2 is deterministic, not generative — the model never invents a
 * case during step 2.
 */
export async function runResearcher(
  input: ResearcherInput,
  deps: ResearcherDeps,
): Promise<ResearcherOutput> {
  // Phase 1 — search plan.
  // IMPORTANT: citationLookup() is a *verifier*, not a search engine.
  // It checks whether citation strings (e.g. "424 U.S. 319") exist in
  // CourtListener. Phase 1 must therefore produce specific case citations
  // that the model believes are relevant — NOT topic keywords.
  // The model draws on training to propose; CourtListener verifies.
  const planText = await completeText({
    model: deps.model,
    systemPrompt: RESEARCHER_SYSTEM_PROMPT,
    user: `
QUESTION: ${input.query}
${input.jurisdiction ? `JURISDICTION: ${input.jurisdiction}` : ''}
${input.matterContext ? `MATTER CONTEXT:\n${input.matterContext}` : ''}

Output only the SEARCH PLAN section. List 5-8 specific case citations that
are likely relevant to this question. Use the full citation format so
CourtListener can verify them (e.g. "Haines v. Kerner, 404 U.S. 519 (1972)").
Draw on your training knowledge — we will verify each citation against
CourtListener before using it. Do NOT include statutes or regulations here;
only cases. Format each as:
  - QUERY: "<Case Name, Volume Reporter Page (Year)>" SOURCE: courtlistener
    `.trim(),
    maxTokens: 1024,
  });
  const searchPlan = parseSearchPlan(planText);

  // Phase 2 — execute searches deterministically.
  const authorities: VerifiedAuthority[] = [];
  const gaps: string[] = [];
  for (const step of searchPlan) {
    if (step.source === 'courtlistener') {
      try {
        const hits = await citationLookup(step.query, deps.courtListenerToken);
        for (const hit of hits.filter((h) => h.status === 'matched' && h.cluster_id)) {
          const auth = await materializeAuthority(hit.cluster_id!, deps);
          if (auth) authorities.push(auth);
        }
        if (hits.every((h) => h.status !== 'matched')) {
          gaps.push(`No CourtListener match for: ${step.query}`);
        }
      } catch (e: any) {
        gaps.push(`Search failed for "${step.query}": ${e.message}`);
      }
    }
    // (eCFR / Congress adapters wired in similarly.)
  }

  // Phase 3 — ask the model to write holding summaries + relevance notes
  // for the verified set. Give it ONLY the verified authorities.
  if (authorities.length > 0) {
    const noteText = await completeText({
      model: deps.model,
      systemPrompt: RESEARCHER_SYSTEM_PROMPT,
      user: `
QUESTION: ${input.query}

VERIFIED AUTHORITIES (these are the only ones you may discuss):
${authorities
  .map(
    (a, i) =>
      `[${i}] ${a.citation}\n  URL: ${a.sourceUrl}`,
  )
  .join('\n\n')}

For each authority above (by index), provide:
  1. A one-sentence holding summary (what the court actually held).
  2. A one-sentence relevance note explaining why it matters for the question.

Format strictly as:
  [0] HOLDING: <one-sentence holding>
  [0] RELEVANCE: <one-sentence relevance>
  [1] HOLDING: <one-sentence holding>
  [1] RELEVANCE: <one-sentence relevance>
  ...
      `.trim(),
      maxTokens: 2048,
    });
    applyRelevanceNotes(authorities, noteText);
  }

  return { searchPlan: searchPlan.map((s) => s.query), authorities, gaps };
}

// ───── helpers ─────

interface PlanStep {
  query: string;
  source: 'courtlistener' | 'ecfr' | 'congress';
}

function parseSearchPlan(text: string): PlanStep[] {
  const out: PlanStep[] = [];
  const re = /QUERY:\s*"([^"]+)"\s*SOURCE:\s*(\w+)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    const src = m[2].toLowerCase();
    if (src === 'courtlistener' || src === 'ecfr' || src === 'congress') {
      out.push({ query: m[1], source: src });
    }
  }
  return out;
}

async function materializeAuthority(
  clusterId: number,
  deps: ResearcherDeps,
): Promise<VerifiedAuthority | null> {
  const cluster = await getCluster(clusterId, deps.courtListenerToken);
  const opinionUrl = cluster.sub_opinions[0];
  const opinion = opinionUrl ? await getOpinion(opinionUrl, deps.courtListenerToken) : null;
  const fullText = opinion?.html_with_citations ?? opinion?.plain_text ?? '';

  const crypto = await import('node:crypto');
  const sha256 = crypto.createHash('sha256').update(fullText).digest('hex');

  // Persist into sources table (or update if it exists).
  const citation = formatBluebook(cluster);
  const { data: existing } = await deps.supabase
    .from('sources')
    .select('id')
    .eq('citation_bluebook', citation)
    .maybeSingle();

  if (!existing) {
    await deps.supabase.from('sources').insert({
      type: 'case',
      citation_bluebook: citation,
      short_name: cluster.case_name,
      jurisdiction: cluster.court,
      year: parseInt(cluster.date_filed?.slice(0, 4) ?? '0', 10) || null,
      source_url: `https://www.courtlistener.com${cluster.absolute_url}`,
      sha256,
      full_text: fullText,
      cl_cluster_id: cluster.id,
      cl_opinion_id: opinion?.id ?? null,
    });
  }

  return {
    citation,
    shortName: cluster.case_name,
    jurisdiction: cluster.court,
    year: parseInt(cluster.date_filed?.slice(0, 4) ?? '0', 10) || undefined,
    holdingSummary: '', // populated by phase 3
    relevanceNote: '',
    sourceUrl: `https://www.courtlistener.com${cluster.absolute_url}`,
    cl_cluster_id: cluster.id,
    cl_opinion_id: opinion?.id,
    fetchedAt: new Date().toISOString(),
    sha256,
  };
}

function formatBluebook(cluster: any): string {
  const c = cluster.citations?.[0];
  if (!c) return cluster.case_name;
  const year = cluster.date_filed?.slice(0, 4);
  return `${cluster.case_name}, ${c.volume} ${c.reporter} ${c.page} (${year})`;
}

function applyRelevanceNotes(authorities: VerifiedAuthority[], text: string) {
  const holdingRe = /\[(\d+)\]\s+HOLDING:\s*([^\n]+)/g;
  const relevanceRe = /\[(\d+)\]\s+RELEVANCE:\s*([^\n]+)/g;
  let m: RegExpExecArray | null;
  while ((m = holdingRe.exec(text)) !== null) {
    const i = parseInt(m[1], 10);
    if (authorities[i]) authorities[i].holdingSummary = m[2].trim();
  }
  while ((m = relevanceRe.exec(text)) !== null) {
    const i = parseInt(m[1], 10);
    if (authorities[i]) authorities[i].relevanceNote = m[2].trim();
  }
  // Fallback: if no structured tags, treat any [N] line as a relevance note.
  if (authorities.every((a) => !a.relevanceNote)) {
    const fallbackRe = /\[(\d+)\]\s*([^\n]+)/g;
    while ((m = fallbackRe.exec(text)) !== null) {
      const i = parseInt(m[1], 10);
      if (authorities[i] && !authorities[i].relevanceNote) {
        authorities[i].relevanceNote = m[2].trim();
      }
    }
  }
}

