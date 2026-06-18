/**
 * LLM Council — provider abstraction.
 *
 * Five advisors run on a deliberate mix of model providers so the
 * thinking is genuinely diverse, not five Claudes wearing different hats.
 *
 * Default routing (override per-deployment):
 *   Contrarian       → Claude Opus       (deep adversarial reasoning)
 *   First Principles → Gemini Pro        (different training, different priors)
 *   Expansionist     → Claude Sonnet     (creative, fast)
 *   Outsider         → Gemini Flash      (fewer priors = more "fresh eyes")
 *   Executor         → Claude Sonnet     (concrete, action-oriented)
 *   Chairman         → Claude Opus       (synthesis)
 *
 * If a user has not configured a Gemini key, the system falls back to
 * Claude across the board and logs a warning. The diversity benefit
 * degrades but the council still runs.
 */

import type Anthropic from '@anthropic-ai/sdk';

export type AdvisorRole =
  | 'contrarian'
  | 'first_principles'
  | 'expansionist'
  | 'outsider'
  | 'executor';

export type Provider = 'claude' | 'gemini';

export interface ModelChoice {
  provider: Provider;
  model: string;
}

export const DEFAULT_ROUTING: Record<AdvisorRole | 'chairman', ModelChoice> = {
  contrarian: { provider: 'claude', model: 'claude-opus-4-7' },
  first_principles: { provider: 'gemini', model: 'gemini-2.5-pro' },
  expansionist: { provider: 'claude', model: 'claude-sonnet-4-6' },
  outsider: { provider: 'gemini', model: 'gemini-2.5-flash' },
  executor: { provider: 'claude', model: 'claude-sonnet-4-6' },
  chairman: { provider: 'claude', model: 'claude-opus-4-7' },
};

export interface LLMClients {
  anthropic: Anthropic;
  /** Optional. If absent, gemini routes fall back to anthropic with a warning. */
  gemini?: GeminiClient;
}

/**
 * Minimal Gemini client interface — implement against @google/generative-ai
 * or the REST endpoint, whichever the deployment uses. Kept narrow so the
 * council code doesn't depend on a specific SDK version.
 */
export interface GeminiClient {
  generate(args: {
    model: string;
    system: string;
    user: string;
    maxTokens: number;
  }): Promise<string>;
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
  if (choice.provider === 'gemini') {
    if (clients.gemini) {
      return clients.gemini.generate({
        model: choice.model,
        system: turn.system,
        user: turn.user,
        maxTokens: turn.maxTokens ?? 2048,
      });
    }
    // Fallback: use Claude Opus when Gemini isn't configured.
    console.warn(
      `[llm-council] Gemini not configured; falling back to Claude Opus for ${choice.model}.`,
    );
    choice = { provider: 'claude', model: 'claude-opus-4-7' };
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
