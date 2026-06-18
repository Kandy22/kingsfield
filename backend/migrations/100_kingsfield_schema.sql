-- Kingsfield additions to Mike's schema.
-- Apply AFTER Mike's 000_one_shot_schema.sql.
--
-- These tables back the verification pipeline and council orchestrator.
-- All tables are tied to `projects` (Mike's term for matters) where relevant.

-- ─────────────────────────────────────────────────────────────────────────
-- sources: every primary or secondary authority we've ever fetched.
-- One row per (citation_bluebook). Re-fetches update fetched_at + sha256.
-- ─────────────────────────────────────────────────────────────────────────
create table if not exists sources (
  id uuid primary key default gen_random_uuid(),
  type text not null check (type in (
    'case', 'statute', 'regulation', 'rule', 'constitutional',
    'treatise', 'law-review', 'practice-guide'
  )),
  citation_bluebook text not null,
  short_name text,
  jurisdiction text not null,
  year int,
  source_url text not null,

  -- Provenance.
  fetched_at timestamptz not null default now(),
  fetched_by uuid references auth.users(id),
  sha256 text not null,
  storage_key text,             -- pointer into S3-compatible storage
  full_text text,               -- inlined for short docs; null when storage_key set

  -- CourtListener-specific identifiers (nullable for non-case sources).
  cl_cluster_id bigint,
  cl_opinion_id bigint,

  -- Currency status, refreshed periodically.
  subsequent_history text,
  currency_signal text check (currency_signal in ('green','yellow','red')),
  currency_checked_at timestamptz,

  unique(citation_bluebook)
);

create index if not exists sources_jurisdiction_idx on sources(jurisdiction);
create index if not exists sources_type_idx on sources(type);

-- ─────────────────────────────────────────────────────────────────────────
-- citations: every cite that appeared in any model-generated artifact.
-- Joined to a message_id (Mike's chat messages) and a source_id.
-- ─────────────────────────────────────────────────────────────────────────
create table if not exists citations (
  id uuid primary key default gen_random_uuid(),
  source_id uuid references sources(id) on delete set null,
  message_id uuid,              -- references Mike's messages table
  project_id uuid,              -- references Mike's projects table

  pin_cite text,
  quoted_text text,

  -- Four-gate state.
  gate_existence boolean default false,
  gate_quote_accuracy boolean default false,
  gate_currency boolean default false,
  gate_jurisdiction_fit boolean default false,

  status text not null default 'pending'
    check (status in ('pending','verified','conditional','vetoed')),

  verifier text,                -- 'skeptic' or user_id as text
  verified_at timestamptz,
  notes text
);

create index if not exists citations_status_idx on citations(status);
create index if not exists citations_project_idx on citations(project_id);

-- ─────────────────────────────────────────────────────────────────────────
-- council_sessions: one row per convened council session.
-- ─────────────────────────────────────────────────────────────────────────
create table if not exists council_sessions (
  id uuid primary key default gen_random_uuid(),
  project_id uuid,
  artifact_id uuid,             -- typically a message_id or document_id
  protocol text not null check (protocol in (
    'standard', 'citation-only', 'strategy-sanity-check'
  )),
  charter text not null,
  status text not null default 'in-progress'
    check (status in (
      'in-progress', 'blocked-by-skeptic',
      'completed-with-conditional', 'completed-clean'
    )),
  started_at timestamptz not null default now(),
  ended_at timestamptz,
  decision_memo text,           -- written by the human convener at close
  convener uuid references auth.users(id)
);

-- ─────────────────────────────────────────────────────────────────────────
-- council_role_outputs: each role's output within a session.
-- ─────────────────────────────────────────────────────────────────────────
create table if not exists council_role_outputs (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references council_sessions(id) on delete cascade,
  role text not null check (role in (
    'skeptic','judge','opposing_counsel','strategist',
    'procedural_clerk','evidence_master','witness_coach',
    'translator','historian'
  )),
  payload jsonb not null,
  created_at timestamptz not null default now()
);

create index if not exists council_role_outputs_session_idx
  on council_role_outputs(session_id);

-- ─────────────────────────────────────────────────────────────────────────
-- council_dissents: roles can dissent from the convener's final decision.
-- Recorded but non-blocking (only the Skeptic has hard veto, and that's
-- enforced via session status, not dissent).
-- ─────────────────────────────────────────────────────────────────────────
create table if not exists council_dissents (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references council_sessions(id) on delete cascade,
  role text not null,
  rationale text not null,
  recorded_at timestamptz not null default now()
);

-- ─────────────────────────────────────────────────────────────────────────
-- RLS: lock everything to project-scoped access.
-- (Mike's existing RLS handles projects; we mirror it here.)
-- ─────────────────────────────────────────────────────────────────────────
alter table sources enable row level security;
alter table citations enable row level security;
alter table council_sessions enable row level security;
alter table council_role_outputs enable row level security;
alter table council_dissents enable row level security;

-- Sources are global (verified case law isn't user-private) but writable
-- only by authenticated users. Adjust if you want per-tenant isolation.
create policy sources_read on sources for select using (true);
create policy sources_write on sources
  for insert with check (auth.uid() is not null);

-- Citations / council artifacts are scoped to project membership. The
-- exact policy depends on Mike's project_members table; this is the shape.
create policy citations_member_read on citations
  for select using (
    project_id in (
      select id from public.projects
      where user_id = auth.uid()::text
      or shared_with @> jsonb_build_array(auth.email())
    )
  );

create policy council_sessions_member_read on council_sessions
  for select using (
    project_id in (
      select id from public.projects
      where user_id = auth.uid()::text
      or shared_with @> jsonb_build_array(auth.email())
    )
  );
