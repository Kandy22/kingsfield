# Setup

Kingsfield inherits Mike's deployment shape and adds a couple of integrations on top.

## Prerequisites

Same as Mike:
- Node 20+
- Supabase project (auth + Postgres)
- S3-compatible object storage (Cloudflare R2 works well)
- LibreOffice (for DOC/DOCX→PDF conversion)
- At least one model provider key (Anthropic Claude or Google Gemini)

Plus, new for Kingsfield:
- A **CourtListener API token** (free, 5,000 queries/hour). Register at https://www.courtlistener.com/sign-in/?next=/

## Install

```bash
npm install --prefix backend
npm install --prefix frontend
```

## Environment

Copy the example files:

```bash
cp backend/.env.example backend/.env
cp frontend/.env.local.example frontend/.env.local
```

Then fill in the Kingsfield-specific keys (in addition to Mike's):

```bash
# backend/.env
COURTLISTENER_TOKEN=<your token>

# Optional — for paid Shepard's / KeyCite cross-check at finalization stage
# Leave blank to rely solely on free-tier currency checks.
WESTLAW_API_KEY=
LEXIS_API_KEY=
```

## Database

Apply Mike's schema first, then Kingsfield's additions:

```sql
-- In the Supabase SQL editor:
\i backend/migrations/000_one_shot_schema.sql
\i backend/migrations/100_kingsfield_schema.sql
```

The `100_kingsfield_schema.sql` migration adds `sources`, `citations`, `council_sessions`, `council_role_outputs`, and `council_dissents` tables. It does not modify any of Mike's existing tables.

## Run

```bash
npm run dev --prefix backend
npm run dev --prefix frontend
```

Open http://localhost:3000.

## First-run smoke test

The fastest way to confirm the verification pipeline is wired correctly:

1. Open a project.
2. In chat, paste: *"Summarize the holding of Mathews v. Eldridge, 424 U.S. 319 (1976)."*
3. The assistant should respond with a summary AND a verified ✓ green chip on the citation.
4. Click the chip — the Source Inspector should open with fetch date, SHA-256, and gate status.

Now try the failure mode:

1. Paste: *"What did Smith v. Jones, 999 F.4th 9999 (11th Cir. 2024) hold about due process?"*
2. The assistant should refuse to answer with content, and the response should be banner-flagged with a Skeptic veto: that case doesn't exist.

If both pass, the pipeline is live.

## Building for production

Same as Mike:

```bash
npm run build --prefix backend
npm run build --prefix frontend
npm run lint --prefix frontend
```

## Self-hosting note

Kingsfield is AGPL-3.0. If you run a modified version as a network service, you must offer your modified source to the users of that service. This is inherited from Mike. The point of the license is to keep the open-source legal AI ecosystem open — if you fork, your fork stays in the commons.
