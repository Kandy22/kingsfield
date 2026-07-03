"""
transcribe.py
Kingsfield — Judicial Intelligence Pipeline, Stage 3
faster-whisper (local) → .srt + .json per video

Usage:
  python3 judicial-intel/pipeline/transcribe.py \
    --manifest judicial-intel/data/fl_2dca/manifest.json \
    --limit 10

Skips videos that already have captions from download.py unless --force.
Skips videos already transcribed.
Writes: data/<channel>/transcripts/<video_id>.json + .srt
Updates manifest.json with transcript_path.
"""

from __future__ import annotations
import argparse, json, logging, sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s")
log = logging.getLogger("transcribe")

WHISPER_MODEL   = "large-v3"
WHISPER_DEVICE  = "cpu"
WHISPER_COMPUTE = "int8"   # int8 is fastest on Apple Silicon CPU, no quality loss for speech

_model = None


def get_model():
    global _model
    if _model is None:
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            log.error("faster-whisper not installed. Run: pip install faster-whisper")
            sys.exit(1)
        log.info("Loading faster-whisper %s ...", WHISPER_MODEL)
        _model = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE,
                              compute_type=WHISPER_COMPUTE)
        log.info("Model loaded.")
    return _model


def segments_to_srt(segments) -> str:
    lines = []
    for i, seg in enumerate(segments, 1):
        start = format_ts(seg["start"])
        end   = format_ts(seg["end"])
        lines.append(f"{i}\n{start} --> {end}\n{seg['text'].strip()}\n")
    return "\n".join(lines)


def format_ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def transcribe_file(audio_path: Path, video_id: str) -> dict:
    model = get_model()
    log.info("Transcribing %s ...", audio_path.name)
    raw_segments, info = model.transcribe(
        str(audio_path),
        beam_size=5,
        vad_filter=True,
        temperature=0,           # greedy — most accurate for legal speech
        word_timestamps=True,
    )
    segments = [
        {
            "start": round(s.start, 3),
            "end":   round(s.end, 3),
            "text":  s.text.strip(),
            "words": [
                {"word": w.word, "start": round(w.start, 3), "end": round(w.end, 3),
                 "probability": round(w.probability, 3)}
                for w in (s.words or [])
            ]
        }
        for s in raw_segments
    ]
    return {
        "video_id":    video_id,
        "language":    info.language,
        "language_probability": round(info.language_probability, 3),
        "duration":    round(info.duration, 1),
        "model":       WHISPER_MODEL,
        "source":      "faster-whisper",
        "transcribed_at": datetime.now(timezone.utc).isoformat(),
        "segments":    segments,
    }


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text())


def save_manifest(path: Path, m: dict):
    path.write_text(json.dumps(m, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True,
        help="Path to manifest.json from download.py")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--force", action="store_true",
        help="Re-transcribe even if transcript exists")
    ap.add_argument("--skip-if-captions", action="store_true", default=True,
        help="Skip Whisper if YouTube captions exist (default True)")
    args = ap.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        log.error("Manifest not found: %s — run download.py first", manifest_path)
        sys.exit(1)

    manifest     = load_manifest(manifest_path)
    data_dir     = manifest_path.parent
    transcript_dir = data_dir / "transcripts"
    transcript_dir.mkdir(exist_ok=True)

    entries = list(manifest["entries"].values())
    if args.limit:
        entries = entries[:args.limit]

    ok = skip = err = 0
    for i, entry in enumerate(entries, 1):
        vid = entry["video_id"]

        # Skip if already transcribed
        t_path = transcript_dir / f"{vid}.json"
        if t_path.exists() and not args.force:
            log.info("[%d/%d] skip (transcript exists): %s", i, len(entries), vid)
            skip += 1
            continue

        # Skip if YouTube captions exist and --skip-if-captions
        if args.skip_if_captions and entry.get("captions_path"):
            cap = Path(entry["captions_path"])
            if cap.exists():
                log.info("[%d/%d] skip (captions exist): %s", i, len(entries), vid)
                skip += 1
                continue

        # Need audio or video file
        audio = entry.get("audio_path") or entry.get("video_path")
        if not audio or not Path(audio).exists():
            log.warning("[%d/%d] no media file for %s — skip", i, len(entries), vid)
            err += 1
            continue

        log.info("[%d/%d] %s — %s", i, len(entries), vid, entry.get("title", "")[:60])
        try:
            result = transcribe_file(Path(audio), vid)
        except Exception as e:
            log.exception("Transcription failed for %s: %s", vid, e)
            err += 1
            continue

        # Write JSON
        t_path.write_text(json.dumps(result, indent=2))

        # Write SRT
        srt_path = transcript_dir / f"{vid}.srt"
        srt_path.write_text(segments_to_srt(result["segments"]))

        # Update manifest
        manifest["entries"][vid]["transcript_path"] = str(t_path)
        manifest["entries"][vid]["srt_path"]        = str(srt_path)
        manifest["entries"][vid]["transcribed"]     = True
        save_manifest(manifest_path, manifest)
        ok += 1
        log.info("  → %d segments, lang=%s", len(result["segments"]), result["language"])

    log.info("Done — ok:%d  skip:%d  err:%d", ok, skip, err)


if __name__ == "__main__":
    main()
