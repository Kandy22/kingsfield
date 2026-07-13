import { Router } from "express";
import { requireAuth } from "../middleware/auth";
import { createServerSupabase } from "../lib/supabase";
import { completeText } from "../lib/llm";
import { verifyDraft } from "../verification/pipeline";
import {
  assertAllowedHost,
  crawlStatutePage,
  findCorpusMatch,
  loadCorpusIndex,
} from "../lib/skills/statuteScanner";
import {
  askUploadedManual,
  chatWithUrlContext,
  createManualStore,
} from "../lib/proSeGemini";
import { getUserModelSettings } from "../lib/userSettings";

export const proSeRouter = Router();

// POST /pro-se/ask — statute/rules Q&A with four-gate verification
proSeRouter.post("/ask", requireAuth, async (req, res) => {
  const userId = res.locals.userId as string;
  const { question, jurisdiction = "colorado", sourceUrl } = req.body as {
    question?: string;
    jurisdiction?: string;
    sourceUrl?: string;
  };

  if (!question?.trim()) {
    return void res.status(400).json({ detail: "question is required" });
  }

  try {
    const db = createServerSupabase();
    const settings = await getUserModelSettings(userId, db);
    let context = loadCorpusIndex(jurisdiction);
    const match = findCorpusMatch(jurisdiction, question);
    if (match) context += `\n\n${match}`;
    if (sourceUrl) {
      const crawled = await crawlStatutePage(sourceUrl, jurisdiction);
      context += `\n\n${crawled.excerpt}`;
    }
    if (!context.trim()) {
      return void res.status(404).json({
        detail:
          "No statute corpus for this jurisdiction yet. Pass sourceUrl (allowlisted host) to seed context.",
      });
    }

    const answer = await completeText({
      model: settings.title_model ?? "gemini-2.5-flash",
      systemPrompt:
        "You are a pro se legal research assistant. Answer only from the provided statute corpus. Cite sections explicitly.",
      user: `Corpus:\n${context}\n\nQuestion: ${question.trim()}`,
      maxTokens: 2048,
    });

    const verification = await verifyDraft(answer, {
      courtListenerToken: process.env.COURTLISTENER_TOKEN ?? "",
      supabase: db,
      matter: { forum: jurisdiction, jurisdictionTier: "state-supreme" },
    });

    // The Skeptic has hard veto power — a vetoed draft is never released to
    // the user, per CLAUDE.md and pipeline.ts's own contract.
    res.json({
      answer: verification.hasVetoes ? null : answer,
      withheld: verification.hasVetoes,
      verification: {
        hasVetoes: verification.hasVetoes,
        hasConditional: verification.hasConditional,
        verdicts: verification.verdicts,
      },
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Pro se ask failed";
    res.status(500).json({ detail: message });
  }
});

// POST /pro-se/chat-with-docs — chat-with-docs GAI template (URL context)
proSeRouter.post("/chat-with-docs", requireAuth, async (req, res) => {
  const { prompt, urls } = req.body as { prompt?: string; urls?: string[] };
  if (!prompt?.trim()) {
    return void res.status(400).json({ detail: "prompt is required" });
  }
  if (!urls || urls.length === 0) {
    return void res.status(400).json({ detail: "At least one url is required" });
  }
  let cleaned: string[];
  try {
    cleaned = urls.map((u) => {
      assertAllowedHost(u);
      return u;
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "URL not allowlisted";
    return void res.status(400).json({ detail: message });
  }

  try {
    const db = createServerSupabase();
    const result = await chatWithUrlContext(prompt.trim(), cleaned);
    const verification = await verifyDraft(result.text, {
      courtListenerToken: process.env.COURTLISTENER_TOKEN ?? "",
      supabase: db,
      matter: { forum: "General", jurisdictionTier: "district" },
    });
    res.json({
      text: verification.hasVetoes ? null : result.text,
      withheld: verification.hasVetoes,
      urlMetadata: result.urlMetadata,
      verification: {
        hasVetoes: verification.hasVetoes,
        hasConditional: verification.hasConditional,
        verdicts: verification.verdicts,
      },
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "chat-with-docs failed";
    res.status(500).json({ detail: message });
  }
});

// POST /pro-se/ask-manual — ask-the-manual GAI template (file search store)
proSeRouter.post("/ask-manual", requireAuth, async (req, res) => {
  const { question, ragStoreName, displayName } = req.body as {
    question?: string;
    ragStoreName?: string;
    displayName?: string;
  };
  if (!question?.trim()) {
    return void res.status(400).json({ detail: "question is required" });
  }

  try {
    const db = createServerSupabase();
    const store =
      ragStoreName?.trim() ||
      (displayName ? await createManualStore(displayName) : null);
    if (!store) {
      return void res.status(400).json({
        detail: "ragStoreName or displayName is required",
      });
    }

    const result = await askUploadedManual(store, question.trim());
    const verification = await verifyDraft(result.text, {
      courtListenerToken: process.env.COURTLISTENER_TOKEN ?? "",
      supabase: db,
      matter: { forum: "General", jurisdictionTier: "district" },
    });

    res.json({
      text: verification.hasVetoes ? null : result.text,
      withheld: verification.hasVetoes,
      ragStoreName: store,
      groundingChunks: result.groundingChunks,
      verification: {
        hasVetoes: verification.hasVetoes,
        hasConditional: verification.hasConditional,
        verdicts: verification.verdicts,
      },
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "ask-manual failed";
    res.status(500).json({ detail: message });
  }
});