-- Migration 120: Docket Watcher
-- Adds docket tracking columns to projects and a docket_checks results table.
--
-- Run after 110_council_and_crew_schema.sql.

-- ── 1. Add docket tracking fields to projects ─────────────────────────────
alter table projects
  add column if not exists docket_id         bigint,        -- CourtListener numeric docket ID
  add column if not exists docket_number     text,          -- case number, e.g. "2:26-cv-00315"
  add column if not exists court_code        text,          -- CL court code, e.g. "cand"
  add column if not exists notify_email      text,          -- who to email on docket updates
  add column if not exists last_docket_check date;          -- date of most recent successful sweep

-- ── 2. Docket check results ───────────────────────────────────────────────
create table if not exists docket_checks (
  id                      uuid primary key default gen_random_uuid(),
  project_id              uuid not null references projects(id) on delete cascade,
  as_of                   timestamptz not null default now(),
  docket_id               bigint,
  court                   text,
  filings_json            jsonb not null default '[]',   -- sanitised FilingRecord[]
  deadlines_json          jsonb not null default '[]',   -- DeadlineRecord[]
  report_md               text not null default '',
  new_filings_count       int not null default 0,
  critical_deadline_count int not null default 0,
  created_at              timestamptz not null default now()
);

create index if not exists docket_checks_project_id_idx on docket_checks(project_id);
create index if not exists docket_checks_as_of_idx      on docket_checks(as_of desc);

-- RLS: users can only read docket checks for projects they have access to.
alter table docket_checks enable row level security;

create policy "docket_checks_select" on docket_checks
  for select using (
    exists (
      select 1 from projects p
      where p.id = docket_checks.project_id
        and p.user_id = auth.uid()
    )
  );

create policy "docket_checks_insert" on docket_checks
  for insert with check (
    exists (
      select 1 from projects p
      where p.id = docket_checks.project_id
        and p.user_id = auth.uid()
    )
  );

-- ── 3. Comments ───────────────────────────────────────────────────────────
comment on column projects.docket_id     is 'CourtListener numeric docket ID for automated docket watching';
comment on column projects.docket_number is 'Case number string, e.g. 2:26-cv-00315';
comment on column projects.court_code    is 'CourtListener court identifier, e.g. cand (N.D. Cal.)';
comment on column projects.notify_email  is 'Email address to notify when new filings or deadlines are detected';
comment on table  docket_checks          is 'Results of automated docket sweeps — one row per matter per run';
