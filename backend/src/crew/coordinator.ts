/**
 * Crew Role: Team Lead + Coordinator.
 *
 * The Team Lead synthesizes the Researcher, Analyst, and Strategist into
 * a single coherent answer for the user. It also flags places where the
 * three roles disagreed — those flags surface in the UI as "things to
 * double-check before relying on this."
 *
 * The Coordinator is the entry point. It decides which crew roles to
 * spawn for a given user message, runs them in the right order, and
 * returns the Team Lead's synthesis plus a structured trace.
 *
 * Heuristics for which roles to spawn:
 *   - If there's a document attached → Researcher + Analyst + Strategist + Lead
 *   - If pure question / research → Researcher + Strategist + Lead
 *   - If casual / factual / "what is" → no crew, just answer directly
 *     (the Coordinator will return null and the chat falls back to
 *     single-agent mode)
 */

import { completeText } from '../lib/llm/index.js';
import type { SupabaseClient } from '@supabase/supabase-js';
import {
  runResearcher,
  type ResearcherOutput,
  type ResearcherDeps,
  type VerifiedAuthority,
} from './researcher.js';
import {
  runContractAnalyst,
  type AnalystOutput,
} from './contract-analyst.js';
import { runStrategist, type StrategistOutput } from './strategist.js';
import {
  runWritingCoach,
  type WritingCoachOutput,
} from './writing-coach.js';
import {
  runImpeacher,
  type ImpeacherOutput,
} from './impeacher.js';
import {
  runOppositionMapper,
  type OppositionMapperOutput,
} from './opposition-mapper.js';
import {
  runInfringementTriage,
  type InfringementTriageOutput,
} from './infringement-triage.js';
import {
  runIpClauseReview,
  type IpClauseReviewOutput,
} from './ip-clause-review.js';
import {
  runDmcaTakedown,
  type DmcaTakedownOutput,
} from './dmca-takedown.js';
import {
  runVeteransHealthSpecialist,
  runSecurityClearanceSpecialist,
  runAiLegalTechSpecialist,
  runCryptoHoweySpecialist,
  runEntertainmentTalentSpecialist,
  type VeteransHealthOutput,
  type SecurityClearanceOutput,
  type AiLegalTechOutput,
  type CryptoHoweyOutput,
  type EntertainmentTalentOutput,
  type SpecialtyType,
} from './specialties/index.js';

export const TEAM_LEAD_SYSTEM_PROMPT = `
You are the Team Lead on the Kingsfield Legal Crew. Three specialists
have produced inputs: the Researcher (verified authorities), the Contract
Analyst (document findings, if any), and the Strategist (situation,
options, recommendation).

Your job is to produce the single response the user actually sees.

Hard rules:
- You may cite only authorities the Researcher verified.
- If the Strategist and Analyst disagreed, surface it explicitly under
  "Watchouts." Do not paper over disagreement.
- Plain English. Translate Latin and terms of art the first time they
  appear. No filler. No "I hope this helps."
- NEVER tell the user to consult, retain, or hire an attorney. NEVER
  suggest they seek legal counsel or legal advice. You are their legal
  team. Give them direct, actionable analysis and specific next steps they
  can execute themselves. The user knows their own situation.
- Structure your response so the user can scan in 30 seconds and read
  in 3 minutes.

Output structure:

  ## Bottom line
  One paragraph. What we found, what we recommend. Direct and actionable.

  ## Authority
  Bulleted list of verified cites with one-line relevance.

  ## Document findings (if any)
  Top issues by severity.

  ## Recommendation
  The Strategist's recommendation, refined for clarity. Specific actions,
  not general guidance.

  ## Watchouts
  Any disagreement between roles, or any gap the Researcher flagged.

  ## Next step
  ONE concrete action the user can take now.
`.trim();

export type CrewTaskType =
  | 'full_crew'         // Researcher + Analyst + Strategist + Lead
  | 'research_only'     // Researcher + Strategist + Lead (no document)
  | 'writing_coach'     // Writing Coach: persuasive-writing critique
  | 'impeacher'         // Impeacher: deposition contradiction finder
  | 'opposition_map'    // Opposition Mapper: defense theory battle plans
  | 'ip_triage'         // Infringement Triage: multi-track IP triage
  | 'ip_clause_review'  // IP Clause Review: assignment gap + clause analysis
  | 'dmca_takedown'     // DMCA Takedown: send/respond/counter drafter
  | 'specialty'         // Specialty vertical agent (veterans, clearance, AI law, crypto, entertainment)
  | 'simple';           // No crew, single-agent fallback

export interface CrewInput {
  userMessage: string;
  matterContext: string;
  documentName?: string;
  documentText?: string;
  jurisdiction?: string;
  /** Explicit task type override. If omitted, coordinator auto-detects. */
  taskType?: CrewTaskType;
  /**
   * For IMPEACHER tasks: additional transcripts beyond the primary document.
   * Each entry: { witnessName, label, text }
   */
  additionalTranscripts?: Array<{ witnessName: string; label: string; text: string }>;
  /**
   * For OPPOSITION_MAP tasks: the defense theories to map.
   * If omitted, coordinator extracts them from userMessage.
   */
  defenseTheories?: string[];
  /**
   * For IP_TRIAGE tasks: which IP tracks to analyze.
   * Omit for auto-detect.
   */
  ipTracks?: ('trademark' | 'copyright' | 'patent' | 'trade_secret')[];
  /**
   * For DMCA_TAKEDOWN tasks: the mode.
   * 'send' | 'respond' | 'counter' (default: 'send')
   */
  dmcaMode?: 'send' | 'respond' | 'counter';
  /**
   * For SPECIALTY tasks: which specialty to route to.
   * If omitted, coordinator auto-detects from keywords.
   */
  specialty?: SpecialtyType;
}

export interface CrewDeps {
  model: string;
  supabase: SupabaseClient;
  courtListenerToken: string;
}

export interface CrewOutput {
  /** Markdown response shown to the user. */
  reply: string;
  /** Full structured trace for debugging / audit. */
  trace: {
    researcher?: ResearcherOutput;
    analyst?: AnalystOutput;
    strategist?: StrategistOutput;
    writingCoach?: WritingCoachOutput;
    impeacher?: ImpeacherOutput;
    oppositionMapper?: OppositionMapperOutput;
    ipTriage?: InfringementTriageOutput;
    ipClauseReview?: IpClauseReviewOutput;
    dmcaTakedown?: DmcaTakedownOutput;
    specialty?: VeteransHealthOutput | SecurityClearanceOutput | AiLegalTechOutput | CryptoHoweyOutput | EntertainmentTalentOutput;
    specialtyType?: SpecialtyType;
    decision: 'crew' | 'simple';
    taskType: CrewTaskType;
    rolesSpawned: string[];
  };
  /** Verified authorities surfaced in the reply, for downstream chips. */
  authorities: VerifiedAuthority[];
}

/**
 * Auto-detect which crew task type best fits this message.
 * The caller can override by setting input.taskType explicitly.
 */
export function detectTaskType(input: CrewInput): CrewTaskType {
  if (input.taskType) return input.taskType;

  const msg = input.userMessage.toLowerCase().trim();

  // Short / casual → simple
  if (msg.length < 80) return 'simple';
  if (/^(hi|hello|hey|thanks|thank you)\b/.test(msg)) return 'simple';
  if (/^(what (does|is)|define|how do i spell|explain|what is)\b/.test(msg)) return 'simple';
  if (/\b(summarize|summary|what (is|was) the holding|explain the (holding|case|decision))\b/.test(msg)) return 'simple';

  // Writing Coach — explicit writing/editing requests
  if (
    /\b(edit|proofread|rewrite|writing|brief check|improve my|review my (brief|motion|memo|letter)|badverbs|zombie nouns|persuasive writing)\b/.test(msg)
  ) return 'writing_coach';

  // Impeacher — deposition, contradiction, cross-examination
  if (
    /\b(deposition|depose|impeach|contradict|cross.?exam|prior testimony|inconsisten|conflict(s| in)|what did.*say|witness.*said)\b/.test(msg)
  ) return 'impeacher';

  // Opposition Mapper — defense theories, opposition mapping
  if (
    /\b(defense theory|their argument|what will they argue|opposition map|counter.*argument|pre.?existing|sudden emergency|comparative fault|low.?impact|map.*defense|defense.*map)\b/.test(msg)
  ) return 'opposition_map';

  // IP Triage — infringement analysis
  if (
    /\b(infringement|infringe|trademark dispute|copyright claim|patent claim|trade secret|stolen (idea|invention|code|design)|copying (my|our)|dmca|likelihood of confusion|triage|ip (issue|problem|dispute|violation))\b/.test(msg)
  ) return 'ip_triage';

  // IP Clause Review — contract IP clause analysis
  if (
    /\b(ip clause|assignment (clause|gap|provision)|work.?for.?hire|open source (clause|risk|license|exposure)|confidentiality clause|intellectual property (clause|provision)|review.*(?:ip|assignment|license)|license (grant|scope|restriction))\b/.test(msg)
  ) return 'ip_clause_review';

  // DMCA Takedown — send/respond/counter notice
  if (
    /\b(dmca (notice|takedown|counter|letter)|takedown notice|counter.?notice|section 512|§\s?512|512[cg]|copyright (notice|complaint|claim))\b/.test(msg)
  ) return 'dmca_takedown';

  // Specialty verticals — detected before full crew
  if (
    /\b(va (claim|rating|disability|benefit|appeal|decision)|veteran('s)? (benefit|health|disability|claim|appeal)|bva|cavc|38 (usc|cfr)|service.?connect|individual unemployability|cue (error|claim)|notice of disagreement)\b/.test(msg)
  ) return 'specialty';

  if (
    /\b(security clearance|clearance (denied|revoked|appeal|hearing)|doha|iscr|sf.?86|adjudicative guideline|foreign influence|whole person|sar access|sap access|ts.?sci|special access program)\b/.test(msg)
  ) return 'specialty';

  if (
    /\b(howey test|token (classification|security|commodity)|sec.*token|cftc.*crypto|defi (liability|regulation)|nft (security|regulation)|bitcoin (security|commodity)|digital asset (law|regulation|compliance)|blockchain (law|regulation))\b/.test(msg)
  ) return 'specialty';

  if (
    /\b(talent agenc|talent representation|7.?year rule|recording contract|360 deal|controlled composition|sync licens|master licens|right of publicity|sampling (clearance|infringement|license)|guild (minimum|agreement|residual)|sag.?aftra|wga|dga)\b/.test(msg)
  ) return 'specialty';

  if (
    /\b(ai (liability|copyright|training data|act compliance|regulation|ethics)|eu ai act|training data (copyright|infringement|fair use)|ai.?generated (copyright|ownership|authorship)|algorithmic (bias|accountability|discrimination)|llm (liability|copyright)|foundation model (compliance|regulation))\b/.test(msg)
  ) return 'specialty';

  // Full crew when a document is attached
  if (input.documentText) return 'full_crew';

  // Default: research-only crew
  return 'research_only';
}

/**
 * Decide whether to spawn the crew for this message. Returns false for
 * casual / factual / one-liner questions where a single-agent reply is
 * better.
 */
export function shouldSpawnCrew(input: CrewInput): boolean {
  return detectTaskType(input) !== 'simple';
}

export async function runCrew(input: CrewInput, deps: CrewDeps): Promise<CrewOutput> {
  const taskType = detectTaskType(input);

  if (taskType === 'simple') {
    return {
      reply: '',
      trace: { decision: 'simple', taskType, rolesSpawned: [] },
      authorities: [],
    };
  }

  // ── Writing Coach path ──────────────────────────────────────────────────
  if (taskType === 'writing_coach') {
    if (!input.documentText || !input.documentName) {
      return {
        reply: 'Please attach a document for writing review.',
        trace: { decision: 'crew', taskType, rolesSpawned: [] },
        authorities: [],
      };
    }
    const writingCoach = await runWritingCoach(
      {
        documentName: input.documentName,
        documentText: input.documentText,
        documentType: 'legal document',
      },
      deps.model,
    );
    const reply = formatWritingCoachReply(writingCoach);
    return {
      reply,
      trace: { decision: 'crew', taskType, rolesSpawned: ['writing_coach'], writingCoach },
      authorities: [],
    };
  }

  // ── Impeacher path ──────────────────────────────────────────────────────
  if (taskType === 'impeacher') {
    const primaryName =
      extractWitnessName(input.userMessage) ?? input.documentName ?? 'Unknown Witness';
    const primaryTranscripts =
      input.documentText && input.documentName
        ? [{ witnessName: primaryName, label: input.documentName, text: input.documentText }]
        : [];
    const allTranscripts = [
      ...primaryTranscripts,
      ...(input.additionalTranscripts ?? []),
    ];
    if (allTranscripts.length === 0) {
      return {
        reply: 'Please attach one or more deposition transcripts.',
        trace: { decision: 'crew', taskType, rolesSpawned: [] },
        authorities: [],
      };
    }
    const impeacher = await runImpeacher(
      {
        primaryWitness: primaryName,
        transcripts: allTranscripts,
        task: input.userMessage,
      },
      deps.model,
    );
    const reply = formatImpeacherReply(impeacher);
    return {
      reply,
      trace: { decision: 'crew', taskType, rolesSpawned: ['impeacher'], impeacher },
      authorities: [],
    };
  }

  // ── Opposition Mapper path ──────────────────────────────────────────────
  if (taskType === 'opposition_map') {
    // Pull verified authorities first so the mapper knows what we have.
    const researcher = await runResearcher(
      {
        query: input.userMessage,
        jurisdiction: input.jurisdiction,
        matterContext: input.matterContext,
      },
      { model: deps.model, supabase: deps.supabase, courtListenerToken: deps.courtListenerToken },
    );
    const theories =
      input.defenseTheories?.length
        ? input.defenseTheories
        : extractTheoriesFromMessage(input.userMessage);
    const oppositionMapper = await runOppositionMapper(
      {
        matterContext: input.matterContext,
        theories,
        verifiedAuthorities: researcher.authorities,
        jurisdiction: input.jurisdiction,
      },
      deps.model,
    );
    const reply = formatOppositionMapperReply(oppositionMapper);
    return {
      reply,
      trace: {
        decision: 'crew',
        taskType,
        rolesSpawned: ['researcher', 'opposition_mapper'],
        researcher,
        oppositionMapper,
      },
      authorities: researcher.authorities,
    };
  }

  // ── IP Triage path ──────────────────────────────────────────────────────
  if (taskType === 'ip_triage') {
    const ipTriage = await runInfringementTriage(
      {
        description: input.userMessage,
        tracks: input.ipTracks,
        jurisdiction: input.jurisdiction,
        ourAssets: input.matterContext || undefined,
        accusedContent: input.documentText || undefined,
      },
      deps.model,
    );
    const reply = formatIpTriageReply(ipTriage);
    return {
      reply,
      trace: { decision: 'crew', taskType, rolesSpawned: ['ip_triage'], ipTriage },
      authorities: [],
    };
  }

  // ── IP Clause Review path ────────────────────────────────────────────────
  if (taskType === 'ip_clause_review') {
    if (!input.documentText || !input.documentName) {
      return {
        reply: 'Please attach the contract for IP clause review.',
        trace: { decision: 'crew', taskType, rolesSpawned: [] },
        authorities: [],
      };
    }
    const ipClauseReview = await runIpClauseReview(
      {
        documentText: input.documentText,
        documentName: input.documentName,
        perspective: undefined,
      },
      deps.model,
    );
    const reply = formatIpClauseReviewReply(ipClauseReview);
    return {
      reply,
      trace: { decision: 'crew', taskType, rolesSpawned: ['ip_clause_review'], ipClauseReview },
      authorities: [],
    };
  }

  // ── DMCA Takedown path ───────────────────────────────────────────────────
  if (taskType === 'dmca_takedown') {
    const mode = input.dmcaMode ?? 'send';
    const dmcaTakedown = await runDmcaTakedown(
      {
        mode,
        copyrightedWork: input.matterContext || undefined,
        accusedContent: input.documentText
          ? input.documentText
          : undefined,
        context: input.userMessage,
        receivedNoticeText: mode !== 'send' && input.documentText
          ? input.documentText
          : undefined,
      },
      deps.model,
    );
    const reply = formatDmcaTakedownReply(dmcaTakedown);
    return {
      reply,
      trace: { decision: 'crew', taskType, rolesSpawned: ['dmca_takedown'], dmcaTakedown },
      authorities: [],
    };
  }

  // ── Specialty path ───────────────────────────────────────────────────────
  if (taskType === 'specialty') {
    const specialtyType = input.specialty ?? detectSpecialty(input.userMessage);
    const specialtyInput = {
      question: input.userMessage,
      matterContext: input.matterContext || undefined,
      documentText: input.documentText || undefined,
      documentName: input.documentName || undefined,
      jurisdiction: input.jurisdiction || undefined,
    };

    let specialtyOutput: VeteransHealthOutput | SecurityClearanceOutput | AiLegalTechOutput | CryptoHoweyOutput | EntertainmentTalentOutput;
    switch (specialtyType) {
      case 'veterans_health':
        specialtyOutput = await runVeteransHealthSpecialist(specialtyInput, deps.model);
        break;
      case 'security_clearance':
        specialtyOutput = await runSecurityClearanceSpecialist(specialtyInput, deps.model);
        break;
      case 'crypto_howey':
        specialtyOutput = await runCryptoHoweySpecialist(specialtyInput, deps.model);
        break;
      case 'ai_legal_tech':
        specialtyOutput = await runAiLegalTechSpecialist(specialtyInput, deps.model);
        break;
      case 'entertainment_talent':
        specialtyOutput = await runEntertainmentTalentSpecialist(specialtyInput, deps.model);
        break;
      default:
        // Unknown specialty → fall through to full crew
        return runCrew({ ...input, taskType: 'full_crew' }, deps);
    }

    const reply = formatSpecialtyReply(specialtyOutput, specialtyType);
    return {
      reply,
      trace: {
        decision: 'crew',
        taskType,
        rolesSpawned: [`specialty:${specialtyType}`],
        specialty: specialtyOutput,
        specialtyType,
      },
      authorities: [],
    };
  }

  // ── Standard crew path (full_crew | research_only) ─────────────────────
  const rolesSpawned: string[] = [];
  let researcher: ResearcherOutput | undefined;
  let analyst: AnalystOutput | undefined;
  let strategist: StrategistOutput | undefined;

  // Researcher always runs.
  rolesSpawned.push('researcher');
  researcher = await runResearcher(
    {
      query: input.userMessage,
      jurisdiction: input.jurisdiction,
      matterContext: input.matterContext,
    },
    { model: deps.model, supabase: deps.supabase, courtListenerToken: deps.courtListenerToken },
  );

  // Analyst runs only when there's a document.
  if (input.documentText && input.documentName) {
    rolesSpawned.push('analyst');
    analyst = await runContractAnalyst(
      {
        documentName: input.documentName,
        documentText: input.documentText,
        task: input.userMessage,
      },
      deps.model,
    );
  }

  // Strategist always runs.
  rolesSpawned.push('strategist');
  strategist = await runStrategist(
    {
      question: input.userMessage,
      matterContext: input.matterContext,
      verifiedAuthorities: researcher?.authorities ?? [],
      analystFindings: analyst,
    },
    deps.model,
  );

  // Team Lead synthesizes.
  rolesSpawned.push('team_lead');
  const reply = await runTeamLead(
    {
      userMessage: input.userMessage,
      researcher: researcher!,
      analyst,
      strategist: strategist!,
    },
    deps.model,
  );

  return {
    reply,
    trace: { decision: 'crew', taskType, rolesSpawned, researcher, analyst, strategist },
    authorities: researcher?.authorities ?? [],
  };
}

// ── Utility: extract a witness name from the user message ─────────────────

function extractWitnessName(msg: string): string | null {
  // "impeach Martinez" | "contradict Dr. Vetter" | "deposition of Sarah Kim"
  const m =
    msg.match(/\b(?:deposition of|impeach|contradict|cross\s+(?:examine|exam))\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)/i) ??
    msg.match(/\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)'s\s+(?:deposition|testimony)/i);
  return m?.[1] ?? null;
}

// ── Utility: pull defense theory strings out of a free-form message ────────

function extractTheoriesFromMessage(msg: string): string[] {
  // Look for numbered or bulleted theories; fall back to the whole message.
  const lines = msg.split(/\n/).map((l) => l.trim()).filter(Boolean);
  const theoryLines = lines.filter((l) =>
    /^[-•*\d]+[.)]\s/.test(l) || /theory|defense|argument|pre.?existing|sudden|comparative|low.?impact/i.test(l),
  );
  return theoryLines.length ? theoryLines : [msg.slice(0, 400)];
}

// ── Reply formatters for specialist-only paths ─────────────────────────────

function formatWritingCoachReply(output: WritingCoachOutput): string {
  const { summary, score, findings, top_rewrites, strengths } = output;
  const scoreStr = `Clarity ${score.clarity}/10 · Conciseness ${score.conciseness}/10 · Credibility ${score.credibility}/10 · Rhythm ${score.rhythm}/10`;

  const high = findings.filter((f) => f.severity === 'high');
  const med = findings.filter((f) => f.severity === 'medium');

  const findingLines = (items: typeof findings) =>
    items.map((f) => `**[${f.rule}]** "${f.quote}"\n→ ${f.issue}\n→ *Rewrite:* ${f.rewrite}`).join('\n\n');

  return [
    `## Writing Review — ${output.documentName}`,
    `*${scoreStr}*`,
    '',
    summary,
    '',
    strengths.length ? `**What's working:** ${strengths.join(' · ')}` : '',
    '',
    high.length ? `### Critical fixes\n\n${findingLines(high)}` : '',
    med.length ? `### Worth fixing\n\n${findingLines(med)}` : '',
    top_rewrites.length
      ? `### Top rewrites\n\n${top_rewrites.map((r, i) => `${i + 1}. ${r}`).join('\n')}`
      : '',
  ]
    .filter((l) => l !== '')
    .join('\n');
}

function formatImpeacherReply(output: ImpeacherOutput): string {
  const high = output.contradictions.filter((c) => c.value === 'high');
  const med = output.contradictions.filter((c) => c.value === 'medium');

  const contLine = (c: (typeof output.contradictions)[0]) =>
    `**[${c.type} · ${c.value.toUpperCase()}]** ${c.topic}\n` +
    `> "${c.statement_a.quote}" *(${c.statement_a.source})*\n` +
    `> vs. "${c.statement_b.quote}" *(${c.statement_b.source})*\n` +
    `→ ${c.impeachment_note}`;

  const outlineLines = output.deposition_outline
    .map((s) => `${s.sequence}. **Setup:** ${s.setup}\n   **Impeach:** "${s.impeach_with}"`)
    .join('\n\n');

  const profile = output.witness_profile;

  return [
    `## Impeachment Map — ${output.primaryWitness}`,
    '',
    high.length ? `### High-value contradictions\n\n${high.map(contLine).join('\n\n')}` : '',
    med.length ? `### Secondary contradictions\n\n${med.map(contLine).join('\n\n')}` : '',
    output.deposition_outline.length
      ? `### Cross-examination sequence\n\n${outlineLines}`
      : '',
    profile.credibility_flags.length
      ? `### Credibility flags\n${profile.credibility_flags.map((f) => `- ${f}`).join('\n')}`
      : '',
    profile.themes.length
      ? `### Vulnerability themes\n${profile.themes.map((t) => `- ${t}`).join('\n')}`
      : '',
  ]
    .filter((l) => l !== '')
    .join('\n\n');
}

function formatOppositionMapperReply(output: OppositionMapperOutput): string {
  const theoryBlocks = output.priority_order
    .map((name) => output.theories.find((t) => t.name === name))
    .filter(Boolean)
    .map((t) => {
      if (!t) return '';
      const threatEmoji = t.threat === 'high' ? '🔴' : t.threat === 'medium' ? '🟡' : '🟢';
      return [
        `### ${threatEmoji} ${t.name} (${t.threat.toUpperCase()})`,
        '',
        `**Their argument:** ${t.their_argument}`,
        '',
        t.their_authority.length
          ? `**They'll cite:** ${t.their_authority.join(', ')}`
          : '**Their authority:** Not identified — research needed.',
        t.our_authority.length
          ? `**Our counter:** ${t.our_authority.join(', ')}`
          : '**Our counter authority:** None verified yet.',
        '',
        `**Defeat plan:**\n${t.defeat_plan.map((s, i) => `${i + 1}. ${s}`).join('\n')}`,
        t.gaps.length
          ? `\n**Gaps:** ${t.gaps.join(' · ')}`
          : '',
        t.jury_instruction
          ? `*Jury instruction: ${t.jury_instruction}*`
          : '',
      ]
        .filter((l) => l !== '')
        .join('\n');
    })
    .join('\n\n---\n\n');

  return [
    '## Opposition Map',
    '',
    output.matter_summary,
    '',
    theoryBlocks,
    output.cross_cutting_issues.length
      ? `### Cross-cutting issues\n${output.cross_cutting_issues.map((i) => `- ${i}`).join('\n')}`
      : '',
  ]
    .filter((l) => l !== '')
    .join('\n\n');
}

// ── Specialty detector ───────────────────────────────────────────────────

function detectSpecialty(msg: string): SpecialtyType {
  const m = msg.toLowerCase();
  if (/\b(va |veteran|bva|cavc|38 (usc|cfr)|service.?connect|unemployability|cue (error|claim)|notice of disagreement)\b/.test(m))
    return 'veterans_health';
  if (/\b(security clearance|doha|iscr|sf.?86|adjudicative|foreign influence|sar access|sap access|ts.?sci)\b/.test(m))
    return 'security_clearance';
  if (/\b(howey|token (class|secur)|sec.*token|cftc.*crypto|defi |nft (secur|reg)|digital asset|blockchain (law|reg))\b/.test(m))
    return 'crypto_howey';
  if (/\b(talent agenc|talent rep|7.?year rule|recording contract|360 deal|controlled comp|sync licens|master licens|right of publicity|sampling |guild |sag.?aftra|wga |dga )\b/.test(m))
    return 'entertainment_talent';
  if (/\b(ai (liabil|copyright|training|act compli|regulat|ethics)|eu ai act|training data|ai.?generat|algorithmic (bias|account|discrimin)|llm |foundation model)\b/.test(m))
    return 'ai_legal_tech';
  return 'ai_legal_tech'; // default fallback for unknown specialties
}

// ── Specialty reply formatter ─────────────────────────────────────────────

function formatSpecialtyReply(
  output: VeteransHealthOutput | SecurityClearanceOutput | AiLegalTechOutput | CryptoHoweyOutput | EntertainmentTalentOutput,
  specialtyType: SpecialtyType,
): string {
  const titles: Record<SpecialtyType, string> = {
    veterans_health: '## Veterans Health Law Analysis',
    security_clearance: '## Security Clearance Analysis',
    ai_legal_tech: '## AI / Legal Technology Analysis',
    crypto_howey: '## Crypto / Digital Assets — Howey Analysis',
    entertainment_talent: '## Entertainment, Talent & IP Analysis',
  };

  const sections: string[] = [titles[specialtyType] ?? '## Specialty Analysis', ''];

  // Main analysis block — common to all
  const analysis = (output as any).analysis;
  if (analysis) {
    sections.push(analysis);
    sections.push('');
  }

  // Specialty-specific sections
  if (specialtyType === 'veterans_health') {
    const o = output as VeteransHealthOutput;
    if (o.current_appeal_level !== 'unknown')
      sections.push(`**Current appeal level:** ${o.current_appeal_level.replace(/_/g, ' ')}`);
    if (o.recommended_lane)
      sections.push(`**Recommended AMA lane:** ${o.recommended_lane.replace(/_/g, ' ')}`);
    if (o.cue_present)
      sections.push(`\n⚠️ **CUE identified:** ${o.cue_note}`);
    if (o.effective_date_issue)
      sections.push(`\n📅 **Effective date issue:** ${o.effective_date_note}`);
    if (o.nexus_analysis)
      sections.push(`\n**Nexus analysis:** ${o.nexus_analysis}`);
    if (o.lay_evidence_value)
      sections.push(`**Lay evidence:** ${o.lay_evidence_value}`);
  }

  if (specialtyType === 'security_clearance') {
    const o = output as SecurityClearanceOutput;
    if (o.guidelines_at_issue.length) {
      sections.push('\n### Guidelines at issue');
      for (const g of o.guidelines_at_issue) {
        const strength = { strong: '🟢', partial: '🟡', weak: '🟠', none: '🔴' }[g.mitigation_strength] ?? '•';
        sections.push(`${strength} **${g.guideline.replace(/_/g, ' ')}** — mitigation: ${g.mitigation_strength}`);
        if (g.disqualifying_conditions.length)
          sections.push(`  - Disqualifying: ${g.disqualifying_conditions.join('; ')}`);
        if (g.mitigating_conditions.length)
          sections.push(`  - Mitigating: ${g.mitigating_conditions.join('; ')}`);
        sections.push(`  - ${g.recommendation}`);
      }
    }
    if (o.whole_person_assessment)
      sections.push(`\n**Whole person assessment:** ${o.whole_person_assessment}`);
    if (o.mitigating_narrative)
      sections.push(`\n**Hearing narrative:** ${o.mitigating_narrative}`);
    if (o.sf86_issues.length)
      sections.push(`\n**SF-86 issues to address:**\n${o.sf86_issues.map((i) => `- ${i}`).join('\n')}`);
  }

  if (specialtyType === 'crypto_howey') {
    const o = output as CryptoHoweyOutput;
    sections.push(`\n### Howey Test — ${o.howey_conclusion.replace(/_/g, ' ').toUpperCase()}`);
    for (const p of o.howey_analysis) {
      const icon = p.satisfied === 'yes' ? '✓' : p.satisfied === 'no' ? '✗' : '?';
      sections.push(`${icon} **${p.prong.replace(/_/g, ' ')}:** ${p.analysis}`);
      if (p.counterargument) sections.push(`   ↳ Counter: ${p.counterargument}`);
    }
    if (o.cftc_jurisdiction_risk) sections.push(`\n⚠️ **CFTC jurisdiction risk:** ${o.cftc_note}`);
    if (o.fincen_msa_risk) sections.push(`⚠️ **FinCEN MSB risk:** ${o.fincen_note}`);
    if (o.state_law_flags.length) sections.push(`**State law flags:** ${o.state_law_flags.join('; ')}`);
    if (o.nft_specific_issues.length) sections.push(`**NFT-specific:** ${o.nft_specific_issues.join('; ')}`);
    if (o.defi_specific_issues.length) sections.push(`**DeFi-specific:** ${o.defi_specific_issues.join('; ')}`);
    sections.push(`\n**Regulatory posture:** ${o.regulatory_posture}`);
  }

  if (specialtyType === 'ai_legal_tech') {
    const o = output as AiLegalTechOutput;
    if (o.training_data) {
      sections.push(`\n### Training Data Copyright`);
      sections.push(`Fair use conclusion: **${o.training_data.fair_use_conclusion}**`);
      sections.push(`Key risk: ${o.training_data.key_risk}`);
    }
    sections.push(`\n**Output ownership:** ${o.output_ownership}`);
    sections.push(`**Products liability risk:** ${o.products_liability_risk}`);
    if (o.eu_ai_act) {
      sections.push(`\n### EU AI Act — ${o.eu_ai_act.risk_tier.replace(/_/g, ' ').toUpperCase()}`);
      sections.push(o.eu_ai_act.tier_rationale);
      if (o.eu_ai_act.compliance_obligations.length)
        sections.push(`Obligations: ${o.eu_ai_act.compliance_obligations.join('; ')}`);
    }
    if (o.ethics_flags.length)
      sections.push(`\n**Ethics flags (ABA Rules):**\n${o.ethics_flags.map((f) => `- ${f}`).join('\n')}`);
    if (o.algorithmic_bias_flags.length)
      sections.push(`**Algorithmic bias:** ${o.algorithmic_bias_flags.join('; ')}`);
  }

  if (specialtyType === 'entertainment_talent') {
    const o = output as EntertainmentTalentOutput;
    if (o.taa_issues.length)
      sections.push(`\n**Talent Agencies Act issues:**\n${o.taa_issues.map((i) => `- ${i}`).join('\n')}`);
    if (o.seven_year_rule_applies)
      sections.push(`\n⚠️ **7-year rule applies:** ${o.seven_year_note}`);
    if (o.controlled_composition_flag)
      sections.push(`⚠️ **Controlled composition clause** — verify mechanic rate impact`);
    if (o.sampling_risk) sections.push(`**Sampling risk:** ${o.sampling_risk}`);
    if (o.rop_analysis) sections.push(`**Right of publicity:** ${o.rop_analysis}`);
    if (o.ai_voice_cloning_risk) sections.push(`**AI voice cloning:** ${o.ai_voice_cloning_risk}`);
    if (o.recoupment_issues.length)
      sections.push(`**Recoupment issues:**\n${o.recoupment_issues.map((i) => `- ${i}`).join('\n')}`);
    if (o.guild_notes.length)
      sections.push(`**Guild/union notes:**\n${o.guild_notes.map((n) => `- ${n}`).join('\n')}`);
  }

  // Common: starred cases, next steps, disclaimer
  const starredCases = (output as any).starred_cases as { citation: string; relevance: string }[] | undefined;
  if (starredCases?.length) {
    sections.push(`\n### Key cases`);
    sections.push(starredCases.map((c) => `- **${c.citation}** — ${c.relevance}`).join('\n'));
  }

  const keyIssues = (output as any).key_issues as string[] | undefined;
  if (keyIssues?.length)
    sections.push(`\n### Key issues\n${keyIssues.map((i) => `- ${i}`).join('\n')}`);

  const nextSteps = (output as any).next_steps as string[] | undefined;
  if (nextSteps?.length)
    sections.push(`\n### Next steps\n${nextSteps.map((s, i) => `${i + 1}. ${s}`).join('\n')}`);

  const deadlines = (output as any).deadlines_to_verify as string[] | undefined;
  if (deadlines?.length)
    sections.push(`\n### Deadlines to verify\n${deadlines.map((d) => `- ⚠️ ${d}`).join('\n')}`);

  sections.push(`\n*${(output as any).disclaimer ?? ''}*`);

  return sections.filter((l) => l !== '').join('\n');
}

// ── IP Triage reply formatter ────────────────────────────────────────────

function formatIpTriageReply(output: InfringementTriageOutput): string {
  const trackLabels: Record<string, string> = {
    trademark: 'Trademark',
    copyright: 'Copyright',
    patent: 'Patent',
    trade_secret: 'Trade Secret',
  };

  const sections: string[] = [
    `## IP Infringement Triage`,
    '',
    `**Tracks detected:** ${output.detected_tracks.map((t) => trackLabels[t] ?? t).join(', ') || 'None identified'}`,
    `**Status:** ${output.overall_status.replace(/_/g, ' ')}`,
    output.fre408_caution ? '\n> ⚠️ **FRE 408 CAUTION:** This situation may involve ongoing settlement or demand negotiations. Review FRE 408 implications before any written communication.' : '',
    '',
  ];

  if (output.trademark) {
    const tm = output.trademark;
    sections.push('### Trademark');
    sections.push(`**Likelihood-of-confusion factors:**\n${tm.likelihood_of_confusion_factors.map((f) => `- ${f}`).join('\n')}`);
    if (tm.dilution_possible) sections.push('⚠️ **Dilution** may also be a viable theory.');
    if (tm.descriptiveness_concern) sections.push('⚠️ **Descriptiveness** of the mark may be at issue.');
    sections.push(`**Priority question:** ${tm.priority_question}`);
    sections.push(`**Recommended searches:** ${tm.recommended_searches.join(', ')}`);
    if (tm.gaps.length) sections.push(`**Gaps:** ${tm.gaps.join(' · ')}`);
    sections.push('');
  }

  if (output.copyright) {
    const cp = output.copyright;
    sections.push('### Copyright');
    sections.push(`**Registration (§411):** ${cp.registration_status}${!cp.registration_required ? ' — required before filing suit' : ''}`);
    sections.push(`**Fair use analysis:**`);
    sections.push(`- Purpose & character: ${cp.fair_use_factors.purpose_and_character}`);
    sections.push(`- Nature of work: ${cp.fair_use_factors.nature_of_work}`);
    sections.push(`- Amount taken: ${cp.fair_use_factors.amount_taken}`);
    sections.push(`- Market effect: ${cp.fair_use_factors.market_effect}`);
    sections.push(`- **Conclusion: ${cp.fair_use_conclusion.replace(/_/g, ' ')}**`);
    if (cp.dmca_safe_harbor_applies) sections.push(`ℹ️ DMCA safe harbor may apply to the accused party: ${cp.dmca_safe_harbor_note}`);
    sections.push(`**Actionability:** ${cp.actionability}`);
    sections.push('');
  }

  if (output.patent) {
    const pt = output.patent;
    sections.push('### Patent');
    sections.push(`**Type:** ${pt.patent_type} · **Claim chart needed:** Yes (always)`);
    if (pt.doe_flag) sections.push('⚠️ Doctrine of Equivalents may apply if literal infringement is unclear.');
    if (pt.invalidity_risks.length) sections.push(`**Invalidity risks:** ${pt.invalidity_risks.join('; ')}`);
    if (pt.key_claims_to_map.length) sections.push(`**Claims to map:** ${pt.key_claims_to_map.join('; ')}`);
    if (pt.gaps.length) sections.push(`**Gaps:** ${pt.gaps.join(' · ')}`);
    sections.push('');
  }

  if (output.trade_secret) {
    const ts = output.trade_secret;
    sections.push('### Trade Secret');
    sections.push(`**Statute:** ${ts.statute}`);
    sections.push(`**Reasonable measures documented:** ${ts.reasonable_measures_documented ? 'Yes' : 'No — critical gap'}`);
    sections.push(`**Misappropriation elements:**`);
    sections.push(`- Acquisition by improper means: ${ts.misappropriation_elements.acquisition_by_improper_means}`);
    sections.push(`- Disclosure or use: ${ts.misappropriation_elements.disclosure_or_use}`);
    sections.push(`- Breach of duty: ${ts.misappropriation_elements.breach_of_duty}`);
    if (ts.gaps.length) sections.push(`**Gaps:** ${ts.gaps.join(' · ')}`);
    sections.push('');
  }

  if (output.next_steps.length) {
    sections.push(`### Next steps`);
    sections.push(output.next_steps.map((s, i) => `${i + 1}. ${s}`).join('\n'));
    sections.push('');
  }

  if (output.evidence_needed.length) {
    sections.push(`### Evidence needed\n${output.evidence_needed.map((e) => `- ${e}`).join('\n')}`);
  }

  sections.push(`\n*${output.disclaimer}*`);
  return sections.filter((l) => l !== '').join('\n');
}

// ── IP Clause Review reply formatter ──────────────────────────────────────

function formatIpClauseReviewReply(output: IpClauseReviewOutput): string {
  const riskEmoji = { critical: '🔴', high: '🟠', medium: '🟡', low: '🟢' };
  const severityEmoji: Record<string, string> = { critical: '🔴', high: '🟠', medium: '🟡', low: '🟢', info: 'ℹ️' };

  const sections: string[] = [
    `## IP Clause Review — ${output.document_name}`,
    `**Contract type:** ${output.contract_type} · **Overall risk:** ${riskEmoji[output.overall_risk]} ${output.overall_risk.toUpperCase()}`,
    '',
  ];

  if (output.open_source_flag) {
    sections.push(`> 🔴 **Open Source Flag:** ${output.open_source_note}`);
    sections.push('');
  }

  // Assignment gap
  const ag = output.assignment_gap;
  sections.push('### Assignment Gap Check');
  sections.push(`- IP assignment clause present: **${ag.ip_assignment_present ? 'Yes' : 'NO — critical gap'}**`);
  if (ag.ip_assignment_present) {
    sections.push(`- Covers inventions: ${ag.covers_inventions ? '✓' : '✗'}`);
    sections.push(`- Covers works of authorship: ${ag.covers_works_of_authorship ? '✓' : '✗'}`);
    sections.push(`- Covers improvements: ${ag.covers_improvements ? '✓' : '✗'}`);
    sections.push(`- Present assignment ("hereby assigns"): ${ag.present_assignments_only ? '✓' : '✗ — "agrees to assign" is weaker'}`);
    sections.push(`- Prior IP carve-out: ${ag.carve_out_present ? 'Present' : 'Not found'}`);
  }
  sections.push(`**${ag.gap_summary}**`);
  sections.push('');

  // Work for hire
  const wfh = output.work_for_hire;
  sections.push('### Work-for-Hire Analysis (17 U.S.C. §101)');
  sections.push(`- WFH clause present: **${wfh.work_for_hire_clause_present ? 'Yes' : 'No'}**`);
  if (wfh.work_types_covered.length) sections.push(`- Work types covered: ${wfh.work_types_covered.join(', ')}`);
  sections.push(`- §101(2) categories met: ${wfh.section_101_categories_met ? '✓' : '✗'}`);
  if (wfh.independent_contractor_risk) sections.push(`⚠️ **Independent contractor risk:** WFH may not apply without a qualifying §101(2) category.`);
  sections.push(wfh.recommendation);
  sections.push('');

  // Findings
  if (output.findings.length) {
    sections.push('### Findings');
    for (const f of output.findings.sort((a, b) => {
      const order = { critical: 0, high: 1, medium: 2, low: 3, info: 4 };
      return (order[a.severity] ?? 5) - (order[b.severity] ?? 5);
    })) {
      sections.push(
        `${severityEmoji[f.severity] ?? '•'} **[${f.clause_type.replace(/_/g, ' ')}]** ` +
        `*${f.location}*\n→ ${f.issue}\n→ ${f.redline_suggestion}`,
      );
    }
    sections.push('');
  }

  if (output.missing_critical_clauses.length) {
    sections.push(`### Missing critical clauses\n${output.missing_critical_clauses.map((c) => `- ${c.replace(/_/g, ' ')}`).join('\n')}`);
    sections.push('');
  }

  if (output.priority_fixes.length) {
    sections.push(`### Priority fixes\n${output.priority_fixes.map((f, i) => `${i + 1}. ${f}`).join('\n')}`);
  }

  sections.push(`\n*${output.disclaimer}*`);
  return sections.filter((l) => l !== '').join('\n');
}

// ── DMCA Takedown reply formatter ────────────────────────────────────────

function formatDmcaTakedownReply(output: DmcaTakedownOutput): string {
  const sections: string[] = [
    `## DMCA ${output.mode === 'send' ? 'Takedown Notice' : output.mode === 'counter' ? 'Counter-Notice' : 'Takedown Analysis'}`,
    '',
  ];

  if (output.blocked) {
    sections.push(`> 🔴 **BLOCKED — Do not proceed without attorney review.**`);
    sections.push(`> ${output.blocked_reason ?? 'Fair use or perjury risk detected.'}`);
    sections.push('');
  }

  if (output.section_512f_risk) {
    sections.push(`> ⚠️ **§512(f) Perjury risk detected:**`);
    for (const n of output.section_512f_notes) sections.push(`> - ${n}`);
    sections.push('');
  }

  if (output.fair_use) {
    const fu = output.fair_use;
    sections.push('### Fair Use Analysis (Lenz gate)');
    sections.push(`- Purpose & character: ${fu.purpose_and_character}`);
    sections.push(`- Nature of work: ${fu.nature_of_work}`);
    sections.push(`- Amount & substantiality: ${fu.amount_and_substantiality}`);
    sections.push(`- Market effect: ${fu.market_effect}`);
    sections.push(`- **Conclusion: ${fu.conclusion.replace(/_/g, ' ')}**${fu.lenz_block ? ' — **BLOCKED**' : ''}`);
    sections.push('');
  }

  if (output.elements_512c3) {
    const el = output.elements_512c3;
    sections.push('### §512(c)(3) Element Checklist');
    sections.push(`- Signature: ${el.physical_or_electronic_signature ? '✓' : '✗'}`);
    sections.push(`- Copyrighted work identified: ${el.identification_of_copyrighted_work ? '✓' : '✗'}`);
    sections.push(`- Infringing material identified: ${el.identification_of_infringing_material ? '✓' : '✗'}`);
    sections.push(`- Contact information: ${el.contact_information ? '✓' : '✗'}`);
    sections.push(`- Good-faith belief: ${el.good_faith_belief_statement ? '✓' : '✗'}`);
    sections.push(`- Accuracy under perjury: ${el.accuracy_under_penalty_of_perjury ? '✓' : '✗'}`);
    if (el.missing_elements.length) sections.push(`**Missing:** ${el.missing_elements.join(', ')}`);
    sections.push('');
  }

  if (output.draft_notice) {
    sections.push('### Draft Notice');
    sections.push('```');
    sections.push(output.draft_notice);
    sections.push('```');
    sections.push('');
  }

  if (output.draft_counter_notice) {
    sections.push('### Draft Counter-Notice');
    sections.push('```');
    sections.push(output.draft_counter_notice);
    sections.push('```');
    sections.push('');
  }

  if (output.platform_notes.length) {
    sections.push(`### Platform notes\n${output.platform_notes.map((n) => `- ${n}`).join('\n')}`);
    sections.push('');
  }

  if (output.next_steps.length) {
    sections.push(`### Next steps\n${output.next_steps.map((s, i) => `${i + 1}. ${s}`).join('\n')}`);
  }

  sections.push(`\n*${output.disclaimer}*`);
  return sections.filter((l) => l !== '').join('\n');
}

interface TeamLeadInput {
  userMessage: string;
  researcher: ResearcherOutput;
  analyst?: AnalystOutput;
  strategist: StrategistOutput;
}

async function runTeamLead(input: TeamLeadInput, model: string): Promise<string> {
  const authBlock = input.researcher.authorities
    .map((a) => `- ${a.citation}: ${a.relevanceNote}`)
    .join('\n');

  return completeText({
    model,
    systemPrompt: TEAM_LEAD_SYSTEM_PROMPT,
    user: `
USER QUESTION:
${input.userMessage}

VERIFIED AUTHORITIES:
${authBlock || '(none)'}

GAPS FLAGGED BY RESEARCHER:
${input.researcher.gaps.join('\n') || '(none)'}

ANALYST FINDINGS:
${input.analyst ? JSON.stringify(input.analyst, null, 2) : '(no document)'}

STRATEGIST OUTPUT:
${JSON.stringify(input.strategist, null, 2)}

Produce the user-facing response per your system prompt's structure.
    `.trim(),
    maxTokens: 3072,
  });
}
