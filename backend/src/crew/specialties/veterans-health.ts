/**
 * Specialty Agent: Veterans Health Law.
 *
 * Covers VA disability claims, appeals, and benefits litigation:
 *   - 38 U.S.C. / 38 CFR rating schedules
 *   - Notice of Disagreement → Statement of the Case → BVA → CAVC → Fed. Cir.
 *   - MST (Military Sexual Trauma) claims
 *   - PTSD / TBI rating; Individual Unemployability (IU)
 *   - Clear and Unmistakable Error (CUE)
 *   - Effective date disputes
 *   - AMA (Appeals Modernization Act) lanes: Direct Review, Evidence Submission, Hearing
 *
 * Key starred cases (surface when relevant):
 *   Butts v. Brown (Fed. Cir. 1995) — veteran entitled to benefit of the doubt
 *   Hodge v. West (Fed. Cir. 1998) — sympathetic reading of pro se pleadings
 *   Dingess v. Nicholson (Vet. App. 2006) — VCAA notice requirements
 *   Caluza v. Brown (Fed. Cir. 1995) — nexus requirement for service connection
 *   Jandreau v. Nicholson (Fed. Cir. 2007) — lay evidence of in-service injury
 *   Saunders v. Wilkie (Fed. Cir. 2018) — pain alone can be a disability
 *   Shinseki v. Sanders (SCOTUS 2009) — harmless error / prejudicial error standard
 */

import { completeText } from '../../lib/llm/index.js';

export interface VeteransHealthInput {
  question: string;
  matterContext?: string;
  /** Veteran's branch and era of service, if known. */
  serviceInfo?: string;
  /** Current VA rating, if known. */
  currentRating?: string;
  /** Document text if analyzing a rating decision, C&P exam report, etc. */
  documentText?: string;
  documentName?: string;
}

export type VaAppealLane = 'direct_review' | 'evidence_submission' | 'hearing' | 'unknown';
export type VaAppealLevel = 'regional_office' | 'bva' | 'cavc' | 'federal_circuit' | 'scotus' | 'unknown';

export interface VeteransHealthOutput {
  analysis: string;
  current_appeal_level: VaAppealLevel;
  recommended_lane?: VaAppealLane;
  key_issues: string[];
  cue_present: boolean;
  cue_note: string;
  effective_date_issue: boolean;
  effective_date_note: string;
  lay_evidence_value: string;
  nexus_analysis: string;
  starred_cases: { citation: string; relevance: string }[];
  next_steps: string[];
  deadlines_to_verify: string[];
  disclaimer: string;
}

const SYSTEM_PROMPT = `
You are the Kingsfield Veterans Health Law specialist. You analyze VA disability
claims, appeals, and benefits matters under 38 U.S.C. and 38 CFR.

Core doctrine you apply:

BENEFIT OF THE DOUBT: When evidence is in equipoise, the veteran wins. 38 U.S.C. §5107(b).
Never concede close calls — articulate why the evidence tips in the veteran's favor.

SERVICE CONNECTION: Three elements:
  1. In-service incurrence or aggravation (lay evidence sufficient per Jandreau).
  2. Current disability (Saunders: pain alone qualifies).
  3. Nexus between 1 and 2 (medical nexus, or direct service connection for combat/POW).

RATING SCHEDULES: 38 CFR Part 4. Analogous ratings when exact code doesn't apply.
Combined ratings table — don't add percentages; use VA math (whole person method).

AMA LANES (post-2019 claims):
  Direct Review: BVA reviews existing record. No new evidence. Fastest.
  Evidence Submission: Submit new evidence to BVA without a hearing.
  Hearing: Before VLJ. Preserves fullest record for CAVC.

CUE: Clear and Unmistakable Error — a specific, undebatable error of fact or law
at the time of the original decision. Not a disagreement with the outcome — an
error that manifestly changes it. Correct standard: *would the outcome have been
manifestly different?* (Fugo v. Brown, Vet. App. 1995).

EFFECTIVE DATE: Earliest possible effective date = date of claim, or date of
entitlement if earlier. Informal claims (written communications to VA expressing
intent to file) can establish earlier effective dates.

STARRED CASES — surface when relevant:
- Butts v. Brown (Fed. Cir. 1995): benefit of the doubt
- Hodge v. West (Fed. Cir. 1998): sympathetic reading of pro se pleadings
- Dingess v. Nicholson (Vet. App. 2006): VCAA §5103(a) notice scope
- Caluza v. Brown (Fed. Cir. 1995): three-element nexus test
- Jandreau v. Nicholson (Fed. Cir. 2007): lay evidence of in-service continuity
- Saunders v. Wilkie (Fed. Cir. 2018): pain alone = disability
- Shinseki v. Sanders (SCOTUS 2009): harmless error standard
- McLendon v. Nicholson (Vet. App. 2006): low threshold for C&P exam trigger

Constraints:
- Never advise a veteran to abandon a claim. Deadlines are jurisdictional.
- Always flag deadlines to verify — NOD deadlines, CAVC deadlines (120 days from
  BVA decision), are strict.
- Output: structured JSON only. No preamble, no markdown fences.

Output schema:
{
  "analysis": "string — substantive analysis",
  "current_appeal_level": "regional_office|bva|cavc|federal_circuit|scotus|unknown",
  "recommended_lane": "direct_review|evidence_submission|hearing|unknown",
  "key_issues": ["string", ...],
  "cue_present": true|false,
  "cue_note": "string",
  "effective_date_issue": true|false,
  "effective_date_note": "string",
  "lay_evidence_value": "string",
  "nexus_analysis": "string",
  "starred_cases": [{"citation": "string", "relevance": "string"}],
  "next_steps": ["string", ...],
  "deadlines_to_verify": ["string", ...],
  "disclaimer": "This analysis is for attorney review. Deadlines in veterans law are jurisdictional — verify before advising."
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

export async function runVeteransHealthSpecialist(
  input: VeteransHealthInput,
  model: string,
): Promise<VeteransHealthOutput> {
  const raw = await completeText({
    model,
    systemPrompt: SYSTEM_PROMPT,
    user: `
QUESTION: ${input.question}
${input.matterContext ? `\nMATTER CONTEXT:\n${input.matterContext}` : ''}
${input.serviceInfo ? `\nSERVICE INFO: ${input.serviceInfo}` : ''}
${input.currentRating ? `\nCURRENT VA RATING: ${input.currentRating}` : ''}
${input.documentText ? `\nDOCUMENT (${input.documentName ?? 'attached'}):\n${input.documentText.slice(0, 20000)}` : ''}

Analyze under 38 U.S.C. / 38 CFR. Return only the JSON object.
    `.trim(),
    maxTokens: 4096,
  });

  const json = stripFences(raw.trim());
  let parsed: any = {};
  try { parsed = JSON.parse(json); }
  catch { try { parsed = JSON.parse(recoverTruncatedJson(json)); } catch { console.error('[veterans-health] JSON parse failed'); } }

  return {
    analysis: parsed.analysis ?? '',
    current_appeal_level: parsed.current_appeal_level ?? 'unknown',
    recommended_lane: parsed.recommended_lane ?? undefined,
    key_issues: Array.isArray(parsed.key_issues) ? parsed.key_issues : [],
    cue_present: parsed.cue_present === true,
    cue_note: parsed.cue_note ?? '',
    effective_date_issue: parsed.effective_date_issue === true,
    effective_date_note: parsed.effective_date_note ?? '',
    lay_evidence_value: parsed.lay_evidence_value ?? '',
    nexus_analysis: parsed.nexus_analysis ?? '',
    starred_cases: Array.isArray(parsed.starred_cases) ? parsed.starred_cases : [],
    next_steps: Array.isArray(parsed.next_steps) ? parsed.next_steps : [],
    deadlines_to_verify: Array.isArray(parsed.deadlines_to_verify) ? parsed.deadlines_to_verify : [],
    disclaimer: 'This analysis is for attorney review. Deadlines in veterans law are jurisdictional — verify before advising.',
  };
}
