/**
 * IP Renewal Watcher — Tier 2: Deadline Mapper.
 *
 * Receives the reader's schema-validated snapshots. No external API calls.
 * No database writes. One LLM call — categorizes urgency, maps asset types
 * to their specific renewal regime (§8 declarations, maintenance fees, Madrid
 * renewals, domain renewals), and produces prioritized action items.
 *
 * Key rules:
 * - needs_verification: true on anything where the deadline calculation
 *   requires attorney confirmation (state rules, foreign law, CMO modifications).
 * - US trademark: §8 declarations (5-6yr window), §15 incontestability (optional),
 *   §9 renewal (10yr cycle). §8 failure = cancellation.
 * - US patent: maintenance fees at 3.5, 7.5, 11.5 years post-grant.
 *   Large entity vs. small entity vs. micro entity — fee depends on status.
 *   6-month grace period with surcharge; after that, irrecoverable abandonment.
 * - Madrid Protocol: renewal every 10 years from international registration date.
 *   Dependent on basic mark for first 5 years — central attack risk.
 * - Domain: renewal varies by registrar; ICANN 60-day lock after transfer.
 * - Returns schema-validated JSON only.
 */

import { completeText } from '../../lib/llm/index.js';
import type { AssetSnapshot } from './reader.js';

export interface PrioritizedAction {
  asset_id: string;
  asset_title: string;
  asset_type: string;
  deadline_date: string;
  days_remaining: number;
  action_required: string;
  regime: string;           // e.g. "USPTO §8 Declaration", "Patent Maintenance Fee Year 7.5"
  urgency: 'critical' | 'high' | 'medium' | 'low';
  grace_period_available: boolean;
  grace_period_note: string;
  needs_verification: boolean;
  verification_reason: string;
}

export interface MapperOutput {
  actions: PrioritizedAction[];
  critical_count: number;
  high_count: number;
  medium_count: number;
  low_count: number;
}

const MAPPER_SYSTEM_PROMPT = `
You are an IP renewal deadline analysis engine for litigation support software.
You receive a list of IP assets with upcoming deadlines and produce prioritized
action items with regime-specific guidance.

RENEWAL REGIMES — apply these rules:

TRADEMARK (US):
- Section 8 Declaration: filed between 5th and 6th anniversary of registration,
  and every 10 years thereafter (combined §8/§9). Late filing allowed up to
  6 months after deadline with surcharge. Failure = cancellation by USPTO.
- Section 15 Incontestability: optional, filed after 5 consecutive years of use.
- Section 9 Renewal: every 10 years from registration date.
- Mark the §8 window as critical if <90 days to 6th anniversary with no §8 filed.

TRADEMARK (Madrid/International):
- Renewal every 10 years from international registration date.
- Dependent on basic mark for first 5 years (central attack risk).
- WIPO handles renewals; must be filed 6 months before expiry (+ 6-month grace).

PATENT (US):
- Maintenance fees due at 3.5, 7.5, and 11.5 years after grant date.
- 6-month grace period with surcharge (USPTO). After grace = irrecoverable lapse.
- Fee amounts differ by entity status: large / small / micro.
- Flag entity status as needs_verification: true — attorneys must confirm status.

PATENT (EP/PCT):
- Annual annuities (year 2+). Each designated state has its own rules.
- Always needs_verification: true for foreign patents.

COPYRIGHT:
- US copyright: no renewal required for works after 1977.
- Pre-1978 works may require renewal — flag needs_verification: true.

DOMAIN:
- Varies by registrar and TLD. ICANN 60-day lock after transfer.
- Flag any domain within 30 days as critical.

URGENCY LEVELS:
- critical: ≤14 days, or past deadline still in grace period
- high:     15-30 days
- medium:   31-60 days
- low:      61-90 days

Hard rules:
- needs_verification: true for all foreign IP, all pre-1978 copyright, all patent
  entity status questions, and all Madrid/PCT matters.
- Return ONLY valid JSON. No preamble, no markdown fences.

Output schema:
{
  "actions": [
    {
      "asset_id": "string",
      "asset_title": "string",
      "asset_type": "string",
      "deadline_date": "YYYY-MM-DD",
      "days_remaining": number,
      "action_required": "string (max 200 chars)",
      "regime": "string (max 120 chars)",
      "urgency": "critical|high|medium|low",
      "grace_period_available": true|false,
      "grace_period_note": "string",
      "needs_verification": true|false,
      "verification_reason": "string"
    }
  ],
  "critical_count": number,
  "high_count": number,
  "medium_count": number,
  "low_count": number
}
`.trim();

function stripFences(s: string): string {
  return s.replace(/^```(?:json)?\s*/i, '').replace(/\s*```\s*$/i, '').trim();
}

function recoverTruncatedJson(s: string): string {
  let t = s.replace(/,?\s*"[^"]*$/, '').replace(/,(\s*[}\]])/, '$1');
  const stack: string[] = [];
  let inStr = false, esc = false;
  for (const ch of t) {
    if (esc) { esc = false; continue; }
    if (ch === '\\') { esc = true; continue; }
    if (ch === '"') { inStr = !inStr; continue; }
    if (inStr) continue;
    if (ch === '{') stack.push('}');
    else if (ch === '[') stack.push(']');
    else if (ch === '}' || ch === ']') stack.pop();
  }
  return t + stack.reverse().join('');
}

export async function runIpDeadlineMapper(
  snapshots: AssetSnapshot[],
  model: string,
): Promise<MapperOutput> {
  if (!snapshots.length) {
    return { actions: [], critical_count: 0, high_count: 0, medium_count: 0, low_count: 0 };
  }

  const today = new Date().toISOString().slice(0, 10);

  // Pass only schema-validated, safe fields — no free-text user notes.
  const safeSnapshots = snapshots.map((s) => ({
    asset_id: s.id,
    asset_type: s.asset_type,
    title: s.title,
    registration_number: s.registration_number,
    jurisdiction: s.jurisdiction,
    next_deadline_date: s.next_deadline_date,
    next_deadline_type: s.next_deadline_type,
    days_remaining: s.days_remaining,
  }));

  const raw = await completeText({
    model,
    systemPrompt: MAPPER_SYSTEM_PROMPT,
    user: `
TODAY: ${today}
ASSETS WITH UPCOMING DEADLINES (schema-validated JSON):
${JSON.stringify(safeSnapshots, null, 2)}

Produce the prioritized action list. Return only the JSON object.
    `.trim(),
    maxTokens: 4096,
  });

  const json = stripFences(raw.trim());
  let parsed: any = {};
  try {
    parsed = JSON.parse(json);
  } catch {
    try {
      parsed = JSON.parse(recoverTruncatedJson(json));
    } catch {
      console.error('[ip-deadline-mapper] JSON parse failed');
    }
  }

  const actions: PrioritizedAction[] = (parsed.actions ?? []).map((a: any) => ({
    asset_id: String(a.asset_id ?? ''),
    asset_title: String(a.asset_title ?? '').slice(0, 200),
    asset_type: String(a.asset_type ?? ''),
    deadline_date: String(a.deadline_date ?? ''),
    days_remaining: typeof a.days_remaining === 'number' ? a.days_remaining : 0,
    action_required: String(a.action_required ?? '').slice(0, 200),
    regime: String(a.regime ?? '').slice(0, 120),
    urgency: ['critical', 'high', 'medium', 'low'].includes(a.urgency) ? a.urgency : 'medium',
    grace_period_available: a.grace_period_available === true,
    grace_period_note: String(a.grace_period_note ?? ''),
    needs_verification: a.needs_verification !== false,
    verification_reason: String(a.verification_reason ?? ''),
  }));

  return {
    actions,
    critical_count: typeof parsed.critical_count === 'number'
      ? parsed.critical_count
      : actions.filter((a) => a.urgency === 'critical').length,
    high_count: typeof parsed.high_count === 'number'
      ? parsed.high_count
      : actions.filter((a) => a.urgency === 'high').length,
    medium_count: typeof parsed.medium_count === 'number'
      ? parsed.medium_count
      : actions.filter((a) => a.urgency === 'medium').length,
    low_count: typeof parsed.low_count === 'number'
      ? parsed.low_count
      : actions.filter((a) => a.urgency === 'low').length,
  };
}
