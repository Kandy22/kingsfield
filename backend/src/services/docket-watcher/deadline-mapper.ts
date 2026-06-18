/**
 * Docket Watcher — Tier 2: Deadline Mapper.
 *
 * Receives the reader's schema-validated JSON. Never calls CourtListener.
 * Never writes to the database. One LLM call — maps filing types to candidate
 * deadline rules from FRCP / local rule tables.
 *
 * Key rules (from deadline-mapper.yaml in anthropics/claude-for-legal):
 * - `needs_verification: true` on EVERY deadline unless all three conditions:
 *     1. Filing type unambiguously triggers a federal rule deadline.
 *     2. No known local rule, standing order, or CMO modifies the default.
 *     3. No service date had to be inferred.
 * - `confidence` reflects rule-basis clarity, not calendar math.
 * - Unknown court → confidence: low + needs_verification: true, always.
 * - Returns schema-validated JSON only — no free text.
 */

import { completeText } from '../../lib/llm/index.js';
import type { ReaderOutput, FilingRecord } from './reader.js';

export interface DeadlineRecord {
  deadline_type: string;
  computed_date: string;       // YYYY-MM-DD
  days_remaining: number;
  source_filing: string;       // docket_entry_number of the triggering filing
  rule_basis: string;          // e.g. "FRCP 12(a)(1)" or "Local Rule 7-3 (C.D. Cal.)"
  confidence: 'high' | 'medium' | 'low';
  needs_verification: boolean;
}

export interface MapperOutput {
  matter_id: string;
  deadlines: DeadlineRecord[];
}

const MAPPER_SYSTEM_PROMPT = `
You are a deadline computation engine for a litigation docket watcher. You
receive a list of court filings and compute candidate response/deadline dates.

Hard rules:
- Set needs_verification: true on EVERY deadline unless ALL of the following
  are true simultaneously:
    1. The filing type unambiguously triggers a federal rule deadline
       (e.g., "Complaint served" → FRCP 12(a)(1) 21-day answer window).
    2. No local rule, standing order, or case management order is known to
       modify that default for this court.
    3. You did not have to infer a service date — the filing date IS the
       trigger date.
- confidence reflects rule-basis clarity:
    high   = clear federal rule, no known local modifications
    medium = local rule basis, or a federal rule with known local variants
    low    = state trial court, unknown court, or ambiguous filing type
- Unknown or state court = confidence: low + needs_verification: true always.
- You may NOT default-fill a deadline when the court is unknown. Return
  confidence: low and needs_verification: true rather than guessing.
- Return ONLY valid JSON. No preamble, no markdown fences.
- computed_date format: YYYY-MM-DD. If you cannot compute a date, use
  "needs-review" as the value and set confidence: low.
- Missing a court deadline has malpractice consequences. Loud is correct.

FRCP reference (encode common triggers):
- Answer to Complaint: FRCP 12(a)(1) — 21 days after service
- Reply re 12(b) motion: 14 days after response served (FRCP 12)
- Opposition to motion: typically 21 days (many districts 14-28 by local rule)
- Reply brief: typically 14 days after opposition
- Rule 26(a)(1) disclosures: 14 days after Rule 26(f) conference
- Summary judgment opposition: 21 days (varies widely by local rule)

Output schema:
{
  "matter_id": "string",
  "deadlines": [
    {
      "deadline_type": "string (max 80 chars)",
      "computed_date": "YYYY-MM-DD or needs-review",
      "days_remaining": number (negative if past),
      "source_filing": "docket_entry_number string",
      "rule_basis": "string (max 240 chars, cite the rule)",
      "confidence": "high | medium | low",
      "needs_verification": true|false
    }
  ]
}
`.trim();

function daysUntil(dateStr: string): number {
  const target = new Date(dateStr);
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  return Math.round((target.getTime() - now.getTime()) / 86_400_000);
}

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

export async function runDeadlineMapper(
  readerOutput: ReaderOutput,
  model: string,
): Promise<MapperOutput> {
  if (!readerOutput.filings.length) {
    return { matter_id: readerOutput.matter_id, deadlines: [] };
  }

  // Pass only sanitised, schema-validated fields — never raw filing text.
  const filingSummary = readerOutput.filings.map((f: FilingRecord) => ({
    docket_entry_number: f.docket_entry_number,
    filing_date: f.filing_date,
    filing_type: f.filing_type,   // already sanitised by reader
    // NOTE: 'title' is intentionally excluded here. The filer controls the
    // title text and it is a prompt-injection vector. The mapper receives only
    // the heuristic filing_type classification from the reader.
  }));

  const today = new Date().toISOString().slice(0, 10);

  const raw = await completeText({
    model,
    systemPrompt: MAPPER_SYSTEM_PROMPT,
    user: `
TODAY: ${today}
MATTER_ID: ${readerOutput.matter_id}
COURT: ${readerOutput.court}

FILINGS (sanitised JSON — no raw filing text):
${JSON.stringify(filingSummary, null, 2)}

Compute candidate deadlines. Return the JSON object per your system prompt.
Output ONLY the JSON.
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
      console.error('[deadline-mapper] JSON parse failed');
    }
  }

  const deadlines: DeadlineRecord[] = (parsed.deadlines ?? []).map((d: any) => ({
    deadline_type: String(d.deadline_type ?? '').slice(0, 80),
    computed_date: String(d.computed_date ?? 'needs-review'),
    days_remaining: typeof d.days_remaining === 'number'
      ? d.days_remaining
      : (d.computed_date && d.computed_date !== 'needs-review')
        ? daysUntil(d.computed_date)
        : 0,
    source_filing: String(d.source_filing ?? '').slice(0, 32),
    rule_basis: String(d.rule_basis ?? '').slice(0, 240),
    confidence: ['high', 'medium', 'low'].includes(d.confidence) ? d.confidence : 'low',
    needs_verification: d.needs_verification !== false, // default TRUE if missing
  }));

  return { matter_id: readerOutput.matter_id, deadlines };
}
