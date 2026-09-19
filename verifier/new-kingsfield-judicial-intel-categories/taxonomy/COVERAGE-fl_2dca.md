# Coverage — fl_2dca (2026-09-19)

| Fact | Name | Status | Entities | Jev role |
|---|---|---|---|---|
| F01 | Career and Employment History | needs_trial_dockets | — | none |
| F02 | Educational Background | needs_trial_dockets | — | none |
| F03 | Professional and Political Affiliations | needs_trial_dockets | — | none |
| F04 | Practical Chambers Data | needs_trial_dockets | — | none |
| F05 | Active Cases | needs_trial_dockets | — | none |
| F06 | Average Case Length | needs_trial_dockets | — | none |
| F07 | Verdict Breakdown | needs_trial_dockets | — | none |
| F08 | Case Practice Area Breakdown | needs_trial_dockets | — | classify_incoming |
| F09 | Matter Type Breakdown | needs_trial_dockets | — | classify_incoming |
| F10 | Motion-by-Motion Success Rates | needs_trial_dockets | — | none |
| F11 | Comparative Motion Benchmarks | needs_trial_dockets | — | score_outlier |
| F12 | Disposition Breakdown | populated | court, appellate_judges(17) | none |
| F13 | Average Case Duration | populated | court, appellate_judges(17) | none |
| F14 | Average Time to Trial | needs_trial_dockets | — | none |
| F15 | Average Time to First Dismissal Order | needs_trial_dockets | — | none |
| F16 | State Court Motion Metrics | needs_trial_dockets | — | none |
| F17 | Timing Events | populated | court | none |
| F18 | Legal Findings | needs_trial_dockets | — | verify_against_opinion |
| F19 | Appeals Analytics | populated | court, appellate_judges(17), trial_judges(81) | none |
| F20 | Class Action Analytics | needs_trial_dockets | — | none |
| F21 | Entity Profiling | populated | counsel(22) | match_entity |
| F22 | Approximating a Judge | populated | court, appellate_judges(17) | score_rule_fit |
| F23 | Synthetic Legal Precedent Structures | needs_source | — | rank_neighbor |
| F24 | The Duty to Settle | needs_source | — | none |
| F25 | Jury and Voting Models | populated | court | none |
| F26 | Judicial Outcome Prediction | populated | court, cases(1416) | calibrate_or_abstain |
| F27 | Litigation Timelines | needs_trial_dockets | — | none |
| F28 | Forum and Strategy Optimization | needs_source | — | choose_forum |
| F29 | Counsel-Performance Analytics | populated | counsel(22) | none |

**9 of 29 facts populated** from the oral-argument pipeline. The rest need trial-court dockets (T1) or a source not yet integrated (see judicial-intel-analytics/DATA-SOURCES.md).
