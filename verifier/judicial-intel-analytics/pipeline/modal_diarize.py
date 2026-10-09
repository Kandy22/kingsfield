#!/usr/bin/env python3
"""
Speaker diarization of oral-argument audio with NVIDIA Nemotron 3 Diarization on Modal.

Runs on a Modal L4 GPU (never on the Mac). The Mac only uploads audio and receives JSON.

Docs read 2026-09-24 before writing this:
  Modal   : docs/guide (install/auth), guide/images, guide/gpu, guide/volumes, guide/scale, guide/timeouts
  Nemotron: huggingface.co/nvidia/Nemotron-3-Diarization model card (Transformers usage) and
            transformers main docs model_doc/nemotron3_diarization (extract_speaker_dict -> Start/End/Speaker)

Modes (run from the judicial-intel-analytics folder, via RUN_diarize_pilot.command):
  modal run pipeline/modal_diarize.py --mode upload  --ids data/fl_2dca/diarization/pilot_ids.txt
  modal run pipeline/modal_diarize.py --mode run     --ids data/fl_2dca/diarization/pilot_ids.txt
  modal run pipeline/modal_diarize.py --mode ytprobe --ids data/fl_2dca/diarization/ytprobe_ids.txt

Output: data/fl_2dca/diarization/<video_id>.json
        {video_id, model, config, duration_sec, n_speakers, segments:[[start, end, "speaker_k"], ...], gpu_sec}
"""
import json
import os
import time

import modal

APP_NAME = "kf-oa-diarize"
VOL_NAME = "kf-oa-audio"
CHANNEL = "fl_2dca"
MODEL_ID = "nvidia/Nemotron-3-Diarization"
OFFLINE_CFG = {"backend": "transformers", "mode": "offline (model default chunk 340 + right context 40 frames)"}

app = modal.App(APP_NAME)
vol = modal.Volume.from_name(VOL_NAME, create_if_missing=True)

# Base = Docker's official python:3.12-slim-trixie (Debian 13), not modal.Image.debian_slim.
# This workspace's debian_slim is Debian 11, whose packages are gone from deb.debian.org
# (every build 404'd). No apt is used at all: static ffmpeg comes from the imageio-ffmpeg
# wheel and the soundfile wheel bundles libsndfile. Modal docs: a registry image needs
# python + pip on PATH and linux/amd64, which this official image has.
BASE = "python:3.12-slim-trixie"
# Model loads through Hugging Face Transformers, not NeMo: the released nemo-toolkit 3.0.0
# rejects this checkpoint (self_attention_model='rope' unsupported). The model card's
# Transformers path needs Transformers from source; the main-branch zip avoids needing git.
gpu_image = (
    modal.Image.from_registry(BASE)
    # torch compiles GPU kernels at run time with Triton, which needs a C compiler. The base is
    # Debian 13 (current), so apt works here, unlike the old Debian 11 base.
    .run_commands("apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev && rm -rf /var/lib/apt/lists/*")
    # librosa: the model's feature extractor (NemotronAsrStreamingFeatureExtractor) requires it.
    .pip_install("torch", "numpy", "librosa", "imageio-ffmpeg==0.6.0", "soundfile==0.14.0")
    .pip_install("transformers @ https://github.com/huggingface/transformers/archive/refs/heads/main.zip")
)
probe_image = (
    modal.Image.from_registry(BASE)
    .pip_install("imageio-ffmpeg==0.6.0", "yt-dlp==2026.8.19")
)

_MODEL = None


def _load():
    """Model card, Transformers offline example. Offline mode chunks internally
    (340 + 40 encoder frames), so a 40-minute argument is fine."""
    global _MODEL
    if _MODEL is None:
        import torch
        from transformers import AutoModelForAudioFrameClassification, AutoProcessor
        proc = AutoProcessor.from_pretrained(MODEL_ID)
        model = AutoModelForAudioFrameClassification.from_pretrained(MODEL_ID).to("cuda")
        model.eval()
        _MODEL = (proc, model)
    return _MODEL


@app.function(image=gpu_image, gpu="L4", volumes={"/audio": vol}, timeout=1800, max_containers=4)
def diarize(video_id: str) -> dict:
    import subprocess
    src = f"/audio/{CHANNEL}/{video_id}.m4a"
    if not os.path.exists(src):
        return {"video_id": video_id, "error": f"missing {src}"}
    wav = f"/tmp/{video_id}.wav"
    import imageio_ffmpeg
    import soundfile
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-loglevel", "error", "-y", "-i", src,
                    "-ac", "1", "-ar", "16000", wav], check=True)
    dur = float(soundfile.info(wav).duration)
    import torch
    proc, model = _load()
    audio, sr = soundfile.read(wav, dtype="float32")
    t0 = time.time()
    inputs = proc(audio, sampling_rate=sr).to(model.device, dtype=model.dtype)
    with torch.inference_mode():
        logits = model(**inputs).logits
    raw = proc.extract_speaker_dict(logits, inputs.attention_mask)[0]
    gpu_sec = round(time.time() - t0, 2)
    segs = sorted(([round(float(x["Start"]), 3), round(float(x["End"]), 3), f"speaker_{int(x['Speaker'])}"]
                   for x in raw), key=lambda x: (x[0], x[1]))
    os.remove(wav)
    return {"video_id": video_id, "model": MODEL_ID, "config": OFFLINE_CFG, "duration_sec": round(dur, 2),
            "n_speakers": len({s[2] for s in segs}), "segments": segs, "gpu_sec": gpu_sec}


@app.function(image=probe_image, timeout=600)
def ytprobe(video_id: str) -> dict:
    """Can a Modal container download audio from YouTube? Metadata + 60 s of audio only."""
    import subprocess
    url = f"https://www.youtube.com/watch?v={video_id}"
    t0 = time.time()
    import imageio_ffmpeg
    r = subprocess.run(["yt-dlp", "-f", "bestaudio", "--download-sections", "*0-60",
                        "--ffmpeg-location", imageio_ffmpeg.get_ffmpeg_exe(),
                        "-o", f"/tmp/{video_id}.%(ext)s", "--no-progress", url],
                       capture_output=True, text=True)
    ok = r.returncode == 0
    return {"video_id": video_id, "ok": ok, "sec": round(time.time() - t0, 1),
            "stderr_tail": r.stderr.strip().splitlines()[-3:] if not ok else []}


def _ids(path):
    return [l.strip() for l in open(path) if l.strip() and not l.startswith("#")]


@app.local_entrypoint()
def main(mode: str = "run", ids: str = "", force: bool = False):
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data = os.path.join(here, "data", CHANNEL)
    out_dir = os.path.join(data, "diarization")
    os.makedirs(out_dir, exist_ok=True)
    vids = _ids(ids)

    if mode == "upload":
        log = os.path.join(out_dir, "uploaded.txt")     # local record; avoids re-uploading
        have = set(_ids(log)) if os.path.exists(log) else set()
        todo = [v for v in vids if v not in have and os.path.exists(os.path.join(data, "audio", f"{v}.m4a"))]
        missing = [v for v in vids if not os.path.exists(os.path.join(data, "audio", f"{v}.m4a"))]
        print(f"upload: {len(todo)} new, {len(have)} already on volume, {len(missing)} not on disk")
        with vol.batch_upload() as batch:
            for v in todo:
                batch.put_file(os.path.join(data, "audio", f"{v}.m4a"), f"/{CHANNEL}/{v}.m4a")
        with open(log, "a") as f:
            f.writelines(v + "\n" for v in todo)
        print("upload done")
        return

    if mode == "ytprobe":
        for r in ytprobe.map(vids, return_exceptions=True):
            print(json.dumps(r if isinstance(r, dict) else {"error": repr(r)}))
        return

    log = os.path.join(out_dir, "uploaded.txt")
    on_vol = set(_ids(log)) if os.path.exists(log) else set()
    skipped = [v for v in vids if v not in on_vol]
    if skipped:
        print(f"skipping {len(skipped)} ids with no uploaded audio (download failed or not uploaded)")
    todo = [v for v in vids if v in on_vol and (force or not os.path.exists(os.path.join(out_dir, f"{v}.json")))]
    print(f"diarize: {len(todo)} to run ({len(vids) - len(todo)} already done)")
    t0, n, gpu = time.time(), 0, 0.0
    # Canary: run one video first so a setup error fails once, not 35 times.
    if todo:
        try:
            first = diarize.remote(todo[0])
        except Exception as e:
            print("STOPPED on first video:", repr(e)[:600]); return
        if "error" in first:
            print("STOPPED on first video:", first["error"]); return
        json.dump(first, open(os.path.join(out_dir, f"{first['video_id']}.json"), "w"))
        n += 1; gpu += first["gpu_sec"]
        print(f"  {first['video_id']}  {first['duration_sec']/60:.1f} min  {first['n_speakers']} speakers  {len(first['segments'])} segments  gpu {first['gpu_sec']}s")
        todo = todo[1:]
    for r in diarize.map(todo, return_exceptions=True):
        if not isinstance(r, dict):
            print("ERROR", repr(r)[:300]); continue
        if "error" in r:
            print("ERROR", r["video_id"], r["error"]); continue
        json.dump(r, open(os.path.join(out_dir, f"{r['video_id']}.json"), "w"))
        n += 1; gpu += r["gpu_sec"]
        print(f"  {r['video_id']}  {r['duration_sec']/60:.1f} min  {r['n_speakers']} speakers  {len(r['segments'])} segments  gpu {r['gpu_sec']}s")
    print(f"done: {n}/{len(todo)} in {int(time.time()-t0)}s wall, {gpu:.1f}s model time")

