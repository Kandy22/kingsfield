/**
 * Dual retrieval for Kingsfield:
 *  1. File Search (Ask-the-Manual) — private uploaded corpora
 *  2. URL Context (Chat-with-Docs) — official public pages
 *
 * Neither replaces CourtListener four-gate for case citations.
 */
import { GoogleGenAI, HarmCategory, HarmBlockThreshold } from "@google/genai";

function client(): GoogleGenAI {
  const key = process.env.GEMINI_API_KEY?.trim();
  if (!key) throw new Error("GEMINI_API_KEY is not configured");
  return new GoogleGenAI({ apiKey: key });
}

const MODEL = "gemini-2.5-flash";

const safetySettings = [
  { category: HarmCategory.HARM_CATEGORY_HARASSMENT, threshold: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE },
  { category: HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE },
  { category: HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE },
  { category: HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE },
];

function delay(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

// ─── URL Context (chat-with-docs) ───────────────────────────────────────────

export async function chatWithUrlContext(
  prompt: string,
  urls: string[],
): Promise<{ text: string; urlMetadata?: unknown[] }> {
  const ai = client();
  const cleaned = urls.map((u) => u.trim()).filter(Boolean).slice(0, 20);
  const urlList = cleaned.join("\n");
  const fullPrompt = urlList
    ? `${prompt}\n\nRelevant official source URLs (use urlContext to fetch and cite them):\n${urlList}\n\nAnswer from those sources. Name which URL supports each claim. Do not invent statutory text.`
    : prompt;

  const response = await ai.models.generateContent({
    model: MODEL,
    contents: [{ role: "user", parts: [{ text: fullPrompt }] }],
    config: { tools: [{ urlContext: {} }], safetySettings },
  });

  const candidate = response.candidates?.[0] as
    | {
        urlContextMetadata?: { urlMetadata?: unknown[] };
      }
    | undefined;
  const urlMetadata = candidate?.urlContextMetadata?.urlMetadata;

  return { text: response.text ?? "", urlMetadata };
}

/** Short starter questions for a URL pack (no tools — JSON only). */
export async function suggestQuestionsFromUrls(
  urls: string[],
): Promise<string[]> {
  const cleaned = urls.map((u) => u.trim()).filter(Boolean).slice(0, 20);
  if (cleaned.length === 0) return [];
  const ai = client();
  const prompt = `Based on the following legal / government documentation URLs, return 3–4 concise questions a lawyer or pro se litigant might ask to explore them. Return ONLY JSON: {"suggestions":["q1","q2",...]}\n\nURLs:\n${cleaned.join("\n")}`;

  const response = await ai.models.generateContent({
    model: MODEL,
    contents: [{ role: "user", parts: [{ text: prompt }] }],
    config: {
      safetySettings,
      responseMimeType: "application/json",
    },
  });

  return parseSuggestionList(response.text ?? "");
}

// ─── File Search (ask-the-manual) ───────────────────────────────────────────

export async function createManualStore(displayName: string): Promise<string> {
  const ai = client();
  const store = await ai.fileSearchStores.create({
    config: { displayName: displayName.slice(0, 120) },
  });
  if (!store.name) throw new Error("Failed to create file search store");
  return store.name;
}

/**
 * Upload bytes into an existing File Search store. Polls until the operation completes.
 */
export async function uploadBytesToManualStore(params: {
  ragStoreName: string;
  bytes: Buffer;
  filename: string;
  mimeType?: string;
}): Promise<void> {
  const ai = client();
  const mime =
    params.mimeType ||
    mimeFromFilename(params.filename) ||
    "application/octet-stream";

  // Node 20+ File is accepted by the Gemini SDK (same as browser File).
  const file = new File([new Uint8Array(params.bytes)], params.filename, {
    type: mime,
  });

  let op = await ai.fileSearchStores.uploadToFileSearchStore({
    fileSearchStoreName: params.ragStoreName,
    file,
    config: { displayName: params.filename },
  });

  const deadline = Date.now() + 5 * 60_000;
  while (!op.done) {
    if (Date.now() > deadline) {
      throw new Error("Timed out waiting for File Search indexing");
    }
    await delay(2500);
    op = await ai.operations.get({ operation: op });
  }
  if (op.error) {
    throw new Error(
      `File Search upload failed: ${JSON.stringify(op.error)}`,
    );
  }
}

export async function askUploadedManual(
  ragStoreName: string,
  query: string,
): Promise<{ text: string; groundingChunks: unknown[] }> {
  const ai = client();
  const response = await ai.models.generateContent({
    model: MODEL,
    contents:
      query.trim() +
      "\n\nInstructions: Answer from the uploaded documents only. " +
      "Pinpoint relevant sections in the response. Do not invent parties, holdings, or citations. " +
      "If the corpus does not contain the answer, say so.",
    config: {
      tools: [{ fileSearch: { fileSearchStoreNames: [ragStoreName] } }],
      safetySettings,
    },
  });
  const groundingChunks =
    response.candidates?.[0]?.groundingMetadata?.groundingChunks ?? [];
  return { text: response.text ?? "", groundingChunks };
}

export async function suggestQuestionsFromManual(
  ragStoreName: string,
): Promise<string[]> {
  const ai = client();
  try {
    const response = await ai.models.generateContent({
      model: MODEL,
      contents:
        "From the uploaded legal documents, generate 4 short practical questions a lawyer might ask. " +
        'Return ONLY a JSON array of strings, e.g. ["q1","q2"]. Do not invent document contents you did not see.',
      config: {
        tools: [{ fileSearch: { fileSearchStoreNames: [ragStoreName] } }],
        safetySettings,
      },
    });
    return parseSuggestionList(response.text ?? "");
  } catch (err) {
    console.warn("[proSeGemini] suggestQuestionsFromManual failed", err);
    return [];
  }
}

export async function deleteManualStore(ragStoreName: string): Promise<void> {
  const ai = client();
  await ai.fileSearchStores.delete({
    name: ragStoreName,
    config: { force: true },
  });
}

// ─── helpers ────────────────────────────────────────────────────────────────

function mimeFromFilename(name: string): string | null {
  const ext = name.split(".").pop()?.toLowerCase();
  if (ext === "pdf") return "application/pdf";
  if (ext === "docx")
    return "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
  if (ext === "doc") return "application/msword";
  if (ext === "txt") return "text/plain";
  if (ext === "md") return "text/markdown";
  return null;
}

function parseSuggestionList(raw: string): string[] {
  let s = raw.trim();
  const fence = s.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (fence) s = fence[1].trim();
  try {
    const parsed = JSON.parse(s) as unknown;
    if (Array.isArray(parsed)) {
      return parsed.filter((x): x is string => typeof x === "string").slice(0, 6);
    }
    if (parsed && typeof parsed === "object" && "suggestions" in parsed) {
      const arr = (parsed as { suggestions: unknown }).suggestions;
      if (Array.isArray(arr)) {
        return arr.filter((x): x is string => typeof x === "string").slice(0, 6);
      }
    }
    if (parsed && typeof parsed === "object" && "questions" in parsed) {
      const arr = (parsed as { questions: unknown }).questions;
      if (Array.isArray(arr)) {
        return arr.filter((x): x is string => typeof x === "string").slice(0, 6);
      }
    }
  } catch {
    /* fall through */
  }
  return [];
}
