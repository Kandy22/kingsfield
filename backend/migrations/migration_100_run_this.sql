create table if not exists sources (
  id uuid primary key default gen_random_uuid(),
  type text not null check (type in ('case','statute','regulation','rule','constitutional','treatise','law-review','practice-guide')),
  citation_bluebook text not null,
  short_name text,
  jurisdiction text not null,
  year int,
  source_url text not null,
  fetched_at timestamptz not null default now(),
  fetched_by uuid references auth.users(id),
  sha256 text not null,
  storage_key text,
  full_text text,
  cl_cluster_id bigint,
  cl_opinion_id bigint,
  subsequent_history text,
  currency_signal text check (currency_signal in ('green','yellow','red')),
  currency_checked_at timestamptz,
  unique(citation_bluebook)
);

create index if not exists sources_jurisdiction_idx on sources(jurisdiction);
create index if not exists sources_type_idx on sources(type);

create table if not exists citations (
  id uuid primary key default gen_random_uuid(),
  source_id uuid references sources(id) on delete set null,
  message_id uuid,
  project_id uuid,
  pin_cite text,
  quoted_text text,
  gate_existence boolean default false,
  gate_quote_accuracy boolean default false,
  gate_currency boolean default false,
  gate_jurisdiction_fit boolean default false,
  status text not null default 'pending' check (status in ('pending','verified','conditional','vetoed')),
  verifier text,
  verified_at timestamptz,
  notes text
);

create index if not exists citations_status_idx on citations(status);
create index if not exists citations_project_idx on citations(project_id);

create table if not exists council_sessions (
  id uuid primary key default gen_random_uuid(),
  project_id uuid,
  artifact_id uuid,
  protocol text not null check (protocol in ('standard','citation-only','strategy-sanity-check')),
  charter text not null,
  status text not null default 'in-progress' check (status in ('in-progress','blocked-by-skeptic','completed-with-conditional','completed-clean')),
  started_at timestamptz not null default now(),
  ended_at timestamptz,
  decision_memo text,
  convener uuid references auth.users(id)
);

create table if not exists council_role_outputs (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references council_sessions(id) on delete cascade,
  role text not null check (role in ('skeptic','judge','opposing_counsel','strategist','procedural_clerk','evidence_master','witness_coach','translator','historian')),
  payload jsonb not null,
  created_at timestamptz not null default now()
);

create index if not exists council_role_outputs_session_idx on council_role_outputs(session_id);

create table if not exists council_dissents (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references council_sessions(id) on delete cascade,
  role text not null,
  rationale text not null,
  recorded_at timestamptz not null default now()
);

alter table sources enable row level security;
alter table citations enable row level security;
alter table council_sessions enable row level security;
alter table council_role_outputs enable row level security;
alter table council_dissents enable row level security;

create policy sources_read on sources for select using (true);
create policy sources_write on sources for insert with check (auth.uid() is not null);

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
