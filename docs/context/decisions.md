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
