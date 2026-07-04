// Minimal OpenAI-compatible chat client for providers that speak the
// /chat/completions dialect — DeepSeek (api.deepseek.com) and Moonshot/Kimi
// (api.moonshot.ai). No SDK dependency; the council only needs one-shot
// system+user → text.

import type { TextGenClient } from "../llm-council/providers.js";

export function makeOpenAICompatClient(
  baseURL: string,
  apiKey: string,
  label: string,
): TextGenClient {
  return {
    async generate({ model, system, user, maxTokens }) {
      const res = await fetch(`${baseURL.replace(/\/$/, "")}/chat/completions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${apiKey}`,
        },
        body: JSON.stringify({
          model,
          max_tokens: maxTokens,
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
