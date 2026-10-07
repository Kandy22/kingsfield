/**
 * Hallucination Guard Middleware.
 *
 * This middleware sits in front of any endpoint that returns model-generated
 * legal text to the user. It scans the outgoing payload for citations and
 * runs the four-gate pipeline. Vetoed citations cause the response to be
 * returned WITH veto flags — the frontend is responsible for rendering them
 * as red chips and disabling outbound actions until resolved.
 *
 * Critically: this never SILENTLY rewrites. It either passes the response
 * through (with verdicts attached) or blocks it explicitly. The goal is to
 * make hallucinations visible, not to paper over them.
 */

import type { RequestHandler } from 'express';
import type { SupabaseClient } from '@supabase/supabase-js';
import {
  verifyDraft,
  type VerifyOptions,
  type MatterContext,
  type GateVerdict,
} from '../verification/pipeline.js';

// Chat routes don't carry a matter/forum context the way project-scoped
// crew work does, so jurisdiction-fit (Gate 4) falls back to "persuasive"
// rather than "mandatory" for every source. This never trips a veto by
// itself (see composeVerdict in pipeline.ts) — it just keeps ungrounded
// chat citations out of the "verified" bucket.
const DEFAULT_CHAT_MATTER: MatterContext = {
  forum: 'General',
  jurisdictionTier: 'district',
};

export interface SseVerificationResult {
  verdicts: GateVerdict[];
  hasVetoes: boolean;
  hasConditional: boolean;
  error?: string;
}

/**
 * Run the four-gate pipeline against a fully-assembled SSE reply and never
 * throw. Streaming handlers call this after the model's final text is known
 * (and before res.end()) so the verdicts can go out as one more SSE event
 * on the same connection. Verification failures fail closed (hasVetoes:
 * true) without taking down the chat response itself.
 */
export async function verifyDraftForSse(
  draftText: string,
  opts: {
    courtListenerToken: string;
    supabase: SupabaseClient;
    matter?: MatterContext;
  },
): Promise<SseVerificationResult> {
  if (!draftText?.trim()) {
    return { verdicts: [], hasVetoes: false, hasConditional: false };
  }
  try {
    return await verifyDraft(draftText, {
      courtListenerToken: opts.courtListenerToken,
      supabase: opts.supabase,
      matter: opts.matter ?? DEFAULT_CHAT_MATTER,
    } as VerifyOptions);
  } catch (err: any) {
    return {
      verdicts: [],
      hasVetoes: true,
      hasConditional: false,
      error: `Verification failed: ${err?.message ?? 'unknown error'}. Treating as unverified.`,
    };
  }
}

// ---------------------------------------------------------------------------
// Buffering SSE writer: nothing the model wrote reaches the client until
// Gate 1 has run over the full reply.
// ---------------------------------------------------------------------------

const SSE_IDENT = /^[A-Za-z0-9_.:-]{1,64}$/;
const isIdent = (v: unknown) => typeof v === 'string' && SSE_IDENT.test(v);
const isCount = (v: unknown) => typeof v === 'number' && Number.isFinite(v);
const isNumOrNull = (v: unknown) => v === null || isCount(v);
const isNumArray = (v: unknown) => Array.isArray(v) && v.every(isCount);
const isServerString = (v: unknown) => typeof v === 'string' && v.length <= 300;

/**
 * Explicit allowlist of events that may go out immediately. Each entry lists
 * every key the payload may carry (besides `type`) and a predicate for its
 * value. Any extra key, wrong value shape or unlisted type is HELD.
 * Everything here is a bare status ping: identifiers, counts, numeric ids, or
 * strings read from server state, never text the model composed.
 */
const LIVE_SSE_EVENTS: Record<string, Record<string, (v: unknown) => boolean>> = {
  // name is the tool identifier the model picked from a fixed tool list.
  tool_call_start: { name: isIdent },
  mcp_tool_start: { name: isIdent },
  // Emitted only when workflow_id resolved in the server-side workflow store.
  workflow_applied: { workflow_id: isServerString, title: isServerString },
  // Numeric ids / counts only. No query, no case name, no citation.
  courtlistener_get_cases_start: { cluster_ids: isNumArray },
  courtlistener_read_case_start: { cluster_id: isNumOrNull },
  courtlistener_verify_citations_start: { citation_count: isCount },
  // Counts only; any `error` key makes it HELD.
  courtlistener_verify_citations: { citation_count: isCount, match_count: isCount },
};

export function isLiveSseLine(line: string): boolean {
  const m = /^data: ([^\n]*)\n\n$/.exec(line);
  if (!m) return false;
  let payload: unknown;
  try {
    payload = JSON.parse(m[1]);
  } catch {
    return false;
  }
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return false;
  const rec = payload as Record<string, unknown>;
  if (typeof rec.type !== 'string') return false;
  if (!Object.prototype.hasOwnProperty.call(LIVE_SSE_EVENTS, rec.type)) return false;
  const spec = LIVE_SSE_EVENTS[rec.type];
  return Object.keys(rec).every(
    (k) => k === 'type' || (Object.prototype.hasOwnProperty.call(spec, k) && spec[k](rec[k])),
  );
}

export interface BufferingSseWriter {
  /** Pass this to runLLMStream as `write`. */
  write: (line: string) => void;
  /** Release every held line, in original order. Call only after verification. */
  flush: () => void;
  /**
   * Hand every held line to the caller (and clear the buffer) WITHOUT sending
   * it. finalizeHeldOutput() decides what actually goes out.
   */
  takeHeld: () => string[];
}

/**
 * Wrap a raw SSE writer. Allowlisted status events pass straight through; all
 * other lines (model text, reasoning, citations, [DONE], tool results,
 * anything unparseable) are held until flush(). If flush() is never called
 * (abort, error, timeout) the held lines are simply dropped.
 */
export function createBufferingSseWriter(
  rawWrite: (line: string) => unknown,
): BufferingSseWriter {
  const held: string[] = [];
  return {
    write: (line: string) => {
      if (isLiveSseLine(line)) rawWrite(line);
      else held.push(line);
    },
    flush: () => {
      for (const line of held.splice(0)) rawWrite(line);
    },
    takeHeld: () => held.splice(0),
  };
}

// ---------------------------------------------------------------------------
// Keepalive: while output is held (the model has finished but Gate 1 has not),
// the browser sees nothing. Comment lines keep proxies and the fetch reader
// from timing the connection out. useAssistantChat ignores non-"data:" lines.
// ---------------------------------------------------------------------------

export const KEEPALIVE_LINE = ': ping\n\n';
export const KEEPALIVE_INTERVAL_MS = 15_000;

export interface KeepaliveTimers {
  setInterval: (fn: () => void, ms: number) => unknown;
  clearInterval: (handle: unknown) => void;
}

const defaultKeepaliveTimers: KeepaliveTimers = {
  setInterval: (fn, ms) => {
    const handle = setInterval(fn, ms);
    // A leaked timer must never keep the process alive.
    (handle as { unref?: () => void }).unref?.();
    return handle;
  },
  clearInterval: (handle) => clearInterval(handle as ReturnType<typeof setInterval>),
};

export interface SseKeepalive {
  /** Idempotent. Safe to call from catch, finally, flush and res "close". */
  stop: () => void;
  readonly active: boolean;
}

/**
 * Write `: ping\n\n` straight to the raw writer every `intervalMs` until
 * stop() is called. A throwing writer (socket already gone) stops the timer
 * instead of surfacing an uncaught exception from a timer callback.
 */
export function startSseKeepalive(
  rawWrite: (line: string) => unknown,
  opts: { intervalMs?: number; timers?: KeepaliveTimers } = {},
): SseKeepalive {
  const timers = opts.timers ?? defaultKeepaliveTimers;
  let handle: unknown;
  let active = true;
  const stop = () => {
    if (!active) return;
    active = false;
    timers.clearInterval(handle);
  };
  handle = timers.setInterval(() => {
    if (!active) return;
    try {
      rawWrite(KEEPALIVE_LINE);
    } catch {
      stop();
    }
  }, opts.intervalMs ?? KEEPALIVE_INTERVAL_MS);
  return {
    stop,
    get active() {
      return active;
    },
  };
}

// ---------------------------------------------------------------------------
// finalizeHeldOutput: decide what the user actually receives once Gate 1 has
// run over the whole reply. Pure apart from the injected `verify`.
// ---------------------------------------------------------------------------

export const WITHHELD_MESSAGE = 'This answer could not be verified and was withheld.';
export const REDACTION_MARKER = '[citation removed: failed verification]';

type Ev = Record<string, unknown>;

const isRecord = (v: unknown): v is Ev => !!v && typeof v === 'object' && !Array.isArray(v);
const isOkStatus = (s: unknown) => s === 'verified' || s === 'conditional';

export type VerifyFn = (text: string) => Promise<SseVerificationResult>;

function errorResult(message: string): SseVerificationResult {
  return {
    verdicts: [],
    hasVetoes: true,
    hasConditional: false,
    error: `Verification failed: ${message}. Treating as unverified.`,
  };
}

/** Never throws; a throw or malformed result becomes an error result (fail closed). */
async function safeVerify(verify: VerifyFn, text: string): Promise<SseVerificationResult> {
  try {
    const r = await verify(text);
    if (!isRecord(r) || !Array.isArray((r as Ev).verdicts)) return errorResult('malformed result');
    return r as unknown as SseVerificationResult;
  } catch (err: any) {
    return errorResult(err?.message ?? 'unknown error');
  }
}

const isVetoedVerdict = (v: GateVerdict) => !isOkStatus(v?.status);
const hasDraftPlaceholder = (r: SseVerificationResult) =>
  r.verdicts.some((v) => v?.citation === '[draft]');

/** Clean = no error, no veto of any kind, nothing pending, no whole-draft placeholder. */
function isClean(r: SseVerificationResult): boolean {
  return !r.error && !r.hasVetoes && !r.verdicts.some(isVetoedVerdict) && !hasDraftPlaceholder(r);
}

// ----- citation keys ---------------------------------------------------------

/**
 * volume | reporter | page, from any cite-shaped string. Used to match a
 * CourtListener case record (bare "123 So. 3d 456") to a verdict whose citation
 * is the full cite as written in the reply ("Doe v. Roe, 123 So. 3d 456 (Fla. 2013)").
 */
const CITE_KEY_RE =
  /(?<![\w.])(\d{1,4})\s+([A-Z][A-Za-z.'&\s]{0,40}?)\s*(\d{1,3}(?:d|th|st|nd|rd))?\s+([A-Z]{0,2}\d{1,6})(?!\d)/;

export function citeKey(citation: unknown): string | null {
  if (typeof citation !== 'string') return null;
  const m = CITE_KEY_RE.exec(citation);
  if (!m) return null;
  const reporter = `${m[2]}${m[3] ?? ''}`.toLowerCase().replace(/[^a-z0-9]/g, '');
  if (!reporter) return null;
  return `${m[1]}|${reporter}|${m[4].toLowerCase()}`;
}

/** key -> 'ok' | 'veto'. A veto on any verdict for a key wins. */
function buildVerdictIndex(verdicts: GateVerdict[]): Map<string, 'ok' | 'veto'> {
  const index = new Map<string, 'ok' | 'veto'>();
  for (const v of verdicts) {
    const key = citeKey(v?.citation);
    if (!key) continue;
    if (isVetoedVerdict(v)) index.set(key, 'veto');
    else if (!index.has(key)) index.set(key, 'ok');
  }
  return index;
}

// ----- redaction -------------------------------------------------------------

// Characters that may sit between (or inside) the characters of a cite in the
// ORIGINAL reply but not in the cleaned text the gate saw: whitespace and
// newlines, markdown emphasis/code/escape marks, link brackets and targets, and
// inline HTML tags.
const NOISE = String.raw`(?:\s|\]\([^)\s]{0,300}\)|[*_\x60\\\[\]]|<[^>\n]{0,60}>)*`;
const LEAD = String.raw`[\[*_\x60]*`;
const TRAIL = String.raw`(?:[*_\x60]{1,3})?(?:\]\([^)\s]{0,300}\))?`;

function escapeRe(s: string): string {
  // Only syntax characters: valid with and without the "u" flag.
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function charPattern(c: string): string {
  if (c === "'" || c === '’' || c === '‘') return "['’‘]";
  if (c === '"' || c === '“' || c === '”') return '["“”]';
  if (c === '-' || c === '–' || c === '—') return '[-–—]';
  if (c === '&') return '(?:&amp;|&)';
  return escapeRe(c);
}

interface CitePattern {
  /** Global, for replacement. */
  g: RegExp;
  /** Non-global, for tests (global regexes are stateful). */
  t: RegExp;
}

function buildCitePattern(cite: string): CitePattern | null {
  const chars = Array.from(cite).filter((c) => !/\s/u.test(c));
  if (!chars.length || chars.length > 800) return null;
  if (!chars.some((c) => /[\p{L}\p{N}]/u.test(c))) return null;
  const first = chars[0];
  const last = chars[chars.length - 1];
  const lead = /[A-Za-z0-9]/.test(first) ? '(?<![A-Za-z0-9])' : '';
  const trail = /[A-Za-z0-9]/.test(last) ? '(?![A-Za-z0-9])' : '';
  const body = LEAD + lead + chars.map(charPattern).join(NOISE) + trail + TRAIL;
  return { g: new RegExp(body, 'giu'), t: new RegExp(body, 'iu') };
}

const LINK_WITH_MARKER_RE = new RegExp(
  String.raw`\[(?:[^\[\]]|${escapeRe(REDACTION_MARKER)})*\]\([^)\s]*\)`,
  'g',
);

/**
 * Replace every occurrence of each cite with REDACTION_MARKER. Returns null if
 * any cite cannot be located in `text` (the caller must then withhold).
 * Overlapping matches are merged so one marker replaces the union.
 */
export function redactCitations(text: string, cites: string[]): string | null {
  const spans: Array<[number, number]> = [];
  for (const cite of cites) {
    const pat = buildCitePattern(cite);
    if (!pat || !pat.t.test(text)) return null;
    for (const m of text.matchAll(pat.g)) {
      if (m.index === undefined || m[0].length === 0) continue;
      spans.push([m.index, m.index + m[0].length]);
    }
  }
  if (!spans.length) return null;
  spans.sort((a, b) => a[0] - b[0] || b[1] - a[1]);
  let out = '';
  let pos = 0;
  let curStart = spans[0][0];
  let curEnd = spans[0][1];
  const emit = () => {
    out += text.slice(pos, curStart) + REDACTION_MARKER;
    pos = curEnd;
  };
  for (const [s, e] of spans.slice(1)) {
    if (s < curEnd) {
      curEnd = Math.max(curEnd, e);
    } else {
      emit();
      curStart = s;
      curEnd = e;
    }
  }
  emit();
  out += text.slice(pos);
  // A link whose label held a removed cite must not survive pointing at the case.
  return out.replace(LINK_WITH_MARKER_RE, (m) => (m.includes(REDACTION_MARKER) ? REDACTION_MARKER : m));
}

// ----- client-facing verification ------------------------------------------------

/**
 * Anything that looks like "volume reporter page" (optionally with a pin cite,
 * a short-form "at N" and a trailing court/year parenthetical). Used to scrub
 * notes on verdicts whose citation text must not reach the client.
 */
const REPORTER_CITE_TEXT_RE =
  /(?<![\w.])\d{1,4}\s+[A-Z][A-Za-z.'&\s]{0,40}?\s*(?:\d{1,3}(?:d|th|st|nd|rd))?\s+(?:[A-Z]{0,2}\d{1,6}|at\s+\*?\d{1,6})(?!\d)(?:\s*,\s*\d{1,6}(?:[-–]\d{1,6})?)?(?:\s*\([^()\n]{0,80}\b\d{4}\))?/g;

/** "Smith v. Jones" from "Smith v. Jones, 123 So. 3d 456 (Fla. 2013)"; null if there is no case-name shape. */
function captionOf(citation: string): string | null {
  const m = /^(.{3,200}?)\s*,?\s+\d{1,4}\s+[A-Z]/.exec(citation.trim());
  if (!m) return null;
  const cap = m[1].replace(/[\s,]+$/, '');
  return /(?:\sv\.?\s|^in re\b)/i.test(cap) ? cap : null;
}

function scrubNote(note: string, citation: string): string {
  let out = note;
  const cite = citation.trim();
  // '[draft]' is the whole-draft placeholder, not citation text.
  if (cite && cite !== '[draft]') {
    const patterns: CitePattern[] = [];
    const full = buildCitePattern(cite);
    if (full) patterns.push(full);
    const cap = captionOf(cite);
    const capPat = cap ? buildCitePattern(cap) : null;
    if (capPat) patterns.push(capPat);
    for (const p of patterns) out = out.replace(p.g, REDACTION_MARKER);
    // The raw string too, in case the tolerant pattern could not be built for it.
    if (cite.length >= 8) out = out.split(cite).join(REDACTION_MARKER);
  }
  return out.replace(REPORTER_CITE_TEXT_RE, REDACTION_MARKER);
}

/**
 * The only form of a verification result that may leave the server (SSE
 * `verification` event, and later saved annotations). Verified and conditional
 * verdicts pass through unchanged. Every other verdict (vetoed, pending,
 * unknown status) loses its citation string (`citation` becomes '') and has
 * citation text scrubbed out of its notes. Pure; never mutates its input.
 */
export function clientSafeVerification(result: SseVerificationResult): SseVerificationResult {
  const verdicts = Array.isArray(result?.verdicts) ? result.verdicts : [];
  return {
    ...result,
    verdicts: verdicts.map((v): GateVerdict => {
      if (!v || typeof v !== 'object' || isOkStatus(v.status)) return v;
      const citation = typeof v.citation === 'string' ? v.citation : '';
      const notes = Array.isArray(v.notes)
        ? v.notes.map((n) => scrubNote(typeof n === 'string' ? n : String(n ?? ''), citation))
        : [];
      return { ...v, citation: '', notes };
    }),
  };
}

// ----- event policy ------------------------------------------------------------

/** Replaces the message of every `error` event held inside the stream. No provider, model or exception text. */
export const GENERIC_ERROR_MESSAGE = 'The reply failed before it could be completed.';

type Policy =
  | { kind: 'pass' }
  | { kind: 'drop' }
  | { kind: 'error' }
  | { kind: 'citations' }
  | { kind: 'case_event' }
  | { kind: 'cl_get' }
  | { kind: 'cl_read' }
  | { kind: 'scrub' }
  | { kind: 'checked'; family: string; scrubOnFlag: boolean };

const DROP: Policy = { kind: 'drop' };
const checked = (family: string, scrubOnFlag = false): Policy => ({ kind: 'checked', family, scrubOnFlag });

/**
 * Policy per event type. SSE types and persisted (chat_messages.content) types
 * share this table so what is sent and what is saved cannot diverge. Any type
 * not listed is DROPPED (fail closed).
 */
const POLICY: Record<string, Policy> = {
  // Server-state names only (user's own uploaded documents) and workflow titles.
  doc_read: { kind: 'pass' },
  doc_read_start: { kind: 'pass' },
  workflow_applied: { kind: 'pass' },
  // Stream failure notice: kept in place, message replaced by a fixed string.
  error: { kind: 'error' },
  // Model reasoning is never sent.
  reasoning: DROP,
  reasoning_delta: DROP,
  reasoning_block_end: DROP,
  // Raw CourtListener opinion payloads: unverified case names and full text.
  case_opinions: DROP,
  // Case metadata gated on a matching non-vetoed verdict.
  citations: { kind: 'citations' },
  case_citation: { kind: 'case_event' },
  courtlistener_get_cases: { kind: 'cl_get' },
  courtlistener_read_case: { kind: 'cl_read' },
  // Model-supplied queries plus case names: dropped outright.
  courtlistener_find_in_case: DROP,
  courtlistener_find_in_case_start: DROP,
  // Error text from CourtListener; counts only.
  courtlistener_verify_citations: { kind: 'scrub' },
  // Model-chosen text, checked through Gate 1; family dropped if any string is flagged.
  courtlistener_search_case_law: checked('cl_search'),
  courtlistener_search_case_law_start: checked('cl_search'),
  doc_find: checked('doc_find'),
  doc_find_start: checked('doc_find'),
  doc_created: checked('doc_created'),
  doc_created_start: checked('doc_created'),
  doc_download: checked('doc_download'),
  doc_replicate_start: checked('doc_replicate'),
  doc_replicated: checked('doc_replicate'),
  doc_edited: checked('doc_edited'),
  doc_edited_start: checked('doc_edited'),
  // Result carries error text from an external server; scrubbed (not dropped) if flagged
  // because mcp_tool_start already went out live and the UI waits for the result.
  mcp_tool_result: checked('mcp', true),
  mcp_tool_call: checked('mcp', true),
};

/** Keep only numbers, booleans, null, identifier-shaped strings and numeric arrays. */
function scrubEvent(ev: Ev): Ev {
  const out: Ev = { type: ev.type };
  for (const [k, v] of Object.entries(ev)) {
    if (k === 'type') continue;
    if (v === null || typeof v === 'boolean' || isCount(v)) out[k] = v;
    else if (typeof v === 'string' && SSE_IDENT.test(v)) out[k] = v;
    else if (Array.isArray(v)) out[k] = v.every(isCount) ? v : [];
  }
  return out;
}

const URL_LIKE = /^(?:https?:\/\/|\/)\S*$/i;
const UUID_LIKE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Every string in an event that could carry a citation (needs a digit; not a URL or id). */
function citableStrings(ev: Ev): string[] {
  const out: string[] = [];
  const walk = (v: unknown, top: boolean) => {
    if (typeof v === 'string') {
      if (/\d/.test(v) && !URL_LIKE.test(v) && !UUID_LIKE.test(v)) out.push(v);
    } else if (Array.isArray(v)) {
      for (const x of v) walk(x, false);
    } else if (isRecord(v)) {
      for (const [k, x] of Object.entries(v)) {
        if (top && k === 'type') continue;
        walk(x, false);
      }
    }
  };
  walk(ev, true);
  return out;
}

const SHORT_FORM_RE = /\b(?:id|ibid|supra|infra)\b|\bat\s+\*?\d/i;
const MAX_SOLO_CHECKS = 30;
const MAX_FALLBACK_CHECKS = 40;

/**
 * Gate 1 over standalone strings. Strings with a short-form marker (Id., supra,
 * "at 5") are checked one at a time so a neighbour cannot supply their
 * antecedent; the rest go in one batch, and individually only if the batch is
 * unclean. Returns the strings that fail (veto, error, throw, over the cap).
 */
async function findFlaggedStrings(strings: string[], verify: VerifyFn): Promise<Set<string>> {
  const flagged = new Set<string>();
  const unique = [...new Set(strings)];
  const solo = unique.filter((s) => SHORT_FORM_RE.test(s));
  const batch = unique.filter((s) => !SHORT_FORM_RE.test(s));

  solo.forEach((s, i) => {
    if (i >= MAX_SOLO_CHECKS) flagged.add(s);
  });
  for (const s of solo.slice(0, MAX_SOLO_CHECKS)) {
    if (!isClean(await safeVerify(verify, s))) flagged.add(s);
  }
  if (!batch.length) return flagged;
  if (isClean(await safeVerify(verify, batch.join('\n\n')))) return flagged;
  if (batch.length === 1) {
    flagged.add(batch[0]);
    return flagged;
  }
  batch.forEach((s, i) => {
    if (i >= MAX_FALLBACK_CHECKS) flagged.add(s);
  });
  for (const s of batch.slice(0, MAX_FALLBACK_CHECKS)) {
    if (!isClean(await safeVerify(verify, s))) flagged.add(s);
  }
  return flagged;
}

// ----- the finalizer -----------------------------------------------------------

export interface FinalizeInput {
  /** Lines the buffering writer held (BufferingSseWriter.takeHeld()). */
  held: string[];
  /** runLLMStream's `events`: what chat_messages.content stores. */
  events: unknown[];
  /** runLLMStream's `annotations`: what chat_messages.annotations stores. */
  annotations: unknown[];
  /** runLLMStream's `fullText` (includes any <CITATIONS> block). */
  fullText: string;
  verify: VerifyFn;
}

export interface FinalizeOutput {
  /** Write these to the client, in order, then the verification event. */
  linesToSend: string[];
  /** Exactly what was sent, in persisted form, for chat_messages.content. */
  savedEvents: Ev[];
  /** Sent citation entries, for chat_messages.annotations. */
  savedAnnotations: unknown[];
  /**
   * For the `verification` SSE event. Already passed through
   * clientSafeVerification(): vetoed/pending verdicts carry no citation text.
   */
  verification: SseVerificationResult;
  withheld: boolean;
  withheldReason: string | null;
  redactedCitations: number;
}

interface HeldItem {
  line: string;
  kind: 'done' | 'event' | 'junk';
  ev?: Ev;
}

function parseHeldLine(line: string): HeldItem {
  if (line === 'data: [DONE]\n\n') return { line, kind: 'done' };
  const m = /^data: ([^\n]*)\n\n$/.exec(line);
  if (!m) return { line, kind: 'junk' };
  try {
    const ev = JSON.parse(m[1]);
    if (isRecord(ev) && typeof ev.type === 'string') return { line, kind: 'event', ev };
  } catch {
    /* fall through */
  }
  return { line, kind: 'junk' };
}

const sseLine = (ev: unknown) => `data: ${JSON.stringify(ev)}\n\n`;
const DONE_LINE = 'data: [DONE]\n\n';

interface Ctx {
  withhold: boolean;
  verdictIndex: Map<string, 'ok' | 'veto'>;
  vetoedPatterns: CitePattern[];
  flaggedFamilies: Set<string>;
}

function caseEntryAllowed(entry: unknown, ctx: Ctx): boolean {
  if (ctx.withhold || !isRecord(entry)) return false;
  const key = citeKey(entry.citation);
  return !!key && ctx.verdictIndex.get(key) === 'ok';
}

function entryStrings(v: unknown, out: string[] = []): string[] {
  if (typeof v === 'string') out.push(v);
  else if (Array.isArray(v)) v.forEach((x) => entryStrings(x, out));
  else if (isRecord(v)) Object.values(v).forEach((x) => entryStrings(x, out));
  return out;
}

/**
 * Document/page citations point into the user's own uploaded documents (kind
 * "document", doc_id, filename, page, quote) and carry no cluster_id. Anything
 * else, including an entry with an unknown or missing kind, is treated as case
 * law and must match a non-vetoed verdict.
 */
function isDocumentEntry(entry: unknown): boolean {
  return isRecord(entry) && entry.kind === 'document' && !('cluster_id' in entry);
}

function filterCitationEntries(entries: unknown[], ctx: Ctx): unknown[] {
  return entries.filter((entry) => {
    if (isDocumentEntry(entry)) {
      // Defensive: a quote from the user's document may itself contain a removed cite.
      if (!ctx.vetoedPatterns.length) return true;
      const strings = entryStrings(entry);
      return !ctx.vetoedPatterns.some((p) => strings.some((s) => p.t.test(s)));
    }
    return caseEntryAllowed(entry, ctx);
  });
}

/** content / content_delta are handled by the caller. Returns null to drop. */
function transformEvent(ev: Ev, ctx: Ctx): Ev | null {
  const policy = POLICY[String(ev.type)];
  if (!policy) return null;
  switch (policy.kind) {
    case 'pass':
      return ev;
    case 'drop':
      return null;
    case 'error':
      return { type: 'error', message: GENERIC_ERROR_MESSAGE };
    case 'citations':
      if (ctx.withhold || !Array.isArray(ev.citations)) return null;
      return { ...ev, citations: filterCitationEntries(ev.citations, ctx) };
    case 'case_event':
      return caseEntryAllowed(ev, ctx) ? ev : null;
    case 'cl_get': {
      const base = scrubEvent(ev);
      const cases = !ctx.withhold && Array.isArray(ev.cases)
        ? ev.cases.filter((c) => caseEntryAllowed(c, ctx))
        : [];
      return { ...base, cases };
    }
    case 'cl_read':
      return caseEntryAllowed(ev, ctx) ? ev : scrubEvent(ev);
    case 'scrub':
      return scrubEvent(ev);
    case 'checked':
      if (!ctx.withhold && !ctx.flaggedFamilies.has(policy.family)) return ev;
      return policy.scrubOnFlag ? scrubEvent(ev) : null;
  }
}

function extractContentText(ev: Ev): string | null {
  return typeof ev.text === 'string' ? ev.text : null;
}

function withheldOutput(
  items: HeldItem[],
  events: unknown[],
  verification: SseVerificationResult,
  reason: string,
): FinalizeOutput {
  const ctx: Ctx = {
    withhold: true,
    verdictIndex: new Map(),
    vetoedPatterns: [],
    flaggedFamilies: new Set(),
  };
  const linesToSend: string[] = [];
  for (const item of items) {
    if (item.kind !== 'event' || !item.ev) continue;
    if (item.ev.type === 'content_delta') continue;
    const out = transformEvent(item.ev, ctx);
    if (out) linesToSend.push(out === item.ev ? item.line : sseLine(out));
  }
  linesToSend.push(sseLine({ type: 'content_delta', text: WITHHELD_MESSAGE }));
  linesToSend.push(DONE_LINE);

  const savedEvents: Ev[] = [];
  let placed = false;
  for (const raw of events) {
    if (!isRecord(raw)) continue;
    if (raw.type === 'content') {
      if (!placed) {
        savedEvents.push({ type: 'content', text: WITHHELD_MESSAGE });
        placed = true;
      }
      continue;
    }
    const out = transformEvent(raw, ctx);
    if (out) savedEvents.push(out);
  }
  if (!placed) savedEvents.push({ type: 'content', text: WITHHELD_MESSAGE });

  return {
    linesToSend,
    savedEvents,
    savedAnnotations: [],
    verification: clientSafeVerification(verification),
    withheld: true,
    withheldReason: reason,
    redactedCitations: 0,
  };
}

/** Last-resort output that depends on nothing it was handed. */
function minimalWithheld(verification: SseVerificationResult, reason: string): FinalizeOutput {
  return {
    linesToSend: [sseLine({ type: 'content_delta', text: WITHHELD_MESSAGE }), DONE_LINE],
    savedEvents: [{ type: 'content', text: WITHHELD_MESSAGE }],
    savedAnnotations: [],
    verification: clientSafeVerification(verification),
    withheld: true,
    withheldReason: reason,
    redactedCitations: 0,
  };
}

/** Verification result for the SSE event when the withholding was NOT the gate's own doing. */
function failedVerification(first: SseVerificationResult, message: string): SseVerificationResult {
  return { ...first, hasVetoes: true, error: first.error ?? `Reply withheld: ${message}` };
}

/**
 * Decide what the user receives after Gate 1 ran over the full reply.
 *
 *  - gate error / throw / whole-draft ('[draft]') veto  -> withhold everything
 *  - no vetoes                                         -> replay held output unchanged
 *                                                         (rule-4 text still checked)
 *  - vetoes                                            -> redact in the assembled text,
 *                                                         re-verify the redacted text,
 *                                                         withhold if anything is left
 *
 * Never throws. Never sends held text it has not accounted for.
 */
export async function finalizeHeldOutput(input: FinalizeInput): Promise<FinalizeOutput> {
  let first: SseVerificationResult = errorResult('not run');
  let items: HeldItem[] = [];
  try {
    items = (Array.isArray(input.held) ? input.held : []).map(parseHeldLine);
    const events = Array.isArray(input.events) ? input.events : [];
    const annotations = Array.isArray(input.annotations) ? input.annotations : [];

    first = await safeVerify(input.verify, input.fullText);

    // 1. The gate itself failed, or vetoed the draft as a whole.
    if (first.error) return withheldOutput(items, events, first, 'verification_error');
    if (hasDraftPlaceholder(first)) return withheldOutput(items, events, first, 'whole_draft_veto');

    const vetoed = first.verdicts.filter(isVetoedVerdict);
    // hasVetoes with no vetoed verdict to locate is an inconsistent result.
    if (vetoed.length === 0 && first.hasVetoes) {
      return withheldOutput(items, events, first, 'veto_without_verdict');
    }

    // 2. Assemble the visible reply from the held deltas and check it against what is saved.
    const deltaTexts: string[] = [];
    for (const item of items) {
      if (item.kind === 'event' && item.ev?.type === 'content_delta') {
        const t = extractContentText(item.ev);
        if (t === null) {
          return withheldOutput(items, events, failedVerification(first, 'malformed content event'), 'malformed_content');
        }
        deltaTexts.push(t);
      }
    }
    const visible = deltaTexts.join('');
    const savedContent = events
      .filter((e): e is Ev => isRecord(e) && e.type === 'content')
      .map((e) => (typeof e.text === 'string' ? e.text : ''))
      .join('');
    if (visible !== savedContent) {
      return withheldOutput(items, events, failedVerification(first, 'streamed and saved text differ'), 'content_mismatch');
    }

    // 3. Redact vetoed citations and re-verify exactly what will be sent.
    let sentText = visible;
    let vetoedPatterns: CitePattern[] = [];
    if (vetoed.length > 0) {
      const cites = vetoed.map((v) => String(v.citation ?? ''));
      const redacted = redactCitations(visible, cites);
      if (redacted === null) {
        return withheldOutput(items, events, first, 'veto_not_located');
      }
      const second = await safeVerify(input.verify, redacted);
      if (!isClean(second)) {
        return withheldOutput(items, events, first, 'reverify_failed');
      }
      sentText = redacted;
      vetoedPatterns = cites.map(buildCitePattern).filter((p): p is CitePattern => p !== null);
    }

    // 4. Gate 1 over the other model-written text that would be sent.
    const familyStrings = new Map<string, string[]>();
    const collect = (ev: Ev) => {
      const policy = POLICY[String(ev.type)];
      if (policy?.kind !== 'checked') return;
      const list = familyStrings.get(policy.family) ?? [];
      list.push(...citableStrings(ev));
      familyStrings.set(policy.family, list);
    };
    for (const item of items) if (item.kind === 'event' && item.ev) collect(item.ev);
    for (const e of events) if (isRecord(e)) collect(e);
    const allStrings = [...familyStrings.values()].flat();
    const flaggedStrings = allStrings.length
      ? await findFlaggedStrings(allStrings, input.verify)
      : new Set<string>();
    const flaggedFamilies = new Set<string>();
    for (const [family, list] of familyStrings) {
      if (list.some((s) => flaggedStrings.has(s))) flaggedFamilies.add(family);
    }

    const ctx: Ctx = {
      withhold: false,
      verdictIndex: buildVerdictIndex(first.verdicts),
      vetoedPatterns,
      flaggedFamilies,
    };

    // 5. Build what is sent, in held order.
    const redacting = vetoed.length > 0;
    const linesToSend: string[] = [];
    let contentPlaced = false;
    for (const item of items) {
      if (item.kind === 'junk') continue;
      if (item.kind === 'done') {
        linesToSend.push(item.line);
        continue;
      }
      const ev = item.ev as Ev;
      if (ev.type === 'content_delta') {
        if (!redacting) {
          linesToSend.push(item.line);
        } else if (!contentPlaced) {
          linesToSend.push(sseLine({ type: 'content_delta', text: sentText }));
          contentPlaced = true;
        }
        continue;
      }
      const out = transformEvent(ev, ctx);
      if (out) linesToSend.push(out === ev ? item.line : sseLine(out));
    }

    // 6. The same decisions applied to the persisted form.
    const savedEvents: Ev[] = [];
    let savedPlaced = false;
    for (const raw of events) {
      if (!isRecord(raw)) continue;
      if (raw.type === 'content') {
        if (!redacting) savedEvents.push(raw);
        else if (!savedPlaced) {
          savedEvents.push({ ...raw, text: sentText });
          savedPlaced = true;
        }
        continue;
      }
      const out = transformEvent(raw, ctx);
      if (out) savedEvents.push(out);
    }

    return {
      linesToSend,
      savedEvents,
      savedAnnotations: filterCitationEntries(annotations, ctx),
      verification: clientSafeVerification(first),
      withheld: false,
      withheldReason: null,
      redactedCitations: vetoed.length,
    };
  } catch (err: any) {
    const verification = failedVerification(first, `internal error (${err?.message ?? 'unknown'})`);
    try {
      return withheldOutput(items, Array.isArray(input.events) ? input.events : [], verification, 'internal_error');
    } catch {
      return minimalWithheld(verification, 'internal_error');
    }
  }
}

export interface HallucinationGuardOptions {
  /** Paths or regexes that should be guarded. Others pass through. */
  guardedPaths: Array<string | RegExp>;
  buildVerifyOpts: (req: any) => VerifyOptions;
}

export function hallucinationGuard(opts: HallucinationGuardOptions): RequestHandler {
  return async (req, res, next) => {
    const isGuarded = opts.guardedPaths.some((p) =>
      typeof p === 'string' ? req.path.startsWith(p) : p.test(req.path),
    );
    if (!isGuarded) return next();

    // Capture the original send so we can intercept.
    const origJson = res.json.bind(res);
    res.json = (body: any) => {
      const draftText = extractDraftText(body);
      if (!draftText) return origJson(body);

      // Verification is async; wrap.
      verifyDraft(draftText, opts.buildVerifyOpts(req))
        .then((result) => {
          const out = {
            ...body,
            __verification: {
              verdicts: result.verdicts,
              hasVetoes: result.hasVetoes,
              hasConditional: result.hasConditional,
            },
          };
          return origJson(out);
        })
        .catch((err) => {
          // Fail closed: if verification crashes, mark the response as
          // unverified rather than silently passing it through.
          return origJson({
            ...body,
            __verification: {
              verdicts: [],
              hasVetoes: true,
              hasConditional: false,
              error: `Verification failed: ${err.message}. Treating as unverified.`,
            },
          });
        });
      return res; // satisfy chainable signature
    };

    next();
  };
}

function extractDraftText(body: any): string | null {
  // Kingsfield returns assistant messages with a `content` field that's either a
  // string or an array of content blocks. Normalize both.
  if (typeof body?.content === 'string') return body.content;
  if (Array.isArray(body?.content)) {
    return body.content
      .filter((b: any) => b.type === 'text' || typeof b === 'string')
      .map((b: any) => (typeof b === 'string' ? b : b.text))
      .join('\n');
  }
  if (typeof body?.message?.content === 'string') return body.message.content;
  return null;
}
