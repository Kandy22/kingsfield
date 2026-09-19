# Kingsfield Judicial Analytics — Handoff Prompt

Paste everything below into Claude Code, run from `/Users/aaronray/kingsfield/Verifier/judicial-intel-analytics/`.

---

## Project

Build "Moneyball for lawyers" — judicial analytics on **state elected judges**, Colorado first.

**Core thesis (mine, non-negotiable):** cultural and social signal about judges — music, film, books, sports, their public influences and close associations — is real, predictive, and undervalued precisely because everyone dismisses it. That is the Moneyball insight applied here. Do not talk me out of it; help me build it and let the data settle it.

**Second thesis:** political appointees rule strategically to position for elevation. Judges who audition for higher seats behave differently. This is testable.

**Deprioritized:** federal judges. They're appointed, don't campaign, generate no public cultural content, and their PII is legally scrubbed. Elected state judges are the target — they campaign, so they produce public material by necessity.

**Trial court docket data is the join target, not the insight.** I need it, but it's raw material. The signal comes from joining it to everything else.

## Where things stand

Working directory: `/Users/aaronray/kingsfield/Verifier/judicial-intel-analytics/`

Rebuild everything with one command:
```
python3 run_all.py                    # seed corpus, no network
CL_TOKEN=<token> python3 run_all.py   # full CourtListener pull
```
CourtListener API token is in the "Kingsfield Lawstopper" doc in Google Drive.

### Files

- `run_all.py` — orchestrator. build → ingest → coverage report.
- `build_co_judges.py` — drops and rebuilds `co_judges.db`, 15-table schema.
- `co_data.py` — all verified source data. A repull edits this one file.
- `ingest_opinions.py` — parses CourtListener panel strings into participation rows and co-panel edges. Has a `fetch_full()` that pages the API with a token.
- `co_clusters_seed.json` — 95 real Colorado Supreme Court clusters, works offline.
- `ingest_ojpe_2026.py` — parses the 123 OJPE evaluation narratives into `judge_accounts`, `cultural_signals` and commission-vote `judge_bio` rows. Verbatim evidence only.
- `parse_toolresult.py` — lifts the harvested narrative JSON out of saved browser tool-result files.
- `data/ojpe2026/narratives.json` — all 123 evaluation narratives, 373KB. The corpus for the keyword vectorizer.
- `maxent_panel.py` — pairwise MaxEnt (Ising) solver, exact MLE by state enumeration. Validated: recovers known couplings at r=0.982 with 1,000 samples.
- `co_judges.db` — SQLite, 15 tables.
- `MONEYBALL-BUILD-SPEC.md`, `DOCKET-EVENT-ONTOLOGY-v0.md` — architecture and the docket-entry event taxonomy.

### Database state — 7 of 15 tables populated

**Populated:**
- `judges` — 155. All 7 sitting CO Supreme justices, 21 historic justices, the full 2026 OJPE retention slate, and 5 workspace district judges.
- `judge_bio` — 130 rows, including a verbatim commission-vote string for each of the 123 ballot judges.
- `retention_elections` — 124 rows. 123 judges + one deliberate conflict row (see Christiansen below).
- `judge_accounts` — 334 rows: 123 evaluation pages, 107 2026 survey-report PDFs, 104 interim survey PDFs.
- `cultural_signals` — 562 rows across 122 of the 123 ballot judges. Only Michael Patrick Halpin (Custer County) yields nothing.
- `opinions` — 109 panel participation rows.
- `judge_edges` — 40 co-panel edges.

`cultural_signals` by category: career_track 213, education 165, civic 56, award 27, leisure 22, origin 19, clerkship 17, sports 12, teaching 12, family 11, faith 3, military 3, arts 2.

**Empty, in priority order:**
1. `keyword_observations` — spin per keyword per shared window, feeds `maxent_panel.py`. The corpus for this now exists (`data/ojpe2026/narratives.json`).
2. `vacancy_events` + `shortlist_membership` — the auditioning design
3. `contributions` — FollowTheMoney
4. `press_mentions` — GDELT
5. `motion_rulings` — CO AOC bulk docket request
6. `media_sessions` — cojudicial.ompnetwork.org
7. `district_geodemo` — PRIZM/Mosaic at district level
8. `financial_interests`

## Do these next

**1. Resolve official bio URLs into `judge_accounts`.** `coloradojudicial.gov` is fetchable (OJPE is not) and its per-court directory pages enumerate every judge with a `/contact/<slug>` link. Slugs are NOT derivable — "A. Bruce Jones" is `bruce-jones` — so they must be read off the directory pages, roughly 25 fetches. This also gives an independent second source for district and county, which is how the ordinal-district bug below would have been caught immediately.

**2. Build `keyword_observations` and run the solver.** The corpus is now in hand: 123 narratives, 373KB, one per ballot judge. Read Lee, Katz, Bommarito & Ginsparg before writing the vectorizer — element positive if that judge used a given keyword. Note the sample-size table below: with N=7 you need ~250 observations before the fit means anything, and 123 documents across 123 judges is one observation each, so the spin has to be built over shared windows or shared vocabulary, not per judge.

**3. Scale `opinions` with the token.** Seed is 95 clusters; the full Colorado set is ~2,786.

**4. Widen the cultural corpus beyond OJPE.** The narratives give education, career track and civic reliably, but direct taste — music, film, books, sports — appears for only ~30 judges and never as a questionnaire answer. The remaining channels: oral-argument video at cojudicial.ompnetwork.org, CBA bar journal profiles, investiture speeches, and the 2020/2022/2024 evaluation narratives for the same judges (longitudinal, and the URL pattern is the same with the year swapped).

**5. Auditioning study.** Within-judge ruling shifts timed to vacancies above them. Alexander is a natural case: unanimous MEETS in 2020, DOES NOT MEET on a 7-3 vote in 2026.

## Sample size — memorize this

From `maxent_panel.py`, N=7 (21 couplings), true coupling scale 0.3:

- 25 observations → RMSE 10.8. Errors 30x the signal. Garbage.
- 50 → RMSE 5.1. Still noise.
- 250 → RMSE 0.14. First usable point.
- 1,000 → RMSE 0.053. Solid.

Always run the included control: on a simulated court with no true coupling, the pairwise model's gain over independent voting is 0.004 nats/case versus 1.386 on a coupled court. Run that before believing any J matrix.

## Traps found the hard way

0. **`judicial_district` was the ordinal position of a section on the OJPE landing page, not the district number.** 52 of 65 district judges carried a wrong district — Datz stored 3 (actually 17th), Amico 4 (18th), Kotlarczyk 5 (20th). Corrected 2026-09-06 from the OJPE **full-list** page. Any analysis joined on district before that date is invalid. Always cross-check a district against `coloradojudicial.gov/contact/<slug>`, which states it plainly.

0a. **Identity was keyed on surname alone.** That silently dropped Costilla County's Tamara McSherry Sullivan and hung her retention row on Court of Appeals Judge Grant Sullivan — the source of the duplicate. The 2026 slate also holds two Larsons, two Hendersons and a Thomas/Martinez-Thomas pair. Identity is now the normalised full name; surname is kept only as a fallback and only when it is unambiguous.

0b. **Judges standing for retention may not campaign** unless there is active opposition (Colorado Code of Judicial Conduct). There are therefore almost no campaign sites, committees or candidate questionnaires. A null campaign account is a verified null, not a missing lookup. No organised 2026 opposition committee was found; confirm against SoS TRACER before concluding zero.

0c. **Three judges drew unfavorable 2026 findings, not one.** Boyce (16th, Crowley), Alexander (10th, Pueblo, 7-3 vote) and Christiansen (13th). Christiansen's ballot-facing recommendation reads MEETS, but that is the **State Commission overriding** the 13th JD commission's DOES NOT MEET after a Rule 21 complaint established the district commission had skipped the mandated initial interim evaluation. Both findings are stored in `retention_elections`. Do not treat her as a clean MEETS.

0d. **judicialperformance.colorado.gov 403s every non-browser client** — WebFetch and plain curl alike. It is readable in a normal browser session. Do not spoof a user agent to get around it; that is the rule and it is not worth the exposure. Oversized browser results are written to disk by the harness, which is how the 373KB corpus reached the workspace without passing through context.

1. **CourtListener has no authorship or dissent typing for `colo`.** Every sub-opinion is `010combined` with a null author. But the cluster-level `judges` string *is* populated ~1995–2016 and lists panel members. Dissent markers survive as OCR noise — "Dlssents", "Does". Capture as a cluster flag; never attribute to a justice. Participation is not authorship. No grant or dissent rate from this table.
2. **Nathan B. Coats was missing from every roster source** — Chief Justice 2018–2020, served 2000–2020, appointed by Bill Owens, the **only Republican appointee** in the file. He surfaced only as an unmatched-token count in the parser. Always print unmatched tokens; they find roster holes.
3. ~~**The OJPE 2026 page truncates at Jefferson County.**~~ CLOSED 2026-09-06. That was an artefact of the paginated `know-your-judges` landing page. The **full-list** page — `/2026-judicial-performance-evaluations-full-list` — enumerates every district and every county and states explicitly where nobody is standing. Real slate is **123 judges**, independently confirmed by Colorado Politics 2026-08-04. Use the full-list page, never the landing page.
4. **Ballotpedia's "next retention" column conflicts with the OJPE slate** — lists Hood at 2024 while OJPE has him standing 2026. OJPE is authoritative. Ballotpedia values are stored separately, flagged unverified.
5. **The `judicialperformance*.csv` files in `judges/` are junk** — 5 of 6 are browser table-scrapes of navigation menus and Google Translate language lists. Only the root one has real content. Discard and refetch.
6. **SCDB (scdb.wustl.edu) is blocked by the egress allowlist** on both the container and the local VM. If you need per-justice SCOTUS votes, download manually.

## Sources that work

- CourtListener bulk, quarterly, S3 `com-courtlistener-storage`, CC0: https://wiki.free.law/c/courtlistener/help/api/bulk-data/bulk-legal-data
- FJC Integrated Database (federal case outcomes, 1979–present): https://www.fjc.gov/research/federal-court-cases-fjc-integrated-database-1979-present
- Colorado OJPE 2026 evaluations: https://judicialperformance.colorado.gov/know-your-judges/2026-judicial-performance-evaluations
- Colorado Judicial Branch: https://www.coloradojudicial.gov/supreme-court/supreme-court-judges-and-staff
- Ballotpedia Colorado Supreme Court: https://ballotpedia.org/Colorado_Supreme_Court
- FollowTheMoney / OpenSecrets — judicial campaign finance (merged 2021)
- GDELT — free structured news with entity extraction
- Colorado oral argument video: cojudicial.ompnetwork.org

## Rules

- **Every derived field carries `src` and `retrieved_at`.** Unknown is NULL, never a guess.
- **Where sources conflict, store both and flag it.** Do not silently pick one.
- **Record gaps in the `data_gaps` table**, not in prose. Print them every run.
- **Print unmatched tokens on every parse.** That's how roster holes get found.
- **Get state court data by AOC records request, not by scraping.** No WAF evasion, no fingerprint spoofing, no CAPTCHA solvers against court systems. The federal corpus is a free licensed download; state AOCs will hand over bulk data on request. Not worth the exposure and it costs the LAFLA and court partnerships.
- **Verify any vendor before it enters a schema.** Nyne.ai and SociaVault have been asserted repeatedly with no evidence they exist or where their data comes from. Platform APIs stopped exposing likes years ago — ask any vendor claiming that data where it originates before building around it.
- **Disposition codes must separate** denied-without-prejudice, denied-as-moot, and taken-under-advisement from plain denials. Segregate agreed orders. Exclude proposed orders (a filing that says "Text of Proposed Order Granting Motion" is a party document, not a ruling). Conflating these corrupts every grant rate.
- **Three clocks per docket entry:** filing date, judge's signature date, clerk's entry date. Time-to-ruling uses signature minus filing. Entry date bakes clerk lag into the judge's number.

## Reference

- Lee, Katz, Bommarito & Ginsparg — *Sensitivity of collective outcomes identifies pivotal components*. In the Judicial Analytics project. The MaxEnt method, including the Twitter keyword construction.
- Black & Owens (AJPS 2016) — circuit judges on Supreme Court shortlists shift voting toward the president. The auditioning result.
- Huber & Gordon (AJPS 2004) — judges sentence more harshly as elections approach. The retention-election result.
- Eren & Mocan (AEJ: Applied 2018) — Louisiana juvenile judges sentenced more harshly after unexpected LSU football losses. Direct causal evidence that cultural attachment moves rulings.

Verify effect sizes in the originals before quoting any of them.
