# neuro-stack — pulled 2026-07-09

Open, runnable brain/neural-interface repos + where the data and papers already live.
All non-commercial (CC-BY-NC) — fine for research, the art piece, demos; NOT for resale
except THINGSplus license-free images.

## What's here (cloned, code only — .git stripped)

| Folder | What it does | Install / run |
|---|---|---|
| `emg2qwerty/` | Wrist sEMG typing dataset + baselines (108 users, 346h). Your real, non-invasive neural-INPUT demo. | `cd emg2qwerty && pip install -e .` — data downloads separately from S3 (see repo README) |
| `THINGSvision/` | Extracts DNN activations to align with brain data (the DINOv2 side of image-decoding). | `pip install thingsvision` — has a browser Colab too |
| `THINGS-data/` | Loader code for the THINGS fMRI/MEG recordings. | `pip install -e .`; data at osf.io/jum2f |
| `eeg_encoding/` | THINGS-EEG2 pipeline (cleanest EEG set to start). | see repo README; data on OSF |

## Already in your Drive (don't re-download)

- **TRIBE v2 code+demo** → `Legal AI 2026/data-sources/Meta/tribev2-main.zip` (+ weights: HF `facebook/tribev2`)
- **THINGS image "cards"** → `Legal AI 2026/Meta Misc/things-initiative.org/THINGS/`
- **THINGS-data paper (eLife 82580)** → `Legal AI 2026/Meta Misc/elife-82580-v4.pdf` (+ figures)
- **Meta dev-blog scrape** → `Legal AI 2026/Meta Misc/extract-data-2026-07-09.json`

## Papers to grab (arXiv IDs)

- Meta MEG image-decoding: 2310.19812
- TRIBE v2: 2605.04326
- emg2qwerty: 2410.20081
- THINGS-data: eLife 10.7554/eLife.82580 (already have PDF)

## Waitlisted — can't pull, need the key

Muse Spark / Meta Model API, Muse Image, Muse Video. Closed hosted API (dev.meta.com),
US-only public preview, $20 free credits, $1.25/M in · $4.25/M out. Not on GitHub.

## Big data NOT pulled (pick which, they're tens of GB)

- emg2qwerty full set (S3), THINGS-MEG / THINGS-EEG2 recordings (OSF). Code is ready; say which to fetch.
