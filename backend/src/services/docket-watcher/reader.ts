/**
 * Docket Watcher — Tier 1: Reader.
 *
 * The ONLY tier that touches CourtListener directly. Returns schema-validated
 * JSON. Never writes to the database. Never calls an LLM.
 *
 * Security model (from anthropics/claude-for-legal docket-watcher cookbook):
 * Court filings are UNTRUSTED INPUT. The filer controls the text and can embed
 * prompt-injection payloads. This module treats all filing text as data — it
 * never summarises, interprets, or acts on filing content. It returns
 * length-capped, schema-validated JSON and nothing else.
 *
 * The deadline-mapper and reporter never see raw filing text.
 */

import { searchDocket, getDocketEntries } from '../../research/courtlistener.js';

export interface ReaderInput {
  matter_id: string;
  /** CourtListener docket ID (numeric). Preferred over docket_number lookup. */
  docket_id?: number;
  /** Case number string, e.g. "2:26-cv-00315". Used if docket_id is absent. */
  docket_number?: string;
  /** CourtListener court code, e.g. "cand". Required if docket_id is absent. */
  court?: string;
  /** ISO date — only entries on or after this date are returned. */
  since: string;
}

export interface FilingRecord {
  filing_date: string;          // ISO date, from CourtListener — trusted metadata
  filing_type: string;          // heuristic classification — UNTRUSTED label
  title: string;                // docket description — UNTRUSTED, max 400 chars
  filer: string;                // party name — UNTRUSTED, max 200 chars
  doc_url: string;              // inert URL string — never rendered as a link
  docket_entry_number: string;  // entry number — UNTRUSTED, max 16 chars
}

export interface ReaderOutput {
  matter_id: string;
  docket_id: number;
  court: string;
  as_of: string;        // ISO timestamp of when the read ran
  filings: FilingRecord[];
  error?: string;       // set if CourtListener returned an error
}

/** Heuristic: classify a filing description into a broad type. */
function classifyFiling(description: string): string {
  const d = description.toLowerCase();
  if (/motion to dismiss|12\(b\)/.test(d)) return 'Motion to Dismiss';
  if (/motion for summary judgment|summary judgment/.test(d)) return 'Motion for Summary Judgment';
  if (/motion in limine/.test(d)) return 'Motion in Limine';
  if (/complaint|petition/.test(d)) return 'Complaint/Petition';
  if (/answer|response to complaint/.test(d)) return 'Answer';
  if (/order|opinion/.test(d)) return 'Order/Opinion';
  if (/scheduling order|case management/.test(d)) return 'Scheduling/CMO';
  if (/stipulation|stip\./.test(d)) return 'Stipulation';
  if (/notice of appeal|appeal/.test(d)) return 'Appeal';
  if (/subpoena/.test(d)) return 'Subpoena';
  if (/deposition/.test(d)) return 'Deposition Notice';
  if (/discovery/.test(d)) return 'Discovery';
  if (/trial/.test(d)) return 'Trial-Related';
  if (/hearing/.test(d)) return 'Hearing Notice';
  if (/judgment|decree/.test(d)) return 'Judgment';
  if (/settlement/.test(d)) return 'Settlement';
  return 'Other';
}

/**
 * Sanitise a string from an UNTRUSTED source so it cannot inject into
 * downstream Markdown or YAML output.
 *
 * Rules (from tracker-writer.yaml):
 * - Leading formula chars get a prefixed apostrophe.
 * - Pipe chars are escaped so they cannot break Markdown tables.
 * - < and > are HTML-entity-escaped.
 * - Truncated to maxLen.
 */
function sanitiseUntrusted(s: string, maxLen: number): string {
  let out = String(s ?? '').slice(0, maxLen);
  // Neutralise spreadsheet formula injection
  if (/^[=+\-@\t\r]/.test(out)) out = `'${out}`;
  // Escape Markdown table pipe
  out = out.replace(/\|/g, '\\|');
  // Escape HTML
  out = out.replace(/</g, '&lt;').replace(/>/g, '&gt;');
  return out;
}

export async function runReader(
  input: ReaderInput,
  courtListenerToken: string,
): Promise<ReaderOutput> {
  const as_of = new Date().toISOString();

  try {
    // Resolve docket_id if not provided.
    let docketId = input.docket_id;
    let court = input.court ?? '';

    if (!docketId) {
      if (!input.docket_number || !input.court) {
        return {
          matter_id: input.matter_id,
          docket_id: 0,
          court: '',
          as_of,
          filings: [],
          error: 'Either docket_id or (docket_number + court) must be provided.',
        };
      }
      const found = await searchDocket(input.docket_number, input.court, courtListenerToken);
      if (!found) {
        return {
          matter_id: input.matter_id,
          docket_id: 0,
          court: input.court,
          as_of,
          filings: [],
          error: `Docket not found: ${input.docket_number} in ${input.court}`,
        };
      }
      docketId = found.id;
      court = found.court;
    }

    const entries = await getDocketEntries(docketId, input.since, courtListenerToken);

    // Build schema-validated, sanitised output.
    const filings: FilingRecord[] = entries.map((e) => ({
      filing_date: /^\d{4}-\d{2}-\d{2}/.test(e.filing_date) ? e.filing_date : '',
      filing_type: sanitiseUntrusted(classifyFiling(e.description), 80),
      title: sanitiseUntrusted(e.description, 400),
      filer: sanitiseUntrusted('', 200),   // CL v4 docket-entries don't surface filer reliably
      doc_url: e.doc_urls[0] ?? '',         // kept as inert string, never rendered as link
      docket_entry_number: sanitiseUntrusted(e.docket_entry_number, 16),
    }));

    return {
      matter_id: input.matter_id,
      docket_id: docketId,
      court,
      as_of,
      filings,
    };
  } catch (err: any) {
    return {
      matter_id: input.matter_id,
      docket_id: input.docket_id ?? 0,
      court: input.court ?? '',
      as_of,
      filings: [],
      error: String(err?.message ?? err),
    };
  }
}
