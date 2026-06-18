/**
 * Specialty Agent: AI / Legal Technology Law.
 *
 * Covers the fast-moving intersection of AI systems and law:
 *   - Training data copyright (ingestion, fair use, opt-out)
 *   - AI output ownership and authorship
 *   - Products liability for AI systems (design defect, failure to warn)
 *   - Negligence and professional liability in AI-assisted practice
 *   - EU AI Act compliance (risk tiers, prohibited uses, GPAI rules)
 *   - Algorithmic accountability / disparate impact (ECOA, FHA, FCRA)
 *   - Deepfake / synthetic media liability
 *   - AI and attorney ethics (ABA Model Rules, state bar guidance)
 *   - Contracting for AI: IP ownership in B2B AI contracts
 *
 * Starred cases / materials:
 *   Thaler v. Perlmutter (D.D.C. 2023) — AI-generated works lack copyright
 *   Authors Guild v. OpenAI (ongoing, S.D.N.Y.)
 *   Getty Images v. Stability AI (D. Del., ongoing)
 *   Andersen v. Stability AI (N.D. Cal., ongoing) — style not copyrightable
 *   Clearview AI cases — biometric privacy, § 1983
 *   EU AI Act (Regulation 2024/1689, fully applicable 2 Aug 2026)
 *   NIST AI RMF (2023) — governance framework (not law but referenced)
 *   ABA Formal Opinion 512 (2023) — generative AI in legal practice
 */

import { completeText } from '../../lib/llm/index.js';

export type AiRiskTier = 'prohibited' | 'high_risk' | 'limited_risk' | 'minimal_risk' | 'gpai' | 'unknown';

export interface AiLegalTechInput {
  question: string;
  matterContext?: string;
  /** Description of the AI system or use case at issue. */
  systemDescription?: string;
  /** Jurisdiction focus: 'us' | 'eu' | 'both' */
  jurisdiction?: string;
  documentText?: string;
  documentName?: string;
}

export interface TrainingDataAnalysis {
  fair_use_factors: {
    purpose_and_character: string;
    nature_of_work: string;
    amount_taken: string;
    market_effect: string;
  };
  fair_use_conclusion: 'likely' | 'unlikely' | 'unclear';
  opt_out_mechanisms_exist: boolean;
  robots_txt_honored: boolean;
  tos_violations: string[];
  key_risk: string;
}

export interface EuAiActAnalysis {
  risk_tier: AiRiskTier;
  tier_rationale: string;
  compliance_obligations: string[];
  prohibited_use_flags: string[];
  gpai_model_rules: string;
}

export interface AiLegalTechOutput {
  analysis: string;
  training_data?: TrainingDataAnalysis;
  output_ownership: string;    // who owns AI-generated outputs
  products_liability_risk: string;
  negligence_risk: string;
  eu_ai_act?: EuAiActAnalysis;
  algorithmic_bias_flags: string[];
  ethics_flags: string[];      // attorney ethics / bar rule issues
  deepfake_flags: string[];
  contract_ip_issues: string[];
  starred_cases: { citation: string; relevance: string }[];
  next_steps: string[];
  disclaimer: string;
}

const SYSTEM_PROMPT = `
You are the Kingsfield AI/Legal Technology specialist. You analyze legal issues
arising from AI systems, training data, and AI-assisted legal practice.

TRAINING DATA COPYRIGHT:
- Ingestion of copyrighted works for ML training: currently litigated in multiple
  circuits. Authors Guild v. OpenAI, Getty v. Stability AI, Andersen v. Stability.
- Fair use four-factor analysis applies. Courts split on "transformation" argument.
- opt-out mechanisms (robots.txt, C2PA, AI training opt-out signals): relevant to
  willfulness, not a legal defense.
- Terms of service violations: separate from copyright — breach of contract, not IP.
- Memorization / verbatim output: higher infringement risk than statistical patterns.

AI OUTPUT OWNERSHIP (17 U.S.C.):
- Thaler v. Perlmutter (D.D.C. 2023): AI-generated works with no human authorship
  = uncopyrightable. Human creative selection/arrangement of AI output may qualify.
- Zarya of the Dawn (Copyright Office 2023): human-written text copyrightable;
  AI-generated images within the work not copyrightable.
- Patent inventorship: AI cannot be named inventor (Thaler v. Vidal, Fed. Cir. 2022).

PRODUCTS LIABILITY:
- AI as product: design defect (was the system unreasonably dangerous?),
  failure to warn (did the interface adequately disclose AI limitations?).
- Learned intermediary doctrine: if a professional uses the AI, does liability
  shift to the professional?
- Section 230 protection: may not apply to AI-generated content that is not
  purely third-party content.

EU AI ACT (Regulation 2024/1689):
- Prohibited (Art. 5): real-time biometric ID in public spaces, social scoring,
  subliminal manipulation, exploitation of vulnerabilities.
- High-risk (Annex III): biometrics, critical infrastructure, education, employment,
  access to services, law enforcement, migration, justice/democratic processes.
- GPAI (General Purpose AI) rules: for foundation models. Systemic risk designation
  (>10^25 FLOPs) triggers enhanced obligations.
- Fully applicable: 2 August 2026. Prohibited uses: 2 February 2025.

ATTORNEY ETHICS (ABA Formal Opinion 512, 2023):
- Competence (Rule 1.1): must understand the tool being used.
- Supervision (Rule 5.1/5.3): supervise AI output; can't outsource judgment.
- Confidentiality (Rule 1.6): sending client data to third-party AI = disclosure.
- Candor to tribunal (Rule 3.3): verify all citations. Hallucinated cites = sanctionable.
- Fees (Rule 1.5): AI efficiency gains don't justify same billing rate x same hours.

ALGORITHMIC BIAS:
- ECOA / Reg B: disparate impact on protected classes in credit decisions.
- FHA: disparate impact in housing (Texas Dept. of Housing v. Inclusive Communities, SCOTUS 2015).
- FCRA: automated decisions using consumer reports — adverse action notice required.
- NYC Local Law 144: automated employment decision tools — annual bias audit required.

Output: structured JSON only. No preamble, no markdown fences.

Output schema:
{
  "analysis": "string",
  "training_data": {
    "fair_use_factors": {
      "purpose_and_character": "string",
      "nature_of_work": "string",
      "amount_taken": "string",
      "market_effect": "string"
    },
    "fair_use_conclusion": "likely|unlikely|unclear",
    "opt_out_mechanisms_exist": true|false,
    "robots_txt_honored": true|false,
    "tos_violations": ["string"],
    "key_risk": "string"
  } | null,
  "output_ownership": "string",
  "products_liability_risk": "string",
  "negligence_risk": "string",
  "eu_ai_act": {
    "risk_tier": "prohibited|high_risk|limited_risk|minimal_risk|gpai|unknown",
    "tier_rationale": "string",
    "compliance_obligations": ["string"],
    "prohibited_use_flags": ["string"],
    "gpai_model_rules": "string"
  } | null,
  "algorithmic_bias_flags": ["string"],
  "ethics_flags": ["string"],
  "deepfake_flags": ["string"],
  "contract_ip_issues": ["string"],
  "starred_cases": [{"citation": "string", "relevance": "string"}],
  "next_steps": ["string"],
  "disclaimer": "This analysis is for attorney review. AI law is rapidly evolving — verify against current case law and regulatory guidance before advising."
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

export async function runAiLegalTechSpecialist(
  input: AiLegalTechInput,
  model: string,
): Promise<AiLegalTechOutput> {
  const raw = await completeText({
    model,
    systemPrompt: SYSTEM_PROMPT,
    user: `
QUESTION: ${input.question}
${input.systemDescription ? `\nAI SYSTEM / USE CASE: ${input.systemDescription}` : ''}
${input.jurisdiction ? `\nJURISDICTION FOCUS: ${input.jurisdiction}` : ''}
${input.matterContext ? `\nMATTER CONTEXT:\n${input.matterContext}` : ''}
${input.documentText ? `\nDOCUMENT (${input.documentName ?? 'attached'}):\n${input.documentText.slice(0, 20000)}` : ''}

Run the full AI law analysis. Return only the JSON object.
    `.trim(),
    maxTokens: 4096,
  });

  const json = stripFences(raw.trim());
  let parsed: any = {};
  try { parsed = JSON.parse(json); }
  catch { try { parsed = JSON.parse(recoverTruncatedJson(json)); } catch { console.error('[ai-legal-tech] JSON parse failed'); } }

  return {
    analysis: parsed.analysis ?? '',
    training_data: parsed.training_data ?? undefined,
    output_ownership: parsed.output_ownership ?? '',
    products_liability_risk: parsed.products_liability_risk ?? '',
    negligence_risk: parsed.negligence_risk ?? '',
    eu_ai_act: parsed.eu_ai_act ?? undefined,
    algorithmic_bias_flags: Array.isArray(parsed.algorithmic_bias_flags) ? parsed.algorithmic_bias_flags : [],
    ethics_flags: Array.isArray(parsed.ethics_flags) ? parsed.ethics_flags : [],
    deepfake_flags: Array.isArray(parsed.deepfake_flags) ? parsed.deepfake_flags : [],
    contract_ip_issues: Array.isArray(parsed.contract_ip_issues) ? parsed.contract_ip_issues : [],
    starred_cases: Array.isArray(parsed.starred_cases) ? parsed.starred_cases : [],
    next_steps: Array.isArray(parsed.next_steps) ? parsed.next_steps : [],
    disclaimer: 'This analysis is for attorney review. AI law is rapidly evolving — verify against current case law and regulatory guidance before advising.',
  };
}
