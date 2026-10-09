#!/usr/bin/env python3
"""Re-gate stored titles on the two remaining list routes."""
from pathlib import Path

projects = Path("backend/src/routes/projects.ts")
text = projects.read_text()
if "gateTitleText" not in text:
    old = 'import { checkProjectAccess } from "../lib/access";\n'
    new = old + 'import { gateTitleText, verifyDraftForSse } from "../middleware/hallucination_guard";\n'
    if old not in text:
        raise SystemExit("projects import missing")
    text = text.replace(old, new, 1)
anchor = '  await attachChatCreatorLabels(db, chats);\n  res.json(chats);\n'
repl = '''  await attachChatCreatorLabels(db, chats);
  const gatedChats = await Promise.all(chats.map(async (chat) => {
    if (typeof chat.title !== "string" || !chat.title) return chat;
    const gated = await gateTitleText(chat.title, "Misc. Query", {
      verify: (value) => verifyDraftForSse(value, {
        courtListenerToken: process.env.COURTLISTENER_TOKEN ?? "",
        supabase: db,
      }),
      logError: (context, error) => console.error(`[project-chats] ${context}`, error),
    });
    return { ...chat, title: gated.title };
  }));
  res.json(gatedChats);
'''
if anchor not in text:
    raise SystemExit("project chats return missing")
projects.write_text(text.replace(anchor, repl, 1))
print("patched", projects)

tabular = Path("backend/src/routes/tabular.ts")
tab = tabular.read_text()
old = '''        .order("updated_at", { ascending: false });

    res.json(chats ?? []);
});'''
new = '''        .order("updated_at", { ascending: false });

    const gatedChats = await Promise.all((chats ?? []).map(async (chat) => {
        if (typeof chat.title !== "string" || !chat.title) return chat;
        const gated = await gateTitleText(chat.title, "Misc. Query", cellGateOptions(db, "tabular/chats"));
        return { ...chat, title: gated.title };
    }));
    res.json(gatedChats);
});'''
if old not in tab:
    raise SystemExit("tabular chats return missing")
tabular.write_text(tab.replace(old, new, 1))
print("patched", tabular)
