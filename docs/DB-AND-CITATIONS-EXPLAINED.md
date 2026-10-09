# The Florida citation database, the citation datasets, and every label, explained

Written 2026-10-09. Plain English first, then exact names. Facts here were read from the code and the database on that date.

## 1. What this is, in one paragraph

Kingsfield checks every Florida case citation an AI writes **against a local database before the user sees it**. If a Florida citation is not in the database (or anything goes wrong), the check says **veto**, and the app withholds the whole answer. The database is a 46 MB SQLite file, `~/kingsfield/kingsfield_florida.db`, built from CourtListener's free bulk data. It lives only on your Mac right now (not on any server, not in git).

## 2. How the database was built

| | |
|---|---|
| Built | 2026-10-08, 15:28 to 16:19 (51 minutes, one CPU core), then page ranges added 21:50 |
| Source files | `~/Kingsfield_Corpus/`: `citations-2026-09-30.csv.bz2`, `opinion-clusters-2026-09-30.csv.bz2`, `dockets-2026-09-30.csv.bz2` (CourtListener bulk data dated 2026-09-30, 7.2 GB compressed) |
| Script | `db/build_sqlite_index.py` (rebuild: `cd ~/kingsfield && ~/.venv-cascade/bin/python db/build_sqlite_index.py --corpus ~/Kingsfield_Corpus`) |
| Kept | Florida courts only: the Florida Supreme Court (`fla`) and the district courts of appeal (`fladistctapp`), plus any case with a Florida Law Weekly citation |
| Result | 391,465 citation rows for 369,866 distinct cases (324,373 DCA rows, 67,053 Supreme Court rows, 39 with no court) |
| By reporter | So. 2d 248,892 · So. 3d 106,017 · Fla. L. Weekly 17,447 · So. (first series) 15,005 · Fla. L. Weekly Supp. 4,104 |
| Scanned and discarded | 18,130,235 citation rows were read; only the Florida ones above were kept |
| Not included | Opinion full text (the 55 GB `opinions` file was skipped; it is only needed for quote checking, Gate 2). No headnotes or key numbers (the ROSS ruling). |

## 3. What is inside it (three tables, kept apart on purpose: Constraint B)

| Table | Holds | Never holds |
|---|---|---|
| `citation_index` | one row per citation: reporter, volume, page, section, case id, case name, court, first page, last page, where the page range came from | opinion text |
| `caselaw_opinion` | raw opinion text (currently empty) | AI summaries |
| `caselaw_analysis` | AI-written summaries and good-law tags (currently empty) | raw opinion text |

Never write AI text into the same table as court text.

### Page ranges (read this)
A **pin cite** is a page inside a case, like `618 So. 2d 177, 181`. To check it, the database needs the case's last page. CourtListener's files do not include that. So the last page was **inferred**: *the page where the next case in the same volume begins*.
- 386,679 rows have an inferred last page (`bounds_source = inferred_next_case`).
- 4,786 rows have none (last case in its volume); a pin cite on those is vetoed as `pin_unverifiable`.
- Weakness: a pin a page or two past the real end of a case can slip through. Real printed ranges (Caselaw Access Project) would replace the inferred ones later; the column `bounds_source` marks which rows to replace.

## 4. How a citation is checked (Gate 1, the existence check)

Code: `pipeline/gate1.py` (Python) and `backend/src/verification/local_sqlite_gate.ts` (TypeScript, same rules line for line). No AI, no internet, same answer every time.

1. **Is it a Florida citation?** Florida keys are `So.`, `So. 2d`, `So. 3d` with a Florida court in the parenthetical, plus `Fla. L. Weekly` and `Fla. L. Weekly Supp.`. A Southern Reporter citation with **no** court in the parentheses is vetoed as malformed (the Southern Reporter also covers Alabama, Louisiana and Mississippi).
2. **Not Florida** (federal and other states): outcome is `fall_through`: it goes to CourtListener's live lookup.
3. **Florida:** look up (reporter, volume, page) in `citation_index`. No match means veto.
4. If a case name was given, its words must match the stored name; if a pin was given, it must fall between the first and last page.
5. Anything that goes wrong (missing database, error, timeout, odd characters) is a veto: it **fails closed**.

## 5. The labels you will see

### 5a. Gate 1's three outcomes
| Label | Meaning |
|---|---|
| `pass` | Florida citation found locally; name and pin (if given) check out |
| `veto` | Florida (or malformed Southern Reporter) citation failed any check, or anything errored |
| `fall_through` | Not a Florida key; sent to CourtListener |

### 5b. Verdict status shown to the app (`GateVerdict.status`)
| Status | Meaning | What the user gets |
|---|---|---|
| `verified` | passed every gate: exists, no failed quote, Gate 3 not yellow/red, Gate 4 `mandatory` | the answer, unchanged |
| `conditional` | the case exists and nothing is disqualifying, but Gate 3 says `yellow` (caution) **or** Gate 4 says the case is not `mandatory` authority (persuasive or off-point) | the answer unchanged; the note is recorded |
| `vetoed` | failed Gate 1 (existence), **or** Gate 3 is `red` (overruled or reversed), **or** a quote was attributed and Gate 2 says it is not in the opinion | **the whole answer is withheld**: "This answer was withheld because it cited a case that could not be verified." |
| `pending` | not finished checking | treated as vetoed |
Any verification **error** also withholds the answer ("could not be verified and was withheld").

### 5c. The four gates on each verdict
| Field | Values |
|---|---|
| `gate1_existence` | true / false: does the case exist (local database for Florida, CourtListener otherwise) |
| `gate2_quote_accuracy` | true / false / null (null when no quote was attributed): is the quoted text really in the opinion |
| `gate3_currency` | `green` (good law) / `yellow` (caution) / `red` (overruled or reversed) / null |
| `gate4_jurisdiction_fit` | `mandatory` (binds this court) / `persuasive` / `off-point` / null |

### 5d. Veto reason codes (the `notes` on a veto)
| Code | In plain words |
|---|---|
| `not_found` | Florida citation, no such row in the database |
| `db_unavailable` | the database file is missing or unreadable (every Florida cite fails closed) |
| `pin_unverifiable` | a pin cite was given but the case has no stored last page |
| `unresolved_short_cite` | "Id." or a short form that does not point back to any citation in the text |
| `ambiguous_short_cite` | a short form that could point to more than one case |
| `antecedent_vetoed` | a short form whose full citation was itself vetoed |
| `unparseable` / `unparsed_citation` | looks like a citation but does not fit the strict grammar |
| `multiple_citations` | one citation slot contains several citations |
| `extractor_disagreement` / `extractor_error` | the two independent parsers (eyecite and the strict grammar) disagreed, or one crashed |
| `non_ascii_citation` / `bad_encoding` | hidden or look-alike characters (a trick used to slip a fake cite past a checker) |
| `florida_court_unknown_reporter` | a Florida court in the parentheses but a reporter the system does not know |
| `too_long` | input too long to check safely |
| `internal_error` | something broke; the check fails closed |

### 5e. Router labels (not wired into the app yet)
`boolean_search`, `vector_search`, `direct_db`: which lookup method the local JEV router picks; anything uncertain becomes `direct_db`. See `docs/HANDOFF-RUN-WITHOUT-CLAUDE.md` section 8.

### 5f. Human review labels (the review tool, Task 2)
| Label | Key | Meaning |
|---|---|---|
| Correct | 1 | the citation really refers to this decision |
| Incorrect | 2 | the citation points to the wrong decision, or does not exist |
| N/A | 3 | not defined anywhere in your instruction file. Proposed definition, to confirm: the row cannot be judged (citation cut off, source unreadable, or not a case citation). Decide this before anyone labels, because the benchmark card says the labeling protocol is missing. |
Jev pre-labels each row (yes/no plus confidence) to sort the lowest-confidence rows first. The tool records who labeled, whether Jev's answer was shown, and the date. The review tool itself (`Verifier/sandbox.html`) has **not** been rebuilt yet; only the June version exists.

## 6. The second dataset: Florida decisions matched to their So. 2d / So. 3d citation (Task 1)

A court's own listing gives a case number and style but not its reporter cite. The reporter cite appears in **later opinions** that cite the case. The pipeline reads those later opinions and matches each printed citation back to the decision.

| | |
|---|---|
| Script | `Verifier/judicial-intel-analytics/pipeline/fl_southern_reporter.py` (committed `664e7ad`) |
| Stages | `list` (court listings, 2008 to today, 7 courts, opinions and PCAs) then `text` (each PDF is read into memory, turned into text, and **never saved**) then `cites` (eyecite finds `So. 2d`/`So. 3d` citations) then `match` |
| Where data goes | `~/Kingsfield_Corpus/flcourts/` (`decisions.jsonl`, `text/`, `cites.jsonl`, `fl_southern_citations.csv`, `review_queue.jsonl`, `run.log`) |
| Matching rule | same court, same year, and the case-name score (rapidfuzz token_set_ratio) is 85 or higher **and** beats the next candidate by at least 5 points. Otherwise the row goes to `review_queue.jsonl` for a human. |
| Test result | 2nd DCA 2020: 517 opinions + 1,071 PCAs (exactly the API's count); 25 PDFs became text; 141 `So.` citations extracted |
| Status | **running** (listing, then text; the text stage takes many hours, resumable) |
| Output columns | `case_number, court, decided_date, case_style, reporter_cite, source_opinion, name_score, n_citing, lawdiver_agrees, status` |
| `status` | `accepted` (met the rule). Rows that did not meet it are not in the CSV; they are in `review_queue.jsonl`. |
| `n_citing` | how many different later opinions printed this same citation for the decision: more is more reliable |
| `lawdiver_agrees` | empty until the optional LawDiver cross-check (needs a free LawDiver key) is run |

## 7. How to check one citation by hand (no AI, no app)

```bash
cd ~/kingsfield
sqlite3 -readonly -header -column kingsfield_florida.db \
  "select reporter, volume, page, case_name, court_id, first_page, last_page, bounds_source
   from citation_index where reporter='So. 2d' and volume=618 and page=177;"
```
A row back means Gate 1 would pass it; no row means veto. Or run the real gate:
```bash
~/.venv-cascade/bin/python pipeline/gate1.py --citation "Tanner v. Hartog, 618 So. 2d 177 (Fla. 1993)"
```

## 8. Limits to know

- The database is local only; production needs a copy (otherwise every Florida citation vetoes as `db_unavailable`).
- Page ranges are inferred, not printed ranges.
- Gate 1 proves a citation **exists**, not that the case says what the AI claims. That is Gate 2 (quote check), which needs opinion text the database does not yet hold.
- It covers Florida appellate courts only (Supreme Court and DCAs), not Florida trial courts.
- Today's fixes are on `main` but the final adversary signoff (`main-verify`) was still running when this was written.

## 9. How this maps to your business plan (BP)

The BP is `to sort/Kingsfield Bus Plan/Kingsfield_Business_Plan_2026_v2.docx` (main plan, section 4.2 "Three Agent Layers"; **dated 2026-05-20**), plus `business-plan/Kingsfield_BP_v3_Additions.docx` (**2026-05-21**). Both are about 4.5 months old and pre-date everything in this document, so they describe the intended product, not the current state. What the BP promises, and what exists today:

| BP promise | Built? |
|---|---|
| "Every citation verified through a 4-gate pipeline before it surfaces" (Gates: existence, quote accuracy, currency, jurisdiction fit) | **Gate 1 yes** (local database, this document). Gates 2-4 exist in `backend/src/verification/pipeline.ts` using CourtListener; Gate 2 needs opinion text the database does not hold yet. |
| "The Skeptic always runs with hard veto: halts output if a citation fails Gate 1" | **Yes in effect**: any veto withholds the whole answer (chat, project chat, tabular, crew, council). |
| "Verification Council: nine adversarial reviewers; every output GREEN, AMBER or RED" | **Not built.** What exists is the four-status verdict. Proposed mapping, to confirm: `verified` = GREEN, `conditional` = AMBER, `vetoed` / `pending` / error = RED. |
| "Targets sub-5% residual error through adversarial human-in-the-loop review" | **Not measured.** The benchmark card (Hugging Face `legal-citation-benchmark`) shows the unverified models' error rates; no residual-error number exists for Kingsfield itself. The human review tool (Task 2) is what would produce it. |
| "Calibrated Kingsfield confidence score" (Oct 3 Task 3.3) | **Not built.** The router's 0.80 threshold is a placeholder. |


## 10. The Task 1 numbers, explained (what "5,166 decisions" and "391,465" each mean)

These are different things; do not compare them.

| Number | What it counts | Where it is |
|---|---|---|
| **391,465** | **citation rows in the finished database**: one per reporter citation like `618 So. 2d 177`, for Florida cases already in CourtListener | `kingsfield_florida.db`. Built. Used by Gate 1 to say a citation exists. |
| **"decisions"** (5,166 at 6:44 AM, 58,169 at 7:20 AM, final about 250,000 to 300,000) | **documents the Florida courts published**, one row each, straight from the courts' own website listing. Not citations. | `~/Kingsfield_Corpus/flcourts/decisions.jsonl`. Still being collected. |

**Court codes:** `1dca` to `5dca` are Florida's First to Fifth District Courts of Appeal; `6dca` is the Sixth (it started in 2023, so 2008 to 2022 is empty); `supremecourt` is the Florida Supreme Court.
**`opinions` vs `pca`:** an `opinion` is a written decision with reasoning (these contain the citations the pipeline reads). A `pca` ("per curiam affirmed") is a one-line order with no opinion text; PCAs only need listing, because their reporter cite is printed by *later* opinions that cite them. So the text stage now downloads **opinions only** (override with `--kinds opinions,pca`).

**What Task 1 is for:** the court listing says "case 18-0525 decided 2020-12-30" but not "842 So. 2d 1057". Later opinions print that cite. The pipeline reads the later opinions' text, finds each `So. 2d`/`So. 3d` citation, and matches it back to the decision (same court + year + case-name score at least 85 and 5 above the runner-up). Output: `fl_southern_citations.csv` (a decision-to-citation table) and `review_queue.jsonl` (what a human must label).

**Two different things both called "text/transcripts" (do not mix them):**
| | Task 1 "text" | Judicial analytics "transcripts" |
|---|---|---|
| What | the **words of written opinions** (court PDFs turned into text; PDFs are never saved) | the **words spoken in oral-argument videos** |
| Where | `~/Kingsfield_Corpus/flcourts/text/<court>/` | `Verifier/judicial-intel-analytics/data/fl_2dca/` : `captions/` 2,892 files (`.vtt` YouTube captions + `.info.json`), `audio/` 426 downloads, `transcripts/` 1,447 files (`.turns.json`, speaker turns), `panel/` Jev scoring results |
| Used for | extracting citations (Task 1) | Jev scoring of arguments; the offer catalog (snapshots: `fl_2dca/cases.jsonl` 1,416 cases, `fl_6dca/cases.jsonl` 98 cases) |

**Time (corrected):** list about 3 hours total (about 2 more now); text about 10 to 11 hours after the speed-up (3 parallel fetchers, opinions only; measured 30 PDFs in 9 seconds); citation extraction about 1 hour; match, minutes. The 1st DCA text stage was started early (its listing is done), so overall about 14 to 15 hours from 6:35 AM, running unattended.

## 11. What to do and say about the databases (checked against the business plan, whose cover title is "Smart. Not Stupid."; see `docs/BP-VS-REALITY-2026-10-09.md`)

**Citation database (`kingsfield_florida.db`)**
- Say: "Gate 1 checks that a Florida citation exists in a local index of public reporter citations (reporter, volume, page, case name, court), built from CourtListener's bulk data." Say that anything it cannot confirm is withheld, not shown.
- Do not say: that it verifies a case *says what the AI claims* (that is Gate 2, not built on this data); that it covers trial courts or other states; that page ranges are the printed ranges (they are inferred); or that it guarantees no hallucinations (the benchmark shows the unverified-model error rates; Kingsfield's own residual error is not measured).
- Keep: opinion text and AI summaries in separate tables (Constraint B). No headnotes, key numbers or editorial synopses are ingested (the ROSS ruling); keep it that way, including from LawDiver or any Westlaw/Lexis product.
- Before redistributing the database file or serving it publicly, re-check CourtListener's current bulk-data terms and keep attribution. It is local and not distributed today.

**Judicial analytics data**
- Say: the Jev outputs are a lift-with-abstention signal (best signal `skepticism_gap`; `ruling_lean` only at confidence 0.7 or more), not an accuracy model; never report a mean score; state the abstention rule and the labeling protocol.
- Keep raw captions, audio and PDFs local; publish derived statistics and code only (your rule: code only to GitHub).
- **Check now:** the public GitHub repo still tracks third-party material (for example a Trellis case-documents PDF under `verifier/judicial-intel/attornies-data/` and the July backup of many documents). Decide whether the repo stays public before any claim is made about the data.
- Have counsel (your licensed-attorney anchor in the BP) confirm any fair-use position before it is stated publicly; this document is not legal advice.
