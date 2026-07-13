# Kingsfield Lawfare — Current State
*Last updated: 2026-07-04 (evening session)*

> ⚠️ **NEWER: read `SESSION-2026-07-12-handoff.md` first** — covers running the
> demo suite (Kingsfield = 2 servers!), Video Analyzer fixes (committed), LAN +
> no-login demo mode (committed), and a list of UNCOMMITTED fixes to protect
> (Wingman, verifier pipeline, pro-se veto, Face Mood stop-music button).

This file is the handoff brief. Any new session — Claude Code, Cowork, or Claude.ai — should read this first alongside CLAUDE.md.

---

## ⭐ NEXT SESSION — START HERE (2026-07-04 evening handoff)

**Environment / how to run:**
- Backend: `cd backend && npm run dev` → port 3001. Frontend: `cd frontend && npm run dev` → port 3000. (Preview harness also works via `.claude/launch.json` config `kingsfield-frontend`.)
- Wingman PWA shares port 3000 with the frontend — only one at a time. Its launch config is `wingman-pwa`.
- Login: `aray.aaron@gmail.com` / temp password **`Kingsfield-Reset-2026`** (reset in auth.users this session; user should change it).
- tsx watch has been flaky (occasional exit 144) AND it does not always reload on edit — if a route behaves like old code, `pkill -f 'tsx watch' && npm run dev` for a clean restart (this bit us again 2026-07-04: route edits silently didn't take effect).
- Supabase project id: `fzexglkmpoyxtkdiwelm`. Backend env has both `COURTLISTENER_TOKEN` and `COURTLISTENER_API_TOKEN` (same value — code reads both names).

**⚠️ CourtListener rate limits (measured live 2026-07-04, this token):**
- General API: ~5 requests/min (the documented 5,000/hr does NOT reflect reality for this account — bursts throttle at 5/min).
- `/citation-lookup/`: **50/hour** — this is the budget for Gate 1 existence checks AND the new Analytics cite-count enrichment. Heavy verification testing exhausts it fast; both degrade gracefully (verification fails closed, enrichment skips with a log line).
- `/courts/` is hard-capped at `page_size=20` → the full ~3,360-court list takes ~170 requests. It is therefore **snapshotted to `backend/data/courtlistener-courts.json`** by `backend/scripts/fetch-courts.mjs` (throttle-respecting, ~60 min) and served from disk by `GET /api/research/courts`. Re-run the script + restart the backend to refresh.

**FIXED & VERIFIED this session (2026-07-04 evening) — the previous open-items list is DONE:**

1. **Analytics redesign — BUILT.** Force graph deleted. New columnar layout (`analytics/page.tsx`): "The players" role-grouped entity chips, then 3 color-coded columns — Allegations (red), Authorities (blue), Defenses (green) — each clustered common → rare. Axis: agent-judged `novelty` (common/uncommon/novel, new field in the extraction prompt) for allegations/defenses; CourtListener `cite_count` for authorities (enriched at extraction time via one batched citation-lookup — `enrichAuthorityCiteCounts()` in `caseIntelligence.ts`; tiers: 1,000+ landmark / 100+ well-established / <100 rarely cited / null = rules & statutes). Hover-an-authority cross-highlight kept. Old extractions lack novelty/cite_count and fall into unlabeled/unresolved buckets — re-analyze to rank them. Verified live with the Perrin extraction and a fresh complaint.pdf re-extraction (novelty populated; cite_count null only because the 50/hr lookup quota was exhausted at test time).
2. **Tabular Review create bug — FIXED.** Root cause: `get_tabular_reviews_overview` RPC never existed in the live DB; creates always succeeded, every list fetch 500'd. RPC created live + back-ported to `backend/migrations/140_tabular_reviews_overview.sql`. Verified end-to-end via authed `GET /tabular-review` (200, both "missing" reviews returned).
3. **Full jurisdiction picker — BUILT.** `GET /api/research/courts` serves the court snapshot (see rate-limit note above). New `frontend/src/app/components/case-law/CourtPicker.tsx`: tabs (Federal Appellate / Federal District / Bankruptcy / State / More), cross-tab search, multi-select checkboxes (search sends space-separated court IDs — CL supports it), section grouping (state supreme/appellate/trial), "include historical" toggle, offline fallback to a static federal list when the snapshot 503s. Case Law page now uses it (old 65-entry hand-maintained dropdown deleted). Verified in browser; full-list verification pending snapshot crawl completion.
4. **`get_chats_overview` RPC missing (found during verification)** — every `GET /chat` list 500'd. Same drift pattern. Created live + back-ported to `backend/migrations/150_chats_overview.sql`. Verified 200.
5. **Gate 4 empty-jurisdiction hole closed** — `assessJurisdictionFit()` now returns `null` (unknown) for empty jurisdiction instead of misreporting `mandatory` (`''` is a substring of every forum string). The docket-resolution fix itself was already committed (49881f5).
6. **Auto-extract on project upload** — `handleDocumentUpload` in `routes/documents.ts` now fires the same fire-and-forget case-extraction as tabular-review create when the upload targets a project (skips already-analyzed docs). Standalone uploads keep manual Analyze.
7. **Case Law honest rate-limit UX** — backend passes CL 429s through as `{error:'rate-limited', retry_in}`; frontend shows "CourtListener is rate-limiting requests — retry in ~Ns" with a retry button instead of the misleading "Search API unreachable".

**FIXED & VERIFIED this session (see detailed sections below):** Council raw-markdown render ("white with lines"), a cascade of live-DB schema drift (user_profiles cols, get_projects_overview RPC, document_versions cols incl. the critical `deleted_at` that broke read_document + extraction, user_api_keys table, 5 MCP tables, tabular_reviews.document_ids), the crashed-backend guard, Case Law in-app opinion reader, Case Law 50 states, modal ghostly-backdrop, Sign Out, the Analytics/Case-Intelligence extraction feature (built from scratch, working), and the auth-caching speed pass (~200ms→~0 per cached request).

**⚠️ Live-only migrations (no `.sql` files):** all schema fixes this session were applied directly to the live DB via the Supabase MCP `apply_migration`, NOT committed as files in `backend/migrations/`. Names applied: add_missing_user_profiles_columns, create_get_projects_overview, add_missing_document_versions_columns, add_document_versions_deleted_at, create_user_api_keys, create_user_mcp_connector_tables, add_tabular_reviews_document_ids, create_case_intelligence. If you rebuild the DB from `backend/migrations/`, these will be missing — back-port them to `.sql` files if that matters.

**Git state:** all changes uncommitted on `main`. New untracked file that matters: `backend/src/lib/caseIntelligence.ts`. Nothing committed or pushed this session (user hasn't asked). Modified files span backend (auth, index routes, tabular, documents, coordinator, index.ts) and frontend (analytics, case-law, council pages; ChatView, InitialView, AppSidebar, Modal components).

---

## What's Built and Working

### Frontend (Next.js 16 / React 19 / Tailwind v4)
- **Landing page** (`frontend/src/app/page.tsx`) — Dark navy (#1A1E2E), Playfair Display 900 wordmark, gold (#C8A96E) accent, IBM Plex Mono labels, four-gate chips, "Enter the App" CTA. Single viewport, no scroll. Fonts loaded via next/font/google.
- **AppSidebar** — Kingsfield gold orbit mark + Playfair wordmark replacing Mike's icon. Nav: Assistant, Projects, Case Law, Legislation, Tabular Review, Workflows, Council.
- **InitialView (chat home)** — Kingsfield wordmark, gold rule, 6 real starter prompts reflecting actual use cases, footer copy: "Every citation verified · Primary sources only · Not legal advice — legal knowledge."
- **Council page** (`/council`) — Five advisor cards with sharpened descriptions. Contrarian, First Principles (Gemini Pro), Expansionist, Outsider (Gemini Flash), Executor.
- **Case Law page** (`/case-law`) — CourtListener-backed search with jurisdiction dropdown and four-gate chips on results.
- **Legislation page** (`/legislation`) — Federal sources + all 50 states + DC + PR.

### Backend
- Crew agents exist: `coordinator.ts`, `researcher.ts`, `strategist.ts`, `contract-analyst.ts`, plus specialty skills.
- LLM Council orchestrator exists: `orchestrator.ts`, `providers.ts`, `prompts.ts`.
- Skills layer: `backend/skills/` contains 9 production-ready legal workflow skills (see below).
- **Four-Gate Citation Verification is wired into the real production chat routes.** `backend/src/middleware/hallucination_guard.ts` exports `verifyDraftForSse()`, which both `backend/src/routes/chat.ts` and `backend/src/routes/projectChat.ts` call right after the assistant's reply is fully assembled (before persistence, before the SSE connection closes). It runs `verifyDraft()` from `backend/src/verification/pipeline.ts` against the live CourtListener API and writes to the `sources`/`citations` tables, then emits one more SSE event on the same connection: `{type: "verification", verdicts, hasVetoes, hasConditional, error?}`. Verification failures fail closed (`hasVetoes: true`) without crashing the chat response. Live-tested against real citations (Miranda v. Arizona, Marbury v. Madison) on 2026-07-03 — both verified end to end, rows persisted with `cl_opinion_id` populated. **Known gap:** `sources.jurisdiction` is currently always stored as an empty string (see blocker below), so Gate 4 (jurisdiction fit) always reports `mandatory` for chat-originated citations regardless of the actual court — filed as a follow-up, not fixed as part of this wiring.

### Skills (backend/skills/)
All migrated from HeyCounsel community repo:
- `privilege-sentinel` — pre-flight privilege check before sending legal content to AI
- `matter-journal` — per-matter case files with auto-logging (maps to Projects feature)
- `tx-title-analysis` — Texas title analysis, production-ready with 15+ reference files
- `employment-law-research` — 50-state employment law research
- `formation-counsel` — US/Canada startup formation, attorney-facing
- `legal-guidance-vault` — guidance archiving and retrieval
- `template-synthesizer` — document template generation
- `redline-emailer` — contract redline + email workflow
- `SKILL_TEMPLATE` — blank template for new Kingsfield skills

---

## What's NOT Working / Not Wired

### Critical blockers (must fix before product works end-to-end):

1. **Chat route** — CORRECTION (2026-07-03): the previous claim that `streamChat`/`streamProjectChat` post to `/api/crew/chat` was **false** — verified by reading `frontend/src/app/lib/mikeApi.ts` directly. They actually post to `${API_BASE}/chat` and `${API_BASE}/projects/:id/chat` (`backend/src/routes/chat.ts`, `backend/src/routes/projectChat.ts`), which is the real production path: auth, `chat_messages` persistence, multi-turn history, MCP connectors. `POST /api/crew/chat` (`backend/src/routes/index.ts`, calls `runCrew()`) has no auth, no persistence, and the frontend never calls it — it's a separate, unwired demo endpoint. ✅ Citation verification has now been wired into the real chat routes instead of swapping the frontend to the unauthenticated crew endpoint (see Backend section above).

2. **Migration 110** ✅ APPLIED — confirmed live in Supabase project `fzexglkmpoyxtkdiwelm` via `list_tables` on 2026-07-03: `llm_council_sessions` and `crew_traces` both exist.

3. **`sources.cl_opinion_id` column** ✅ PRESENT — confirmed live on 2026-07-03; `sources` table already has `cl_opinion_id bigint`, and `verifyDraft()` writes to it successfully (verified with a real CourtListener round-trip).

4. **Gemini API key** ✅ SET — `GEMINI_API_KEY` is in `backend/.env` and `backend/src/index.ts` instantiates the `GeminiClient` from it (lines 46–61). Provider diversity is live on next server restart.

5. **`sources.jurisdiction` always empty** ✅ FIXED — commit 49881f5 resolves court via the linked docket resource (`resolveCourtFromDocket` in courtlistener.ts); 2026-07-04 evening closed the remaining hole: `assessJurisdictionFit()` returns `null` for an empty jurisdiction instead of misreporting `mandatory`.

---

## Wingman (2026-07-03 handoff executed)

Two builds, both verified running against live Gemini (`gemini-3.1-flash-live-preview`):

- **`wingman-in-your-ear/wingman-demo/`** (own git repo, Node/TS + React PWA, port 3000) — the iPhone path. Was missing all courtroom-advisor behavior; now has: `harness/` dir (court_pro_se, broadcast_market, deposition), server-side harness loader injecting `systemInstruction` + per-agent voice (Charon/Fenrir) at `ai.live.connect`, agent selected client-side and passed as `?agent=` WS query param, advisor audio playback (24kHz PCM) + WINGMAN transcript logging in App.tsx (neither existed — the client never played model audio). Fixed broken text relay (`gSession.send` → `sendRealtimeInput`; `sendClientContent` is restricted to initial-history seeding on gemini-3.1 live). package.json renamed react-example → wingman-pwa, unused vision deps stripped (mediapipe, tfjs, coco-ssd, ffmpeg-static, better-sqlite3, tone — grep-confirmed unused). `.env` created from backend key (gitignored). **Behaviorally verified end-to-end**: silent through 3 neutral courtroom turns, spoke once on a planted contradiction ("Contradicts his testimony under oath"). Harness needed two iterations: explicit high-bar-for-speaking rule (was trigger-happy) and explicit "no placeholder output" rule (model spoke the literal word "\<silent\>").
- **`wingman-in-your-ear/wingman_live.py`** (Python desktop) — the handoff's P3 premise was wrong: the file on disk has no `send_client_content` call and no harness loader (hardcoded `system_instruction`). Added the same 3-agent harness loader (`harness/` copy at `wingman-in-your-ear/harness/`), CLI agent selection (`python wingman_live.py deposition`), per-agent voice. Harness goes through `system_instruction` at connect — deliberately NOT `send_client_content`, which sidesteps the history_config API change entirely. The June-15 working Python env no longer existed (system Python is now 3.14.5); created `wingman-in-your-ear/venv/` with google-genai + pyaudio. **Live-verified headless**: deposition agent connected and answered a mischaracterized-testimony trap with "Mischaracterizes testimony. Object."

Later same day: both builds gained `context_window_compression` (sliding window) so sessions survive past the Live API's audio time limit — accepted by the model, behavior re-verified. `proactivity`/`proactive_audio` was tried and is **rejected at setup by gemini-3.1-flash-live-preview** (native-audio-dialog-family feature only); silence remains prompt-enforced. Mobile fixes: safe-area insets + viewport-fit=cover, dvh, scrollable start-overlay (Start button was clipped on phone), proper title/PWA meta tags.

## Verifier / Judicial-intel (2026-07-03)

- `verifier/venv` — OK (requests, rapidfuzz); all citation-benchmark scripts compile. `verifier/.env` created from backend keys (CL_TOKEN etc., gitignored); CourtListener API auth live-tested 200.
- `verifier/venv-judicial` — was completely broken (built on Python 3.13, since uninstalled; all symlinks dangling). Rebuilt on 3.14 with requests, rapidfuzz, opencv, numpy, av 18, ctranslate2 4.8.1, faster-whisper (installed `--no-deps` because it pins an older PyAV with no 3.14 wheel). **onnxruntime has no macOS-x86_64/py3.14 wheel** → `transcribe.py` patched to skip the VAD filter gracefully when onnxruntime is absent; Whisper-API path unaffected. yt-dlp + ffmpeg present on PATH. All pipeline scripts compile and `--help` runs.

---

## Schema drift + app fixes (2026-07-03, later session)

The live Supabase DB (`fzexglkmpoyxtkdiwelm`) had drifted badly from what the backend code expects — the code was never wrong, the DB was just missing objects. Fixed by migration (all additive, never dropped):
- `user_profiles` — added `mfa_on_login`, `title_model`, `legal_research_us` (every auth'd request selected these → constant errors).
- `public.get_projects_overview(p_user_id, p_user_email)` RPC — **created from scratch** (never existed live); every Projects page load 500'd. Returns owned+shared projects with document/chat/review counts.
- `document_versions` — added `filename`, `file_type`, `size_bytes`, `page_count` (upload version insert failed).
- `documents` insert in `routes/documents.ts` — was omitting `filename` (NOT NULL) → "Failed to create document record". Code fix.
- `user_api_keys` table — **created from scratch**; its PGRST205 rejection was the unhandled-rejection that crashed the whole backend (Node kills the process on unhandled rejection). Also added a `process.on("unhandledRejection")` guard in `index.ts` so one stray rejection can't take the server down again.
- 5 MCP connector tables created: `user_mcp_connectors`, `user_mcp_connector_tools`, `user_mcp_oauth_tokens`, `user_mcp_oauth_states`, `user_mcp_tool_audit_logs`.
- CourtListener token: code reads it under **two** env names (`COURTLISTENER_TOKEN` in index.ts, `COURTLISTENER_API_TOKEN` in userApiKeys.ts). Only the first was set → case-opinions failed. Added the alias to `backend/.env`.

**A background task (`task_8407d280`) was spawned to systematically audit ALL `.from()/.rpc()/column` references in backend/src against the live DB** — the fixes above were found error-by-error and a full sweep is warranted.

App-level fixes same session:
- **Case Law in-app opinion reader** (`case-law/page.tsx`) — was link-out-only; now clicking a result or "Read opinion" opens a slide-over that pulls full opinion text via `/case-law/case-opinions` (four-gate verified) and renders it in-app, CourtListener cited as *source* in the footer, not the destination. Harvey-style. Live-verified with Twombly.
- **Council page** — was hardcoded dark (`#161615`/white bg) and looked broken in light theme; rewritten to use the theme-aware `bg-white`/`bg-gray-50`/`text-gray-*` classes so it respects Light/Parchment/Dark.
- **Sign Out** — added to the sidebar avatar dropdown (`AppSidebar.tsx`); there was no way to log out.
- **Killed the "AI can make mistakes" disclaimer** (InitialView + ChatView) — replaced with the approved "Every citation verified · Primary sources only · Not legal advice — legal knowledge." per decisions.md 2026-05-16. It had silently survived in the assistant views.

Note: password for `aray.aaron@gmail.com` was reset directly in `auth.users` during this session (user forgot it) to a temporary value — user should change it.

## Batch 3 fixes (2026-07-03, third session)

- **Ghostly modals fixed** — shared `components/shared/Modal.tsx` used a 30%-opaque white backdrop + 94% panel, so every modal (New Project, New Tabular Review, workflow "Use") rendered see-through with the page bleeding through ("faint typing in the bg"). Changed to `bg-gray-900/50` scrim + solid `bg-white` panel. Now theme-aware and solid. NOTE: "Create" buttons are correctly disabled until a name is entered — that was mistaken for "broken" only because the transparent modal hid the disabled state.
- **`tabular_reviews.document_ids`** — added (jsonb). Workflow "Use" → create review was 500ing on the missing column (same drift pattern).
- **Case Law: all 50 states + DC** — jurisdiction dropdown had only SCOTUS + federal circuits. Added every state's highest court, using real CourtListener court IDs pulled live from `/courts?jurisdiction=S`.
- **Verification vs source chips** — now visually distinct: green shield "Existence verified" vs blue book "CourtListener" (source).
- **Council WP-plugin dead link** — `#word-plugin` anchor → mailto early-access request.
- **Assistant killed disclaimer** — done (see Batch 2).

### Known / not-yet-fixed (flagged for the user)
- **Assistant can't read some attached PDFs** ("not correctly indexed"). Root-cause hypothesis: uploads were fully broken (filename NOT NULL) until Batch 2 this same day, so files like "RULE 60.pdf" were uploaded during the broken window and never got a proper version row / storage path. `buildDocContext` only loads docs with `status='ready'` + a storage_path. **Re-upload after the fix should resolve it** — needs a fresh-upload test to confirm before deciding it's a live extraction bug.
- **Analytics is a stub vs. the intended product**: the vision is a judicial/opposing-counsel/witness connection graph + an allegation↔defense↔authority cluster, populated by a pre-trained extraction agent that runs when a doc is uploaded to Tabular Review or a Project, strips the case facts (authorities cited, defense theory, how rare/common the fact pattern is), and pushes structured output into Workflows + Analytics. This is a multi-session feature build, not a bug — not started.
- **Perf**: Council = 11 model calls/session, crew is multi-agent; both feel slow. No parallelization/caching pass done yet. Scoped, not started.

## Analytics / Case Intelligence — BUILT (2026-07-03, fourth session)

Replaced the hardcoded SCOTUS mock with a real extraction pipeline, live-verified end to end.
- **`case_intelligence` table** (migration) — one row per document: caption, entities[{name,role}], allegations[{claim,authorities[]}], defenses[{defense,authorities[]}], authorities[{citation,proposition,treatment}], rarity{score,label,rationale}, defense_summary.
- **`backend/src/lib/caseIntelligence.ts`** — the extraction agent. `loadDocumentPlainText` (downloads current version via `loadCurrentVersionBytes`, extracts pdf/docx), `extractCaseIntelligence` (LLM structured-JSON call, tabular_model), `runCaseExtraction` (orchestrate + upsert on document_id).
- **Routes** (index.ts, requireAuth): `GET /api/analytics` (extractions), `GET /api/analytics/documents` (ready docs + analyzed flag), `POST /api/analytics/extract` ({documentId}).
- **Auto-trigger**: tabular-review create fires a fire-and-forget `runCaseExtraction` per attached doc (skips already-analyzed) — "uploaded to tab review" is the trigger per spec.
- **Analytics UI** (`analytics/page.tsx`) — document picker + Analyze button, case tabs, d3 connection graph (case center; entities colored by role: judge/opposing_counsel/witness/expert/party/court/authority), rarity meter, defense summary, and the Allegations↔Authorities↔Defenses cluster (hover an authority to highlight what it supports). Empty state when nothing analyzed.
- **Verified**: uploaded a synthetic CA employment complaint → extraction pulled judge (Patricia Hollows), witness (Robert Chen), expert (Dr. Park), 2 allegations w/ Tameny + Yanowitz, 2 defenses w/ McDonnell Douglas, 5 authorities, rarity "Routine". Rendered correctly in the browser.

### CRITICAL drift fix found here: `document_versions.deleted_at`
`loadActiveVersion` filters `.is("deleted_at", null)`, but the column was missing → the query errored → EVERY version load returned null. This silently broke **`read_document` in the assistant** (the real cause of "RULE 60.pdf not correctly indexed") AND case extraction. Column added. The assistant should now read attached PDFs — worth a re-test.

### Still open
- ~~Auto-trigger only on tabular-review create; project-tab upload doesn't yet auto-extract~~ — DONE 2026-07-04: project uploads now auto-extract too (documents.ts `handleDocumentUpload`).

## Open items after 2026-07-04 evening session

- **Courts snapshot crawl**: `backend/scripts/fetch-courts.mjs` may still be running (~60 min) or need a re-run if it died. Until `backend/data/courtlistener-courts.json` exists, the picker shows the federal fallback + "full court list unavailable" note. After it lands, restart the backend and confirm the picker shows all tabs populated.
- **Old extractions unranked**: case_intelligence rows extracted before today have no `novelty`/`cite_count` — re-analyze from the Analytics page to rank them (cite counts need the 50/hr citation-lookup quota to be available).
- **`get_*_overview` RPC drift pattern**: three RPCs were missing live (`get_projects_overview`, `get_tabular_reviews_overview`, `get_chats_overview`). The full audit task (task_8407d280) should still sweep for others.

## Speed pass (2026-07-04)

**Root cause of "too slow":** every authenticated request independently (1) constructed a fresh Supabase admin client, (2) made a network round-trip to Supabase to validate the JWT (`admin.auth.getUser`), and (3) ran a DB query for the MFA preference. Measured ~170-330ms of pure auth overhead per request — and the frontend fires a burst of 5-8 parallel authed requests with the SAME token on every page load, each paying it.

**Fix (`middleware/auth.ts`):** module-level singleton admin client + short-TTL (60s) in-memory caches keyed by token (user resolution) and by user (MFA preference). Only the first request in a burst pays the round-trip; the rest are cache hits.

**Measured:** cold request 206ms → warm/cached ~0ms auth (warm /projects ~60-110ms, now dominated by the actual query, not auth). A realistic 8-endpoint parallel page-load burst completes in ~0.5s wall-clock. Security verified intact: bad/missing tokens still 401 (only validated tokens are cached; TTL 60s bounds revocation lag).

**Council/Crew latency** is architectural, not a bug: advisors already run in parallel (`Promise.all`), reviewers in parallel, then chairman — 3 unavoidable LLM waves. Left as-is.

## Design System (confirmed, do not change without reason)

*Superseded 2026-06-23 — "Redesign frontend with new ink/paper/blue design system" (commit `3156631`). The gold/navy table below is historical; the ink/paper/blue tokens are what's actually in `frontend/src/app/globals.css` as of 2026-07-03.*

| Token | Value |
|-------|-------|
| Ink (primary text/bg-dark) | `#0A0A0A` (`--color-ink`), with `-2`/`-3`/`-mid`/`-soft` steps for hierarchy |
| Paper (app background) | `#F7F6F2` (`--color-paper`), `#EFEEEA` secondary |
| Stone / Mist | `#C4C3BD` / `#C8D8DC` — muted neutrals |
| Blue accent (research/links) | `#2B5CE6` (`--color-research`, `--color-blue`) |
| Semantic accents | Draft `#C7341A`, Workflow `#E8B121`, Data room `#1F8A5B`, Knowledge `#7A3FD6` |
| Sans | DM Sans (`--font-sans` / `--font-dm-sans`) |
| Serif/display | Playfair Display (`--font-serif` / `--font-playfair`) |
| Mono | JetBrains Mono (`--font-mono` / `--font-jetbrains-mono`) |

Legacy `--color-kf-navy` (`#15192E`), `--color-kf-gold` (`#E09B30`), `--color-kf-black`, `--color-kf-cream` variables still exist in `globals.css` for anything not yet migrated off the old system — don't treat their presence as evidence the old system is still primary.

App interior (Council, Case Law, etc.) stays clean and crisp — matches existing Mike styling with Kingsfield branding layered on.

---

## Pending / Next Work

- [x] Wire real citation verification into production chat — done 2026-07-03, `verifyDraftForSse()` called from `chat.ts` and `projectChat.ts`, emits `verification` SSE event. (Previous "Wire chat route to Crew" entry was based on a false claim — the frontend was never repointed at `/api/crew/chat`, and correctly so, since that route has no auth/persistence.)
- [x] Migration 110 — confirmed already applied live (2026-07-03)
- [x] `cl_opinion_id` column — confirmed already present live (2026-07-03)
- [x] Gemini key — set in backend/.env, instantiated in backend/src/index.ts lines 46–61
- [x] Fix `sources.jurisdiction` always empty — done (commit 49881f5 + empty-string guard in pipeline.ts, 2026-07-04)
- [ ] Build judge scoring prompt + `quality_scores` schema for A/B testing
- [ ] Add `cal.diy` scheduling infrastructure for deadline/docket tracking
- [ ] Build per-school law school debt dataset (research product)
- [ ] Consider Legal Data Hunter MCP (`https://legaldatahunter.com/mcp`) vs CourtListener
