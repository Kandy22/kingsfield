---
license: cc-by-4.0
language:
- en
tags:
- legal
- appellate-court
- audio-processing
- speech-to-text
- whisper-benchmark
pretty_name: Florida Appellate Court Oral Argument Transcription Dataset
size_categories:
- 1K<n<10K
---

# Florida Appellate Court Oral Argument Transcription Dataset

**Version:** 0.1 (in progress)  
**Target:** 1,440+ cases from Florida appellate courts  
**Pipeline:** [`../judicial-intel/`](../judicial-intel/README.md)

---

## What This Is

Oral argument records from Florida appellate court YouTube archives. Each case produces:

1. Reference audio (`.m4a`) or video (`.mp4`)
2. Timestamped transcript (`.srt` + `.json`)
3. Transcript verification score vs. YouTube auto-captions
4. Behavioral signals manifest (frames, face count, prosody stubs)

This is the **judicial intelligence** dataset — separate from the Showalter citation benchmark.

---

## Technical Pipeline

Implemented in `judicial-intel/pipeline/`:

| Stage | Script | Output |
|---|---|---|
| Index | `index_channel.py` | `data/fl_2dca/index.json` |
| Download | `download.py` | audio + `.vtt` captions |
| Transcribe | `transcribe.py` | `.srt` via faster-whisper or Whisper API |
| Verify | `verify_transcript.py` | caption match score in manifest |
| Signals | `analyze_signals.py` | OpenCV/MediaPipe features |

### Transcription guardrails

- `temperature=0.0` — no semantic smoothing
- SRT output — sub-second timestamps, anti-loop pacing
- ffmpeg 15-minute chunks for API 25MB limit

---

## Priority Channels

1. **FL 2nd DCA** — `@seconddistrictcourtofappea8708` (1,700+ videos)
2. FL Supreme Court YouTube
3. FL 1st, 4th, 5th, 6th DCAs

Config: [`../judicial-intel/florida/config.json`](../judicial-intel/florida/config.json)

---

## Cost Estimates (Whisper API)

| Stack | Rate | ~1,440 cases |
|---|---|---|
| OpenAI Whisper-1 | $0.006/min | ~$302 |
| Groq | ~$0.003/min | ~$151 |
| faster-whisper (local) | compute only | **preferred** |

---

## Dataset Layout (per case)

```
judicial-intel/data/fl_2dca/
  manifest.json
  audio/<video_id>.m4a
  captions/<video_id>.vtt
  transcripts/<video_id>.srt
  transcripts/<video_id>.json
  signals/<video_id>.json
  frames/<video_id>/frame_*.jpg
```

Media excluded from git — store on S3/R2 in production.

---

## Status

**Not yet populated.** Pipeline scaffolded June 2026 after prior sessions cut off before transcript-caption matches completed. Run:

```bash
python3 judicial-intel/pipeline/index_channel.py --channel fl_2dca
```

---

## License

CC BY 4.0