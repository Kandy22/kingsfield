# Kingsfield Legal Citation Benchmark — Findings

**Dataset:** Showalter's Law Dictionary — **1,979 entries** (full scale)  
**Updated:** June 2026  
**Models:** Claude Haiku 4.5, Gemini 2.5 Flash, GPT-4o-mini

---

## Full Dataset (results_full.json)

| Metric | Value |
|--------|-------|
| Total entries | 1,979 |
| All 3 model verdicts | 1,780 |
| 3-way unanimous | 660 (33%) |
| Grounded in opinion text | 139 (7.0%) |
| Human labels | 200 |

### Per-model distribution (entries with verdict)

| Model | Yes | No | Unsure |
|-------|-----|----|--------|
| Claude | ~784 | ~417 | ~579 |
| GPT-4o | ~915 | ~579 | ~286 |
| Gemini | ~390 | ~267 | ~1,123 |

Gemini says "unsure" far more often — many truncated reasons need `--redo-gemini`.

---

## Initial 250-Entry Sample (May 2026)

Early run before full AI verify completed:

| Model | Verified | Rejected | Unsure |
|-------|----------|----------|--------|
| Claude | 20.4% | 73.6% | 6.0% |
| Gemini | 44.4% | 55.2% | 0.4% |

**Inter-model agreement:** 61.3% agree, 38.7% disagree (96 entries in `disagreements.json`)

---

## What This Means

A **33–67% disagreement rate** on factual citation verification is significant. Models measure different things:

- **Claude** — stricter on citation formatting and malformed reporters
- **Gemini** — more "unsure", sometimes verifies substance from training knowledge
- **GPT** — highest "yes" rate

For legal practice, **both formalism and substance matter.**

---

## Next Steps

1. Continue MCP grinder — 803 citations queued (~973 entries unlockable)
2. Human review remaining ~1,779 entries (200 done)
3. Fix truncated Gemini reasons
4. Distinguish verbatim vs. substantive accuracy in schema
5. Publish to HuggingFace when grounding >25%