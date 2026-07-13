import "dotenv/config";
import express from "express";
import cors from "cors";
import Anthropic from "@anthropic-ai/sdk";
import { GoogleGenAI } from "@google/genai";
import { makeOpenAICompatClient } from "./lib/openaiCompat.js";
import { chatRouter } from "./routes/chat";
import { projectsRouter } from "./routes/projects";
import { projectChatRouter } from "./routes/projectChat";
import { documentsRouter } from "./routes/documents";
import { tabularRouter } from "./routes/tabular";
import { workflowsRouter } from "./routes/workflows";
import { userRouter } from "./routes/user";
import { downloadsRouter } from "./routes/downloads";
import { caseLawRouter } from "./routes/caseLaw";
import { proSeRouter } from "./routes/proSe";
import { buildRoutes } from "./routes/index";
import { createServerSupabase } from "./lib/supabase";
import type { GeminiClient } from "./llm-council/providers";

const app = express();
const PORT = process.env.PORT ?? 3001;

// A stray rejected promise (e.g. a fire-and-forget inside a route) must not
// take down the whole server — Node's default since v15 is to crash.
// Observed 2026-07-03: an async rejection out of the crew/chat path killed
// the process and every route went dark until manual restart.
process.on("unhandledRejection", (reason) => {
  console.error("[unhandledRejection]", reason);
});

// Allow the frontend on localhost AND on private LAN addresses (port 3000),
// so the app can be opened from another device on the same Wi-Fi (e.g. an iPad).
// Private ranges only — this does not expose the API to the public internet.
const LAN_ORIGIN =
  /^http:\/\/(localhost|127\.0\.0\.1|(?:192\.168|10|172\.(?:1[6-9]|2\d|3[01]))\.[\d.]+):3000$/;
app.use(
  cors({
    origin: (origin, cb) => {
      if (!origin || LAN_ORIGIN.test(origin) || origin === process.env.FRONTEND_URL) {
        cb(null, true);
      } else {
        cb(null, false);
      }
    },
    credentials: true,
  }),
);

app.use(express.json({ limit: "50mb" }));

app.use("/chat", chatRouter);
app.use("/projects", projectsRouter);
app.use("/projects/:projectId/chat", projectChatRouter);
app.use("/single-documents", documentsRouter);
app.use("/tabular-review", tabularRouter);
app.use("/workflows", workflowsRouter);
app.use("/user", userRouter);
app.use("/users", userRouter);
app.use("/download", downloadsRouter);
app.use("/case-law", caseLawRouter);
app.use("/pro-se", proSeRouter);

// Kingsfield — Crew + Council routes
const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
const supabase = createServerSupabase();

// Wire Gemini if key is present so the LLM Council gets real provider diversity.
let gemini: GeminiClient | undefined;
if (process.env.GEMINI_API_KEY) {
  const genai = new GoogleGenAI({ apiKey: process.env.GEMINI_API_KEY });
  gemini = {
    generate: async ({ model, system, user, maxTokens }) => {
      const response = await genai.models.generateContent({
        model,
        contents: [{ role: "user", parts: [{ text: user }] }],
        config: {
          systemInstruction: system,
          maxOutputTokens: maxTokens,
        },
      });
      return response.text ?? "";
    },
  };
}

// DeepSeek + Kimi (Moonshot) — OpenAI-compatible council advisors.
// Preference order per seat: native provider key → shared OPENROUTER_API_KEY
// (one key fills both seats) → Claude fallback with a warning. DEFAULT_ROUTING
// keeps native model IDs; when routed via OpenRouter they're remapped to OR slugs.
const OPENROUTER_BASE = "https://openrouter.ai/api/v1";
const openrouterKey = process.env.OPENROUTER_API_KEY;
const moonshotKey = process.env.MOONSHOT_API_KEY ?? process.env.KIMI_API_KEY;

/** Remap native model IDs to OpenRouter slugs on the way out. */
function withSlugMap(client: GeminiClient, map: Record<string, string>): GeminiClient {
  return {
    generate: (args) => client.generate({ ...args, model: map[args.model] ?? args.model }),
  };
}

const deepseek = process.env.DEEPSEEK_API_KEY
  ? makeOpenAICompatClient(
      process.env.DEEPSEEK_BASE_URL ?? "https://api.deepseek.com/v1",
      process.env.DEEPSEEK_API_KEY,
      "deepseek",
    )
  : openrouterKey
  ? withSlugMap(
      makeOpenAICompatClient(OPENROUTER_BASE, openrouterKey, "deepseek/openrouter"),
      { "deepseek-v4-pro": "deepseek/deepseek-v4-pro" },
    )
  : undefined;
const kimi = moonshotKey
  ? makeOpenAICompatClient(
      process.env.MOONSHOT_BASE_URL ?? "https://api.moonshot.ai/v1",
      moonshotKey,
      "kimi",
    )
  : openrouterKey
  ? withSlugMap(
      makeOpenAICompatClient(OPENROUTER_BASE, openrouterKey, "kimi/openrouter"),
      { "kimi-k2.6": "moonshotai/kimi-k2.6" },
    )
  : undefined;

app.use("/api", buildRoutes({
  anthropic,
  gemini,
  deepseek,
  kimi,
  supabase,
  courtListenerToken: process.env.COURTLISTENER_TOKEN ?? "",
}));

app.get("/health", (_req, res) => res.json({ ok: true }));

app.listen(PORT, () => {
  console.log(`Mike backend running on port ${PORT}`);
  if (!process.env.DEEPSEEK_API_KEY && !openrouterKey) {
    console.warn("[llm-council] no DeepSeek or OpenRouter key — First Principles seat uses Sonnet fallback.");
  } else if (!process.env.DEEPSEEK_API_KEY) {
    console.log("[llm-council] First Principles → DeepSeek V4 Pro via OpenRouter.");
  }
  if (!moonshotKey && !openrouterKey) {
    console.warn("[llm-council] no Moonshot or OpenRouter key — Outsider seat uses Sonnet fallback.");
  } else if (!moonshotKey) {
    console.log("[llm-council] Outsider → Kimi K2.6 via OpenRouter.");
  }
  if (!process.env.GEMINI_API_KEY) {
    console.warn("[llm-council] GEMINI_API_KEY unset — Expansionist seat uses Sonnet fallback.");
  }
});
