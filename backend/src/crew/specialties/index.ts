/**
 * Specialty agents index.
 *
 * Each specialty is a vertical practice area agent with curated doctrine,
 * starred cases, and structured JSON output.
 *
 * Routing: the coordinator's detectTaskType() maps keywords → specialty.
 * Each specialty returns a structured output that formatSpecialtyReply()
 * converts to the user-facing Markdown.
 *
 * Available specialties:
 *   veterans_health      — 38 U.S.C./CFR, VA claims, BVA, CAVC appeals
 *   security_clearance   — DoD adjudicative guidelines, DOHA, SAP/SCI
 *   ai_legal_tech        — training data copyright, EU AI Act, ethics
 *   crypto_howey         — Howey test, SEC/CFTC/FinCEN, NFTs, DeFi
 *   entertainment_talent — talent agreements, recording, music rights, ROP
 */

export { runVeteransHealthSpecialist } from './veterans-health.js';
export type { VeteransHealthInput, VeteransHealthOutput } from './veterans-health.js';

export { runSecurityClearanceSpecialist } from './security-clearance.js';
export type { SecurityClearanceInput, SecurityClearanceOutput } from './security-clearance.js';

export { runAiLegalTechSpecialist } from './ai-legal-tech.js';
export type { AiLegalTechInput, AiLegalTechOutput } from './ai-legal-tech.js';

export { runCryptoHoweySpecialist } from './crypto-howey.js';
export type { CryptoHoweyInput, CryptoHoweyOutput } from './crypto-howey.js';

export { runEntertainmentTalentSpecialist } from './entertainment-talent.js';
export type { EntertainmentTalentInput, EntertainmentTalentOutput } from './entertainment-talent.js';

export type SpecialtyType =
  | 'veterans_health'
  | 'security_clearance'
  | 'ai_legal_tech'
  | 'crypto_howey'
  | 'entertainment_talent';
