# The business plan vs. what actually exists (2026-10-09)

**The plan:** "Kingsfield Lawfare | Legal Intelligence Platform | **Smart. Not Stupid.** | Business Plan, Investor Edition | May 2026" (v2 dated 2026-05-20, v3 additions dated 2026-05-21). Files: `to sort/Kingsfield Bus Plan/Kingsfield_Business_Plan_2026_v2.docx` and `business-plan/Kingsfield_BP_v3_Additions.docx`. It is the working plan; it is about 4.5 months old and describes the intended product. Everything below was checked against the code on this date.

The ask in the plan: $4.5M seed (SAFE, 20% discount, $18M cap); Year 1 ARR $612K, Year 3 $13.8M; 72% gross margin target.

## 1. Promise by promise

| What the plan says | Where | Status today (evidence) |
|---|---|---|
| Every citation verified through a **4-gate pipeline**; **hard veto** when a citation fails Gate 1 ("the Skeptic halts output") | 3.1, 4.2, 5, v3 sec. 5 | **Built, for Gate 1, and now enforced on every route that returns model text** (chat, project chat, tabular, crew, council, titles, document writes). Any veto withholds the whole answer. Florida Gate 1 runs on the local database (391,465 citations). Gates 2 to 4 exist in `verification/pipeline.ts` but Gate 2 needs opinion text the database does not hold. Final adversary signoff of this work was still running when this was written. |
| **Crew**: Researcher, Contract Analyst, Strategist, Team Lead | 4.2 Layer 1 | **Built** (`backend/src/crew/`, `POST /api/crew/chat`, now behind login and Gate 1). |
| **LLM Council**: 5 advisors + Chairman, Claude + Gemini diversity, 11 model calls, anonymized blind review | 4.2 Layer 3, v3 sec. 3B | **Built and wired** (`backend/src/llm-council/`, `POST /api/council`, sessions in `llm_council_sessions`). Now Gate-1-checked and behind login. |
| **Verification Council**: 9 adversarial reviewers (Skeptic with hard veto + Judge, Opposing Counsel, Procedural Clerk, Evidence Master, Witness Coach, Translator, Historian, Strategist); every output **GREEN / AMBER / RED** | 3.1, 4.2 Layer 2, 7.3 | **Partly built, not wired.** `backend/src/council/` (349 lines) has the orchestrator, the Skeptic and the Judge only; the other seven roles are placeholders ("other roles wired in similarly"). **No route calls it.** Its statuses are `cleared / blocked-by-skeptic / completed-with-conditional / completed-clean`, not GREEN/AMBER/RED. The only live equivalent is the per-citation verdict `verified / conditional / vetoed / pending`. |
| **GAN adversarial simulation** of opposing counsel, judge, jury, trained on real case outcomes | 1, 3.1, 4.1, 5 | **Not built.** No GAN or trained model exists. Nearest things: `crew/opposition-mapper.ts` and prompts in `llm-council/prompts.ts` (prompted LLMs, not a trained GAN). The plan's biggest differentiator ("Harvey has no GAN") is not in the product. |
| "Optimized Greedy Engine": routes queries, manages checkpoints | 4.1 | **Not wired.** The local JEV CPU router (`router/`) was built and signed off in stubs but nothing in `backend/src` calls it. |
| **Self-hosted**; "client data never touches third-party SaaS servers; not subject to subpoena via LLM providers" | 4.3, 5.1, 7.3 | **Not true as built.** User text goes to Anthropic, Google Gemini, DeepSeek and Kimi (via OpenRouter, Council only); data is stored in Supabase and Cloudflare R2; email through Resend. See section 2, item 1. |
| **State-specific UPL gating** for strict jurisdictions (FL, TX, NC) | 7.3 | **Not built.** No UPL gating code anywhere (0 files). Note the plan itself lists Florida as strict, while the citation database is Florida-first. |
| "**Attorney review required before filing export**; full **audit trail**" | 7.3 | **Not built.** One audit-related file exists (MCP servers), no review-before-export flow. |
| Disclaimer "We are not lawyers. You represent yourself." on every surface | 7.4 | **Partly.** Present in `frontend/src/app/page.tsx`, `InitialView.tsx`, `ChatView.tsx`. |
| **Pro se / Self-Help (D2C)** product line | 3.2 Line 2 | **Partly.** `proSe.ts` route and 21 files with pro-se handling; no questionnaires/document-kit product or niche modules confirmed. |
| **Document analysis / Tabular Review** | 3.1 | **Built** (`tabular.ts`), now Gate-1-checked. |
| **Case Intelligence Graph** | v3 | **Built** (`caseIntelligence.ts`, analytics page). Its extraction output is now Gate-1-checked before saving. |
| **Entertainment/IP vertical** (SAG/WGA/DGA library, rights-chain, digital replica clauses) | 6.1, 10 Phase 5 | **Not built.** `backend/skills/` has 10 general skills; no SAG/WGA/DGA library. (An IP infringement-triage agent exists in `crew/infringement-triage.ts`.) |
| **Pricing and billing** ($99-$399/seat; $29/$79/$149 D2C) | 6.1 | **Not built.** No Stripe or subscription code (0 files). |
| **Concierge** (expert teams, coordination fee) | 3.2 Line 3 | **Not built** (it is a services line). |
| **AZ ABS entity**, CCO, attorney supervision (Weiner, Hart) | 7.1, 9 | **Not verifiable from code.** Phase 1 of the plan says "incorporate AZ ABS entity"; confirm its status yourself before any investor sees "ABS-licensed" as a present-tense claim. |
| "Sub-5% residual error"; "complete argument in 20 minutes"; "cuts legal cost up to 75%" | 1, 2.3, 5.1 | **Not measured.** The Hugging Face benchmark card measures other models' error rates (Gemini 2.5 Flash 27.7% and GPT-4o-mini 30.0% error on the gold rows; only Claude Haiku 4.5 clearly beats the 32.4% always-say-yes baseline). No residual-error number exists for Kingsfield, and the human review tool that would produce one (Task 2) has not been rebuilt. |

## 2. Claims in the plan to fix before an investor or regulator reads them

1. **Privacy/subpoena claim (4.3, 5.1, 7.3).** As built, user prompts and documents go to Anthropic, Gemini and others, and are stored in Supabase and R2. Either (a) reword to "self-deployable; client data stays in your infrastructure when run with local models", and build a local-model mode (the router and a local gguf already exist in `router/`), or (b) remove "never touches third-party servers" and "not subject to subpoena via LLM providers". This is the highest-risk sentence in the plan.
2. **"Kingsfield = only platform with a GAN simulation layer"** is not true of the product today. Reword as "adversarial role-play (prompted)" until a trained GAN exists, or build it.
3. **"Every output GREEN/AMBER/RED"** and **"nine adversarial reviewers"** are not live. State it as roadmap, or wire the existing `council/` (2 of 9 roles) and map `verified/conditional/vetoed` to GREEN/AMBER/RED.
4. **"Sub-5% residual error"** has no measurement behind it. Remove, or measure with the review tool.
5. **Florida.** The plan marks Florida as a strict UPL state to be gated, while the citation system is Florida-first. Decide with counsel whether Florida users are served at all (and how) before launch.
6. **ABS status** (7.1): confirm the entity actually exists and is licensed before any present-tense statement.

## 3. What the plan needs next (priority, no time estimates)

1. Close out the safety verification already underway (`main-verify` signoff). Everything else builds on the citation guard.
2. **Fix the false/unsafe plan claims** in section 2 (words only, no code): items 1, 2, 3, 4.
3. **Wire the Verification Council** with GREEN/AMBER/RED: connect `council/orchestrator.ts` to the chat/export path, add the missing seven roles, map statuses. This is the plan's Layer 2.
4. **Attorney-review-before-export and audit trail** (needed for the plan's UPL mitigations).
5. **UPL gating by state** (starting with FL, TX, NC).
6. **Billing** (Stripe) and the pricing tiers.
7. **Local-model mode** so the privacy claim can become true.
8. **GAN/simulation**: decide whether to build a trained model or sell it honestly as prompted adversarial role-play.
9. Entertainment/IP vertical, Concierge, API/white-label, per the plan's Phase 4 and 5.
10. Measure real accuracy with the review tool (Task 2) to replace the "sub-5%" target with a number.

## 4. How the databases fit the plan

- The plan's "4-Gate Verified Citation Pipeline" and "hard veto" are exactly what the Florida citation database makes real for Florida (Gate 1). See `docs/DB-AND-CITATIONS-EXPLAINED.md`.
- The judicial-analytics data (oral-argument transcripts, Jev scoring, offer catalog) supports the plan's "Moneyball for law" positioning and the strategy/simulation story. It is a separate dataset; its claims must follow the lift-with-abstention rule (`docs/context/decisions.md`).
