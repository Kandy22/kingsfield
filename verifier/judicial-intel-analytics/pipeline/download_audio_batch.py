#!/usr/bin/env python3
"""
Download audio-only for a list of videos, one at a time, low bitrate (Mac-friendly).

    python3 pipeline/download_audio_batch.py --ids data/fl_2dca/diarization/batch2_ids.txt

Format: YouTube itag 139 (m4a, ~48 kbps). Speaker separation resamples to 16 kHz mono,
so higher bitrates add size, not accuracy. Falls back to the smallest m4a audio stream.
One download at a time, pause between files and a longer pause every 25 (heat rule).
YouTube now requires a JavaScript challenge solver (yt-dlp wiki "EJS"): yt-dlp[default]
brings yt-dlp-ejs, and Deno (PyPI "deno") is the default runtime. Without them every video
reports "This video is not available". The run stops after 5 straight failures.
Resumable: files already on disk are skipped. Failures go to diarization/_download_failed.txt.
"""
import argparse
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FMT = "139/worstaudio[ext=m4a]/bestaudio[ext=m4a]/bestaudio/worst/best"  # last resort: smallest stream with audio (decoded by ffmpeg on Modal)


def ytdlp_cmd():
    here = os.path.join(ROOT, ".venv-modal", "bin", "python")
    if os.path.exists(here):
        r = subprocess.run([here, "-c", "import yt_dlp"], capture_output=True)
        if r.returncode == 0:
            return [here, "-m", "yt_dlp"]
    if shutil.which("yt-dlp"):
        return ["yt-dlp"]
    sys.exit("yt-dlp not found")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="fl_2dca")
    ap.add_argument("--ids", required=True)
    ap.add_argument("--pause", type=float, default=1.0)
    ap.add_argument("--batch", type=int, default=25)
    ap.add_argument("--cooldown", type=float, default=15.0)
    a = ap.parse_args()
    audio = os.path.join(ROOT, "data", a.channel, "audio")
    os.makedirs(audio, exist_ok=True)
    failed_log = os.path.join(ROOT, "data", a.channel, "diarization", "_download_failed.txt")
    vids = [l.strip() for l in open(a.ids) if l.strip() and not l.startswith("#")]
    todo = [v for v in vids if not os.path.exists(os.path.join(audio, f"{v}.m4a"))]
    y = ytdlp_cmd()
    env = dict(os.environ)
    venv_bin = os.path.join(ROOT, ".venv-modal", "bin")
    env["PATH"] = venv_bin + os.pathsep + env.get("PATH", "")
    deno = shutil.which("deno", path=env["PATH"])
    if deno:
        y = y + ["--js-runtimes", f"deno:{deno}"]
    else:
        print("WARNING: no Deno found; YouTube downloads will likely fail")
    print(f"{len(vids)} listed, {len(vids) - len(todo)} already on disk, {len(todo)} to download  ({' '.join(y[-2:])})")
    ok = bad = streak = 0
    total_bytes = 0
    for n, v in enumerate(todo, 1):
        out = os.path.join(audio, f"{v}.m4a")  # fixed name; ffmpeg on Modal reads by content, not extension
        r = subprocess.run(y + ["-f", FMT, "--no-playlist", "--no-progress", "--no-part",
                                "-o", out, f"https://www.youtube.com/watch?v={v}"],
                           capture_output=True, text=True, env=env)
        path = os.path.join(audio, f"{v}.m4a")
        if r.returncode == 0 and os.path.exists(path):
            ok += 1
            sz = os.path.getsize(path); total_bytes += sz
            print(f"  [{n}/{len(todo)}] {v}  {sz/1e6:.1f} MB", flush=True)
        else:
            bad += 1
            err = (r.stderr.strip().splitlines() or ["unknown error"])[-1][:200]
            print(f"  [{n}/{len(todo)}] {v}  FAILED: {err}", flush=True)
            with open(failed_log, "a") as f:
                f.write(f"{v}\t{err}\n")
            streak += 1
            if streak >= 5 and ok == 0:
                print("STOPPED: 5 failures in a row before any success. Setup problem, not missing videos.")
                break
        if r.returncode == 0 and os.path.exists(path):
            streak = 0
        if n % a.batch == 0 and n < len(todo):
            print(f"  -- {n} done, cooling down {int(a.cooldown)} s --")
            time.sleep(a.cooldown)
        else:
            time.sleep(a.pause)
    print(f"done: {ok} downloaded ({total_bytes/1e9:.2f} GB), {bad} failed")


if __name__ == "__main__":
    main()
