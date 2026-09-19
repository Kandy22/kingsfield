# Judicial Intelligence Pipeline

Court video → transcript → verification → behavioral signals.

This is Kingsfield's edge for **judicial intelligence** and **jury selection**: capture how judges and parties actually behave in oral argument — tone, interruption patterns, facial cues, hesitation — before courts restrict access.

**Store everything now.** Judges will restrict this once they realize it's being indexed.

---

## Architecture

Two tracks. The **captions track** is what produces the scored dataset today;
the **audio track** (Whisper / Gemini diarization / MediaPipe) is the older
path and is not yet run at scale.

```
pipeline/index_channel.py       YouTube channel → data/<ch>/index.json (ids, titles, durations)
        ↓
pipeline/pull_captions.py       auto-captions (.vtt) + slim metadata (.info.json), no media
        ↓                       resumable, 3 yt-dlp workers, ~13 videos/min
pipeline/build_transcripts.py   rolling-caption dedupe → ">>" turn split → role inference
        ↓                       (BENCH / APPELLANT_COUNSEL / APPELLEE_COUNSEL, with role_src)
pipeline/run_oa_panel.py        TypeSafe Jev decision panel per transcript → panel/oa_results.{jsonl,csv}
        ↓                       resumable, 12 threads, ~$0.0004/transcript
pipeline/enrich_flcourts.py     Florida courts opinion-search API (the endpoint Juriscraper wraps):
        ↓                       EVERY decision for the district incl. PCAs → flcourts/decisions.jsonl,
                                joined to videos on case number → dockets/<id>.json; --with-pdf adds
                                panel, author, trial judge, county, counsel from the opinion PDF.
                                Primary ground truth. Unauthenticated; ~2 req/s.
pipeline/enrich_dockets.py      CourtListener lookup (secondary / cross-check; token is 100 req/hour)
                                (all ground truth is joined into oa_results.csv AFTER scoring — never sent to the model)

pipeline/validate_roles.py      scores role inference against hand labels / diarization
```

Audio track (older, pilot only): `download.py` → `transcribe.py` → `verify_transcript.py`
→ `diarize.py` → `analyze_signals.py` → `merge_signals.py`. `diarize.py` output is chunk-local
and not usable as speaker ground truth — see the note in `build_transcripts.py`.

### Quick start (Florida 2nd DCA, captions track)

```bash
cd Verifier/judicial-intel-analytics
python3 pipeline/pull_captions.py   --channel fl_2dca --workers 3
python3 pipeline/build_transcripts.py --channel fl_2dca
export OPENROUTER_API_KEY=...        # or TYPESAFE_API_KEY with --provider typesafe
python3 pipeline/run_oa_panel.py    --channel fl_2dca --limit 10 --dump-raw   # validate first
python3 pipeline/run_oa_panel.py    --channel fl_2dca                          # full corpus
python3 pipeline/enrich_flcourts.py --channel fl_2dca --since 2016              # all decisions + join
python3 pipeline/enrich_flcourts.py --channel fl_2dca --skip-pull --with-pdf    # panels from PDFs
python3 pipeline/run_oa_panel.py    --channel fl_2dca --rebuild-csv            # re-join ground truth + calibration
```

### Panel design rules (run_oa_panel.py)

1. One proposition per question. 2. Never average a score — every level's probability is a
column, plus `__modal` and a `__bimodal` flag (two non-adjacent levels ≥ 0.20).
3. Nothing under test goes in state; disposition, panel, date are joined back after.
4. Python gate (ceremony titles, < 1,500 words) then a model gate (`transcript_sufficient`,
`is_oral_argument`). 5. No counting or dates in questions. 6. State is the labeled transcript
and a one-line note, nothing else.

### Results (2DCA, 2026-09-19, n = 1,098 argued cases with decisions)

- Argued cases affirm 74%; the court as a whole affirms ~86% (≈3,000 PCAs vs ≈500 written
  opinions a year). Oral argument is granted for cases that reverse 2.5× as often.
- `ruling_lean` raw accuracy 64% — below the always-affirm baseline. Its `reverse` calls
  are 48% precise against a 19% base rate (2.5× lift). Confidence is monotonic:
  <0.5 → 53%, 0.5–0.7 → 75%, 0.7–0.9 → 88%, ≥0.9 → 94%. **Abstain below 0.7.**
- `skepticism_gap` (appellant modal − appellee modal, computed in Python) is the strongest
  signal: ≤−2 → 32% affirmed, −1 → 53%, 0 → 71%, +1 → 94%, ≥+2 → 97%. Replicates on 6DCA.
- `bench_posture_toward_trial_court`: critical → 40% reverse/mixed, deferential → 9%.
- The behavioral nouls (issue unraised, jurisdiction, concessions, not-answering) do not
  predict outcome. They are the descriptive layer, not forecasts.
- 13% of appellant scores and 21% of appellee scores are bimodal; never report a mean.

### Corpus facts (2026-09-19)

- 1,440 individual clips + 297 full-day live streams. Live streams are excluded: they
  duplicate the clips and exceed the 32k state budget.
- Titles are case numbers only (`25 1145` → `2D2025-1145`; pre-2023 `2D19 852`). No case
  name, date, or panel in the YouTube metadata — those come from `enrich_dockets.py`.
- Transcript size: median ~7.5k tokens, max ~15k.
- Auto-captions garble the legal vocabulary ("may police court", "on behalf of the appeal");
  role inference is fuzzy on purpose. ~86% BENCH/COUNSEL accuracy on a hand-labeled video.

## Why transcript verification is separate

Citation verification (Showalter benchmark) and **oral-argument transcript verification** are different problems:

| Track | Question | Ground truth |
|---|---|---|
| Citation benchmark | Does this quote appear in this case? | CourtListener opinion text |
| Judicial intel | Did we transcribe what was actually said? | YouTube auto-captions + docket metadata |

The Florida dataset README describes the Whisper stack (`temperature=0`, SRT format, ffmpeg chunking). `verify_transcript.py` scores whether our transcript matches the platform's captions — the first sanity check before emotion analysis.

---

## Signal layer (your ad-tech edge)

`analyze_signals.py` extracts keyframes and writes a signals manifest. Wire in:

- **OpenCV** — face detection, gaze proxy, movement energy
- **MediaPipe** — pose, hand, face mesh
- **DeepFace / emotion models** — affect classification (treat as features, not ground truth)
- **Prosody from audio** — pause length, interruption rate, speaking-time ratio (judge vs counsel)

Output schema: `data/<channel>/signals/<video_id>.json`

---

## Channel priority

See `court_yt_channels.md`. Start with **FL 2nd DCA** (1,700+ videos, auto-captions).

---

## Storage

Media stays out of git (see `verifier/.gitignore`). Production: S3/R2 with manifest JSON in Supabase `sources` table (same provenance pattern as citation benchmark).