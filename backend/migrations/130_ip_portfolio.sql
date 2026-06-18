-- Migration 130: IP Portfolio Assets
-- Adds a table for tracking IP assets and their renewal deadlines.
-- Supports: patents, trademarks (US + Madrid), copyrights, domains, trade secrets.
--
-- Run after 120_docket_watcher.sql.

-- ── 1. IP asset table ─────────────────────────────────────────────────────
create table if not exists ip_assets (
  id                uuid primary key default gen_random_uuid(),
  project_id        uuid not null references projects(id) on delete cascade,
  user_id           uuid not null references auth.users(id) on delete cascade,

  -- Classification
  asset_type        text not null check (asset_type in (
                      'patent_us', 'patent_pct', 'patent_ep',
                      'trademark_us', 'trademark_madrid', 'trademark_foreign',
                      'copyright', 'domain', 'trade_secret'
                    )),
  title             text not null,
  description       text,

  -- Registration / filing identifiers
  registration_number   text,
  application_number    text,
  serial_number         text,   -- USPTO serial for TM
  filing_date           date,
  registration_date     date,
  expiration_date       date,   -- for domains and foreign TMs
  grant_date            date,   -- patents

  -- Jurisdiction
  jurisdiction      text,       -- "US", "EP", "WIPO", domain TLD, etc.
  classes           text[],     -- Nice classes for trademarks
  international_classes text[], -- for patents (CPC/IPC)

  -- Maintenance / renewal tracking
  next_deadline_date  date,
  next_deadline_type  text,     -- "Section 8 Declaration", "Maintenance Fee Year 4", etc.
  last_renewal_date   date,
  renewal_cycle_years int,      -- e.g. 10 for US TMs, 20 for patents

  -- Owner / assignee
  owner_name        text,
  inventor_names    text[],
  assignee_name     text,

  -- Status
  status            text not null default 'active' check (status in (
                      'active', 'pending', 'expired', 'abandoned',
                      'cancelled', 'lapsed', 'licensed'
                    )),

  -- Metadata
  notes             text,
  tags              text[],
  notify_email      text,
  raw_json          jsonb,      -- store full USPTO/WIPO API response for reference

  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

create index if not exists ip_assets_project_id_idx on ip_assets(project_id);
create index if not exists ip_assets_user_id_idx    on ip_assets(user_id);
create index if not exists ip_assets_type_idx       on ip_assets(asset_type);
create index if not exists ip_assets_deadline_idx   on ip_assets(next_deadline_date asc nulls last);
create index if not exists ip_assets_status_idx     on ip_assets(status);

-- ── 2. IP renewal checks (analogous to docket_checks) ────────────────────
create table if not exists ip_renewal_checks (
  id                    uuid primary key default gen_random_uuid(),
  as_of                 timestamptz not null default now(),
  assets_checked        int not null default 0,
  deadlines_within_90   int not null default 0,
  deadlines_within_30   int not null default 0,
  critical_count        int not null default 0,  -- ≤14 days
  report_md             text not null default '',
  assets_json           jsonb not null default '[]',  -- snapshot of assets with deadlines
  created_at            timestamptz not null default now()
);

create index if not exists ip_renewal_checks_as_of_idx on ip_renewal_checks(as_of desc);

-- ── 3. RLS ────────────────────────────────────────────────────────────────
alter table ip_assets enable row level security;

create policy "ip_assets_select" on ip_assets
  for select using (user_id = auth.uid());

create policy "ip_assets_insert" on ip_assets
  for insert with check (user_id = auth.uid());

create policy "ip_assets_update" on ip_assets
  for update using (user_id = auth.uid());

create policy "ip_assets_delete" on ip_assets
  for delete using (user_id = auth.uid());

-- ip_renewal_checks is global (not per-user) — scoped to service role inserts only.
-- Users read via the API; no direct RLS needed for service-side writes.

-- ── 4. Auto-update updated_at ─────────────────────────────────────────────
create or replace function set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger ip_assets_updated_at
  before update on ip_assets
  for each row execute function set_updated_at();

-- ── 5. Comments ──────────────────────────────────────────────────────────
comment on table ip_assets         is 'IP portfolio assets tracked for renewal deadlines and status';
comment on table ip_renewal_checks is 'Results of automated IP renewal sweeps';
comment on column ip_assets.next_deadline_date is 'Next action date: maintenance fee, §8 declaration, renewal, domain expiry, etc.';
comment on column ip_assets.next_deadline_type is 'Human-readable label for what must be done by next_deadline_date';
comment on column ip_assets.raw_json           is 'Full API response from USPTO/WIPO/IANA for reference; not used for decisions';
