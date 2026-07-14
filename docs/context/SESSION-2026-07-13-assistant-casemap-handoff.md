# Session handoff — 2026-07-13 (evening)

**Status when left:** Frontend/backend **stopped** (ports 3000/3001 killed so LAN share links die). Work is **local on `main`**, largely **uncommitted** unless you committed elsewhere. Read this + `CLAUDE.md` + `current-state.md` before continuing.

---

## Product map locked this session

| Surface | Role |
|---|---|
| **Assistant** | Front door: upload → auto case extract → card in chat → optional Case Map / Editor |
| **Case Map** (`/analytics`) | Per-document deep map (entities, allegations, authorities, defenses) — **not** “Judicial Analytics” |
| **Tabular Review** | Multi-doc matrix (rows = docs, columns = prompts) — not intake |
| **Workflows** | Opt-in templates only (Assistant prompt **or** tabular columns) — **never** auto-start on upload |
| **Council** | Adversarial multi-model deliberation |
| **Case Law / Statutes** | Primary-source research |

### Explicit non-goals (do not reopen without Aaron)
- Do not move parser exclusively into Analytics  
- Do not auto-start workflows on upload  
- Do not ship Ulysses multi-style pack (Pleading/Agreement/Memo skins)  
- Do not build a WordPerfect clone first (WP = Coming Soon interop)  
- Do not use brutalist heavy bold / Playfair for chrome — **Helvetica Neue**, thin elegant weights  

---

## What shipped (code)

### 1. Assistant intake + extract (slices 1–3)
- **Auto `runCaseExtraction` on every upload** (standalone + project) — `backend/src/routes/documents.ts`  
- **Case extract card** — `frontend/src/app/components/assistant/CaseExtractionCard.tsx`  
  - Polls `/api/analytics?documentId=` via `waitForExtraction`  
  - Chips: Open Case Map, Open in editor  
  - Also under user messages that had files (`ChatView`)  
- **Document Editor modal (Review)** — `DocumentEditorModal.tsx` + `legalReviewHighlight.ts`  
  - Dusty-black chrome; authorities **blue**, prior filings **green**  
  - No multi-mode style dropdown  
- **GET analytics** supports `?documentId=` — `backend/src/routes/index.ts`  

### 2. Naming & section copy
- Sidebar: **Analytics → Case Map**; clearer sublabels for Tabular / Workflows  
- Full-width definitions via `SectionIntro.tsx` on: Projects, Workflows, Tabular, Case Law, Statutes  
- Council / Case Map intros widened (`max-w-none`)  
- **Coming Soon** in **left sidebar** (and Case Map footer `#coming-soon`):  
  1. Word / WordPerfect plugin (mailto early access)  
  2. Judicial Analytics  
  3. Verifier  
  4. Wingman  
- Word plugin banner **removed from Council** (moved to Coming Soon)  

### 3. Typography
- Site-wide **Helvetica Neue** (local OTFs in `public/fonts/helvetica-neue/`)  
- Weight remap: bold/semibold → thin/elegant (see `globals.css`)  
- Utility `.label-caps` for section labels  
- Council shouting labels softened  

### 4. LAN / API base (critical for multi-device)
- **`getApiBase()`** — `frontend/src/app/lib/apiBase.ts`  
  - Uses page hostname + `:3001` when `NEXT_PUBLIC_API_BASE_URL` empty  
  - Wired through `mikeApi`, Case Law, Council, Case Map, hooks, etc.  
  - **Bug fixed:** many files hard-coded `localhost:3001` → phones hit their own loopback  

### 5. Scanned PDF / hollow extract
- **Heppner** PACER file is RICOH **image-only** — only docket stamps extract  
- **`isSparseLegalText()`** refuses extract when body is stamps-only — `caseIntelligence.ts`  
- Opinion-aware extraction prompt (holdings mapping for opinions/orders)  
- Card shows **“No body text”** amber copy instead of empty columns  
- **Good demo PDF:**  
  `…/caselaw/ASSINI v. Hayward, 2026 NY Slip Op 26086 - NY_ Supreme Court 2026 - Google Scholar.pdf`  
  (Google Scholar text PDF, ~2k words, parties/judge/cites/OpenAI subpoena issues)  

### 6. Composer UX after upload
- InitialView **scrolls** when extract card grows  
- Extract cards max-height ~40vh + internal scroll  
- Textarea high-contrast text + focus after attach  
- ChatView bottom gradient / pointer-events fixed for dark mode  

---

## Environment / creds (as of handoff)

| | |
|---|---|
| Backend | `cd backend && npm run dev` → **3001** |
| Frontend | `cd frontend && npm run dev` → **3000** |
| Your login | `aray.aaron@gmail.com` / `Kingsfield-Reset-2026` (temp — change it) |
| Demo guest | `demo@kingsfield.app` / `KingsfieldDemo-2026` |
| Demo mode | `NEXT_PUBLIC_DEMO_MODE=false` in `frontend/.env.local` (login wall on) |
| API base env | `NEXT_PUBLIC_API_BASE_URL=` **blank** (derive from hostname) |
| Supabase | `fzexglkmpoyxtkdiwelm` |
| LAN IP (this house, may change) | often `192.168.1.218` — check `ipconfig getifaddr en0` |
| Share URL when servers up | `http://<LAN-IP>:3000` (**must include :3000**) |
| Servers at handoff | **STOPPED** (kill ports 3000/3001) |

Backend CORS already allows private LAN origins on port 3000 (`LAN_ORIGIN` in `backend/src/index.ts`).

---

## Git / commit state
- Session work was done on local tree; **do not assume pushed**.  
- Run `git status` before next session. Key new/touched areas:  
  - `backend/src/lib/caseIntelligence.ts`, `routes/documents.ts`, `routes/index.ts`  
  - `frontend/src/app/lib/apiBase.ts`, `caseIntelligenceApi.ts`, `legalReviewHighlight.ts`  
  - `frontend/src/app/components/assistant/*`, `shared/AppSidebar.tsx`, `shared/SectionIntro.tsx`, `shared/DocumentEditorModal.tsx`  
  - pages: analytics, council, case-law, legislation, tabular-reviews  
  - `frontend/src/app/globals.css`, `layout.tsx`  

---

## Dual retrieval (added later same calendar day)

**Both engines are wired — not either/or.**

| Engine | Template | Backend | UI |
|---|---|---|---|
| **URL Context** | chat-with-docs | `POST /pro-se/chat-with-docs`, `/pro-se/url-suggestions` | Statutes: multi-URL source pack (≤20), suggest Qs, labeled answers |
| **File Search** | ask-the-manual | `POST /pro-se/manual-store`, `/upload`, `/ask-manual`, `/manual-suggestions` | Assistant: **DocBinderPanel** after attach — Index docs → ask + grounding |

- Core Gemini helpers: `backend/src/lib/proSeGemini.ts`  
- Allowlisted official hosts expanded in `statuteScanner.ts`  
- Answers labeled via `SourceLabeledAnswer` (engine + URLs / grounding count)  
- Case citations still run four-gate; File Search/URL are labeled sources not “verified case law”

---

## Open / next when returning

1. **OCR / vision extract** for image-only PACER PDFs (optional product)  
2. Free-form drafting editor (beyond Review viewer)  
3. Judicial Analytics product (portfolio graph) — Coming Soon only  
4. CourtListener daily cap still a **beta blocker** (see decisions 2026-07-05)  
5. Commit/push this session’s uncommitted UI + extract work  
6. Re-test Assini upload end-to-end after restart  
7. Change temp password when convenient  
8. Persist File Search store id on **projects** table (today: ephemeral per Index click)  
9. Live-test Gemini File Search upload with real `GEMINI_API_KEY`

---

## Quick smoke after restart

```bash
cd backend && npm run dev   # 3001
cd frontend && npm run dev  # 3000
# open http://localhost:3000
# login → Assistant → upload Assini PDF → extract card populates → type in ask bar → send
```

Avoid re-uploading **Heppner** scan as a success demo; use it only to show scan failure UX.
