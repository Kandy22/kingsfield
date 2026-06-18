/**
 * IP Renewal Watcher — Orchestrator.
 *
 * Runs the three-tier pipeline for IP portfolio renewal tracking:
 *   reader → deadline-mapper → reporter
 *
 * Can be called from:
 *   - POST /api/ip/renewal/sweep  (portfolio-wide sweep, cron)
 *   - POST /api/projects/:id/ip/renewal/check  (per-project manual trigger)
 *
 * Security model mirrors the docket watcher:
 *   - Reader: read-only Supabase, no LLM, no external APIs.
 *   - Mapper: LLM only, schema-validated input, no external calls, no DB writes.
 *   - Reporter: write-only (ip_renewal_checks insert), no raw user data to LLM.
 */

import type { SupabaseClient } from '@supabase/supabase-js';
import { runIpReader } from './reader.js';
import { runIpDeadlineMapper } from './deadline-mapper.js';
import { runIpReporter, type ReporterOutput } from './reporter.js';

export interface IpRenewalWatcherDeps {
  model: string;
  supabase: SupabaseClient;
  resendKey?: string;
  notifyEmail?: string;
  /** How many days ahead to scan (default 90). */
  windowDays?: number;
  /** Limit sweep to a specific project UUID. Omit for portfolio-wide. */
  projectId?: string;
}

export async function runIpRenewalWatcher(
  deps: IpRenewalWatcherDeps,
): Promise<ReporterOutput> {
  // Tier 1: read assets with upcoming deadlines.
  const readerOutput = await runIpReader(deps.supabase, {
    windowDays: deps.windowDays,
    projectId: deps.projectId,
  });

  // Tier 2: map assets to prioritized actions (LLM, no external calls).
  const mapperOutput = await runIpDeadlineMapper(
    readerOutput.due_within_window,
    deps.model,
  );

  // Tier 3: write report, send email if warranted.
  const result = await runIpReporter(readerOutput, mapperOutput, deps.supabase, {
    notifyEmail: deps.notifyEmail,
    resendKey: deps.resendKey,
  });

  return result;
}
