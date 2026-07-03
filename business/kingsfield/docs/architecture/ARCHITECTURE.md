# Architecture

This document describes how Kingsfield extends Mike. Read [Mike's README](https://github.com/willchen96/mike) first if you haven't.

## Mike, in one paragraph

Mike is a Next.js frontend + Express/TypeScript backend, backed by Supabase (auth + Postgres) and S3-compatible object storage (e.g., Cloudflare R2). It uses LibreOffice for DOC/DOCX→PDF conversion and a "Projects" abstraction (matter-style workspaces) to give the chat assistant scoped context across uploaded documents. Models are pluggable — users supply their own Claude or Gemini API keys.

## What we keep

- The Next.js frontend shell, auth, chat UI, document upload, vault/projects abstraction.
- The Express backend, Supabase schema, S3 storage layer, doc-processing pipeline.
- The user-supplied-API-key model (privacy-preserving, no central key custody).
- The AGPL-3.0 license.

## What we add

### 1. Research Layer — `backend/src/research/`

A set of adapters for free, primary, citable legal sources. Every adapter normalizes results into a single internal `Source` shape so downstream code doesn't care where a case came from.

| Adapter | Source | Use |
|---|---|---|
| `courtlistener.ts` | CourtListener REST API v4 | Federal & state cases, dockets, judges, oral arguments. **Citation Lookup endpoint is the anti-hallucination anchor.** |
| `cap.ts` | Caselaw Access Project | Older state and federal cases (pre-2020), backup for cases not in CourtListener. |
| `ecfr.ts` | eCFR.gov | Federal regulations, current + historical versions. |
| `congress.ts` | Congress.gov / GovInfo.gov | Federal statutes, public laws, bill text. |
| `state_codes/*.ts` | Per-state legislature sites | State statutes (one adapter per supported state). |
| `court_rules/*.ts` | Per-court websites | FRCP, FRE, FRAP, local rules, standing orders. |

All adapters write into the **Source Cache** (next).

### 2. Source Cache — Supabase tables + S3

Every fetched authority is persisted with full provenance. New tables:

```sql
-- sources: one row per fetched authority
create table sources (
  id uuid primary key default gen_random_uuid(),
  type text not null check (type in ('case','statute','regulation','rule','constitutional','treatise')),
  citation_bluebook text not null,
  short_name text,
  jurisdiction text not null,
  year int,
  source_url text not null,
  fetched_at timestamptz not null default now(),
  fetched_by uuid references auth.users(id),
  sha256 text not null,
  storage_key text not null, -- pointer into S3
  subsequent_history text,
  unique(citation_bluebook)
);

-- citations: every cite that appears in any model output
create table citations (
  id uuid primary key default gen_random_uuid(),
  source_id uuid references sources(id),
  message_id uuid references messages(id),
  pin_cite text,
  quoted_text text,
  gate_existence boolean default false,
  gate_quote_accuracy boolean default false,
  gate_currency boolean default false,
  gate_jurisdiction_fit boolean default false,
  verifier text, -- 'skeptic' | user_id
  verified_at timestamptz,
  status text not null default 'pending'
    check (status in ('pending','verified','conditional','vetoed'))
);
```

The `sha256` column is the proof-of-non-tampering. Re-verification re-hashes; mismatches alert.

### 3. Verification Pipeline — `backend/src/verification/`

Implements the Four Gates from `docs/HALLUCINATION-PROTOCOL.md`:

```
verify(citation, draftText) →
  Gate 1: existence       — POST to CourtListener Citation Lookup, or hit cache
  Gate 2: quote_accuracy  — fetch full opinion text, regex-match the quoted span
  Gate 3: currency        — pull cited-by graph, scan for negative-treatment markers
  Gate 4: jurisdiction    — compare source.jurisdiction to active matter's forum
  →  status: verified | conditional | vetoed
```

A draft submitted to the assistant is **always** scanned by `verifyDraft(draftText, matterId)` before the response is returned to the UI. Any vetoed citations cause the message to be returned as a **draft with veto flags**, never silently passed.

### 4. Council Engine — `backend/src/council/`

Each role is a system-prompted, separately-invoked LLM call. Roles:

- `judge.ts`
- `opposing_counsel.ts`
- `skeptic.ts` *(hard veto power; cannot be overridden by other roles)*
- `strategist.ts`
- `procedural_clerk.ts`
- `evidence_master.ts`
- `witness_coach.ts`
- `translator.ts`
- `historian.ts`

Each role file exports:

```ts
export interface Role {
  name: string;
  systemPrompt: string;
  requiredQuestions: string[];
  refusalTemplate: string;
  run(args: RoleArgs): Promise<RoleOutput>;
}
```

Sessions are orchestrated by `council/orchestrator.ts` following the protocols defined in `docs/COUNCIL.md`:

- **Standard Session** — full review for filings.
- **Citation-Only Review** — Skeptic only.
- **Strategy Sanity Check** — Strategist + Translator + Judge.

Every session is logged in a new Supabase table `council_sessions`, tied to a matter (project) and an artifact.

### 5. Frontend additions — `frontend/`

- **Source Inspector** — drawer that opens on any citation chip in chat. Shows the cached source, hash, fetch date, gate status, subsequent history.
- **Council Session UI** — convene a session, watch each role's pass run, see the consolidated decision memo.
- **Verified Citation Chips** — green ✅, yellow ⚠️, red ❌ depending on gate status. Red chips block the "send" button on outgoing documents.
- **Hallucination Banner** — if any cite in a draft fails Gate 1, a top banner explicitly says "This draft contains an unverified citation. It cannot be sent until the Skeptic clears it."

## What we don't change (yet)

- Tabular review (Mike's existing strength — keep as-is, add citation chips inline).
- Document workflows / drafting templates (Mike has these; we add Council pre-flight as an optional final step).
- Authentication and project model.

## Why CourtListener specifically

CourtListener's REST API v4 includes a **Citation Lookup endpoint** that the Free Law Project explicitly markets as "a guardrail to help prevent hallucinated citations." It accepts either a single citation or a block of text and returns which citations resolve to real cases in the corpus. Authenticated users get 5,000 queries/hour for free. This is the highest-leverage single integration in the entire system.

## What this is not (architecturally)

- Not a wrapper around a paid Westlaw / Lexis API. Those would change the cost model and the licensing posture.
- Not a "copilot in your IDE." Mike is a webapp; we keep that.
- Not a multi-tenant SaaS sold by us. The point is self-hosting; the demo at kingsfield.[tld] is a demo, not the product.
