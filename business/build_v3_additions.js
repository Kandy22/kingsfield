/**
 * Kingsfield Business Plan — v3 Additions Script
 * Generates the new/corrected sections to merge into or append to v2:
 *   - Competitive Landscape (Harvey / Legora / Lexis — corrected, current)
 *   - LLM Council (corrected: multi-provider Claude + Gemini)
 *   - Case Intelligence Graph (new feature section)
 *   - Images folder recommendation (inline note)
 *   - Reference Links & Data Sources (Section 16)
 *   - Assets folder spec (appendix note)
 *
 * Run: node build_v3_additions.js
 * Output: Kingsfield_BP_v3_Additions.docx
 */

'use strict';
const fs = require('fs');
const path = require('path');
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, ImageRun,
  AlignmentType, BorderStyle, WidthType, ShadingType, HeadingLevel,
  ExternalHyperlink, PageBreak, LevelFormat,
} = require('docx');

// ── COLORS ───────────────────────────────────────────────────────────────────
const C = {
  black:   '1A1A1A',
  navy:    '0B1F3A',
  gold:    'C9A84C',
  red:     'C0392B',
  grey:    '4A4A4A',
  ltgrey:  'F5F5F5',
  midgrey: 'CCCCCC',
  white:   'FFFFFF',
  green:   '27AE60',
  purple:  '7B2D8B',
  blue:    '2471A3',
  orange:  'D35400',
  teal:    '148F77',
};

// ── HELPERS ──────────────────────────────────────────────────────────────────
const border = { style: BorderStyle.SINGLE, size: 1, color: C.midgrey };
const borders = { top: border, bottom: border, left: border, right: border };

function cm(text) {
  return new TextRun({ text: String(text), font: 'Arial', size: 22, color: C.black });
}
function bold(text, color = C.navy) {
  return new TextRun({ text: String(text), font: 'Arial', size: 22, bold: true, color });
}
function P(children, opts = {}) {
  return new Paragraph({
    spacing: { before: 100, after: 100 },
    ...opts,
    children,
  });
}
function H1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 360, after: 180 },
    children: [new TextRun({ text, font: 'Arial', size: 36, bold: true, color: C.navy })],
  });
}
function H2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 240, after: 120 },
    children: [new TextRun({ text, font: 'Arial', size: 28, bold: true, color: C.navy })],
    border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: C.gold, space: 2 } },
  });
}
function H3(text) {
  return new Paragraph({
    spacing: { before: 180, after: 80 },
    children: [new TextRun({ text, font: 'Arial', size: 24, bold: true, color: C.gold })],
  });
}
function bullet(text) {
  return new Paragraph({
    numbering: { reference: 'bullets', level: 0 },
    spacing: { before: 60, after: 60 },
    children: [cm(text)],
  });
}
function link(label, url) {
  return new ExternalHyperlink({
    children: [new TextRun({ text: label, font: 'Arial', size: 22, color: C.blue, underline: {} })],
    link: url,
  });
}

function tbl(rows, ws) {
  const ncols = ws.length;
  const totalW = ws.reduce((a, b) => a + b, 0);
  return new Table({
    width: { size: totalW, type: WidthType.DXA },
    columnWidths: ws,
    rows: rows.map(function(r) {
      const isHdr = !!r[ncols];
      return new TableRow({
        tableHeader: isHdr,
        children: ws.map(function(w, i) {
          const txt = String(r[i] || '');
          const fill = isHdr ? C.navy : (i === 0 ? C.ltgrey : C.white);
          const tc   = isHdr ? C.white : (txt === 'Yes' ? C.green : (txt === 'No' ? C.red : C.grey));
          const bd   = isHdr || (i === 0 && !isHdr);
          return new TableCell({
            borders,
            width: { size: w, type: WidthType.DXA },
            shading: { fill, type: ShadingType.CLEAR },
            margins: { top: 80, bottom: 80, left: 120, right: 120 },
            children: [P([new TextRun({ text: txt, font: 'Arial', size: 20, bold: bd, color: tc })])],
          });
        }),
      });
    }),
  });
}

function goldRule() {
  return new Paragraph({
    spacing: { before: 160, after: 160 },
    children: [new TextRun({ text: '', font: 'Arial', size: 4 })],
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: C.gold, space: 1 } },
  });
}

function callout(label, text) {
  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [360, 9000],
    rows: [new TableRow({ children: [
      new TableCell({
        borders,
        width: { size: 360, type: WidthType.DXA },
        shading: { fill: C.gold, type: ShadingType.CLEAR },
        margins: { top: 80, bottom: 80, left: 80, right: 80 },
        children: [P([new TextRun({ text: label, font: 'Arial', size: 20, bold: true, color: C.white })])],
      }),
      new TableCell({
        borders,
        width: { size: 9000, type: WidthType.DXA },
        shading: { fill: 'FAF5E4', type: ShadingType.CLEAR },
        margins: { top: 80, bottom: 80, left: 140, right: 120 },
        children: [P([cm(text)])],
      }),
    ]})],
  });
}

// ── SECTIONS ─────────────────────────────────────────────────────────────────

function sectionBreak() {
  return new Paragraph({ children: [new PageBreak()] });
}

// ─── SECTION: LLM COUNCIL (CORRECTED) ────────────────────────────────────────
function llmCouncilSection() {
  return [
    H1('Section 3B — The LLM Council: Multi-Provider Adversarial Synthesis'),
    goldRule(),
    P([cm('The LLM Council is the strategic pressure-test layer that runs above the four agents. Every significant conclusion is submitted for a structured adversarial review before it reaches the user. This is not five Claudes wearing different hats. It is a genuinely diverse set of models with different training data, different priors, and different failure modes — chosen specifically so that no single model\'s biases dominate the output.')]),
    P([cm('')]),
    H2('Pipeline Architecture'),
    P([cm('Eleven model calls per Council session. Three stages. Full parallelism at each stage.')]),
    P([cm('')]),
    tbl([
      ['Stage', 'Role', 'Provider / Model', 'Why This Choice', true],
      ['1 — Frame', 'Chairman (Framer)', 'Claude Opus', 'Synthesis and neutral framing before the question is posed to advisors.'],
      ['2 — Advise', 'Contrarian', 'Claude Opus', 'Deep adversarial reasoning. Finds the hole in any argument.'],
      ['2 — Advise', 'First Principles', 'Gemini 2.5 Pro', 'Different training corpus = different priors. Surfaces what Claude misses.'],
      ['2 — Advise', 'Expansionist', 'Claude Sonnet', 'Creative, fast. Finds the angle nobody asked about.'],
      ['2 — Advise', 'Outsider', 'Gemini 2.5 Flash', 'Fewer priors. Fresh eyes. Does not know what it is "supposed" to say.'],
      ['2 — Advise', 'Executor', 'Claude Sonnet', 'Concrete and action-oriented. What can actually be done with this?'],
      ['3 — Review', '5 Reviewers', 'Same routing as Advisors', 'Each advisor reviews the anonymized set. Blind peer review.'],
      ['4 — Verdict', 'Chairman', 'Claude Opus', 'Synthesizes all advisor responses and all peer reviews into a single verdict memo.'],
    ], [1200, 1400, 1800, 4960]),
    P([cm('')]),
    P([bold('Provider diversity is intentional. '), cm('Gemini and Claude are trained differently, finetuned differently, and have different documented failure modes. Using both is a hedge against any single provider\'s blind spots. If the Gemini API key is not configured, the system falls back to all-Claude and logs a warning — the Council still runs, but the diversity benefit degrades.')]),
    P([cm('')]),
    callout('CODE', 'Implemented in backend/src/llm-council/orchestrator.ts and providers.ts. Five advisors run in parallel (Promise.all). Five reviewers run in parallel on the anonymized set. Chairman synthesizes. All sessions are persisted in Supabase llm_council_sessions.'),
    P([cm('')]),
    H2('The Anonymization Step'),
    P([cm('Advisor responses are randomly shuffled to letters A–E before the review round. Reviewers evaluate the content, not the persona. This prevents role-bias in peer review — the Contrarian reviewing "the Contrarian\'s response" would not be independent.')]),
    P([cm('')]),
    H2('Why Not Just Run Claude More Times?'),
    P([cm('Same model, same training, same fine-tuning = correlated errors. If Claude Opus has a blind spot on a particular legal theory, running it five times does not surface that blind spot — it reinforces it. Provider diversity is the only structural defense against model-level bias.')]),
    P([cm('')]),
    callout('NOTE', 'Harvey runs on a single provider (OpenAI). Legora runs on a single provider (Claude/Anthropic). Kingsfield is the only platform in this category with deliberate cross-provider adversarial review architecture.'),
  ];
}

// ─── SECTION: COMPETITIVE LANDSCAPE ──────────────────────────────────────────
function competitiveSection() {
  return [
    sectionBreak(),
    H1('Section 5 — Competitive Landscape'),
    goldRule(),
    P([cm('Three incumbents dominate the legal AI market. All three share the same structural blind spot: they are built for institutions, priced for institutions, and wired into incumbent data monopolies. That is the gap.')]),
    P([cm('')]),

    H2('Harvey — The Category Leader'),
    P([cm('Harvey is the benchmark. Series D, $1.1B+ valuation, used at over half the Am Law 100. If you are building in legal AI, Harvey defines what "good" looks like at enterprise scale. Know it cold.')]),
    P([cm('')]),
    tbl([
      ['Harvey — What They Have', '', true],
      ['Feature', 'Detail'],
      ['Core Products', 'Assistant (conversational AI), Research (case/statute lookup), Vault (doc repository), Workflows (multi-step automation)'],
      ['Scale', '500+ deployed use-case agents. Workflow Builder for custom automation. Command Center for enterprise AI governance.'],
      ['Market', 'Over 50% of Am Law 100. Designed around BigLaw compliance, ethics walls, SAML SSO, audit logs.'],
      ['Pricing', '$1,000–$1,200/seat/month. Annual contract minimums of $50K–$200K. Not for individuals.'],
      ['AI Stack', 'OpenAI GPT-4 class models. Single-provider. No multi-model adversarial layer.'],
      ['Citation Verification', 'Research responses cite sources, but no four-gate verification pipeline. No hard veto on bad citations.'],
      ['Institutional Knowledge', 'DeepJudge integration (May 2026) — pulls firm work product into workflows while respecting ethics walls.'],
    ], [3600, 5760]),
    P([cm('')]),
    callout('KINGSFIELD vs HARVEY', 'Harvey charges $12K–$14K/year per attorney to access public law. Kingsfield is built for everyone that price locks out. Harvey has no hard citation veto. Kingsfield\'s Skeptic halts output if a citation fails Gate 1. Harvey serves institutions. Kingsfield serves people.'),
    P([cm('')]),

    H2('Legora — The Fast-Rising Challenger'),
    P([cm('Legora is the most dangerous competitor in the mid-market. €500M Series D (April 2026). $5.6B valuation. $100M ARR. 1,000+ customers across 50 markets. They hit $100M ARR in under 18 months from general launch. Built on Anthropic\'s Claude — the same foundation as Kingsfield.')]),
    P([cm('')]),
    tbl([
      ['Legora — What They Have', '', true],
      ['Feature', 'Detail'],
      ['Core Products', 'Tabular Review (structured extraction for contract analysis), agentic workflows, matter-grounded AI, mobile access.'],
      ['Integrations', 'Outlook, Word, iManage, NetDocs, SharePoint, mobile. Deep in the law firm stack.'],
      ['Governance', 'Full audit trails, review/approval flows, enterprise-wide workflow deployment.'],
      ['AI Stack', 'Built on Anthropic Claude. Single-provider (same blind-spot risk as Harvey). No cross-provider adversarial layer.'],
      ['Market', 'European origin but global expansion. Targets mid-to-large law firms and in-house legal departments.'],
      ['Citation Verification', 'Citation-backed research, but no four-gate pipeline. No hard veto architecture.'],
      ['Pricing', 'Enterprise SaaS, likely $500+/seat/month based on reported ARR and customer base.'],
    ], [3600, 5760]),
    P([cm('')]),
    callout('KINGSFIELD vs LEGORA', 'Legora\'s Tabular Review is excellent contract analysis for firms. Kingsfield\'s Case Intelligence Graph maps the entire matter — parties, exhibits, authorities, issues — in a navigable force-directed visualization. Legora is firm-focused, enterprise-priced. Kingsfield is user-focused, open-model.'),
    P([cm('')]),

    H2('LexisNexis Protégé — The Incumbent'),
    P([cm('LexisNexis rebranded Lexis+ AI to "Lexis+ with Protégé" in February 2026. They control the largest commercial legal database, Shepard\'s Citations, and decades of attorney relationships. Their moat is data lock-in, not intelligence.')]),
    P([cm('')]),
    tbl([
      ['Lexis+ with Protégé — What They Have', '', true],
      ['Feature', 'Detail'],
      ['Core Products', 'Protégé AI assistant, Vault (100K docs), Skills (contract comparison, due diligence, compliance review), Protégé Work.'],
      ['Citation Validation', 'Shepard\'s Verify Trust Markers — flags citations that cannot be verified against their database.'],
      ['AI Stack', 'Proprietary LLM + LexisNexis content layer. No disclosed provider. No adversarial review.'],
      ['Market', 'Law firms, in-house legal, government. Bundled with existing Lexis subscriptions.'],
      ['Pricing', '$100–$300+/month per user on top of Lexis base subscription. Total cost $2,000–$5,000+/year per attorney.'],
      ['Data Position', 'They charge for access to public law. This is the structural problem Kingsfield solves.'],
    ], [3600, 5760]),
    P([cm('')]),
    callout('KINGSFIELD vs LEXIS', 'Lexis charges for access to federal statutes and case law that are public domain. CourtListener, eCFR.gov, and Congress.gov are free. Shepard\'s is a paid service that monetizes citation verification. Kingsfield\'s four-gate pipeline does the same job on open sources. The law belongs to the people who have to live under it — not to whoever built the best paywall.'),
    P([cm('')]),

    H2('Head-to-Head Comparison'),
    tbl([
      ['Feature', 'Harvey', 'Legora', 'Lexis Protégé', 'Kingsfield', true],
      ['Target user', 'BigLaw', 'Mid-large firm', 'All attorneys', 'Everyone else'],
      ['Price', '$12–14K/yr/attorney', '$6K+/yr/attorney', '$2–5K/yr/attorney', 'Open / affordable'],
      ['Multi-provider AI', 'No (OpenAI)', 'No (Claude)', 'No (proprietary)', 'Yes (Claude + Gemini)'],
      ['Hard citation veto', 'No', 'No', 'Shepard\'s flags', 'Yes — 4-gate pipeline'],
      ['Primary sources only', 'No', 'No', 'No (paid data)', 'Yes — CourtListener etc.'],
      ['Case knowledge graph', 'No', 'No', 'No', 'Yes — Case Intelligence'],
      ['Pro se / creator focus', 'No', 'No', 'No', 'Core mission'],
      ['Arizona ABS compliant', 'No', 'No', 'No', 'Yes — by design'],
      ['Open source base', 'No', 'No', 'No', 'AGPL-3.0 (fork of Mike)'],
    ], [2000, 1680, 1680, 1680, 2320]),
    P([cm('')]),
  ];
}

// ─── SECTION: CASE INTELLIGENCE GRAPH ────────────────────────────────────────
function caseGraphSection() {
  return [
    sectionBreak(),
    H1('Section 6A — Case Intelligence Graph'),
    goldRule(),
    P([cm('When a matter is complex — multiple parties, dozens of exhibits, a dozen case authorities, five contested issues — attorneys pay paralegals and associates thousands of dollars to build chronologies, cross-reference exhibits to witnesses, and map case law to claims. That work is document review dressed up as strategy.')]),
    P([cm('')]),
    P([bold('The Case Intelligence Graph does it automatically. ')]),
    P([cm('Every document uploaded to a matter is parsed for entities. Those entities — parties, exhibits, authorities, statutes, pleadings, issues — are mapped into a navigable force-directed graph. The user can see the entire matter at a glance, filter by node type, click any node to see full detail, and trace the path from claim to evidence to authority in seconds.')]),
    P([cm('')]),
    H2('What the Graph Shows'),
    tbl([
      ['Node Type', 'Color', 'Examples', 'Source', true],
      ['Parties / People', 'Blue', 'Plaintiff, defendant, experts, witnesses, employers', 'Extracted from pleadings, deposition notices'],
      ['Exhibits', 'Orange', 'Photographs, medical records, subpoena returns, expert reports', 'Extracted from exhibit lists, document filenames'],
      ['Case Authorities', 'Purple', 'Cited cases — Diaz v. Carcamo, Hinman v. Westinghouse', 'Extracted citations → CourtListener 4-gate verified'],
      ['Statutes / CACI', 'Teal', 'VC § 23123.5, CCP § 335.1, CACI 400, CACI 418', 'Extracted from FAC, pleadings → eCFR verified'],
      ['Pleadings & Discovery', 'Gold', 'FAC, subpoenas, RFAs, interrogatories, strategy memos', 'Indexed from uploaded documents'],
      ['Legal Issues / Claims', 'Red', 'Negligence, negligence per se, vicarious liability, causation', 'Extracted from FAC causes of action'],
    ], [2000, 1000, 2800, 3560]),
    P([cm('')]),
    H2('What Happens When You Click a Node'),
    P([cm('A detail panel opens showing: node type, full description, jurisdiction/status, metadata (Bates range, filing date, deposition status), and all connected nodes. Clicking a connected node navigates to it. The graph updates in real time as documents are added to the matter.')]),
    P([cm('')]),
    H2('Technical Implementation'),
    tbl([
      ['Step', 'What Happens', 'Technology', true],
      ['1. Ingest', 'Document uploaded to matter project', 'Existing upload/storage pipeline (S3 + Supabase)'],
      ['2. Extract', 'Entity extraction pass — names, citations, statutes, exhibit references', 'Claude structured output + regex patterns'],
      ['3. Verify', 'Citations submitted to four-gate pipeline', 'CourtListener Citation Lookup (verification/pipeline.ts)'],
      ['4. Graph', 'Nodes + edges written to graph_nodes / graph_edges tables', 'New Supabase tables (migration 120)'],
      ['5. Render', 'D3.js force-directed graph loaded on demand', 'React component, D3 v7, color-coded by node type'],
      ['6. Filter', 'User filters by node type, searches by name, clicks to inspect', 'Frontend state, no additional API calls'],
      ['7. Export', 'PNG/SVG export for inclusion in court binders or strategy memos', 'SVG serialization, canvas export'],
    ], [1000, 3800, 4560]),
    P([cm('')]),
    P([bold('What this means for the user: '), cm('Upload your complaint, your deposition notices, your subpoenas, and your exhibit list. Within minutes, the full matter web is visible. Who is connected to what exhibit. Which authority supports which claim. Which issue lacks supporting case law. This is the work that used to cost $400/hour.')]),
    P([cm('')]),
    callout('DEMO', 'A live interactive demo of the Case Intelligence Graph is available at kingsfield_case_graph.html in the project assets. The demo models Chen v. Brooks — a multi-defendant personal injury matter — with all node types populated and filter/inspect functionality live.'),
    P([cm('')]),
    H2('Why None of the Competitors Have This'),
    P([cm('Harvey\'s Vault is a document repository, not a graph. Legora\'s Tabular Review extracts structured data from contracts, not relationships across a matter. Lexis\' Protégé searches within documents, not across the matter web. None of them model the relationships between evidence, people, authorities, and claims because that requires entity extraction at the matter level — not document search.')]),
    P([cm('')]),
  ];
}

// ─── SECTION: REFERENCE LINKS ────────────────────────────────────────────────
function referenceLinksSection() {
  return [
    sectionBreak(),
    H1('Section 16 — Reference Links & Data Sources'),
    goldRule(),
    P([cm('All primary legal sources used in Kingsfield are free, open, and publicly available. No paywalls. No licensing fees. The following is the complete integration and reference stack.')]),
    P([cm('')]),

    H2('Core Legal Data Sources'),
    tbl([
      ['Source', 'URL', 'What It Provides', 'Status', true],
      ['CourtListener', 'courtlistener.com', '9M+ federal and state decisions. REST API v4. Citation Lookup anti-hallucination endpoint. 5,000 queries/hr free (membership required as of May 2026).', 'Integrated — pipeline.ts'],
      ['Caselaw Access Project (CAP)', 'case.law', 'Harvard Law School. 6.9M pre-2020 state and federal cases. Bulk download + API. Free for researchers.', 'Planned adapter'],
      ['eCFR.gov', 'ecfr.gov', 'Electronic Code of Federal Regulations. Official, current, machine-readable. All 50 titles. Free.', 'Planned adapter'],
      ['Congress.gov / GovInfo', 'congress.gov / govinfo.gov', 'Federal statutes, public laws, bill text. Official government sources. Free.', 'Planned adapter'],
      ['Cornell Legal Information Institute', 'law.cornell.edu', 'Curated statutory and case law summaries. UCC, federal statutes, state codes. Highly linkable. Free.', 'Reference'],
      ['RECAP Archive / PACER', 'free.law/recap', 'PACER documents liberated to public domain by Free Law Project. Federal court filings. Free.', 'Reference'],
      ['SALI Alliance', 'salialliance.org', 'Legal Matter Specification Standard (LMSS). Open API. Used by Am Law 200. Free nonprofit.', 'Reference'],
    ], [1800, 1600, 4160, 1800]),
    P([cm('')]),

    H2('Entertainment & IP Data Sources'),
    tbl([
      ['Source', 'URL', 'What It Provides', 'Status', true],
      ['Copyright.gov', 'copyright.gov', 'US Copyright Office records. Registration search, deposit records. Free.', 'Reference'],
      ['USPTO TESS', 'tmsearch.uspto.gov', 'Trademark Electronic Search System. All active and inactive US trademarks. Free.', 'Reference'],
      ['ASCAP / BMI / SESAC', 'ascap.com / bmi.com', 'PRO licensing databases. Work registrations, publisher splits. Free lookup.', 'Reference'],
      ['Luminate (Billboard)', 'luminatedata.com', 'Official Billboard charts and music analytics. Requires licensed data access.', 'Evaluate'],
      ['Pollstar Pro', 'pollstar.com', 'Concert industry data. Requires subscription. Use for entertainment vertical.', 'Evaluate'],
      ['Variety / Deadline', 'variety.com / deadline.com', 'Entertainment news and industry tracking. No API — reference only.', 'Reference'],
    ], [1800, 1800, 3960, 1800]),
    P([cm('')]),

    H2('Document Parsing Infrastructure'),
    tbl([
      ['Tool', 'URL', 'Cost', 'Use Case', true],
      ['LiteParse (NousResearch)', 'github.com/NousResearch/LiteParse', 'Free / Open Source', 'Self-hosted. No API, no cloud, no LLM required. Bounding box extraction. Local-first.'],
      ['LlamaParse (LlamaIndex)', 'cloud.llamaindex.ai', 'Free: 10K credits/mo. Starter: $50/mo. Pro: $500/mo.', 'Cloud. Premium structured extraction. Tables, forms, complex layouts. Use for paid tier.'],
      ['pdf.js (Mozilla)', 'mozilla.github.io/pdf.js', 'Free / Open Source', 'Client-side PDF rendering. Already in npm dependencies.'],
      ['Mammoth', 'github.com/mwilliamson/mammoth.js', 'Free / Open Source', 'DOCX to HTML conversion. Already integrated in backend.'],
    ], [1800, 2100, 1560, 4100]),
    P([cm('')]),

    H2('Competitor Reference Links'),
    tbl([
      ['Competitor', 'URL', 'Key Page', true],
      ['Harvey', 'harvey.ai', 'harvey.ai/platform — feature overview'],
      ['Legora', 'legora.com', 'legora.com — product, also TechCrunch coverage April 2026 for latest valuation/ARR'],
      ['LexisNexis Protégé', 'lexisnexis.com', 'lexisnexis.com/en-us/products/lexis-plus-protege.page'],
      ['Thomson Reuters CoCounsel', 'legal.thomsonreuters.com', 'legal.thomsonreuters.com/en/products/westlaw/co-counsel'],
      ['Westlaw Precision', 'legal.thomsonreuters.com', 'Westlaw Precision — alternative to CoCounsel for legal research'],
    ], [1800, 2000, 5560]),
    P([cm('')]),

    H2('AI Provider Reference'),
    tbl([
      ['Provider', 'URL', 'Models Used in Kingsfield', true],
      ['Anthropic', 'anthropic.com', 'Claude Opus (Contrarian, Executor advisor, Chairman), Claude Sonnet (Expansionist, Executor)'],
      ['Google DeepMind', 'deepmind.google / ai.google.dev', 'Gemini 2.5 Pro (First Principles advisor), Gemini 2.5 Flash (Outsider advisor)'],
      ['Free Law Project', 'free.law', 'CourtListener infrastructure. Non-profit. Accepts donations.'],
      ['NousResearch', 'nousresearch.com', 'Hermes 3 on Llama 3.1 — for adversarial simulation layer (GAN component). Self-hosted.'],
    ], [1800, 2500, 5060]),
    P([cm('')]),
  ];
}

// ─── SECTION: ASSETS FOLDER SPEC ─────────────────────────────────────────────
function assetsFolderSection() {
  return [
    sectionBreak(),
    H1('Appendix A — Image Assets Folder Structure'),
    goldRule(),
    P([cm('All brand and product images should be committed to the kingsfield repository under the following structure. This ensures the business plan build script, the blog, and any future marketing materials all reference the same canonical assets.')]),
    P([cm('')]),
    H2('Recommended Structure'),
    P([new TextRun({ text: 'kingsfield/', font: 'Courier New', size: 22, bold: true, color: C.navy })]),
    P([new TextRun({ text: '  assets/', font: 'Courier New', size: 22, color: C.navy })]),
    P([new TextRun({ text: '    brand/', font: 'Courier New', size: 22, color: C.navy })]),
    P([new TextRun({ text: '      logo.png         — Primary wordmark (horizontal, dark bg)', font: 'Courier New', size: 20, color: C.grey })]),
    P([new TextRun({ text: '      logo-light.png   — Wordmark on light background', font: 'Courier New', size: 20, color: C.grey })]),
    P([new TextRun({ text: '      skull.png        — Skull motif (brand icon)', font: 'Courier New', size: 20, color: C.grey })]),
    P([new TextRun({ text: '      icon.png         — Square icon (favicons, social)', font: 'Courier New', size: 20, color: C.grey })]),
    P([new TextRun({ text: '    product/', font: 'Courier New', size: 22, color: C.navy })]),
    P([new TextRun({ text: '      appui.png        — Main chat interface screenshot', font: 'Courier New', size: 20, color: C.grey })]),
    P([new TextRun({ text: '      product.png      — Product positioning / landing visual', font: 'Courier New', size: 20, color: C.grey })]),
    P([new TextRun({ text: '      case-graph.png   — Case Intelligence Graph screenshot', font: 'Courier New', size: 20, color: C.grey })]),
    P([new TextRun({ text: '    docs/', font: 'Courier New', size: 22, color: C.navy })]),
    P([new TextRun({ text: '      — Images used in business plan, pitch deck, grant apps', font: 'Courier New', size: 20, color: C.grey })]),
    P([cm('')]),
    P([cm('The build scripts for the business plan already reference logo.png, skull.png, appui.png, and product.png. If you move the images to assets/brand/ and assets/product/, update the path variables at the top of build_v2.js (or build_v4.js, next rebuild).')]),
    P([cm('')]),
    callout('NOW', 'Current working image paths (from previous build): logo.png, skull.png, appui.png, product.png — all in the same directory as the build script. Moving to assets/ subdirectory is recommended before the next rebuild so paths are consistent across documents.'),
  ];
}

// ── DOCUMENT ASSEMBLY ─────────────────────────────────────────────────────────
const allContent = [
  // Title page for this supplement
  new Paragraph({
    spacing: { before: 1440, after: 240 },
    alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: 'KINGSFIELD LAWFARE', font: 'Arial', size: 52, bold: true, color: C.navy })],
  }),
  new Paragraph({
    spacing: { before: 80, after: 80 },
    alignment: AlignmentType.CENTER,
    border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: C.gold, space: 4 } },
    children: [new TextRun({ text: 'Business Plan — v3 Additions & Corrections', font: 'Arial', size: 28, bold: true, color: C.gold })],
  }),
  new Paragraph({
    spacing: { before: 160, after: 80 },
    alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: 'May 2026', font: 'Arial', size: 22, color: C.grey })],
  }),
  new Paragraph({
    spacing: { before: 40, after: 40 },
    alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: 'This document contains the new and corrected sections for merge into the v2 Business Plan.', font: 'Arial', size: 20, color: C.grey, italics: true })],
  }),
  new Paragraph({
    spacing: { before: 40, after: 240 },
    alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: 'Sections: LLM Council (corrected) | Competitive Landscape | Case Intelligence Graph | Reference Links | Assets Folder', font: 'Arial', size: 20, color: C.grey, italics: true })],
  }),
  goldRule(),

  ...llmCouncilSection(),
  ...competitiveSection(),
  ...caseGraphSection(),
  ...referenceLinksSection(),
  ...assetsFolderSection(),
];

const doc = new Document({
  numbering: {
    config: [{
      reference: 'bullets',
      levels: [{
        level: 0,
        format: LevelFormat.BULLET,
        text: '•',
        alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 720, hanging: 360 } } },
      }],
    }],
  },
  styles: {
    default: { document: { run: { font: 'Arial', size: 22 } } },
    paragraphStyles: [
      { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 36, bold: true, font: 'Arial', color: C.navy },
        paragraph: { spacing: { before: 360, after: 180 }, outlineLevel: 0 } },
      { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 28, bold: true, font: 'Arial', color: C.navy },
        paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 1 } },
    ],
  },
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 },
        margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 },
      },
    },
    children: allContent,
  }],
});

const outPath = path.join(__dirname, 'Kingsfield_BP_v3_Additions.docx');
Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync(outPath, buf);
  console.log('✓ Written:', outPath);
  console.log('  Paragraphs:', allContent.length);
}).catch(err => {
  console.error('Build failed:', err.message);
  process.exit(1);
});
