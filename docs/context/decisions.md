# Kingsfield Lawfare — Key Decisions Log
*Running log of directional decisions. Add to this, never delete.*

---

## Product

**2026-05-16 — Landing page direction confirmed**
Dark navy (#1A1E2E) + Playfair Display 900 + gold (#C8A96E) is the confirmed design system for both landing and app interior. The V5 cream/Archivo treatment (from a parallel design session) was reviewed and set aside — the dark treatment won. "I like the unique grey/black and gold vibe."

**2026-05-16 — "Kingsfield Lawfare" — two words, always**
Product name is Kingsfield Lawfare, not just Kingsfield. This must be consistent everywhere in UI, copy, and code.

**2026-05-16 — App interior vs marketing tone**
"Irreverent brash attitude in marketing content (ads, blogs, trailers), but functionality should be crisp and powerful." The brashness lives in the landing page and marketing layer. The app interior (Council, Case Law, Council) stays clean, direct, professional.

**2026-05-16 — Intro trailer direction**
Ronin/samurai film aesthetic for the video trailer. Cinematic title card sequence (not a functional landing page). Separate from the product. Will have narration + music (Kill Bill-adjacent score). Orange brushstroke "KINGSFIELD LAWFARE" title card is the money shot.

**2026-05-16 — "AI can make mistakes" disclaimer killed**
Replaced with: "Every citation verified · Primary sources only · Not legal advice — legal knowledge." The product's position is that it verifies harder than most lawyers do, not that it might be wrong.

**2026-05-16 — HeyCounsel skills integrated**
9 skills migrated to `backend/skills/`. Source folder (heycounsel-community-main) deleted from kingsfield root (requires manual Finder delete — read-only permissions blocked CLI). Quick Start Guide saved to `docs/skills-quick-start.md`.

---

## Business Model

**2026-05-16 — B2B law firm play confirmed as primary go-to-market**
Not a mass consumer tool at launch. Targeting boutique powerhouse firms (#2/#3 in their market, on the rise). Sectors: LA entertainment, NYC finance, SF/Austin/Boulder tech, Miami crypto. Younger restless partners who want to dethrone senior partners coasting on relationships.

**2026-05-16 — Monthly fee structure**
Monthly SaaS fee = platform access + strategic consulting. Separately, partner firms handle legal representation with their own engagement letters. These cannot be bundled — UPL exposure if Kingsfield collects legal retainers. Clean separation required.

**2026-05-16 — "Weights" terminology clarified**
What Kingsfield protects is not model weights (those belong to Anthropic/Google) but the agent configuration layer: system prompts, orchestration logic, Council advisor ordering, scoring rubrics. Legally: trade secret. AGPL core stays open; proprietary config layer sits on top.

**2026-05-16 — IBM parallel**
"You can't get fired for hiring BigLaw" = the liability shield BigLaw sells. Kingsfield's counter: "It depends on who your client is." Public-facing framing should be "same tools BigLaw already has, available to everyone" — not mercenary framing.

**2026-05-16 — First Amendment / access to courts positioning**
Access to legal knowledge = First Amendment right. The Bar/Westlaw/LexisNexis model = toll road on public law. The Maxwell/Pergamon parallel (walling off publicly-funded research) applies directly to Westlaw/LexisNexis on public case law. This is the campaign frame for the provocateur/debate play.

---

**2026-07-21 — Thomson Reuters / Westlaw connectors are permanently excluded, not a case-by-case call**
Prompted by reviewing a WillC/Open-Legal-Products post announcing a `mike-workflows` SKILL.md library (repo was effectively empty at review time — one commit, LICENSE only, license itself Apache-2.0 despite the post claiming MIT) and comparing it against Anthropic's own `anthropics/claude-for-legal` (real, mature: 12 practice-area plugins, 90+ named agents, 8.8k stars, launched 2026-05-12). That repo ships an `external_plugins/cocounsel-legal` plugin built and owned by Thomson Reuters for Westlaw Deep Research. Decision: never install it, and treat any Thomson Reuters/Westlaw-branded connector or plugin — in that repo, in any future marketplace, in any other project — as permanently out of bounds, not something to evaluate individually each time it appears. Grounding: *Thomson Reuters Enterprise Centre GmbH v. ROSS Intelligence, Inc.* — TR sued ROSS (an early legal-AI competitor) in 2020 over Westlaw headnote use, won partial summary judgment in Feb 2025 (Judge Bibas, D. Del.; fair-use defense rejected), and the litigation cost alone forced ROSS to shut down before the case even resolved. That is the anti-capture principle in CLAUDE.md made concrete: TR has a demonstrated history of using litigation to remove legal-AI upstarts rather than license to them, not merely a pricing model to route around. This exclusion is intended to travel — apply it to any project, not only Kingsfield, whenever a Thomson Reuters/Westlaw/CoCounsel connector shows up as an option.
Separately, the two external repos reviewed did not change the plan: `mike-workflows` has no content to adopt yet (watch, don't merge); `claude-for-legal`'s `litigation-legal`/`ip-legal` skill definitions are useful as a prompt-quality reference for Kingsfield's own already-built Crew agents (opposition-mapper, impeacher, dmca-takedown, ip-clause-review, infringement-triage — currently unwired behind the unauthenticated `/api/crew/chat` demo route) but not something to install wholesale. The higher-leverage move identified: wire the existing Crew agents into the authenticated `chat.ts`/`projectChat.ts` route, same pattern as the 2026-07-03 citation-verification wiring.

## Technical

**2026-05-16 — Font stack finalized**
Google Fonts blocked in widget sandbox (CSP). Solution: @fontsource via cdn.jsdelivr.net for previews, next/font/google for actual codebase. Bebas Neue removed, replaced with Playfair Display 900.

**2026-05-16 — Mike branding removal in progress**
MikeIcon removed from AppSidebar. InitialView rewritten (no more "Hi, {username}" with Mike's icon). More Mike references likely remain in the codebase — systematic cleanup needed.

**2026-05-16 — cal.diy identified as scheduling infrastructure**
`calcom/cal.diy` (MIT license, Next.js + tRPC + Prisma + Postgres) is a candidate for court deadline, SOL tracking, docket scheduling features. Integrate as backend service, not embedded UI.

**2026-05-16 — A/B testing architecture designed**
Once migration 110 runs, `crew_traces` and `llm_council_sessions` provide the raw data. Four evaluation layers planned: automatic judge scoring, Council advisor adoption tracking, user follow-up signal, Crew role contribution analysis. Judge prompt + `quality_scores` schema extension to be built.

**2026-07-03 — Citation verification wired into the real chat routes, not `/api/crew/chat`**
`current-state.md` previously claimed the frontend was repointed at `/api/crew/chat` for Four-Gate Citation Verification. That was false — verified by reading `frontend/src/app/lib/mikeApi.ts` directly: `streamChat`/`streamProjectChat` post to `/chat` and `/projects/:id/chat`, the routes with auth, `chat_messages` persistence, and MCP connectors. `/api/crew/chat` has none of that and the frontend never called it. Rather than repoint the frontend (which would drop auth and history), `verifyDraftForSse()` was added to `backend/src/middleware/hallucination_guard.ts` and wired directly into `chat.ts`/`projectChat.ts`, emitting a `verification` SSE event on the existing authenticated stream. Decision: verification belongs on the route that's actually in production, not on the route that's easiest to modify.

**2026-07-03 — Migration 110 and `cl_opinion_id` confirmed already live**
Both were listed as open blockers in CLAUDE.md and `current-state.md`. Checked the live Supabase project (`fzexglkmpoyxtkdiwelm`) directly via `list_tables` — `llm_council_sessions`, `crew_traces`, and `sources.cl_opinion_id` all already exist. Someone applied these outside of this session's tracking; docs were stale, not the database. Lesson: verify live DB state before trusting the "Open Wiring Tasks" list in CLAUDE.md — it isn't kept in sync automatically.

**2026-07-03 — Wingman harness lives in system_instruction, not send_client_content**
Both Wingman builds (wingman-demo server.ts and wingman_live.py) inject the agent harness via `systemInstruction` in the `live.connect` config. `send_client_content` on `gemini-3.1-flash-live-preview` is restricted to seeding initial history and requires `history_config` — routing the harness through the system instruction sidesteps that API change entirely and guarantees the persona is bound at session start. Harness files are duplicated (`wingman-in-your-ear/harness/` and `wingman-demo/harness/`) because wingman-demo is its own git repo; keep them in sync manually until a shared package exists.

**2026-07-03 — Wingman agent selection is a WS query param**
The PWA client picks one of three agents (court_pro_se / broadcast_market / deposition) before session start and passes it as `?agent=` on the `/api/live-ws` WebSocket URL. The server whitelists the key against its AGENTS map and loads the matching harness + voice (Charon/Fenrir). Selection is locked once the session starts — changing agents means a new session, which matches Live API semantics (system instruction is fixed per connection).

**2026-07-03 — wingman-demo stays a separate repo; verifier/judicial-intel stay in kingsfield**
wingman-demo is already its own git repo and stays that way (different runtime, deploy target, and lifecycle from the legal platform — per the handoff, don't merge until the PWA path is proven). The verifier and judicial-intel do NOT get their own repos: the citation benchmark is the evidence base for the four-gate product claim and shares CourtListener tooling/keys with the backend; splitting them adds sync cost with no isolation benefit. The actual repo-hygiene problem is data weight (opinion_cache, video datasets, venvs) — solved with .gitignore, not repo splits.

**2026-07-03 — Gate 4 (jurisdiction fit) silently broken, not fixed in this pass**
Live-testing citation verification (Miranda v. Arizona, Marbury v. Madison) surfaced that `sources.jurisdiction` is always stored as `''`, because `getCluster()` in `courtlistener.ts` reads `court`/`court_id` fields that no longer exist on CourtListener's v4 cluster response (court moved to the linked `docket` resource). An empty jurisdiction string is trivially "included" in any forum string in `assessJurisdictionFit()`, so every citation is misreported as `mandatory` regardless of actual court. Decision: flagged as a separate follow-up task rather than fixed inline, since it's a pre-existing bug in `verification/pipeline.ts`/`courtlistener.ts` unrelated to the SSE-wiring task at hand.

**2026-07-04 — Live DB had pervasive schema drift; fix additively, never drop**
The backend code was correct but the live Supabase DB was missing many objects the code referenced, surfacing as runtime errors one at a time (projects 500, upload fail, case-law crash, workflow "Use" error, analytics fail). Root causes fixed by additive migrations: `user_profiles` missing mfa_on_login/title_model/legal_research_us; `get_projects_overview` RPC never created; `document_versions` missing filename/file_type/size_bytes/page_count AND `deleted_at` (the latter made `loadActiveVersion` return null for EVERY doc → silently broke read_document in the assistant and case extraction); `user_api_keys` table missing (its PGRST205 crashed the whole backend); 5 `user_mcp_*` tables missing; `tabular_reviews.document_ids` missing. Decision: a background task (task_8407d280) was spawned to audit ALL `.from()/.rpc()/column` refs vs live DB in one sweep. Lesson: this codebase's migrations/ files were never fully applied live — always verify live schema before trusting it.

**2026-07-04 — Node unhandledRejection now logged, not fatal**
A single rejected promise in a route (the missing user_api_keys table) crashed the entire backend (Node's default since v15). Added `process.on("unhandledRejection")` in `index.ts` to log instead of exit. Treats the symptom; the underlying fire-and-forget rejections should still be caught at source.

**2026-07-04 — Case Law is in-app, not link-out**
CourtListener is the SOURCE, not the destination. Case Law results now open a full opinion reader in-app (`/case-law/case-opinions` → full text, four-gate verified) with CL cited in the footer. Same philosophy will apply to Legislation when built.

**2026-07-04 — Auth validated via short-TTL cache, not per-request network call**
Every authed request was doing a network round-trip to Supabase (`admin.auth.getUser`) + a fresh client + an MFA DB query (~200ms), and the frontend fires 5-8 parallel authed requests per page load. Fix (`middleware/auth.ts`): singleton admin client + 60s in-memory caches keyed by token (user) and user (MFA pref). Only the first request in a burst pays. Security tradeoff accepted: a revoked token stays valid up to 60s. Measured: cached auth ~0ms; 8-endpoint burst ~0.5s wall-clock.

**2026-07-04 — Council/advisor output renders as Markdown**
The chairman verdict + advisor responses + framed question contain Markdown (##, **, lists). They were rendered as raw pre-wrapped text ("white with lines" complaint). Now rendered via react-markdown + remark-gfm through a `Prose` component using arbitrary-variant element styling (the @tailwindcss/typography plugin is NOT installed). Headings/bold intentionally inherit the wrapper's themed color (no hardcoded text-gray-900) because the app's dark-mode overrides only recolor literal utility classes, not arbitrary variants — hardcoding made them invisible on dark.

**2026-07-04 — Court list is a disk snapshot, not a runtime proxy**
CL's `/courts/` endpoint is hard-capped at `page_size=20` and the account throttles at ~5 req/min, so the ~3,360-court list can't be crawled at request time (~170 requests ≈ 35–60 min). Decision: `backend/scripts/fetch-courts.mjs` crawls it politely into `backend/data/courtlistener-courts.json`; `GET /api/research/courts` serves the snapshot from memory. Court lists change a few times a year — re-run the script and restart the backend to refresh. The frontend picker falls back to a static federal list with an honest notice if the snapshot is missing.

**2026-07-04 — CourtListener rate limits are the real constraint, surface them honestly**
Measured live: general API ~5/min, `/citation-lookup/` 50/hour (shared by Gate 1 verification and Analytics cite-count enrichment). Both consumers degrade gracefully (verification fails closed; enrichment skips and logs). The Case Law page now shows "CourtListener is rate-limiting requests — retry in ~Ns" on 429 instead of the misleading "Search API unreachable". Anti-capture note: if these limits pinch in production, the answer is caching primary-source data (as with the courts snapshot), not a Westlaw contract.

**2026-07-04 — Analytics common↔rare axis: agent novelty for claims/defenses, CL citation counts for authorities**
The columnar redesign (replacing the unreadable force graph) clusters each of the 3 categories by a different measure of commonness: allegations/defenses carry an agent-judged `novelty` (common/uncommon/novel) emitted by the extraction prompt; authorities carry `cite_count` from a single batched CourtListener citation-lookup at extraction time (1,000+ = landmark, 100+ = well-established, <100 = rarely cited, unresolved = rules/statutes). Chosen because no single axis fits both: citation frequency is objective for cases but meaningless for a legal theory, and the agent can judge theory-novelty but shouldn't guess citation counts. Built without re-asking the user (they had dismissed the clarifying question and then asked for all issues finished); the documented "likely intent" was followed — revisit the tier thresholds if they feel wrong in use.

**2026-07-04 — The `get_*_overview` RPC family was never created live; back-port migrations from now on**
Three RPCs the routes depend on didn't exist in the live DB: `get_projects_overview` (fixed earlier), `get_tabular_reviews_overview` (the entire "Tabular Review create bug" — creates always worked, the list fetch 500'd), and `get_chats_overview` (every chat-list load 500'd). New rule followed this session: every live `apply_migration` gets a matching file in `backend/migrations/` (140_tabular_reviews_overview.sql, 150_chats_overview.sql) so a DB rebuild doesn't regress.

**2026-07-04 — Analytics = case-intelligence extraction, and it's being redesigned**
Built an extraction agent (`backend/src/lib/caseIntelligence.ts`) that strips an uploaded doc into structured facts (entities by role, allegations, defenses, authorities, rarity), stored in `case_intelligence`, auto-triggered on tabular-review upload + manual "Analyze". First UI was a d3 force graph + 3-column cluster. User found the force graph unreadable ("complete fail") and wants a columnar, 3-color-category layout (like CL's jurisdiction picker) with items clustered by common-vs-rare/popularity. Redesign is PENDING the user's answer on the exact 3 categories and the clustering axis — do not rebuild blind.

**2026-07-04 — Council expanded to four model families (DeepSeek + Kimi seated)**
Per Aaron: open-weight models benchmark competitively and diversity is the Council's design goal. New routing (`llm-council/providers.ts`): Contrarian + Chairman → Claude Opus 4.8 (upgraded from 4.7, same price), First Principles → DeepSeek V4 Pro, Expansionist → Gemini 3.1 Pro (upgraded from stale 2.5), Outsider → Kimi K2.6, Executor → Claude Sonnet 4.6. DeepSeek/Kimi called via their OpenAI-compatible APIs (`lib/openaiCompat.ts`); keys: DEEPSEEK_API_KEY + MOONSHOT_API_KEY (or KIMI_API_KEY) in backend/.env — NOT YET SET; until then those seats fall back to Claude Opus with a logged warning. Note: DeepSeek's legacy IDs (deepseek-reasoner/-chat) hard-deprecate 2026-07-24; kimi-k2 line discontinued 2026-05-25 — v4/k2.6 IDs used. Chairman and citation verification deliberately stay on Claude. Still open from the cost review: prompt caching (zero cache_control in backend — biggest cost lever), reviewers-on-Haiku, Batch API for background extraction.

**2026-07-05 — CRITICAL: CourtListener account is capped at 125 requests/day, account-wide**
Re-running the courts crawler triggered `429 Rate limit exceeded: 125/day` — confirmed via a second, unrelated endpoint (`/search/`) that this is an **account-wide daily cap covering every CourtListener endpoint**, not a per-endpoint or per-minute-only limit. This is far more restrictive than the 5/min-general + 50/hr-citation-lookup limits documented on 2026-07-04, and it means the *entire app's* CourtListener-dependent surface (case-law search, citation verification, cite-count enrichment, the courts snapshot) shares one 125-call/day budget. At any real beta-user volume this is unworkable — a handful of chat sessions with citation verification could exhaust the day's quota before noon. **This is now the top blocker for beta, above deployment**: email Free Law Project for a limit increase (mission-aligned nonprofit, they raise limits for legitimate legal-access projects — this is more urgent than "nice to have" now), and/or evaluate a paid CourtListener tier if one exists. Until raised, minimize dev-loop testing against the live API (use the cached `sources` table and the courts snapshot, don't re-fetch to "double check"). Courts crawler is paused via checkpoint (`backend/data/.courtlistener-courts.checkpoint.json`) and will resume where it left off next run, but at this budget a full crawl could take many days of quota sharing with production traffic — reconsider fetching a static/community-published CourtListener court list instead of self-crawling.

**2026-07-13 — Assistant is the intake front door; Case Map is the deep map; no auto-workflows; no Ulysses style pack**
Product map confirmed with Aaron: (1) case extraction auto-runs on **every** document upload (standalone Assistant included), not only project/tabular attach; (2) structured extract card surfaces in Assistant chat with chips to Case Map + Document Editor; (3) former "Analytics" page renamed **Case Map** (per-document intelligence) — **Judicial Analytics** is a separate Coming Soon product (cross-matter/judge/counsel graphs); (4) Workflows are **opt-in templates only** (Assistant prompt or Tabular column set) — never auto-started on upload, with on-page explanation; (5) no multi-style export pack (Pleading/Agreement/Memo skins) this pass; (6) Document Editor is Review-mode viewer with authority (blue) + prior-filing (green) paint — not a free-form Word clone, not WP plugin install. Explicit non-goals locked: do not move parser exclusively into Analytics; do not auto-start workflows; do not dump 15 Ulysses skins; do not build WP clone first.

**2026-07-13 — Helvetica Neue site-wide; elegant thin weights not brutalist**
Display/serif/editorial utilities and body all resolve to local Helvetica Neue OTFs. Tailwind font-bold/semibold remapped lighter so labels (e.g. Council form) stay thin and open. Word/WordPerfect teaser lives in sidebar Coming Soon, not on the Council page.

**2026-07-13 — API base derives from page host for LAN testing**
`getApiBase()` uses `window.location.hostname:3001` when env is blank so phones on Wi-Fi hit the Mac backend. Hardcoding `localhost:3001` in page modules breaks multi-device demos. Share URL must include port (`http://LAN-IP:3000`). Demo mode left off unless explicitly enabled. Servers stopped when session ended.

**2026-07-13 — Refuse sparse/image-only PDF extracts; Assini is the text demo**
PACER/RICOH scans (e.g. Heppner) often only have header stamps as a text layer — hollow Case Map rows are worse than a clear error. `isSparseLegalText()` fails closed with an honest message. Google Scholar text PDFs (e.g. Assini v. Hayward) are the correct extract demo. Full OCR/vision pipeline is future work.

**2026-07-13 — Dual retrieval: File Search + URL Context both ship, not either/or**
Ask-the-manual (Gemini File Search) and chat-with-docs (urlContext) are complementary engines under one product: private uploaded corpora vs official public URLs. Answers are source-labeled; four-gate still applies to case citations. Do not force a tradeoff between the two — orchestrate by intent (my docs vs official pages vs verified case law).

**2026-07-27 — The published citation benchmark had 87 groundings scored against the wrong opinion; the MCP route is the only trusted resolver**
Auditing `verifier/results_full.json` found its 139 "grounded" entries came from two fetch routes with opposite outcomes: MCP `opinion_view` (n=52) was 88.5% verified with a median fuzzy score of 100.0, while the older direct-REST resolver (n=87) was 80.5% `not_found` with a median score of 52.8. That is a resolver defect, not a data difference — the REST route wrote `cl_url` values pointing at CourtListener cluster IDs in the 10.2M–10.7M range, which are 2025–2026 filings, so entries citing e.g. 293 U.S. 474 (1935) or 378 U.S. 368 (1964) were fuzzy-matched against unrelated modern opinions (an AEDPA-deference quote against an Oklahoma sheriff's-sale case; an adoptive-admission quote against a Title VII retaliation case). Decision: quarantine rather than delete — `verifier/quarantine_bad_grounding.py` moves the bad block to `verification_quarantined`, sets `opinion_found=false` and `grounding_status="needs_refetch"`, logs all 87 to `quarantine_report.json`, and backs up `results_full.json` first. Re-running `ground.py` against the existing `opinion_cache/` then correctly re-grounded 3 of them, proving the pipeline is sound when handed the right opinion. Real grounding is **55/1,979 (2.8%)**, of which **49 (89.1%) verified** — not the 139 (7.0%) previously reported. New rule: any citation→opinion resolver must assert that the resolved opinion's date is consistent with the cited reporter volume before accepting the match. Never reintroduce the direct-REST resolver without that guard.

**2026-07-27 — Production Gate 1 is NOT affected by the resolver bug — verified, do not "fix" it**
Checked `backend/src/verification/pipeline.ts` directly before assuming the defect was shared. Production resolves citations via `citationLookup()` — CourtListener's Citation Lookup API, which parses volume/reporter/page and returns matched clusters — then filters on `status === 'matched'` and vetoes (fails closed) when nothing matches. There is also a bulk path that parses citation parts locally. This is a structurally different and correct mechanism from the research script's search-and-take-first approach. The 87 bad rows were confined to a one-off benchmark script. Recorded so a future session doesn't "discover" the bug again and refactor working production code.

**2026-07-27 — HF dataset corrections are revised in place with a visible notice, never silently overwritten**
`Kingsfield-Lawfare/legal-citation-benchmark` was already public (CC BY 4.0, 146 downloads) with three defects: (1) both `results_full.json` and `kingsfield-verified-2026-06-01.json` sat in the repo root so the loader concatenated them — `load_dataset()` returned ~3,958 rows for a 1,979-entry benchmark, and the two copies did not agree on every field; (2) the 87 mis-resolved groundings; (3) `benchmark_summary.md` listed Gemini's verdict distribution as 390/267/1,123 and concluded "Gemini says unsure far more often" — actual is 986/621/**173**, i.e. Gemini abstains *least* and Claude abstains most (579). The row and the conclusion drawn from it were both backwards. Decision: revise v0.1 in place rather than publish v0.2 alongside, and lead the dataset card with the correction — what broke, how many rows, and what it means for anyone who already ran numbers. For a verification product, publicly documenting a self-caught error is a stronger credential than a clean card. Duplication fixed durably by declaring an explicit `configs:`/`data_files:` block in the card YAML pinning the split to `results_full.json`, so a stray JSON in the repo can never be swallowed again.

**2026-07-27 — Model rationales in the benchmark contain fabricated citations; the `reason` field is evidence, not authority**
Entry `idx: 1` (ABSOLUTE PRIORITY RULE) — the literal first row of the public dataset — carries a Claude `"yes"` verdict justified by two invented citations: "Case v. Los Alamos Grazing Ass'n, 308 U.S. 106 (1939)" and "Dewsnup v. Timm, 526 U.S. 434 (1992)". Verified against CourtListener: 308 U.S. 106 is *Case v. Los Angeles Lumber Products Co.* (cluster 103240) and a full-text search for "Los Alamos Grazing" returns **zero results** across 8.2M opinions; 526 U.S. 434 is *Bank of America v. 203 North LaSalle Street Partnership* (1999, Souter, J., cluster 118285), not Dewsnup and not 1992. Notably the model had the doctrine and both reporter cites right — *203 N. LaSalle* actually cites *Case v. Los Angeles Lumber* at that exact page — and invented only the party names. Everything a reader spot-checks at a glance was correct. Decision: document this as a worked example on the dataset card rather than quietly fix it, and state plainly that the rationales have **not** been systematically audited (n=1, checked only because it is row 1, which implies the rate is not low). Planned follow-up: extract and resolve citations from all 1,780 `agent_verdicts.reason` fields to produce a measured per-model fabrication rate — arguably a more valuable dataset than the one currently published, since it measures whether models fabricate *while claiming to verify*.

**2026-07-27 — Build the US layer on top of Charlotin's tracker; do not clone it, do not attack the maintainer**
Reviewed the AI Hallucination Cases database against a proposal to compete with it. Findings that set the direction: upstream is more capable than a "guy with a spreadsheet" framing suggests — published inclusion criteria and FAQ, a contributor network (Jesse Schaefer 227 rows, Courtready 99, Robert Freund 46, Volokh 36), a full graphs layer, a daily CSV export, an evolving schema (14 → 18 columns), and its own verification tool (PelAIkan). Only **27.7% of rows carry a human credit**; the other 72% come from his own scrapers, keyword searches, and legal-editor flags. Courts now cite the database in published opinions (11th Cir. *Parnell*; 5th Cir. *Fletcher v. Experian*) and perma.cc-archive it. The real gap is narrow and structural: the export is a flat file with free-text analytics (560 distinct `Outcome` values, 329 unresolvable court strings, 86% of `AI Tool` empty signal, money unparseable) and **no US procedural model** — no judge, docket, reporter citation, opinion ID, or sanctioning authority (Rule 11(b)(2)/(c), § 1927, inherent power, local rule, RPC 3.3). He cannot add that without abandoning global scope, because no single procedural vocabulary fits 1,800+ cases across 40 jurisdictions. He also concedes the count is "necessarily an undercount" by design, since he only records what a judge wrote about — which is the standing justification for a RECAP base-rate sweep over *filed briefs*. Decision: build `hallucination-registry/` as a normalization + enrichment layer with attribution and upstream corrections, compete on the procedural/verification layer, and keep the dataset free and open per the anti-capture principle. Explicitly rejected: cloning the global incident count (no differentiation, permanent manual cost, behind on recall day one), and any framing that attacks the maintainer personally — bar associations and courts are exactly the audience that would notice.

**2026-07-27 — *Mata v. Avianca* citing references are the de facto tag for hallucination decisions**
There is no formal tag, hashtag, or topic code for AI-hallucination cases in any free source. But the citation graph supplies one: a search for opinions citing *Mata v. Avianca* returned 20 US decisions in 2026, **16 of which (84%) were already in Charlotin's database** — judges reach for *Mata* when sanctioning for fabricated citations, so its citing references track the same population. A second synthetic tag: opinions citing Charlotin's database itself (4 real hits, all genuine). Decision: the intake pipeline is three queries — broad keyword terms (`hallucinated`, `nonexistent case`, `fictitious/fabricated citation`), *Mata* citing references, and Charlotin citing references — run weekly, deduped against the registry, with an LLM classification pass over the residue. Candidate discovery is easy and free; **classification is the bottleneck**, which is what the four gates plus an LLM pass are for. Byproduct worth keeping: the same queries surface court *rulemaking* (e.g. Okla. Crim. App., 2026 OK CR 7, adopting an AI rule and citing *Mata*), which is outside Charlotin's inclusion rule forever and is the seed corpus for the standing-order/compliance product.

## 2026-09-19 — Judicial intel: ground truth, model role, commit policy

- **Ground truth for Florida DCA outcomes comes from the courts' own opinion JSON API** (`flcourts-media.flcourts.gov/_search/opinions/`, `type=opinions` + `type=pca`), not CourtListener and not Google Scholar. It is unauthenticated, returns disposition as a field, includes PCAs, and is what Juriscraper uses. Hit at ≤2 req/s with an identifying UA. CourtListener stays as a cross-check (token limited to 100 req/hour).
- **Jev is a lift-with-abstention model, not an accuracy model.** Ship `skepticism_gap` (Python-composed from two atomic scores) and confidence-gated `ruling_lean` (abstain below 0.7). Never report a mean score; carry every level's probability and a bimodal flag.
- **Behavioral nouls are the descriptive layer.** They showed zero outcome signal; they are not forecasts and must not be presented as such.
- **Live-stream tabs are excluded from the OA corpus**; per-case clips are the unit.
- **Commit policy after the repo-deletion incident:** work goes up on a branch + PR; deletions are never staged without explicit review; media, Keynote decks, nested git repos and regenerable caption/transcript data are gitignored (see `.gitignore` and `verifier/.gitignore`, 2026-09-19 blocks).
- **Mike upstream is not to be synced blind.** `Kandy22/mike` is a current standalone copy of upstream; merging its 600+ changes into Kingsfield is a planned migration, not a routine pull.

## 2026-10-05 — Deterministic citation cascade: local SQLite Gate 1

- **SQLite replaces Task 3.1's Postgres/pgvector for Gate 1.** `kingsfield_florida.db` (B-tree index on reporter, volume, page) serves single-user, local, deterministic lookups. Postgres/pgvector is reserved for multi-user deployment.
- **Constraint A is Florida-scoped.** Florida keys (Southern Reporter with a Florida court parenthetical, `Fla. L. Weekly`, `Fla. L. Weekly Supp.`) must match locally or veto. Federal and other state keys fall through to CourtListener `citationLookup()`. Southern Reporter also covers other states, so the reporter alone does not make a citation Florida. A Southern Reporter citation with no court parenthetical is vetoed as malformed. `Fla. L. Weekly` stays in scope and fails closed until its data is loaded.
- **Production integration is a pre-filter, not a replacement.** The 2026-07-27 rule stands: `citationLookup()` is not refactored. `backend/src/verification/local_sqlite_gate.ts` runs first; the lead wires it into `pipeline.ts` after adversary signoff and a separate review.
- **The runtime check uses Node's built-in `node:sqlite`**, not `better-sqlite3`. Fallback: a synchronous Python SQLite child process.
- **Von does not run on this Intel Mac.** The newest PyTorch with a macOS x86_64 wheel is 2.2.2 and Docker is not installed. The router ships with `direct_db` as the hardcoded fallback and a stub `/v1/systemone` client for a remote Von server.
- **Python cascade code lives at the repo root** (`db/`, `pipeline/`, `router/`) and runs on `~/.venv-cascade` (Python 3.12, eyecite). Bulk CourtListener CSVs and CAP data go only to `/Volumes/Kingsfield_Corpus`.
- **The adversary agent owns the bypass tests**, not the builder, so the builder cannot weaken the suite it must pass.


## 2026-10-05 — Gate 1 scope rulings made while building the local gate

- **Southern Reporter falls through only on positive identification.** A So./So. 2d/So. 3d cite falls through to CourtListener only when its parenthetical matches a closed list of known non-Florida courts (Ala./La./Miss. variants, federal). Anything unrecognized — `(citation omitted)`, OCR damage like `(F1a.)` — vetoes. Reason: "not Florida" by default was a fail-open hole the adversary found.
- **Florida parenthetical + unrecognized or OCR-confusable reporter vetoes; a reporters_db-recognized reporter falls through.** `S0. 3d` and `FIa. L. Weekly` veto. `WL`, `Fla.` (Florida Reports), `Fla. Supp.` and `F.3d` fall through per Constraint A.
- **Fla. L. Weekly division letters are part of the key.** `citation_index.section` exists, and D500, S500 and 500 never match each other.
- **Court level is cross-checked; DCA district is not.** A `(Fla. YEAR)` cite against a stored `fladistctapp` record, or a DCA cite against a stored `fla` record, vetoes as `court_mismatch`. District numbers aren't compared, because CourtListener lumps all DCAs into one court id.
- **Backend-wide bypass test is deferred to wiring, not dropped.** The adversary's check for `citationLookup()` calls outside the gate skips until `local_sqlite_gate` is imported into backend code, then goes live. `researcher.ts:123` is the known open bypass it will catch.


## 2026-10-05 — Gate 1 draft mode and backend wiring

- **Constraint A does not yet hold in chat — known exception, merge-to-main blocker.** `routes/chat.ts` (and `projectChat.ts`) stream model tokens to the user over SSE *before* `verifyDraftForSse` runs Gate 1, so a hallucinated citation is on screen before its veto arrives as an advisory flag (adversary finding W2). Stream-vs-buffer is the user's product decision for the follow-up task. The same follow-up covers W3 (verdicts are not persisted with the chat message, so a reload shows a vetoed cite unflagged) and W4 (aborted/errored streams are saved and shown unverified). The adversary's W3 reload test is skipped with this entry as its reason.
- **Do not merge `feature/local-sqlite-gate1` to `main`** until `kingsfield_florida.db` is built and populated, and W2–W4 are resolved. Without the DB every Florida citation vetoes `db_unavailable`.
- **Draft parsing lives only in Python.** `localGate1Text()` in `local_sqlite_gate.ts` runs `check_text()` in `pipeline/gate1.py` through an async child process (draft on stdin, max 4 concurrent children, bounded queue wait → `gate_busy` veto, every failure resolves to exactly one veto). No second citation parser in TypeScript.
- **Short cites, Id. and supra resolve through eyecite** and inherit their antecedent's verdict, with their own pin checked; a short cite's name must match its antecedent. They are never vetoed as `malformed`. Unresolved or ambiguous short forms veto.
- **A local Gate 1 pass skips `citationLookup()`.** The local index is built from CourtListener bulk data, so its cluster id fetches the opinion text directly; this preserves the CourtListener rate limit. Only an explicit `fall_through` reaches `citationLookup()`.
- **Wiring:** `verifyCitation` (single cite), `verifyDraft` (whole draft) and the Researcher (via `confirmExistence()` in `pipeline.ts`) all run local Gate 1 before the cache and any CourtListener call. `researcher.ts` no longer calls `citationLookup()` directly.
- **Path-guard identity:** cascade agents must be spawned as plain `backend_builder` / `adversary` subagents and must pass an identity probe (a write the hook must refuse) before writing. A team-spawned builder was not recognised by `enforce_agent_dirs.py` and wrote via Bash heredocs, which the hook does not path-check; the edits were reviewed and kept. The Bash gap in the hook is open.


## 2026-10-06 — Gate 1 draft mode: signoff scope and test load

- **Findings 1-3 from the signoff review go to the chat follow-up task as merge-to-main blockers**, alongside W2-W4: `/api/crew/chat` and `/api/council` release model text with no Gate 1, and `runResearcher`'s model-written notes are returned unchecked. Constraint A does not hold on those paths yet. The adversary's tests for them are skipped with this entry as the reason, bodies intact.
- **The unauthenticated model routes on `main` are an urgent security fix, handled on `main` independently of this branch** (remove the routes or add `requireAuth`). Not done from the cascade session.
- **Finding 4 is in scope for this module:** the draft cleaner must not discard user-visible text (HTML attribute values, comments, markdown link/image titles). Any of it can carry a citation.
- **The test suite must respect this Intel Mac's heat/load limits.** Concurrency and exact-cap tests are deterministic and light: few Python children, no long sustained runs. Speed budgets are calibrated to this machine by making the work smaller, never by raising timeouts, and veto assertions are never weakened.


## 2026-10-06 — System One routing moves from the Von stub to local llama.cpp

- **Routing now runs locally on this Mac's CPU.** A quantized model loaded through llama.cpp (or ONNX) in `router/` answers the Choice/Noul/Score questions. A Von System One endpoint is still supported when one is configured. This replaces the 2026-10-05 position that no model runs on this Intel Mac and routing goes only to a remote Von stub. `router/jev_cpu_inference.py` (user-authored) is the foundation; wiring it is the next task.
- **`direct_db` stays the fallback.** Any routing output that is not exactly one allowed option, any error or timeout, a missing model, or confidence below the threshold routes to `direct_db`. Routing never bypasses Gate 1.
- **CLAUDE.md Constraints C and E rewritten** (C: Local Routing; E: Zero LLM APIs). Hosted LLM APIs stay forbidden for routing and Gates 1-4. CourtListener stays allowed for non-Florida Gate 1 and Gates 2-4 until the corpus is local. Each module needs a fast test target under 30 s; the full adversary signoff suite stays under 5 minutes with at most 4 concurrent processes.
