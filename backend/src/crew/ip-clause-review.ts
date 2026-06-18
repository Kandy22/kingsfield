/**
 * IP Clause Review — crew agent.
 *
 * Reviews IP-related clauses in contracts: assignment, license, work-for-hire,
 * confidentiality/trade-secret, non-compete/non-solicit, indemnification,
 * ownership, and field-of-use restrictions.
 *
 * Adapted from claude-for-legal ip-clause-review spec.
 *
 * Key constraints:
 * - Gap check FIRST: does the document have the required clauses at all?
 * - Clause-by-clause analysis: what it says, what it misses, redline suggestion.
 * - Assignment gap: who owns IP created during performance? Confirm present
 *   and adequate or flag as critical gap.
 * - Work-for-hire: §101 / §101(2) criteria check for each relevant work type.
 * - Never drafts final contract language — produces surgical redline suggestions
 *   for attorney review only.
 * - Output: structured JSON only.
 */

import { completeText } from '../lib/llm/index.js';

// ── Types ─────────────────────────────────────────────────────────────────

export type ClauseType =
  | 'assignment'
  | 'license'
  | 'work_for_hire'
  | 'confidentiality'
  | 'non_compete'
  | 'non_solicit'
  | 'indemnification'
  | 'ownership'
  | 'field_of_use'
  | 'background_ip'
  | 'foreground_ip'
  | 'moral_rights'
  | 'publicity_rights'
  | 'open_source'
  | 'other';

export type ClauseSeverity = 'critical' | 'high' | 'medium' | 'low' | 'info';

export interface ClauseFinding {
  clause_type: ClauseType;
  present: boolean;
  location: string;           // quote or section reference (≤120 chars)
  issue: string;              // what's wrong or missing
  severity: ClauseSeverity;
  redline_suggestion: string; // surgical suggested fix for attorney review
  rationale: string;
}

export interface AssignmentGapCheck {
  ip_assignment_present: boolean;
  covers_inventions: boolean;
  covers_works_of_authorship: boolean;
  covers_improvements: boolean;
  present_assignments_only: boolean;   // "hereby assigns" vs. "agrees to assign"
  carve_out_present: boolean;          // employee carve-out for prior IP
  gap_summary: string;
}

export interface WorkForHireCheck {
  work_for_hire_clause_present: boolean;
  work_types_covered: string[];
  section_101_categories_met: boolean; // at least one §101(2) category applies
  independent_contractor_risk: boolean; // contractor = no automatic WFH
  recommendation: string;
}

export interface IpClauseReviewOutput {
  document_name: string;
  contract_type: string;                 // inferred: 'employment', 'consulting', 'license', 'M&A', 'other'
  assignment_gap: AssignmentGapCheck;
  work_for_hire: WorkForHireCheck;
  findings: ClauseFinding[];
  missing_critical_clauses: ClauseType[];
  overall_risk: 'critical' | 'high' | 'medium' | 'low';
  priority_fixes: string[];              // ordered top-5 actions for attorney
  open_source_flag: boolean;
  open_source_note: string;
  disclaimer: string;
}

// ── System prompt ─────────────────────────────────────────────────────────

const CLAUSE_REVIEW_SYSTEM_PROMPT = `
You are an IP contract review engine for litigation support software. You analyze
contracts for IP-related clause gaps, weaknesses, and risks.

CRITICAL CONSTRAINTS:
1. Check for the assignment gap FIRST: is there a clause that assigns IP created
   during performance to the correct party? "Agrees to assign" is weaker than
   "hereby assigns" — flag the difference.
2. Work-for-hire check: for any clause relying on work-for-hire, verify that
   17 U.S.C. §101(2) categories apply (commissioned work in one of nine
   enumerated categories AND written agreement signed by both parties).
   Employees: work within scope of employment qualifies automatically.
   Independent contractors: ONLY if within a §101(2) category AND agreement signed.
3. Open source: flag any mention of GPL, LGPL, AGPL, or other copyleft licenses.
   Copyleft in a product can require open-sourcing proprietary code — this is
   almost always a critical finding in M&A or product contracts.
4. Never draft final contract language. Produce surgical suggestions only, clearly
   labeled "SUGGESTION FOR ATTORNEY REVIEW."
5. Return ONLY valid JSON. No preamble, no markdown fences.

Required output schema:
{
  "document_name": "string",
  "contract_type": "employment|consulting|license|M&A|other",
  "assignment_gap": {
    "ip_assignment_present": true|false,
    "covers_inventions": true|false,
    "covers_works_of_authorship": true|false,
    "covers_improvements": true|false,
    "present_assignments_only": true|false,
    "carve_out_present": true|false,
    "gap_summary": "string"
  },
  "work_for_hire": {
    "work_for_hire_clause_present": true|false,
    "work_types_covered": ["string"],
    "section_101_categories_met": true|false,
    "independent_contractor_risk": true|false,
    "recommendation": "string"
  },
  "findings": [
    {
      "clause_type": "assignment|license|work_for_hire|confidentiality|non_compete|non_solicit|indemnification|ownership|field_of_use|background_ip|foreground_ip|moral_rights|publicity_rights|open_source|other",
      "present": true|false,
      "location": "string (≤120 chars, quote or section ref)",
      "issue": "string",
      "severity": "critical|high|medium|low|info",
      "redline_suggestion": "SUGGESTION FOR ATTORNEY REVIEW: string",
      "rationale": "string"
    }
  ],
  "missing_critical_clauses": ["clause_type", ...],
  "overall_risk": "critical|high|medium|low",
  "priority_fixes": ["string", ...],
  "open_source_flag": true|false,
  "open_source_note": "string",
  "disclaimer": "These findings are for attorney review only and do not constitute legal advice."
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
  'These findings are for attorney review only and do not constitute legal advice.';

// ── Main ──────────────────────────────────────────────────────────────────

export async function runIpClauseReview(
  input: {
    documentText: string;
    documentName: string;
    /** Optional focus: which clause types to prioritize. */
    focusClauses?: ClauseType[];
    /** Party perspective: 'assignor' | 'assignee' | 'licensor' | 'licensee' | 'neutral' */
    perspective?: string;
  },
  model: string,
): Promise<IpClauseReviewOutput> {
  const focusNote = input.focusClauses?.length
    ? `Focus especially on these clause types: ${input.focusClauses.join(', ')}.`
    : 'Review all IP-related clause types.';

  const perspNote = input.perspective
    ? `Party perspective: ${input.perspective}.`
    : '';

  const raw = await completeText({
    model,
    systemPrompt: CLAUSE_REVIEW_SYSTEM_PROMPT,
    user: `
DOCUMENT: ${input.documentName}
${perspNote}
${focusNote}

CONTRACT TEXT (truncated at 40,000 chars):
${input.documentText.slice(0, 40000)}

Run the IP clause review. Return only the JSON object.
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
      console.error('[ip-clause-review] JSON parse failed');
    }
  }

  return {
    document_name: parsed.document_name ?? input.documentName,
    contract_type: parsed.contract_type ?? 'other',
    assignment_gap: parsed.assignment_gap ?? {
      ip_assignment_present: false,
      covers_inventions: false,
      covers_works_of_authorship: false,
      covers_improvements: false,
      present_assignments_only: false,
      carve_out_present: false,
      gap_summary: 'Unable to parse assignment gap analysis.',
    },
    work_for_hire: parsed.work_for_hire ?? {
      work_for_hire_clause_present: false,
      work_types_covered: [],
      section_101_categories_met: false,
      independent_contractor_risk: false,
      recommendation: 'Unable to parse work-for-hire analysis.',
    },
    findings: Array.isArray(parsed.findings) ? parsed.findings : [],
    missing_critical_clauses: Array.isArray(parsed.missing_critical_clauses)
      ? parsed.missing_critical_clauses
      : [],
    overall_risk: parsed.overall_risk ?? 'high',
    priority_fixes: Array.isArray(parsed.priority_fixes) ? parsed.priority_fixes : [],
    open_source_flag: parsed.open_source_flag === true,
    open_source_note: parsed.open_source_note ?? '',
    disclaimer: DISCLAIMER,
  };
}
