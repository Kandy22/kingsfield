/**
 * Crew Role: Writing Coach.
 *
 * Applies the Kingsfield persuasive-writing standard to any legal draft —
 * briefs, motions, demand letters, mediation statements — and returns
 * structured, line-level critique with rewrites.
 *
 * The 11 rules this role enforces:
 *   1.  Audience awareness
 *   2.  No categorical absolutes
 *   3.  Clear and concrete language
 *   4.  Conciseness (cut the fat)
 *   5.  Cohesion and navigability
 *   6.  Compelling — holds attention
 *   7.  Credibility — earned, not asserted
 *   8.  Read and reverse-engineer great writing
 *   9.  Rewrite — persuasive prose is the end product of many drafts
 *  10.  Kill badverbs (intensifier and hedge adverbs)
 *  11.  Kill zombie nouns (-tion, -ance, -ence nominalisations)
 *  12.  Vary sentence length for rhythm
 *
 * The Coach does NOT rewrite the whole document — it surfaces issues so
 * the author can rewrite. It can optionally produce a sentence-level
 * rewrite for each flagged item.
 */

import { completeText } from '../lib/llm/index.js';

export const WRITING_COACH_SYSTEM_PROMPT = `
You are the Writing Coach on the Kingsfield Legal Crew. You apply the
Kingsfield persuasive-writing standard to legal drafts.

The 12 rules you enforce:

  1. AUDIENCE — does the draft account for reader expectations?
  2. CATEGORICAL — does it over-claim ("always," "never," "clearly")?
  3. CONCRETE — are facts and ideas stated in plain, specific words?
  4. CONCISE — is every word doing work?
  5. COHESIVE — is it easy to scan and navigate?
  6. COMPELLING — does it hold attention?
  7. CREDIBLE — does it earn authority or just assert it?
  8. BADVERBS — intensifier adverbs (Clearly, Obviously, Outrageously) and
     hedge adverbs (Arguably, Apparently, Fairly). Both weaken arguments.
     Research on Supreme Court briefs shows: more intensifiers → more losses.
  9. ZOMBIE NOUNS — nominalisations: -tion, -ance, -ence forms that carry
     tail markings and shackle verbs.
     "conducted an investigation" → "investigated"
     "made a decision" → "decided"
     "provided a justification" → "justified"
 10. RHYTHM — sentence length variety. Short hits hard. Long builds pressure.
     Same-length stacking numbs the reader.
 11. CREDIBILITY — reputation is earned in the record, not invoked.
 12. REWRITE — every draft has a better version; flag where it's needed.

Your output is a JSON object:

{
  "summary": "One paragraph overall assessment — what's working, what isn't.",
  "score": { "clarity": 1-10, "conciseness": 1-10, "credibility": 1-10, "rhythm": 1-10 },
  "findings": [
    {
      "rule": "BADVERBS | ZOMBIE_NOUN | CATEGORICAL | CONCISE | CREDIBILITY | RHYTHM | OTHER",
      "severity": "high | medium | low",
      "quote": "verbatim text ≤ 30 words",
      "issue": "one sentence on the problem",
      "rewrite": "suggested replacement (≤ 40 words)"
    }
  ],
  "top_rewrites": [
    "The three most impactful sentence-level rewrites, each as a before/after pair."
  ],
  "strengths": ["array of 2-3 things the draft does well"]
}

Hard rules:
- Quote the exact problematic text. No paraphrase.
- Every finding needs a specific rewrite, not just a diagnosis.
- Do not flag comma placement, citation format, or stylistic preference
  unrelated to the 12 rules.
- Flag badverbs by name: identify whether each is an intensifier or hedge.
- A brief that loses "Clearly" and gains specificity gets stronger. Show that.
`.trim();

export const STRUCTURAL_COACH_SYSTEM_PROMPT = `
You are the Structural Writing Coach on the Kingsfield Legal Crew. You analyze
the architecture of legal documents — briefs, motions, memos, demand letters —
and give attorneys specific structural feedback on argument order, analysis
depth, issue framing, and navigability.

Unlike a student-facing writing coach, you PRODUCE REWRITES. Attorneys need
concrete suggestions, not pedagogical scaffolding. Every structural issue gets
a suggested fix.

Structural frameworks:
- BRIEF/MOTION: Point headings in priority order (strongest first unless sequencing
  requires otherwise). Issue statements (under/over-inclusive?). Rule-application
  mapping — is the rule applied to the specific facts or just stated next to them?
  Counterarguments addressed before or punted?
- MEMO: BLUF (Bottom Line Up Front). Issue, Rule, Analysis, Conclusion — each
  section should be identifiable. Analysis must connect rule to facts, not just
  list both.
- DEMAND LETTER: Demand stated early, legal theory stated plainly, specific harm
  quantified, deadline explicit.
- APPELLATE BRIEF: Standard of review stated and used. Preservation noted. Issue
  order matches severity + preservation strength.

Output schema:
{
  "document_type": "brief | motion | memo | demand_letter | appellate_brief | other",
  "structure_score": 1-10,
  "thesis_present": true|false,
  "thesis_location": "string — where the main thesis appears, if at all",
  "argument_order": "string — summary of current order, assessment of whether it's optimal",
  "structural_findings": [
    {
      "type": "THESIS | ARGUMENT_ORDER | RULE_APPLICATION | COUNTERARGUMENT | NAVIGABILITY | ISSUE_FRAMING | BLUF | OTHER",
      "severity": "critical | high | medium | low",
      "location": "string — section or quote ≤ 40 words",
      "issue": "string",
      "fix": "string — specific structural fix or rewrite suggestion"
    }
  ],
  "priority_fixes": ["string", ...],
  "structural_strengths": ["string", ...]
}

Return ONLY valid JSON. No preamble, no markdown fences.
`.trim();

export interface WritingCoachInput {
  documentText: string;
  documentName: string;
  documentType?: string; // "brief" | "motion" | "demand letter" | "memo" | "other"
  focusAreas?: string[]; // e.g. ["badverbs", "zombie_nouns"] — omit for full review
  /**
   * 'persuasive' (default): sentence-level critique — badverbs, zombie nouns,
   *   rhythm, credibility, conciseness. Produces line-level rewrites.
   * 'structural': document architecture — argument order, IRAC/CRAC, thesis
   *   placement, rule-application mapping.
   * 'both': run both passes and combine.
   */
  mode?: 'persuasive' | 'structural' | 'both';
}

export type WritingRule =
  | 'BADVERBS'
  | 'ZOMBIE_NOUN'
  | 'CATEGORICAL'
  | 'CONCISE'
  | 'CREDIBILITY'
  | 'RHYTHM'
  | 'AUDIENCE'
  | 'COHESIVE'
  | 'CONCRETE'
  | 'COMPELLING'
  | 'OTHER';

export interface WritingFinding {
  rule: WritingRule;
  severity: 'high' | 'medium' | 'low';
  quote: string;
  issue: string;
  rewrite: string;
}

export interface WritingScore {
  clarity: number;
  conciseness: number;
  credibility: number;
  rhythm: number;
}

export type StructuralFindingType =
  | 'THESIS'
  | 'ARGUMENT_ORDER'
  | 'RULE_APPLICATION'
  | 'COUNTERARGUMENT'
  | 'NAVIGABILITY'
  | 'ISSUE_FRAMING'
  | 'BLUF'
  | 'OTHER';

export interface StructuralFinding {
  type: StructuralFindingType;
  severity: 'critical' | 'high' | 'medium' | 'low';
  location: string;
  issue: string;
  fix: string;
}

export interface StructuralAnalysis {
  document_type: string;
  structure_score: number;
  thesis_present: boolean;
  thesis_location: string;
  argument_order: string;
  structural_findings: StructuralFinding[];
  priority_fixes: string[];
  structural_strengths: string[];
}

export interface WritingCoachOutput {
  documentName: string;
  documentType: string;
  mode: 'persuasive' | 'structural' | 'both';
  summary: string;
  score: WritingScore;
  findings: WritingFinding[];
  top_rewrites: string[];
  strengths: string[];
  structural?: StructuralAnalysis;
}

export async function runWritingCoach(
  input: WritingCoachInput,
  model: string,
): Promise<WritingCoachOutput> {
  // Cap at 24k chars — more than enough for any motion or brief section.
  const safeText = (input.documentText ?? '').slice(0, 24000);
  const docType = input.documentType ?? 'legal document';
  const mode = input.mode ?? 'persuasive';
  const focus = input.focusAreas?.length
    ? `Focus especially on: ${input.focusAreas.join(', ')}.`
    : 'Apply all 12 rules equally.';

  const userBlock = `
DOCUMENT NAME: ${input.documentName}
DOCUMENT TYPE: ${docType}
${focus}

DOCUMENT TEXT:
---
${safeText}
---
  `.trim();

  // ── Persuasive pass ──────────────────────────────────────────────────────
  let persuasiveParsed: Record<string, any> = {};
  if (mode === 'persuasive' || mode === 'both') {
    const raw = await completeText({
      model,
      systemPrompt: WRITING_COACH_SYSTEM_PROMPT,
      user: `${userBlock}

Return a JSON object with: summary, score, findings[], top_rewrites[],
strengths[]. Each finding must have: rule, severity, quote, issue, rewrite.
Output ONLY the JSON. No preamble, no markdown fences.`,
      maxTokens: 6144,
    });
    const json = stripFences(raw.trim());
    try {
      persuasiveParsed = JSON.parse(json);
    } catch {
      try { persuasiveParsed = JSON.parse(recoverTruncatedJson(json)); }
      catch { console.error('[writing-coach] persuasive JSON parse failed'); }
    }
  }

  // ── Structural pass ──────────────────────────────────────────────────────
  let structural: StructuralAnalysis | undefined;
  if (mode === 'structural' || mode === 'both') {
    const raw = await completeText({
      model,
      systemPrompt: STRUCTURAL_COACH_SYSTEM_PROMPT,
      user: `${userBlock}

Return the structural analysis JSON object per your schema.
Output ONLY the JSON. No preamble, no markdown fences.`,
      maxTokens: 4096,
    });
    const json = stripFences(raw.trim());
    let sp: any = {};
    try {
      sp = JSON.parse(json);
    } catch {
      try { sp = JSON.parse(recoverTruncatedJson(json)); }
      catch { console.error('[writing-coach] structural JSON parse failed'); }
    }
    structural = {
      document_type: sp.document_type ?? docType,
      structure_score: typeof sp.structure_score === 'number' ? sp.structure_score : 0,
      thesis_present: sp.thesis_present === true,
      thesis_location: sp.thesis_location ?? '',
      argument_order: sp.argument_order ?? '',
      structural_findings: Array.isArray(sp.structural_findings) ? sp.structural_findings : [],
      priority_fixes: Array.isArray(sp.priority_fixes) ? sp.priority_fixes : [],
      structural_strengths: Array.isArray(sp.structural_strengths) ? sp.structural_strengths : [],
    };
  }

  return {
    documentName: input.documentName,
    documentType: docType,
    mode,
    summary: persuasiveParsed.summary ?? '',
    score: persuasiveParsed.score ?? { clarity: 0, conciseness: 0, credibility: 0, rhythm: 0 },
    findings: persuasiveParsed.findings ?? [],
    top_rewrites: persuasiveParsed.top_rewrites ?? [],
    strengths: persuasiveParsed.strengths ?? [],
    structural,
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
