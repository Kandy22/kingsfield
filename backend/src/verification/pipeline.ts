/**
 * Four-Gate Citation Verification Pipeline.
 *
 * This is the heart of the anti-hallucination layer. Every citation that
 * could appear in any output must pass all four gates:
 *
 *   Gate 1: Existence       — does this case/statute actually exist?
 *   Gate 2: Quote Accuracy  — does it actually say what we claim?
 *   Gate 3: Currency        — is it still good law?
 *   Gate 4: Jurisdiction Fit — is it binding/persuasive in this forum?
 *
 * The pipeline never silently rewrites. It returns a verdict; the model
 * output is held by the orchestrator and only released to the user once
 * verdicts are resolved.
 *
 * See /docs/HALLUCINATION-PROTOCOL.md for the doctrinal version.
 */

import crypto from 'node:crypto';
import {
  citationLookup,
  getCluster,
  getOpinion,
  checkCurrency,
  type CitationLookupHit,
} from '../research/courtlistener.js';
import type { SupabaseClient } from '@supabase/supabase-js';

export type VerdictStatus = 'verified' | 'conditional' | 'vetoed' | 'pending';

export interface CitationCandidate {
  /** The raw citation string as it appears in the draft. */
  citation: string;
  /** Optional pin cite (page number) inside the cite. */
  pinCite?: string;
  /** Optional quoted language attributed to the source. */
  quotedText?: string;
  /** Where in the draft this candidate sits — for UI highlighting. */
  spanStart?: number;
  spanEnd?: number;
}

export interface MatterContext {
  /** The forum / court the matter is in (e.g., "S.D. Fla.", "Fla. Cir. Ct."). */
  forum: string;
  /** Bench / appellate level for jurisdiction-fit analysis. */
  jurisdictionTier: 'us-supreme' | 'circuit' | 'district' | 'state-supreme' | 'state-appellate' | 'state-trial';
}

export interface GateVerdict {
  citation: string;
  status: VerdictStatus;
  gate1_existence: boolean;
  gate2_quote_accuracy: boolean | null; // null if no quote was attributed
  gate3_currency: 'green' | 'yellow' | 'red' | null;
  gate4_jurisdiction_fit: 'mandatory' | 'persuasive' | 'off-point' | null;
  notes: string[];
  /** ID of the persisted source row, if cached. */
  sourceId?: string;
  /** sha256 of the cached document, if cached. */
  sha256?: string;
}

export interface VerifyOptions {
  courtListenerToken: string;
  supabase: SupabaseClient;
  matter: MatterContext;
}

/**
 * Verify a single candidate. Caller is responsible for batching when checking
 * a whole draft (see verifyDraft below).
 */
export async function verifyCitation(
  candidate: CitationCandidate,
  opts: VerifyOptions,
): Promise<GateVerdict> {
  const verdict: GateVerdict = {
    citation: candidate.citation,
    status: 'pending',
    gate1_existence: false,
    gate2_quote_accuracy: null,
    gate3_currency: null,
    gate4_jurisdiction_fit: null,
    notes: [],
  };

  // Try cache first — re-verifying every cite on every request is wasteful.
  const cached = await readCache(candidate.citation, opts.supabase);
  if (cached) {
    verdict.sourceId = cached.id;
    verdict.sha256 = cached.sha256;
    verdict.gate1_existence = true;
    verdict.notes.push('Cache hit.');
  } else {
    // Gate 1: existence via CourtListener Citation Lookup.
    const hits = await citationLookup(candidate.citation, opts.courtListenerToken);
    const hit = hits.find((h) => h.status === 'matched');
    if (!hit || !hit.cluster_id) {
      verdict.status = 'vetoed';
      verdict.notes.push(
        'CITATION NOT FOUND in CourtListener. Possible hallucination. Verify against ' +
          'Caselaw Access Project or original reporter before any use.',
      );
      return verdict;
    }
    verdict.gate1_existence = true;

    // Pull cluster + first opinion text, hash it, persist as a Source row.
    const cluster = await getCluster(hit.cluster_id, opts.courtListenerToken);
    const opinionUrl = cluster.sub_opinions[0];
    const opinion = opinionUrl
      ? await getOpinion(opinionUrl, opts.courtListenerToken)
      : null;
    const fullText = opinion?.html_with_citations ?? opinion?.plain_text ?? '';
    const sha256 = crypto.createHash('sha256').update(fullText).digest('hex');

    const inserted = await writeCache(
      {
        citation_bluebook: candidate.citation,
        type: 'case',
        jurisdiction: cluster.court,
        year: parseInt(cluster.date_filed?.slice(0, 4) ?? '0', 10) || null,
        source_url: hit.url ?? `https://www.courtlistener.com${cluster.absolute_url}`,
        sha256,
        full_text: fullText,
        // Persist the opinion ID so Gate 3 (currency) can run on cache hits.
        // Requires migration: ALTER TABLE sources ADD COLUMN IF NOT EXISTS cl_opinion_id bigint;
        cl_opinion_id: opinion?.id ?? null,
      },
      opts.supabase,
    );
    verdict.sourceId = inserted.id;
    verdict.sha256 = sha256;
  }

  // Gate 2: quote accuracy (only if a quote was attributed).
  if (candidate.quotedText) {
    const fullText = await readCacheText(verdict.sourceId!, opts.supabase);
    verdict.gate2_quote_accuracy = quoteAppearsIn(candidate.quotedText, fullText);
    if (!verdict.gate2_quote_accuracy) {
      verdict.notes.push(
        `Quoted text does not appear verbatim in the cited source. Strike or rephrase.`,
      );
    }
  }

  // Gate 3: currency. Only run for cache hits without recent currency check;
  // for fresh adds, run now.
  if (verdict.sourceId) {
    const opinionId = await readOpinionIdFromSource(verdict.sourceId, opts.supabase);
    if (opinionId) {
      const currency = await checkCurrency(opinionId, opts.courtListenerToken);
      verdict.gate3_currency = currency.signal;
      if (currency.signal === 'red') {
        verdict.notes.push(
          `Negative treatment detected: ${currency.negativeMentions.join(' | ')}`,
        );
      }
    }
  }

  // Gate 4: jurisdiction fit.
  verdict.gate4_jurisdiction_fit = assessJurisdictionFit(
    await readSourceRow(verdict.sourceId!, opts.supabase),
    opts.matter,
  );

  // Compose final status.
  if (verdict.gate3_currency === 'red') {
    verdict.status = 'vetoed';
  } else if (
    candidate.quotedText &&
    verdict.gate2_quote_accuracy === false
  ) {
    verdict.status = 'vetoed';
  } else if (
    verdict.gate3_currency === 'yellow' ||
    verdict.gate4_jurisdiction_fit !== 'mandatory'
  ) {
    verdict.status = 'conditional';
  } else {
    verdict.status = 'verified';
  }

  await persistVerdict(verdict, opts.supabase);
  return verdict;
}

/**
 * Verify every citation in a draft text in one shot. Uses CourtListener's
 * block-of-text mode for Gate 1, then spreads out to per-citation checks
 * for gates 2-4.
 */
export async function verifyDraft(
  draftText: string,
  opts: VerifyOptions,
): Promise<{
  verdicts: GateVerdict[];
  hasVetoes: boolean;
  hasConditional: boolean;
}> {
  const hits = await citationLookup(draftText, opts.courtListenerToken);
  // Convert hits + the original draft into candidate objects.
  const candidates: CitationCandidate[] = hits.map((h) => ({
    citation: h.citation,
  }));
  const verdicts: GateVerdict[] = [];
  for (const c of candidates) {
    verdicts.push(await verifyCitation(c, opts));
  }
  return {
    verdicts,
    hasVetoes: verdicts.some((v) => v.status === 'vetoed'),
    hasConditional: verdicts.some((v) => v.status === 'conditional'),
  };
}

// ───── helpers ─────

function quoteAppearsIn(quote: string, fullText: string): boolean {
  // Normalize whitespace/quotes; case-sensitive comparison.
  const normalize = (s: string) =>
    s
      .replace(/[\u2018\u2019]/g, "'")
      .replace(/[\u201C\u201D]/g, '"')
      .replace(/\s+/g, ' ')
      .trim();
  return normalize(fullText).includes(normalize(quote));
}

function assessJurisdictionFit(
  source: { jurisdiction: string } | null,
  matter: MatterContext,
): 'mandatory' | 'persuasive' | 'off-point' | null {
  if (!source) return null;
  // Crude first pass; replace with a real jurisdiction graph in v2.
  if (source.jurisdiction === 'scotus' || source.jurisdiction === 'us-supreme') {
    return 'mandatory'; // SCOTUS binds everyone on federal questions.
  }
  if (matter.forum.includes(source.jurisdiction)) return 'mandatory';
  return 'persuasive';
}

async function readCache(
  citation: string,
  supabase: SupabaseClient,
): Promise<{ id: string; sha256: string } | null> {
  const { data } = await supabase
    .from('sources')
    .select('id, sha256')
    .eq('citation_bluebook', citation)
    .maybeSingle();
  return data ?? null;
}

async function readCacheText(sourceId: string, supabase: SupabaseClient): Promise<string> {
  const { data } = await supabase
    .from('sources')
    .select('full_text')
    .eq('id', sourceId)
    .single();
  return data?.full_text ?? '';
}

async function readSourceRow(sourceId: string, supabase: SupabaseClient) {
  const { data } = await supabase.from('sources').select('*').eq('id', sourceId).single();
  return data;
}

async function readOpinionIdFromSource(
  sourceId: string,
  supabase: SupabaseClient,
): Promise<number | null> {
  const { data } = await supabase
    .from('sources')
    .select('cl_opinion_id')
    .eq('id', sourceId)
    .single();
  return data?.cl_opinion_id ?? null;
}

async function writeCache(row: any, supabase: SupabaseClient) {
  const { data, error } = await supabase.from('sources').insert(row).select().single();
  if (error) throw error;
  return data;
}

async function persistVerdict(verdict: GateVerdict, supabase: SupabaseClient) {
  await supabase.from('citations').insert({
    source_id: verdict.sourceId,
    gate_existence: verdict.gate1_existence,
    gate_quote_accuracy: verdict.gate2_quote_accuracy ?? false,
    gate_currency: verdict.gate3_currency === 'green',
    gate_jurisdiction_fit: verdict.gate4_jurisdiction_fit === 'mandatory',
    status: verdict.status,
    verifier: 'skeptic',
    verified_at: new Date().toISOString(),
  });
}
