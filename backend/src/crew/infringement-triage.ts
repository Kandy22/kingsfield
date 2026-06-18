/**
 * Infringement Triage — crew agent.
 *
 * Triages a potential IP infringement situation across four IP tracks:
 *   Trademark · Copyright · Patent · Trade Secret
 *
 * Key constraints (adapted from claude-for-legal infringement-triage spec):
 * - NEVER concludes infringement exists. Output: analysis_complete, possible_infringement,
 *   insufficient_evidence, or outside_scope.
 * - FRE 408 gate: if facts describe ongoing settlement/demand negotiation,
 *   add fre408_caution flag.
 * - Copyright: fair-use gate before recommending action. §411 registration
 *   check (required before filing). DMCA safe harbor check.
 * - Patent: claim chart mapping required before any conclusion. Design vs.
 *   utility branch separation. DOE (doctrine of equivalents) flag.
 * - Trade secret: DTSA (federal) vs. state UTSA distinction. Misappropriation
 *   element checklist.
 * - Output: structured JSON only — no free text, no legal conclusions.
 */

import { completeText } from '../lib/llm/index.js';

// ── Types ─────────────────────────────────────────────────────────────────

export type InfringementTrack = 'trademark' | 'copyright' | 'patent' | 'trade_secret' | 'unknown';
export type AnalysisStatus =
  | 'analysis_complete'
  | 'possible_infringement'
  | 'insufficient_evidence'
  | 'outside_scope';

export interface InfringementTriageInput {
  /** Free-form description of the alleged infringement. */
  description: string;
  /** Which IP tracks to analyze. Omit for auto-detect. */
  tracks?: InfringementTrack[];
  /** Jurisdiction (US assumed if omitted). */
  jurisdiction?: string;
  /** Relevant IP assets owned by the claimant (title, registration number, etc.). */
  ourAssets?: string;
  /** Description of the accused product/work/process. */
  accusedContent?: string;
}

export interface TrademarkAnalysis {
  likelihood_of_confusion_factors: string[];
  dilution_possible: boolean;
  descriptiveness_concern: boolean;
  priority_question: string;
  recommended_searches: string[];
  gaps: string[];
}

export interface CopyrightAnalysis {
  registration_required: boolean;           // §411 check
  registration_status: string;              // 'registered' | 'unregistered' | 'unknown'
  fair_use_factors: {
    purpose_and_character: string;          // transformative?
    nature_of_work: string;
    amount_taken: string;
    market_effect: string;
  };
  fair_use_conclusion: 'likely_fair_use' | 'likely_not_fair_use' | 'unclear';
  dmca_safe_harbor_applies: boolean;
  dmca_safe_harbor_note: string;
  actionability: string;
}

export interface PatentAnalysis {
  patent_type: 'utility' | 'design' | 'both' | 'unknown';
  claim_chart_needed: boolean;
  doe_flag: boolean;                         // doctrine of equivalents applicable?
  invalidity_risks: string[];
  key_claims_to_map: string[];
  gaps: string[];
}

export interface TradeSecretAnalysis {
  statute: 'DTSA' | 'UTSA' | 'both' | 'unknown';
  reasonable_measures_documented: boolean;
  misappropriation_elements: {
    acquisition_by_improper_means: string;
    disclosure_or_use: string;
    breach_of_duty: string;
  };
  gaps: string[];
}

export interface InfringementTriageOutput {
  detected_tracks: InfringementTrack[];
  overall_status: AnalysisStatus;
  fre408_caution: boolean;
  trademark?: TrademarkAnalysis;
  copyright?: CopyrightAnalysis;
  patent?: PatentAnalysis;
  trade_secret?: TradeSecretAnalysis;
  next_steps: string[];                      // ordered, attorney-directed
  evidence_needed: string[];
  risks_if_no_action: string[];
  disclaimer: string;
}

// ── System prompt ─────────────────────────────────────────────────────────

const TRIAGE_SYSTEM_PROMPT = `
You are an IP triage engine for litigation support software. You analyze potential
infringement situations and return structured JSON for attorney review.

CRITICAL CONSTRAINTS — NEVER VIOLATE:
1. NEVER conclude that infringement exists or does not exist. That is a legal
   conclusion for a licensed attorney. Use status values only:
   analysis_complete | possible_infringement | insufficient_evidence | outside_scope
2. FRE 408: If the facts describe ongoing demand/settlement negotiation, set
   fre408_caution: true and note in next_steps that FRE 408 issues must be
   reviewed before any written communication.
3. Copyright: Always run the fair-use four-factor analysis. Always check §411
   registration requirement before recommending filing. Always check whether
   DMCA safe harbor applies to the accused party.
4. Patent: Never map claims without a full claim chart. Set claim_chart_needed: true
   always unless you have the actual claim language. Distinguish utility vs. design.
   Flag DOE if literal infringement is unclear.
5. Trade secret: Identify DTSA vs. state UTSA applicability. Check all three
   misappropriation elements (acquisition, disclosure/use, breach of duty).
6. Return ONLY valid JSON. No preamble, no markdown fences, no commentary.

Output schema:
{
  "detected_tracks": ["trademark"|"copyright"|"patent"|"trade_secret"],
  "overall_status": "analysis_complete|possible_infringement|insufficient_evidence|outside_scope",
  "fre408_caution": true|false,
  "trademark": { ... } | null,
  "copyright": { ... } | null,
  "patent": { ... } | null,
  "trade_secret": { ... } | null,
  "next_steps": ["string", ...],
  "evidence_needed": ["string", ...],
  "risks_if_no_action": ["string", ...],
  "disclaimer": "This triage is for attorney review only. It does not constitute legal advice and does not determine whether infringement has occurred."
}

Trademark schema:
{
  "likelihood_of_confusion_factors": ["DuPont factor: ..."],
  "dilution_possible": true|false,
  "descriptiveness_concern": true|false,
  "priority_question": "string",
  "recommended_searches": ["TESS full search", ...],
  "gaps": ["missing: registration certificate", ...]
}

Copyright schema:
{
  "registration_required": true|false,
  "registration_status": "registered|unregistered|unknown",
  "fair_use_factors": {
    "purpose_and_character": "string",
    "nature_of_work": "string",
    "amount_taken": "string",
    "market_effect": "string"
  },
  "fair_use_conclusion": "likely_fair_use|likely_not_fair_use|unclear",
  "dmca_safe_harbor_applies": true|false,
  "dmca_safe_harbor_note": "string",
  "actionability": "string"
}

Patent schema:
{
  "patent_type": "utility|design|both|unknown",
  "claim_chart_needed": true,
  "doe_flag": true|false,
  "invalidity_risks": ["string", ...],
  "key_claims_to_map": ["Claim 1: ...", ...],
  "gaps": ["string", ...]
}

Trade secret schema:
{
  "statute": "DTSA|UTSA|both|unknown",
  "reasonable_measures_documented": true|false,
  "misappropriation_elements": {
    "acquisition_by_improper_means": "string",
    "disclosure_or_use": "string",
    "breach_of_duty": "string"
  },
  "gaps": ["string", ...]
}
`.trim();

// ── Helpers ───────────────────────────────────────────────────────────────

function stripFences(s: string): string {
  return s.replace(/^```(?:json)?\s*/i, '').replace(/\s*```\s*$/i, '').trim();
}

function recoverTruncatedJson(s: string): string {
  let t = s.replace(/,?\s*"[^"]*$/, '').replace(/,(\s*[}\]])/, '$1');
  const stack: string[] = [];
  let inStr = false, esc = false;
  for (const ch of t) {
    if (esc) { esc = false; continue; }
    if (ch === '\\') { esc = true; continue; }
    if (ch === '"') { inStr = !inStr; continue; }
    if (inStr) continue;
    if (ch === '{') stack.push('}');
    else if (ch === '[') stack.push(']');
    else if (ch === '}' || ch === ']') stack.pop();
  }
  return t + stack.reverse().join('');
}

const DISCLAIMER =
  'This triage is for attorney review only. It does not constitute legal advice ' +
  'and does not determine whether infringement has occurred.';

// ── Main ──────────────────────────────────────────────────────────────────

export async function runInfringementTriage(
  input: InfringementTriageInput,
  model: string,
): Promise<InfringementTriageOutput> {
  const tracksNote = input.tracks?.length
    ? `Focus on these tracks: ${input.tracks.join(', ')}.`
    : 'Auto-detect which IP tracks apply.';

  const raw = await completeText({
    model,
    systemPrompt: TRIAGE_SYSTEM_PROMPT,
    user: `
JURISDICTION: ${input.jurisdiction ?? 'United States (federal + state)'}
${tracksNote}

ALLEGED INFRINGEMENT:
${input.description}

${input.ourAssets ? `OUR IP ASSETS:\n${input.ourAssets}` : ''}

${input.accusedContent ? `ACCUSED PRODUCT/WORK/PROCESS:\n${input.accusedContent}` : ''}

Run the triage. Return only the JSON object.
    `.trim(),
    maxTokens: 4096,
  });

  const json = stripFences(raw.trim());
  let parsed: any = {};
  try {
    parsed = JSON.parse(json);
  } catch {
    try {
      parsed = JSON.parse(recoverTruncatedJson(json));
    } catch {
      console.error('[infringement-triage] JSON parse failed');
    }
  }

  return {
    detected_tracks: Array.isArray(parsed.detected_tracks) ? parsed.detected_tracks : [],
    overall_status: parsed.overall_status ?? 'insufficient_evidence',
    fre408_caution: parsed.fre408_caution === true,
    trademark: parsed.trademark ?? undefined,
    copyright: parsed.copyright ?? undefined,
    patent: parsed.patent ?? undefined,
    trade_secret: parsed.trade_secret ?? undefined,
    next_steps: Array.isArray(parsed.next_steps) ? parsed.next_steps : [],
    evidence_needed: Array.isArray(parsed.evidence_needed) ? parsed.evidence_needed : [],
    risks_if_no_action: Array.isArray(parsed.risks_if_no_action) ? parsed.risks_if_no_action : [],
    disclaimer: DISCLAIMER,
  };
}
