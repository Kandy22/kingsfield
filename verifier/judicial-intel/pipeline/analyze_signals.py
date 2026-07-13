#!/usr/bin/env python3
"""
Extract video frames + behavioral signals for judicial intelligence.

VibeViz blendshape mood scoring (remix_-vibeviz port) via MediaPipe FaceLandmarker.
OpenCV Haar fallback when MediaPipe/model unavailable.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import ROOT, entry_paths, load_manifest, save_manifest  # noqa: E402
from vibeviz_mood import mood_from_blendshapes  # noqa: E402
from analyze_posture import analyze_gaze_note, analyze_posture  # noqa: E402

FRAME_INTERVAL_SEC = 30
FACE_MODEL = os.path.join(ROOT, "models", "face_landmarker.task")
GAZE_MIN_FACE_H = 80

_landmarker = None
_smoothed_state: dict[str, float] | None = None


def _get_landmarker():
    global _landmarker
    if _landmarker is not None:
        return _landmarker
    if not os.path.exists(FACE_MODEL):
        return None
    try:
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision
    except ImportError:
        return None

    opts = vision.FaceLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=FACE_MODEL),
        output_face_blendshapes=True,
        num_faces=2,
    )
    _landmarker = vision.FaceLandmarker.create_from_options(opts)
    return _landmarker


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


def _gaze_from_landmarks(landmarks, face_h_px: float) -> dict | None:
    if face_h_px < GAZE_MIN_FACE_H or not landmarks or len(landmarks) < 474:
        return None
    # Iris centers vs eye corners — normalized offset proxy
    try:
        l_iris = landmarks[468]
        r_iris = landmarks[473]
        l_outer = landmarks[33]
        r_outer = landmarks[263]
        l_inner = landmarks[133]
        r_inner = landmarks[362]
        lw = abs(l_inner.x - l_outer.x) or 1e-6
        rw = abs(r_inner.x - r_outer.x) or 1e-6
        dx = ((l_iris.x - l_outer.x) / lw + (r_iris.x - r_outer.x) / rw) / 2 - 0.5
        dy = ((l_iris.y - l_outer.y) / lw + (r_iris.y - r_outer.y) / rw) / 2 - 0.5
        return {"dx": round(dx, 3), "dy": round(dy, 3)}
    except (IndexError, AttributeError):
        return None


def _enrich_wide_shot(out: dict, frame_path: str, face_h: int = 0) -> dict:
    """Wide-shot path: posture + qualitative gaze when tight metrics unavailable."""
    tight = face_h >= GAZE_MIN_FACE_H and out.get("gaze") is not None
    if tight:
        return out
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        try:
            out["gaze_note"] = analyze_gaze_note(frame_path)
        except Exception as ex:
            out["gaze_note_error"] = str(ex)
        try:
            out["posture"] = analyze_posture(frame_path)
        except Exception as ex:
            out["posture_error"] = str(ex)
    out["shot_class"] = "tight" if tight else "wide"
    return out


def analyze_frame_vibeviz(frame_path: str, frame_index: int, interval: int) -> dict:
    global _smoothed_state
    landmarker = _get_landmarker()
    out: dict = {
        "frame": os.path.basename(frame_path),
        "t": frame_index * interval,
        "engine": "opencv_haar",
    }

    if landmarker is not None:
        try:
            import mediapipe as mp
            from mediapipe.tasks.python import vision

            img = mp.Image.create_from_file(frame_path)
            result = landmarker.detect(img)
            if result.face_blendshapes:
                out["engine"] = "mediapipe_vibeviz"
                out["face_count"] = len(result.face_blendshapes)
                faces = []
                for i, bs_list in enumerate(result.face_blendshapes):
                    blend = {c.category_name: round(c.score, 4) for c in bs_list}
                    _smoothed_state, mood, dom, _ = mood_from_blendshapes(
                        blend, smoothed=_smoothed_state
                    )
                    face_h = 0
                    gaze = None
                    if result.face_landmarks and i < len(result.face_landmarks):
                        lm = result.face_landmarks[i]
                        ys = [p.y for p in lm]
                        xs = [p.x for p in lm]
                        face_h = int((max(ys) - min(ys)) * img.height)
                        gaze = _gaze_from_landmarks(lm, face_h)
                    faces.append({
                        "blendshapes": blend,
                        "mood_score_visual": round(mood, 3),
                        "dominant_emotion": dom,
                        "face_height_px": face_h,
                        "gaze": gaze,
                    })
                out["faces"] = faces
                if faces:
                    out["mood_score_visual"] = faces[0]["mood_score_visual"]
                    out["dominant_emotion"] = faces[0]["dominant_emotion"]
                    out["gaze"] = faces[0]["gaze"]
                    return _enrich_wide_shot(out, frame_path, faces[0].get("face_height_px", 0))
                return _enrich_wide_shot(out, frame_path, 0)
        except Exception as ex:
            out["mediapipe_error"] = str(ex)

    merged = {**out, **analyze_frame_opencv(frame_path)}
    max_h = 0
    for f in merged.get("faces") or []:
        if isinstance(f, dict) and "h" in f:
            max_h = max(max_h, int(f["h"]))
    return _enrich_wide_shot(merged, frame_path, max_h)


def analyze_frame_opencv(frame_path: str) -> dict:
    try:
        import cv2  # type: ignore
    except ImportError:
        return {"opencv": "not_installed"}

    img = cv2.imread(frame_path)
    if img is None:
        return {"error": "read_failed"}

    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    faces = cv2.CascadeClassifier(cascade_path).detectMultiScale(gray, 1.1, 4)

    return {
        "frame": os.path.basename(frame_path),
        "resolution": [w, h],
        "face_count": len(faces),
        "faces": [{"x": int(x), "y": int(y), "w": int(fw), "h": int(fh)} for x, y, fw, fh in faces],
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
            "frame_interval_sec": args.frame_interval,
            "prosody": speaking_time_from_transcript(paths["transcript_json"]),
            "frames": [],
        }

        if not args.skip_frames and os.path.exists(paths["video"]):
            try:
                frames = extract_frames(paths["video"], paths["frames_dir"], args.frame_interval)
                for i, fp in enumerate(frames[:50]):
                    signals["frames"].append(analyze_frame_vibeviz(fp, i, args.frame_interval))
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
            "engine": (signals["frames"][0].get("engine") if signals.get("frames") else None),
        }
        save_manifest(args.channel, manifest)
        print(f"    → {len(signals.get('frames', []))} frames, prosody={bool(signals.get('prosody'))}")

    print("Done.")


if __name__ == "__main__":
    main()