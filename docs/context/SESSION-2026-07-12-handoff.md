# Session Handoff — 2026-07-12

Read this first, then `current-state.md`. This session was mostly about getting
the demo suite runnable, fixing the Video Analyzer, and enabling cross-device /
no-login demo access.

---

## HOW TO RUN (the thing that bit us repeatedly)

**Kingsfield is TWO servers — BOTH must run:**
- Frontend → port **3000** (launch config `kingsfield-frontend`)
- Backend → port **3001** (launch config `kingsfield-backend`)

If only the frontend is up, Case Law / Council / Projects / chat all fail with
"backend search endpoint unavailable" or similar. That error is NOT a
CourtListener problem — it means the backend (3001) is down.

**All launch configs (`.claude/launch.json`), each on its own port:**
| App | Port | Login? |
|---|---|---|
| kingsfield-frontend | 3000 | yes (unless demo mode) |
| kingsfield-backend | 3001 | — |
| face-mood-tracker | 5173 | no |
| wingman-pwa | 5174 | no |
| video-analyzer | 5175 | no |

Hub page with clickable links: **`KF_LINKS.html`** (repo root). Open it in a
REAL browser via `open KF_LINKS.html` (the in-app preview pane blocks
cross-port localhost links). Links open in new tabs.

**Currently running at end of session:** kingsfield-frontend (3000) +
kingsfield-backend (3001). Others stopped.

---

## CROSS-DEVICE (same Wi-Fi) — DONE & COMMITTED

Someone on the same Wi-Fi opens the app at the Mac's LAN IP, not localhost.
- Mac LAN IP this session: **192.168.1.218** (can change on Wi-Fi reconnect).
- Mac firewall is OFF, so LAN reachable.
- Share links: `http://192.168.1.218:3000` (Kingsfield), `:5175` (Video
  Analyzer), `:5173` (Face Mood), `:5174` (Wingman).
- Backend CORS now allows private-LAN origins on :3000; frontend derives the
  backend URL from the page host (so no rebuild needed per device).
- **Committed:** kingsfield `3c2bf16`.

## NO-LOGIN DEMO MODE — DONE & COMMITTED (currently OFF)

Auto-signs-in as a throwaway demo account so guests skip the login screen.
- Toggle in `frontend/.env.local`: `NEXT_PUBLIC_DEMO_MODE=true|false`.
  **Currently `false`** (normal login wall active — set this way on purpose so
  fresh logins work).
- Demo account already created in Supabase: `demo@kingsfield.app` /
  `KingsfieldDemo-2026` (email-confirmed, MFA off). Recreate/reset with
  `node backend/scripts/create-demo-user.mjs`.
- To enable guest mode: set `NEXT_PUBLIC_DEMO_MODE=true`, restart frontend.
- **Committed:** kingsfield `3c2bf16` (AuthContext, create-demo-user.mjs,
  `.env.local.example` docs). Verified working (fresh browser → auto-lands in
  /assistant as Demo User, backend calls authenticated).

---

## VIDEO ANALYZER (`video-analyzer4/`) — FIXED & COMMITTED

Cloned from github.com/Kandy22/video-analyzer4. Fixed the real bugs Gemini kept
missing:
- Port respects `PORT` env (runs on 5175), HMR socket disabled in middleware
  mode (killed the WebSocket errors), body limit raised (413 only ever happened
  in the AI Studio sandbox, not locally).
- **Key Moments now returns EXACT VERBATIM QUOTES** (was paraphrased
  summaries) — prompt fix in `modes.ts`.
- Robust function-call dispatch so a run never silently renders empty.
- **Committed:** video-analyzer4 `8ffa5d1`. Full writeup in that repo's
  `FIXES_AND_NOTES.md`.
- Verified on a 28:51 courtroom video: 396-line transcript, 23 verbatim key
  moments.
- NOT committed there: 3 stray `.ipynb` notebooks (left alone).
- Still TODO (user asked, deferred): collapse the right panel; replace the
  placeholder stress/sentiment/oscilloscope widgets with the Face-Mood emotion
  gradient chart.

---

## OTHER FIXES THIS SESSION — **UNCOMMITTED** (protect these!)

These are done and tested but NOT yet committed. A crash loses them.

1. **Wingman session-duration crash** — `wingman-in-your-ear/wingman_live.py`:
   added `session_resumption` + reconnect loop so it survives the ~10-min Gemini
   Live cap instead of crashing on the GoAway/1008. Verified connects.
2. **Verifier pipeline** (`verifier/judicial-intel/pipeline/`):
   - `diarize.py` → model `gemini-3-flash-preview` + explicit responseSchema
     (matches the echoscript template). Ran clean on fl_2dca `cwPVWKqwg4A`.
   - `analyze_posture.py` → model `gemini-robotics-er-1.6-preview` (was 1.5).
   - `download.py` → fixed `already_done()` so `--with-video` actually
     re-downloads video (was skipping because audio already existed). A real
     171MB video is now downloaded for `cwPVWKqwg4A`.
   - Note: **mediapipe still not installable** on this Python 3.14 (no wheel),
     so `analyze_signals.py` blendshape path falls back to opencv-only. The
     real face-blendshape work is browser-side (Face Mood Tracker app).
3. **Skeptic veto enforcement** — `backend/src/routes/proSe.ts`: vetoed answers
   now withheld (not just flagged); `/pro-se/chat-with-docs` enforces the
   domain allowlist; `chatWithUrlContext` (`proSeGemini.ts`) restored the
   `safetySettings` block from the source template. Frontend legislation page
   shows a "withheld" state. (Typechecked + browser-verified earlier.)
4. **Face Mood Tracker STOP MUSIC** — `~/FACE-MOOD-TRACKER/face-mood-tracker-code/src/App.tsx`
   (SEPARATE repo): added an always-visible red STOP MUSIC button (Vision mode
   had NO way to stop the audio — this is why the song "wouldn't stop"). The
   old stop button only existed in Sonic mode. Verified the button appears &
   the stop handler is the proven `synthEngine.stop()`.

Plus the pre-existing large dirty tree from before this session (business/
kingsfield dedup deletion, loose media, etc.) — leave that for a deliberate
cleanup, don't `git add -A`.

---

## DIAGNOSED (no code change)

- **CourtListener limits:** free tier is hard-capped 5/min · 50/hr · 125/day
  (policy changed 2026-05-07 — email requests no longer raise it). Self-service
  raise = **Free Law Project membership** (paid, instant, no form). Free
  alternative = CourtListener **bulk data** download + local cache. Token is
  fine (`COURTLISTENER_TOKEN`, verified 200).
- **Legislation "jurisdiction shows webpages not data":** BY DESIGN — the state
  / federal cards are external links (Justia, eCFR, congress.gov). To show
  actual statute text in-app, build a Legislation in-app reader (the "Pro Se
  Ask" box on that page already has the URL-context + allowlist machinery to do
  it). NOT built — this is the next real feature if wanted.

---

## SUGGESTED NEXT STEPS

1. **Commit the uncommitted fixes above** (Wingman, verifier, pro-se veto, Face
   Mood stop button) so they're safe — group into logical commits, do NOT
   `git add -A`.
2. Build the Legislation in-app reader (jurisdiction → real statute text).
3. Video Analyzer right-panel: collapse + Face-Mood emotion gradient swap.
4. Decide on CourtListener membership vs bulk-data for the demo rate cap.
