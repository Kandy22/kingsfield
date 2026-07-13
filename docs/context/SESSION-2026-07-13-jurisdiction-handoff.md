# Jurisdiction redesign — handoff (2026-07-13)

Read this if you only have room for one page. Full product context still lives in
`current-state.md` / `CLAUDE.md`. **App only:** `frontend/` + `backend/`.

---

## How to run (sandbox)

Two servers, both required:

```bash
cd /Users/aaronray/kingsfield/backend && npm run dev   # :3001
cd /Users/aaronray/kingsfield/frontend && npm run dev  # :3000
```

- Local: http://localhost:3000  
- LAN (same Wi‑Fi): http://192.168.1.218:3000  
- Health: http://localhost:3001/health → `{"ok":true}`  
- Login required (`NEXT_PUBLIC_DEMO_MODE=false` right now)

After login, check:

1. **Assistant** — jurisdiction control at the top (front door)  
2. **Case Law** — same control; state list is **not** empty  
3. **Legislation** — same control; statutes follow the pick (no second picker)

---

## What you decided (locked)

| Decision | Why |
|----------|-----|
| One jurisdiction for the whole app | Separate case vs statute pickers cause confusion |
| Statutes auto-follow case jurisdiction | No real use case for “cases in CA, statutes in NY” |
| Google Scholar two-tier UI | Quick radios for 90% of use; multi-court grid for power users |
| Two build passes | Pass 1 = quick shared selector; Pass 2 = Scholar radios + multi-court |

**Factual note:** Google Scholar does case law (+ articles), not statutes. Kingsfield still covers statutes — scoped by the **same** jurisdiction.

---

## Pass 1 — DONE (commit `abb2114`)

- `frontend/src/app/lib/jurisdictions.ts` — Federal + 50 states + DC/PR → CourtListener court IDs + statute URLs (static; no server snapshot)  
- `frontend/src/contexts/JurisdictionContext.tsx` — shared + `localStorage`  
- `JurisdictionSelector` — searchable single-select  
- Case Law uses it (replaces empty-State `CourtPicker` path)  
- Legislation auto-scopes; dropped 50-state grid  
- Layout wraps pages in `JurisdictionProvider`

**Root cause fixed:** old State tab needed `backend/data/courtlistener-courts.json`. That file is still missing (`GET /api/research/courts` → 503). Static data does not need it.

---

## Pass 2 — IN PROGRESS / NEXT

Scholar pattern:

1. **Quick row:** `Federal courts` · `[State] courts` · `Select courts…`  
2. **Select courts…** → multi-select grid (reuse `CourtPicker` ideas + static fallbacks when snapshot 503s)  
3. Mount prominently on **Assistant**; keep compact mirrors on Case Law / Legislation  
4. Case search uses effective `courtIds`; statutes always follow primary jurisdiction key  

Cleanup: remove dead `STATES` / `STATE_LAW_URLS` from legislation page if still present.

---

## Do not do

- Reintroduce a separate “statute jurisdiction” picker  
- Depend on the courts snapshot for basic state picking  
- Touch Wingman / Face Mood / Video Analyzer / verifier in this thread  

---

## Git

- Pass 1: `abb2114` on `main` (local; check `git status` before push)  
- Repo root is a large kitchen-sink tree — **only commit frontend/backend jurisdiction files** for this work  
