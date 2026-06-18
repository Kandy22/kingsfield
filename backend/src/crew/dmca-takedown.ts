/**
 * DMCA Takedown Drafter — crew agent.
 *
 * Three operational modes (adapted from claude-for-legal takedown spec):
 *
 *   send       — Draft a §512(c)(3) takedown notice to a platform.
 *   respond    — Analyze a takedown notice received; draft counter-notice
 *                elements if warranted.
 *   counter    — Draft a §512(g)(3) counter-notice.
 *
 * Key constraints:
 * - Lenz fair-use gate: ALWAYS run fair-use four-factor analysis before
 *   drafting a send notice. If fair_use_conclusion is 'likely_fair_use',
 *   block the draft and require attorney review.  Lenz v. Universal Music
 *   Corp. (9th Cir. 2016) requires good-faith consideration of fair use.
 * - §512(c)(3) elements: all six statutory elements must be present.
 * - §512(f) liability: perjury gate — agent must flag if any element is
 *   uncertain; never certify under penalty of perjury.
 * - Counter-notice: §512(g)(3) elements checklist; consent to federal
 *   jurisdiction required.
 * - Output: structured JSON + draft text blocks for attorney review.
 * - Never sends any communication. Output only.
 */

import { completeText } from '../lib/llm/index.js';

// ── Types ─────────────────────────────────────────────────────────────────

export type TakedownMode = 'send' | 'respond' | 'counter';

export interface FairUseAnalysis {
  purpose_and_character: string;        // transformative?
  nature_of_work: string;
  amount_and_substantiality: string;
  market_effect: string;
  conclusion: 'likely_fair_use' | 'likely_not_fair_use' | 'unclear';
  lenz_block: boolean;                  // true = do not proceed without attorney review
}

export interface Section512c3Elements {
  physical_or_electronic_signature: boolean;
  identification_of_copyrighted_work: boolean;
  identification_of_infringing_material: boolean;
  contact_information: boolean;
  good_faith_belief_statement: boolean;
  accuracy_under_penalty_of_perjury: boolean;
  all_elements_present: boolean;
  missing_elements: string[];
}

export interface Section512g3Elements {
  physical_or_electronic_signature: boolean;
  identification_of_removed_material: boolean;
  statement_of_good_faith: boolean;
  subscriber_name_address_phone: boolean;
  consent_to_federal_jurisdiction: boolean;
  all_elements_present: boolean;
  missing_elements: string[];
}

export interface DmcaTakedownOutput {
  mode: TakedownMode;
  // Fair use (send/respond modes)
  fair_use?: FairUseAnalysis;
  // §512(f) perjury risk flags
  section_512f_risk: boolean;
  section_512f_notes: string[];
  // Element checklists
  elements_512c3?: Section512c3Elements;
  elements_512g3?: Section512g3Elements;
  // Draft text blocks (for attorney review and editing)
  draft_notice?: string;
  draft_counter_notice?: string;
  // Platform-specific notes
  platform_notes: string[];
  // Next steps
  next_steps: string[];
  // Blocked?
  blocked: boolean;
  blocked_reason?: string;
  disclaimer: string;
}

// ── System prompt ─────────────────────────────────────────────────────────

const TAKEDOWN_SYSTEM_PROMPT = `
You are a DMCA notice drafting engine for litigation support software. You assist
attorneys in drafting, analyzing, and responding to DMCA takedown notices.

CRITICAL CONSTRAINTS — NEVER VIOLATE:

1. LENZ GATE (send mode): Before drafting any takedown notice, run the four-factor
   fair use analysis. If fair_use_conclusion is "likely_fair_use", set
   lenz_block: true and blocked: true. Do NOT draft the notice. Lenz v. Universal
   Music Corp. (9th Cir. 2016) requires good-faith consideration of fair use before
   sending a §512(c) notice; failure creates §512(f) liability.

2. PERJURY GATE: If ANY §512(c)(3) element is uncertain, set section_512f_risk: true.
   Never produce a notice that includes an accuracy certification unless all elements
   are clearly established. Flag uncertainty loudly.

3. §512(c)(3) ELEMENTS: All six must be present:
   (A) Physical or electronic signature of copyright owner or authorized person.
   (B) Identification of copyrighted work(s) claimed to be infringed (registration
       number if available).
   (C) Identification of infringing material with sufficient information to locate it
       (URL, timestamp, etc.).
   (D) Contact information of the complaining party.
   (E) Good-faith belief statement.
   (F) Accuracy statement under penalty of perjury.

4. §512(g)(3) ELEMENTS (counter-notice): All five must be present:
   (A) Signature.
   (B) Identification of removed material and where it appeared before removal.
   (C) Statement of good faith belief the material was removed by mistake or
       misidentification.
   (D) Subscriber's name, address, and phone number.
   (E) Consent to federal court jurisdiction (district where subscriber is located,
       or if outside US, any judicial district).

5. Never send any communication. Output draft text only, labeled
   "DRAFT FOR ATTORNEY REVIEW — DO NOT SEND WITHOUT ATTORNEY APPROVAL."

6. Return ONLY valid JSON. No preamble, no markdown fences.

Output schema:
{
  "mode": "send|respond|counter",
  "fair_use": {
    "purpose_and_character": "string",
    "nature_of_work": "string",
    "amount_and_substantiality": "string",
    "market_effect": "string",
    "conclusion": "likely_fair_use|likely_not_fair_use|unclear",
    "lenz_block": true|false
  } | null,
  "section_512f_risk": true|false,
  "section_512f_notes": ["string", ...],
  "elements_512c3": {
    "physical_or_electronic_signature": true|false,
    "identification_of_copyrighted_work": true|false,
    "identification_of_infringing_material": true|false,
    "contact_information": true|false,
    "good_faith_belief_statement": true|false,
    "accuracy_under_penalty_of_perjury": true|false,
    "all_elements_present": true|false,
    "missing_elements": ["string"]
  } | null,
  "elements_512g3": { ... same shape ... } | null,
  "draft_notice": "DRAFT FOR ATTORNEY REVIEW — DO NOT SEND WITHOUT ATTORNEY APPROVAL\\n\\n[full notice text]" | null,
  "draft_counter_notice": "DRAFT FOR ATTORNEY REVIEW — DO NOT SEND WITHOUT ATTORNEY APPROVAL\\n\\n[full counter-notice text]" | null,
  "platform_notes": ["string", ...],
  "next_steps": ["string", ...],
  "blocked": true|false,
  "blocked_reason": "string" | null,
  "disclaimer": "This draft is for attorney review only. Do not send without attorney review and approval. This is not legal advice."
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
  'This draft is for attorney review only. Do not send without attorney review and approval. This is not legal advice.';

// ── Main ──────────────────────────────────────────────────────────────────

export async function runDmcaTakedown(
  input: {
    mode: TakedownMode;
    /** Description of the copyrighted work. */
    copyrightedWork?: string;
    /** Description / URL of the infringing content. */
    accusedContent?: string;
    /** Platform or host where the content appears. */
    platform?: string;
    /** Claimant information (name, address, email, relationship to work). */
    claimantInfo?: string;
    /** Full text of the takedown notice received (for respond/counter modes). */
    receivedNoticeText?: string;
    /** Any additional context. */
    context?: string;
  },
  model: string,
): Promise<DmcaTakedownOutput> {
  const raw = await completeText({
    model,
    systemPrompt: TAKEDOWN_SYSTEM_PROMPT,
    user: `
MODE: ${input.mode}

${input.copyrightedWork ? `COPYRIGHTED WORK:\n${input.copyrightedWork}` : ''}
${input.accusedContent ? `\nACCUSED CONTENT:\n${input.accusedContent}` : ''}
${input.platform ? `\nPLATFORM: ${input.platform}` : ''}
${input.claimantInfo ? `\nCLAIMANT INFO:\n${input.claimantInfo}` : ''}
${input.receivedNoticeText ? `\nRECEIVED NOTICE TEXT:\n${input.receivedNoticeText.slice(0, 10000)}` : ''}
${input.context ? `\nADDITIONAL CONTEXT:\n${input.context}` : ''}

Run the DMCA analysis. Return only the JSON object.
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
      console.error('[dmca-takedown] JSON parse failed');
    }
  }

  return {
    mode: input.mode,
    fair_use: parsed.fair_use ?? undefined,
    section_512f_risk: parsed.section_512f_risk === true,
    section_512f_notes: Array.isArray(parsed.section_512f_notes) ? parsed.section_512f_notes : [],
    elements_512c3: parsed.elements_512c3 ?? undefined,
    elements_512g3: parsed.elements_512g3 ?? undefined,
    draft_notice: parsed.draft_notice ?? undefined,
    draft_counter_notice: parsed.draft_counter_notice ?? undefined,
    platform_notes: Array.isArray(parsed.platform_notes) ? parsed.platform_notes : [],
    next_steps: Array.isArray(parsed.next_steps) ? parsed.next_steps : [],
    blocked: parsed.blocked === true,
    blocked_reason: parsed.blocked_reason ?? undefined,
    disclaimer: DISCLAIMER,
  };
}
