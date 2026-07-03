# Kingsfield

> **Smart. Not Stupid. Power to the People.**
>
> A fork of [Mike](https://github.com/willchen96/mike) hardened against hallucinations, grounded in primary case law, and structured around a Council of Experts that pressure-tests every output before it leaves the system.

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)

---

## What this is

Mike is the open-source legal AI platform built by Will Chen — a self-hostable alternative to Harvey and Legora with a chat assistant, projects/vault, tabular review, and pre-built workflows. It's the right foundation: open, AGPL, vibe-codeable, owned by the operator instead of a vendor.

What Mike is missing — and what every legal AI tool struggles with — is the thing that gets pro se litigants dismissed and law firms sanctioned: **hallucinated citations**.

Kingsfield is a fork that adds three layers on top of Mike:

1. **Primary-source legal research** — wired into [CourtListener](https://www.courtlistener.com/) (Free Law Project, 501(c)(3) nonprofit) and the [Caselaw Access Project](https://case.law/), the same kind of case-law grounding [OpenJuris](https://openjuris.org/) provides — but open, free, and self-hosted.
2. **A four-gate citation verification pipeline** — every cite the model wants to use is checked for *existence*, *quote accuracy*, *currency*, and *jurisdiction fit* before it can appear in any output.
3. **The Council of Experts** — a structured agent system (Judge, Opposing Counsel, Skeptic, Strategist, Procedural Clerk, Evidence Master, Witness Coach, Translator, Historian) that adversarially reviews every significant output. The Skeptic has hard veto power over unverified citations.

## Who this is for

- **Pro se litigants** who can't afford Harvey or Westlaw and need help that won't get them dismissed.
- **Small and solo firms** priced out of the BigLaw stack.
- **Paralegals, advisors, and operators** who do the actual research and don't have a six-figure software budget.
- **In-house teams** who want full control of their stack and won't put privileged docs on someone else's GPU.

## What this is *not*

- Not legal advice.
- Not a substitute for a licensed attorney where one is needed.
- Not connected to a court e-filing system. The human is always in the loop.
- Not a paid Shepard's / KeyCite replacement for high-stakes filings. We do best-effort currency checks against open sources; for bet-the-company briefs, supplement with paid tools at the finalization stage.

---

## Architecture

```
┌────────────────────────────────────────────────────────────┐
│                       Frontend (Next.js)                   │
│   Vault UI · Chat · Tabular Review · Council Sessions      │
└────────────────┬───────────────────────────────────────────┘
                 │
┌────────────────▼───────────────────────────────────────────┐
│                    Backend (Express, TS)                   │
│   Auth · Document Pipeline · Workflows · Council Engine    │
└──┬──────────────────────┬──────────────────────────────┬───┘
   │                      │                              │
   │                      │                              │
┌──▼─────────┐    ┌───────▼──────────┐         ┌────────▼─────────┐
│  Supabase  │    │  Object Storage  │         │  Research Layer  │
│  (Auth/DB) │    │  (S3 / R2)       │         │  CourtListener   │
└────────────┘    └──────────────────┘         │  CAP, eCFR, etc. │
                                               │  + Cache + Hash  │
                                               └────────┬─────────┘
                                                        │
                                          ┌─────────────▼──────────────┐
                                          │   Verification Pipeline    │
                                          │   (Four Gates · Skeptic)   │
                                          └─────────────┬──────────────┘
                                                        │
                                          ┌─────────────▼──────────────┐
                                          │    Council of Experts      │
                                          │  Judge · OC · Strategist · │
                                          │  Procedural · Evidence ·   │
                                          │  Witness · Translator ·    │
                                          │  Historian                 │
                                          └────────────────────────────┘
```

## What's added vs. upstream Mike

| Component | Upstream Mike | Kingsfield additions |
|---|---|---|
| Frontend | Next.js chat + Vault | + Council Session UI, + Verified Citation chips, + Source Inspector |
| Backend | Express + Supabase + doc processing | + Research router, + Verification pipeline, + Council orchestrator |
| Database | Supabase Postgres | + tables: `sources`, `citations`, `council_sessions`, `verifications` |
| Models | User-supplied Claude / Gemini keys | Same — plus role-specific system prompts per Council role |
| Research | None | CourtListener + CAP + eCFR adapters |
| Output guarantees | Best-effort | Four-gate verification + Skeptic veto |

## Quick start

See [`docs/SETUP.md`](./docs/SETUP.md). Same shape as Mike's setup (Supabase, S3-compatible storage, model API keys), plus:

- A free [CourtListener API token](https://www.courtlistener.com/help/api/rest/) (5,000 queries/hour).
- Optional: Caselaw Access Project access for older case text.

## License

**AGPL-3.0-only**, inherited from Mike. If you run a modified version as a network service, you must offer your modified source to users. This is a feature, not a bug — it's how the open-source legal AI ecosystem stays open.

## Voice

This project follows the Kingsfield brand voice. See [`docs/branding/VOICE.md`](./docs/branding/VOICE.md). Direct, plain English, no Latin without translation, no softening hard truths, no hiding behind credentials.

> Real help. Zero bullshit.
