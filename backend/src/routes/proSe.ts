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
  deleteManualStore,
  suggestQuestionsFromManual,
  suggestQuestionsFromUrls,
  uploadBytesToManualStore,
} from "../lib/proSeGemini";
import { getUserModelSettings } from "../lib/userSettings";
import { loadCurrentVersionBytes } from "../lib/chatTools";
import { ensureDocAccess } from "../lib/access";

export const proSeRouter = Router();

const MAX_URLS = 20;

/**
 * URL Context: allow any https URL (Gemini fetches; user-curated packs).
 * Local corpus crawl still uses assertAllowedHost (stricter).
 */
function cleanHttpsUrls(urls: string[]): string[] {
  const out: string[] = [];
  for (const raw of urls) {
    if (!raw?.trim()) continue;
    let u: URL;
    try {
      u = new URL(raw.trim());
    } catch {
      throw new Error(`Invalid URL: ${raw}`);
    }
    if (u.protocol !== "https:" && u.protocol !== "http:") {
      throw new Error(`Only http(s) URLs allowed: ${raw}`);
    }
    out.push(u.href);
    if (out.length >= MAX_URLS) break;
  }
  return out;
}

// ─── Corpus ask (local statute files + optional crawl) ──────────────────────

// POST /pro-se/ask
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
          "No statute corpus for this jurisdiction yet. Use “Chat with URL pack” (urlContext) or pass an allowlisted sourceUrl.",
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

    res.json({
      engine: "corpus",
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

// ─── URL Context engine (chat-with-docs) ────────────────────────────────────

// POST /pro-se/chat-with-docs — multi-URL pack + urlContext tool
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
    cleaned = cleanHttpsUrls(urls);
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Invalid URL";
    return void res.status(400).json({ detail: message });
  }
  if (cleaned.length === 0) {
    return void res.status(400).json({ detail: "No valid URLs" });
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
      engine: "url_context",
      text: verification.hasVetoes ? null : result.text,
      withheld: verification.hasVetoes,
      urls: cleaned,
      urlMetadata: result.urlMetadata ?? [],
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

// POST /pro-se/url-suggestions — starter questions for a URL pack
proSeRouter.post("/url-suggestions", requireAuth, async (req, res) => {
  const { urls } = req.body as { urls?: string[] };
  if (!urls?.length) {
    return void res.status(400).json({ detail: "urls required" });
  }
  let cleaned: string[];
  try {
    cleaned = cleanHttpsUrls(urls);
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Invalid URL";
    return void res.status(400).json({ detail: message });
  }
  try {
    const suggestions = await suggestQuestionsFromUrls(cleaned);
    res.json({ engine: "url_context", suggestions, urls: cleaned });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "suggestions failed";
    res.status(500).json({ detail: message });
  }
});

// ─── File Search engine (ask-the-manual) ────────────────────────────────────

// POST /pro-se/manual-store — create empty store
proSeRouter.post("/manual-store", requireAuth, async (req, res) => {
  const { displayName } = req.body as { displayName?: string };
  const name =
    displayName?.trim() ||
    `kingsfield-binder-${res.locals.userId}-${Date.now()}`;
  try {
    const ragStoreName = await createManualStore(name);
    res.status(201).json({ engine: "file_search", ragStoreName, displayName: name });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "create store failed";
    res.status(500).json({ detail: message });
  }
});

// POST /pro-se/manual-store/upload — index a Kingsfield document into the store
proSeRouter.post("/manual-store/upload", requireAuth, async (req, res) => {
  const userId = res.locals.userId as string;
  const userEmail = res.locals.userEmail as string;
  const { ragStoreName, documentId } = req.body as {
    ragStoreName?: string;
    documentId?: string;
  };
  if (!ragStoreName?.trim() || !documentId?.trim()) {
    return void res
      .status(400)
      .json({ detail: "ragStoreName and documentId are required" });
  }

  try {
    const db = createServerSupabase();
    const { data: doc } = await db
      .from("documents")
      .select("id, user_id, project_id, filename, file_type, status")
      .eq("id", documentId)
      .maybeSingle();
    if (!doc) return void res.status(404).json({ detail: "Document not found" });

    const access = await ensureDocAccess(
      doc as { user_id: string; project_id: string | null },
      userId,
      userEmail,
      db,
    );
    if (!access.ok) {
      return void res.status(403).json({ detail: "No access to document" });
    }

    const current = await loadCurrentVersionBytes(documentId, db);
    if (!current) {
      return void res.status(404).json({ detail: "Document has no readable bytes" });
    }

    const filename =
      (doc as { filename?: string }).filename || "document.pdf";

    await uploadBytesToManualStore({
      ragStoreName: ragStoreName.trim(),
      bytes: Buffer.from(current.bytes),
      filename,
    });

    res.json({
      engine: "file_search",
      ok: true,
      ragStoreName: ragStoreName.trim(),
      documentId,
      filename,
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "upload to store failed";
    console.error("[pro-se/manual-store/upload]", err);
    res.status(500).json({ detail: message });
  }
});

// POST /pro-se/ask-manual — query a File Search store
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
      engine: "file_search",
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

// POST /pro-se/manual-suggestions
proSeRouter.post("/manual-suggestions", requireAuth, async (req, res) => {
  const { ragStoreName } = req.body as { ragStoreName?: string };
  if (!ragStoreName?.trim()) {
    return void res.status(400).json({ detail: "ragStoreName required" });
  }
  try {
    const suggestions = await suggestQuestionsFromManual(ragStoreName.trim());
    res.json({ engine: "file_search", suggestions });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "suggestions failed";
    res.status(500).json({ detail: message });
  }
});

// DELETE /pro-se/manual-store — best-effort cleanup
proSeRouter.delete("/manual-store", requireAuth, async (req, res) => {
  const { ragStoreName } = req.body as { ragStoreName?: string };
  if (!ragStoreName?.trim()) {
    return void res.status(400).json({ detail: "ragStoreName required" });
  }
  try {
    await deleteManualStore(ragStoreName.trim());
    res.status(204).send();
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "delete failed";
    res.status(500).json({ detail: message });
  }
});
