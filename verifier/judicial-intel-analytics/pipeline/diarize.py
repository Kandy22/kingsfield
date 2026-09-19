#!/usr/bin/env python3
"""EchoScript-style diarization + audio emotion via Gemini (GAI template port)."""
import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import entry_paths, load_manifest, save_manifest  # noqa: E402

MODEL = "gemini-3-flash-preview"
CHUNK_MB = 18
CHUNK_SEC = 600  # 10 min — stays under Gemini inline limit


def _api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    if not key:
        raise RuntimeError("Set GEMINI_API_KEY")
    return key


def _parse_ts_start(ts: str) -> float:
    m = re.match(r"(\d{1,2}:\d{2}(?::\d{2})?)", (ts or "").strip())
    if not m:
        return 0.0
    parts = [int(p) for p in m.group(1).split(":")]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return 0.0


def _format_ts(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


def _shift_segment(seg: dict, offset_sec: float) -> dict:
    start = _parse_ts_start(seg.get("timestamp", ""))
    end_m = re.search(r"-\s*(\d{1,2}:\d{2}(?::\d{2})?)", seg.get("timestamp", ""))
    end = _parse_ts_start(end_m.group(1)) if end_m else start + 5
    new_start = start + offset_sec
    new_end = end + offset_sec
    out = dict(seg)
    out["timestamp"] = f"{_format_ts(new_start)} - {_format_ts(new_end)}"
    out["_t_start"] = new_start
    return out


def _split_audio(audio_path: str, chunk_dir: str) -> list[tuple[str, float]]:
    """Return [(chunk_path, offset_seconds), ...]."""
    size = os.path.getsize(audio_path)
    if size <= CHUNK_MB * 1024 * 1024:
        return [(audio_path, 0.0)]

    os.makedirs(chunk_dir, exist_ok=True)
    pattern = os.path.join(chunk_dir, "chunk_%03d.m4a")
    subprocess.run([
        "ffmpeg", "-y", "-i", audio_path,
        "-f", "segment", "-segment_time", str(CHUNK_SEC),
        "-c", "copy", pattern,
    ], check=True, capture_output=True)

    chunks = sorted(
        os.path.join(chunk_dir, f) for f in os.listdir(chunk_dir) if f.endswith(".m4a")
    )
    return [(p, i * CHUNK_SEC) for i, p in enumerate(chunks)]


def diarize_audio_chunk(audio_path: str) -> dict:
    from google import genai

    client = genai.Client(api_key=_api_key())
    with open(audio_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")

    prompt = """Process this court hearing audio. Return JSON only:
{"summary":"brief summary","segments":[{"speaker":"Speaker 1","timestamp":"00:00 - 00:15","content":"text","language":"English","language_code":"en","translation":"","emotion":"Neutral"}]}
emotion must be one of: Happy, Sad, Angry, Neutral."""

    response_schema = {
        "type": "OBJECT",
        "properties": {
            "summary": {"type": "STRING", "description": "A concise summary of the audio content."},
            "segments": {
                "type": "ARRAY",
                "description": "List of transcribed segments with speaker and timestamp.",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "speaker": {"type": "STRING"},
                        "timestamp": {"type": "STRING"},
                        "content": {"type": "STRING"},
                        "language": {"type": "STRING"},
                        "language_code": {"type": "STRING"},
                        "translation": {"type": "STRING"},
                        "emotion": {
                            "type": "STRING",
                            "description": "The emotion of the speaker.",
                            "enum": ["Happy", "Sad", "Angry", "Neutral"],
                        },
                    },
                    "required": ["speaker", "timestamp", "content", "language", "language_code", "emotion"],
                },
            },
        },
        "required": ["summary", "segments"],
    }

    response = client.models.generate_content(
        model=MODEL,
        contents=[
            {"inline_data": {"mime_type": "audio/mp4", "data": b64}},
            {"text": prompt},
        ],
        config={
            "response_mime_type": "application/json",
            "response_schema": response_schema,
        },
    )
    text = (response.text or "{}").strip()
    for fence in ("```json", "```"):
        text = text.removeprefix(fence).removesuffix(fence).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            raise
        return json.loads(m.group(0))


def diarize_audio(audio_path: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="diarize_") as tmp:
        chunks = _split_audio(audio_path, os.path.join(tmp, "chunks"))
        all_segments: list[dict] = []
        summaries: list[str] = []

        for chunk_path, offset in chunks:
            data = diarize_audio_chunk(chunk_path)
            if data.get("summary"):
                summaries.append(data["summary"])
            for seg in data.get("segments", []):
                all_segments.append(_shift_segment(seg, offset))

        all_segments.sort(key=lambda s: s.get("_t_start", 0))
        for seg in all_segments:
            seg.pop("_t_start", None)

        return {
            "summary": summaries[0] if summaries else "",
            "chunk_count": len(chunks),
            "segments": all_segments,
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", required=True)
    ap.add_argument("--video")
    ap.add_argument("--limit", type=int, default=5)
    args = ap.parse_args()

    manifest = load_manifest(args.channel)
    entries = list(manifest.get("entries", {}).values())
    if args.video:
        entries = [e for e in entries if e.get("video_id") == args.video]
    else:
        entries = [
            e for e in entries
            if os.path.exists(entry_paths(args.channel, e["video_id"])["audio"])
            and (e.get("diarization") or {}).get("status") != "done"
        ][: args.limit]

    for entry in entries:
        vid = entry["video_id"]
        paths = entry_paths(args.channel, vid)
        out_path = paths["diarize"]
        print(f"  {vid}")
        try:
            data = diarize_audio(paths["audio"])
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            manifest["entries"][vid]["diarization"] = {
                "status": "done",
                "path": out_path,
                "segment_count": len(data.get("segments", [])),
                "chunk_count": data.get("chunk_count", 1),
                "at": datetime.now(timezone.utc).isoformat(),
            }
            print(f"    -> {len(data.get('segments', []))} segments ({data.get('chunk_count', 1)} chunks)")
        except Exception as ex:
            manifest["entries"][vid]["diarization"] = {"status": "error", "error": str(ex)}
            print(f"    -> error: {ex}")
        save_manifest(args.channel, manifest)

    print("Done.")


if __name__ == "__main__":
    main()