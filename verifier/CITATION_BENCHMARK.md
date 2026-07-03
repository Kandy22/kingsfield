# Kingsfield Legal Citation Verification Benchmark

**Version:** 0.1  
**Released:** May 2026  
**Entries:** 1,979  
**License:** CC BY 4.0

---

## What This Is

A benchmark of 1,979 claimed legal quotations from Showalter's Law Dictionary, each attributed to court opinions. Three frontier models (Claude, Gemini, GPT-4o-mini) were asked whether each quote accurately appears in the cited case. The dataset records model verdicts, CourtListener fuzzy-match scores where available, and human review labels.

This is **not** a definitions dataset. It tests **citation verification** — the class of error that gets pro se litigants dismissed.

---

## Current Stats (June 2026)

| Metric | Value |
|--------|-------|
| Total entries | 1,979 |
| All 3 model verdicts | 1,780 |
| 3-way unanimous | 660 (33%) |
| Grounded in opinion text | 139 (7.0%) |
| Human labels | 200 |
| Citations queued for grounding | 803 |

**Grounding breakdown:** 87 via REST pipeline, 52 via MCP grinder (`opinion_cache/`).

---

## Key Findings

Only **33% unanimous** agreement across three models on a factual verification task. Models disagree on citation formalism vs. substantive accuracy — both matter in practice.

See [`benchmark_summary.md`](./benchmark_summary.md) for the initial 250-entry analysis. Full-dataset stats in `results_full.json`.

---

## Canonical Files

| File | Purpose |
|---|---|
| `results_full.json` | **Canonical dataset** |
| `kingsfield-verified-2026-06-01.json` | Export sync'd with canonical |
| `fetch_queue.json` | Citations still needing MCP fetch |
| `cite_to_entries.json` | Citation → entry index map |
| `opinion_cache/` | Cached CourtListener opinion text |
| `disagreements.json` | 96 high-value model disagreements |
| `sandbox.html` | Human review UI |

---

## Grounding Pipeline (Grinder)

See [`GRINDER.md`](./GRINDER.md).

```
make_queue.py → MCP opinion_view → harvest.py → ground.py
```

Thresholds: ≥80 verified, 55–79 fuzzy/unsure, <55 not_found.

---

## Data Schema

```json
{
  "idx": 1,
  "term": "ABSOLUTE PRIORITY RULE",
  "quote": "...",
  "all_cites": ["526 U.S. 434"],
  "opinion_found": false,
  "verification": { "score": 82.1, "status": "verified", "passage": "..." },
  "grounded_verdict": "yes",
  "human_verdict": "unsure",
  "agent_verdicts": {
    "claude": { "verdict": "yes", "reason": "..." },
    "gemini": { "verdict": "yes", "reason": "..." },
    "gpt":    { "verdict": "no",  "reason": "..." }
  },
  "source": "courtlistener"
}
```

**Verdict values:** `yes` | `no` | `unsure`  
**Source:** `courtlistener` (grounded) | `ai_direct` (model memory only)

---

## Known Limitations

- **848 entries** have no retrievable citation — cannot be CourtListener-grounded
- **213 entries** have no extractable quote from Showalter parse
- **1,175 Gemini reasons** truncated — re-run `archive/ai_verify.py --redo-gemini`
- Verbatim vs. substantive accuracy not yet distinguished in schema

---

## Citation

```
@dataset{kingsfield_citation_benchmark_2026,
  title     = {Kingsfield Legal Citation Verification Benchmark},
  author    = {Kingsfield},
  year      = {2026},
  version   = {0.1}
}
```