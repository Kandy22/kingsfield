# Judicial Intelligence Pipeline

Court video → transcript → verification → behavioral signals.

This is Kingsfield's edge for **judicial intelligence** and **jury selection**: capture how judges and parties actually behave in oral argument — tone, interruption patterns, facial cues, hesitation — before courts restrict access.

**Store everything now.** Judges will restrict this once they realize it's being indexed.

---

## Architecture (four decoupled stages)

```
index_channel.py     YouTube/archive metadata → channel_index.json
       ↓
download.py          video/audio + YouTube auto-captions (verification baseline)
       ↓
transcribe.py        faster-whisper (local) or Whisper API → .srt + .json
       ↓
verify_transcript.py Compare our transcript vs YT captions + docket keywords
       ↓
analyze_signals.py   OpenCV frame extraction + emotion/attention signals (ad-tech algos)
```

Each stage is **resumable** and writes a manifest. A session cutoff only loses the current item, not the pipeline.

---

## Quick start (Florida 2nd DCA)

```bash
cd verifier
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# Optional: pip install faster-whisper opencv-python mediapipe numpy

# 1. Index channel (metadata only — fast, no downloads)
python3 judicial-intel/pipeline/index_channel.py \
  --config judicial-intel/florida/config.json \
  --channel fl_2dca

# 2. Download audio + auto-captions for first batch
python3 judicial-intel/pipeline/download.py \
  --index judicial-intel/data/fl_2dca/index.json \
  --limit 10

# 3. Transcribe (local faster-whisper preferred)
python3 judicial-intel/pipeline/transcribe.py \
  --manifest judicial-intel/data/fl_2dca/manifest.json \
  --limit 10

# 4. Verify transcript against YouTube captions
python3 judicial-intel/pipeline/verify_transcript.py \
  --manifest judicial-intel/data/fl_2dca/manifest.json

# 5. Extract frames + behavioral signals (stub — wire your algos)
python3 judicial-intel/pipeline/analyze_signals.py \
  --manifest judicial-intel/data/fl_2dca/manifest.json \
  --limit 5
```

---

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

Output schema: `judicial-intel/data/<channel>/signals/<video_id>.json`

---

## Channel priority

See `court_yt_channels.md`. Start with **FL 2nd DCA** (1,700+ videos, auto-captions).

---

## Storage

Media stays out of git (see `verifier/.gitignore`). Production: S3/R2 with manifest JSON in Supabase `sources` table (same provenance pattern as citation benchmark).