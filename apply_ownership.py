#!/usr/bin/env python3
"""Scope project, council, and IP reads to the logged-in owner. 404 otherwise."""
from pathlib import Path

path = Path("backend/src/routes/index.ts")
text = path.read_text()
if "async function ownedProject" in text:
    print("already patched")
    raise SystemExit(0)

helper = '''
  const ownedProject = async (userId: string, projectId: string) => {
    const { data, error } = await deps.supabase
      .from("projects")
      .select("id, name, docket_id, docket_number, court_code, notify_email, user_id")
      .eq("id", projectId)
      .eq("user_id", userId)
      .maybeSingle();
    if (error || !data) return null;
    return data;
  };

  const ownedProjectIds = async (userId: string): Promise<string[]> => {
    const { data, error } = await deps.supabase
      .from("projects")
      .select("id")
      .eq("user_id", userId);
    if (error || !data) return [];
    return data.map((row: { id: string }) => row.id);
  };

'''
anchor = "  const r = Router();\n"
if anchor not in text:
    raise SystemExit("router anchor missing")
text = text.replace(anchor, anchor + helper, 1)

old_watch = '''      const matter_id = req.params.id;
      const { data: project, error: pErr } = await deps.supabase
        .from('projects')
        .select('id, name, docket_id, docket_number, court_code, notify_email')
        .eq('id', matter_id)
        .single();

      if (pErr || !project) {
        return res.status(404).json({ error: 'Matter not found' });
      }'''
new_watch = '''      const userId = res.locals.userId as string;
      const project = await ownedProject(userId, req.params.id);
      if (!project) return res.status(404).json({ error: 'Matter not found' });
      const matter_id = project.id;'''
if old_watch not in text:
    raise SystemExit("docket watch block missing")
text = text.replace(old_watch, new_watch, 1)

old_checks = '''  r.get('/projects/:id/docket/checks', requireAuth, async (req: Request, res: Response) => {
    const { data, error } = await deps.supabase
      .from('docket_checks')
      .select('id, as_of, new_filings_count, critical_deadline_count, report_md, deadlines_json')
      .eq('project_id', req.params.id)'''
new_checks = '''  r.get('/projects/:id/docket/checks', requireAuth, async (req: Request, res: Response) => {
    const userId = res.locals.userId as string;
    if (!(await ownedProject(userId, req.params.id))) {
      return res.status(404).json({ error: 'Matter not found' });
    }
    const { data, error } = await deps.supabase
      .from('docket_checks')
      .select('id, as_of, new_filings_count, critical_deadline_count, report_md, deadlines_json')
      .eq('project_id', req.params.id)'''
if old_checks not in text:
    raise SystemExit("docket checks block missing")
text = text.replace(old_checks, new_checks, 1)

old_ip = '''        .select('id, name, notify_email')
        .eq('id', req.params.id)
        .single();

      if (pErr || !project) {
        return res.status(404).json({ error: 'Project not found' });
      }'''
new_ip = '''        .select('id, name, notify_email, user_id')
        .eq('id', req.params.id)
        .eq('user_id', res.locals.userId as string)
        .maybeSingle();

      if (pErr || !project) {
        return res.status(404).json({ error: 'Project not found' });
      }'''
if old_ip not in text:
    raise SystemExit("ip check block missing")
text = text.replace(old_ip, new_ip, 1)

old_council = '''    .eq('id', req.params.id)
      .single();
    if (error || !data) return res.status(404).json({ error: 'not found' });
    const gated = await gateStoredCouncilRow(data);'''
new_council = '''    .eq('id', req.params.id)
      .single();
    if (error || !data) return res.status(404).json({ error: 'not found' });
    const owner = await ownedProject(res.locals.userId as string, (data as any).project_id);
    if (!owner) return res.status(404).json({ error: 'not found' });
    const gated = await gateStoredCouncilRow(data);'''
if old_council not in text:
    raise SystemExit("council json block missing")
text = text.replace(old_council, new_council, 1)

for old, new, label in (
    (
        "if (error || !data) return res.status(404).send('not found');\n    const gated = await gateStoredCouncilRow(data);\n    const html = renderCouncilHTML",
        "if (error || !data) return res.status(404).send('not found');\n    const owner = await ownedProject(res.locals.userId as string, (data as any).project_id);\n    if (!owner) return res.status(404).send('not found');\n    const gated = await gateStoredCouncilRow(data);\n    const html = renderCouncilHTML",
        "html",
    ),
    (
        "if (error || !data) return res.status(404).send('not found');\n    const gated = await gateStoredCouncilRow(data);\n    const md = renderCouncilMarkdown",
        "if (error || !data) return res.status(404).send('not found');\n    const owner = await ownedProject(res.locals.userId as string, (data as any).project_id);\n    if (!owner) return res.status(404).send('not found');\n    const gated = await gateStoredCouncilRow(data);\n    const md = renderCouncilMarkdown",
        "markdown",
    ),
):
    if old not in text:
        raise SystemExit(label + " block missing")
    text = text.replace(old, new, 1)

old_assets = '''    if (req.query.projectId) {
      query = query.eq('project_id', req.query.projectId as string);
    }'''
new_assets = '''    const projectIds = await ownedProjectIds(res.locals.userId as string);
    if (req.query.projectId) {
      const requested = req.query.projectId as string;
      if (!projectIds.includes(requested)) return res.status(404).json({ error: 'Project not found' });
      query = query.eq('project_id', requested);
    } else if (projectIds.length === 0) {
      return res.json([]);
    } else {
      query = query.in('project_id', projectIds);
    }'''
if old_assets not in text:
    raise SystemExit("ip assets block missing")
text = text.replace(old_assets, new_assets, 1)

old_runs = '''  r.get('/ip/renewal/checks', requireAuth, async (_req: Request, res: Response) => {
    const { data, error } = await deps.supabase
      .from('ip_renewal_checks')
      .select('id, as_of, assets_checked, critical_count, deadlines_within_30, report_md')
      .order('as_of', { ascending: false })
      .limit(10);'''
new_runs = '''  r.get('/ip/renewal/checks', requireAuth, async (_req: Request, res: Response) => {
    const projectIds = await ownedProjectIds(res.locals.userId as string);
    if (projectIds.length === 0) return res.json([]);
    const { data, error } = await deps.supabase
      .from('ip_renewal_checks')
      .select('id, as_of, assets_checked, critical_count, deadlines_within_30, report_md, project_id')
      .in('project_id', projectIds)
      .order('as_of', { ascending: false })
      .limit(10);'''
if old_runs not in text:
    raise SystemExit("ip runs block missing")
text = text.replace(old_runs, new_runs, 1)

path.write_text(text)
print("patched", path)
