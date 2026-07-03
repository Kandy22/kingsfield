# Self-Improvement Loop Pattern — Kingsfield Lawfare
# Source: Zach Lloyd (@zachlloydtweets), June 16 2026
# Extracted and translated to Kingsfield architecture

---

## Core Pattern (Lloyd's original)

```
INNER LOOP
  Trigger: event (new issue filed)
  Agent: runs the Skill
  Output: label/classification applied
  Record: interaction logged (file, trace, Slack, GitHub)

      ↓ (feedback — human corrects wrong label + explains why)

OUTER LOOP
  Trigger: schedule (runs once/day)
  Agent: observes ALL inner loop runs since last cycle
  Input: records of every inner loop run + human corrections
  Output: DIFF to the Skill file (not a rewrite — a patch)
  Result: improved Skill feeds back into inner loop next run
```

Key constraint: **outer loop produces a diff, not a rewrite.**
Targeted patch only touches what changed. Full rewrite risks losing
correctly-compiled facts elsewhere in the skill/wiki page.

---

## Translation to Kingsfield

### Inner Loop = Wingman Session

```
INNER LOOP
  Trigger: Aaron launches wingman_live.py (selects agent)
  Agent: Gemini 3.1 Flash Live reads wiki → monitors audio
  Output: alerts fired (or not fired), session transcript
  Record: sessions/YYYYMMDD_HHMMSS_[agent].txt → Baserow log
  Feedback signals:
    - Alert fired but was wrong (noise) → Aaron dismisses it
    - Alert should have fired but didn't (miss) → Aaron notes it
    - Judge behaved differently than wiki profile predicted
    - Citation came up not in verified citations page
    - Trigger condition needs tightening or broadening
```

### Outer Loop = Wiki Refresh Agent

```
OUTER LOOP
  Trigger: scheduled (nightly or weekly depending on wiki type)
             OR: manual run after significant session
  Agent: Sonnet 4.6 (not Flash — needs reasoning for diff quality)
  Input: 
    - Session transcripts from Baserow since last refresh
    - Current wiki page versions (read-only during analysis)
    - GRADE verifier results from recent sessions
    - Any manual corrections Aaron flagged
  Process:
    1. Pull transcripts + corrections from Baserow
    2. Identify discrepancies vs. current wiki pages
    3. Produce TARGETED DIFFS to affected pages only
    4. Run diffs through grade_verifier.py before writing
    5. Write verified diffs, leave rest of page untouched
    6. Update Baserow: refresh record + new wiki version hash
  Output: patched wiki pages (diff only, not full regeneration)
```

---

## Wiki Page Field Types (Critical Distinction)

Not all fields should be diffable. Schema must define which are locked
vs. diffable to prevent wiki from becoming an unstable moving target.

### LOCKED fields (only update on explicit re-ingestion of source)
- Judge reversal rate (source: official court records)
- Statute text (source: official statute, version-controlled)
- Case holding (source: verified opinion text via CourtListener)
- Citation verification status (source: grade_verifier.py pass)

### DIFFABLE fields (update from session transcripts + outer loop)
- Judge documented behavior in pro se hearings
- Judge pet peeves observed in session
- Alert trigger conditions (tightened/broadened from miss/noise data)
- Witness prior statement cross-references (updated per deposition)
- Market data on broadcast wiki (updated from known-correct facts)

### APPEND-ONLY fields (never overwritten, only added to)
- Session log references (Baserow IDs)
- Alert fire history (timestamp, trigger, outcome)
- Known corrections log (what was wrong, when fixed, why)

---

## Trigger Stack Self-Improvement (Most Valuable Kingsfield Version)

This is the moat nobody else can build without real sessions.

```
SESSION: Wingman fires alert → Aaron notes correct/incorrect
                                         ↓
TRANSCRIPT: alert event recorded with context + outcome flag
                                         ↓
OUTER LOOP: reads alert events from last N sessions
  - False positive (noise): tighten trigger condition in wiki
  - Miss (should have fired): broaden trigger condition
  - Correct fire: no change (reinforcement, not modification)
                                         ↓
DIFF: targeted patch to trigger conditions section of wiki page
  e.g.:
    BEFORE: "Fire when speaker cites statute incorrectly"
    AFTER:  "Fire when speaker cites statute incorrectly AND
             misquoted text appears in snippet (not paraphrase)
             — do not fire on imprecise but accurate summaries"
                                         ↓
GRADE VERIFIER: validates diff doesn't contradict locked fields
                                         ↓
WIKI UPDATED: next session runs improved trigger stack
```

After 20-30 sessions: trigger stack refined against real courtroom audio.
Compounding advantage — each session makes the next one more accurate.

---

## Implementation Notes

### What you need to add to existing stack:

1. **Diff format** — wiki pages need a structured patch format
   (JSON Patch RFC 6902 or simple field-level JSON diff)
   so outer loop writes diffs, not full page replacements.

2. **Field lock/diffable metadata in legal_wiki_schema.md**
   Every field definition must include: `locked | diffable | append-only`

3. **Feedback capture in session transcript**
   Current transcript format only logs Wingman output.
   Need: `[FEEDBACK] NOISE|MISS|CORRECT — [trigger] — [context]`
   Aaron flags these during or immediately after session.

4. **Outer loop scheduler**
   Prefect job or cron → runs `wiki_refresh_agent.py`
   Acquires exclusive write lock on wiki dir before running.
   Releases lock when done. Inner loop agents get previous
   snapshot during refresh (read-only, never blocked).

5. **Baserow table: wiki_refresh_log**
   | run_id | triggered_by | pages_diffed | fields_changed |
   | diffs_rejected_by_grader | wiki_version_hash | timestamp |

### What does NOT change:
- wingman_live.py — no changes needed to inner loop
- grade_verifier.py — used as-is for diff validation
- session transcript format — just add FEEDBACK lines
- Exclusive write lock rule — one writer, many readers, never concurrent

---

## Lloyd's Key Quote (extract for master ref)

"Since Skills are just files, this means [the outer loop agent] should
make a diff to improve Skill based on user feedback from past runs."

Translation for Kingsfield: since wiki pages are just markdown files,
the refresh agent makes diffs to improve wiki pages based on session
transcript feedback. The intelligence compounds in the files themselves,
not in the model's context window.

---
# Status: PATTERN EXTRACTED — needs legal_wiki_schema.md built first
# Next: define field types for judge profile page, then implement diff format
# Owner: Aaron Ray / Kingsfield Lawfare
# Extracted: June 17 2026
