#!/usr/bin/env python3
"""
Facial expression analysis of oral-argument video, on Modal (never on the Mac: the Mac has
~20 GB free and the no-heat rule). Video is fetched inside the Modal container and deleted
after use; only frames/JSON come back.

Docs read 2026-09-30 before writing this:
  EmotiEffLib (ex-HSEmotion) README + emotiefflib/facial_analysis.py + "Predict emotions on
  video" tutorial: EmotiEffLibRecognizer(engine, model_name, device); predict_emotions(list of
  RGB face crops, logits=False) -> (labels, scores); model "enet_b0_8_va_mtl" = 8 emotions
  (Anger, Contempt, Disgust, Fear, Happiness, Neutral, Sadness, Surprise) + valence, arousal
  in the last two columns. Code Apache-2.0; weights trained on AffectNet (research terms).
  Face detection: facenet_pytorch.MTCNN, as in the tutorial.

Video comes from the Mac (YouTube blocks Modal's servers: probe 2 got 'Sign in to confirm
you're not a bot' / 403 on all 3), uploaded to volume kf-oa-video with --mode upload.

Mode probe (this step): can Modal fetch the video at all, what does the 2DCA frame look like,
how many faces and how big. Returns 4 frames per video to data/fl_2dca/face_probe/.
    modal run pipeline/modal_face.py --mode probe --ids data/fl_2dca/face_probe/probe_ids.txt
No YouTube workarounds: if YouTube asks for sign-in or blocks, the probe reports it and stops.
"""
import json
import os
import time

import modal

APP_NAME = "kf-oa-face"
CHANNEL = "fl_2dca"
FMT = "134/bv*[height<=360][ext=mp4]/18"   # 360p; smallest size where faces in a grid stay >= ~40 px

app = modal.App(APP_NAME)
vol = modal.Volume.from_name("kf-oa-video", create_if_missing=True)
image = (
    modal.Image.from_registry("python:3.12-slim-trixie")
    # libgl1/libglib2.0-0: a dependency pulls in full opencv-python, which needs them (probe 1 failed on libGL.so.1)
    .run_commands("apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*")
    .pip_install("torch", "numpy", "opencv-python-headless", "imageio-ffmpeg==0.6.0",
                 "yt-dlp[default]==2026.8.19", "deno==2.9.7", "facenet-pytorch", "emotiefflib")
)


def _fetch(video_id):
    import subprocess
    import shutil
    import imageio_ffmpeg
    out = f"/tmp/{video_id}.mp4"
    deno = shutil.which("deno")
    cmd = ["yt-dlp", "-f", FMT, "--no-playlist", "--no-progress", "--no-part",
           "--ffmpeg-location", imageio_ffmpeg.get_ffmpeg_exe(), "-o", out,
           f"https://www.youtube.com/watch?v={video_id}"]
    if deno:
        cmd[1:1] = ["--js-runtimes", f"deno:{deno}"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out):
        return None, (r.stderr.strip().splitlines() or ["unknown"])[-1][:300]
    return out, None


@app.function(image=image, timeout=1200, cpu=2.0, volumes={"/video": vol})
def probe(video_id: str) -> dict:
    import cv2
    import numpy as np
    from facenet_pytorch import MTCNN
    t0 = time.time()
    on_vol = f"/video/{CHANNEL}/{video_id}.mp4"
    if os.path.exists(on_vol):
        import shutil
        path, err = f"/tmp/{video_id}.mp4", None
        shutil.copy(on_vol, path)
    else:
        path, err = _fetch(video_id)
    if err:
        return {"video_id": video_id, "ok": False, "error": err}
    cap = cv2.VideoCapture(path)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)); fps = cap.get(cv2.CAP_PROP_FPS) or 30
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    det = MTCNN(keep_all=True, post_process=False, min_face_size=20, device="cpu")
    frames, faces = [], []
    for frac in (0.1, 0.3, 0.5, 0.7):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * frac))
        ok, img = cap.read()
        if not ok:
            continue
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        boxes, probs = det.detect(rgb)
        fs = []
        if boxes is not None:
            for b, p in zip(boxes, probs):
                if p is not None and p > 0.9:
                    fs.append({"box": [int(v) for v in b], "w": int(b[2] - b[0]), "p": round(float(p), 3)})
                    cv2.rectangle(img, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), (0, 255, 0), 1)
        faces.append({"t_sec": round(n * frac / fps), "faces": fs})
        frames.append(cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes())
    cap.release()
    size = os.path.getsize(path); os.remove(path)
    # model load check (weights download) so the full run won't fail on it later
    try:
        from emotiefflib.facial_analysis import EmotiEffLibRecognizer
        EmotiEffLibRecognizer(engine="onnx", model_name="enet_b0_8_va_mtl", device="cpu")
        model_ok = True
    except Exception as e:
        model_ok = repr(e)[:300]
    return {"video_id": video_id, "ok": True, "w": w, "h": h, "fps": round(fps, 2), "frames_total": n,
            "mb": round(size / 1e6, 1), "faces": faces, "model_ok": model_ok,
            "sec": round(time.time() - t0, 1), "_jpgs": frames}


@app.local_entrypoint()
def main(mode: str = "probe", ids: str = ""):
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(here, "data", CHANNEL, "face_probe")
    os.makedirs(out, exist_ok=True)
    vids = [l.strip() for l in open(ids) if l.strip() and not l.startswith("#")]
    if mode == "upload":
        vdir = os.path.join(here, "data", CHANNEL, "video")
        have = [v for v in vids if os.path.exists(os.path.join(vdir, f"{v}.mp4"))]
        with vol.batch_upload(force=True) as b:
            for v in have:
                b.put_file(os.path.join(vdir, f"{v}.mp4"), f"/{CHANNEL}/{v}.mp4")
        print(f"uploaded {len(have)} of {len(vids)} videos to volume kf-oa-video")
        return
    if mode != "probe":
        raise SystemExit("only --mode probe exists yet; the full run is written after the probe")
    for r in probe.map(vids, return_exceptions=True):
        if not isinstance(r, dict):
            print("ERROR", repr(r)[:400]); continue
        for k, jpg in enumerate(r.pop("_jpgs", []) or []):
            open(os.path.join(out, f"{r['video_id']}_{k}.jpg"), "wb").write(jpg)
        json.dump(r, open(os.path.join(out, f"{r['video_id']}.probe.json"), "w"), indent=1)
        print(json.dumps({k: v for k, v in r.items() if k != "faces"}))
        for f in r.get("faces", []):
            print(f"   t={f['t_sec']}s  faces={len(f['faces'])}  widths={[x['w'] for x in f['faces']]}")
