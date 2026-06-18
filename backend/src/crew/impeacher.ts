/**
 * Crew Role: Impeacher.
 *
 * Reads one or more deposition transcripts and produces a structured
 * impeachment map:
 *
 *   1. INTRA-WITNESS contradictions — places where THIS witness said
 *      something at time T1 that conflicts with what they said at T2.
 *
 *   2. INTER-WITNESS contradictions — places where ANOTHER witness's
 *      testimony conflicts with what THIS witness said.
 *
 *   3. CROSS-MATTER patterns — if prior testimony from other matters is
 *      supplied, flags where expert or witness testimony differs from what
 *      they've said before.
 *
 * The Impeacher NEVER paraphrases. Every contradiction is anchored by two
 * exact quotes. The output is designed so counsel can walk into a deposition
 * or cross-examination with a printout and use it directly.
 *
 * The broader agent layer this role enables:
 *   → Deposition outline drafting (reads profile + prior outlines)
 *   → Timeline construction (reads all transcripts, builds chronology)
 *   → Cross-matter expert lookup ("What do I know about Expert Foster?")
 *   → Exhibit cross-reference (new discovery PDF → summary next morning)
 */

import { completeText } from '../lib/llm/index.js';

export const IMPEACHER_SYSTEM_PROMPT = `
You are the Impeacher on the Kingsfield Legal Crew. You read deposition
transcripts and locate testimony that can be used for impeachment.

Three types of contradictions you find:

  INTRA — This witness contradicted themselves. Quote the two passages.
  INTER — Another witness contradicted this witness. Quote both.
  PRIOR — This witness's testimony differs from prior-matter testimony
          (only when prior-matter text is provided).

Hard rules:
- Quote exact text from the transcript. Word for word. No paraphrase.
- Every contradiction requires TWO quotes: what they said before, what
  they said now (or what a different witness said).
- Identify the speaker, deposition/exhibit label, and page/line if
  available in the text. If not available, use paragraph order.
- Rate each contradiction's impeachment value:
    "high"   — direct, unambiguous conflict on a material fact
    "medium" — conflicting implication or inconsistent detail
    "low"    — tone or emphasis inconsistency, not a direct conflict
- After the contradiction list, output a DEPOSITION OUTLINE: the 5-10
  most powerful impeachment sequences, in the order you'd use them in
  a cross-examination, with the setup question and the impeaching quote.

Output JSON:

{
  "primary_witness": "name",
  "contradictions": [
    {
      "type": "INTRA | INTER | PRIOR",
      "value": "high | medium | low",
      "topic": "one-line description of what the contradiction is about",
      "statement_a": {
        "speaker": "name",
        "source": "deposition label / exhibit / transcript page",
        "quote": "exact verbatim text"
      },
      "statement_b": {
        "speaker": "name",
        "source": "deposition label / exhibit / transcript page",
        "quote": "exact verbatim text"
      },
      "impeachment_note": "one sentence on why this matters and how to use it"
    }
  ],
  "deposition_outline": [
    {
      "sequence": 1,
      "setup": "The question you ask to get the witness committed",
      "impeach_with": "The prior statement you hit them with"
    }
  ],
  "witness_profile": {
    "themes": ["recurring topics where witness is vulnerable"],
    "credibility_flags": ["anything suggesting bias, interest, or evasion"],
    "strengths": ["areas where testimony appears consistent and hard to attack"]
  }
}
`.trim();

export interface WitnessTranscript {
  witnessName: string;
  label: string; // e.g. "Martinez Depo - Oct 2025", "Exhibit G"
  text: string;
}

export interface ImpeacherInput {
  primaryWitness: string; // name of the witness being impeached
  transcripts: WitnessTranscript[]; // the primary witness first; others follow
  priorMatterTranscripts?: WitnessTranscript[]; // cross-matter testimony if available
  task?: string; // e.g. "focus on pre-existing condition defense"
}

export interface ImpeachStatement {
  speaker: string;
  source: string;
  quote: string;
}

export interface Contradiction {
  type: 'INTRA' | 'INTER' | 'PRIOR';
  value: 'high' | 'medium' | 'low';
  topic: string;
  statement_a: ImpeachStatement;
  statement_b: ImpeachStatement;
  impeachment_note: string;
}

export interface DepositionSequence {
  sequence: number;
  setup: string;
  impeach_with: string;
}

export interface WitnessProfile {
  themes: string[];
  credibility_flags: string[];
  strengths: string[];
}

export interface ImpeacherOutput {
  primaryWitness: string;
  contradictions: Contradiction[];
  deposition_outline: DepositionSequence[];
  witness_profile: WitnessProfile;
}

export async function runImpeacher(
  input: ImpeacherInput,
  model: string,
): Promise<ImpeacherOutput> {
  // Build the transcript block. Primary witness first, then others.
  const transcriptBlock = input.transcripts
    .map((t) => `=== ${t.label} (${t.witnessName}) ===\n${t.text.slice(0, 12000)}`)
    .join('\n\n');

  const priorBlock = input.priorMatterTranscripts?.length
    ? '\n\nPRIOR-MATTER TESTIMONY (other cases):\n' +
      input.priorMatterTranscripts
        .map((t) => `=== ${t.label} (${t.witnessName}) ===\n${t.text.slice(0, 6000)}`)
        .join('\n\n')
    : '';

  const taskNote = input.task
    ? `\nFOCUS: ${input.task}`
    : '';

  const raw = await completeText({
    model,
    systemPrompt: IMPEACHER_SYSTEM_PROMPT,
    user: `
PRIMARY WITNESS: ${input.primaryWitness}
${taskNote}

TRANSCRIPTS:
${transcriptBlock}
${priorBlock}

Find all contradictions. Return the JSON object per your system prompt.
Output ONLY the JSON. No preamble, no markdown fences.
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
      console.error('[impeacher] JSON parse failed, using empty findings');
    }
  }

  return {
    primaryWitness: input.primaryWitness,
    contradictions: parsed.contradictions ?? [],
    deposition_outline: parsed.deposition_outline ?? [],
    witness_profile: parsed.witness_profile ?? {
      themes: [],
      credibility_flags: [],
      strengths: [],
    },
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
