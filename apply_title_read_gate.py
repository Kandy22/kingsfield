#!/usr/bin/env python3
"""Re-gate stored chat titles on the two chat read routes."""
from pathlib import Path

path = Path("backend/src/routes/chat.ts")
text = path.read_text()
if "async function gatedStoredTitle" in text:
    print("already patched")
    raise SystemExit(0)

helper = '''
async function gatedStoredTitle(title: string | null, db: Db): Promise<string | null> {
    if (!title) return title;
    const gated = await gateTitleText(title, TITLE_FALLBACK, {
        verify: (text) =>
            verifyDraftForSse(text, {
                courtListenerToken: process.env.COURTLISTENER_TOKEN ?? "",
                supabase: db,
            }),
        logError: (context, error) => console.error(`[chat-title] ${context}`, error),
    });
    return gated.title;
}

'''
anchor = "const TITLE_FALLBACK = \"Misc. Query\";\n"
if anchor not in text:
    raise SystemExit("fallback anchor missing")
text = text.replace(anchor, anchor + helper, 1)

old_list = '''    if (error) return void res.status(500).json({ detail: error.message });
    res.json(data ?? []);
});'''
new_list = '''    if (error) return void res.status(500).json({ detail: error.message });
    const rows = Array.isArray(data) ? data : [];
    const gated = await Promise.all(rows.map(async (row) => {
        if (!row || typeof row !== "object" || typeof (row as { title?: unknown }).title !== "string") return row;
        return { ...row, title: await gatedStoredTitle((row as { title: string }).title, db) };
    }));
    res.json(gated);
});'''
if old_list not in text:
    raise SystemExit("list return missing")
text = text.replace(old_list, new_list, 1)

old_one = '''    const hydrated = await hydrateEditStatuses(messages ?? [], db);
    res.json({ chat, messages: hydrated });'''
new_one = '''    const hydrated = await hydrateEditStatuses(messages ?? [], db);
    res.json({ chat: { ...chat, title: await gatedStoredTitle(chat.title, db) }, messages: hydrated });'''
if old_one not in text:
    raise SystemExit("single chat return missing")
text = text.replace(old_one, new_one, 1)

path.write_text(text)
print("patched", path)
