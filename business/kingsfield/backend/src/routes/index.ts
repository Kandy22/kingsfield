/**
 * HTTP routes for the LLM Council and the Crew.
 *
 * - POST /api/council          — run a full council session
 * - POST /api/council/detect   — check whether a chat message should trigger the council
 * - GET  /api/council/:id      — fetch a saved session
 * - GET  /api/council/:id/html — render the HTML report
 * - POST /api/crew/chat        — chat endpoint that runs the Crew silently
 *
 * The hallucination guard middleware is applied to /api/crew/chat so any
 * cite the Crew produces gets verified before it leaves the server.
 */

import { Router } from 'express';
import type { Request, Response } from 'express';
import type Anthropic from '@anthropic-ai/sdk';
import type { SupabaseClient } from '@supabase/supabase-js';
import type { GeminiClient } from '../llm-council/providers.js';
import { runLLMCouncil } from '../llm-council/orchestrator.js';
import { detectTrigger } from '../llm-council/triggers.js';
import { renderCouncilHTML, renderCouncilMarkdown } from '../llm-council/report.js';
import { runCrew } from '../crew/coordinator.js';

export interface RouteDeps {
  anthropic: Anthropic;
  gemini?: GeminiClient;
  supabase: SupabaseClient;
  courtListenerToken: string;
}

export function buildRoutes(deps: RouteDeps): Router {
  const r = Router();

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

  r.post('/crew/chat', async (req, res) => {
    try {
      const { userMessage, matterContext, documentName, documentText, jurisdiction } =
        req.body ?? {};
      const out = await runCrew(
        { userMessage, matterContext, documentName, documentText, jurisdiction },
        {
          llm: deps.anthropic,
          supabase: deps.supabase,
          courtListenerToken: deps.courtListenerToken,
        },
      );
      // The hallucination_guard middleware will scan `reply` for cites and
      // attach `__verification` to the response body before it ships.
      res.json({
        content: out.reply,
        crew_decision: out.trace.decision,
        roles_spawned: out.trace.rolesSpawned,
        authorities: out.authorities,
      });
    } catch (err: any) {
      console.error('[crew/chat] error', err);
      res.status(500).json({ error: err.message });
    }
  });

  return r;
}
