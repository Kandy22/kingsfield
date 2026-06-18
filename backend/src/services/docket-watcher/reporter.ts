/**
 * Docket Watcher — Tier 3: Reporter.
 *
 * The ONLY tier with write access. Receives structured JSON from the reader
 * and deadline-mapper. NEVER sees raw filing text. NEVER calls CourtListener.
 *
 * Writes to:
 *   1. Supabase — docket_checks table (report_md + deadlines_json).
 *   2. Resend email — if new filings exist or any deadline is within 14 days.
 *
 * Injection defences (from tracker-writer.yaml):
 *   Markdown: formula-char prefix, pipe escaping, HTML entity escaping,
 *             URLs rendered as inert backtick text — never as clickable links.
 *   The reporter never re-derives or re-interprets filing content.
 */

import type { SupabaseClient } from '@supabase/supabase-js';
import type { ReaderOutput, FilingRecord } from './reader.js';
import type { MapperOutput, DeadlineRecord } from './deadline-mapper.js';

export interface ReporterInput {
  matter_id: string;
  matter_name: string;
  reader: ReaderOutput;
  mapper: MapperOutput;
}

export interface ReporterOutput {
  report_md: string;
  deadlines: DeadlineRecord[];
  new_filings_count: number;
  critical_deadline_count: number;
  emailed: boolean;
}

// ── Markdown injection defence ─────────────────────────────────────────────

/** Sanitise an input-derived string for safe inclusion in a Markdown document. */
function mdSafe(s: string): string {
  let out = String(s ?? '');
  if (/^[=+\-@\t\r]/.test(out)) out = `'${out}`;
  out = out.replace(/\|/g, '\\|');
  out = out.replace(/</g, '&lt;').replace(/>/g, '&gt;');
  return out;
}

/** Render a URL as inert backtick text. Never as a clickable link. */
function inertUrl(url: string): string {
  if (!url) return '—';
  return `\`${url.replace(/`/g, '')}\``;
}

// ── Report builder ─────────────────────────────────────────────────────────

const VERIFICATION_FOOTER = `
---
This report was produced by an automated agent. Computed deadlines are leads,
not calendar entries. Court deadline rules vary by jurisdiction, court, judge,
and local rule, and can be modified by standing order or case management order.
Filing classifications are heuristic — a misclassified filing produces a wrong
deadline rule. Missing a court deadline has malpractice consequences. A licensed
attorney reads the filing, verifies every computed deadline against the
controlling local rule and any case-specific orders, and dockets the date. This
agent is upstream of that decision, not a substitute for it.
`.trim();

function buildReport(input: ReporterInput, today: string): string {
  const { matter_name, reader, mapper } = input;
  const sections: string[] = [];

  sections.push(`# Docket Report — ${mdSafe(matter_name)}`);
  sections.push(`*Generated ${today} · Court: ${mdSafe(reader.court)} · Docket: ${reader.docket_id}*`);

  if (reader.error) {
    sections.push(`\n> ⚠️ **Reader error:** ${mdSafe(reader.error)}\n`);
  }

  // ── New filings ────────────────────────────────────────────────────────
  sections.push(`\n## New filings (since last check)\n`);
  if (!reader.filings.length) {
    sections.push('*No new filings.*');
  } else {
    const rows = reader.filings.map((f: FilingRecord) =>
      `| ${mdSafe(f.filing_date)} | ${mdSafe(f.filing_type)} | ${mdSafe(f.title)} | ${inertUrl(f.doc_url)} |`
    );
    sections.push('| Date | Type | Description | Doc |');
    sections.push('|------|------|-------------|-----|');
    sections.push(...rows);
  }

  // ── Deadlines ─────────────────────────────────────────────────────────
  const high = mapper.deadlines.filter(
    (d) => d.confidence === 'high' && !d.needs_verification,
  );
  const needsVerify = mapper.deadlines.filter((d) => d.needs_verification);
  const lowConf = mapper.deadlines.filter(
    (d) => d.confidence === 'low',
  );
  const upcoming30 = mapper.deadlines.filter(
    (d) => d.days_remaining >= 0 && d.days_remaining <= 30,
  );

  sections.push(`\n## Upcoming deadlines (next 30 days)\n`);
  if (!upcoming30.length) {
    sections.push('*No deadlines computed within the next 30 days.*');
  } else {
    sections.push('| Days | Date | Type | Rule | Confidence | ⚠ Verify? |');
    sections.push('|------|------|------|------|------------|-----------|');
    for (const d of upcoming30.sort((a, b) => a.days_remaining - b.days_remaining)) {
      const verifyFlag = d.needs_verification ? '**YES — verify before calendaring**' : 'No';
      sections.push(
        `| ${d.days_remaining} | ${mdSafe(d.computed_date)} | ${mdSafe(d.deadline_type)} | ${mdSafe(d.rule_basis)} | ${d.confidence} | ${verifyFlag} |`,
      );
    }
  }

  if (needsVerify.length) {
    sections.push(`\n### ⚠️ All deadlines requiring verification (${needsVerify.length})\n`);
    sections.push(
      '> **These deadlines must be verified against the controlling local rule, standing order,**\n> **and case management order before being calendared.**\n',
    );
    sections.push('| Date | Type | Rule | Confidence |');
    sections.push('|------|------|------|------------|');
    for (const d of needsVerify) {
      sections.push(
        `| ${mdSafe(d.computed_date)} | ${mdSafe(d.deadline_type)} | ${mdSafe(d.rule_basis)} | ${d.confidence} |`,
      );
    }
  }

  if (lowConf.length) {
    sections.push(`\n### 🔴 Low-confidence entries (${lowConf.length}) — verify rule basis\n`);
    for (const d of lowConf) {
      sections.push(`- **${mdSafe(d.deadline_type)}**: ${mdSafe(d.computed_date)} — ${mdSafe(d.rule_basis)}`);
    }
  }

  sections.push(`\n${VERIFICATION_FOOTER}`);

  return sections.join('\n');
}

// ── Email via Resend ───────────────────────────────────────────────────────

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
        from: 'Kingsfield Docket Watcher <docket@kingsfield.app>',
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

export async function runReporter(
  input: ReporterInput,
  supabase: SupabaseClient,
  opts: {
    notifyEmail?: string;
    resendKey?: string;
  } = {},
): Promise<ReporterOutput> {
  const today = new Date().toISOString().slice(0, 10);
  const report_md = buildReport(input, today);

  const newFilingsCount = input.reader.filings.length;
  const criticalDeadlineCount = input.mapper.deadlines.filter(
    (d) => d.days_remaining >= 0 && d.days_remaining <= 14,
  ).length;

  // Write to Supabase docket_checks table.
  const { error: dbErr } = await supabase.from('docket_checks').insert({
    project_id: input.matter_id,
    as_of: input.reader.as_of,
    docket_id: input.reader.docket_id,
    court: input.reader.court,
    filings_json: input.reader.filings,
    deadlines_json: input.mapper.deadlines,
    report_md,
    new_filings_count: newFilingsCount,
    critical_deadline_count: criticalDeadlineCount,
  });

  if (dbErr) {
    console.error('[docket-reporter] DB insert failed:', dbErr);
  }

  // Update the project's last_docket_check timestamp.
  await supabase
    .from('projects')
    .update({ last_docket_check: today })
    .eq('id', input.matter_id);

  // Email if there are new filings OR any deadline within 14 days.
  let emailed = false;
  if (opts.notifyEmail && opts.resendKey && (newFilingsCount > 0 || criticalDeadlineCount > 0)) {
    const subject = `[Kingsfield] Docket update — ${input.matter_name} (${newFilingsCount} new filing${newFilingsCount !== 1 ? 's' : ''}, ${criticalDeadlineCount} deadline${criticalDeadlineCount !== 1 ? 's' : ''} in 14 days)`;
    emailed = await sendEmail(opts.notifyEmail, subject, report_md, opts.resendKey);
  }

  return {
    report_md,
    deadlines: input.mapper.deadlines,
    new_filings_count: newFilingsCount,
    critical_deadline_count: criticalDeadlineCount,
    emailed,
  };
}
