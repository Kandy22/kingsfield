/**
 * Council Role: The Judge.
 *
 * Neutral. Not an advocate. Predicts how the bench would actually rule.
 * Applies the law cold to the actual record, not the version of facts the
 * litigant wishes were true.
 */

import type Anthropic from '@anthropic-ai/sdk';

export const JUDGE_SYSTEM_PROMPT = `
You are the Judge on the Kingsfield Council of Experts. You are a neutral
trial judge with twenty years on the bench. You are NOT advising the
litigant. You are doing what a judge does in chambers: reading the brief
cold, comparing it to the record, applying the law, and deciding.

Your output for any artifact under review must address:
1. STANDARD — What is the legal standard the court would apply? Cite the
   rule. (You may only cite authorities that have been verified by the
   Skeptic and supplied to you in context. NEVER cite from memory.)
2. APPLICATION — Apply that standard to the actual record as pleaded and
   admitted, not the wishful version.
3. WEAKEST POINT — Where will this argument most likely fail on the merits?
   Be specific.
4. PREDICTED RULING — One of: GRANT, DENY, GRANT IN PART, TAKEN UNDER
   ADVISEMENT, INSUFFICIENT RECORD. With reasoning.
5. APPELLATE RISK — Standard of review on appeal; how would your predicted
   ruling fare?

Hard rules:
- You never cite a case from memory. If a case isn't in the verified-source
  context, you don't cite it.
- You don't cheerlead. You don't soften.
- You treat the desired outcome and the legally correct outcome as separate
  questions.

If the artifact contains a citation that you cannot find in the verified-
source context provided to you, you respond verbatim:

  "I cannot rule on a brief that cites authority I have not seen. Send the
  cited materials to the Skeptic for verification, then return."
`.trim();

export interface JudgeInput {
  artifactText: string;
  verifiedSources: Array<{
    citation: string;
    holding: string;
    pinCites?: Record<string, string>;
  }>;
  matter: { forum: string; description: string };
}

export interface JudgeOutput {
  standard: string;
  application: string;
  weakestPoint: string;
  predictedRuling: 'grant' | 'deny' | 'grant-in-part' | 'under-advisement' | 'insufficient-record';
  ruling_reasoning: string;
  appellateRisk: string;
}

export async function runJudge(
  input: JudgeInput,
  llm: Anthropic,
): Promise<JudgeOutput> {
  const userMsg = `
ARTIFACT UNDER REVIEW:
${input.artifactText}

MATTER CONTEXT:
Forum: ${input.matter.forum}
Description: ${input.matter.description}

VERIFIED SOURCES YOU MAY CITE:
${input.verifiedSources
  .map((s) => `- ${s.citation}\n  Holding: ${s.holding}`)
  .join('\n')}

If any citation in the artifact is not present in the verified sources list
above, refuse per your refusal template.
  `.trim();

  const resp = await llm.messages.create({
    model: 'claude-opus-4-7',
    max_tokens: 2048,
    system: JUDGE_SYSTEM_PROMPT,
    messages: [{ role: 'user', content: userMsg }],
  });

  // The model returns a structured response per the system prompt format.
  // Parser is conservative: prefer the model's text, then fall back to a
  // light section-extraction. (Full parser elided — replace with a robust
  // schema-validated parse in production.)
  return parseJudgeOutput(extractText(resp));
}

function extractText(resp: any): string {
  return (resp.content ?? [])
    .filter((b: any) => b.type === 'text')
    .map((b: any) => b.text)
    .join('\n');
}

function parseJudgeOutput(text: string): JudgeOutput {
  const get = (label: string) => {
    const re = new RegExp(`${label}[:\\s]+([\\s\\S]*?)(?=\\n[A-Z][A-Z\\s]+:|$)`, 'i');
    return text.match(re)?.[1]?.trim() ?? '';
  };
  const ruling = (get('PREDICTED RULING') || '').toLowerCase();
  let predicted: JudgeOutput['predictedRuling'] = 'insufficient-record';
  if (ruling.includes('grant in part')) predicted = 'grant-in-part';
  else if (ruling.includes('grant')) predicted = 'grant';
  else if (ruling.includes('deny')) predicted = 'deny';
  else if (ruling.includes('advisement')) predicted = 'under-advisement';

  return {
    standard: get('STANDARD'),
    application: get('APPLICATION'),
    weakestPoint: get('WEAKEST POINT'),
    predictedRuling: predicted,
    ruling_reasoning: get('PREDICTED RULING'),
    appellateRisk: get('APPELLATE RISK'),
  };
}
