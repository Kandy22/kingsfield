-- 150: get_chats_overview RPC
-- Back-port of live migration `create_get_chats_overview` (2026-07-04).
-- GET /chat calls this; without it every chat-list fetch 500s
-- ("Could not find the function public.get_chats_overview in the schema cache").

create or replace function public.get_chats_overview(
  p_user_id text,
  p_limit integer default null
)
returns table (
  id uuid,
  project_id uuid,
  user_id text,
  creator_display_name text,
  title text,
  created_at timestamptz
)
language sql
stable security definer
set search_path to 'public'
as $$
  select
    c.id,
    c.project_id,
    c.user_id,
    up.display_name as creator_display_name,
    c.title,
    c.created_at
  from chats c
  left join user_profiles up on up.user_id::text = c.user_id
  where c.user_id = p_user_id
  order by c.created_at desc
  limit coalesce(p_limit, 1000);
$$;
