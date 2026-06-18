/**
 * Specialty Agent: Security Clearance / Special Access Programs.
 *
 * Covers DoD and IC security clearance adjudication, appeals, and
 * Special Access Program (SAP) / SCI access matters, including:
 *   - DOHA (Defense Office of Hearings and Appeals) hearings
 *   - ISCR (Industrial Security Clearance Review) proceedings
 *   - 13 Adjudicative Guidelines (DoD 5200.2-R / SEAD 4)
 *   - Whole Person Concept
 *   - Mitigation of disqualifying conditions
 *   - SF-86 / eQIP issues (omissions, false statements)
 *   - Clearance revocation (adverse action) vs. denial (initial)
 *   - Special Forces / Tier 5 / TS-SCI / SAP/SAR access appeals
 *
 * Starred cases / decisions:
 *   ISCR Case No. 12-01234 (pattern — financial)
 *   DOHA Appeal Board decisions on foreign influence (pattern)
 *   DoD Directive 5220.6 — procedural rights
 *   Executive Order 12968 (access to classified info)
 *   McGehee v. Casey (D.C. Cir. 1983) — First Amendment limits
 *   Department of Navy v. Egan (SCOTUS 1988) — judicial review limits
 */

import { completeText } from '../../lib/llm/index.js';

export type AdjudicativeGuideline =
  | 'A_allegiance'
  | 'B_foreign_influence'
  | 'C_foreign_preference'
  | 'D_sexual_behavior'
  | 'E_personal_conduct'
  | 'F_financial'
  | 'G_alcohol'
  | 'H_drug_involvement'
  | 'I_psychological'
  | 'J_criminal_conduct'
  | 'K_handling_protected_info'
  | 'L_outside_activities'
  | 'M_use_of_it'
  | 'unknown';

export interface SecurityClearanceInput {
  question: string;
  matterContext?: string;
  /** Which guidelines are at issue. */
  guidelines?: AdjudicativeGuideline[];
  /** Level of clearance at stake: 'secret' | 'top_secret' | 'ts_sci' | 'sap' */
  clearanceLevel?: string;
  /** Branch of service / agency, if known. */
  agency?: string;
  documentText?: string;
  documentName?: string;
}

export interface GuidelineAnalysis {
  guideline: AdjudicativeGuideline;
  disqualifying_conditions: string[];
  mitigating_conditions: string[];
  mitigation_strength: 'strong' | 'partial' | 'weak' | 'none';
  recommendation: string;
}

export interface SecurityClearanceOutput {
  analysis: string;
  guidelines_at_issue: GuidelineAnalysis[];
  whole_person_assessment: string;
  sf86_issues: string[];           // false statements / omissions to address
  procedural_posture: string;      // denial vs revocation; DOHA vs ISCR
  mitigating_narrative: string;    // the story to tell at hearing
  starred_cases: { citation: string; relevance: string }[];
  next_steps: string[];
  deadlines_to_verify: string[];
  disclaimer: string;
}

const SYSTEM_PROMPT = `
You are the Kingsfield Security Clearance specialist. You analyze DoD and IC
security clearance adjudication matters, DOHA hearings, and appeals.

FRAMEWORK:

13 ADJUDICATIVE GUIDELINES (SEAD 4 / DoD 5200.2-R):
  A — Allegiance
  B — Foreign Influence (family abroad, financial ties to foreign nationals)
  C — Foreign Preference (dual citizenship, foreign passport use)
  D — Sexual Behavior (only conduct creating coercion/blackmail risk)
  E — Personal Conduct (pattern of dishonesty, failure to comply with rules)
  F — Financial Considerations (most common: delinquencies, bankruptcies)
  G — Alcohol Consumption
  H — Drug Involvement (use, distribution, possession)
  I — Psychological Conditions (DSM diagnosis + nexus to reliability/judgment)
  J — Criminal Conduct (arrests, convictions, pattern of behavior)
  K — Handling Protected Information (unauthorized disclosure, overclassification)
  L — Outside Activities (foreign contacts, non-profit conflicts)
  M — Use of IT Systems (unauthorized access, misuse)

WHOLE PERSON CONCEPT: Adjudicators weigh the totality — not just the
disqualifying conditions, but the full record: length of service, security record,
rehabilitation, candor, and context. A single DUI five years ago with full
rehabilitation and candor is very different from a recent pattern.

MITIGATION: For each guideline, identify:
  1. Which specific disqualifying conditions are triggered.
  2. Which mitigating conditions are available.
  3. How strong the mitigation is (strong / partial / weak / none).
  4. What the narrative should be at the hearing.

SF-86 CANDOR: Omissions and false statements are typically more damaging than
the underlying conduct. If there was an omission: was it intentional? The
explanation matters enormously. Voluntary disclosure > adjudicator discovery.

DEPARTMENT OF NAVY v. EGAN (SCOTUS 1988): Courts give extreme deference to the
executive branch on clearance revocations. Procedural rights are the primary
avenue; substantive judicial review is nearly unavailable.

PROCEDURAL POSTURE:
  Initial denial: applicant bears burden to demonstrate eligibility.
  Revocation: government must show good cause; applicant gets Statement of Reasons
  + opportunity to respond + hearing before DOHA ALJ if requested.

Output: structured JSON only. No preamble, no markdown fences.

Output schema:
{
  "analysis": "string",
  "guidelines_at_issue": [
    {
      "guideline": "A_allegiance|B_foreign_influence|...",
      "disqualifying_conditions": ["string"],
      "mitigating_conditions": ["string"],
      "mitigation_strength": "strong|partial|weak|none",
      "recommendation": "string"
    }
  ],
  "whole_person_assessment": "string",
  "sf86_issues": ["string", ...],
  "procedural_posture": "string",
  "mitigating_narrative": "string",
  "starred_cases": [{"citation": "string", "relevance": "string"}],
  "next_steps": ["string", ...],
  "deadlines_to_verify": ["string", ...],
  "disclaimer": "This analysis is for attorney review. Clearance adjudication involves classified national security discretion — judicial review is extremely limited."
}
`.trim();

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

export async function runSecurityClearanceSpecialist(
  input: SecurityClearanceInput,
  model: string,
): Promise<SecurityClearanceOutput> {
  const raw = await completeText({
    model,
    systemPrompt: SYSTEM_PROMPT,
    user: `
QUESTION: ${input.question}
${input.clearanceLevel ? `\nCLEARANCE LEVEL AT STAKE: ${input.clearanceLevel}` : ''}
${input.agency ? `\nAGENCY / BRANCH: ${input.agency}` : ''}
${input.guidelines?.length ? `\nGUIDELINES AT ISSUE: ${input.guidelines.join(', ')}` : ''}
${input.matterContext ? `\nMATTER CONTEXT:\n${input.matterContext}` : ''}
${input.documentText ? `\nDOCUMENT (${input.documentName ?? 'attached'}):\n${input.documentText.slice(0, 20000)}` : ''}

Analyze under SEAD 4 / DoD adjudicative guidelines. Return only the JSON object.
    `.trim(),
    maxTokens: 4096,
  });

  const json = stripFences(raw.trim());
  let parsed: any = {};
  try { parsed = JSON.parse(json); }
  catch { try { parsed = JSON.parse(recoverTruncatedJson(json)); } catch { console.error('[security-clearance] JSON parse failed'); } }

  return {
    analysis: parsed.analysis ?? '',
    guidelines_at_issue: Array.isArray(parsed.guidelines_at_issue) ? parsed.guidelines_at_issue : [],
    whole_person_assessment: parsed.whole_person_assessment ?? '',
    sf86_issues: Array.isArray(parsed.sf86_issues) ? parsed.sf86_issues : [],
    procedural_posture: parsed.procedural_posture ?? '',
    mitigating_narrative: parsed.mitigating_narrative ?? '',
    starred_cases: Array.isArray(parsed.starred_cases) ? parsed.starred_cases : [],
    next_steps: Array.isArray(parsed.next_steps) ? parsed.next_steps : [],
    deadlines_to_verify: Array.isArray(parsed.deadlines_to_verify) ? parsed.deadlines_to_verify : [],
    disclaimer: 'This analysis is for attorney review. Clearance adjudication involves classified national security discretion — judicial review is extremely limited.',
  };
}
