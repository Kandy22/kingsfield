-- 140: get_tabular_reviews_overview RPC
-- Back-port of live migration `create_get_tabular_reviews_overview` (2026-07-04).
-- GET /tabular-review calls this; without it every review-list fetch 500s while
-- creates still succeed ("modal closes but review never appears").
-- Access: owner, direct share (shared_with ? email), or member of the parent project.

create or replace function public.get_tabular_reviews_overview(
  p_user_id text,
  p_user_email text,
  p_project_id uuid default null
)
returns table (
  id uuid,
  project_id uuid,
  user_id text,
  is_owner boolean,
  title text,
  columns_config jsonb,
  document_ids jsonb,
  workflow_id uuid,
  practice text,
  shared_with jsonb,
  created_at timestamptz,
  updated_at timestamptz,
  document_count bigint
)
language sql
stable security definer
set search_path to 'public'
as $$
  select
    t.id,
    t.project_id,
    t.user_id,
    (t.user_id = p_user_id) as is_owner,
    t.title,
    t.columns_config,
    coalesce(t.document_ids, '[]'::jsonb) as document_ids,
    t.workflow_id,
    t.practice,
    coalesce(t.shared_with, '[]'::jsonb) as shared_with,
    t.created_at,
    t.updated_at,
    jsonb_array_length(coalesce(t.document_ids, '[]'::jsonb))::bigint as document_count
  from tabular_reviews t
  where (p_project_id is null or t.project_id = p_project_id)
    and (
      t.user_id = p_user_id
      or (p_user_email is not null and t.shared_with ? p_user_email)
      or (
        t.project_id is not null
        and exists (
          select 1 from projects p
          where p.id = t.project_id
            and (
              p.user_id = p_user_id
              or (p_user_email is not null and p.shared_with ? p_user_email)
            )
        )
      )
    )
  order by t.updated_at desc;
$$;
