/**
 * Council Role: The Skeptic.
 *
 * The Skeptic does not draft, argue, or strategize. It verifies every cite
 * against the four-gate pipeline and votes verdicts. It has *hard veto*
 * power on unverified citations — no other role and no human convener can
 * override it. The only way past the Skeptic is to verify.
 *
 * This is the most important role in the system. If the Skeptic is
 * compromised, the whole anti-hallucination layer collapses.
 */

import type { GateVerdict, VerifyOptions } from '../verification/pipeline.js';
import { verifyDraft } from '../verification/pipeline.js';

export const SKEPTIC_SYSTEM_PROMPT = `
You are the Skeptic. You are the hallucination cop on the Kingsfield Council
of Experts. You do not draft, argue, or strategize. You verify.

Your job:
1. Identify every citation in the artifact under review.
2. For each citation, run the four-gate protocol (existence, quote accuracy,
   currency, jurisdiction fit) using the verification pipeline.
3. Report verdicts: VERIFIED, CONDITIONAL, or VETOED.

Hard rules:
- You never approve a citation that fails Gate 1 (existence). Period.
- You never approve a quote that fails Gate 2 (quote accuracy). Period.
- You report negative treatment loudly, even when it's inconvenient.
- You do not soften, equivocate, or grant exceptions. Other roles dissent;
  you veto.

Output format (strict):

  CITATION: <as written in the draft>
  STATUS: VERIFIED | CONDITIONAL | VETOED
  GATES:
    G1 existence: pass|fail
    G2 quote: pass|fail|n/a
    G3 currency: green|yellow|red|n/a
    G4 jurisdiction: mandatory|persuasive|off-point|n/a
  NOTES: <one paragraph max>

Refusal template (use verbatim when asked to approve an unverified cite):
  "Veto. Citation [X] failed gate [N]. I will re-review when verified per
  the four-gate protocol. No exceptions."
`.trim();

export interface SkepticInput {
  draftText: string;
  verifyOpts: VerifyOptions;
}

export interface SkepticOutput {
  verdicts: GateVerdict[];
  blocking: GateVerdict[];
  conditional: GateVerdict[];
  cleared: GateVerdict[];
  summary: string;
  /** True iff the Skeptic vetoes the artifact as a whole. */
  vetoed: boolean;
}

export async function runSkeptic(input: SkepticInput): Promise<SkepticOutput> {
  const { verdicts, hasVetoes } = await verifyDraft(input.draftText, input.verifyOpts);

  const blocking = verdicts.filter((v) => v.status === 'vetoed');
  const conditional = verdicts.filter((v) => v.status === 'conditional');
  const cleared = verdicts.filter((v) => v.status === 'verified');

  const summary = formatSummary(verdicts);
  return {
    verdicts,
    blocking,
    conditional,
    cleared,
    summary,
    vetoed: hasVetoes,
  };
}

function formatSummary(verdicts: GateVerdict[]): string {
  if (verdicts.length === 0) {
    return 'No citations found in artifact. No verification required.';
  }
  const lines: string[] = [];
  for (const v of verdicts) {
    const flag =
      v.status === 'verified' ? '✅' : v.status === 'conditional' ? '⚠️' : '❌';
    lines.push(
      `${flag} ${v.citation}\n` +
        `   G1 existence: ${v.gate1_existence ? 'pass' : 'fail'}\n` +
        `   G2 quote: ${v.gate2_quote_accuracy === null ? 'n/a' : v.gate2_quote_accuracy ? 'pass' : 'fail'}\n` +
        `   G3 currency: ${v.gate3_currency ?? 'n/a'}\n` +
        `   G4 jurisdiction: ${v.gate4_jurisdiction_fit ?? 'n/a'}\n` +
        (v.notes.length ? `   NOTES: ${v.notes.join(' | ')}\n` : ''),
    );
  }
  return lines.join('\n');
}
