#!/usr/bin/env python3
from pathlib import Path

notes = Path("docs/context/current-state.md")
body = notes.read_text()
marker = "2026-10-09 gate follow-ups on main"
if marker not in body:
    notes.write_text(
        "# Kingsfield Lawfare \u2014 Current State\n"
        "*Last updated: 2026-10-09. The items below supersede the 2026-10-08 open list.*\n\n"
        "## 2026-10-09 gate follow-ups on main\n\n"
        "Closed on `main` after `29efac5`: tabular chat, document writes, chat titles (including read-time replacement of a stored title that fails Gate 1), inferred Florida bounds, MCP connector refusal, owner checks on project/council/IP routes, analytics extract gated before save, jammed `So. 2d` / `So. 3d` identifier scrub, crew fallback skipped on disconnect, live failed-reply text.\n\n"
        "Still open: a crew model call already in flight is not cancelled; `GET /analytics` re-checks stored rows on read but does not rewrite them.\n\n"
        + body
    )
    print("patched", notes)
else:
    print("notes already patched")

route = Path("backend/src/routes/index.ts")
text = route.read_text()
if "analytics stored row withheld" in text:
    print("route already patched")
    raise SystemExit(0)
old = '''    if (error) return void res.status(500).json({ detail: error.message });
    res.json({ extractions: data ?? [] });
  });'''
new = '''    if (error) return void res.status(500).json({ detail: error.message });
    const rows = data ?? [];
    const extractions = await Promise.all(rows.map(async (row) => {
      const blob = JSON.stringify({
        caption: row.caption,
        entities: row.entities,
        allegations: row.allegations,
        defenses: row.defenses,
        authorities: row.authorities,
        rarity: row.rarity,
        defense_summary: row.defense_summary,
      });
      const checked = await verifyDraftForSse(blob, {
        courtListenerToken: deps.courtListenerToken,
        supabase: deps.supabase,
      });
      if (!checked.hasVetoes && !checked.error) return row;
      // analytics stored row withheld
      return {
        ...row,
        caption: null,
        entities: [],
        allegations: [],
        defenses: [],
        authorities: [],
        rarity: null,
        defense_summary: "This extraction was withheld because it could not be verified.",
      };
    }));
    res.json({ extractions });
  });'''
if old not in text:
    raise SystemExit("analytics list return missing")
route.write_text(text.replace(old, new, 1))
print("patched", route)
