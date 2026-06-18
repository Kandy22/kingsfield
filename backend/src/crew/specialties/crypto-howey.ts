/**
 * Specialty Agent: Crypto / Digital Assets — Howey Test & Regulatory Analysis.
 *
 * Covers:
 *   - SEC v. W.J. Howey Co. four-prong test for investment contracts
 *   - Reves test for notes (family resemblance)
 *   - DAO Report (SEC, 2017)
 *   - SEC enforcement actions: Ripple (XRP), Coinbase, Binance, LBRY
 *   - CFTC jurisdiction (commodities — BTC, ETH post-Merge debate)
 *   - State money transmission / BitLicense
 *   - Stablecoin regulation (pending federal framework)
 *   - DeFi: protocol vs. UI operator liability
 *   - NFTs as securities (SEC enforcement against Impact Theory, etc.)
 *   - Token classification: utility vs. security vs. commodity vs. currency
 *
 * Starred cases / materials:
 *   SEC v. W.J. Howey Co., 328 U.S. 293 (1946)
 *   SEC v. Ripple Labs, Inc. (S.D.N.Y. 2023) — programmatic sales distinction
 *   Reves v. Ernst & Young, 494 U.S. 56 (1990) — notes test
 *   In re DAO Report (SEC Release No. 81207, 2017)
 *   SEC v. Telegram Group (S.D.N.Y. 2020) — SAFT analysis
 *   United States v. Ulbricht (2d Cir. 2015) — BTC as funds
 *   CFTC v. BitMEX (S.D.N.Y. 2021)
 */

import { completeText } from '../../lib/llm/index.js';

export interface CryptoHoweyInput {
  question: string;
  matterContext?: string;
  /** Description of the token, protocol, or instrument at issue. */
  tokenDescription?: string;
  /** Specific regulatory concern: 'sec' | 'cftc' | 'fincen' | 'state' | 'all' */
  regulatoryFocus?: string;
  documentText?: string;
  documentName?: string;
}

export interface HoweyProng {
  prong: 'investment_of_money' | 'common_enterprise' | 'expectation_of_profits' | 'efforts_of_others';
  satisfied: 'yes' | 'no' | 'unclear';
  analysis: string;
  counterargument: string;
}

export interface CryptoHoweyOutput {
  howey_analysis: HoweyProng[];
  howey_conclusion: 'likely_security' | 'likely_not_security' | 'unclear';
  reves_applicable: boolean;
  reves_note: string;
  cftc_jurisdiction_risk: boolean;
  cftc_note: string;
  fincen_msa_risk: boolean;     // money services business / money transmission
  fincen_note: string;
  state_law_flags: string[];
  nft_specific_issues: string[];
  defi_specific_issues: string[];
  regulatory_posture: string;   // overall risk narrative
  starred_cases: { citation: string; relevance: string }[];
  next_steps: string[];
  disclaimer: string;
}

const SYSTEM_PROMPT = `
You are the Kingsfield Crypto/Digital Assets specialist. You analyze token
classification, regulatory jurisdiction, and enforcement risk for digital assets.

HOWEY TEST — SEC v. W.J. Howey Co., 328 U.S. 293 (1946):
Four-prong test for "investment contract" = security:
  1. Investment of money — broadly construed; BTC/ETH counts (Howey uses "money or money's worth")
  2. Common enterprise — horizontal (pooled funds) or vertical (investor fortunes tied to promoter)
  3. Expectation of profits — including capital appreciation, not just dividends
  4. From the efforts of others — efforts of a third party essential to the return

RIPPLE DISTINCTION (SEC v. Ripple Labs, S.D.N.Y. 2023):
  Institutional sales of XRP = securities (knew buyers were investing)
  Programmatic exchange sales ≠ securities (anonymous buyers had no reasonable expectation
  of promoter's efforts; no direct relationship)
  This distinction matters for how tokens are sold, not just what they are.

REVES TEST — notes:
  Notes are presumptively securities unless they fall within a "family resemblance"
  exception: short-term notes, consumer financing, business loan notes, etc.
  Four-factor test: motivation of buyer/seller, plan of distribution, reasonable
  expectations of investing public, risk-reducing factors.

DAO REPORT (2017): Token sales for project development = securities. The issuer's
continued efforts to develop the ecosystem = "efforts of others."

TELEGRAM / SAFT: Future delivery of tokens (SAFTs) analyzed under Howey at time of
original sale and at delivery. If the network isn't "sufficiently decentralized" at
delivery, the analysis may still apply.

CFTC JURISDICTION: Bitcoin = commodity (Commodity Exchange Act). Ethereum post-Merge
= contested (CFTC: commodity; SEC: potential security). CFTC has anti-fraud/anti-
manipulation jurisdiction over all commodities in interstate commerce.

FinCEN / MSB: Exchanges, administrators, and (some) DeFi protocols = Money Services
Businesses requiring BSA/AML compliance. Exchangers of "value that substitutes for
currency" = money transmitters.

NFTs AS SECURITIES: SEC has brought enforcement (Impact Theory, Stoner Cats) where
NFTs were sold with expectation of appreciation tied to issuer's efforts. "Fractional"
NFTs and royalty-bearing NFTs face heightened risk.

DeFi: Protocol code ≠ operator. UI operators and governance token holders face more
risk than pure smart contract usage. CFTC v. Ooki DAO: DAO members who voted = liable.

Constraints:
- State the Howey prong analysis for each prong, separately.
- Note the Ripple programmatic-sale distinction explicitly when relevant.
- Flag FinCEN MSB risk separately from SEC/CFTC — different agencies, different exposure.
- Output: structured JSON only. No preamble, no markdown fences.

Output schema:
{
  "howey_analysis": [
    {
      "prong": "investment_of_money|common_enterprise|expectation_of_profits|efforts_of_others",
      "satisfied": "yes|no|unclear",
      "analysis": "string",
      "counterargument": "string"
    }
  ],
  "howey_conclusion": "likely_security|likely_not_security|unclear",
  "reves_applicable": true|false,
  "reves_note": "string",
  "cftc_jurisdiction_risk": true|false,
  "cftc_note": "string",
  "fincen_msa_risk": true|false,
  "fincen_note": "string",
  "state_law_flags": ["string"],
  "nft_specific_issues": ["string"],
  "defi_specific_issues": ["string"],
  "regulatory_posture": "string",
  "starred_cases": [{"citation": "string", "relevance": "string"}],
  "next_steps": ["string"],
  "disclaimer": "This analysis is for attorney review. Digital asset regulation is unsettled and enforcement-driven. Do not rely on this analysis without current regulatory guidance."
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

export async function runCryptoHoweySpecialist(
  input: CryptoHoweyInput,
  model: string,
): Promise<CryptoHoweyOutput> {
  const raw = await completeText({
    model,
    systemPrompt: SYSTEM_PROMPT,
    user: `
QUESTION: ${input.question}
${input.tokenDescription ? `\nTOKEN / INSTRUMENT: ${input.tokenDescription}` : ''}
${input.regulatoryFocus ? `\nREGULATORY FOCUS: ${input.regulatoryFocus}` : ''}
${input.matterContext ? `\nMATTER CONTEXT:\n${input.matterContext}` : ''}
${input.documentText ? `\nDOCUMENT (${input.documentName ?? 'attached'}):\n${input.documentText.slice(0, 20000)}` : ''}

Run the Howey analysis and full regulatory assessment. Return only the JSON object.
    `.trim(),
    maxTokens: 4096,
  });

  const json = stripFences(raw.trim());
  let parsed: any = {};
  try { parsed = JSON.parse(json); }
  catch { try { parsed = JSON.parse(recoverTruncatedJson(json)); } catch { console.error('[crypto-howey] JSON parse failed'); } }

  return {
    howey_analysis: Array.isArray(parsed.howey_analysis) ? parsed.howey_analysis : [],
    howey_conclusion: parsed.howey_conclusion ?? 'unclear',
    reves_applicable: parsed.reves_applicable === true,
    reves_note: parsed.reves_note ?? '',
    cftc_jurisdiction_risk: parsed.cftc_jurisdiction_risk === true,
    cftc_note: parsed.cftc_note ?? '',
    fincen_msa_risk: parsed.fincen_msa_risk === true,
    fincen_note: parsed.fincen_note ?? '',
    state_law_flags: Array.isArray(parsed.state_law_flags) ? parsed.state_law_flags : [],
    nft_specific_issues: Array.isArray(parsed.nft_specific_issues) ? parsed.nft_specific_issues : [],
    defi_specific_issues: Array.isArray(parsed.defi_specific_issues) ? parsed.defi_specific_issues : [],
    regulatory_posture: parsed.regulatory_posture ?? '',
    starred_cases: Array.isArray(parsed.starred_cases) ? parsed.starred_cases : [],
    next_steps: Array.isArray(parsed.next_steps) ? parsed.next_steps : [],
    disclaimer: 'This analysis is for attorney review. Digital asset regulation is unsettled and enforcement-driven. Do not rely on this analysis without current regulatory guidance.',
  };
}
