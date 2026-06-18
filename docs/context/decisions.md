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
