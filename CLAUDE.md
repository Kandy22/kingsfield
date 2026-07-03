# CLAUDE.md — Kingsfield Lawfare

---

## What This Is

Kingsfield Lawfare is a legal AI platform built on the principle that the law is public, written, and belongs to everyone — not to the institutions that have spent two centuries charging admission to it.

The legal system made a promise: equal justice, written rules, blind scales. The Bar, BigLaw, Westlaw, and LexisNexis built a toll road on top of that promise. Kingsfield is the bypass.

This is not a lawyer replacement. It is a capability equalizer. The same research, verification, and strategic analysis that BigLaw charges $800/hour for — delivered without a retainer, without gatekeeping, without the theater.

**Core position:** Access to legal knowledge is a First Amendment right. The rules are public. The cases are public. Primary sources belong to the people they govern. Any system that monetizes access to public law while hiding behind "unauthorized practice" rules is a protection racket, not a profession.

**Product promise:** Zero emotional manipulation. Zero billable-hour incentives. Verified citations or nothing. The Skeptic has hard veto power for a reason — we would rather return no answer than a wrong one dressed up as right.

---

## Architecture

**The Crew** — Four specialist agents run behind every query: Researcher, Analyst, Strategist, Team Lead. The user sees one clean answer. The Crew did the work.

**Four-Gate Citation Verification** — Every citation is checked for: (1) Existence, (2) Quote Accuracy, (3) Currency, (4) Jurisdiction Fit. The Skeptic can veto any output that fails. This is non-negotiable — it is the entire point of the product.

**The LLM Council** — Five advisors (Contrarian, First Principles, Expansionist, Outsider, Executor) across two AI providers (Claude + Gemini) with a Chairman for synthesis. Provider diversity is intentional: no single model's biases dominate. Eleven model calls per session. Questions pressure-tested from every angle.

**Skills layer** — `backend/skills/` contains production-ready legal workflow skills (privilege review, matter journaling, TX title analysis, employment law research, formation counsel, etc.) that the Crew can invoke for specialized tasks.

---

## Values Embedded in Every Feature

- **No apology for the product's existence.** The disclaimer is not "AI can make mistakes." The position is: we verify harder than most lawyers do, and we show our work.
- **Primary sources only.** CourtListener for case law. USC/CFR for federal law. Official state sources. No summarized secondhand garbage.
- **The Crew works for the user, not the billable hour.** Speed and accuracy are the same incentive here. There is no reason to slow down or hedge.
- **The Council is adversarial by design.** The Contrarian's job is to find the holes. If a strategy can't survive the Contrarian, it won't survive opposing counsel.
- **Anti-capture.** No partnerships with Westlaw, LexisNexis, or any incumbent that profits from restricted access. If a data source charges for public law, we find the public source.

---

## Session Continuity

Before starting any work, read these two files in addition to this one:
- `docs/context/current-state.md` — what's built, what's broken, what's next
- `docs/context/decisions.md` — all directional decisions made, with dates

Update `current-state.md` when wiring tasks are completed. Add to `decisions.md` when a new direction is confirmed. Never delete from decisions.md — append only.

---

## Open Wiring Tasks

Setup and commands are in `README.md` and `docs/SETUP.md`.

### 1. Frontend chat route

`frontend/src/app/lib/mikeApi.ts` still posts chat messages to Mike's original route. Wire it to the Crew instead:

```
- /chat               →  /api/crew/chat
- /projects/:id/chat  →  /api/projects/:id/crew/chat
```

The crew route is defined in `backend/src/routes/index.ts`. The frontend should pass `projectId` and `documentContext` in the request body so the Coordinator can decide which roles to spawn.

### 2. Migration 110 not applied

`backend/migrations/110_council_and_crew_schema.sql` has not been run. It adds `llm_council_sessions` and `crew_traces`.

Run in the Supabase SQL editor after `100_kingsfield_schema.sql`:

```sql
\i backend/migrations/110_council_and_crew_schema.sql
```

### 3. Missing column: `sources.cl_opinion_id`

`100_kingsfield_schema.sql` defines `cl_opinion_id bigint` on the `sources` table but the column is missing from the live database:

```sql
alter table sources add column if not exists cl_opinion_id bigint;
```

The Researcher (`backend/src/crew/researcher.ts`) writes to this column when materializing a CourtListener authority. Without it, every Researcher run fails on insert.

### 4. Gemini API key for LLM Council

The Council routes `first_principles` → Gemini Pro and `outsider` → Gemini Flash. Without the key both fall back to Claude Opus and provider diversity is lost.

Add to `backend/.env`:

```
GEMINI_API_KEY=<your key>
```

Confirm instantiation in `backend/src/llm-council/orchestrator.ts`. The `providers.ts` fallback logs a warning when Gemini is absent.

**Do not commit the key.** `backend/.env` is in `.gitignore`.

---

## Copy and Tone Standards

Every piece of copy in this product should reflect these standards:

- **Direct, not apologetic.** "Know the rules. Use them." Not "please note that AI may make errors."
- **No theater.** The product works or it doesn't. Verification gates exist precisely so we can make that claim.
- **The user is not a layperson to be managed.** They are a person with a legitimate problem and a right to information. Treat them accordingly.
- **Citations are not optional.** Every claim that can be sourced must be sourced. Every source must survive the four gates.
- **Power to the people is not a slogan here.** It is the architecture. The Crew, the Council, the skills layer — all of it exists to put BigLaw-grade analysis in the hands of anyone who needs it.

---

## Kingsfield is a fork of Mike (AGPL-3.0)

We respect the upstream project. We do not bend the knee to the Bar, to Westlaw's pricing model, or to the idea that legal knowledge requires a gatekeeper. AGPL-3.0 means improvements stay open. That is the point.
