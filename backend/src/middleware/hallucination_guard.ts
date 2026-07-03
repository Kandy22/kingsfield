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
  // Mike returns assistant messages with a `content` field that's either a
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
