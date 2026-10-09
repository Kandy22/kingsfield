// Minimal OpenAI-compatible chat client for providers that speak the
// /chat/completions dialect — DeepSeek (api.deepseek.com) and Moonshot/Kimi
// (api.moonshot.ai). No SDK dependency; the council only needs one-shot
// system+user → text.

import type { TextGenClient } from "../llm-council/providers.js";
import { maxOutputTokensOverride } from "./llm/outputLimit.js";

export function makeOpenAICompatClient(
  baseURL: string,
  apiKey: string,
  label: string,
): TextGenClient {
  return {
    async generate({ model, system, user, maxTokens }) {
      // OpenRouter ignores the caller's reasoning unless it is in the request
      // body; send it explicitly, and default to "none" so hidden reasoning
      // tokens are not generated or billed (Mike d666189).
      const isOpenRouter = /(^|\/\/|\.)openrouter\.ai/i.test(baseURL);
      const res = await fetch(`${baseURL.replace(/\/$/, "")}/chat/completions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${apiKey}`,
        },
        body: JSON.stringify({
          model,
          max_tokens: maxOutputTokensOverride() ?? maxTokens,
          ...(isOpenRouter ? { reasoning: { effort: "none" } } : {}),
          messages: [
            { role: "system", content: system },
            { role: "user", content: user },
          ],
        }),
      });
      if (!res.ok) {
        const detail = await res.text().catch(() => "");
        throw new Error(`[${label}] ${res.status}: ${detail.slice(0, 300)}`);
      }
      const body = (await res.json()) as {
        choices?: { message?: { content?: string } }[];
      };
      return body.choices?.[0]?.message?.content ?? "";
    },
  };
}
