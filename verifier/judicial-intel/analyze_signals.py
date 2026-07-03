"""
analyze_signals.py
Kingsfield — Judicial Intelligence Pipeline, Stage 5
OpenCV frame extraction + behavioral signals (ad-tech algos).

This is the layer nobody has. Public record video + facial analysis +
transcript timing + final opinion = unprecedented judicial behavior dataset.

Usage:
  python3 judicial-intel/pipeline/analyze_signals.py \
    --manifest judicial-intel/data/fl_2dca/manifest.json \
    --limit 5

Requires (install separately, heavier deps):
  pip install opencv-python mediapipe numpy

Optional (emotion classification — treat as features, not ground truth):
  pip install deepface tf-keras

Output: data/<channel>/signals/<video_id>.json
Schema:
  {
    "video_id": ...,
    "frames_extracted": N,
    "faces_detected": N,
    "prosody": { pause_rate, interruption_count, speaking_time_ratio },
    "face_tracks": [ { frame, timestamp, bbox, emotion_scores } ],
    "segment_signals": [ { start, end, text, energy, face_count } ]
  }
"""

from __future__ import annotations
import argparse, json, logging, sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s")
log = logging.getLogger("analyze_signals")

SAMPLE_FPS  = 1      # extract 1 frame per second — sufficient for behavioral signal
FACE_SCALE  = 1.1
FACE_NEIGHBORS = 5


def check_deps() -> dict:
    deps = {}
    try:
        import cv2
        deps["cv2"] = cv2.__version__
    except ImportError:
        deps["cv2"] = None
    try:
        import mediapipe
        deps["mediapipe"] = mediapipe.__version__
    except ImportError:
        deps["mediapipe"] = None
    try:
        import numpy
        deps["numpy"] = numpy.__version__
    except ImportError:
        deps["numpy"] = None
    try:
        from deepface import DeepFace
        deps["deepface"] = True
    except ImportError:
        deps["deepface"] = None
    return deps


def extract_frames(video_path: Path, sample_fps: int = SAMPLE_FPS) -> list[dict]:
    """Extract keyframes at sample_fps. Returns list of {frame_idx, timestamp, frame_array}."""
    try:
        import cv2
    except ImportError:
        log.error("opencv-python not installed. Run: pip install opencv-python")
        return []

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        log.error("Could not open video: %s", video_path)
        return []

    native_fps = cap.get(cv2.CAP_PROP_FPS) or 30
    interval   = max(1, int(native_fps / sample_fps))
    frames     = []
    frame_idx  = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % interval == 0:
            timestamp = frame_idx / native_fps
            frames.append({
                "frame_idx": frame_idx,
                "timestamp": round(timestamp, 2),
                "frame":     frame,
            })
        frame_idx += 1

    cap.release()
    log.info("  %d frames extracted from %d total (%.1f fps source)",
             len(frames), frame_idx, native_fps)
    return frames


def detect_faces_cv2(frame) -> list[dict]:
    """Basic OpenCV Haar cascade face detection."""
    import cv2
    import numpy as np

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    faces = cascade.detectMultiScale(
        gray, scaleFactor=FACE_SCALE, minNeighbors=FACE_NEIGHBORS,
        minSize=(30, 30)
    )
    if len(faces) == 0:
        return []
    return [
        {"x": int(x), "y": int(y), "w": int(w), "h": int(h)}
        for (x, y, w, h) in faces
    ]


def analyze_emotion(frame, bbox: dict) -> dict | None:
    """DeepFace emotion analysis on a face crop. Optional."""
    try:
        from deepface import DeepFace
        import numpy as np
        x, y, w, h = bbox["x"], bbox["y"], bbox["w"], bbox["h"]
        face_crop = frame[y:y+h, x:x+w]
        result = DeepFace.analyze(
            face_crop, actions=["emotion"], enforce_detection=False, silent=True
        )
        if result:
            return result[0].get("emotion")
    except Exception:
        pass
    return None


def prosody_from_transcript(transcript_path: Path) -> dict:
    """
    Extract prosody signals from Whisper word-timestamp transcript.
    - pause_rate: pauses > 0.5s per minute of speech
    - avg_pause_duration: mean pause length in seconds
    - speaking_segments: count of continuous speech blocks
    """
    if not transcript_path or not transcript_path.exists():
        return {}

    data     = json.loads(transcript_path.read_text())
    segments = data.get("segments", [])
    if not segments:
        return {}

    total_duration = data.get("duration", 0)
    pauses = []
    for i in range(1, len(segments)):
        gap = segments[i]["start"] - segments[i-1]["end"]
        if gap > 0.5:
            pauses.append(gap)

    minutes = total_duration / 60 if total_duration else 1
    return {
        "pause_count":        len(pauses),
        "pause_rate_per_min": round(len(pauses) / minutes, 2),
        "avg_pause_sec":      round(sum(pauses) / len(pauses), 2) if pauses else 0,
        "max_pause_sec":      round(max(pauses), 2) if pauses else 0,
        "total_segments":     len(segments),
        "total_duration_sec": total_duration,
    }


def segment_signals(frames: list[dict], transcript_path: Path) -> list[dict]:
    """
    Join face detections to transcript segments by timestamp.
    For each transcript segment: how many faces visible, avg face count.
    """
    if not transcript_path or not transcript_path.exists():
        return []

    t_data   = json.loads(transcript_path.read_text())
    segments = t_data.get("segments", [])

    # Build frame → face_count lookup
    frame_faces = {f["timestamp"]: len(f.get("faces", [])) for f in frames}

    result = []
    for seg in segments:
        start, end = seg["start"], seg["end"]
        # Frames within this segment
        seg_frames = [fc for ts, fc in frame_faces.items() if start <= ts <= end]
        result.append({
            "start":         start,
            "end":           end,
            "text":          seg["text"].strip(),
            "frame_count":   len(seg_frames),
            "avg_faces":     round(sum(seg_frames) / len(seg_frames), 2) if seg_frames else 0,
            "max_faces":     max(seg_frames) if seg_frames else 0,
        })
    return result


def analyze_video(entry: dict, signals_dir: Path, use_deepface: bool = False) -> dict | None:
    vid = entry["video_id"]
    out_path = signals_dir / f"{vid}.json"

    if out_path.exists():
        log.info("  signals exist, skip: %s", vid)
        return json.loads(out_path.read_text())

    video_path = entry.get("video_path")
    if not video_path or not Path(video_path).exists():
        log.warning("  no video file for %s — signals require --with-video in download.py", vid)
        return None

    transcript_path = Path(entry["transcript_path"]) if entry.get("transcript_path") else None

    log.info("  extracting frames from %s ...", vid)
    frames = extract_frames(Path(video_path))
    if not frames:
        return None

    # Face detection per frame
    faces_total = 0
    for f in frames:
        f["faces"] = detect_faces_cv2(f["frame"])
        faces_total += len(f["faces"])
        if use_deepface and f["faces"]:
            f["emotions"] = [
                analyze_emotion(f["frame"], face) for face in f["faces"]
            ]
        # Drop raw frame array before serializing
        del f["frame"]

    prosody  = prosody_from_transcript(transcript_path)
    seg_sigs = segment_signals(frames, transcript_path)

    result = {
        "video_id":           vid,
        "title":              entry.get("title", ""),
        "court":              entry.get("court", ""),
        "date":               entry.get("date"),
        "docket":             entry.get("docket"),
        "frames_extracted":   len(frames),
        "faces_detected":     faces_total,
        "avg_faces_per_frame": round(faces_total / len(frames), 2) if frames else 0,
        "prosody":            prosody,
        "frame_signals":      frames,           # timestamp + bbox + optional emotions
        "segment_signals":    seg_sigs,         # transcript-aligned face counts
        "analyzed_at":        datetime.now(timezone.utc).isoformat(),
        "deepface_used":      use_deepface,
    }

    out_path.write_text(json.dumps(result, indent=2))
    log.info("  signals → %s  (%d frames, %d faces)",
             out_path.name, len(frames), faces_total)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--deepface", action="store_true",
        help="Run DeepFace emotion classification (slow, optional)")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    # Dep check
    deps = check_deps()
    log.info("Deps: %s", deps)
    if not deps.get("cv2"):
        log.error("opencv-python required. Run: pip install opencv-python numpy")
        sys.exit(1)

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        log.error("Manifest not found: %s", manifest_path)
        sys.exit(1)

    manifest    = json.loads(manifest_path.read_text())
    data_dir    = manifest_path.parent
    signals_dir = data_dir / "signals"
    signals_dir.mkdir(exist_ok=True)

    entries = [
        e for e in manifest["entries"].values()
        if e.get("verify_verdict") in ("PASS", "WARN", "UNVERIFIED", None)
    ]
    if args.limit:
        entries = entries[:args.limit]

    log.info("Analyzing %d entries (deepface=%s)", len(entries), args.deepface)
    ok = skip = err = 0

    for i, entry in enumerate(entries, 1):
        vid = entry["video_id"]
        log.info("[%d/%d] %s — %s", i, len(entries), vid, entry.get("title", "")[:60])
        try:
            r = analyze_video(entry, signals_dir, use_deepface=args.deepface)
            if r is None:
                skip += 1
            else:
                manifest["entries"][vid]["analyzed"]       = True
                manifest["entries"][vid]["signals_path"]   = str(signals_dir / f"{vid}.json")
                manifest["entries"][vid]["faces_detected"] = r["faces_detected"]
                ok += 1
        except Exception as e:
            log.exception("Error analyzing %s: %s", vid, e)
            err += 1

        # Save manifest after every entry
        manifest_path.write_text(json.dumps(manifest, indent=2))

    log.info("Done — ok:%d  skip:%d  err:%d", ok, skip, err)


if __name__ == "__main__":
    main()
