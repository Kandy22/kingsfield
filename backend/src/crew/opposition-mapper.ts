/**
 * Crew Role: Opposition Mapper.
 *
 * For every defense theory the opponent is likely to run, this role
 * produces a full battle plan: what they'll argue (in their actual words),
 * threat level, authority they'll cite, and what you need to defeat it.
 *
 * Based on the Kingsfield opposition-mapping framework. Example:
 *
 *   Defense theory: "Pre-existing condition — C5-C6 herniation predates
 *   the collision and is age-typical degeneration."
 *
 *   The mapper produces one note for each theory that cross-references:
 *   → The defense's expected framing (in their words, not ours)
 *   → Threat level: high / medium / low + reasoning
 *   → Authority they'll cite (case law, statutes, regulations)
 *   → Our authority to counter
 *   → Key exhibits and documents that bear on this theory
 *   → Witness testimony (ours and theirs) relevant to the theory
 *   → Jury instruction implicated (e.g., CACI 3927 for aggravation)
 *   → What we need to defeat it (evidence, experts, motions)
 *
 * The Mapper does not invent facts. It works from the matter context,
 * verified authorities, and document findings supplied to it.
 * When a gap exists ("we have no IME report yet"), it flags it.
 */

import { completeText } from '../lib/llm/index.js';
import type { VerifiedAuthority } from './researcher.js';

export const OPPOSITION_MAPPER_SYSTEM_PROMPT = `
You are the Opposition Mapper on the Kingsfield Legal Crew. For each
defense theory, you produce a complete battle plan.

You think like the defense attorney first — write their argument in their
words, as they would write it in a brief — then you map the counter.

For each defense theory, output:

  1. THEIR_ARGUMENT — the defense theory in the defense's own voice.
     Do not strawman. Write the best version of their argument.
  2. THREAT — "high" | "medium" | "low" with a one-sentence reason.
  3. THEIR_AUTHORITY — cases, statutes, or regulations they will likely
     cite. If you can't identify specific authority, say so.
  4. OUR_AUTHORITY — the verified authorities we have that counter this.
     Only cite what is in the verified-research input. Never invent cites.
  5. KEY_EXHIBITS — documents or evidence that bear on this theory.
  6. WITNESS_EXPOSURE — whose testimony is relevant; who helps, who hurts.
  7. JURY_INSTRUCTION — any jury instruction implicated (CACI, federal, etc.).
  8. DEFEAT_PLAN — what we need to defeat this theory: motions in limine,
     expert designations, deposition topics, cross sequences, jury argument.
  9. GAPS — what we are missing that the defense could exploit.

Output JSON:

{
  "matter_summary": "One paragraph on the matter and its posture.",
  "theories": [
    {
      "name": "short label for this theory",
      "their_argument": "defense's argument in their voice",
      "threat": "high | medium | low",
      "threat_reason": "one sentence",
      "their_authority": ["citations they will likely use"],
      "our_authority": ["our verified citations that counter"],
      "key_exhibits": ["exhibit or document references"],
      "witness_exposure": [
        { "name": "witness", "role": "ours | theirs | neutral", "note": "what they say on this theory" }
      ],
      "jury_instruction": "instruction name / number if applicable",
      "defeat_plan": ["ordered list of steps to defeat this theory"],
      "gaps": ["what we are missing"]
    }
  ],
  "priority_order": ["theory names ordered from highest to lowest threat"],
  "cross_cutting_issues": ["issues that appear across multiple theories"]
}

Hard rules:
- Write their argument as they would write it. Not a caricature.
- Threat level is based on: strength of their authority, weakness of ours,
  evidentiary gaps, and jury appeal.
- NEVER cite authority not in the verified-research input. If you have
  nothing for a theory, say "No verified authority yet — research needed."
- Gaps are as important as strengths. Flag them clearly.
`.trim();

export interface OppositionMapperInput {
  matterContext: string;
  theories: string[]; // list of expected defense theories to map
  verifiedAuthorities: VerifiedAuthority[];
  exhibits?: string[]; // exhibit names/labels in the matter
  witnesses?: Array<{ name: string; role: 'ours' | 'theirs' | 'neutral'; description: string }>;
  jurisdiction?: string;
}

export interface WitnessExposure {
  name: string;
  role: 'ours' | 'theirs' | 'neutral';
  note: string;
}

export interface TheoryMap {
  name: string;
  their_argument: string;
  threat: 'high' | 'medium' | 'low';
  threat_reason: string;
  their_authority: string[];
  our_authority: string[];
  key_exhibits: string[];
  witness_exposure: WitnessExposure[];
  jury_instruction: string;
  defeat_plan: string[];
  gaps: string[];
}

export interface OppositionMapperOutput {
  matter_summary: string;
  theories: TheoryMap[];
  priority_order: string[];
  cross_cutting_issues: string[];
}

export async function runOppositionMapper(
  input: OppositionMapperInput,
  model: string,
): Promise<OppositionMapperOutput> {
  const safeContext = (input.matterContext ?? '').slice(0, 8000);

  const authBlock = input.verifiedAuthorities
    .map(
      (a) =>
        `- ${a.citation}\n  Holding: ${a.holdingSummary}\n  Relevance: ${a.relevanceNote}`,
    )
    .join('\n\n');

  const exhibitBlock = input.exhibits?.length
    ? `EXHIBITS IN MATTER:\n${input.exhibits.map((e) => `- ${e}`).join('\n')}`
    : '';

  const witnessBlock = input.witnesses?.length
    ? `WITNESSES:\n${input.witnesses.map((w) => `- ${w.name} (${w.role}): ${w.description}`).join('\n')}`
    : '';

  const theoriesBlock = input.theories.map((t, i) => `${i + 1}. ${t}`).join('\n');

  const raw = await completeText({
    model,
    systemPrompt: OPPOSITION_MAPPER_SYSTEM_PROMPT,
    user: `
MATTER CONTEXT:
${safeContext}

JURISDICTION: ${input.jurisdiction ?? 'Not specified'}

DEFENSE THEORIES TO MAP:
${theoriesBlock}

VERIFIED AUTHORITIES (only these may appear in our_authority):
${authBlock || '(No verified authorities yet — note as gaps.)'}

${exhibitBlock}

${witnessBlock}

Map each defense theory per your system prompt. Return the JSON object.
Output ONLY the JSON. No preamble, no markdown fences.
Keep each theory's defeat_plan concrete and ordered.
    `.trim(),
    maxTokens: 8192,
  });

  const json = stripFences(raw.trim());
  let parsed: Record<string, any> = {};
  try {
    parsed = JSON.parse(json);
  } catch {
    try {
      parsed = JSON.parse(recoverTruncatedJson(json));
    } catch {
      console.error('[opposition-mapper] JSON parse failed, using empty findings');
    }
  }

  return {
    matter_summary: parsed.matter_summary ?? '',
    theories: parsed.theories ?? [],
    priority_order: parsed.priority_order ?? [],
    cross_cutting_issues: parsed.cross_cutting_issues ?? [],
  };
}

function stripFences(s: string): string {
  return s
    .replace(/^```(?:json)?\s*/i, '')
    .replace(/\s*```\s*$/i, '')
    .trim();
}

function recoverTruncatedJson(s: string): string {
  let truncated = s.replace(/,?\s*"[^"]*$/, '').replace(/,(\s*[}\]])/, '$1');
  const stack: string[] = [];
  let inString = false;
  let escape = false;
  for (const ch of truncated) {
    if (escape) { escape = false; continue; }
    if (ch === '\\') { escape = true; continue; }
    if (ch === '"') { inString = !inString; continue; }
    if (inString) continue;
    if (ch === '{') stack.push('}');
    else if (ch === '[') stack.push(']');
    else if (ch === '}' || ch === ']') stack.pop();
  }
  return truncated + stack.reverse().join('');
}
