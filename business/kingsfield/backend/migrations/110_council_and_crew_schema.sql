-- Extends 100_kingsfield_schema.sql with tables for:
--   - LLM Council sessions (Karpathy-style 5-advisor flow)
--   - Crew session traces (audit log of which roles fired and what they returned)
--
-- Apply AFTER 100_kingsfield_schema.sql.

-- ─────────────────────────────────────────────────────────────────────────
-- llm_council_sessions: one row per Karpathy-style council session.
-- ─────────────────────────────────────────────────────────────────────────
create table if not exists llm_council_sessions (
  id uuid primary key default gen_random_uuid(),
  project_id uuid,
  user_id uuid references auth.users(id),

  raw_question text,
  framed_question text not null,

  -- Full structured advisor + reviewer outputs as JSON. Keeps the schema
  -- flexible while we iterate on the council format.
  advisors jsonb not null,
  reviewers jsonb not null,
  chairman_verdict text not null,

  created_at timestamptz not null default now()
);

create index if not exists llm_council_project_idx
  on llm_council_sessions(project_id);

-- ─────────────────────────────────────────────────────────────────────────
-- crew_traces: audit log of each Crew run.
-- Each row corresponds to one user message that triggered the Crew.
-- ─────────────────────────────────────────────────────────────────────────
create table if not exists crew_traces (
  id uuid primary key default gen_random_uuid(),
  project_id uuid,
  user_id uuid references auth.users(id),
  message_id uuid,

  user_message text not null,
  decision text not null check (decision in ('crew', 'simple')),
  roles_spawned text[] not null default '{}',

  -- Full structured outputs from each spawned role.
  researcher_output jsonb,
  analyst_output jsonb,
  strategist_output jsonb,
  team_lead_reply text,

  /* Latency in ms — useful for tuning. */
  total_latency_ms int,

  created_at timestamptz not null default now()
);

create index if not exists crew_traces_project_idx on crew_traces(project_id);

-- ─────────────────────────────────────────────────────────────────────────
-- RLS — same pattern as the rest of Kingsfield: project-scoped reads.
-- ─────────────────────────────────────────────────────────────────────────
alter table llm_council_sessions enable row level security;
alter table crew_traces enable row level security;

create policy llm_council_member_read on llm_council_sessions
  for select using (
    user_id = auth.uid()
    or project_id in (
      select project_id from project_members where user_id = auth.uid()
    )
  );

create policy crew_traces_member_read on crew_traces
  for select using (
    user_id = auth.uid()
    or project_id in (
      select project_id from project_members where user_id = auth.uid()
    )
  );
