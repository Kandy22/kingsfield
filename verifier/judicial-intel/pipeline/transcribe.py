#!/usr/bin/env python3
"""
Transcribe court oral-argument audio → SRT + JSON.
Prefers local faster-whisper; falls back to OpenAI Whisper API.

Resumable via manifest.json. Chunks long files with ffmpeg.
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import entry_paths, load_manifest, save_manifest  # noqa: E402

CHUNK_MINUTES = 15


def srt_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def segments_to_srt(segments: list) -> str:
    lines = []
    for i, seg in enumerate(segments, 1):
        start = seg.get("start", 0)
        end = seg.get("end", start + 1)
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        lines.append(str(i))
        lines.append(f"{srt_timestamp(start)} --> {srt_timestamp(end)}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def transcribe_faster_whisper(audio_path: str, model_name: str, device: str) -> list:
    from faster_whisper import WhisperModel  # type: ignore

    model = WhisperModel(model_name, device=device, compute_type="int8" if device == "cpu" else "float16")
    segments, _ = model.transcribe(
        audio_path,
        temperature=0.0,
        vad_filter=True,
        word_timestamps=False,
    )
    return [{"start": s.start, "end": s.end, "text": s.text} for s in segments]


def transcribe_openai_api(audio_path: str, api_key: str) -> list:
    import requests

    # Chunk if needed (25MB limit)
    size_mb = os.path.getsize(audio_path) / (1024 * 1024)
    if size_mb > 24:
        return transcribe_chunked_openai(audio_path, api_key)

    with open(audio_path, "rb") as f:
        r = requests.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_key}"},
            files={"file": (os.path.basename(audio_path), f, "audio/m4a")},
            data={"model": "whisper-1", "response_format": "verbose_json", "temperature": "0"},
            timeout=600,
        )
    r.raise_for_status()
    data = r.json()
    return [{"start": s["start"], "end": s["end"], "text": s["text"]} for s in data.get("segments", [])]


def transcribe_chunked_openai(audio_path: str, api_key: str) -> list:
    import requests
    import tempfile

    tmp = tempfile.mkdtemp()
    chunk_pattern = os.path.join(tmp, "chunk_%03d.m4a")
    subprocess.run([
        "ffmpeg", "-y", "-i", audio_path,
        "-f", "segment", "-segment_time", str(CHUNK_MINUTES * 60),
        "-c", "copy", chunk_pattern,
    ], check=True, capture_output=True)

    all_segments = []
    offset = 0.0
    for fname in sorted(os.listdir(tmp)):
        if not fname.endswith(".m4a"):
            continue
        chunk_path = os.path.join(tmp, fname)
        with open(chunk_path, "rb") as f:
            r = requests.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": (fname, f, "audio/m4a")},
                data={"model": "whisper-1", "response_format": "verbose_json", "temperature": "0"},
                timeout=600,
            )
        r.raise_for_status()
        data = r.json()
        for s in data.get("segments", []):
            all_segments.append({
                "start": s["start"] + offset,
                "end": s["end"] + offset,
                "text": s["text"],
            })
        offset += CHUNK_MINUTES * 60
    return all_segments


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", help="Path to manifest.json")
    ap.add_argument("--channel", help="Channel id (uses data/<channel>/manifest.json)")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--video", help="Single video_id")
    ap.add_argument("--engine", choices=["faster-whisper", "openai"], default="faster-whisper")
    ap.add_argument("--model", default=os.environ.get("WHISPER_MODEL", "large-v3"))
    ap.add_argument("--device", default=os.environ.get("WHISPER_DEVICE", "cpu"))
    args = ap.parse_args()

    if args.manifest:
        manifest = json.load(open(args.manifest))
        channel_id = manifest.get("channel_id") or args.channel
    elif args.channel:
        channel_id = args.channel
        manifest = load_manifest(channel_id)
    else:
        raise SystemExit("Provide --manifest or --channel")

    entries = list(manifest.get("entries", {}).values())
    if args.video:
        entries = [e for e in entries if e.get("video_id") == args.video]
    else:
        entries = [e for e in entries if not (e.get("transcription") or {}).get("status") == "done"][: args.limit]

    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_KEY", "")

    for i, entry in enumerate(entries, 1):
        vid = entry["video_id"]
        paths = entry_paths(channel_id, vid)
        audio = paths["audio"]
        print(f"  [{i}/{len(entries)}] {vid}")

        if not os.path.exists(audio):
            print("    → skip (no audio)")
            continue
        if os.path.exists(paths["transcript_srt"]) and os.path.getsize(paths["transcript_srt"]) > 50:
            print("    → skip (already transcribed)")
            continue

        os.makedirs(os.path.dirname(paths["transcript_srt"]), exist_ok=True)

        try:
            if args.engine == "faster-whisper":
                segments = transcribe_faster_whisper(audio, args.model, args.device)
                engine = f"faster-whisper/{args.model}"
            else:
                if not api_key:
                    raise RuntimeError("OPENAI_API_KEY not set")
                segments = transcribe_openai_api(audio, api_key)
                engine = "openai/whisper-1"
        except Exception as ex:
            print(f"    → error: {ex}")
            manifest["entries"][vid]["transcription"] = {"status": "error", "error": str(ex)}
            save_manifest(channel_id, manifest)
            continue

        srt = segments_to_srt(segments)
        with open(paths["transcript_srt"], "w", encoding="utf-8") as f:
            f.write(srt)
        with open(paths["transcript_json"], "w", encoding="utf-8") as f:
            json.dump({"video_id": vid, "engine": engine, "segments": segments}, f, indent=2)

        manifest["entries"][vid]["transcription"] = {
            "status": "done",
            "engine": engine,
            "segment_count": len(segments),
            "srt_path": paths["transcript_srt"],
            "at": datetime.now(timezone.utc).isoformat(),
        }
        save_manifest(channel_id, manifest)
        print(f"    → {len(segments)} segments")

    print("Done.")


if __name__ == "__main__":
    main()