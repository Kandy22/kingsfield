-- 160: get_workflows_overview RPC
-- Back-port of live migration `create_get_workflows_overview` (2026-07-05).
-- GET /workflows calls this; without it the Workflows page 500s
-- ("Could not find the function public.get_workflows_overview in the schema cache").
-- Found during a systematic audit of backend .from()/.rpc() calls against the
-- live schema, prompted by three prior instances of this exact drift pattern
-- (get_projects_overview, get_tabular_reviews_overview, get_chats_overview).

create or replace function public.get_workflows_overview(
  p_user_id text,
  p_user_email text,
  p_type text default null
)
returns table (
  id uuid,
  user_id text,
  title text,
  type text,
  prompt_md text,
  columns_config jsonb,
  practice text,
  is_system boolean,
  created_at timestamptz,
  is_owner boolean,
  allow_edit boolean,
  shared_by_name text
)
language sql
stable security definer
set search_path to 'public'
as $$
  select
    w.id,
    w.user_id,
    w.title,
    w.type,
    w.prompt_md,
    w.columns_config,
    w.practice,
    w.is_system,
    w.created_at,
    (w.user_id = p_user_id) as is_owner,
    case
      when w.user_id = p_user_id then true
      when w.is_system then false
      else coalesce(ws.allow_edit, false)
    end as allow_edit,
    case
      when w.user_id = p_user_id or w.is_system then null
      else up.display_name
    end as shared_by_name
  from workflows w
  left join workflow_shares ws
    on ws.workflow_id = w.id
    and lower(ws.shared_with_email) = lower(coalesce(p_user_email, ''))
  left join user_profiles up on up.user_id::text = ws.shared_by_user_id
  where (p_type is null or w.type = p_type)
    and (
      w.user_id = p_user_id
      or w.is_system
      or (p_user_email is not null and ws.id is not null)
    )
  order by w.created_at desc;
$$;

-- Deny-by-default: this RPC takes an arbitrary p_user_id and would leak any
-- user's workflows to anon/authenticated callers if left public (same class
-- of issue closed today for get_chats_overview/get_projects_overview/etc).
revoke execute on function public.get_workflows_overview(text, text, text) from public, anon, authenticated;
