#!/usr/bin/env python3
"""Merge transcript, EchoScript diarization, and visual signals into one timeline."""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import entry_paths, load_manifest, save_manifest  # noqa: E402


def parse_mmss(ts: str) -> float | None:
    """Parse 'MM:SS' or 'H:MM:SS' to seconds."""
    ts = ts.strip()
    parts = [int(p) for p in ts.split(":") if p.isdigit()]
    if not parts:
        return None
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return None


def parse_timestamp_range(value: str) -> tuple[float | None, float | None]:
    m = re.match(r"(\d{1,2}:\d{2}(?::\d{2})?)\s*-\s*(\d{1,2}:\d{2}(?::\d{2})?)", value or "")
    if not m:
        return None, None
    return parse_mmss(m.group(1)), parse_mmss(m.group(2))


def load_json(path: str) -> dict | list | None:
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def nearest_frame(frames: list[dict], t: float, interval: int) -> dict | None:
    if not frames:
        return None
    best = None
    best_dist = interval + 1
    for i, fr in enumerate(frames):
        ft = fr.get("t")
        if ft is None:
            ft = i * interval
        dist = abs(ft - t)
        if dist < best_dist:
            best_dist = dist
            best = fr
    return best if best_dist <= interval else None


def segments_from_diarize(data: dict) -> list[dict]:
    out = []
    for seg in data.get("segments", []):
        start, end = parse_timestamp_range(seg.get("timestamp", ""))
        if start is None:
            continue
        out.append({
            "t": start,
            "end": end if end is not None else start,
            "speaker": seg.get("speaker") or "unknown",
            "text": seg.get("content") or "",
            "emotion_audio": seg.get("emotion"),
            "source": "diarization",
        })
    return out


def segments_from_transcript(data: dict) -> list[dict]:
    out = []
    for seg in data.get("segments", []):
        start = seg.get("start")
        if start is None:
            continue
        out.append({
            "t": float(start),
            "end": float(seg.get("end", start)),
            "speaker": seg.get("speaker") or "unknown",
            "text": seg.get("text") or "",
            "emotion_audio": None,
            "source": "transcript",
        })
    return out


def merge_entry(channel: str, video_id: str, frame_interval: int) -> dict:
    paths = entry_paths(channel, video_id)
    signals = load_json(paths["signals"]) or {}
    transcript = load_json(paths["transcript_json"]) or {}
    diarize_path = os.path.join(
        os.path.dirname(paths["transcript_json"]), f"{video_id}.diarize.json"
    )
    diarize = load_json(diarize_path)

    base_segments = (
        segments_from_diarize(diarize)
        if diarize and diarize.get("segments")
        else segments_from_transcript(transcript)
    )

    frames = []
    for i, fr in enumerate(signals.get("frames") or []):
        frames.append({**fr, "t": fr.get("t", i * frame_interval)})

    timeline = []
    for seg in base_segments:
        fr = nearest_frame(frames, seg["t"], frame_interval)
        row = {
            "t": round(seg["t"], 2),
            "end": round(seg.get("end", seg["t"]), 2),
            "speaker": seg["speaker"],
            "text": seg["text"],
            "emotion_audio": seg.get("emotion_audio"),
            "source": seg.get("source"),
        }
        if fr:
            if fr.get("mood_score_visual") is not None:
                row["mood_score_visual"] = fr["mood_score_visual"]
            if fr.get("dominant_emotion"):
                row["dominant_emotion_visual"] = fr["dominant_emotion"]
            if fr.get("gaze") is not None:
                row["gaze"] = fr["gaze"]
            if fr.get("gaze_note"):
                row["gaze_note"] = fr["gaze_note"]
            if fr.get("posture"):
                row["posture"] = fr["posture"]
            if fr.get("shot_class"):
                row["shot_class"] = fr["shot_class"]
            if fr.get("face_count") is not None:
                row["face_count"] = fr["face_count"]
        timeline.append(row)

    os.makedirs(os.path.dirname(paths["timeline"]), exist_ok=True)
    payload = {
        "video_id": video_id,
        "channel": channel,
        "merged_at": datetime.now(timezone.utc).isoformat(),
        "segment_count": len(timeline),
        "has_diarization": bool(diarize and diarize.get("segments")),
        "has_visual": bool(frames),
        "timeline": timeline,
    }
    with open(paths["timeline"], "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return payload


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", required=True)
    ap.add_argument("--video")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--frame-interval", type=int, default=30)
    args = ap.parse_args()

    manifest = load_manifest(args.channel)
    entries = list(manifest.get("entries", {}).values())
    if args.video:
        entries = [e for e in entries if e.get("video_id") == args.video]
    else:
        entries = [
            e for e in entries
            if (e.get("transcription") or {}).get("status") == "done"
        ][: args.limit]

    for entry in entries:
        vid = entry["video_id"]
        print(f"  {vid}")
        try:
            payload = merge_entry(args.channel, vid, args.frame_interval)
            manifest["entries"][vid]["timeline"] = {
                "status": "done",
                "path": entry_paths(args.channel, vid)["timeline"],
                "segment_count": payload["segment_count"],
                "at": datetime.now(timezone.utc).isoformat(),
            }
            print(f"    -> {payload['segment_count']} segments")
        except Exception as ex:
            manifest["entries"][vid]["timeline"] = {"status": "error", "error": str(ex)}
            print(f"    -> error: {ex}")
        save_manifest(args.channel, manifest)

    print("Done.")


if __name__ == "__main__":
    main()