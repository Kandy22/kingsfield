import "dotenv/config";
import express from "express";
import cors from "cors";
import Anthropic from "@anthropic-ai/sdk";
import { GoogleGenAI } from "@google/genai";
import { chatRouter } from "./routes/chat";
import { projectsRouter } from "./routes/projects";
import { projectChatRouter } from "./routes/projectChat";
import { documentsRouter } from "./routes/documents";
import { tabularRouter } from "./routes/tabular";
import { workflowsRouter } from "./routes/workflows";
import { userRouter } from "./routes/user";
import { downloadsRouter } from "./routes/downloads";
import { caseLawRouter } from "./routes/caseLaw";
import { buildRoutes } from "./routes/index";
import { createServerSupabase } from "./lib/supabase";
import type { GeminiClient } from "./llm-council/providers";

const app = express();
const PORT = process.env.PORT ?? 3001;

app.use(
  cors({
    origin: process.env.FRONTEND_URL ?? "http://localhost:3000",
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

app.use("/api", buildRoutes({
  anthropic,
  gemini,
  supabase,
  courtListenerToken: process.env.COURTLISTENER_TOKEN ?? "",
}));

app.get("/health", (_req, res) => res.json({ ok: true }));

app.listen(PORT, () => {
  console.log(`Mike backend running on port ${PORT}`);
});
