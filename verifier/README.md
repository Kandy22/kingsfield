# Kingsfield Verifier

Two datasets. One storage philosophy: **capture primary evidence now, verify deterministically, store with provenance.**

| Track | What it builds | Status |
|---|---|---|
| **[Citation Benchmark](./CITATION_BENCHMARK.md)** | 1,979 Showalter quotes × 3 AI models × CourtListener grounding | AI eval done; grounding 7%; human labels 200 |
| **[Judicial Intelligence](./judicial-intel/README.md)** | FL court video → transcript → caption verify → behavioral signals | Pipeline scaffolded; indexing not yet run |

---

## Citation Benchmark (quick ref)

Canonical file: **`results_full.json`**

```bash
cd verifier
source venv/bin/activate   # or: python3 -m venv venv && pip install -r requirements.txt
cp .env.example .env       # add CL_TOKEN, API keys

# Grounding grinder (resumable)
python3 make_queue.py
# → MCP opinion_view per citation in fetch_queue.json
python3 harvest.py && python3 ground.py

# Human review
open sandbox.html          # load results_full.json
python3 merge_human_labels.py
```

Legacy scripts: [`archive/`](./archive/README.md)

---

## Judicial Intelligence (quick ref)

**Goal:** Find court/judge videos → transcribe → verify transcript → extract emotion/cues (ad-tech algos) for judicial intelligence and jury selection.

**Start:** Florida 2nd DCA (1,700+ YouTube videos)

```bash
# Requires: yt-dlp, ffmpeg on PATH
# Optional: faster-whisper, opencv-python, mediapipe

python3 judicial-intel/pipeline/index_channel.py --channel fl_2dca
python3 judicial-intel/pipeline/download.py \
  --index judicial-intel/data/fl_2dca/index.json --limit 10 --with-video
python3 judicial-intel/pipeline/transcribe.py --channel fl_2dca --limit 10
python3 judicial-intel/pipeline/verify_transcript.py --channel fl_2dca
python3 judicial-intel/pipeline/analyze_signals.py --channel fl_2dca --limit 5
```

Channel list: [`judicial-intel/court_yt_channels.md`](./judicial-intel/court_yt_channels.md)

---

## Why these live together

Both tracks feed Kingsfield's verification layer:

- **Citations** → four-gate pipeline + Skeptic veto (written authority)
- **Oral argument** → transcript integrity + behavioral features (how authority is exercised)

Judges will restrict video access once they realize it's being indexed. **Download and store now.**

---

## Environment

See [`.env.example`](./.env.example) and [`requirements.txt`](./requirements.txt).

**Never commit API keys.** Rotate any keys that were previously hardcoded in archived scripts.