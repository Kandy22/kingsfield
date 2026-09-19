# Kingsfield Judicial Intelligence — offer catalog

Machine-readable tree for what Kingsfield will **offer**, modeled on public product surfaces:

| Top | Modeled on |
|---|---|
| T1 State Trial Court Intelligence | Trellis Research (state raw dockets) |
| T2 Enterprise and Federal Court Analytics | Lex Machina |
| T3 Computational and Predictive Modeling | Wolfram Demonstrations, Pre/Dicta, Premonition |

Six capability mains sit under those tops. Twenty-nine factual fields are the SKUs.

```
kingsfield-judicial-intel/
  README.md
  data/catalog.json          # source of truth
  taxonomy/TREE.md           # indented 3 / 6 / 29
  taxonomy/OFFER.md          # one-sentence list
  src/types.ts               # TS contracts
  src/catalog.ts             # loaders + asserts
  src/catalog.py             # python loader; prints OFFER.md
```

```bash
python src/catalog.py                              # print OFFER.md
python src/build_snapshots.py --channel fl_2dca    # populate the catalog from the OA pipeline
python src/voting.py                               # F25 math check
```

## Implementation (2026-09-19)

| File | Role |
|---|---|
| `src/value_types.py` | Schemas for every `value_type` the catalog names (`appeals_row`, `probability_card`, `decision_tree`, `counsel_judge_row[]`, …) + `validate()`. Mirrored in `types.ts`. |
| `src/sources.py` | Readers for `judicial-intel-analytics/data/<channel>/` (flcourts decisions, Jev panel CSV, dockets). Set `$KINGSFIELD_DATA` to point elsewhere. |
| `src/build_snapshots.py` | Producers + snapshot writer. Emits `JudgeIntelSnapshot`s to `data/snapshots/<channel>/` (court, appellate judges, trial-judge appellate trails, counsel dossier, per-case F26 cards) and `taxonomy/COVERAGE-<channel>.md`. |
| `src/voting.py` | F25: Condorcet majority probability, Banzhaf index. Pure math. |

**Populated today (FL 2DCA): 9 of 29** — F12 F13 F17 F19 F21 F22 F25 F26 F29 — from 1,416 argued
cases, 1,097 with a decision, 23,377 court decisions. See `taxonomy/COVERAGE-fl_2dca.md`.
The remaining 20 need trial-court dockets (T1) or a source listed in
`../judicial-intel-analytics/DATA-SOURCES.md`.

Rules the producers follow: every number is arithmetic on public records or on Jev panel
outputs already on disk (nothing here calls a model); every populated fact carries
provenance; rates carry n and a Wilson 95% CI; counsel rows below n=5 are suppressed;
F26 abstains when its calibration bin has n<20 or sits within ±10 points of the base rate.
The fitted F22 rule for 2DCA:

```
IF   skepticism_gap >= +1                      → affirm   p=0.95  n=208
ELIF skepticism_gap <= -1                      → p_affirm 0.44    n=57
ELIF conf >= 0.7 AND ruling_lean == affirm     → affirm   p=0.89  n=83
ELIF conf >= 0.7 AND ruling_lean == reverse    → p_affirm 0.23    n=22
ELSE abstain                                   → p ≈ base 0.74    n=727
```

This is a catalog, not a scrape. Do not ingest Trellis or Lex Machina pages. Populate fields from CourtListener, CAP, public state dockets, and models you train yourself.

Jev’s job on this tree is narrow: classify an incoming matter into F08/F09, flag F11 outliers, verify F18 findings against an opinion, match F21 entities, score F22 rule-fit, rank F23 neighbors, abstain on F26 when calibration is junk, choose among F28 forums. Everything else is tables and arithmetic.

Vendor marketing numbers (e.g. Pre/Dicta “85%”) are stored as *their* claim in docs, never as a Kingsfield accuracy field.
