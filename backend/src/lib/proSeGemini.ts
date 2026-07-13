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

export async function chatWithUrlContext(
  prompt: string,
  urls: string[],
): Promise<{ text: string; urlMetadata?: unknown[] }> {
  const ai = client();
  const urlList = urls.filter(Boolean).join("\n");
  const fullPrompt = urlList
    ? `${prompt}\n\nRelevant URLs for context:\n${urlList}`
    : prompt;

  const response = await ai.models.generateContent({
    model: MODEL,
    contents: [{ role: "user", parts: [{ text: fullPrompt }] }],
    config: { tools: [{ urlContext: {} }], safetySettings },
  });

  const candidate = response.candidates?.[0];
  const urlMetadata = (candidate as { urlContextMetadata?: { urlMetadata?: unknown[] } })
    ?.urlContextMetadata?.urlMetadata;

  return { text: response.text ?? "", urlMetadata };
}

export async function askUploadedManual(
  ragStoreName: string,
  query: string,
): Promise<{ text: string; groundingChunks: unknown[] }> {
  const ai = client();
  const response = await ai.models.generateContent({
    model: MODEL,
    contents:
      query +
      " DO NOT ASK THE USER TO READ THE MANUAL — cite the relevant sections directly.",
    config: {
      tools: [{ fileSearch: { fileSearchStoreNames: [ragStoreName] } }],
    },
  });
  const groundingChunks =
    response.candidates?.[0]?.groundingMetadata?.groundingChunks ?? [];
  return { text: response.text ?? "", groundingChunks };
}

export async function createManualStore(displayName: string): Promise<string> {
  const ai = client();
  const store = await ai.fileSearchStores.create({ config: { displayName } });
  if (!store.name) throw new Error("Failed to create file search store");
  return store.name;
}