/**
 * IP Renewal Watcher — Tier 3: Reporter.
 *
 * The ONLY tier with write access. Receives structured JSON from the reader
 * and deadline-mapper. NEVER sees raw asset notes or user free text (only
 * schema-validated fields). NEVER calls external APIs.
 *
 * Writes to:
 *   1. Supabase — ip_renewal_checks table.
 *   2. Resend email — if any asset has a deadline within 30 days.
 *
 * Same Markdown injection defenses as docket-watcher reporter:
 *   formula-char prefix, pipe escaping, HTML entities, inert URLs.
 */

import type { SupabaseClient } from '@supabase/supabase-js';
import type { ReaderOutput } from './reader.js';
import type { MapperOutput, PrioritizedAction } from './deadline-mapper.js';
import { mdSafe } from './reader.js';

export interface ReporterOutput {
  report_md: string;
  critical_count: number;
  high_count: number;
  assets_checked: number;
  emailed: boolean;
}

// ── Verification footer ───────────────────────────────────────────────────

const VERIFICATION_FOOTER = `
---
This report was produced by an automated agent. Renewal deadlines are computed
from data stored in the Kingsfield IP portfolio database. Deadline rules vary
by IP type, jurisdiction, entity status, and applicable treaties. The grace
periods noted are general — confirm the controlling rule and current fee
schedule with a licensed IP attorney or registered patent/trademark agent before
taking action. Missing a maintenance, renewal, or declaration deadline can
result in irrecoverable loss of IP rights. This agent is upstream of that
decision, not a substitute for it.
`.trim();

// ── Report builder ────────────────────────────────────────────────────────

function buildReport(reader: ReaderOutput, mapper: MapperOutput, today: string): string {
  const sections: string[] = [];

  sections.push(`# IP Portfolio Renewal Report`);
  sections.push(
    `*Generated ${today} · ${reader.total_assets} active assets · ` +
    `${reader.due_within_window.length} with deadlines in the next 90 days*`,
  );

  if (reader.error) {
    sections.push(`\n> ⚠️ **Reader error:** ${mdSafe(reader.error)}\n`);
  }

  if (!mapper.actions.length) {
    sections.push('\n*No deadlines due within the next 90 days.*');
    sections.push(`\n${VERIFICATION_FOOTER}`);
    return sections.join('\n');
  }

  // ── Critical / High ────────────────────────────────────────────────────
  const critical = mapper.actions.filter((a) => a.urgency === 'critical');
  const high = mapper.actions.filter((a) => a.urgency === 'high');

  if (critical.length) {
    sections.push(`\n## 🔴 CRITICAL — Action required within 14 days (${critical.length})\n`);
    sections.push(
      '> **These deadlines require immediate attorney attention. ' +
      'Failure to act may result in irrecoverable loss of IP rights.**\n',
    );
    sections.push(actionTable(critical));
  }

  if (high.length) {
    sections.push(`\n## 🟠 High Priority — Due within 30 days (${high.length})\n`);
    sections.push(actionTable(high));
  }

  // ── Medium / Low ──────────────────────────────────────────────────────
  const medium = mapper.actions.filter((a) => a.urgency === 'medium');
  const low = mapper.actions.filter((a) => a.urgency === 'low');

  if (medium.length || low.length) {
    sections.push(`\n## 📋 Upcoming (31–90 days)\n`);
    sections.push(actionTable([...medium, ...low]));
  }

  // ── Verification required ──────────────────────────────────────────────
  const needsVerify = mapper.actions.filter((a) => a.needs_verification);
  if (needsVerify.length) {
    sections.push(
      `\n## ⚠️ All items requiring attorney verification (${needsVerify.length})\n`,
    );
    sections.push(
      '> **Verify deadline calculation, entity status, and applicable rules before taking action.**\n',
    );
    for (const a of needsVerify) {
      sections.push(
        `- **${mdSafe(a.asset_title)}** (${mdSafe(a.asset_type)}): ` +
        `${mdSafe(a.deadline_date)} — ${mdSafe(a.verification_reason)}`,
      );
    }
  }

  sections.push(`\n${VERIFICATION_FOOTER}`);
  return sections.join('\n');
}

function actionTable(actions: PrioritizedAction[]): string {
  const lines: string[] = [
    '| Days | Date | Asset | Type | Action | Regime | Grace? | ⚠ Verify? |',
    '|------|------|-------|------|--------|--------|--------|-----------|',
  ];
  for (const a of actions.sort((x, y) => x.days_remaining - y.days_remaining)) {
    const verifyFlag = a.needs_verification ? '**YES**' : 'No';
    const grace = a.grace_period_available ? `Yes — ${mdSafe(a.grace_period_note)}` : 'No';
    lines.push(
      `| ${a.days_remaining} | ${mdSafe(a.deadline_date)} | ${mdSafe(a.asset_title)} | ` +
      `${mdSafe(a.asset_type)} | ${mdSafe(a.action_required)} | ` +
      `${mdSafe(a.regime)} | ${grace} | ${verifyFlag} |`,
    );
  }
  return lines.join('\n');
}

// ── Email via Resend ──────────────────────────────────────────────────────

async function sendEmail(
  to: string,
  subject: string,
  bodyMd: string,
  resendKey: string,
): Promise<boolean> {
  try {
    const res = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${resendKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        from: 'Kingsfield IP Watcher <ip@kingsfield.app>',
        to: [to],
        subject,
        text: bodyMd,
      }),
    });
    return res.ok;
  } catch {
    return false;
  }
}

// ── Main ──────────────────────────────────────────────────────────────────

export async function runIpReporter(
  reader: ReaderOutput,
  mapper: MapperOutput,
  supabase: SupabaseClient,
  opts: {
    notifyEmail?: string;
    resendKey?: string;
  } = {},
): Promise<ReporterOutput> {
  const today = new Date().toISOString().slice(0, 10);
  const report_md = buildReport(reader, mapper, today);

  // Write to ip_renewal_checks.
  const { error: dbErr } = await supabase.from('ip_renewal_checks').insert({
    as_of: reader.as_of,
    assets_checked: reader.total_assets,
    deadlines_within_90: reader.due_within_window.length,
    deadlines_within_30: mapper.actions.filter(
      (a) => a.days_remaining >= 0 && a.days_remaining <= 30,
    ).length,
    critical_count: mapper.critical_count,
    report_md,
    assets_json: reader.due_within_window,
  });

  if (dbErr) {
    console.error('[ip-reporter] DB insert failed:', dbErr);
  }

  // Email if any critical or high-urgency deadline.
  let emailed = false;
  const shouldEmail = mapper.critical_count > 0 || mapper.high_count > 0;

  if (opts.notifyEmail && opts.resendKey && shouldEmail) {
    const subject =
      `[Kingsfield IP] Renewal alert — ` +
      `${mapper.critical_count} critical, ${mapper.high_count} high-priority deadline` +
      `${mapper.high_count !== 1 ? 's' : ''}`;
    emailed = await sendEmail(opts.notifyEmail, subject, report_md, opts.resendKey);
  }

  return {
    report_md,
    critical_count: mapper.critical_count,
    high_count: mapper.high_count,
    assets_checked: reader.total_assets,
    emailed,
  };
}
