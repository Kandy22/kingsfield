# Kingsfield Judicial Intelligence — Data Sources

Reorganized 2026-09-19 from the working list. Organized by **what each source does in
the pipeline**, tagged with the offer-catalog fields it populates
(`Verifier/new-kingsfield-judicial-intel-categories/taxonomy/TREE.md`, F01–F29), and
with the gotcha we learned when we actually used it.

Status key: **LIVE** = in the pipeline now · **NEXT** = concrete hook identified ·
**REF** = context only · **COMP** = competitor / comparable, never ingested.

---

## 1. Live in the pipeline

| Source | What it gives | Fields | Status · gotcha |
|---|---|---|---|
| **YouTube via yt-dlp** — FL 2DCA (`@seconddistrictcourtofappea8708`), FL 6DCA (`@floridasixthdistrictcourto8200`) | Oral-argument video, auto-captions, upload date, duration. Titles are case numbers only (2DCA) or date + case number (6DCA). | F19, F22, F26 | **LIVE** · Live-stream tabs are multi-case sessions; use the clip tab. Captions garble legal vocabulary ("may police court"). ~13 videos/min pull rate before YouTube paces you. |
| **Florida courts opinion search API** — `flcourts-media.flcourts.gov/_search/opinions/` (what each DCA's Opinions page calls; Juriscraper's `fladistctapp_N` wraps it) | Every decision per district: `case_number`, `case_style` (case name), `note` (the disposition text), opinion type (Authored / Per Curiam / **PCA** / Petition), date, PDF, ctrack id. `type=opinions` and `type=pca` are separate listings. | F12, F19, F18 (via PDF) | **LIVE** (`pipeline/enrich_flcourts.py`) · No auth, no observed throttle, ~100/page. This is the ground truth for `ruling_lean` and the court-wide base rates. Hit it at ≤2 req/s with an identifying UA. |
| **CourtListener REST API v4** (`fladistctapp`; token in `Verifier/.env`) | Opinion text incl. one-line PCAs; case name; panel, author, trial judge, county, counsel, dissent parsed from text. | F12, F18, F19, F01–F03 (people DB) | **LIVE** (`pipeline/enrich_dockets.py`) · **Account is throttled to 100 req/hour**; the session MCP connector shares the quota. Pre-2023 dockets stored as `19-0852` (no district prefix, collides across DCAs). Membership at donate.free.law raises the limit. Now the secondary source; flcourts is primary. |
| **TypeSafe Jev via OpenRouter** (`typesafe/jev-1.13`, `/api/alpha/decisions`) | Typed decisions over a transcript: skepticism scores per side, ruling lean, bench behaviors. | F19, F22, F26 | **LIVE** (`pipeline/run_oa_panel.py`) · $0.042/M input; 1,440 transcripts ≈ $0.55, ~4 s at 12 threads. Reads scoping words literally; no counting; keep math in Python. |
| **Charlotin AI Hallucination Cases** (daily CSV) | 1,469 incidents / 4,469 items of fabricated authority in filings; outcome, party type, court, tool. | F18, F29 | **LIVE** (`hallucination-registry/`) · Normalized; the `charlotin` Jev panel in `run_panel.py` is built and unrun. `party_type` is the blind variable. |

## 2. Integrate next — ordered by payoff, with the hook

| Source | Why now | Fields | Hook |
|---|---|---|---|
| **Juriscraper** (`freelawproject/juriscraper`) | Per-court scrapers for every US appellate court's opinions **and oral-argument audio** (`oral_args/united_states/federal_appellate/`). We already use its Florida endpoint; the OA-audio scrapers open the federal circuits to the same panel without video. | F19, F26 | `pip install juriscraper`; `oral_args.united_states.federal_appellate.<circuit>` → mp3 → Whisper → `build_transcripts` (roles from turn structure) → `run_oa_panel`. |
| **Eyecite** (`freelawproject/eyecite`) | Citation extraction/resolution from opinion and brief text. Replaces regex in the Verifier's citation benchmark and turns the registry's `||`-delimited "Hallucination Items" into structured cites. | F18 | `get_citations(text)` on `incident_items.csv` and on the Showalter benchmark inputs. |
| **CourtListener `/people/` + `retention-events` + `positions` + `political-affiliations` + `aba-ratings` + `financial-disclosures`** | The judge-bio backbone for the Colorado Moneyball DB — appointer, education, party, retention history — already structured. HANDOFF says CL lacks *opinion authorship* for `colo`; the people DB is a different table and is populated. | F01, F02, F03, F04 | `call_endpoint("people", {"positions__court": "colo"})`; cross-check `co_judges.db` districts (the ordinal-district bug would have been caught here). Same 100/hr limit. |
| **CourtListener `/audio/`** (oral-argument audio archive) | OA audio for federal circuits and some states — the non-YouTube route to argument transcripts. | F19, F26 | Search `type=oa`, filter by court; same Whisper → panel path as Juriscraper OA. |
| **Caselaw Access Project on Hugging Face** (`common-pile/caselaw_access_project`) | Full historical US caselaw (Harvard CAP) as a dataset — offline, no API quota. Covers the pre-2020 FL DCA cases whose old-format numbers (`2D19-852`) are painful on the API. | F12, F18, F23 | Filter the FL slice locally; index by docket number; join to old-format titles. Also the corpus for F23 precedent-structure work. |
| **Doctor** (`freelawproject/doctor`) | PDF → text, audio duration, thumbnailing as a service. We use `pdftotext -layout` today; Doctor is the same thing at scale with a stable API. | F18 | Point `enrich_flcourts.py --with-pdf` at a Doctor container when volume exceeds a few thousand PDFs. |
| **Colorado annual statistical reports** (`coloradojudicial.gov/annual-statistical-reports`) | Filings, dispositions, time-to-disposition per district per year — the denominators for every per-judge rate. | F05, F06, F13, F15 | Tables into `co_judges.db` as `district_baselines`; every judge-level rate is reported against its district baseline. |
| **Colorado Chief Justice Directives** (`coloradojudicial.gov/Courts/Supreme_Court/cjds`) | Dated policy events (livestreaming rules, case-management orders). Event markers for before/after analyses. | F17 | `policy_events` table: cjd_number, effective_date, subject. |
| **State Court Records guide** (Tyler McBrien, `tyler-mcbrien.github.io/state-court-records`) | State-by-state map of which AOCs provide bulk dockets and how. This is the map for the "records request, not scraping" rule. | T1 (F10, F16) | Use it to write the AOC requests; record each state's answer in `data_gaps`. |
| **Legal Data Hunter** (`legaldatahunter.com`; connected as an MCP in this workspace) | 38M documents, 230 jurisdictions; a second opinion-lookup path with its own quota. | F12, F18 | Probe `search` by docket number for FL DCAs; use as fallback when CL throttles. |
| **Inception** (`freelawproject/inception`) | Embedding generator tuned on legal text. | F23 | Neighbors for "synthetic precedent structures"; only after F23's design is set. |
| **X-Ray** (`freelawproject/x-ray`) | Detects bad (recoverable) redactions in PDFs. | evidence / pro se products | Niche; belongs to Publicus, not judicial intel. |

## 3. Reference only

| Source | Note |
|---|---|
| **SCDB** (`scdb.wustl.edu`, `scdb.la.psu.edu`) | SCOTUS votes 1791–present. Blocked by the egress allowlist; download manually. Design reference for the auditioning study (Black & Owens), not a state-judge input. |
| **Federal Rules Committee minutes** (`uscourts.gov/forms-rules/records-rules-committees`) | Policy context for federal procedure; no fields. |
| **GMU free legal research guide**, **wiki.free.law**, **free.law/open-source-tools** | Directories. Start here when a new source is needed; nothing to ingest. |
| **Open Legal Data** (`openlegaldata.io`) | German case law. Not US. |
| **Reuters Legal** | News. GDELT (in HANDOFF) is the structured route for press mentions (F03). |
| **Federal Register**, **USPTO data** | Regulatory / patents. Not judicial analytics; keep for a compliance product. |
| **Atticus Project (CUAD)** | Contract-clause dataset. Contracts product, not judicial. |
| **Federal Cameras in Courts archive** (N.D. Cal., W.D. Wash., Guam; 2016–2025) | Trial-court hearings hosted on uscourts.gov, not OA. Needs its own downloader and a trial-judge panel. |
| **Florida Virtual Courtroom Directory** | Circuit-court live streams (Zoom/YouTube). Trial-court product; natural home for the pro se questions. Live, mostly not archived. |
| **Colorado appellate video** (`cojudicial.ompnetwork.org`) | The real CO OA source; YouTube has only PSAs. OMP player — not yt-dlp; check for an HLS manifest, else records request. |
| **Affect / face databases** (AffectNet, Affect+, DU DIST) | Reference for the biometric layer (Phase 2). Jev never sees pixels; Python computes affect features, Jev scores words, the join is the product. |

## 4. Competitors and comparables — never ingested

Store their numbers as *their* claims. Do not scrape their pages (catalog README rule).

| Product | Models which top | Note |
|---|---|---|
| **Trellis** (`trellis.law`, `support.trellis.law/dockets`) | T1 state trial dockets + judge analytics | Direct competitor. Their docket docs are a useful schema reference for `DOCKET-EVENT-ONTOLOGY-v0.md`. |
| **Lex Machina** | T2 federal analytics | |
| **Pre/Dicta**, **Premonition** | T3 outcome prediction | "85%" is their claim, stored as such. |
| **Westlaw Quick Check** | Verifier comparable | Brief checker. |
| **midpage.ai** | AI legal research | |
| **LawGeex** | Contract review | Not judicial. |
| **UniCourt** (Datarade listings) | Commercial judge/docket API | Priced; a buy-vs-build benchmark for T1. |

## 5. Your own repos

| Repo | What it is | Role |
|---|---|---|
| **Kandy22/LawLink** (fork of `lawflow-boop/LawLink`, v1.3.2, MIT) | Self-hosted case/practice management: intake, conflicts, deadlines, documents, approvals. Next.js 16 / Postgres / Prisma. | **Delivery surface, not a source.** The place F-fields land inside a firm's case file (judge card on the matter, deadline risk from F13–F15). |
| **Kandy22/LibreTranslate** | Self-hosted MT. | Language Access Initiative (see `Legal AI 2026/Kingsfield_Language_Access_Initiative.docx`); pairs with the Virtual Courtroom / interpreter work. Not a data source. |

### 5b. More of your repos (added 2026-09-19)

| Repo | What it is | Role |
|---|---|---|
| **Kandy22/kingsfield** | The platform repo. | Home for everything above once it leaves `Verifier/`. |
| **Kandy22/mike** (fork of willchen96/mike, 600+ unsynced updates) | The video-analyzer lineage: real-time analysis of live court proceedings, hardened against hallucinations, Council-of-Experts review. | **The Phase-2 engine.** Its job on this pipeline is the per-turn rolling scorer (the "trader loop" shape) over live 2DCA/6DCA streams, and the biometric layer. Sync the fork before building on it. |
| **Kandy22/video-analyzer4**, **Kandy22/face-mood-tracker** | Frame extraction + MediaPipe blendshape mood scoring (the `analyze_signals.py` / `vibeviz_mood.py` port). | Biometric features per turn — Python computes, Jev never sees pixels; joined to the transcript panel. |
| **Kandy22/Wingman-demo** | In-ear real-time assistant. | Consumer of F26 cards + F22 rules live in the courtroom. |
| **Kandy22/legal-sources**, **Kandy22/awesome-legal-data** | Curated source lists. | Fold into this document; they're the long tail of §2–3. |
| **Kandy22/legal-reference-extraction** | Citation/reference extraction. | Compare against Eyecite before keeping both. |
| **Kandy22/openprobono** | Pro bono legal-aid assistant. | Pro se product surface; the pro se OA questions feed it. |
| **Kandy22/claude-for-legal** | Claude legal-workflow templates. | Reference for the deliberation layer (LLM) above Jev's decision layer. |
| **Kandy22/agent-operated-company** | Agent orchestration. | Reference for the Council-of-Experts harness. |
| **Kandy22/karakeep** | Bookmark/knowledge keeper. | Store for the sources in this doc. |
| **Kandy22/big-blue-marble** | "Make like LawDiver" — the map/visual front end. | Visualization surface for court/judge snapshots (`data/snapshots/`). |
| **Kandy22/images** | Hosted images. | Assets only. |

## 6. Not a data source — the show

"Legal Influencer Show" (All-In-style; hosts Robee Barnes, Bryan Freedman; law-school tour, moot court award, prediction markets, lifelines) is a **content product**. Two real links to this pipeline:

- **Prediction markets ↔ F26.** `ruling_lean` with its probability *is* a market-shaped signal; the flcourts join tells you how often the bench's tell was right. That's a segment.
- **The dataset is show material.** "Which 2DCA judge is hardest on appellants" and "how often does a hostile bench still affirm" are answerable from `oa_results.csv` today.

Moved out of the sources list so it stops looking like one.

---

### Rules carried over from HANDOFF.md

Every derived field carries `src` and `retrieved_at`. Unknown is NULL. Where sources
conflict, store both and flag it. Get state court data by AOC request, not by scraping; no
WAF evasion, no fingerprint spoofing, no CAPTCHA solvers. Verify any vendor before it enters
a schema. Three clocks per docket entry (filed / signed / entered).
