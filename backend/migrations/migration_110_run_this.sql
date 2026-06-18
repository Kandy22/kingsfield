create table if not exists llm_council_sessions (
  id uuid primary key default gen_random_uuid(),
  project_id uuid,
  user_id uuid references auth.users(id),
  raw_question text,
  framed_question text not null,
  advisors jsonb not null,
  reviewers jsonb not null,
  chairman_verdict text not null,
  created_at timestamptz not null default now()
);

create index if not exists llm_council_project_idx on llm_council_sessions(project_id);

create table if not exists crew_traces (
  id uuid primary key default gen_random_uuid(),
  project_id uuid,
  user_id uuid references auth.users(id),
  message_id uuid,
  user_message text not null,
  decision text not null check (decision in ('crew','simple')),
  roles_spawned text[] not null default '{}',
  researcher_output jsonb,
  analyst_output jsonb,
  strategist_output jsonb,
  team_lead_reply text,
  total_latency_ms int,
  created_at timestamptz not null default now()
);

create index if not exists crew_traces_project_idx on crew_traces(project_id);

alter table llm_council_sessions enable row level security;
alter table crew_traces enable row level security;

create policy llm_council_member_read on llm_council_sessions
  for select using (user_id = auth.uid());

create policy crew_traces_member_read on crew_traces
  for select using (user_id = auth.uid());

alter table sources add column if not exists cl_opinion_id bigint;
