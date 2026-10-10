# Business plan corrections: replacement wording (DRAFT, 2026-10-10)

Status: draft for Aaron to approve. Not legal advice. A lawyer should review sections 1, 5 and 6 before an investor or regulator reads them. Source of each finding: docs/BP-VS-REALITY-2026-10-09.md. Plan sections are from the v2 plan (2026-05-20) and v3 additions (2026-05-21).

I only have the plan's claims as summarized in the gap list, not the exact original sentences. Search the plan for the quoted phrases to find each place.

## 1. Privacy and subpoena claim (4.3, 5.1, 7.3)

Problem: the plan says client data never touches third-party servers and is not subject to subpoena via LLM providers. As built, prompts go to Anthropic, Google Gemini, and (Council only) DeepSeek and Kimi through OpenRouter. Data is stored in Supabase and Cloudflare R2. Email goes through Resend.

Replace with: "Kingsfield can be deployed in a customer's own environment. In the hosted version, prompts are processed by third-party AI providers under their enterprise terms, and data is stored with our cloud vendors. A local-model mode, where client data stays on the customer's own machines, is on the roadmap."

Delete: "never touches third-party SaaS servers" and "not subject to subpoena via LLM providers". The subpoena sentence is a legal conclusion we cannot support.

## 2. GAN adversarial simulation (1, 3.1, 4.1, 5)

Problem: no GAN or trained model exists. What exists is prompted role-play (crew/opposition-mapper.ts, llm-council/prompts.ts).

Replace with: "Kingsfield stress-tests every argument with prompted adversarial roles: opposing counsel, judge and skeptic. A model trained on real case outcomes is a research goal."

Delete: "only platform with a GAN" and "Harvey has no GAN".

## 3. Nine-reviewer GREEN / AMBER / RED council (3.1, 4.2, 7.3)

Problem: only the Skeptic and the Judge exist in backend/src/council/, and no route calls them. GREEN/AMBER/RED are not produced.

Replace with: "Every citation in every answer is checked by a deterministic gate. For Florida, the check runs against a local database of 391,465 citations. A citation that cannot be confirmed blocks the whole answer. The nine-reviewer panel with GREEN/AMBER/RED ratings is in development."

Note: "391,465" is the database row count. It is not a measure of accuracy.

## 4. Sub-5% residual error, 20-minute argument, 75% cost cut (1, 2.3, 5.1)

Problem: nothing measures these. The only measured numbers are for other models on our benchmark: Gemini 2.5 Flash 27.7% error, GPT-4o-mini 30.0%, always-say-yes baseline 32.4%.

Replace with: "Our target is to reduce unverified citations to a level an attorney can review quickly. We are measuring this on a labeled benchmark and will publish the result."

Delete the percentages, "20 minutes" and "up to 75%" until measured. The review tool and merge script exist (Verifier/sandbox.html); human labels are still needed.

## 5. Florida UPL gating (7.3)

Problem: the plan lists Florida as a strict state to be gated, yet the citation database is Florida-first. No gating code exists.

Replace with: "State-by-state availability will follow a unauthorized-practice-of-law review by counsel. Launch states have not yet been selected."

Open decision for Aaron and counsel: whether Florida users are served at all, and how.

## 6. AZ ABS status (7.1, 9)

Problem: cannot be verified from code. Do not write "ABS-licensed" in the present tense unless the license exists.

Replace with whichever is true: "Licensed as an Arizona Alternative Business Structure" or "Application for Arizona ABS licensure is planned/pending."

## 7. Also say plainly

- Attorney review before export and audit trail: roadmap, not built.
- Pricing and billing: not built.
- Entertainment/IP vertical and Concierge: roadmap.
- Self-help (pro se) line: partly built.
