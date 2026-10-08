# Kingsfield Lawfare — Current State
*Last updated: 2026-10-08 (route auth fixed on `feature/local-sqlite-gate1`, awaiting cherry-pick to main; project-ownership gap open; tabular chat added to merge blockers)*

---

## 🚨 URGENT, fix on `main` independently of any branch: unauthenticated model routes are live

**Status 2026-10-07: fixed on `feature/local-sqlite-gate1`, NOT yet on `main`.** Two standalone commits, meant to be cherry-picked to `main`:
- `1aab2e4`: `requireAuth` on `/council/detect`, `/council`, `/council/:id`, `/:id/html`, `/:id/markdown` and `/crew/chat`.
- `bbca61d`: `requireAuth` on `/research/case-law`, `/research/courts`, `/projects/:id/docket/watch`, `/projects/:id/docket/checks`, `/projects/:id/ip/renewal/check`, `/ip/renewal/checks` and `/ip/assets`. `/docket/sweep` and `/ip/renewal/sweep` now fail closed: they return 401 unless `SWEEP_SECRET` is set and `x-sweep-secret` matches it. `SWEEP_SECRET` is not in `backend/.env.example`, and any external cron job needs it.

The frontend's `/research/courts` callers (`JurisdictionSelector.tsx`, `CourtPicker.tsx`) must send the Bearer token too, or they fall back to their small static court lists. That fix is a separate frontend change, and it must go to `main` with `bbca61d`.

The original finding is kept below for the record.

**`POST /api/crew/chat` is unauthenticated and live on `main` today.** `backend/src/routes/index.ts:349` (`r.post('/crew/chat', async (req, res) => …)`) has no `requireAuth`, and `backend/src/index.ts:127` mounts the router at `/api`. Anyone who can reach the backend can burn our model API keys and get Crew output whose citations never pass Gate 1. The header comment at `routes/index.ts:11-12` claims the hallucination guard is applied; it is not. The frontend does not call this route (decisions.md 2026-07-03), so removing it or adding `requireAuth` breaks nothing user-facing.

Found while verifying, same file on `main`, also without `requireAuth`: `POST /api/council` (11 model calls per session across Claude + Gemini, output unverified), `GET /api/council/:id`, `/:id/html` and `/:id/markdown` (serve stored council sessions by id), and `GET /api/research/case-law` and `/research/courts` (proxy CourtListener with our token).

**Fix:** remove the demo routes or put `requireAuth` on every one of them, in its own change on `main`. Do not wait for `feature/local-sqlite-gate1`; that branch is blocked on other things.

## OPEN (found 2026-10-07, not fixed): project routes check login, not ownership

`requireAuth` only proves the caller is logged in. In `backend/src/routes/index.ts`:
- `POST /projects/:id/docket/watch`, `GET /projects/:id/docket/checks` and `POST /projects/:id/ip/renewal/check` load the project by `:id` with the service-role Supabase client (`createServerSupabase()`, which bypasses RLS), and never check that it belongs to the caller. Any logged-in user can read another user's docket checks, or run the watcher (CourtListener + LLM + email) on another user's matter.
- `GET /ip/renewal/checks` returns the latest portfolio-wide runs, and `GET /ip/assets` returns every user's active IP assets (optionally filtered by any `?projectId=`). Neither is scoped to the caller.

Fix it in its own task: scope each query to the caller's projects (or return 404 when they don't own the project), and scope or remove the two portfolio-wide reads.

## OPEN (found 2026-10-07, not fixed): chat tools write model text into documents before Gate 1

The chat-route buffering (W2, Step 1/1b) only governs what reaches the chat stream and `chat_messages`. Chat tools write model text into the user's documents *during* `runLLMStream`, before Gate 1 runs on anything, and nothing reverts them when the reply is later withheld. All in `backend/src/lib/chatTools.ts`:
- **`generate_docx`** (tool def ~355; dispatch ~3531; `generateDocx()` ~866): builds a .docx from model-written content, `uploadFile()` to storage (~1298), inserts `documents` (~1311) and `document_versions` (~1327) rows. Filename comes from the model's `title`.
- **`edit_document`** (tool def ~427; dispatch ~3111; `runEditDocument()` ~1392): applies model-written replacement text to the user's document, `uploadFile()` the new bytes (~1467/~1483), writes `document_versions` (~1473-1520), `document_edits` rows with the model's `replace`/`reason` text (~1552), and updates `documents` (~1563).
- **`replicate_document`** (tool def ~213; dispatch ~3273): copies an existing user document under a model-chosen `new_filename`; inserts `documents` (~3361), `uploadFile()` (~3392/~3397), `document_versions` (~3418). Content is the user's own; only the filenames are model text.

Effect: a vetoed or fabricated citation can be stored in a generated or edited .docx (and in `document_edits`) even when the chat reply that announced it was withheld. Fix in its own task: run Gate 1 over the content before the write (fail closed: refuse the tool call), or stage writes and commit them only after the reply passes. `chatTools.ts` is shared with `tabular.ts`, so check that path too.

## OPEN (found 2026-10-08, not fixed): model-written chat titles are saved with no Gate 1

`POST /chat/:chatId/generate-title` in `backend/src/routes/chat.ts` (~397-415) asks the user's title model for a 3-6 word title from the first message (`completeText`, ~402), normalizes it, saves it to `chats.title` (~410) and returns it in the JSON. None of it goes through Gate 1, so a title like "Doe v. Roe, 999 So. 3d 999" would be stored and shown in the sidebar. The fallback title on the success path of `chat.ts`/`projectChat.ts` (`lastUser.content.slice(0, 120)`) is the user's own text, not model text. Fix in its own task: run the title through Gate 1 and fall back to the fixed title on any veto or error.

## OPEN (found 2026-10-08, not fixed): the frontend shows no words for a live failed reply

When a chat reply fails while streaming, the backend sends `{type:'error', message: GENERIC_ERROR_MESSAGE}` and `[DONE]`. `useAssistantChat.ts` (~401-420) stores it as an `error` event, but `AssistantMessage.tsx:1707` (`isRenderableEvent`) never renders `error` events: the message only turns the status icon red, with no text. After a reload the saved marker's `content` event ("The reply failed before it could be completed.") does show. Fix in the frontend: render the error event's fixed message as body text (it's always the generic string now).

## OPEN (found 2026-10-08, low risk, not fixed): unspaced citation strings survive the chat guard's scrub

In `backend/src/middleware/hallucination_guard.ts`, `scrubEvent()` (~499) keeps any string that matches `SSE_IDENT` (`/^[A-Za-z0-9_.:-]{1,64}$/`, ~81). It's applied to `courtlistener_verify_citations`, to `courtlistener_read_case` entries with no verified verdict, to `courtlistener_get_cases`, and to `mcp_tool_result`/`mcp_tool_call` when flagged (`scrubOnFlag`, ~693), including inside withheld replies. A model- or MCP-supplied unspaced string such as `999So.3d999` passes the scrub and reaches the client and `chat_messages`. Gate 1 likely wouldn't read it as a citation, and it needs a field the model or an MCP server controls, so the risk is low. Fix in its own task: run scrubbed strings through the reporter-cite check, or keep only numbers, booleans and known-format ids (UUIDs, cluster ids). Related, left as is by decision (B6, 2026-10-08): `tool_call_start`/`mcp_tool_start` send an identifier-shaped tool `name` live before Gate 1.

## ⭐ 2026-10-06 — JEV CPU router wired (stub-tested); adversary signoff VERIFIED

Task `[module] JEV CPU router` (id `jev-cpu-router`). Signoff `.claude/signoffs/jev-cpu-router.signoff` = `5e0d2e40…`, verified with `require_adversary_signoff.py` (exit 0, 193 s). Adversary suite: 369 tests, 0 failures, 0 errors, 5 documented skips, 192 s. Router suite: 169 tests, about 10 s. The digest is whole-tree, so it supersedes the `gate1-draft-mode` signoff (that file no longer matches, which is expected). All tests use a stub model; no real GGUF has been loaded. Suite headroom against the hook's 240 s timeout is about 45 s, and the Gate 1 tests (about 190 s) dominate.

Built: exact-option full-sequence log-likelihood routing (no generation), absolute-mass floors, a tokenization boundary check, worker timeouts with a circuit breaker, a deterministic `pipeline.gate1.check_text` citation pre-check in `route()` (covers Von too), `calibrated` forced False (`CALIBRATION_RECORDED`), and a calibration harness that measures through `route()`.

### Router task definition (kept for reference)

Definition of done, per user instructions on 2026-10-06 (see decisions.md):
- Routing runs on local llama.cpp under CLAUDE.md Constraint C. Any output that is not exactly one allowed option, any error or timeout, a missing model, or low confidence routes to `direct_db`. Today `choice()` substring-matches and defaults to `options[0]`, which violates C.
- Confidence comes from llama.cpp token log-probabilities over the allowed options, not from a model-generated score. It is uncalibrated until measured on labeled (contrastive) pairs, and the threshold stays a placeholder until then.
- The adversary reviews `router/jev_cpu_inference.py` before signoff. It is in the Gate 1 digest but was never reviewed.
- A fast router test target under 30 s (stub model). The full signoff suite stays under 5 min with at most 4 processes (Constraint E).
- The user provides `llama-cpp-python` and the GGUF model. The agents' hooks block installs and downloads.
- Round 2 (2026-10-06): an absolute-mass floor (placeholder, uncalibrated) and a deterministic eyecite citation pre-check that routes to `direct_db`.
- **Before production (REQUIRED): one-time real-GGUF smoke test.** Required checks:
  - **F3 (KV-cache rewind):** each option score after `llm.n_tokens = n_prompt` equals a fresh `reset()` + `eval(prompt + option)` score, and the `logits_all=True` rows are the per-position log-prob rows the code assumes.
  - **F4 (tokenization boundary):** the real tokenizer passes the boundary check (`tokenize(prompt + " " + opt)` == `tokenize(prompt)` + `tokenize(" " + opt, no BOS)`). A SentencePiece-style dummy prefix space would fail it on every query and silently turn the router into always-`direct_db`. If it fails, fix the boundary handling before production; don't disable the check.
- **Known router risks, accepted and recorded (adversary review 2026-10-06; none bypasses Constraint C or Gate 1):**
  - **F5:** the circuit breaker is permanent per process. One query past the 15 s deadline, or a cached failed load (e.g. OOM), disables local routing until `reset_shared_router()` or a restart. That fails closed, but it's an availability risk. A reset while a worker is truly hung leaves the old context alive (memory doubles), so restart instead.
  - **F7:** the mass floors (`CHOICE_MASS_FLOOR=1e-2`, `NOUL_MASS_FLOOR=5e-2`) are placeholders. A 1% floor still admits a model with 99% of its mass elsewhere. Tune them from real-model mass distributions during calibration.
  - **F8:** each `route()` is 2 prompts with 5 option evals plus the boundary-check tokenizations. Latency on this Intel Mac is unmeasured.
  - **F9:** queries up to 2,000 chars are accepted, but with a ~110-token prompt in a 512-token `n_ctx`, long queries silently fail closed to `direct_db`.
  - **F10:** the raw query is interpolated into the prompt, so text like newline + `Route:` can steer routing. That affects routing quality only; Gate 1 still runs.
  - **F11:** calibration statistics use Wilson lower bounds over an 11-point grid with no multiple-comparison correction, and labels are author-written with no independent labeler. The set (~56 non-gated items) must grow about 4x past `MIN_RELIABLE_N=200` before any threshold can be suggested.

## ⭐ 2026-10-06 — Gate 1 draft mode built and wired on `feature/local-sqlite-gate1`; adversary signoff VERIFIED

Task `[module] Gate 1 draft mode` (id `gate1-draft-mode`). Nothing committed. Signoff `.claude/signoffs/gate1-draft-mode.signoff` = `dea18c05…` (tree digest now also covers `pipeline.ts` and `researcher.ts`). Verified 2026-10-06 by running `require_adversary_signoff.py` with the task payload: exit 0, 200 s. Adversary suite: 214 tests, 0 failures, 0 errors, 5 documented skips (W3 + findings 1-3), 189 s. Builder suite: 154 pass. Any edit to a digested file invalidates the signoff. Directional decisions: decisions.md 2026-10-05 "Gate 1 draft mode and backend wiring" and 2026-10-06.

- **Built (backend_builder):** `localGate1Text()` in `local_sqlite_gate.ts`, an async child-process wrapper around `check_text()` in `pipeline/gate1.py` (draft on stdin, max 4 concurrent children, slot released on child `close`, `gate_busy` veto on queue wait, every failure resolves to one veto). Short cites / Id. / supra resolved via eyecite with name and pin checks; residue detector vetoes Florida-looking tokens no result covers. 145 builder tests pass.
- **Wired (lead):** `verifyCitation`, `verifyDraft` and `confirmExistence()` in `pipeline.ts` run local Gate 1 before the cache and any CourtListener call; a local pass skips `citationLookup()`; only an explicit `fall_through` reaches CourtListener. `researcher.ts` uses `confirmExistence()`. `tsc --noEmit` clean. `tree_digest.py` now also covers `pipeline.ts` and `researcher.ts` (user edit).
- **Resolved before signoff** (the adversary first blocked on these, 2026-10-06):
  1. Finding 4, in-module, FIXED: `_clean_draft` in `gate1.py` discards HTML attribute values, comment text and markdown link/image titles, which the frontend renders (`react-markdown` + `rehype-raw`). They are now kept and scanned as extra segments.
  2. The suite was too heavy for this Intel Mac (14-17 min, up to 16 Python processes). FIXED: concurrency/exact-cap tests use 6 cheap stub children with deterministic release points, the hostile drafts are about 10x smaller with the 10 s budget kept, and a scaling test was added. A full run is now about 190 s.
  3. `require_adversary_signoff.py` runs the suite with a 240 s timeout (hook limit 300 s in settings.json). The suite now fits (200 s), but with little headroom.

### Merge-to-main blockers for `feature/local-sqlite-gate1`
1. `kingsfield_florida.db` built and populated (without it every Florida cite vetoes `db_unavailable`).
2. Chat follow-up task: W2 (tokens streamed before Gate 1; stream-vs-buffer is the user's decision), W3 (verdicts not persisted with the chat message), W4 (aborted/errored streams saved unverified).
3. Same follow-up: findings 1-3. `/api/crew/chat` and `/api/council` release model text with no Gate 1, and `runResearcher`'s holding/relevance notes are returned unchecked. The adversary's tests for these are skipped with the decisions.md reason, bodies intact. (The auth exposure of those routes is the separate URGENT item above.)
   - **Step 4 to-do (logged 2026-10-08):** the adversary adds a real-gate test where a period-less reporter cite (e.g. `999 So 3d 999`) appears in the chat reply text, with CourtListener stubbed to "not found"; the reply must be withheld. Reason: in the 2026-10-08 signoff-tier run, a real-gate probe on the filename `Doe v Roe 999 So 3d 999 Fla 2015 Memo.docx` did not veto locally; it fell through toward the cache/CourtListener path (blocked by the harness, so it errored and failed closed). Production behaviour for that form is unverified.
4. **Tabular review chat streams and saves unverified model text (found 2026-10-08 by the adversary, B2; its own task, not part of chat-route-verify).** `backend/src/routes/tabular.ts`:
   - The tabular chat route (~1348-1363) calls `runLLMStream` with the raw `res.write`: no buffering writer, no Gate 1, no `finalizeHeldOutput`. Tokens reach the browser as generated, and the reply is saved unverified (~1365-1374, ~1413-1422, ~1449-1456).
   - `POST /:reviewId/generate` (~933-952) streams generated cell content to the client raw, with no Gate 1.
   Fix the same way as `chat.ts`/`projectChat.ts` (buffering writer, `finalizeHeldOutput`, save what was sent). `tabular.ts` is outside the backend_builder's write paths today, so the task needs a hook change. The adversary's test for this is skipped with this reason, body intact.

### Known, accepted
Abbreviated pin ranges (`790-91`) over-veto; `ambiguous_short_cite` over-veto; no per-user fairness in the draft-gate queue; a killed child that never emits `close` keeps its slot (fails closed as `gate_busy`); `verifyDraft` never runs Gate 2 for draft authorities (pre-existing); `/pro-se/url-suggestions` and `/manual-suggestions` return model text unchecked (low). The draft cleaner doesn't scan URL-type attributes (`href`, `src`, `srcset`) or inline `style`, so a citation rendered inside a `data:image/svg+xml` URI's `<text>` would go unscanned (low).

## ⭐ 2026-10-05 — Local SQLite Gate 1 and System One router built; adversary signed off; NOT wired

**`[module] Gate 1 and Local Router Setup` is done.** All of it is uncommitted and untracked (`db/`, `pipeline/`, `router/`, `backend/src/verification/local_sqlite_gate.ts`). Built by the cascade agents (backend_builder, decision_router, adversary) under the `.claude/hooks/` path guards.

- `db/build_sqlite_index.py` ingests CourtListener bulk CSVs (citations, opinion-clusters, dockets, optional CAP page-bounds) into `kingsfield_florida.db`. It is **not run yet**: `/Volumes/Kingsfield_Corpus` isn't mounted and no DB exists. Florida court ids are `fla` and `fladistctapp` only.
- **Schema:** `citation_index` has a `section` column for Fla. L. Weekly division letters, B-tree `idx_citation_rvp(reporter, volume, page, section)`. `caselaw_opinion` and `caselaw_analysis` are separate tables.
- **Gates:** `pipeline/gate1.py` is the Python reference gate (eyecite). `local_sqlite_gate.ts` exports a synchronous `localGate1()` (`node:sqlite`, read-only, Python child-process fallback). The two have verdict parity: `pass` / `veto` / `fall_through`.
- `router/system_one_client.py` is the Choice/Noul/Score stub client for `/v1/systemone`. `direct_db` is the fallback on no URL, any error, or confidence below 0.80. The Von wire format is assumed and stubbed, and the Noul cutoffs (0.20 / 0.80) are unvalidated.
- **Tests:** the adversary's bypass suite `pipeline/tests/` has 105 tests, all OK, with 3 wiring-conditional skips. Builder tests are `pipeline/builder_tests/` (54) and router tests are `router/tests/` (27). `tsc --noEmit` is clean. The signoff is at `.claude/signoffs/gate1-local-router-setup.signoff` (digest `0abe54a2…`). Any edit to the reviewed files invalidates it.

### Open, in priority order
1. **Wire `localGate1` into `pipeline.ts` ahead of `citationLookup()`** (Constraint D), after a separate review. Then have the adversary re-run, which un-skips the 3 ordering tests.
2. **`backend/src/crew/researcher.ts:123` is an open Gate 1 bypass.** LLM-proposed cites go straight to `citationLookup()` and become `VerifiedAuthority`. It must route through the local gate when wiring lands, or the bypass test fails. `caseIntelligence.ts:217` (cite counts only) is allowlisted. Open UX question: a non-null cite_count implies "resolved".
3. Run the corpus build once the volume is mounted, then load-test lookup latency and the slow-DB timeout (only a locked DB is tested).
4. **Untested:** exposure bias (no train/eval set exists), borderline caption abbreviations, a well-formed Von response, and other model-cite output flows (chat, council) beyond `citationLookup(` call sites.

## ⭐ 2026-09-19 — Judicial intel: FL 2DCA/6DCA oral arguments scored with Jev; offer catalog implemented

**Nothing is on fire.** This session's work is on branch `judicial-intel-oa-panel-2026-09-19` (PR to `main`); it stages additions and modifications only — the 345 working-tree deletions (wingman data-info, business/, old `verifier/judicial-intel` path) were deliberately NOT committed and need the user's eyes.

### NEW: captions-track pipeline in `verifier/judicial-intel-analytics/pipeline/`

`pull_captions.py` → `build_transcripts.py` → `run_oa_panel.py` → `enrich_flcourts.py` (+ `enrich_dockets.py` secondary, `validate_roles.py`). Full docs in that folder's `README.md`; sources in `DATA-SOURCES.md`.

- **1,438 2DCA clips** with captions + metadata (5 have no captions), **98 6DCA** clips. Live-stream tabs excluded (multi-case, exceed Jev's state budget).
- **1,428 transcripts scored** by `typesafe/jev-1.13` via OpenRouter, 15-question panel, **$0.465**, 4 s at 12 threads. 9-video hand-checked validation first.
- **Ground truth from the Florida courts' own opinion JSON API** (`flcourts-media.flcourts.gov/_search/opinions/`, the endpoint Juriscraper wraps): 23,659 2DCA decisions 2016–2026 incl. PCAs; **1,236/1,438 videos matched**; 1,204 opinion PDFs parsed for panel / trial judge / counsel. CourtListener demoted to secondary — the token is throttled to **100 req/hour**.
- **Findings (n=1,097 argued cases with decisions):** argued cases affirm 74% (court-wide 86%). `ruling_lean` raw 64% — below baseline — but confidence is monotonic (≥0.7 → 90%) and the Python-composed **skepticism gap** is the signal: ≥+1 → 95% affirmed (n=208), ≤−1 → 44%; inside gap 0 a confident `reverse` lean is right 77% (n=22). Two-thirds of cases fall in the abstain bin. Behavioral nouls describe, don't predict. 13–21% of score rows are bimodal. Replicates on 6DCA.
- **Pass-1 speaker roles** are heuristic (fuzzy intro anchors + Viterbi): 86.8% BENCH/COUNSEL on a hand-labeled video. The existing Gemini `diarize.py` output is chunk-local and **not usable as ground truth**.

### NEW: offer catalog implemented — `verifier/new-kingsfield-judicial-intel-categories/`

`src/value_types.py`, `src/sources.py`, `src/build_snapshots.py`, `src/voting.py`. **9 of 29 facts populated** for 2DCA (F12 F13 F17 F19 F21 F22 F25 F26 F29): court snapshot, 17 appellate judges, 81 trial-judge appellate trails, 22 counsel rows (floor n=5), 1,416 F26 cards. `taxonomy/COVERAGE-fl_2dca.md`. Producers are arithmetic only.

### Cleanup done
Mock `Case_*` stub folders (iCloud, 250) trashed; GDrive `Florida_Court_Archive` (1,780 stubs) trashed by user. Stale `verifier/judicial-intel` paths fixed in config/manifest/README/HANDOFF. `index_channel.py` no longer drops video ids starting with `UC`.

### Open, in priority order
1. **Review the 345 unstaged deletions** and commit or restore them (this PR does not touch them).
2. **Mike upstream sync** — `Kandy22/mike` is a current copy of upstream (pushed 2026-09-19); Kingsfield forked from a much older Mike. 600+ upstream changes need a deliberate merge, not a sync.
3. **Gemini pass 2 for roles** — rewrite `diarize.py` for whole-file audio with a role-constrained schema; validate against `data/fl_2dca/transcripts/_truth_eLU5je2C12I.json`.
4. Whisper for the 5 caption-less videos; Phase-2 per-turn rolling scorer + biometric join (`mike` / `video-analyzer4` lineage).
5. Colorado OA video is on `cojudicial.ompnetwork.org`, not YouTube — separate ingestion.
6. CourtListener membership if the API is needed above 100/hour; otherwise flcourts covers Florida.

---

## ⭐ 2026-07-27 — Hallucination registry built; published benchmark corrected

**Nothing is on fire.** Production Gate 1 was checked and is sound (see below). All work this session is **uncommitted** on `main` — 216 changed files in the root repo, of which the relevant ones are `verifier/` (23) and the new `hallucination-registry/`. Nothing pushed.

### NEW: `hallucination-registry/` — normalization layer over the Charlotin AI-hallucination case database

Turns his flat 18-column CSV into two queryable tables. Stdlib only, deterministic, source SHA-256 in `manifest.json`.

- `normalize.py` → `out/incidents.csv` (**1,810 cases, 1,251 US**) + `out/incident_items.csv` (**5,406 items, 3,869 US**) + `qa_unmapped.csv` + `report.md`
- `schema.sql` — Postgres/Supabase DDL, with enrichment columns stubbed and NULL (`judge_name`, `docket_number`, `case_citation`, `cl_opinion_id`, `order_sha256`, `sanctioning_authority`, `bar_referral_disposition`, `appellate_history`)
- Coverage: court mapping **95.8% high confidence** (2 unmapped of 1,251), **875 CourtListener court IDs resolved**, outcomes **1,052/1,216 recorded mapped (86.5%)**
- Traps handled and unit-tested (20/20): `CA California` = state Court of Appeal vs `CA 5th Cir.` = federal circuit; `D.C. New Jersey` = *District Court*, not DC; **New York's "Supreme Court" is a TRIAL court** and is classified `state_trial` — getting this wrong inverts any NY analysis
- `monetary_is_placeholder` flags the 22 rows where upstream uses a bare `1` to mean "sanctioned, amount unknown". Guarded, real US figures are n=160, **median $2,000, max $110,204**
- Three AI-specific remedy codes coined that upstream has no field for: `authority_production_ordered`, `ai_certification_ordered`, `client_notification_ordered` (18 US cases — small but the seed of the standing-order product)

**NOT done:** nothing loaded into Supabase (the MCP is connected and could), no enrichment run, no intake pipeline, `kingsfield_network_v2.html` still shows stale static numbers.

### FIXED: `verifier/` benchmark had 87 groundings scored against the wrong opinion

The old direct-REST resolver mapped historical citations to 2025–26 CourtListener clusters. Quarantined via new `quarantine_bad_grounding.py` (reversible; backup + `quarantine_report.json`). **Real grounding is 55/1,979 (2.8%), of which 49 (89.1%) verified** — not the 139 (7.0%) previously claimed. `CITATION_BENCHMARK.md` and `benchmark_summary.md` rewritten as v0.2 with the correction visible. Also corrected: "3-way unanimous 33%" (wrong denominator; 37.1% of the 1,780 actually scored), "200 human labels" (only 139 usable — 61 are `unsure`), and a **backwards Gemini verdict row** that had led to the opposite conclusion.

**✅ Production is NOT affected.** `backend/src/verification/pipeline.ts` uses `citationLookup()` (CourtListener's Citation Lookup API — parses volume/reporter/page, filters `status === 'matched'`, fails closed). Different and correct mechanism. Do not refactor it.

### PUBLISHED: HF dataset corrected in place

`Kingsfield-Lawfare/legal-citation-benchmark` (public, CC BY 4.0, 146 downloads) had **every row duplicated** — both JSON files sat in the repo root and the loader concatenated them (~3,958 rows for 1,979 entries). Fixed with an explicit `configs:`/`data_files:` block pinning the split to `results_full.json`. Card rewritten as v0.2, leading with the correction, and now carries a **verified worked example**: entry `idx: 1`'s Claude rationale cites two fabricated cases ("Los Alamos Grazing" returns zero results in 8.2M opinions; 526 U.S. 434 is *203 North LaSalle*, not *Dewsnup*). Staged at `verifier/hf_release_v0.2/`.

### Open, in priority order

1. **Commit and push** — today's work exists only on this machine
2. Re-ground the 87 quarantined + 803 queued citations via the MCP route; add the **date-consistency guard** (reject any cluster whose date can't match the cited reporter volume) — free, background, ~890 fetches
3. Load `hallucination-registry` into Supabase; write `enrich.py` (judge / docket / CL opinion ID / sanctioning authority)
4. Audit all 1,780 `agent_verdicts.reason` fields for fabricated citations → measured per-model fabrication rate
5. Standing-order + bar-opinion registry (greenfield; the compliance product)

---

*Previous update: 2026-07-13 (evening handoff — user switched projects)*

> ⭐ **START HERE:** `docs/context/SESSION-2026-07-13-assistant-casemap-handoff.md`  
> Full notes from the Assistant / Case Map / LAN / extract session.  
> Also: `SESSION-2026-07-12-handoff.md` (demo suite, Video Analyzer, LAN demo mode).  
> Servers were **stopped** at end of 2026-07-13 evening; restart backend:3001 + frontend:3000.

This file is the handoff brief. Any new session — Claude Code, Cowork, Grok, or Claude.ai — should read CLAUDE.md + the latest SESSION handoff first.

---

## ⭐ 2026-07-13 evening — summary (see full SESSION file)

**Product:** Assistant = intake; Case Map (`/analytics`) = per-doc extract view; Workflows never auto-start; Coming Soon in sidebar (Word/WP, Judicial Analytics, Verifier, Wingman). Helvetica Neue site-wide, thin weights.

**Shipped:** auto extract all uploads · extract card · Review editor (blue/green spans) · section definitions full-width · `getApiBase()` for LAN · sparse-scan PDF refusal · Assini = good demo PDF · composer scroll/contrast fix · LAN servers killed on exit.

**Demo PDF:** `…/caselaw/ASSINI v. Hayward, 2026 NY Slip Op 26086…Google Scholar.pdf`  
**Bad demo (scan):** Heppner PACER RICOH image-only.

**Creds:** `aray.aaron@gmail.com` / `Kingsfield-Reset-2026` · demo `demo@kingsfield.app` / `KingsfieldDemo-2026` · `NEXT_PUBLIC_DEMO_MODE=false`.

**Not done:** OCR for scans, free-form drafting, Judicial Analytics product, commit/push this session, CourtListener 125/day raise.

---

## ⭐ NEXT SESSION — START HERE (2026-07-04 evening handoff)

**Environment / how to run:**
- Backend: `cd backend && npm run dev` → port 3001. Frontend: `cd frontend && npm run dev` → port 3000. (Preview harness also works via `.claude/launch.json` config `kingsfield-frontend`.)
- Wingman PWA shares port 3000 with the frontend — only one at a time. Its launch config is `wingman-pwa`.
- Login: `aray.aaron@gmail.com` / temp password **`Kingsfield-Reset-2026`** (reset in auth.users this session; user should change it).
- tsx watch has been flaky (occasional exit 144) AND it does not always reload on edit — if a route behaves like old code, `pkill -f 'tsx watch' && npm run dev` for a clean restart (this bit us again 2026-07-04: route edits silently didn't take effect).
- Supabase project id: `fzexglkmpoyxtkdiwelm`. Backend env has both `COURTLISTENER_TOKEN` and `COURTLISTENER_API_TOKEN` (same value — code reads both names).

**⚠️ CourtListener rate limits (measured live 2026-07-04, this token):**
- General API: ~5 requests/min (the documented 5,000/hr does NOT reflect reality for this account — bursts throttle at 5/min).
- `/citation-lookup/`: **50/hour** — this is the budget for Gate 1 existence checks AND the new Analytics cite-count enrichment. Heavy verification testing exhausts it fast; both degrade gracefully (verification fails closed, enrichment skips with a log line).
- `/courts/` is hard-capped at `page_size=20` → the full ~3,360-court list takes ~170 requests. It is therefore **snapshotted to `backend/data/courtlistener-courts.json`** by `backend/scripts/fetch-courts.mjs` (throttle-respecting, ~60 min) and served from disk by `GET /api/research/courts`. Re-run the script + restart the backend to refresh.

**FIXED & VERIFIED this session (2026-07-04 evening) — the previous open-items list is DONE:**

1. **Analytics redesign — BUILT.** Force graph deleted. New columnar layout (`analytics/page.tsx`): "The players" role-grouped entity chips, then 3 color-coded columns — Allegations (red), Authorities (blue), Defenses (green) — each clustered common → rare. Axis: agent-judged `novelty` (common/uncommon/novel, new field in the extraction prompt) for allegations/defenses; CourtListener `cite_count` for authorities (enriched at extraction time via one batched citation-lookup — `enrichAuthorityCiteCounts()` in `caseIntelligence.ts`; tiers: 1,000+ landmark / 100+ well-established / <100 rarely cited / null = rules & statutes). Hover-an-authority cross-highlight kept. Old extractions lack novelty/cite_count and fall into unlabeled/unresolved buckets — re-analyze to rank them. Verified live with the Perrin extraction and a fresh complaint.pdf re-extraction (novelty populated; cite_count null only because the 50/hr lookup quota was exhausted at test time).
2. **Tabular Review create bug — FIXED.** Root cause: `get_tabular_reviews_overview` RPC never existed in the live DB; creates always succeeded, every list fetch 500'd. RPC created live + back-ported to `backend/migrations/140_tabular_reviews_overview.sql`. Verified end-to-end via authed `GET /tabular-review` (200, both "missing" reviews returned).
3. **Full jurisdiction picker — BUILT.** `GET /api/research/courts` serves the court snapshot (see rate-limit note above). New `frontend/src/app/components/case-law/CourtPicker.tsx`: tabs (Federal Appellate / Federal District / Bankruptcy / State / More), cross-tab search, multi-select checkboxes (search sends space-separated court IDs — CL supports it), section grouping (state supreme/appellate/trial), "include historical" toggle, offline fallback to a static federal list when the snapshot 503s. Case Law page now uses it (old 65-entry hand-maintained dropdown deleted). Verified in browser; full-list verification pending snapshot crawl completion.
4. **`get_chats_overview` RPC missing (found during verification)** — every `GET /chat` list 500'd. Same drift pattern. Created live + back-ported to `backend/migrations/150_chats_overview.sql`. Verified 200.
5. **Gate 4 empty-jurisdiction hole closed** — `assessJurisdictionFit()` now returns `null` (unknown) for empty jurisdiction instead of misreporting `mandatory` (`''` is a substring of every forum string). The docket-resolution fix itself was already committed (49881f5).
6. **Auto-extract on project upload** — `handleDocumentUpload` in `routes/documents.ts` now fires the same fire-and-forget case-extraction as tabular-review create when the upload targets a project (skips already-analyzed docs). Standalone uploads keep manual Analyze.
7. **Case Law honest rate-limit UX** — backend passes CL 429s through as `{error:'rate-limited', retry_in}`; frontend shows "CourtListener is rate-limiting requests — retry in ~Ns" with a retry button instead of the misleading "Search API unreachable".

**FIXED & VERIFIED this session (see detailed sections below):** Council raw-markdown render ("white with lines"), a cascade of live-DB schema drift (user_profiles cols, get_projects_overview RPC, document_versions cols incl. the critical `deleted_at` that broke read_document + extraction, user_api_keys table, 5 MCP tables, tabular_reviews.document_ids), the crashed-backend guard, Case Law in-app opinion reader, Case Law 50 states, modal ghostly-backdrop, Sign Out, the Analytics/Case-Intelligence extraction feature (built from scratch, working), and the auth-caching speed pass (~200ms→~0 per cached request).

**⚠️ Live-only migrations (no `.sql` files):** all schema fixes this session were applied directly to the live DB via the Supabase MCP `apply_migration`, NOT committed as files in `backend/migrations/`. Names applied: add_missing_user_profiles_columns, create_get_projects_overview, add_missing_document_versions_columns, add_document_versions_deleted_at, create_user_api_keys, create_user_mcp_connector_tables, add_tabular_reviews_document_ids, create_case_intelligence. If you rebuild the DB from `backend/migrations/`, these will be missing — back-port them to `.sql` files if that matters.

**Git state:** all changes uncommitted on `main`. New untracked file that matters: `backend/src/lib/caseIntelligence.ts`. Nothing committed or pushed this session (user hasn't asked). Modified files span backend (auth, index routes, tabular, documents, coordinator, index.ts) and frontend (analytics, case-law, council pages; ChatView, InitialView, AppSidebar, Modal components).

---

## What's Built and Working

### Frontend (Next.js 16 / React 19 / Tailwind v4)
- **Landing page** (`frontend/src/app/page.tsx`) — Dark navy (#1A1E2E), Playfair Display 900 wordmark, gold (#C8A96E) accent, IBM Plex Mono labels, four-gate chips, "Enter the App" CTA. Single viewport, no scroll. Fonts loaded via next/font/google.
- **AppSidebar** — Kingsfield gold orbit mark + Playfair wordmark replacing Mike's icon. Nav: Assistant, Projects, Case Law, Legislation, Tabular Review, Workflows, Council.
- **InitialView (chat home)** — Kingsfield wordmark, gold rule, 6 real starter prompts reflecting actual use cases, footer copy: "Every citation verified · Primary sources only · Not legal advice — legal knowledge."
- **Council page** (`/council`) — Five advisor cards with sharpened descriptions. Contrarian, First Principles (Gemini Pro), Expansionist, Outsider (Gemini Flash), Executor.
- **Case Law page** (`/case-law`) — CourtListener-backed search with jurisdiction dropdown and four-gate chips on results.
- **Legislation page** (`/legislation`) — Federal sources + all 50 states + DC + PR.

### Backend
- Crew agents exist: `coordinator.ts`, `researcher.ts`, `strategist.ts`, `contract-analyst.ts`, plus specialty skills.
- LLM Council orchestrator exists: `orchestrator.ts`, `providers.ts`, `prompts.ts`.
- Skills layer: `backend/skills/` contains 9 production-ready legal workflow skills (see below).
- **Four-Gate Citation Verification is wired into the real production chat routes.** `backend/src/middleware/hallucination_guard.ts` exports `verifyDraftForSse()`, which both `backend/src/routes/chat.ts` and `backend/src/routes/projectChat.ts` call right after the assistant's reply is fully assembled (before persistence, before the SSE connection closes). It runs `verifyDraft()` from `backend/src/verification/pipeline.ts` against the live CourtListener API and writes to the `sources`/`citations` tables, then emits one more SSE event on the same connection: `{type: "verification", verdicts, hasVetoes, hasConditional, error?}`. Verification failures fail closed (`hasVetoes: true`) without crashing the chat response. Live-tested against real citations (Miranda v. Arizona, Marbury v. Madison) on 2026-07-03 — both verified end to end, rows persisted with `cl_opinion_id` populated. **Known gap:** `sources.jurisdiction` is currently always stored as an empty string (see blocker below), so Gate 4 (jurisdiction fit) always reports `mandatory` for chat-originated citations regardless of the actual court — filed as a follow-up, not fixed as part of this wiring.

### Skills (backend/skills/)
All migrated from HeyCounsel community repo:
- `privilege-sentinel` — pre-flight privilege check before sending legal content to AI
- `matter-journal` — per-matter case files with auto-logging (maps to Projects feature)
- `tx-title-analysis` — Texas title analysis, production-ready with 15+ reference files
- `employment-law-research` — 50-state employment law research
- `formation-counsel` — US/Canada startup formation, attorney-facing
- `legal-guidance-vault` — guidance archiving and retrieval
- `template-synthesizer` — document template generation
- `redline-emailer` — contract redline + email workflow
- `SKILL_TEMPLATE` — blank template for new Kingsfield skills

---

## What's NOT Working / Not Wired

### Critical blockers (must fix before product works end-to-end):

1. **Chat route** — CORRECTION (2026-07-03): the previous claim that `streamChat`/`streamProjectChat` post to `/api/crew/chat` was **false** — verified by reading `frontend/src/app/lib/mikeApi.ts` directly. They actually post to `${API_BASE}/chat` and `${API_BASE}/projects/:id/chat` (`backend/src/routes/chat.ts`, `backend/src/routes/projectChat.ts`), which is the real production path: auth, `chat_messages` persistence, multi-turn history, MCP connectors. `POST /api/crew/chat` (`backend/src/routes/index.ts`, calls `runCrew()`) has no auth, no persistence, and the frontend never calls it — it's a separate, unwired demo endpoint. ✅ Citation verification has now been wired into the real chat routes instead of swapping the frontend to the unauthenticated crew endpoint (see Backend section above).

2. **Migration 110** ✅ APPLIED — confirmed live in Supabase project `fzexglkmpoyxtkdiwelm` via `list_tables` on 2026-07-03: `llm_council_sessions` and `crew_traces` both exist.

3. **`sources.cl_opinion_id` column** ✅ PRESENT — confirmed live on 2026-07-03; `sources` table already has `cl_opinion_id bigint`, and `verifyDraft()` writes to it successfully (verified with a real CourtListener round-trip).

4. **Gemini API key** ✅ SET — `GEMINI_API_KEY` is in `backend/.env` and `backend/src/index.ts` instantiates the `GeminiClient` from it (lines 46–61). Provider diversity is live on next server restart.

5. **`sources.jurisdiction` always empty** ✅ FIXED — commit 49881f5 resolves court via the linked docket resource (`resolveCourtFromDocket` in courtlistener.ts); 2026-07-04 evening closed the remaining hole: `assessJurisdictionFit()` returns `null` for an empty jurisdiction instead of misreporting `mandatory`.

---

## Wingman (2026-07-03 handoff executed)

Two builds, both verified running against live Gemini (`gemini-3.1-flash-live-preview`):

- **`wingman-in-your-ear/wingman-demo/`** (own git repo, Node/TS + React PWA, port 3000) — the iPhone path. Was missing all courtroom-advisor behavior; now has: `harness/` dir (court_pro_se, broadcast_market, deposition), server-side harness loader injecting `systemInstruction` + per-agent voice (Charon/Fenrir) at `ai.live.connect`, agent selected client-side and passed as `?agent=` WS query param, advisor audio playback (24kHz PCM) + WINGMAN transcript logging in App.tsx (neither existed — the client never played model audio). Fixed broken text relay (`gSession.send` → `sendRealtimeInput`; `sendClientContent` is restricted to initial-history seeding on gemini-3.1 live). package.json renamed react-example → wingman-pwa, unused vision deps stripped (mediapipe, tfjs, coco-ssd, ffmpeg-static, better-sqlite3, tone — grep-confirmed unused). `.env` created from backend key (gitignored). **Behaviorally verified end-to-end**: silent through 3 neutral courtroom turns, spoke once on a planted contradiction ("Contradicts his testimony under oath"). Harness needed two iterations: explicit high-bar-for-speaking rule (was trigger-happy) and explicit "no placeholder output" rule (model spoke the literal word "\<silent\>").
- **`wingman-in-your-ear/wingman_live.py`** (Python desktop) — the handoff's P3 premise was wrong: the file on disk has no `send_client_content` call and no harness loader (hardcoded `system_instruction`). Added the same 3-agent harness loader (`harness/` copy at `wingman-in-your-ear/harness/`), CLI agent selection (`python wingman_live.py deposition`), per-agent voice. Harness goes through `system_instruction` at connect — deliberately NOT `send_client_content`, which sidesteps the history_config API change entirely. The June-15 working Python env no longer existed (system Python is now 3.14.5); created `wingman-in-your-ear/venv/` with google-genai + pyaudio. **Live-verified headless**: deposition agent connected and answered a mischaracterized-testimony trap with "Mischaracterizes testimony. Object."

Later same day: both builds gained `context_window_compression` (sliding window) so sessions survive past the Live API's audio time limit — accepted by the model, behavior re-verified. `proactivity`/`proactive_audio` was tried and is **rejected at setup by gemini-3.1-flash-live-preview** (native-audio-dialog-family feature only); silence remains prompt-enforced. Mobile fixes: safe-area insets + viewport-fit=cover, dvh, scrollable start-overlay (Start button was clipped on phone), proper title/PWA meta tags.

## Verifier / Judicial-intel (2026-07-03)

- `verifier/venv` — OK (requests, rapidfuzz); all citation-benchmark scripts compile. `verifier/.env` created from backend keys (CL_TOKEN etc., gitignored); CourtListener API auth live-tested 200.
- `verifier/venv-judicial` — was completely broken (built on Python 3.13, since uninstalled; all symlinks dangling). Rebuilt on 3.14 with requests, rapidfuzz, opencv, numpy, av 18, ctranslate2 4.8.1, faster-whisper (installed `--no-deps` because it pins an older PyAV with no 3.14 wheel). **onnxruntime has no macOS-x86_64/py3.14 wheel** → `transcribe.py` patched to skip the VAD filter gracefully when onnxruntime is absent; Whisper-API path unaffected. yt-dlp + ffmpeg present on PATH. All pipeline scripts compile and `--help` runs.

---

## Schema drift + app fixes (2026-07-03, later session)

The live Supabase DB (`fzexglkmpoyxtkdiwelm`) had drifted badly from what the backend code expects — the code was never wrong, the DB was just missing objects. Fixed by migration (all additive, never dropped):
- `user_profiles` — added `mfa_on_login`, `title_model`, `legal_research_us` (every auth'd request selected these → constant errors).
- `public.get_projects_overview(p_user_id, p_user_email)` RPC — **created from scratch** (never existed live); every Projects page load 500'd. Returns owned+shared projects with document/chat/review counts.
- `document_versions` — added `filename`, `file_type`, `size_bytes`, `page_count` (upload version insert failed).
- `documents` insert in `routes/documents.ts` — was omitting `filename` (NOT NULL) → "Failed to create document record". Code fix.
- `user_api_keys` table — **created from scratch**; its PGRST205 rejection was the unhandled-rejection that crashed the whole backend (Node kills the process on unhandled rejection). Also added a `process.on("unhandledRejection")` guard in `index.ts` so one stray rejection can't take the server down again.
- 5 MCP connector tables created: `user_mcp_connectors`, `user_mcp_connector_tools`, `user_mcp_oauth_tokens`, `user_mcp_oauth_states`, `user_mcp_tool_audit_logs`.
- CourtListener token: code reads it under **two** env names (`COURTLISTENER_TOKEN` in index.ts, `COURTLISTENER_API_TOKEN` in userApiKeys.ts). Only the first was set → case-opinions failed. Added the alias to `backend/.env`.

**A background task (`task_8407d280`) was spawned to systematically audit ALL `.from()/.rpc()/column` references in backend/src against the live DB** — the fixes above were found error-by-error and a full sweep is warranted.

App-level fixes same session:
- **Case Law in-app opinion reader** (`case-law/page.tsx`) — was link-out-only; now clicking a result or "Read opinion" opens a slide-over that pulls full opinion text via `/case-law/case-opinions` (four-gate verified) and renders it in-app, CourtListener cited as *source* in the footer, not the destination. Harvey-style. Live-verified with Twombly.
- **Council page** — was hardcoded dark (`#161615`/white bg) and looked broken in light theme; rewritten to use the theme-aware `bg-white`/`bg-gray-50`/`text-gray-*` classes so it respects Light/Parchment/Dark.
- **Sign Out** — added to the sidebar avatar dropdown (`AppSidebar.tsx`); there was no way to log out.
- **Killed the "AI can make mistakes" disclaimer** (InitialView + ChatView) — replaced with the approved "Every citation verified · Primary sources only · Not legal advice — legal knowledge." per decisions.md 2026-05-16. It had silently survived in the assistant views.

Note: password for `aray.aaron@gmail.com` was reset directly in `auth.users` during this session (user forgot it) to a temporary value — user should change it.

## Batch 3 fixes (2026-07-03, third session)

- **Ghostly modals fixed** — shared `components/shared/Modal.tsx` used a 30%-opaque white backdrop + 94% panel, so every modal (New Project, New Tabular Review, workflow "Use") rendered see-through with the page bleeding through ("faint typing in the bg"). Changed to `bg-gray-900/50` scrim + solid `bg-white` panel. Now theme-aware and solid. NOTE: "Create" buttons are correctly disabled until a name is entered — that was mistaken for "broken" only because the transparent modal hid the disabled state.
- **`tabular_reviews.document_ids`** — added (jsonb). Workflow "Use" → create review was 500ing on the missing column (same drift pattern).
- **Case Law: all 50 states + DC** — jurisdiction dropdown had only SCOTUS + federal circuits. Added every state's highest court, using real CourtListener court IDs pulled live from `/courts?jurisdiction=S`.
- **Verification vs source chips** — now visually distinct: green shield "Existence verified" vs blue book "CourtListener" (source).
- **Council WP-plugin dead link** — `#word-plugin` anchor → mailto early-access request.
- **Assistant killed disclaimer** — done (see Batch 2).

### Known / not-yet-fixed (flagged for the user)
- **Assistant can't read some attached PDFs** ("not correctly indexed"). Root-cause hypothesis: uploads were fully broken (filename NOT NULL) until Batch 2 this same day, so files like "RULE 60.pdf" were uploaded during the broken window and never got a proper version row / storage path. `buildDocContext` only loads docs with `status='ready'` + a storage_path. **Re-upload after the fix should resolve it** — needs a fresh-upload test to confirm before deciding it's a live extraction bug.
- **Analytics is a stub vs. the intended product**: the vision is a judicial/opposing-counsel/witness connection graph + an allegation↔defense↔authority cluster, populated by a pre-trained extraction agent that runs when a doc is uploaded to Tabular Review or a Project, strips the case facts (authorities cited, defense theory, how rare/common the fact pattern is), and pushes structured output into Workflows + Analytics. This is a multi-session feature build, not a bug — not started.
- **Perf**: Council = 11 model calls/session, crew is multi-agent; both feel slow. No parallelization/caching pass done yet. Scoped, not started.

## Analytics / Case Intelligence — BUILT (2026-07-03, fourth session)

Replaced the hardcoded SCOTUS mock with a real extraction pipeline, live-verified end to end.
- **`case_intelligence` table** (migration) — one row per document: caption, entities[{name,role}], allegations[{claim,authorities[]}], defenses[{defense,authorities[]}], authorities[{citation,proposition,treatment}], rarity{score,label,rationale}, defense_summary.
- **`backend/src/lib/caseIntelligence.ts`** — the extraction agent. `loadDocumentPlainText` (downloads current version via `loadCurrentVersionBytes`, extracts pdf/docx), `extractCaseIntelligence` (LLM structured-JSON call, tabular_model), `runCaseExtraction` (orchestrate + upsert on document_id).
- **Routes** (index.ts, requireAuth): `GET /api/analytics` (extractions), `GET /api/analytics/documents` (ready docs + analyzed flag), `POST /api/analytics/extract` ({documentId}).
- **Auto-trigger**: tabular-review create fires a fire-and-forget `runCaseExtraction` per attached doc (skips already-analyzed) — "uploaded to tab review" is the trigger per spec.
- **Analytics UI** (`analytics/page.tsx`) — document picker + Analyze button, case tabs, d3 connection graph (case center; entities colored by role: judge/opposing_counsel/witness/expert/party/court/authority), rarity meter, defense summary, and the Allegations↔Authorities↔Defenses cluster (hover an authority to highlight what it supports). Empty state when nothing analyzed.
- **Verified**: uploaded a synthetic CA employment complaint → extraction pulled judge (Patricia Hollows), witness (Robert Chen), expert (Dr. Park), 2 allegations w/ Tameny + Yanowitz, 2 defenses w/ McDonnell Douglas, 5 authorities, rarity "Routine". Rendered correctly in the browser.

### CRITICAL drift fix found here: `document_versions.deleted_at`
`loadActiveVersion` filters `.is("deleted_at", null)`, but the column was missing → the query errored → EVERY version load returned null. This silently broke **`read_document` in the assistant** (the real cause of "RULE 60.pdf not correctly indexed") AND case extraction. Column added. The assistant should now read attached PDFs — worth a re-test.

### Still open
- ~~Auto-trigger only on tabular-review create; project-tab upload doesn't yet auto-extract~~ — DONE 2026-07-04: project uploads now auto-extract too (documents.ts `handleDocumentUpload`).

## Open items after 2026-07-04 evening session

- **Courts snapshot crawl**: `backend/scripts/fetch-courts.mjs` may still be running (~60 min) or need a re-run if it died. Until `backend/data/courtlistener-courts.json` exists, the picker shows the federal fallback + "full court list unavailable" note. After it lands, restart the backend and confirm the picker shows all tabs populated.
- **Old extractions unranked**: case_intelligence rows extracted before today have no `novelty`/`cite_count` — re-analyze from the Analytics page to rank them (cite counts need the 50/hr citation-lookup quota to be available).
- **`get_*_overview` RPC drift pattern**: three RPCs were missing live (`get_projects_overview`, `get_tabular_reviews_overview`, `get_chats_overview`). The full audit task (task_8407d280) should still sweep for others.

## Speed pass (2026-07-04)

**Root cause of "too slow":** every authenticated request independently (1) constructed a fresh Supabase admin client, (2) made a network round-trip to Supabase to validate the JWT (`admin.auth.getUser`), and (3) ran a DB query for the MFA preference. Measured ~170-330ms of pure auth overhead per request — and the frontend fires a burst of 5-8 parallel authed requests with the SAME token on every page load, each paying it.

**Fix (`middleware/auth.ts`):** module-level singleton admin client + short-TTL (60s) in-memory caches keyed by token (user resolution) and by user (MFA preference). Only the first request in a burst pays the round-trip; the rest are cache hits.

**Measured:** cold request 206ms → warm/cached ~0ms auth (warm /projects ~60-110ms, now dominated by the actual query, not auth). A realistic 8-endpoint parallel page-load burst completes in ~0.5s wall-clock. Security verified intact: bad/missing tokens still 401 (only validated tokens are cached; TTL 60s bounds revocation lag).

**Council/Crew latency** is architectural, not a bug: advisors already run in parallel (`Promise.all`), reviewers in parallel, then chairman — 3 unavoidable LLM waves. Left as-is.

## Design System (confirmed, do not change without reason)

*Superseded 2026-06-23 — "Redesign frontend with new ink/paper/blue design system" (commit `3156631`). The gold/navy table below is historical; the ink/paper/blue tokens are what's actually in `frontend/src/app/globals.css` as of 2026-07-03.*

| Token | Value |
|-------|-------|
| Ink (primary text/bg-dark) | `#0A0A0A` (`--color-ink`), with `-2`/`-3`/`-mid`/`-soft` steps for hierarchy |
| Paper (app background) | `#F7F6F2` (`--color-paper`), `#EFEEEA` secondary |
| Stone / Mist | `#C4C3BD` / `#C8D8DC` — muted neutrals |
| Blue accent (research/links) | `#2B5CE6` (`--color-research`, `--color-blue`) |
| Semantic accents | Draft `#C7341A`, Workflow `#E8B121`, Data room `#1F8A5B`, Knowledge `#7A3FD6` |
| Sans | DM Sans (`--font-sans` / `--font-dm-sans`) |
| Serif/display | Playfair Display (`--font-serif` / `--font-playfair`) |
| Mono | JetBrains Mono (`--font-mono` / `--font-jetbrains-mono`) |

Legacy `--color-kf-navy` (`#15192E`), `--color-kf-gold` (`#E09B30`), `--color-kf-black`, `--color-kf-cream` variables still exist in `globals.css` for anything not yet migrated off the old system — don't treat their presence as evidence the old system is still primary.

App interior (Council, Case Law, etc.) stays clean and crisp — matches existing Mike styling with Kingsfield branding layered on.

---

## Pending / Next Work

- [x] Wire real citation verification into production chat — done 2026-07-03, `verifyDraftForSse()` called from `chat.ts` and `projectChat.ts`, emits `verification` SSE event. (Previous "Wire chat route to Crew" entry was based on a false claim — the frontend was never repointed at `/api/crew/chat`, and correctly so, since that route has no auth/persistence.)
- [x] Migration 110 — confirmed already applied live (2026-07-03)
- [x] `cl_opinion_id` column — confirmed already present live (2026-07-03)
- [x] Gemini key — set in backend/.env, instantiated in backend/src/index.ts lines 46–61
- [x] Fix `sources.jurisdiction` always empty — done (commit 49881f5 + empty-string guard in pipeline.ts, 2026-07-04)
- [ ] Build judge scoring prompt + `quality_scores` schema for A/B testing
- [ ] Add `cal.diy` scheduling infrastructure for deadline/docket tracking
- [ ] Build per-school law school debt dataset (research product)
- [ ] Consider Legal Data Hunter MCP (`https://legaldatahunter.com/mcp`) vs CourtListener
