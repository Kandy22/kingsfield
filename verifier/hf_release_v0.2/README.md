---
license: cc-by-4.0
language:
- en
size_categories:
- 1K<n<10K
pretty_name: Kingsfield Legal Citation Verification Benchmark
tags:
- legal
- benchmark
- citation-verification
- hallucination
- llm-evaluation
configs:
- config_name: default
  data_files:
  - split: train
    path: results_full.json
---

# Kingsfield Legal Citation Verification Benchmark

**Version:** 0.2 · **Updated:** July 2026 · **Entries:** 1,979
**Models evaluated:** Claude Haiku 4.5, Gemini 2.5 Flash, GPT-4o-mini

---

## ⚠️ v0.2 corrects three errors in v0.1 — please re-download

If you downloaded v0.1 (June 2026), it has defects that affect any analysis you
ran. All three are fixed here, and nothing has been silently overwritten.

### 1. Every row was duplicated

v0.1 shipped `results_full.json` **and** `kingsfield-verified-2026-06-01.json`
in the repository root. The loader concatenated both, so
`load_dataset()` returned ~3,958 rows for a 1,979-entry benchmark — each entry
twice, and the two copies did not agree on every field.

**If you computed anything over v0.1, your denominator was roughly double.**

Fixed by declaring an explicit `configs:` block above that points at
`results_full.json` only. The v0.1 second export remains in the repository as
`kingsfield-verified-2026-06-01.json` for provenance — it is still downloadable
but is **no longer loaded** by `load_dataset()`.

### 2. 87 entries were scored against the wrong court opinion

The benchmark grounded quotes against real opinion text by two different
routes, which produced opposite results:

| route | n | verified | not_found | median fuzzy score |
|---|---|---|---|---|
| MCP `opinion_view` | 52 | **88.5%** | 3.8% | **100.0** |
| direct REST resolver | 87 | 2.3% | **80.5%** | 52.8 |

That is a resolver bug, not a data difference. The REST route wrote `cl_url`
values pointing at CourtListener cluster IDs in the 10.2M–10.7M range, which
are 2025–2026 filings. An entry citing 293 U.S. 474 (1935) or 378 U.S. 368
(1964) cannot resolve there. Spot checks confirmed it: an AEDPA-deference quote
was scored against an Oklahoma sheriff's-sale opinion; an adoptive-admission
quote against a Title VII retaliation opinion.

Those 87 entries now carry:

```json
"opinion_found": false,
"grounding_status": "needs_refetch",
"quarantine_reason": "...",
"verification_quarantined": { ...the discarded bad result... }
```

Nothing was deleted. `quarantine_report.json` lists all 87 with the bad cluster
IDs so the correction is auditable.

### 3. The grounding headline was overstated

v0.1 reported **"139 grounded in opinion text (7.0%)."** After removing the 87
mis-resolved entries the real figure is **55 (2.8%)** — of which **49 (89.1%)
verified**.

The apparent "these dictionary quotes don't check out" signal in v0.1 was the
resolver bug, not Showalter.

---

## What This Is

1,979 claimed legal quotations from Showalter's Law Dictionary, each attributed
to one or more court opinions. Three models were asked whether each quote
accurately appears in the cited case. The dataset records each model's verdict
and reasoning, human review labels, and — for a small verified subset —
deterministic fuzzy matching against real CourtListener opinion text.

This is **not** a definitions dataset. It tests **citation verification** — the
failure mode that gets litigants sanctioned.

---

## Stats

| Metric | Value | v0.1 said |
|--------|-------|-----------|
| Entries | 1,979 | 1,979 (but loaded as ~3,958) |
| With all 3 model verdicts | 1,780 | — |
| 3-way unanimous | 660 (**37.1%** of 1,780) | 33% (divided by 1,979) |
| Human labels | 200 — **139 usable** | 200 |
| Grounded vs. real opinion text | **55 (2.8%)** | 139 (7.0%) |
| — of those, verified | **49 (89.1%)** | — |
| Flagged `needs_refetch` | 87 | — |

---

## Headline result: model accuracy differs ~3x

Against the 139 human-labeled yes/no entries:

| Model | Correct | Error rate |
|-------|---------|-----------|
| Claude Haiku 4.5 | 92/104 | **11.5%** |
| Gemini 2.5 Flash | 86/119 | 27.7% |
| GPT-4o-mini | 84/120 | **30.0%** |

Cheap models get citation verification wrong roughly a third of the time.

*Caveat:* n = 104–120 per model, and the human labeling protocol is not
documented as blind to model output. Indicative, not definitive.

## Disagreement is high — and is not error

| Pair | Disagree |
|---|---|
| Claude vs GPT | 42.9% |
| Gemini vs GPT | 46.5% |
| Claude vs Gemini | 46.9% |

Only 37.1% of scored entries are 3-way unanimous. **These are disagreement
rates, not error rates** — two models can agree and both be wrong. Use the
accuracy table above for error rates.

**But consensus is a usable signal:** when all three models agree, the human
label contradicts them only **3 times in 53 (5.7%)**.

---

## Worked example: a fabricated citation inside the benchmark itself

Entry `idx: 1` (ABSOLUTE PRIORITY RULE) is the first row of this dataset. Claude
returned `"verdict": "yes"` with this rationale:

> This language is from the Absolute Priority Rule as established in **Case v.
> Los Alamos Grazing Ass'n, 308 U.S. 106 (1939)**, and is directly cited and
> discussed in **Dewsnup v. Timm, 526 U.S. 434 (1992)**, which addresses the
> rule's application in bankruptcy contexts.

Both citations are fabricated. Verified against CourtListener:

| As cited by the model | What the citation actually is | CL cluster |
|---|---|---|
| *Case v. Los Alamos Grazing Ass'n*, 308 U.S. 106 (1939) | ***Case v. Los Angeles Lumber Products Co.***, 308 U.S. 106 (1939), Douglas, J. | [103240](https://www.courtlistener.com/opinion/103240/) |
| *Dewsnup v. Timm*, 526 U.S. 434 (1992) | ***Bank of America N.T. & S.A. v. 203 North LaSalle Street Partnership***, 526 U.S. 434 (1999), Souter, J. | [118285](https://www.courtlistener.com/opinion/118285/) |

A full-text search of CourtListener (8.2M+ opinions) for `"Los Alamos Grazing"`
returns **zero results**. No such case exists.

**Why this example matters more than the summary tables.** The model had the
doctrine right and the reporter citations right. 308 U.S. 106 and 526 U.S. 434
are both real, both Supreme Court, and both genuinely about the absolute
priority rule — *203 North LaSalle* cites *Case v. Los Angeles Lumber* at that
exact page in its concurrence and dissent. The model kept the correct volume,
page, year, and even the "*Case v.*" party name, and invented only the second
party and one case name.

Everything a reader would spot-check at a glance is correct. That is the failure
mode this benchmark exists to measure, and it is sitting in row 1.

Note also that Gemini answered `"yes"` on the same entry with the reason
`"VERDICT: VERIFIED"` and no citation at all; GPT-4o-mini answered `"no"`. The
human label is `"unsure"`.

---

## Fields

| Field | Meaning |
|---|---|
| `idx` | Stable entry ID |
| `term` | Law-dictionary headword |
| `quote` | The claimed quotation |
| `all_cites` | Citations the dictionary attributes it to |
| `primary_cite_pair` | Resolved case name + citation, where known |
| `cl_cluster`, `cl_url` | CourtListener identifiers (null unless grounded) |
| `opinion_found` | True only where real opinion text was matched |
| `verification` | `{score, status, passage, matched_via}` — status ∈ verified / fuzzy / not_found |
| `grounded_verdict` | yes / unsure / no, derived from the fuzzy score |
| `human_verdict` | yes / no / unsure — 200 labeled, 139 usable as gold |
| `agent_verdicts` | Per-model `{verdict, reason}` |
| `correct_definition` | Reviewer-supplied correction, where recorded |
| `grounding_status` | `needs_refetch` on the 87 quarantined entries |
| `verification_quarantined` | The discarded bad result, retained for audit |

---

## Known limitations

- **97% of the benchmark is ungrounded.** Only 55 entries have been checked
  against real opinion text. Everything else rests on model verdicts plus 139
  human labels. This benchmark currently measures *what models believe about
  citations*, not *whether the citations are real*.
- 199 entries have no model verdicts at all.
- The human labeling protocol (who, blinding, adjudication rules) is
  undocumented.
- Model rationales in `agent_verdicts` are **unverified model output** and
  themselves contain fabricated citations — verified, see the worked example
  above for entry `idx: 1`. Do not treat the `reason` field as ground truth. It
  is evidence of what a model asserted, not authority for what the law says.
  The rationales have not been systematically audited; entry 1 was checked
  because it is the first row, which suggests the rate is not low.
- 87 entries await re-grounding through the MCP route.

## Planned work

Not yet done — listed so users know what this dataset does not currently
support.

1. **Re-ground the 87 quarantined entries** through the MCP route, and add a
   resolver guard that rejects any CourtListener cluster whose date is
   inconsistent with the cited reporter volume. That single check would have
   prevented the v0.1 defect.
2. **Clear the grounding backlog** — 803 citations queued. Grounding is the
   difference between measuring what models believe and measuring what is true.
3. **Audit the model rationales.** Entry 1's rationale contains two fabricated
   citations (see the worked example above). That is one confirmed instance from
   a sample of one, which establishes that the problem exists and says nothing
   about how often. The fix is to extract every citation from all 1,780
   `agent_verdicts.reason` fields and resolve each against CourtListener,
   producing a measured fabrication rate per model.

   This would arguably be the more useful dataset: not *can models verify
   citations*, but *do models fabricate citations while claiming to verify
   them*. It is not currently possible to answer that from this data.
4. **Document the human labeling protocol** — who labeled, whether they were
   blind to model output, and how disagreements were adjudicated. Until that
   exists, treat the accuracy table as indicative.

## Citation

```bibtex
@dataset{kingsfield_citation_benchmark_2026,
  title  = {Kingsfield Legal Citation Verification Benchmark},
  author = {Kingsfield Lawfare},
  year   = {2026},
  note   = {Version 0.2},
  url    = {https://huggingface.co/datasets/Kingsfield-Lawfare/legal-citation-benchmark}
}
```

License: CC BY 4.0. Source quotations are from Showalter's Law Dictionary;
opinion text is from CourtListener (Free Law Project), free of known copyright
restrictions.
