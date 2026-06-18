/**
 * LLM Council trigger detection.
 *
 * The Council is expensive (~11 LLM calls per session). It must only fire
 * when the user actually wants it.
 *
 * Three trigger paths:
 *   1. Explicit phrase ("council this", "war room this", etc.) — fires.
 *   2. Sidebar "Council" tab — explicit user click — fires.
 *   3. Strong "should I X or Y" question with stakes — *suggests* the
 *      council. Does NOT auto-fire. UI shows a "Run the council on this?"
 *      prompt; user confirms.
 */

const HARD_TRIGGERS = [
  /\bcouncil this\b/i,
  /\brun the council\b/i,
  /\bwar[\s-]?room this\b/i,
  /\bpressure[\s-]?test this\b/i,
  /\bstress[\s-]?test this\b/i,
  /\bdebate this\b/i,
];

const SOFT_TRIGGERS = [
  /should I \w+ or \w+/i,
  /which option/i,
  /what would you do/i,
  /is this the right move/i,
  /validate this/i,
  /multiple perspectives/i,
  /can'?t decide/i,
  /torn between/i,
];

const NEGATIVE_SIGNALS = [
  /\b(what is|define|spell|capital of|how do you spell)\b/i,
  /^(yes|no|maybe|ok|thanks)\b/i,
];

export type TriggerVerdict =
  | { kind: 'fire'; reason: 'hard-phrase' | 'sidebar' }
  | { kind: 'suggest'; reason: string }
  | { kind: 'skip' };

export function detectTrigger(message: string, source?: 'chat' | 'sidebar'): TriggerVerdict {
  if (source === 'sidebar') return { kind: 'fire', reason: 'sidebar' };

  if (HARD_TRIGGERS.some((re) => re.test(message))) {
    return { kind: 'fire', reason: 'hard-phrase' };
  }

  if (NEGATIVE_SIGNALS.some((re) => re.test(message))) {
    return { kind: 'skip' };
  }

  // Soft triggers fire only when combined with stakes signals.
  const hasSoft = SOFT_TRIGGERS.some((re) => re.test(message));
  const hasStakes =
    /\$[\d,]+/.test(message) ||
    /\b(client|filing|deadline|trial|deposition|settle|sanction)\b/i.test(message) ||
    message.length > 200;

  if (hasSoft && hasStakes) {
    return {
      kind: 'suggest',
      reason: 'Looks like a real decision — want me to run the council?',
    };
  }

  return { kind: 'skip' };
}
