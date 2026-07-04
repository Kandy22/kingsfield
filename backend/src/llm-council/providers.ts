/**
 * LLM Council — provider abstraction.
 *
 * Five advisors run on a deliberate mix of model providers so the
 * thinking is genuinely diverse, not five Claudes wearing different hats.
 * Four model families: Anthropic, Google, DeepSeek, Moonshot (Kimi).
 *
 * Default routing (override per-deployment):
 *   Contrarian       → Claude Opus 4.8   (deep adversarial reasoning)
 *   First Principles → DeepSeek V4 Pro   (strong reasoner, different priors)
 *   Expansionist     → Gemini 3.1 Pro    (creative breadth, different training)
 *   Outsider         → Kimi K2.6         (literally the outsider — fourth lab, fresh eyes)
 *   Executor         → Claude Sonnet     (concrete, action-oriented)
 *   Chairman         → Claude Opus 4.8   (synthesis)
 *
 * Any provider without a configured key falls back to Claude with a logged
 * warning. The diversity benefit degrades but the council still runs.
 */

import type Anthropic from '@anthropic-ai/sdk';

export type AdvisorRole =
  | 'contrarian'
  | 'first_principles'
  | 'expansionist'
  | 'outsider'
  | 'executor';

export type Provider = 'claude' | 'gemini' | 'deepseek' | 'kimi';

export interface ModelChoice {
  provider: Provider;
  model: string;
}

// NOTE (2026-07): DeepSeek's legacy IDs (deepseek-reasoner/deepseek-chat)
// hard-deprecate 2026-07-24 — use the v4 IDs only. Kimi's k2 line was
// discontinued 2026-05-25; kimi-k2.6 is the current flagship.
export const DEFAULT_ROUTING: Record<AdvisorRole | 'chairman', ModelChoice> = {
  contrarian: { provider: 'claude', model: 'claude-opus-4-8' },
  first_principles: { provider: 'deepseek', model: 'deepseek-v4-pro' },
  expansionist: { provider: 'gemini', model: 'gemini-3.1-pro-preview' },
  outsider: { provider: 'kimi', model: 'kimi-k2.6' },
  executor: { provider: 'claude', model: 'claude-sonnet-4-6' },
  chairman: { provider: 'claude', model: 'claude-opus-4-8' },
};

/**
 * Minimal text-generation client interface. Implemented for Gemini via
 * @google/genai and for DeepSeek/Kimi via their OpenAI-compatible REST
 * endpoints (see lib/openaiCompat.ts). Kept narrow so the council code
 * doesn't depend on any specific SDK version.
 */
export interface TextGenClient {
  generate(args: {
    model: string;
    system: string;
    user: string;
    maxTokens: number;
  }): Promise<string>;
}

/** Back-compat alias — index.ts and routes type against GeminiClient. */
export type GeminiClient = TextGenClient;

export interface LLMClients {
  anthropic: Anthropic;
  /** Optional. Any absent provider falls back to anthropic with a warning. */
  gemini?: TextGenClient;
  deepseek?: TextGenClient;
  kimi?: TextGenClient;
}

export interface ChatTurn {
  system: string;
  user: string;
  maxTokens?: number;
}

export async function callModel(
  choice: ModelChoice,
  turn: ChatTurn,
  clients: LLMClients,
): Promise<string> {
  if (choice.provider !== 'claude') {
    const client = clients[choice.provider];
    if (client) {
      return client.generate({
        model: choice.model,
        system: turn.system,
        user: turn.user,
        maxTokens: turn.maxTokens ?? 2048,
      });
    }
    // Fallback: use Claude Opus when the provider isn't configured.
    console.warn(
      `[llm-council] ${choice.provider} not configured; falling back to Claude Opus for ${choice.model}.`,
    );
    choice = { provider: 'claude', model: 'claude-opus-4-8' };
  }
  const resp = await clients.anthropic.messages.create({
    model: choice.model,
    max_tokens: turn.maxTokens ?? 2048,
    system: turn.system,
    messages: [{ role: 'user', content: turn.user }],
  });
  return (resp.content ?? [])
    .filter((b: any) => b.type === 'text')
    .map((b: any) => b.text)
    .join('\n');
}
