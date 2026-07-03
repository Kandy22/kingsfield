# Citation Grounding Grinder — Runbook

Turns the benchmark's ungrounded quotes into quotes verified against **real CourtListener opinion text**. Resumable, idempotent, rate-limit-aware.

## Why this exists
The original pipeline called the CourtListener REST API directly from Python and kept
failing on rate limits, so only 87/1,979 entries (4.4%) ever got grounded. This system
routes fetches through the working CourtListener **MCP** `opinion_view` tool and decouples
*fetching* from *matching*, so the job completes incrementally without choking on the
~60 requests/hour limit or on opinion texts that are 30–80 KB each.

## The four scripts
- `make_queue.py` — builds `fetch_queue.json`: citations still needing grounding, ordered by how many benchmark entries each unlocks. Skips already-cached.
- `harvest.py` — scans persisted MCP tool-results on disk and writes full opinion text to `opinion_cache/<slug>.txt`. **No opinion text passes through the agent's context.**
- `ground.py` — fuzzy-matches each claimed quote against cached opinion text and writes a grounded verdict (`yes` / `unsure` / `no`) into `results_full.json`.
- `cite_to_entries.json` — citation → benchmark entry indices map.

## Manual run (one batch)
1. `python3 make_queue.py` — refresh the queue, see what's left.
2. Take the top N citations from `fetch_queue.json` and, for each, call the MCP tool:
   `opinion_view { "identifier": "<cite>" }`  (e.g. `339 U.S. 306`). Large opinions
   auto-persist to disk; you do **not** need to echo them back.
3. `python3 harvest.py` — pull the fetched opinion text off disk into the cache.
4. `python3 ground.py` — score and update `results_full.json`.
5. `python3 make_queue.py` — refresh queue for the next batch.

## Scoring thresholds (see dataset README schema)
- fuzzy score ≥ 80 → `verified` → grounded verdict **yes**
- 55–79 → `fuzzy` → **unsure**
- < 55 → `not_found` → **no**

A quote scoring `no`/`unsure` is the high-value signal: it usually means the quote is
paraphrased, fragmentary, or misattributed (e.g. modern FRCP text pinned to a 1947 case).

## Notes
- ~848 of the 1,892 ungrounded entries have **no citation at all** and cannot be grounded
  by lookup — they need a different strategy (e.g. opinion_search by quote) or stay model-only.
- Roughly 806 citations remain queued, unlocking ~984 entries. At ~30/run that's ~1 month
  of daily runs, or faster with larger batches inside the hourly rate limit.
