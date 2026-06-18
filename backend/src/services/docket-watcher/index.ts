/**
 * Docket Watcher — Orchestrator.
 *
 * Runs the three-tier pipeline for one matter at a time:
 *   reader → deadline-mapper → reporter
 *
 * Can be called from:
 *   - The POST /api/projects/:id/docket/watch route (manual trigger)
 *   - A cron job that sweeps all active matters (see runPortfolioSweep)
 *
 * Security: the orchestrator holds no write access and reads no raw filings.
 * It passes the reader's schema-validated JSON to the mapper, and both
 * outputs to the reporter. Raw filing text never reaches the LLM or the DB
 * write path directly — the reader sanitises before passing on.
 */

import type { SupabaseClient } from '@supabase/supabase-js';
import { runReader, type ReaderInput } from './reader.js';
import { runDeadlineMapper } from './deadline-mapper.js';
import { runReporter, type ReporterOutput } from './reporter.js';

export interface DocketWatcherInput {
  /** Project/matter ID (UUID). */
  matter_id: string;
  matter_name: string;
  /** CourtListener numeric docket ID. Preferred. */
  docket_id?: number;
  /** Fallback: case number string, e.g. "2:26-cv-00315". */
  docket_number?: string;
  /** CourtListener court code, e.g. "cand". Required if docket_id absent. */
  court?: string;
  /** Only fetch filings on or after this ISO date. Defaults to 7 days ago. */
  since?: string;
  /** Email address to notify. If omitted, no email is sent. */
  notify_email?: string;
}

export interface DocketWatcherDeps {
  model: string;
  supabase: SupabaseClient;
  courtListenerToken: string;
  resendKey?: string;
}

function defaultSince(): string {
  const d = new Date();
  d.setDate(d.getDate() - 7);
  return d.toISOString().slice(0, 10);
}

export async function runDocketWatcher(
  input: DocketWatcherInput,
  deps: DocketWatcherDeps,
): Promise<ReporterOutput> {
  const since = input.since ?? defaultSince();

  const readerInput: ReaderInput = {
    matter_id: input.matter_id,
    docket_id: input.docket_id,
    docket_number: input.docket_number,
    court: input.court,
    since,
  };

  // Tier 1: read docket entries from CourtListener.
  const readerOutput = await runReader(readerInput, deps.courtListenerToken);

  // Tier 2: map filings to candidate deadlines (LLM, no external calls).
  const mapperOutput = await runDeadlineMapper(readerOutput, deps.model);

  // Tier 3: write report to Supabase, send email if warranted.
  const result = await runReporter(
    {
      matter_id: input.matter_id,
      matter_name: input.matter_name,
      reader: readerOutput,
      mapper: mapperOutput,
    },
    deps.supabase,
    {
      notifyEmail: input.notify_email,
      resendKey: deps.resendKey,
    },
  );

  return result;
}

/**
 * Sweep all active matters in the portfolio that have a docket_id configured.
 * Intended to be called by a cron job or a scheduled API route.
 *
 * Schedule:
 *   - Weekly for most matters.
 *   - Daily for anything with a hearing in 14 days or risk: critical.
 *   (The calling scheduler is responsible for determining frequency.)
 */
export async function runPortfolioSweep(
  deps: DocketWatcherDeps & { defaultNotifyEmail?: string },
): Promise<{ matter_id: string; status: 'ok' | 'error'; detail?: string }[]> {
  // Fetch all projects that have docket tracking configured.
  const { data: matters, error } = await deps.supabase
    .from('projects')
    .select('id, name, docket_id, docket_number, court_code, notify_email')
    .or('docket_id.not.is.null,docket_number.not.is.null');

  if (error) {
    console.error('[docket-watcher] Portfolio fetch failed:', error);
    return [];
  }

  const results: { matter_id: string; status: 'ok' | 'error'; detail?: string }[] = [];

  for (const matter of matters ?? []) {
    try {
      await runDocketWatcher(
        {
          matter_id: matter.id,
          matter_name: matter.name,
          docket_id: matter.docket_id ?? undefined,
          docket_number: matter.docket_number ?? undefined,
          court: matter.court_code ?? undefined,
          notify_email: matter.notify_email ?? deps.defaultNotifyEmail,
        },
        deps,
      );
      results.push({ matter_id: matter.id, status: 'ok' });
    } catch (err: any) {
      console.error(`[docket-watcher] Matter ${matter.id} failed:`, err);
      results.push({ matter_id: matter.id, status: 'error', detail: String(err?.message ?? err) });
    }
  }

  return results;
}
