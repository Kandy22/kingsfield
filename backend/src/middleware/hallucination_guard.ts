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
import { safeErrorLog } from '../lib/safeError';

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

/** Sent and saved when verification could not run or the checked text cannot be tied to what is sent. */
export const WITHHELD_MESSAGE = 'This answer could not be verified and was withheld.';
/** Sent and saved when Gate 1 vetoed (or left pending) any citation in the reply. */
export const VETO_WITHHELD_MESSAGE = 'This answer was withheld because it cited a case that could not be verified.';
/** In-notes placeholder only: clientSafeVerification() puts it where a scrubbed verdict note held citation text. Never used in reply text. */
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

// ----- note scrubbing patterns -----------------------------------------------
// Used only by scrubNote() to remove citation text from verdict notes.

// Characters that may sit between (or inside) the characters of a cite as
// written: whitespace and newlines, markdown emphasis/code/escape marks, link
// brackets and targets, and inline HTML tags.
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

/** A global, whitespace/markdown-tolerant pattern for one cite; null if none can be built. */
function buildCitePattern(cite: string): RegExp | null {
  const chars = Array.from(cite).filter((c) => !/\s/u.test(c));
  if (!chars.length || chars.length > 800) return null;
  if (!chars.some((c) => /[\p{L}\p{N}]/u.test(c))) return null;
  const first = chars[0];
  const last = chars[chars.length - 1];
  const lead = /[A-Za-z0-9]/.test(first) ? '(?<![A-Za-z0-9])' : '';
  const trail = /[A-Za-z0-9]/.test(last) ? '(?![A-Za-z0-9])' : '';
  const body = LEAD + lead + chars.map(charPattern).join(NOISE) + trail + TRAIL;
  return new RegExp(body, 'giu');
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
    const patterns: RegExp[] = [];
    const full = buildCitePattern(cite);
    if (full) patterns.push(full);
    const cap = captionOf(cite);
    const capPat = cap ? buildCitePattern(cap) : null;
    if (capPat) patterns.push(capPat);
    for (const p of patterns) out = out.replace(p, REDACTION_MARKER);
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
 * citation text scrubbed out of its notes. Any `error` becomes the fixed
 * CLIENT_VERIFICATION_ERROR: no exception, SQLite, network or CourtListener
 * text leaves the server. Only the four known fields are copied. Pure; never
 * mutates its input.
 */
export const CLIENT_VERIFICATION_ERROR = 'Verification failed.';

export function clientSafeVerification(result: SseVerificationResult): SseVerificationResult {
  const verdicts = Array.isArray(result?.verdicts) ? result.verdicts : [];
  const out: SseVerificationResult = {
    hasVetoes: result?.hasVetoes,
    hasConditional: result?.hasConditional,
    verdicts: verdicts.map((v): GateVerdict => {
      if (!v || typeof v !== 'object' || isOkStatus(v.status)) return v;
      const citation = typeof v.citation === 'string' ? v.citation : '';
      const notes = Array.isArray(v.notes)
        ? v.notes.map((n) => scrubNote(typeof n === 'string' ? n : String(n ?? ''), citation))
        : [];
      return { ...v, citation: '', notes };
    }),
  };
  if (result?.error) out.error = CLIENT_VERIFICATION_ERROR;
  return out;
}

/**
 * The verification record saved in chat_messages.annotations. It is the
 * client-safe verification, shaped { type, verdicts, hasVetoes, hasConditional,
 * error? }. It deliberately has NO ref / kind / filename / document_id, so the
 * frontend's annotation matchers (a.ref === ref, a.kind !== "case" &&
 * a.filename === ...) never pick it up. Pass only clientSafeVerification output.
 */
export interface VerificationAnnotation {
  type: 'verification';
  verdicts: GateVerdict[];
  hasVetoes: boolean;
  hasConditional: boolean;
  error?: string;
}

export function buildVerificationAnnotation(clientSafe: SseVerificationResult): VerificationAnnotation {
  const rec: VerificationAnnotation = {
    type: 'verification',
    verdicts: clientSafe.verdicts,
    hasVetoes: clientSafe.hasVetoes,
    hasConditional: clientSafe.hasConditional,
  };
  if (clientSafe.error) rec.error = clientSafe.error;
  return rec;
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
  // Workflow titles read from the server-side workflow store.
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
  // The filename can be model-chosen (generate_docx titles), so doc_read is checked like the rest.
  doc_read: checked('doc_read'),
  doc_read_start: checked('doc_read'),
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
  /**
   * Server-side sink for the RAW verification failure (exception, SQLite,
   * network or CourtListener text). Called once per failed verification;
   * `context` says which step failed. Defaults to console.error. The raw text
   * never reaches the client: clientSafeVerification() replaces it.
   */
  logError?: VerificationErrorLogger;
}

export type VerificationErrorLogger = (context: string, error: ReturnType<typeof safeErrorLog>) => void;

const defaultErrorLogger: VerificationErrorLogger = (context, error) => {
  console.error(`[chat/verify] ${context}`, error);
};

export interface FinalizeOutput {
  /** Write these to the client, in order, then the verification event. */
  linesToSend: string[];
  /** Exactly what was sent, in persisted form, for chat_messages.content. */
  savedEvents: Ev[];
  /**
   * For chat_messages.annotations: the sent citation entries followed by ONE
   * VerificationAnnotation (the same client-safe record as `verification`).
   * Never empty, in every outcome (replay or withheld).
   */
  savedAnnotations: unknown[];
  /**
   * For the `verification` SSE event. Already passed through
   * clientSafeVerification(): vetoed/pending verdicts carry no citation text.
   */
  verification: SseVerificationResult;
  withheld: boolean;
  withheldReason: string | null;
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
  flaggedFamilies: Set<string>;
}

function caseEntryAllowed(entry: unknown, ctx: Ctx): boolean {
  if (ctx.withhold || !isRecord(entry)) return false;
  const key = citeKey(entry.citation);
  return !!key && ctx.verdictIndex.get(key) === 'ok';
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
  return entries.filter((entry) => isDocumentEntry(entry) || caseEntryAllowed(entry, ctx));
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
  message: string = WITHHELD_MESSAGE,
): FinalizeOutput {
  const ctx: Ctx = {
    withhold: true,
    verdictIndex: new Map(),
    flaggedFamilies: new Set(),
  };
  const linesToSend: string[] = [];
  for (const item of items) {
    if (item.kind !== 'event' || !item.ev) continue;
    if (item.ev.type === 'content_delta') continue;
    const out = transformEvent(item.ev, ctx);
    if (out) linesToSend.push(out === item.ev ? item.line : sseLine(out));
  }
  linesToSend.push(sseLine({ type: 'content_delta', text: message }));
  linesToSend.push(DONE_LINE);

  const savedEvents: Ev[] = [];
  let placed = false;
  for (const raw of events) {
    if (!isRecord(raw)) continue;
    if (raw.type === 'content') {
      if (!placed) {
        savedEvents.push({ type: 'content', text: message });
        placed = true;
      }
      continue;
    }
    const out = transformEvent(raw, ctx);
    if (out) savedEvents.push(out);
  }
  if (!placed) savedEvents.push({ type: 'content', text: message });

  // A reply withheld for a veto always says so, whatever flag the gate result carried
  // (a pending or unknown-status verdict can arrive with hasVetoes: false). The sent and
  // the saved record come from this one object.
  const vetoed = reason === 'veto' || reason === 'whole_draft_veto';
  const safe = clientSafeVerification(vetoed ? { ...verification, hasVetoes: true } : verification);
  return {
    linesToSend,
    savedEvents,
    savedAnnotations: [buildVerificationAnnotation(safe)],
    verification: safe,
    withheld: true,
    withheldReason: reason,
  };
}

/** Last-resort output that depends on nothing it was handed. */
function minimalWithheld(verification: SseVerificationResult, reason: string): FinalizeOutput {
  const safe = clientSafeVerification(verification);
  return {
    linesToSend: [sseLine({ type: 'content_delta', text: WITHHELD_MESSAGE }), DONE_LINE],
    savedEvents: [{ type: 'content', text: WITHHELD_MESSAGE }],
    savedAnnotations: [buildVerificationAnnotation(safe)],
    verification: safe,
    withheld: true,
    withheldReason: reason,
  };
}

/** Verification result for the SSE event when the withholding was NOT the gate's own doing. */
function failedVerification(first: SseVerificationResult, message: string): SseVerificationResult {
  return { ...first, hasVetoes: true, error: first.error ?? `Reply withheld: ${message}` };
}

// ----- visible text vs. full text ---------------------------------------------

/** The tag runLLMStream hides from the stream (chatTools.ts CITATIONS_OPEN_TAG). */
const CITATIONS_OPEN_TAG = '<CITATIONS>';
/**
 * Work budget for the alignment search below, in "units". Every unit is one
 * character comparison, one loop iteration, one character of the one-time tag
 * scan, or ALIGN_WALK_COST for a walk() call (its binary search and memo lookup).
 * Nothing the search does is free, so the total work is at most
 * ALIGN_WORK_BUDGET units plus one bounded step, whatever the input size or
 * shape. Reaching the budget fails closed (see alignVisibleToFullText).
 *
 * Sizing: an honest reply costs about len(visible) + len(hidden blocks) units
 * (one comparison pass plus the one-time scan), so a 100 KB reply with one
 * trailing block is ~0.2M units and the multi-iteration replies in the tests are
 * below 0.5M. 10M is 20x or more above those, and still only tens of
 * milliseconds of synchronous work in the worst case.
 */
export const ALIGN_WORK_BUDGET = 10_000_000;
/** Units charged per walk() call: a binary search over the tag positions plus a Set lookup/insert. */
const ALIGN_WALK_COST = 32;

export interface AlignmentResult {
  /** True only when a complete alignment was found within the budget. */
  matched: boolean;
  /** Units charged. Work actually performed never exceeds ALIGN_WORK_BUDGET (the charge that tips over is refused). */
  work: number;
  /** True when the budget ran out. Always accompanied by matched === false. */
  exhausted: boolean;
}

/**
 * The search behind visibleMatchesFullText, with its accounting exposed so the
 * budget can be measured. Deterministic, never throws on string input.
 * Budget exhaustion returns { matched: false, exhausted: true }: a search that
 * ran out of budget is indistinguishable from "no alignment" to the caller, and
 * the final result is forced to false whenever `exhausted` is set.
 */
export function alignVisibleToFullText(visible: string, fullText: string): AlignmentResult {
  if (visible === fullText) return { matched: true, work: 0, exhausted: false };
  const tag = CITATIONS_OPEN_TAG;
  // The shown text is fullText with stretches removed: it can never be longer.
  if (visible.length > fullText.length) return { matched: false, work: 0, exhausted: false };

  let work = 0;
  let exhausted = false;
  /** Charge `n` units; false (and `exhausted`) once the budget is gone. */
  const spend = (n: number): boolean => {
    work += n;
    if (work > ALIGN_WORK_BUDGET) {
      exhausted = true;
      return false;
    }
    return true;
  };

  // One pass: every tag position. Charged by length (indexOf scans the whole string).
  if (!spend(fullText.length)) return { matched: false, work, exhausted };
  const tags: number[] = [];
  for (let i = fullText.indexOf(tag); i >= 0; i = fullText.indexOf(tag, i + tag.length)) tags.push(i);
  if (!tags.length) return { matched: false, work, exhausted };
  const tagStarts = new Set<number>(tags);
  /** First tag position at or after `fp`, or -1. */
  const nextTag = (fp: number): number => {
    let lo = 0;
    let hi = tags.length;
    while (lo < hi) {
      const mid = (lo + hi) >>> 1;
      if (tags[mid] < fp) lo = mid + 1;
      else hi = mid;
    }
    return lo < tags.length ? tags[lo] : -1;
  };

  const failedStates = new Set<number>();
  /** fullText[fp .. fp+len) equals visible[vp .. vp+len). Every comparison is charged. */
  const runMatches = (fp: number, vp: number, len: number): boolean => {
    if (vp + len > visible.length) return false;
    const room = ALIGN_WORK_BUDGET - work;
    const n = len < room ? len : room;
    for (let i = 0; i < n; i++) {
      if (fullText.charCodeAt(fp + i) !== visible.charCodeAt(vp + i)) {
        work += i + 1;
        return false;
      }
    }
    work += n;
    if (n < len) {
      // The run could not be finished inside the budget: not a match, not a mismatch.
      work += 1;
      exhausted = true;
      return false;
    }
    return true;
  };
  // An iteration starts at fullText[fp]; visible[0..vp) has been accounted for so far.
  const walk = (fp: number, vp: number): boolean => {
    if (exhausted || !spend(ALIGN_WALK_COST)) return false;
    const stateKey = fp * (visible.length + 1) + vp;
    if (failedStates.has(stateKey)) return false;
    const tagIdx = nextTag(fp);
    let ok = false;
    if (tagIdx < 0) {
      // No tag left: every remaining iteration is shown whole.
      ok = fullText.length - fp === visible.length - vp && runMatches(fp, vp, fullText.length - fp);
    } else if (runMatches(fp, vp, tagIdx - fp)) {
      // This iteration shows fullText[fp, tagIdx) and hides from the tag to its own end.
      // The next iteration starts at some q at or after the end of the tag (or fullText ends).
      const nextVp = vp + (tagIdx - fp);
      const first = tagIdx + tag.length;
      ok = walk(fullText.length, nextVp);
      for (let q = first; q < fullText.length && !ok && !exhausted; q++) {
        if (!spend(1)) break;
        // The next iteration shows its first character or, if it starts with the tag, nothing.
        if (!tagStarts.has(q) && fullText.charCodeAt(q) !== visible.charCodeAt(nextVp)) continue;
        ok = walk(q, nextVp);
      }
    }
    if (!ok && !exhausted) failedStates.add(stateKey);
    return ok;
  };
  const matched = walk(0, 0) && !exhausted;
  return { matched, work, exhausted };
}

/**
 * True only when `visible` (the joined content_delta texts) is exactly what
 * runLLMStream shows of `fullText` (the joined model text of every iteration).
 * runLLMStream streams each iteration up to its first <CITATIONS> tag and hides
 * everything after the tag to the end of that iteration; iteration boundaries
 * are not recorded in fullText. So `visible` must be fullText with zero or more
 * hidden stretches removed, each stretch starting exactly at a <CITATIONS> tag.
 * Identical strings match. Anything else (extra text, missing text, text moved,
 * a blank fullText with non-blank visible, a hidden stretch not at a tag) does
 * not. Deterministic. Total work, character comparisons included, is bounded by
 * ALIGN_WORK_BUDGET; running out of budget returns false (fail closed), so
 * finalizeHeldOutput withholds with 'fulltext_mismatch'.
 */
export function visibleMatchesFullText(visible: string, fullText: string): boolean {
  return alignVisibleToFullText(visible, fullText).matched;
}

/**
 * Decide what the user receives after Gate 1 ran over the reply.
 *
 * Gate 1 runs over `fullText` (its verdicts feed the citations/case events) and
 * over the exact text that will be sent (the joined held content_delta texts),
 * unless the two are identical.
 *
 *  - any vetoed or pending verdict, or a '[draft]' whole-draft veto
 *                                                -> withhold everything, VETO_WITHHELD_MESSAGE
 *  - gate error / throw / inconsistent result, malformed content, sent text that is not
 *    fullText with its hidden <CITATIONS> parts removed, sent vs saved text differing,
 *    internal error                             -> withhold everything, WITHHELD_MESSAGE
 *  - otherwise (verified / conditional only)    -> replay held output unchanged
 *                                                  (rule-4 text still checked)
 *
 * No part of a model reply is ever rewritten: it is sent whole or not at all.
 * Never throws. Never sends held text it has not accounted for.
 */
export async function finalizeHeldOutput(input: FinalizeInput): Promise<FinalizeOutput> {
  let first: SseVerificationResult = errorResult('not run');
  let items: HeldItem[] = [];

  // The raw error stays on the server: every failed verification is logged once, here.
  const sink = input.logError ?? defaultErrorLogger;
  const logFailure = (context: string, raw: unknown) => {
    try {
      sink(context, safeErrorLog(raw));
    } catch {
      /* logging must never change the outcome */
    }
  };
  const verifyAs = (context: string): VerifyFn => async (text) => {
    const r = await safeVerify(input.verify, text);
    if (r.error) logFailure(context, r.error);
    return r;
  };
  // A failure that is not the gate's own (mismatch, internal error): log what the client is told, in full.
  const failed = (prev: SseVerificationResult, message: string): SseVerificationResult => {
    const v = failedVerification(prev, message);
    if (!prev.error) logFailure('withheld', v.error);
    return v;
  };

  try {
    items = (Array.isArray(input.held) ? input.held : []).map(parseHeldLine);
    const events = Array.isArray(input.events) ? input.events : [];
    const annotations = Array.isArray(input.annotations) ? input.annotations : [];

    if (typeof input.fullText !== 'string') throw new Error('fullText is not a string');
    const fullText = input.fullText;

    // The exact text that will be sent: the joined held content_delta texts.
    let malformedContent = false;
    const deltaTexts: string[] = [];
    for (const item of items) {
      if (item.kind === 'event' && item.ev?.type === 'content_delta') {
        const t = extractContentText(item.ev);
        if (t === null) malformedContent = true;
        else deltaTexts.push(t);
      }
    }
    const visible = deltaTexts.join('');

    // Any non-clean result withholds: a veto (or pending) with the veto message, the rest with the generic one.
    const withholdIfNotClean = (r: SseVerificationResult): FinalizeOutput | null => {
      if (r.error) return withheldOutput(items, events, r, 'verification_error');
      if (hasDraftPlaceholder(r)) return withheldOutput(items, events, r, 'whole_draft_veto', VETO_WITHHELD_MESSAGE);
      if (r.verdicts.some(isVetoedVerdict)) return withheldOutput(items, events, r, 'veto', VETO_WITHHELD_MESSAGE);
      // hasVetoes with no vetoed verdict is an inconsistent result.
      if (r.hasVetoes) return withheldOutput(items, events, r, 'veto_without_verdict');
      return null;
    };

    // 1. Gate 1 over the full reply. Its verdicts feed the citations / case events.
    first = await verifyAs('first_verify')(fullText);
    const firstBlock = withholdIfNotClean(first);
    if (firstBlock) return firstBlock;

    if (malformedContent) {
      return withheldOutput(items, events, failed(first, 'malformed content event'), 'malformed_content');
    }

    // 2. Gate 1 over exactly the text that will be sent, unless it is the same string.
    if (visible !== fullText) {
      const sentResult = await verifyAs('visible_verify')(visible);
      const sentBlock = withholdIfNotClean(sentResult);
      if (sentBlock) return sentBlock;
      // 3. The sent text must be the full text with only the hidden <CITATIONS> parts removed.
      if (!visibleMatchesFullText(visible, fullText)) {
        return withheldOutput(
          items, events, failed(first, 'sent text does not match the verified text'), 'fulltext_mismatch',
        );
      }
    }

    // 4. The sent text must be the text that is saved.
    const savedContent = events
      .filter((e): e is Ev => isRecord(e) && e.type === 'content')
      .map((e) => (typeof e.text === 'string' ? e.text : ''))
      .join('');
    if (visible !== savedContent) {
      return withheldOutput(items, events, failed(first, 'streamed and saved text differ'), 'content_mismatch');
    }

    // 5. Gate 1 over the other model-written text that would be sent.
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
      ? await findFlaggedStrings(allStrings, verifyAs('tool_text'))
      : new Set<string>();
    const flaggedFamilies = new Set<string>();
    for (const [family, list] of familyStrings) {
      if (list.some((s) => flaggedStrings.has(s))) flaggedFamilies.add(family);
    }

    const ctx: Ctx = {
      withhold: false,
      // Built only from the clean full-text result: every verdict in it is verified or conditional.
      verdictIndex: buildVerdictIndex(first.verdicts),
      flaggedFamilies,
    };

    // 6. Build what is sent, in held order. Model text goes out unchanged.
    const linesToSend: string[] = [];
    for (const item of items) {
      if (item.kind === 'junk') continue;
      if (item.kind === 'done') {
        linesToSend.push(item.line);
        continue;
      }
      const ev = item.ev as Ev;
      if (ev.type === 'content_delta') {
        linesToSend.push(item.line);
        continue;
      }
      const out = transformEvent(ev, ctx);
      if (out) linesToSend.push(out === ev ? item.line : sseLine(out));
    }

    // 7. The same decisions applied to the persisted form.
    const savedEvents: Ev[] = [];
    for (const raw of events) {
      if (!isRecord(raw)) continue;
      if (raw.type === 'content') {
        savedEvents.push(raw);
        continue;
      }
      const out = transformEvent(raw, ctx);
      if (out) savedEvents.push(out);
    }

    const safe = clientSafeVerification(first);
    return {
      linesToSend,
      savedEvents,
      savedAnnotations: [...filterCitationEntries(annotations, ctx), buildVerificationAnnotation(safe)],
      verification: safe,
      withheld: false,
      withheldReason: null,
    };
  } catch (err: any) {
    logFailure('internal_error', err);
    const verification = failedVerification(first, `internal error (${err?.message ?? 'unknown'})`);
    try {
      return withheldOutput(items, Array.isArray(input.events) ? input.events : [], verification, 'internal_error');
    } catch {
      return minimalWithheld(verification, 'internal_error');
    }
  }
}

// ----- failed / aborted replies -------------------------------------------------

/** Saved as the whole assistant message when a reply was aborted (client left, stream cancelled). */
export const ABORTED_MESSAGE = 'This reply was stopped before it was completed.';

export type FailedReplyKind = 'aborted' | 'failed';

export interface FailedReplyRecord {
  /** For chat_messages.content: fixed strings only. */
  events: Ev[];
  /** For chat_messages.annotations: always null (a marker has no citations and no verification record). */
  annotations: null;
  /** SSE lines for the browser. Empty for 'aborted' (the client is gone). Generic error event then [DONE] for 'failed'. */
  sseLines: string[];
}

/**
 * What a route saves (and, for a failure, sends) when a reply did not complete.
 * It takes no model text, no error and no events, so nothing from the stream,
 * a tool or a provider can appear in it. Anything other than 'aborted' is
 * treated as 'failed'. Every call returns fresh objects.
 *
 * Saved shape: a `content` event carrying the fixed text (this is what the
 * frontend renders as the message body after a reload: getChat() joins the
 * `content` events, and AssistantMessage never prints `error` event text), plus,
 * for 'failed', the `error` event with the generic message so the message
 * keeps the red error icon on reload.
 */
export function failedReplyRecord(kind: FailedReplyKind): FailedReplyRecord {
  if (kind === 'aborted') {
    return { events: [{ type: 'content', text: ABORTED_MESSAGE }], annotations: null, sseLines: [] };
  }
  return {
    events: [
      { type: 'content', text: GENERIC_ERROR_MESSAGE },
      { type: 'error', message: GENERIC_ERROR_MESSAGE },
    ],
    annotations: null,
    sseLines: [sseLine({ type: 'error', message: GENERIC_ERROR_MESSAGE }), DONE_LINE],
  };
}

// ---------------------------------------------------------------------------
// Routes that are not the chat stream (/crew/chat, /council): the same Gate 1,
// the same withhold-whole rule, the same client-safe verification record.
// ---------------------------------------------------------------------------

function makeFailureLogger(sink?: VerificationErrorLogger) {
  const out = sink ?? defaultErrorLogger;
  return (context: string, raw: unknown) => {
    try {
      out(context, safeErrorLog(raw));
    } catch {
      /* logging must never change the outcome */
    }
  };
}

/** One result out of several: every verdict, any veto, any conditional, the first error. */
function mergeResults(results: SseVerificationResult[]): SseVerificationResult {
  const merged: SseVerificationResult = {
    verdicts: results.flatMap((r) => r.verdicts),
    hasVetoes: results.some((r) => r.hasVetoes),
    hasConditional: results.some((r) => r.hasConditional),
  };
  const error = results.find((r) => r.error)?.error;
  if (error) merged.error = error;
  return merged;
}

/** The reason and the fixed message for a non-clean result; null when the result is clean. */
function uncleanOutcome(r: SseVerificationResult): { reason: string; message: string } | null {
  if (r.error) return { reason: 'verification_error', message: WITHHELD_MESSAGE };
  if (hasDraftPlaceholder(r)) return { reason: 'whole_draft_veto', message: VETO_WITHHELD_MESSAGE };
  if (r.verdicts.some(isVetoedVerdict)) return { reason: 'veto', message: VETO_WITHHELD_MESSAGE };
  if (r.hasVetoes) return { reason: 'veto_without_verdict', message: WITHHELD_MESSAGE };
  return null;
}

/** The `verification` SSE event line, built from a client-safe result only. */
export function verificationSseLine(safe: SseVerificationResult): string {
  return sseLine({
    type: 'verification',
    verdicts: safe.verdicts,
    hasVetoes: safe.hasVetoes,
    hasConditional: safe.hasConditional,
    error: safe.error,
  });
}

// ----- /crew/chat ---------------------------------------------------------------

/** One streamed content_delta carries at most this many characters (the drip animation in the UI). */
export const CREW_CHUNK_SIZE = 80;

export interface CrewAuthorityLike {
  citation: string;
  sourceUrl: string;
  /** Model-written by the Researcher. */
  relevanceNote: string;
}

export interface FinalizeCrewInput {
  /** The Team Lead / specialist reply (or the direct completeText fallback). */
  reply: string;
  authorities: CrewAuthorityLike[];
  verify: VerifyFn;
  logError?: VerificationErrorLogger;
}

/**
 * Gate 1 for everything /crew/chat sends, through finalizeHeldOutput so the
 * veto / withhold / verification-record rules are the chat ones, unchanged.
 *
 * Held output = the reply as content_delta chunks, one `citations` event
 * (type 'legal_authority': citation, url, relevance) and [DONE]. The checked
 * full text is the reply, then a hidden <CITATIONS> stretch holding every string
 * the citations event carries (citation, url, relevance), so a cite hidden in a
 * relevance note is vetoed like one in the reply, and the sent reply is checked
 * on its own as well (no antecedent can be borrowed from the hidden part).
 * Short-form strings in the hidden part (Id., supra, "at 5") are also checked
 * alone, so a neighbour cannot supply their antecedent.
 *
 * Citation chips are kept only when their citation matches a verified or
 * conditional verdict (the chat rule); the rest are dropped from a clean reply.
 * A veto, pending verdict, gate error or malformed input withholds the whole
 * reply (VETO_WITHHELD_MESSAGE / WITHHELD_MESSAGE) with no citations event.
 *
 * linesToSend ends with the client-safe `verification` event and then [DONE].
 * Never throws.
 */
export async function finalizeCrewReply(input: FinalizeCrewInput): Promise<FinalizeOutput> {
  const log = makeFailureLogger(input.logError);
  let held: string[] = [];
  let events: unknown[] = [];
  let fullText: string | undefined;
  const hidden: string[] = [];

  try {
    const { reply, authorities } = input;
    if (typeof reply !== 'string') throw new Error('crew reply is not a string');
    if (!Array.isArray(authorities)) throw new Error('crew authorities is not an array');

    const entries: Ev[] = [];
    for (const a of authorities) {
      if (!isRecord(a) || typeof a.citation !== 'string' || typeof a.sourceUrl !== 'string') {
        throw new Error('malformed crew authority');
      }
      const relevance = a.relevanceNote ?? '';
      if (typeof relevance !== 'string') throw new Error('malformed crew authority relevance');
      entries.push({ type: 'legal_authority', citation: a.citation, url: a.sourceUrl, relevance });
      hidden.push(a.citation, a.sourceUrl, relevance);
    }

    for (let i = 0; i < reply.length; i += CREW_CHUNK_SIZE) {
      held.push(sseLine({ type: 'content_delta', text: reply.slice(i, i + CREW_CHUNK_SIZE) }));
    }
    held.push(sseLine({ type: 'citations', citations: entries }));
    held.push(DONE_LINE);
    events = [{ type: 'content', text: reply }];
    fullText = hidden.length ? `${reply}${CITATIONS_OPEN_TAG}${hidden.join('\n')}` : reply;
  } catch (err: any) {
    // Anything malformed: hand finalizeHeldOutput a non-string fullText so it withholds (fail closed).
    log('crew_input', err);
    held = [];
    events = [];
    fullText = undefined;
  }

  const full = fullText;
  const verify: VerifyFn = async (text) => {
    const main = await safeVerify(input.verify, text);
    if (text !== full) return main;
    const solo = [...new Set(hidden)].filter((s) => SHORT_FORM_RE.test(s));
    if (solo.length > MAX_SOLO_CHECKS) return errorResult('too many short-form authority strings');
    const results = [main];
    for (const s of solo) results.push(await safeVerify(input.verify, s));
    return mergeResults(results);
  };

  const out = await finalizeHeldOutput({
    held,
    events,
    annotations: [],
    fullText: full as string,
    verify,
    logError: input.logError,
  });

  // The verification event goes out before [DONE].
  const lines = out.linesToSend.slice();
  if (lines[lines.length - 1] === DONE_LINE) lines.pop();
  lines.push(verificationSseLine(out.verification), DONE_LINE);
  return { ...out, linesToSend: lines };
}

// ----- /council -----------------------------------------------------------------

export const COUNCIL_ROLES = ['contrarian', 'first_principles', 'expansionist', 'outsider', 'executor'] as const;
const COUNCIL_LETTERS = ['A', 'B', 'C', 'D', 'E'] as const;
const COUNCIL_NAME = /^[A-Za-z0-9_.:/-]{1,80}$/;

/** What /council returns (and llm_council_sessions stores): the shape council/page.tsx reads. */
export interface CouncilTextOutput {
  framedQuestion: string;
  advisors: Array<{
    role: (typeof COUNCIL_ROLES)[number];
    model: { provider: string; model: string };
    text: string;
    letter: (typeof COUNCIL_LETTERS)[number];
  }>;
  reviewers: Array<{ reviewerRole: (typeof COUNCIL_ROLES)[number]; text: string }>;
  chairmanVerdict: string;
}

export interface GatedCouncil {
  /** What may be sent, saved and rendered: the checked text, or the fixed withheld version. */
  output: CouncilTextOutput;
  /** Client-safe (clientSafeVerification): no citation text on a non-OK verdict, no raw error. */
  verification: SseVerificationResult;
  withheld: boolean;
  withheldReason: string | null;
}

/**
 * Same shape as a real council output, every text field the fixed message: five
 * advisors (so each seat in the UI has a response), five reviewers, no model text.
 */
export function withheldCouncilOutput(message: string = WITHHELD_MESSAGE): CouncilTextOutput {
  return {
    framedQuestion: message,
    advisors: COUNCIL_ROLES.map((role, i) => ({
      role,
      model: { provider: 'withheld', model: 'withheld' },
      text: message,
      letter: COUNCIL_LETTERS[i],
    })),
    reviewers: COUNCIL_ROLES.map((reviewerRole) => ({ reviewerRole, text: message })),
    chairmanVerdict: message,
  };
}

const isOneOf = <T extends string>(list: readonly T[], v: unknown): v is T =>
  typeof v === 'string' && (list as readonly string[]).includes(v);

/** Rebuild with only the known keys (no extra field can carry unchecked text); null if malformed. */
function normalizeCouncil(raw: unknown): CouncilTextOutput | null {
  if (!isRecord(raw)) return null;
  if (typeof raw.framedQuestion !== 'string' || typeof raw.chairmanVerdict !== 'string') return null;
  if (!Array.isArray(raw.advisors) || !Array.isArray(raw.reviewers)) return null;
  const advisors: CouncilTextOutput['advisors'] = [];
  for (const a of raw.advisors) {
    if (!isRecord(a) || !isOneOf(COUNCIL_ROLES, a.role) || !isOneOf(COUNCIL_LETTERS, a.letter)) return null;
    if (typeof a.text !== 'string' || !isRecord(a.model)) return null;
    const { provider, model } = a.model;
    if (typeof provider !== 'string' || typeof model !== 'string') return null;
    if (!COUNCIL_NAME.test(provider) || !COUNCIL_NAME.test(model)) return null;
    advisors.push({ role: a.role, model: { provider, model }, text: a.text, letter: a.letter });
  }
  const reviewers: CouncilTextOutput['reviewers'] = [];
  for (const r of raw.reviewers) {
    if (!isRecord(r) || !isOneOf(COUNCIL_ROLES, r.reviewerRole) || typeof r.text !== 'string') return null;
    reviewers.push({ reviewerRole: r.reviewerRole, text: r.text });
  }
  return { framedQuestion: raw.framedQuestion, advisors, reviewers, chairmanVerdict: raw.chairmanVerdict };
}

/**
 * Gate 1 over every model-written string in a council output (framedQuestion,
 * each advisor and reviewer text, chairmanVerdict). Strings with a short-form
 * marker (Id., supra, "at 5") are checked one at a time so a neighbour cannot
 * supply their antecedent; the rest go in one batch. The first non-clean result
 * stops the run.
 *
 * Any veto, pending verdict, gate error, throw or malformed output withholds the
 * WHOLE output (withheldCouncilOutput): nothing is rewritten, nothing partial is
 * released. The caller sends, saves and renders `output` only. Never throws.
 */
export async function gateCouncilOutput(
  raw: unknown,
  opts: { verify: VerifyFn; logError?: VerificationErrorLogger },
): Promise<GatedCouncil> {
  const log = makeFailureLogger(opts.logError);
  const withheld = (reason: string, message: string, verification: SseVerificationResult): GatedCouncil => {
    const vetoed = reason === 'veto' || reason === 'whole_draft_veto';
    return {
      output: withheldCouncilOutput(message),
      verification: clientSafeVerification(vetoed ? { ...verification, hasVetoes: true } : verification),
      withheld: true,
      withheldReason: reason,
    };
  };

  try {
    const council = normalizeCouncil(raw);
    if (!council) {
      const v = errorResult('malformed council output');
      log('council_malformed', v.error);
      return withheld('malformed_output', WITHHELD_MESSAGE, v);
    }

    const parts = [
      council.framedQuestion,
      ...council.advisors.map((a) => a.text),
      ...council.reviewers.map((r) => r.text),
      council.chairmanVerdict,
    ];
    const unique = [...new Set(parts)];
    const solo = unique.filter((s) => SHORT_FORM_RE.test(s));
    const batch = unique.filter((s) => !SHORT_FORM_RE.test(s));
    if (solo.length > MAX_SOLO_CHECKS) {
      const v = errorResult('too many short-form fields');
      log('council_verify', v.error);
      return withheld('verification_error', WITHHELD_MESSAGE, v);
    }

    const results: SseVerificationResult[] = [];
    const checks = [...solo, ...(batch.length ? [batch.join('\n\n')] : [])];
    for (const text of checks) {
      const r = await safeVerify(opts.verify, text);
      if (r.error) log('council_verify', r.error);
      results.push(r);
      if (uncleanOutcome(r)) break;
    }

    const merged = mergeResults(results);
    const bad = uncleanOutcome(merged);
    if (bad) return withheld(bad.reason, bad.message, merged);
    return {
      output: council,
      verification: clientSafeVerification(merged),
      withheld: false,
      withheldReason: null,
    };
  } catch (err: any) {
    log('council_internal_error', err);
    return withheld('internal_error', WITHHELD_MESSAGE, errorResult('internal error'));
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
