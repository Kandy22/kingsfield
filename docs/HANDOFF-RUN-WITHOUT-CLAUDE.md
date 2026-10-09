# Kingsfield: how to run, check and ship this WITHOUT Claude

Written 2026-10-09 (morning) so you never depend on a Claude session to understand or operate this repo.
Everything below is a normal shell command. Nothing here needs Claude, an agent, or a hook to run.

## 0. State of things when this was written (be skeptical, verify with section 3)

> **UPDATE 2026-10-09 ~11:05: `main-verify` is DONE and pushed.** The adversary found 11 holes in the 20 unreviewed `Kandy22` commits (see section 11), the builder fixed them over 4 rounds, and the adversary signed `main` (signoff `0f826ff3...`, matches `tree_digest.py`). Signoff tier 537 tests OK in 175 s; `tests_extended` 12 OK in 86 s; the hook `require_adversary_signoff.py` exits 0. Committed as `e49007d`, GitHub `main` = local `main` = `e40ba52`. The 18 `apply_*.py` scripts are gone. Everything below in this section that calls the post-Part-A code "unreviewed" or lists the 5+1 failing tests is now **superseded**. Still open: watcher `report_md` (docket/IP) has no Gate 1; `edit_document` only gates text within about 300 characters of a change; two files outside the builder's write scope were edited by the lead and reviewed by the adversary (`crew/coordinator.ts`, `lib/caseIntelligence.ts`, not in the digest).

- **Public GitHub `main`** (https://github.com/Kandy22/kingsfield) = local `main` = commit `565a0c0` (checked 2026-10-09).
- Work done up to the **chat-route signoff (2026-10-08, commit `d06dec2`) WAS reviewed** by the adversary agent and has a signoff file.
- Work added **after** that (document-write gate, chat titles, ownership checks, MCP gate, analytics gate, crew abort, inferred page bounds, jammed-cite scrub) was applied with `apply_*.py` patch scripts and pushed **without** adversary review or a signoff. Treat it as **unreviewed**.
- A task called `main-verify` was started 2026-10-09 ~6:00 AM to fix 4 failing tests, have the adversary review that unreviewed work, and write a signoff. If its result is not committed yet, that work is still open.
- Known failing tests on `565a0c0` (from a run on 2026-10-09):
  - signoff tier: 509 tests, 1 failure (`test_a_veto_survives_a_reload_of_the_chat`, a code-shape check made stale by the title patch), 207 s (limit is 200 s)
  - builder tests: 231 tests, 5 failures (`edit_document` gated twice x3; crew keepalive not stopped on disconnect; one tabular abort test that only fails under load and passes alone)
- **JEV (the CPU router in `router/`) is NOT connected to the app.** Nothing in `backend/src` calls it. It only exists, signed off against stubs.

## 1. What is where

| Thing | Location |
|---|---|
| This repo | `~/kingsfield` (GitHub: Kandy22/kingsfield, **public**) |
| Backend / frontend | `backend/`, `frontend/` |
| Gate 1 (citation existence check) | Python: `pipeline/gate1.py`. TypeScript: `backend/src/verification/local_sqlite_gate.ts`, `pipeline.ts` |
| The chat guard (holds replies until Gate 1 passes, withholds on veto) | `backend/src/middleware/hallucination_guard.ts`, used by `routes/chat.ts`, `projectChat.ts`, `tabular.ts`, `index.ts` |
| Tests, builder's | `pipeline/builder_tests/` |
| Tests, adversary's (the ones that count for signoff) | `pipeline/tests/` (must finish < 200 s) and `pipeline/tests_extended/` (slow variants, run separately) |
| Signoff files | `.claude/signoffs/*.signoff` (a fingerprint of the reviewed code) |
| Florida citation database | `~/kingsfield/kingsfield_florida.db` (52 MB, **local only, git-ignored, not on any server**) |
| Source data for that database | `~/Kingsfield_Corpus/` (3 CourtListener `.bz2` files, 7.2 GB; build log `build-2026-10-08.log`) |
| JEV / System One router | `router/` (Python, with a local `.gguf` model) |
| Wingman | `wingman-in-your-ear/` (start with `RUN_wingman.command`; spec files `WINGMAN_*.md`) |
| Judicial intel (oral arguments, Jev scoring) | `verifier/judicial-intel-analytics/` and `verifier/new-kingsfield-judicial-intel-categories/` |
| **Business plan (BP)** | `to sort/Kingsfield Bus Plan/Kingsfield_Business_Plan_2026_v2.docx` (main), `business-plan/Kingsfield_BP_v3_Additions.docx` (BP dated 2026-05-20, additions 2026-05-21). Read as text: `textutil -convert txt -stdout <file>`. Mapped to what exists in `docs/DB-AND-CITATIONS-EXPLAINED.md` section 9 |
| **The business plan vs. what exists (promise by promise)** | `docs/BP-VS-REALITY-2026-10-09.md` |
| **The DB / citations / labels explained** | `docs/DB-AND-CITATIONS-EXPLAINED.md` |
| Project state notes | `docs/context/current-state.md` (top = newest; **older "OPEN/not fixed" sections below the top may be stale**) and `docs/context/decisions.md` |
| Python for all of the above | `~/.venv-cascade/bin/python` (Python 3.12) |
| Hugging Face | org `Kingsfield-Lawfare`: datasets `legal-citation-benchmark` (public), `florida-court-transcripts` (private) |
| Other GitHub repos (forks/tools) | `jev-mcp`, `jev-skills`, `awesome-jev`, `von`, `kev` (fork of jaredpalmer/kev, a model family, NOT a safety gate), `mike`, `eyecite`, `capstone`, `open-us-law` |

## 2. How to run everything by hand

```bash
cd ~/kingsfield
PY=~/.venv-cascade/bin/python

# Type-check (both must print nothing and exit 0)
backend/node_modules/.bin/tsc --noEmit -p backend
(cd frontend && node_modules/.bin/tsc --noEmit -p .)

# Tests. Run ONE at a time; don't run other heavy apps meanwhile (the 200 s limit is tight).
$PY -m unittest discover pipeline/tests            # signoff tier, ~3 min
$PY -m unittest discover pipeline/tests_extended   # ~30 s
$PY -m unittest discover pipeline/builder_tests    # ~1.5 min
$PY -m unittest discover router/tests              # router suite, ~10 s

# Is the code still what was signed off? (the two lines should be identical per task)
$PY .claude/hooks/tree_digest.py
cat .claude/signoffs/chat-route-verify.signoff

# Run the same check Claude's "task complete" hook runs
echo '{"task_id":"chat-route-verify","task_subject":"[module] Chat route verification"}' | CLAUDE_PROJECT_DIR=$PWD $PY .claude/hooks/require_adversary_signoff.py; echo "exit $?"
```

A signoff is valid only while `tree_digest.py` equals the number inside the `.signoff` file. Any edit to a file the digest covers (`db/`, `pipeline/`, `router/`, and the listed files in `backend/src`) invalidates it until the adversary re-signs.

**Ship:**
```bash
git status --short | grep -v '^ D'      # review what you are about to commit
git add <specific files>                # never `git add -A` here: there are ~180 unrelated uncommitted deletions
git commit -m "message"
git push origin main
```

**Rebuild the Florida database** (one process, ~51 minutes, uses one CPU core):
```bash
cd ~/kingsfield && ~/.venv-cascade/bin/python db/build_sqlite_index.py --corpus ~/Kingsfield_Corpus
```

## 3. Verify the claims in section 0 yourself (2 minutes)

```bash
cd ~/kingsfield
git fetch origin && git log --oneline -1 && git rev-list --left-right --count main...origin/main   # expect "0  0"
git log --oneline 540e748..HEAD | wc -l                      # commits made after the last fully reviewed point
~/.venv-cascade/bin/python .claude/hooks/tree_digest.py; cat .claude/signoffs/chat-route-verify.signoff
ls apply_*.py 2>/dev/null                                    # patch scripts; should be gone after main-verify
```
If the digest and the signoff differ, the code changed after the last review (expected until `main-verify` is committed).

## 4. The Claude machinery in this repo (what it is, how to turn it off)

- **Agents** (`~/.claude/agents/`): `backend_builder` (writes code), `adversary` (writes tests + signoffs), `decision_router`. All run on Sonnet, effort medium (changed from high on 2026-10-09 to save tokens).
- **Hooks** (`.claude/hooks/`, wired in `.claude/settings.json`):
  - `enforce_agent_dirs.py`: each agent may write only its own paths, and run only allowed commands.
  - `require_adversary_signoff.py`: a `[module]` task cannot be marked complete without a valid signoff.
  - `tree_digest.py`: computes the fingerprint.
- They only run **inside Claude Code**. They do nothing when you use a normal terminal, git, or another tool (e.g. Aider). If you stop using Claude Code, they simply never fire.
- **To disable them inside Claude Code:** delete the `"hooks"` block in `.claude/settings.json` (back it up first). Doing so removes the agents' file limits and the signoff requirement.
- Aider/other tools are fine for non-gate projects (Drink Champs, the blog). Do **not** use them to edit the gate files, since nothing enforces review there.

## 5. Everything changed on your machine outside the repo (so nothing is a surprise)

| What | Where | How to undo |
|---|---|---|
| Default model Sonnet + effort medium | `~/.claude/settings.json` (backup: `settings.json.bak-2026-10-09`) | `cp ~/.claude/settings.json.bak-2026-10-09 ~/.claude/settings.json` |
| Project effort high -> medium | `~/kingsfield/.claude/settings.json` | edit `effortLevel` |
| Agents effort high -> medium | `~/.claude/agents/{backend_builder,adversary,decision_router}.md` | edit the `effort:` line |
| Agents may edit `tabular.ts`, `chatTools.ts` | those agent files + `.claude/hooks/enforce_agent_dirs.py`, `tree_digest.py` (commit `9d13d3d`) | `git revert 9d13d3d` and edit the agent files |
| `.gitignore` now ignores `kingsfield_florida.db` | commit `96f738a` | revert it |
| 163 Wingman files restored from git | `wingman-in-your-ear/` (they had been deleted in the working tree, not in git) | n/a |
| Florida DB built | `~/kingsfield/kingsfield_florida.db` | delete the file; rebuild with section 2 |
| CourtListener bulk files downloaded | `~/Kingsfield_Corpus/` (7.2 GB; only needed to rebuild the DB; ~23 GB disk free at last check) | delete if you need the space |
| Claude memory note about token routing | `~/.claude/projects/-Users-aaronray-Library-CloudStorage-GoogleDrive-aray-aaron-gmail-com-My-Drive/memory/token-budget-model-routing.md` | delete the file and its line in `MEMORY.md` |
| Untracked: ~180 deletions in `verifier/judicial-intel...`, `business/kingsfield`, `assets/Side Logos`, etc. | working tree only | `git restore -- <path>` to undo, or commit them deliberately |

The old Claude conversation transcripts are plain files in `~/.claude/projects/-Users-aaronray-kingsfield/*.jsonl` and `~/.claude/projects/-Users-aaronray-Library-CloudStorage-GoogleDrive-aray-aaron-gmail-com-My-Drive/*.jsonl`. Search them with `grep`.

## 6. Open items (also in `docs/context/current-state.md`)

1. Finish `main-verify`: fix the 4 failures, adversary review of the unreviewed commits, signoff, delete `apply_*.py`, fix the contradictory section in `current-state.md`.
2. **The GitHub repo is public and contains personal files** committed in July: `EXPERT CREDENTIAL SYNTHESIS & QUALIFICATION PROFILE.md`, 68 files under `UPL:Licensed Legal Paraprofessional /`, `Current Edition _ Jailhouse Lawyer's Manual.pdf`. Decide: make the repo private, or remove those files (note: removing them does not erase them from git history).
3. Decide what to do with the ~180 uncommitted deletions (restore or commit).
4. Copy `kingsfield_florida.db` to wherever the backend runs. Without it, production Florida citations veto as `db_unavailable`. Page ranges in it are **inferred** (next case's first page), not CourtListener's, and 4,786 of 391,465 rows have none.
5. Wire JEV into the app as its own task (nothing calls it today).
6. Stored model text with no Gate 1 still exists in older database rows (chat messages, tabular cells before the gate). Read paths re-check some of it; the database itself isn't rewritten.
7. Other projects (judicial intel diarization rework, Mike upstream sync of 600+ changes, Wingman local migration per `WINGMAN_LOCAL_MIGRATION.md`) are untouched by this work.

## 7. Services, hosting, GPU jobs (added after you pointed out they were missing)

**Where production is hosted: NOT RECORDED ANYWHERE I COULD FIND.** The repo has no deploy config (no Vercel/Render/Railway/Fly/Netlify files, no Dockerfile, no Procfile). `docs/SETUP.md` (line 92, "Self-hosting note") and `docs/architecture/ARCHITECTURE.md` (line 145: the demo lives at "kingsfield.[tld]") never name a host or domain. Fill this in yourself:

| Fill in | Value |
|---|---|
| Backend host / how it is deployed | ______ |
| Frontend host | ______ |
| Domain / DNS | ______ |
| Where `kingsfield_florida.db` must be copied | ______ |

**Services the app uses (from `backend/.env.example` and `frontend/.env.local.example`; names only, values live in your local `.env` files):**
- **Supabase**: database + auth. Project id in the notes: `fzexglkmpoyxtkdiwelm`. Vars: `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SUPABASE_DB_URL`; frontend `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY`.
- **Cloudflare R2**: file storage. `R2_ENDPOINT_URL`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`.
- **Model providers**: `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY` (OpenRouter is only a key + base URL for a model slug; nothing routes by JEV).
- **Resend**: email. `RESEND_API_KEY`.
- **CourtListener**: the code reads `COURTLISTENER_TOKEN` but it is **missing from `backend/.env.example`**. Add it so the next setup doesn't miss it. Rate limit noted in the docs: 100 requests/hour.
- **Frontend to backend**: `NEXT_PUBLIC_API_BASE_URL`, backend `FRONTEND_URL`. Frontend also has demo-mode vars (`NEXT_PUBLIC_DEMO_*`).
- `frontend/.env.local` exists on disk and contains a `SUPABASE_SECRET_KEY` line. Git-ignore check result at the time of writing: frontend/.env.local backend/.env 

**Modal (GPU jobs): only the judicial-intel project, NOT the app.**
- Files: `verifier/judicial-intel-analytics/pipeline/modal_diarize.py` (speaker diarization, NVIDIA Nemotron 3 Diarization on a Modal L4 GPU), `modal_emotion.py`, `modal_face.py`. Launched with `modal run pipeline/<file>.py --mode ...`, via `RUN_diarize_pilot.command`, from inside `verifier/judicial-intel-analytics/`. Needs `modal` installed and authenticated.
- Per your notes, the existing diarization output is not ground truth; pass 2 needs whole-file audio and a role schema.
- (A repo-wide search for "modal" returns ~70 files, but nearly all are UI popup components in `frontend/`.)

**LawDiver: not integrated anywhere in code.** The only mention in the repo is `verifier/judicial-intel-analytics/DATA-SOURCES.md` line 91: "Make like LawDiver", as the visual model for your `Kandy22/big-blue-marble` map front end. A LawDiver connector exists inside Claude (needs separate sign-in there); it is not part of this repo. One earlier AI note mentioned a "LawDiver missing-key reconstruction": there is nothing like that in the repo; ignore it.

**Other hosts that hold your material:** GitHub `Kandy22/*` (all public: kingsfield, von, mike, kev, jev-mcp, jev-skills, awesome-jev, nimble, eyecite, capstone, open-us-law, etc.); Hugging Face org `Kingsfield-Lawfare`.

## 8. JEV: everything, in one place

"Jev" means three different things in your work. They are easy to mix up (several AI sessions did).

**A. TypeSafe's hosted Jev decision model (used for judicial-intel scoring).** Called through OpenRouter's Decisions API (`POST https://openrouter.ai/api/alpha/decisions`, model `typesafe/jev-1.13`, about $0.042 per million input tokens, key in `$OPENROUTER_API_KEY`). Three primitives: **noul** (probability a statement is true), **choice** (pick an option with probabilities), **score** (a level on a legend).
- Code: `Verifier/new-kingsfield-judicial-intel-categories/src/jev.py` (run with `RUN_jev.command`: smoke test, 10-case validation, asks before the full corpus); `Verifier/judicial-intel-analytics/pipeline/run_oa_panel.py` (+ `RUN_diar_jev.command`, ~$0.01 for 35 arguments); `hallucination-registry/jev_panel.py` (+ `RUN_jev_jobs.command`, outputs in `hallucination-registry/out/`); `reference/jev-voice-turn/` (an iOS app project, `JevVoiceTurn`).
- Findings (FL 2DCA/6DCA oral arguments, 1,428 transcripts scored for $0.47, calibration n=1,098): argued cases affirm 74%; `ruling_lean` is a **lift-with-abstention** signal, not an accuracy model (raw 64%, below baseline, but `reverse` calls at confidence >= 0.7 are right ~90%; abstain below 0.7); the best signal is **`skepticism_gap`** (appellant modal minus appellee modal, composed in Python); nouls don't predict outcome; never report a mean score; carry every level's probability and a bimodal flag. See `docs/context/decisions.md` line 155 and `docs/context/current-state.md` (2026-09-19).
- Offer catalog: 9 of 29 facts populated from this pipeline (`build_snapshots.py`, snapshots in `Verifier/new-kingsfield-judicial-intel-categories/data/snapshots/`).

**B. The LOCAL JEV CPU router in this app (signed off 2026-10-06, NOT wired in).** `router/jev_cpu_inference.py`, `router/system_one_client.py`, `router/calibration.py`, tests in `router/tests/` and `pipeline/tests/test_jev_router.py`; model file `router/qwen1_5-0_5b-chat-q4_k_m.gguf` (quantized, runs on this Mac's CPU through llama.cpp).
- It picks a **retrieval method** (`boolean_search`, `vector_search` or `direct_db`) for a query. It does **not** choose which AI model answers anything, and does not talk to OpenRouter.
- No text is generated. Confidence = softmax over the full-sequence log-likelihood of each allowed option. Anything unusual (not exactly one allowed option, error, timeout, missing model, low confidence, low probability mass) goes to `direct_db`. Citation-shaped queries skip the model entirely (eyecite + Gate 1 pre-check) and go to `direct_db`. Gate 1 still runs on every route.
- **Placeholders, uncalibrated:** the 0.80 confidence threshold and both absolute-mass floors. Calibrate on labeled pairs before trusting them.
- **Required before production:** a real-model KV-cache smoke test (rewound option scores must equal a fresh `reset()` + eval). Stub tests cannot prove it.
- Client selection: `VON_BASE_URL` set -> Von server; else `JEV_MODEL_PATH` set -> local llama.cpp; else a client that raises -> `direct_db`.
- **Nothing in `backend/src` calls it.** Wiring it in is its own task (design: backend calls the router, fail closed to `direct_db`; the adversary signs it off like everything else).

**C. The family around it (GitHub, all yours, all public):**
`Kandy22/jev-mcp` (typed judgments from TypeSafe's Jev as MCP tools), `Kandy22/jev-skills` (agent skills for TypeSafe's System One API), `Kandy22/awesome-jev` (source-backed Jev directory + review workflow), `Kandy22/von` (open-source System One decision model, sub-15 ms, local alternative to Jev; **does not run on this Intel Mac**: newest macOS x86_64 PyTorch wheel is 2.2.2, Docker isn't installed), `Kandy22/kev` (fork of jaredpalmer/kev: a Jev-like model family on Qwen you can train; **not** a safety gate). Local tooling: `~/.config/jev-cli/credentials.json` (a credential file; never paste or commit it). Reference reading in the repo root: `Top 7 Open-Source TypeSafe Jev Alternatives _ DataCamp.pdf`.

**D. Ideas and plans that are written down (from the notes):**
1. Wire the local router into the backend (own task, after `main-verify`).
2. Calibrate the thresholds/floors on labeled pairs; run the KV-cache smoke test.
3. Run a Von System One server when one exists (the client already supports it).
4. Gemini pass 2 for speaker roles: rewrite `diarize.py` for whole-file audio with a role-constrained schema; validate against `data/fl_2dca/transcripts/_truth_eLU5je2C12I.json`; then re-score with Jev (`RUN_diar_jev.command`).
5. Finish the offer catalog (20 of 29 facts still unpopulated).
6. Jev panel over the Charlotin AI-hallucination registry (`hallucination-registry/jev_panel.py`).
Ideas you described in conversation but that were never written into a file live only in the old chat transcripts. Search them by hand:
```bash
grep -il jev ~/.claude/projects/-Users-aaronray-kingsfield/*.jsonl ~/.claude/projects/-Users-aaronray-Library-CloudStorage-GoogleDrive-aray-aaron-gmail-com-My-Drive/*.jsonl
```
The session "Judicial signals with Jev model" (started 2026-09-21) is the main one for part A.

## 9. Your 2026-10-03 instruction set ("the 5 tasks") and what actually happened

The exact point-by-point instructions you demanded on Oct 3 are in **`~/kingsfield/INSTRUCTIONS_5_TASKS_2026-10-03.md`** (13 KB, written 2026-10-03 00:28). It is **untracked in git** on purpose (it was never committed; back it up yourself if you want it kept). Status as verified 2026-10-09:

| Task | Status |
|---|---|
| 1. Florida Southern Reporter citations (flcourts API -> PDFs -> eyecite -> match, LawDiver cross-check) | **NOT built.** `Verifier/judicial-intel-analytics/pipeline/fl_southern_reporter.py` does not exist. (The Florida database built 10-08 is a different thing: CourtListener bulk data for Gate 1.) |
| 2. Review tool (`Verifier/sandbox.html`, Jev pre-labels, merge script) | **NOT rebuilt.** `sandbox.html` and `merge_human_labels.py` are the old June 9 versions. |
| 3. Gates, confidence score, on-prem database | **Partly.** Gate 1 + SQLite DB + chat guard are built (needs `main-verify` signoff). The 8-gate stack and the calibrated "Kingsfield score" are NOT built. |
| 4. Family-law transcripts (Rule 2.515 trade proposal, sandbox, Michigan) | **Not started.** |
| 5. Wingman (folder fixes, Objection cues, diarization, latency, offline) | **Files restored (163, 2026-10-09). The work itself is not started.** |

Leftovers listed at the end of that file:
| Leftover | Status |
|---|---|
| Upload the corrected benchmark card to Hugging Face | **NOT done.** Hugging Face last modified 2026-07-27. The corrected file is `Verifier/hf_release_v0.2/README_v0.2.1_corrected.md`. Commands: `hf auth login`, then `hf upload Kingsfield-Lawfare/legal-citation-benchmark ~/kingsfield/Verifier/hf_release_v0.2/README_v0.2.1_corrected.md README.md --repo-type dataset` |
| Restore the 502 deleted transcripts in `hf_workspace` | **DONE 2026-10-09.** A stale 0-byte `hf_workspace/.git/index.lock` from Aug 25 (a crashed git run) had blocked git there. Removed it, ran `git checkout -- .`; 0 deleted, 2,879 files present. |
| Two Mike fixes (upstream `171d6f9` output limit, `d666189` OpenRouter reasoning) | **DONE 2026-10-09** (ported, since Kingsfield has no `aiSdk.ts`). New `backend/src/lib/llm/outputLimit.ts`: optional env `LLM_MAX_OUTPUT_TOKENS` (positive whole number; empty, 0, negative, fractions and text are ignored). Wired into `claude.ts` (Anthropic *requires* `max_tokens`, so the default stays 16,384 unless the env var is set), `openai.ts` (no cap by default now, provider decides; a caller's own `maxTokens` still wins), `gemini.ts` (provider default unless set) and `openaiCompat.ts` (override applies there too). Reasoning: `openaiCompat.ts` now sends `reasoning: {effort: "none"}` on OpenRouter requests (only OpenRouter; used by the Council's Kimi client). Kingsfield's chat layer has no OpenRouter adapter, so there was nothing else to port. Checked with a stub test (all cases pass) and `tsc`. Add `#LLM_MAX_OUTPUT_TOKENS=` to `backend/.env.example` yourself (that file has your own uncommitted edits). |
| Push main's July commits (code only) | **DONE** (main == origin/main on 2026-10-09). |

Mike overall (2026-10-09): upstream is `open-legal-products/mike` (latest `20d30e5`, 2026-10-09). Your mirror `Kandy22/mike` is 171 commits behind it. Kingsfield has had one port (`62778fb`, LibreOffice path, from upstream `03e8acf`); 199 upstream commits since. The rule in `decisions.md` still stands: do not sync blind; port deliberately.

## 10. If Claude (or your token allowance) stops mid-task: what keeps running and how to resume by hand

**Keeps running with no Claude at all:** the Task 1 jobs (listing, and the 1st DCA text run). They are detached background processes with the Mac kept awake (`caffeinate`), and every stage skips work already on disk, so they survive a Claude cutoff. They stop only if the Mac restarts or sleeps for long; then simply run the commands below again.

**Pauses until your allowance resets:** the `main-verify` lead and its adversary (they are Claude sessions). Everything they already wrote is on disk and the lead's conversation is saved. Resume with:
```bash
cd ~/kingsfield && claude --model sonnet --resume 3afaba8f-4a0c-473d-856e-276519909cbf
```

**Check Task 1 progress (no Claude needed):**
```bash
O=~/Kingsfield_Corpus/flcourts
wc -l $O/decisions.jsonl                      # decisions listed so far
find $O/text -name '*.txt' | wc -l            # opinion texts extracted so far
tail -2 $O/run.log $O/run_text_1dca.log       # latest lines
pgrep -fl fl_southern_reporter                # is it running?
```

**Restart or continue Task 1 by hand (safe to repeat; it skips what exists). Order: list, text, cites, match.**
```bash
cd ~/kingsfield/Verifier/judicial-intel-analytics/pipeline
PY=~/.venv-flsr/bin/python; O=~/Kingsfield_Corpus/flcourts
nice -n 10 caffeinate -i $PY fl_southern_reporter.py --stage list  --out $O     # all courts, 2008 to today
nice -n 10 caffeinate -i $PY fl_southern_reporter.py --stage text  --out $O     # opinions only, 3 workers; add --courts 2dca for one court
$PY fl_southern_reporter.py --stage cites --out $O                              # when text is done
$PY fl_southern_reporter.py --stage match --out $O                              # writes fl_southern_citations.csv + review_queue.jsonl
```

**Everything else is already committed** (`git log --oneline -15`), and `main` plus the handoff docs describe the rest. Unpushed commits: `git fetch && git log --oneline origin/main..main`; push with `git push origin main`.

## 11. Who made which commits on `main` (read from git, 2026-10-09)

The 56 commits between `2caafa1` and `565a0c0` split three ways. Reproduce with `git log --format='%h %an | %s' 2caafa1..565a0c0` and look for `Co-Authored-By` trailers.

| Group | Count | What it is | Reviewed by the adversary? |
|---|---|---|---|
| Author **Aaron Ray**, with a **Claude** co-author trailer | 16 | The cascade work done in Claude Code sessions: auth fixes, hook changes, chat-route verification Steps 1-4, the signoff `d06dec2`, the .gitignore, the Mike LibreOffice port | **Yes** up to `d06dec2` (signoff `chat-route-verify`) |
| Author **Kandy22** (the GitHub identity), **no Claude trailer** | 20 | The patch work: document-write gate (Part B), MCP gate, title read/list gates, ownership checks, analytics gate, jammed-cite scrub, crew abort (`apply_*.py` one-shot patch scripts were created in these commits) | **No.** These were not made by Claude Code. You say they came from Gemini; git cannot tell which outside tool, only that they came through the GitHub identity. |
| Author **Aaron Ray**, no trailer | 20 | Your own commits and merges (for example the Oct 8 merge `29efac5`, the WIP commit `540e748`) | Not applicable |

The adversary's 2026-10-09 run of the signoff tier found **11 failures** (526 tests) in the second group's code: crew abort not reaching every role, a stored analytics row with a split cite passing the read check, a council session saved under a project the caller does not own, a document-write bypass, a JSON-escaped-newline cite bypass, a name Gate 1 reads as a citation passing the identifier allowlist, and a disconnected tabular client still starting the model.
