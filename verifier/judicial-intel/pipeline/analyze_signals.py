#!/usr/bin/env python3
"""
Extract video frames + behavioral signal stubs for judicial intelligence.

This is where ad-tech-style analysis plugs in:
  - OpenCV face detection
  - MediaPipe pose/face mesh
  - Emotion classifiers (DeepFace, etc.)
  - Speaking-time / interruption metrics from transcript JSON

Outputs signals/<video_id>.json — features only, not legal conclusions.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import entry_paths, load_manifest, save_manifest  # noqa: E402

FRAME_INTERVAL_SEC = 30  # one keyframe every 30s — tune for cost


def extract_frames(video_path: str, out_dir: str, interval: int) -> list:
    import subprocess

    os.makedirs(out_dir, exist_ok=True)
    pattern = os.path.join(out_dir, "frame_%05d.jpg")
    subprocess.run([
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"fps=1/{interval}",
        "-q:v", "2",
        pattern,
    ], check=True, capture_output=True)
    return sorted([
        os.path.join(out_dir, f) for f in os.listdir(out_dir) if f.endswith(".jpg")
    ])


def analyze_frame_opencv(frame_path: str) -> dict:
    """Lightweight stub — wire DeepFace/MediaPipe here."""
    try:
        import cv2  # type: ignore
    except ImportError:
        return {"opencv": "not_installed"}

    img = cv2.imread(frame_path)
    if img is None:
        return {"error": "read_failed"}

    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # Haar cascade — replace with your production detector
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    faces = cv2.CascadeClassifier(cascade_path).detectMultiScale(gray, 1.1, 4)

    return {
        "frame": os.path.basename(frame_path),
        "resolution": [w, h],
        "face_count": len(faces),
        "faces": [{"x": int(x), "y": int(y), "w": int(fw), "h": int(fh)} for x, y, fw, fh in faces],
        # TODO: emotion_scores, gaze_proxy, movement_energy
    }


def speaking_time_from_transcript(transcript_json: str) -> dict:
    if not os.path.exists(transcript_json):
        return {}
    data = json.load(open(transcript_json))
    segments = data.get("segments", [])
    if not segments:
        return {}
    total = sum(max(0, s.get("end", 0) - s.get("start", 0)) for s in segments)
    return {
        "segment_count": len(segments),
        "total_speech_seconds": round(total, 1),
        # TODO: diarization → judge vs counsel speaking ratio
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", required=True)
    ap.add_argument("--video", help="Single video_id")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--frame-interval", type=int, default=FRAME_INTERVAL_SEC)
    ap.add_argument("--skip-frames", action="store_true", help="Transcript-only signals")
    args = ap.parse_args()

    manifest = load_manifest(args.channel)
    entries = list(manifest.get("entries", {}).values())
    if args.video:
        entries = [e for e in entries if e.get("video_id") == args.video]
    else:
        entries = [e for e in entries
                   if (e.get("transcription") or {}).get("status") == "done"
                   and not os.path.exists(entry_paths(args.channel, e["video_id"])["signals"])][: args.limit]

    for entry in entries:
        vid = entry["video_id"]
        paths = entry_paths(args.channel, vid)
        print(f"  {vid}")

        signals = {
            "video_id": vid,
            "title": entry.get("title"),
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "prosody": speaking_time_from_transcript(paths["transcript_json"]),
            "frames": [],
        }

        if not args.skip_frames and os.path.exists(paths["video"]):
            try:
                frames = extract_frames(paths["video"], paths["frames_dir"], args.frame_interval)
                for fp in frames[:20]:  # cap per run — remove in production
                    signals["frames"].append(analyze_frame_opencv(fp))
            except Exception as ex:
                signals["frame_error"] = str(ex)
        elif not os.path.exists(paths["video"]):
            signals["note"] = "no video file — re-run download.py --with-video"

        os.makedirs(os.path.dirname(paths["signals"]), exist_ok=True)
        json.dump(signals, open(paths["signals"], "w"), indent=2)
        manifest["entries"][vid]["signals"] = {
            "status": "done",
            "path": paths["signals"],
            "frame_count": len(signals.get("frames", [])),
        }
        save_manifest(args.channel, manifest)
        print(f"    → {len(signals.get('frames', []))} frames, prosody={bool(signals.get('prosody'))}")

    print("Done.")


if __name__ == "__main__":
    main()