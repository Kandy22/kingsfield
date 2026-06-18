/**
 * IP Renewal Watcher — Tier 1: Reader.
 *
 * The ONLY tier with read access to the ip_assets table.
 * Reads assets, computes days-to-deadline, and returns a schema-validated
 * snapshot for the deadline-mapper to analyze.
 *
 * Never calls external APIs (no USPTO, WIPO, ICANN lookups — asset data
 * is assumed to be pre-loaded into ip_assets by the user or a future
 * ingestion pipeline).
 * Never writes to the database.
 * Never calls an LLM.
 */

import type { SupabaseClient } from '@supabase/supabase-js';

export interface AssetSnapshot {
  id: string;
  project_id: string;
  asset_type: string;
  title: string;
  registration_number: string | null;
  application_number: string | null;
  jurisdiction: string | null;
  status: string;
  next_deadline_date: string | null;   // YYYY-MM-DD
  next_deadline_type: string | null;
  days_remaining: number | null;
  owner_name: string | null;
  notify_email: string | null;
}

export interface ReaderOutput {
  as_of: string;
  total_assets: number;
  snapshots: AssetSnapshot[];
  /** assets with next_deadline_date within windowDays */
  due_within_window: AssetSnapshot[];
  error?: string;
}

function daysUntil(dateStr: string): number {
  const target = new Date(dateStr);
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  return Math.round((target.getTime() - now.getTime()) / 86_400_000);
}

/** Sanitise a string from the database before including in a Markdown report. */
export function mdSafe(s: string | null | undefined): string {
  let out = String(s ?? '');
  if (/^[=+\-@\t\r]/.test(out)) out = `'${out}`;
  out = out.replace(/\|/g, '\\|');
  out = out.replace(/</g, '&lt;').replace(/>/g, '&gt;');
  return out;
}

export async function runIpReader(
  supabase: SupabaseClient,
  opts: {
    /** Only fetch assets with deadline within this many days (default 90). */
    windowDays?: number;
    /** Limit to a specific project. Omit for portfolio-wide. */
    projectId?: string;
  } = {},
): Promise<ReaderOutput> {
  const windowDays = opts.windowDays ?? 90;
  const as_of = new Date().toISOString();

  try {
    const today = new Date().toISOString().slice(0, 10);
    const windowEnd = new Date();
    windowEnd.setDate(windowEnd.getDate() + windowDays);
    const windowEndStr = windowEnd.toISOString().slice(0, 10);

    let query = supabase
      .from('ip_assets')
      .select(
        'id, project_id, asset_type, title, registration_number, application_number, ' +
        'jurisdiction, status, next_deadline_date, next_deadline_type, owner_name, notify_email',
      )
      .eq('status', 'active')
      .not('next_deadline_date', 'is', null)
      .lte('next_deadline_date', windowEndStr)
      .gte('next_deadline_date', today)
      .order('next_deadline_date', { ascending: true });

    if (opts.projectId) {
      query = query.eq('project_id', opts.projectId);
    }

    const { data: dueAssets, error: dueErr } = await query;
    if (dueErr) {
      return { as_of, total_assets: 0, snapshots: [], due_within_window: [], error: dueErr.message };
    }

    // Also fetch total active asset count for the report header.
    let countQuery = supabase
      .from('ip_assets')
      .select('id', { count: 'exact', head: true })
      .eq('status', 'active');
    if (opts.projectId) {
      countQuery = countQuery.eq('project_id', opts.projectId);
    }
    const { count } = await countQuery;

    const snapshots: AssetSnapshot[] = (dueAssets ?? []).map((a: any) => ({
      id: a.id,
      project_id: a.project_id,
      asset_type: String(a.asset_type ?? ''),
      title: String(a.title ?? '').slice(0, 200),
      registration_number: a.registration_number ? String(a.registration_number).slice(0, 50) : null,
      application_number: a.application_number ? String(a.application_number).slice(0, 50) : null,
      jurisdiction: a.jurisdiction ? String(a.jurisdiction).slice(0, 50) : null,
      status: String(a.status ?? 'active'),
      next_deadline_date: a.next_deadline_date ?? null,
      next_deadline_type: a.next_deadline_type ? String(a.next_deadline_type).slice(0, 120) : null,
      days_remaining: a.next_deadline_date ? daysUntil(a.next_deadline_date) : null,
      owner_name: a.owner_name ? String(a.owner_name).slice(0, 100) : null,
      notify_email: a.notify_email ? String(a.notify_email).slice(0, 200) : null,
    }));

    return {
      as_of,
      total_assets: count ?? 0,
      snapshots,
      due_within_window: snapshots,
    };
  } catch (err: any) {
    return {
      as_of,
      total_assets: 0,
      snapshots: [],
      due_within_window: [],
      error: String(err?.message ?? err),
    };
  }
}
