/**
 * HTTP routes for the LLM Council and the Crew.
 *
 * - POST /api/council          — run a full council session
 * - POST /api/council/detect   — check whether a chat message should trigger the council
 * - GET  /api/council/:id      — fetch a saved session
 * - GET  /api/council/:id/html — render the HTML report
 * - POST /api/crew/chat        — chat endpoint that runs the Crew silently
 * - GET  /api/research/case-law — proxy CourtListener opinion search
 *
 * The hallucination guard middleware is applied to /api/crew/chat so any
 * cite the Crew produces gets verified before it leaves the server.
 */

import { Router } from 'express';
import type { Request, Response } from 'express';
import { mediaRouter } from './media.js';
import type Anthropic from '@anthropic-ai/sdk';
import type { SupabaseClient } from '@supabase/supabase-js';
import type { GeminiClient } from '../llm-council/providers.js';
import { runLLMCouncil } from '../llm-council/orchestrator.js';
import { detectTrigger } from '../llm-council/triggers.js';
import { renderCouncilHTML, renderCouncilMarkdown } from '../llm-council/report.js';
import { runCrew } from '../crew/coordinator.js';
import { MOCK_ENABLED, MOCK_COUNCIL, MOCK_CREW } from '../lib/mock-llm.js';
import { runDocketWatcher, runPortfolioSweep } from '../services/docket-watcher/index.js';
import { runIpRenewalWatcher } from '../services/ip-renewal-watcher/index.js';
import { loadActiveVersion } from '../lib/documentVersions.js';
import { downloadFile } from '../lib/storage.js';
import { extractPdfText } from '../lib/chatTools.js';
import { requireAuth } from '../middleware/auth.js';
import { getUserModelSettings } from '../lib/userSettings.js';
import { runCaseExtraction } from '../lib/caseIntelligence.js';

/** In-memory copy of the court-list snapshot (loaded once per process;
 *  restart the server after re-running scripts/fetch-courts.mjs). */
interface CachedCourt {
  id: string;
  full_name: string;
  short_name: string;
  citation_string: string;
  jurisdiction: string;
  in_use: boolean;
}
let courtsCache: { fetchedAt: number; courts: CachedCourt[] } | null = null;

/**
 * Fetch and extract text from one or more uploaded documents.
 * Looks up the active version's storage path, downloads from R2,
 * and extracts text using pdfjs (PDF) or mammoth (DOCX).
 */
async function fetchDocumentTexts(
  documentIds: string[],
  db: SupabaseClient,
): Promise<{ name: string; text: string }[]> {
  const results: { name: string; text: string }[] = [];
  for (const docId of documentIds) {
    try {
      const { data: doc } = await (db as any)
        .from('documents')
        .select('filename, current_version_id')
        .eq('id', docId)
        .single();
      if (!doc) continue;

      const version = await loadActiveVersion(docId, db as any);
      if (!version) continue;

      const raw = await downloadFile(version.storage_path);
      if (!raw) continue;

      const filename = (doc.filename as string) ?? 'document';
      const ext = filename.split('.').pop()?.toLowerCase() ?? '';
      let text = '';

      if (ext === 'pdf') {
        text = await extractPdfText(raw);
      } else if (ext === 'docx' || ext === 'doc') {
        const mammoth = await import('mammoth');
        const result = await mammoth.extractRawText({ buffer: Buffer.from(raw) });
        text = result.value;
      }

      if (text.trim()) {
        results.push({ name: filename, text: text.slice(0, 40000) }); // cap at 40k chars
      }
    } catch (err: any) {
      console.error(`[crew/chat] Failed to extract text from document ${docId}:`, err?.message);
    }
  }
  return results;
}

export interface RouteDeps {
  anthropic: Anthropic;
  gemini?: GeminiClient;
  supabase: SupabaseClient;
  courtListenerToken: string;
}

export function buildRoutes(deps: RouteDeps): Router {
  const r = Router();

  // Media — audio/video assets served with range-request support.
  // No auth required so the player works on public-facing pages.
  r.use('/media', mediaRouter);

  // ── Analytics / Case Intelligence ──────────────────────────────────────
  // The extraction agent strips an uploaded document into structured case
  // facts (entities, allegations, defenses, authorities, rarity) that power
  // the Analytics connection graph + allegation/defense/authority clusters.

  // GET /api/analytics — all extractions for the user (optionally by project)
  r.get('/analytics', requireAuth, async (_req: Request, res: Response) => {
    const userId = res.locals.userId as string;
    const projectId = _req.query.projectId as string | undefined;
    let q = deps.supabase
      .from('case_intelligence')
      .select('*')
      .eq('user_id', userId)
      .order('updated_at', { ascending: false });
    if (projectId) q = q.eq('project_id', projectId);
    const { data, error } = await q;
    if (error) return void res.status(500).json({ detail: error.message });
    res.json({ extractions: data ?? [] });
  });

  // GET /api/analytics/documents — ready documents the user can analyze
  r.get('/analytics/documents', requireAuth, async (_req: Request, res: Response) => {
    const userId = res.locals.userId as string;
    const { data, error } = await deps.supabase
      .from('documents')
      .select('id, filename, project_id, created_at')
      .eq('user_id', userId)
      .eq('status', 'ready')
      .order('created_at', { ascending: false })
      .limit(200);
    if (error) return void res.status(500).json({ detail: error.message });
    // Flag which already have an extraction so the UI can show status.
    const ids = (data ?? []).map((d) => (d as { id: string }).id);
    const analyzed = new Set<string>();
    if (ids.length) {
      const { data: intel } = await deps.supabase
        .from('case_intelligence')
        .select('document_id')
        .in('document_id', ids);
      for (const row of intel ?? [])
        analyzed.add((row as { document_id: string }).document_id);
    }
    res.json({
      documents: (data ?? []).map((d) => ({
        ...(d as Record<string, unknown>),
        analyzed: analyzed.has((d as { id: string }).id),
      })),
    });
  });

  // POST /api/analytics/extract — run the extraction agent on one document
  r.post('/analytics/extract', requireAuth, async (req: Request, res: Response) => {
    const userId = res.locals.userId as string;
    const { documentId, projectId } = req.body ?? {};
    if (!documentId || typeof documentId !== 'string')
      return void res.status(400).json({ detail: 'documentId is required' });
    try {
      const settings = await getUserModelSettings(userId, deps.supabase as any);
      const result = await runCaseExtraction({
        documentId,
        userId,
        projectId: projectId ?? null,
        model: settings.tabular_model,
        apiKeys: settings.api_keys,
        db: deps.supabase as any,
      });
      if (!result.ok) return void res.status(422).json({ detail: result.error });
      res.json({ extraction: result.row });
    } catch (err: any) {
      console.error('[analytics/extract] error', err);
      res.status(500).json({ detail: err?.message ?? 'Extraction failed' });
    }
  });

  r.post('/council/detect', (req, res) => {
    const { message, source } = req.body ?? {};
    if (typeof message !== 'string') {
      return res.status(400).json({ error: 'message required' });
    }
    res.json(detectTrigger(message, source));
  });

  r.post('/council', async (req, res) => {
    try {
      const { rawQuestion, context, projectId } = req.body ?? {};
      if (typeof rawQuestion !== 'string' || rawQuestion.length < 10) {
        return res.status(400).json({ error: 'rawQuestion required' });
      }
      if (MOCK_ENABLED) {
        console.log('[council] MOCK_LLM=true — returning stub response');
        return res.json(MOCK_COUNCIL);
      }
      const out = await runLLMCouncil(
        { rawQuestion, context },
        { anthropic: deps.anthropic, gemini: deps.gemini },
        deps.supabase,
        projectId,
      );
      res.json(out);
    } catch (err: any) {
      console.error('[council] error', err);
      res.status(500).json({ error: err.message });
    }
  });

  r.get('/council/:id', async (req, res) => {
    const { data, error } = await deps.supabase
      .from('llm_council_sessions')
      .select('*')
      .eq('id', req.params.id)
      .single();
    if (error || !data) return res.status(404).json({ error: 'not found' });
    res.json(data);
  });

  r.get('/council/:id/html', async (req, res) => {
    const { data, error } = await deps.supabase
      .from('llm_council_sessions')
      .select('*')
      .eq('id', req.params.id)
      .single();
    if (error || !data) return res.status(404).send('not found');
    const html = renderCouncilHTML({
      framedQuestion: data.framed_question,
      advisors: data.advisors,
      reviewers: data.reviewers,
      chairmanVerdict: data.chairman_verdict,
    });
    res.type('html').send(html);
  });

  r.get('/council/:id/markdown', async (req, res) => {
    const { data, error } = await deps.supabase
      .from('llm_council_sessions')
      .select('*')
      .eq('id', req.params.id)
      .single();
    if (error || !data) return res.status(404).send('not found');
    const md = renderCouncilMarkdown({
      framedQuestion: data.framed_question,
      advisors: data.advisors,
      reviewers: data.reviewers,
      chairmanVerdict: data.chairman_verdict,
    });
    res.type('text/markdown').send(md);
  });

  // ── Case Law search (CourtListener proxy) ─────────────────────────────────

  /**
   * GET /api/research/case-law?q=...&jurisdiction=...
   * Proxies a full-text opinion search to CourtListener so the frontend
   * can display results without exposing the API token to the browser.
   * Returns { count, results[] } shaped for the Case Law page.
   */
  r.get('/research/case-law', async (req: Request, res: Response) => {
    const q = req.query.q as string | undefined;
    if (!q?.trim()) return res.status(400).json({ error: 'q required' });

    const params = new URLSearchParams({
      type: 'o',
      q: q.trim(),
      order_by: 'score desc',
      page_size: '20',
    });
    if (req.query.jurisdiction) {
      params.set('court', req.query.jurisdiction as string);
    }

    try {
      const clRes = await fetch(
        `https://www.courtlistener.com/api/rest/v4/search/?${params}`,
        { headers: { Authorization: `Token ${deps.courtListenerToken}` } },
      );
      if (clRes.status === 429) {
        // Surface the throttle honestly so the frontend can say "retry in Ns"
        // instead of pretending the backend is down.
        const body = await clRes.json().catch(() => ({}) as any);
        const wait = Number(String(body?.detail ?? '').match(/(\d+) seconds/)?.[1] ?? 30);
        return void res.status(429).json({ error: 'rate-limited', retry_in: wait });
      }
      if (!clRes.ok) throw new Error(`CourtListener ${clRes.status}`);
      const body = await clRes.json() as any;

      const results = (body.results ?? []).map((r: any) => ({
        id: r.cluster_id ?? r.id,
        case_name: r.caseName ?? r.case_name ?? '',
        citation: (r.citation ?? []).join(', ') || r.citeCount ? `${r.citation?.[0] ?? ''}` : '',
        date_filed: r.dateFiled ?? r.date_filed ?? '',
        court: r.court ?? r.court_id ?? '',
        absolute_url: r.absolute_url ?? '',
        snippet: r.snippet ?? '',
        status: r.status ?? '',
      }));

      res.json({ count: body.count ?? results.length, results });
    } catch (err: any) {
      console.error('[research/case-law] error', err);
      res.status(502).json({ error: err.message });
    }
  });

  /**
   * GET /api/research/courts
   * Full CourtListener court list (~3,400 courts incl. historical) for the
   * jurisdiction picker. Served from the snapshot at
   * backend/data/courtlistener-courts.json — the live /courts endpoint is
   * hard-capped at page_size=20 and throttled ~5/min, so it cannot be crawled
   * at request time. Rebuild the snapshot with `node scripts/fetch-courts.mjs`.
   */
  r.get('/research/courts', async (_req: Request, res: Response) => {
    try {
      if (!courtsCache) {
        const { readFile } = await import('node:fs/promises');
        const path = await import('node:path');
        // Server starts from backend/ (npm run dev), but tolerate repo root too.
        const candidates = [
          path.resolve(process.cwd(), 'data/courtlistener-courts.json'),
          path.resolve(process.cwd(), 'backend/data/courtlistener-courts.json'),
        ];
        let raw: any = null;
        for (const p of candidates) {
          try {
            raw = JSON.parse(await readFile(p, 'utf8'));
            break;
          } catch { /* try next */ }
        }
        if (!raw) throw new Error('snapshot not found');
        courtsCache = { fetchedAt: Date.now(), courts: raw.courts ?? [] };
      }
      res.json({ count: courtsCache.courts.length, courts: courtsCache.courts });
    } catch (err: any) {
      console.error('[research/courts] snapshot missing — run scripts/fetch-courts.mjs', err.message);
      res.status(503).json({ error: 'Court list snapshot not built yet' });
    }
  });

  r.post('/crew/chat', async (req, res) => {
    if (typeof req.body?.userMessage !== 'string' || !req.body.userMessage.trim()) {
      res.status(400).json({ error: 'userMessage (non-empty string) is required' });
      return;
    }
    // The frontend hook (useAssistantChat) reads a Server-Sent Events stream.
    // We open the SSE connection immediately, run the crew (which blocks while
    // hitting CourtListener + LLM), then flush the full reply as SSE events.
    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');
    res.flushHeaders();

    const sse = (obj: Record<string, unknown>) =>
      res.write(`data: ${JSON.stringify(obj)}\n\n`);

    if (MOCK_ENABLED) {
      console.log('[crew/chat] MOCK_LLM=true — returning stub response');
      const CHUNK = 80;
      const reply = MOCK_CREW.reply;
      for (let i = 0; i < reply.length; i += CHUNK) {
        sse({ type: 'content_delta', text: reply.slice(i, i + CHUNK) });
      }
      sse({ type: 'citations', citations: [] });
      res.write('data: [DONE]\n\n');
      res.end();
      return;
    }

    try {
      const { userMessage, matterContext, documentName, documentText, documentIds, jurisdiction } =
        req.body ?? {};
      // Use the model from the request body, falling back to Gemini Flash.
      const model = req.body?.model ?? process.env.DEFAULT_CREW_MODEL ?? 'gemini-2.5-flash';

      // Fetch and extract text from any attached documents.
      let resolvedDocText = documentText as string | undefined;
      let resolvedDocName = documentName as string | undefined;
      if (Array.isArray(documentIds) && documentIds.length > 0) {
        const docs = await fetchDocumentTexts(documentIds, deps.supabase);
        if (docs.length > 0) {
          resolvedDocName = docs.map((d) => d.name).join(', ');
          resolvedDocText = docs
            .map((d) => `=== ${d.name} ===\n${d.text}`)
            .join('\n\n');
        }
      }

      // Simple mode: if the crew decides not to spawn (short/casual message),
      // fall back to a single direct LLM call so the user still gets a reply.
      const out = await runCrew(
        { userMessage, matterContext, documentName: resolvedDocName, documentText: resolvedDocText, jurisdiction },
        {
          model,
          supabase: deps.supabase,
          courtListenerToken: deps.courtListenerToken,
        },
      );

      let reply = out.reply;

      // If the Coordinator decided to skip the crew, produce a simple answer.
      if (!reply) {
        const { completeText } = await import('../lib/llm/index.js');
        reply = await completeText({
          model,
          systemPrompt: 'You are Kingsfield, a plain-English legal AI. Answer concisely.',
          user: userMessage ?? '',
          maxTokens: 1024,
        });
      }

      // Stream the reply as content_delta events (one chunk per 80 chars so
      // the drip animation in the UI has something to animate).
      const CHUNK = 80;
      for (let i = 0; i < reply.length; i += CHUNK) {
        sse({ type: 'content_delta', text: reply.slice(i, i + CHUNK) });
      }

      // Send authority citations so the UI can render citation chips.
      const citations = out.authorities.map((a) => ({
        type: 'legal_authority',
        citation: a.citation,
        url: a.sourceUrl,
        relevance: a.relevanceNote,
      }));
      sse({ type: 'citations', citations });

      res.write('data: [DONE]\n\n');
      res.end();
    } catch (err: any) {
      console.error('[crew/chat] error', err);
      sse({ type: 'error', error: err.message });
      res.write('data: [DONE]\n\n');
      res.end();
    }
  });

  // ── Docket Watcher routes ──────────────────────────────────────────────

  /**
   * POST /api/projects/:id/docket/watch
   * Manual trigger: run the docket watcher for one matter now.
   * Body: { docket_id?, docket_number?, court?, since?, notify_email? }
   */
  r.post('/projects/:id/docket/watch', async (req: Request, res: Response) => {
    try {
      const matter_id = req.params.id;
      const { data: project, error: pErr } = await deps.supabase
        .from('projects')
        .select('id, name, docket_id, docket_number, court_code, notify_email')
        .eq('id', matter_id)
        .single();

      if (pErr || !project) {
        return res.status(404).json({ error: 'Matter not found' });
      }

      const body = req.body ?? {};
      const model = body.model ?? process.env.DEFAULT_CREW_MODEL ?? 'gemini-2.5-flash';

      const result = await runDocketWatcher(
        {
          matter_id: project.id,
          matter_name: project.name,
          docket_id: body.docket_id ?? project.docket_id ?? undefined,
          docket_number: body.docket_number ?? project.docket_number ?? undefined,
          court: body.court ?? project.court_code ?? undefined,
          since: body.since ?? undefined,
          notify_email: body.notify_email ?? project.notify_email ?? undefined,
        },
        {
          model,
          supabase: deps.supabase,
          courtListenerToken: deps.courtListenerToken,
          resendKey: process.env.RESEND_API_KEY,
        },
      );

      res.json(result);
    } catch (err: any) {
      console.error('[docket/watch] error', err);
      res.status(500).json({ error: err.message });
    }
  });

  /**
   * GET /api/projects/:id/docket/checks
   * List recent docket check results for a matter (latest 10).
   */
  r.get('/projects/:id/docket/checks', async (req: Request, res: Response) => {
    const { data, error } = await deps.supabase
      .from('docket_checks')
      .select('id, as_of, new_filings_count, critical_deadline_count, report_md, deadlines_json')
      .eq('project_id', req.params.id)
      .order('as_of', { ascending: false })
      .limit(10);

    if (error) return res.status(500).json({ error: error.message });
    res.json(data ?? []);
  });

  /**
   * POST /api/docket/sweep
   * Portfolio sweep: run the docket watcher for ALL active matters with
   * a docket configured. Intended to be called by a cron job or a scheduled
   * internal ping. Should be protected by an internal secret header in prod.
   */
  r.post('/docket/sweep', async (req: Request, res: Response) => {
    const secret = req.headers['x-sweep-secret'];
    if (process.env.SWEEP_SECRET && secret !== process.env.SWEEP_SECRET) {
      return res.status(403).json({ error: 'Forbidden' });
    }

    const model = req.body?.model ?? process.env.DEFAULT_CREW_MODEL ?? 'gemini-2.5-flash';

    try {
      const results = await runPortfolioSweep({
        model,
        supabase: deps.supabase,
        courtListenerToken: deps.courtListenerToken,
        resendKey: process.env.RESEND_API_KEY,
        defaultNotifyEmail: process.env.DEFAULT_NOTIFY_EMAIL,
      });
      res.json({ swept: results.length, results });
    } catch (err: any) {
      console.error('[docket/sweep] error', err);
      res.status(500).json({ error: err.message });
    }
  });

  // ── IP Renewal Watcher routes ──────────────────────────────────────────

  /**
   * POST /api/ip/renewal/sweep
   * Portfolio-wide IP renewal sweep. Checks all active assets with deadlines
   * in the next 90 days. Protected by SWEEP_SECRET header in prod.
   * Body: { windowDays?, notifyEmail?, model? }
   */
  r.post('/ip/renewal/sweep', async (req: Request, res: Response) => {
    const secret = req.headers['x-sweep-secret'];
    if (process.env.SWEEP_SECRET && secret !== process.env.SWEEP_SECRET) {
      return res.status(403).json({ error: 'Forbidden' });
    }

    const body = req.body ?? {};
    const model = body.model ?? process.env.DEFAULT_CREW_MODEL ?? 'gemini-2.5-flash';

    try {
      const result = await runIpRenewalWatcher({
        model,
        supabase: deps.supabase,
        resendKey: process.env.RESEND_API_KEY,
        notifyEmail: body.notifyEmail ?? process.env.DEFAULT_NOTIFY_EMAIL,
        windowDays: body.windowDays ? Number(body.windowDays) : undefined,
      });
      res.json(result);
    } catch (err: any) {
      console.error('[ip/renewal/sweep] error', err);
      res.status(500).json({ error: err.message });
    }
  });

  /**
   * POST /api/projects/:id/ip/renewal/check
   * Per-project IP renewal check. Scans assets for this project only.
   * Body: { windowDays?, notifyEmail?, model? }
   */
  r.post('/projects/:id/ip/renewal/check', async (req: Request, res: Response) => {
    try {
      const body = req.body ?? {};
      const model = body.model ?? process.env.DEFAULT_CREW_MODEL ?? 'gemini-2.5-flash';

      const { data: project, error: pErr } = await deps.supabase
        .from('projects')
        .select('id, name, notify_email')
        .eq('id', req.params.id)
        .single();

      if (pErr || !project) {
        return res.status(404).json({ error: 'Project not found' });
      }

      const result = await runIpRenewalWatcher({
        model,
        supabase: deps.supabase,
        resendKey: process.env.RESEND_API_KEY,
        notifyEmail: body.notifyEmail ?? project.notify_email ?? process.env.DEFAULT_NOTIFY_EMAIL,
        windowDays: body.windowDays ? Number(body.windowDays) : undefined,
        projectId: project.id,
      });

      res.json(result);
    } catch (err: any) {
      console.error('[ip/renewal/check] error', err);
      res.status(500).json({ error: err.message });
    }
  });

  /**
   * GET /api/ip/renewal/checks
   * Recent IP renewal check results (latest 10 portfolio-wide runs).
   */
  r.get('/ip/renewal/checks', async (_req: Request, res: Response) => {
    const { data, error } = await deps.supabase
      .from('ip_renewal_checks')
      .select('id, as_of, assets_checked, critical_count, deadlines_within_30, report_md')
      .order('as_of', { ascending: false })
      .limit(10);

    if (error) return res.status(500).json({ error: error.message });
    res.json(data ?? []);
  });

  /**
   * GET /api/ip/assets
   * List active IP assets with upcoming deadlines (next 90 days).
   * Query params: ?projectId=, ?windowDays=
   */
  r.get('/ip/assets', async (req: Request, res: Response) => {
    const windowDays = req.query.windowDays ? Number(req.query.windowDays) : 90;
    const today = new Date().toISOString().slice(0, 10);
    const windowEnd = new Date();
    windowEnd.setDate(windowEnd.getDate() + windowDays);
    const windowEndStr = windowEnd.toISOString().slice(0, 10);

    let query = deps.supabase
      .from('ip_assets')
      .select(
        'id, project_id, asset_type, title, registration_number, jurisdiction, ' +
        'status, next_deadline_date, next_deadline_type, owner_name',
      )
      .eq('status', 'active')
      .not('next_deadline_date', 'is', null)
      .lte('next_deadline_date', windowEndStr)
      .gte('next_deadline_date', today)
      .order('next_deadline_date', { ascending: true });

    if (req.query.projectId) {
      query = query.eq('project_id', req.query.projectId as string);
    }

    const { data, error } = await query;
    if (error) return res.status(500).json({ error: error.message });
    res.json(data ?? []);
  });

  return r;
}
