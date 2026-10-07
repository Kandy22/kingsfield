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
  };
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
