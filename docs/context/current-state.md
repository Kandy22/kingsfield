# Kingsfield Lawfare — Current State
*Last updated: 2026-05-16*

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

1. **Chat route** ✅ WIRED — `mikeApi.ts` `streamChat` (line 444) and `streamProjectChat` (line 486) both post to `${API_BASE}/api/crew/chat`. Done.

2. **Migration 110** — `backend/migrations/110_council_and_crew_schema.sql` not yet applied. Adds `llm_council_sessions` and `crew_traces` tables. **Run in Supabase SQL editor** (see SQL in CLAUDE.md wiring task 2).

3. **`sources.cl_opinion_id` column missing** — Every Researcher run fails on insert without it. **Run in Supabase SQL editor**:
   ```sql
   alter table sources add column if not exists cl_opinion_id bigint;
   ```

4. **Gemini API key** ✅ SET — `GEMINI_API_KEY` is in `backend/.env` and `backend/src/index.ts` instantiates the `GeminiClient` from it (lines 46–61). Provider diversity is live on next server restart.

---

## Design System (confirmed, do not change without reason)

| Token | Value |
|-------|-------|
| Background (app) | `#1A1E2E` navy |
| Gold accent | `#C8A96E` |
| Cream text | `#EDE8D8` |
| Display font | Playfair Display 900 (`--font-playfair`) |
| Mono/labels | IBM Plex Mono (`--font-ibm-plex-mono`) |
| Editorial | EB Garamond (`--font-eb-garamond`) |
| Body | Inter (`--font-inter`) |

App interior (Council, Case Law, etc.) stays clean and crisp — matches existing Mike styling with Kingsfield branding layered on.

---

## Pending / Next Work

- [x] Wire chat route to Crew — done, streamChat + streamProjectChat both post to /api/crew/chat
- [ ] Run migration 110 in Supabase SQL editor
- [ ] Add `cl_opinion_id` column in Supabase SQL editor
- [x] Gemini key — set in backend/.env, instantiated in backend/src/index.ts lines 46–61
- [ ] Build judge scoring prompt + `quality_scores` schema for A/B testing
- [ ] Add `cal.diy` scheduling infrastructure for deadline/docket tracking
- [ ] Build per-school law school debt dataset (research product)
- [ ] Consider Legal Data Hunter MCP (`https://legaldatahunter.com/mcp`) vs CourtListener
