/**
 * Specialty Agent: Entertainment, Talent & IP.
 *
 * Covers:
 *   - Talent representation: agency vs. management (Talent Agencies Act, Cal.)
 *   - 7-year rule (Cal. Labor Code §2855) — personal service contract max
 *   - Recording contracts: 360 deals, advances, royalty accounting, recoupment,
 *     controlled composition clauses, audit rights
 *   - Music publishing: sync licensing, master licensing, PROs (ASCAP/BMI/SESAC/GMR)
 *   - Guild agreements: SAG-AFTRA, WGA, DGA minimums and residuals
 *   - Right of publicity (Cal. Civil Code §3344, §3344.1 posthumous; NY NYPPL §50-51)
 *   - Copyright in film/TV: work for hire, underlying rights acquisition,
 *     option/purchase agreements
 *   - Defamation in entertainment (actual malice; fact vs. opinion)
 *   - AI and entertainment: AI voice cloning, synthetic performers, UCC Art. 2
 *   - Music copyright: *Blurred Lines* / *Stairway to Heaven* thin copyright;
 *     sampling without license (*Bridgeport* rule)
 *
 * Starred cases:
 *   De Havilland v. Warner Bros. (Cal. App. 1944) — 7-year rule
 *   Newton v. Diamond (9th Cir. 2004) — de minimis sampling
 *   Bridgeport Music v. Dimension Films (6th Cir. 2005) — no de minimis for sound recordings
 *   Williams v. Gaye (9th Cir. 2018) — "Blurred Lines" / feel/groove copyright
 *   Led Zeppelin v. Spirit (9th Cir. en banc 2020) — thin copyright, independent creation
 *   Midler v. Ford Motor Co. (9th Cir. 1988) — voice right of publicity
 *   White v. Samsung (9th Cir. 1992) — likeness right of publicity
 *   Talent Agencies Act (Cal. Labor Code §1700 et seq.)
 */

import { completeText } from '../../lib/llm/index.js';

export type EntertainmentArea =
  | 'talent_representation'
  | 'recording_contract'
  | 'music_publishing'
  | 'film_tv_copyright'
  | 'guild_agreement'
  | 'right_of_publicity'
  | 'sampling'
  | 'defamation'
  | 'ai_entertainment'
  | 'sync_licensing'
  | 'other';

export interface EntertainmentTalentInput {
  question: string;
  matterContext?: string;
  areas?: EntertainmentArea[];
  /** State (CA is presumed for talent/labor; NY for right of publicity). */
  jurisdiction?: string;
  documentText?: string;
  documentName?: string;
}

export interface EntertainmentTalentOutput {
  analysis: string;
  areas_identified: EntertainmentArea[];
  // Talent-specific
  taa_issues: string[];               // Talent Agencies Act issues
  seven_year_rule_applies: boolean;
  seven_year_note: string;
  // Recording/publishing
  recoupment_issues: string[];
  audit_right_present: boolean;
  controlled_composition_flag: boolean;
  // Guild/union
  guild_minimums_met: boolean;
  guild_notes: string[];
  // Copyright
  work_for_hire_analysis: string;
  sampling_risk: string;
  thin_copyright_note: string;
  // Right of publicity
  rop_analysis: string;
  posthumous_rights_applicable: boolean;
  // AI-specific
  ai_voice_cloning_risk: string;
  // Defamation
  defamation_flags: string[];
  starred_cases: { citation: string; relevance: string }[];
  next_steps: string[];
  disclaimer: string;
}

const SYSTEM_PROMPT = `
You are the Kingsfield Entertainment, Talent & IP specialist. You analyze
entertainment industry agreements, talent representation, music rights, film/TV
copyright, and right of publicity matters.

TALENT AGENCIES ACT (Cal. Labor Code §1700 et seq.):
  Only licensed talent agents may procure employment for artists.
  Managers who procure = practicing without a license = contract voidable.
  SB 171 (2022): managers may negotiate (not procure) without a license.
  Test: does the activity constitute "procuring" employment?

7-YEAR RULE (Cal. Labor Code §2855):
  Personal service contracts for unique services enforceable for max 7 years.
  De Havilland v. Warner Bros. (Cal. App. 1944): studios could not enjoin
  beyond 7 years. Still invoked in recording and film contracts.

RECORDING CONTRACTS:
  Royalties: typically 12-20% of retail/wholesale. Recoupment from royalties only
  (not mechanical rate, unless cross-collateralized).
  360 deals: label takes % of all revenue streams (touring, merch, sponsorships).
  Controlled composition: label pays 75% of statutory mechanical rate for songs
  artist "controls." Never agree to this without understanding the math.
  Audit right: standard 2-year audit window. Track audit trigger language.
  Reversion: copyright reversion after 35 years (17 U.S.C. §203) — non-waivable.

MUSIC PUBLISHING & SYNC:
  Sync license: grants right to use composition in visual media. Master license:
  use of specific sound recording. Both required for film/TV placement.
  PRO affiliation: ASCAP / BMI / SESAC / GMR — publisher and writer splits.
  Statutory mechanical rate: applies to digital downloads and physical; streaming
  governed by Copyright Royalty Board rates.

GUILD MINIMUMS (2024-2025):
  SAG-AFTRA: theatrical scale; new media; AI/digital replica provisions (2023 strike).
  WGA: minimums by type; residuals from streaming (post-2023 agreement).
  DGA: director minimums; creative rights; director's cut; sequel rights.

RIGHT OF PUBLICITY:
  California (§3344): commercial use of name/likeness without consent = liable.
  (§3344.1): posthumous rights — 70 years after death. Covers digital replicas.
  New York (NYPPL §50-51): narrower; no posthumous rights (for now; legislation pending).
  Transformative use defense: *Comedy III v. Saderup* (Cal. 2001).
  AI voice cloning: implicates right of publicity AND Lanham Act (false endorsement).

SAMPLING:
  6th Circuit (Bridgeport): ANY sampling of a sound recording without license =
  infringement. No de minimis defense for sound recordings.
  9th Circuit (Newton): de minimis applies to the COMPOSITION (not the recording).
  Clear both: master AND composition for any sample.

THIN COPYRIGHT / MUSICAL ELEMENTS:
  Blurred Lines: feel, groove, and style are not copyrightable; specific expression is.
  Stairway to Heaven (en banc): independent creation is a complete defense.
  Copyright in music = specific notes, rhythm, melody in expression — not a "genre feel."

AI IN ENTERTAINMENT:
  AI voice cloning without consent = right of publicity violation (Cal. §3344 + Midler).
  AI-generated performances: SAG-AFTRA 2023 agreement requires consent + compensation.
  AI-generated works: uncopyrightable without human authorship (Thaler v. Perlmutter).
  Studios using AI to replace writers: WGA 2023 agreement prohibits without consent.

Output: structured JSON only. No preamble, no markdown fences.

Output schema:
{
  "analysis": "string",
  "areas_identified": ["talent_representation|recording_contract|music_publishing|film_tv_copyright|guild_agreement|right_of_publicity|sampling|defamation|ai_entertainment|sync_licensing|other"],
  "taa_issues": ["string"],
  "seven_year_rule_applies": true|false,
  "seven_year_note": "string",
  "recoupment_issues": ["string"],
  "audit_right_present": true|false,
  "controlled_composition_flag": true|false,
  "guild_minimums_met": true|false,
  "guild_notes": ["string"],
  "work_for_hire_analysis": "string",
  "sampling_risk": "string",
  "thin_copyright_note": "string",
  "rop_analysis": "string",
  "posthumous_rights_applicable": true|false,
  "ai_voice_cloning_risk": "string",
  "defamation_flags": ["string"],
  "starred_cases": [{"citation": "string", "relevance": "string"}],
  "next_steps": ["string"],
  "disclaimer": "This analysis is for attorney review. Entertainment and music copyright law is jurisdiction-specific and fact-intensive."
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

export async function runEntertainmentTalentSpecialist(
  input: EntertainmentTalentInput,
  model: string,
): Promise<EntertainmentTalentOutput> {
  const raw = await completeText({
    model,
    systemPrompt: SYSTEM_PROMPT,
    user: `
QUESTION: ${input.question}
${input.areas?.length ? `\nAREAS: ${input.areas.join(', ')}` : ''}
${input.jurisdiction ? `\nJURISDICTION: ${input.jurisdiction}` : ''}
${input.matterContext ? `\nMATTER CONTEXT:\n${input.matterContext}` : ''}
${input.documentText ? `\nDOCUMENT (${input.documentName ?? 'attached'}):\n${input.documentText.slice(0, 20000)}` : ''}

Analyze under entertainment law. Return only the JSON object.
    `.trim(),
    maxTokens: 4096,
  });

  const json = stripFences(raw.trim());
  let parsed: any = {};
  try { parsed = JSON.parse(json); }
  catch { try { parsed = JSON.parse(recoverTruncatedJson(json)); } catch { console.error('[entertainment-talent] JSON parse failed'); } }

  return {
    analysis: parsed.analysis ?? '',
    areas_identified: Array.isArray(parsed.areas_identified) ? parsed.areas_identified : [],
    taa_issues: Array.isArray(parsed.taa_issues) ? parsed.taa_issues : [],
    seven_year_rule_applies: parsed.seven_year_rule_applies === true,
    seven_year_note: parsed.seven_year_note ?? '',
    recoupment_issues: Array.isArray(parsed.recoupment_issues) ? parsed.recoupment_issues : [],
    audit_right_present: parsed.audit_right_present === true,
    controlled_composition_flag: parsed.controlled_composition_flag === true,
    guild_minimums_met: parsed.guild_minimums_met !== false,
    guild_notes: Array.isArray(parsed.guild_notes) ? parsed.guild_notes : [],
    work_for_hire_analysis: parsed.work_for_hire_analysis ?? '',
    sampling_risk: parsed.sampling_risk ?? '',
    thin_copyright_note: parsed.thin_copyright_note ?? '',
    rop_analysis: parsed.rop_analysis ?? '',
    posthumous_rights_applicable: parsed.posthumous_rights_applicable === true,
    ai_voice_cloning_risk: parsed.ai_voice_cloning_risk ?? '',
    defamation_flags: Array.isArray(parsed.defamation_flags) ? parsed.defamation_flags : [],
    starred_cases: Array.isArray(parsed.starred_cases) ? parsed.starred_cases : [],
    next_steps: Array.isArray(parsed.next_steps) ? parsed.next_steps : [],
    disclaimer: 'This analysis is for attorney review. Entertainment and music copyright law is jurisdiction-specific and fact-intensive.',
  };
}
