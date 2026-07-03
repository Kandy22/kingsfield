# Kingsfield Lawfare — Current State
*Last updated: 2026-07-03*

This file is the handoff brief. Any new session — Claude Code, Cowork, or Claude.ai — should read this first alongside CLAUDE.md.

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

5. **`sources.jurisdiction` always empty** — NEW (2026-07-03): `getCluster()` in `backend/src/research/courtlistener.ts` reads `court`/`court_id` off the CourtListener v4 cluster response, but neither field exists there anymore — court now lives on the linked `docket` resource. Every `sources` row gets `jurisdiction: ''`, which breaks Gate 4 (jurisdiction fit) in `verification/pipeline.ts`'s `assessJurisdictionFit()` — an empty string is trivially "included" in any forum string, so every citation is misreported as `mandatory`. Filed as a follow-up task, not yet fixed.

---

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
- [ ] Fix `sources.jurisdiction` always empty (Gate 4 accuracy bug — see blocker #5 above)
- [ ] Build judge scoring prompt + `quality_scores` schema for A/B testing
- [ ] Add `cal.diy` scheduling infrastructure for deadline/docket tracking
- [ ] Build per-school law school debt dataset (research product)
- [ ] Consider Legal Data Hunter MCP (`https://legaldatahunter.com/mcp`) vs CourtListener
