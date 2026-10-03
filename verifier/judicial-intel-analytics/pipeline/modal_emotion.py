#!/usr/bin/env python3
"""
Vocal emotion per speaker turn, on a Modal L4 GPU (never on the Mac).

Model: audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim — arousal, dominance, valence,
each roughly 0..1. License CC-BY-NC-SA-4.0, "research purpose only" per the model card;
a product needs audEERING's commercial model or a differently licensed one.
Docs read 2026-09-30 before writing this: the model card README (usage code: custom
RegressionHead + EmotionModel over Wav2Vec2Model, Wav2Vec2Processor normalization, mean
pooling over all frames, 16 kHz mono input) and config.json (id2label 0=arousal,
1=dominance, 2=valence).

Because the model mean-pools every frame, turns are scored one window at a time (no padding).
Turns shorter than 1 s are skipped; longer turns are cut into windows of at most 10 s and
the window scores are averaged, weighted by window length.
Also per turn: loudness (RMS dBFS) and pitch (librosa.yin median / IQR over the louder frames).

    modal run pipeline/modal_emotion.py --ids data/fl_2dca/diarization/emotion_ids.txt

Input : data/fl_2dca/transcripts_diar/<id>.turns.json (turn start/end), audio already on the
        Modal volume kf-oa-audio (uploaded by the diarization runs)
Output: data/fl_2dca/emotion/<id>.json  {video_id, model, turns:[{i, a, d, v, sec, rms_db, f0_med, f0_iqr}], gpu_sec}
"""
import json
import os
import time

import modal

APP_NAME = "kf-oa-emotion"
VOL_NAME = "kf-oa-audio"
CHANNEL = "fl_2dca"
MODEL_ID = "audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim"
MIN_SEC, WIN_SEC = 1.0, 10.0

app = modal.App(APP_NAME)
vol = modal.Volume.from_name(VOL_NAME)

# Same base as modal_diarize.py (Debian 13 registry image, gcc for Triton, ffmpeg from the wheel).
image = (
    modal.Image.from_registry("python:3.12-slim-trixie")
    .run_commands("apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev && rm -rf /var/lib/apt/lists/*")
    .pip_install("torch", "numpy", "librosa", "imageio-ffmpeg==0.6.0", "soundfile==0.14.0", "transformers")
)

_M = None


def _load():
    global _M
    if _M is None:
        import torch
        import torch.nn as nn
        from transformers import Wav2Vec2Processor
        from transformers.models.wav2vec2.modeling_wav2vec2 import Wav2Vec2Model, Wav2Vec2PreTrainedModel

        class RegressionHead(nn.Module):          # verbatim structure from the model card
            def __init__(self, config):
                super().__init__()
                self.dense = nn.Linear(config.hidden_size, config.hidden_size)
                self.dropout = nn.Dropout(config.final_dropout)
                self.out_proj = nn.Linear(config.hidden_size, config.num_labels)

            def forward(self, x):
                x = self.dropout(x)
                x = torch.tanh(self.dense(x))
                x = self.dropout(x)
                return self.out_proj(x)

        class EmotionModel(Wav2Vec2PreTrainedModel):
            def __init__(self, config):
                super().__init__(config)
                self.config = config
                self.wav2vec2 = Wav2Vec2Model(config)
                self.classifier = RegressionHead(config)
                self.post_init()

            def forward(self, input_values):
                h = self.wav2vec2(input_values)[0]
                h = torch.mean(h, dim=1)
                return h, self.classifier(h)

        proc = Wav2Vec2Processor.from_pretrained(MODEL_ID)
        model = EmotionModel.from_pretrained(MODEL_ID).to("cuda").eval()
        _M = (proc, model)
    return _M


@app.function(image=image, gpu="L4", volumes={"/audio": vol}, timeout=3600, max_containers=4)
def score(video_id: str, turns: list) -> dict:
    import subprocess
    import numpy as np
    import soundfile
    import torch
    import imageio_ffmpeg
    import librosa
    src = f"/audio/{CHANNEL}/{video_id}.m4a"
    if not os.path.exists(src):
        return {"video_id": video_id, "error": f"missing {src}"}
    wav = f"/tmp/{video_id}.wav"
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-loglevel", "error", "-y", "-i", src,
                    "-ac", "1", "-ar", "16000", wav], check=True)
    audio, sr = soundfile.read(wav, dtype="float32")
    os.remove(wav)
    proc, model = _load()
    t0 = time.time()
    out = []
    for i, st, en in turns:
        sec = en - st
        if sec < MIN_SEC:
            continue
        seg = audio[int(st * sr):int(en * sr)]
        if len(seg) < MIN_SEC * sr:
            continue
        n = max(1, int(np.ceil(len(seg) / (WIN_SEC * sr))))
        wins = [w for w in np.array_split(seg, n) if len(w) >= 0.5 * sr]
        adv, wts = [], []
        for w in wins:
            x = proc(w, sampling_rate=sr)["input_values"][0].reshape(1, -1)
            with torch.no_grad():
                y = model(torch.from_numpy(x).to("cuda"))[1][0].cpu().numpy()
            adv.append(y); wts.append(len(w))
        a, d, v = (np.average(np.array(adv), axis=0, weights=wts)).tolist()
        rms = librosa.feature.rms(y=seg, frame_length=1024, hop_length=320)[0]
        f0 = librosa.yin(seg, fmin=65, fmax=400, sr=sr, frame_length=1024, hop_length=320)
        k = min(len(rms), len(f0))
        loud = rms[:k] >= np.median(rms[:k])
        f = f0[:k][loud]
        out.append({"i": i, "a": round(a, 4), "d": round(d, 4), "v": round(v, 4), "sec": round(sec, 2),
                    "rms_db": round(float(20 * np.log10(np.sqrt(np.mean(seg ** 2)) + 1e-9)), 2),
                    "f0_med": round(float(np.median(f)), 1) if len(f) else None,
                    "f0_iqr": round(float(np.percentile(f, 75) - np.percentile(f, 25)), 1) if len(f) else None})
    return {"video_id": video_id, "model": MODEL_ID, "min_sec": MIN_SEC, "win_sec": WIN_SEC,
            "turns": out, "gpu_sec": round(time.time() - t0, 1)}


@app.local_entrypoint()
def main(ids: str = "", force: bool = False):
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data = os.path.join(here, "data", CHANNEL)
    out_dir = os.path.join(data, "emotion")
    os.makedirs(out_dir, exist_ok=True)
    vids = [l.strip() for l in open(ids) if l.strip() and not l.startswith("#")]
    jobs = []
    for v in vids:
        if not force and os.path.exists(os.path.join(out_dir, f"{v}.json")):
            continue
        doc = json.load(open(os.path.join(data, "transcripts_diar", f"{v}.turns.json")))
        jobs.append((v, [(t["i"], float(t["start"]), float(t["end"])) for t in doc["turns"]]))
    print(f"emotion: {len(jobs)} to run ({len(vids) - len(jobs)} already done)")
    t0, n, gpu = time.time(), 0, 0.0
    if jobs:   # canary: one video first so a setup error fails once
        try:
            first = score.remote(*jobs[0])
        except Exception as e:
            print("STOPPED on first video:", repr(e)[:800]); return
        if "error" in first:
            print("STOPPED on first video:", first["error"]); return
        json.dump(first, open(os.path.join(out_dir, f"{first['video_id']}.json"), "w"))
        n += 1; gpu += first["gpu_sec"]
        t = first["turns"]
        print(f"  {first['video_id']}  {len(t)} turns scored  gpu {first['gpu_sec']}s  e.g. {t[:2]}")
        jobs = jobs[1:]
    for r in score.starmap(jobs, return_exceptions=True):
        if not isinstance(r, dict):
            print("ERROR", repr(r)[:300]); continue
        if "error" in r:
            print("ERROR", r["video_id"], r["error"]); continue
        json.dump(r, open(os.path.join(out_dir, f"{r['video_id']}.json"), "w"))
        n += 1; gpu += r["gpu_sec"]
        if n % 20 == 0:
            print(f"  {n} videos done, {gpu:.0f}s model time", flush=True)
    print(f"done: {n} videos in {int(time.time()-t0)}s wall, {gpu:.1f}s model time")
