"""Shared path helpers for the judicial-intel pipeline."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")


def channel_dir(channel_id: str) -> str:
    path = os.path.join(DATA, channel_id)
    os.makedirs(path, exist_ok=True)
    return path


def load_manifest(channel_id: str) -> dict:
    path = os.path.join(channel_dir(channel_id), "manifest.json")
    if os.path.exists(path):
        return json.load(open(path))
    return {"channel_id": channel_id, "entries": {}}


def save_manifest(channel_id: str, manifest: dict) -> str:
    path = os.path.join(channel_dir(channel_id), "manifest.json")
    json.dump(manifest, open(path, "w"), indent=2)
    return path


def entry_paths(channel_id: str, video_id: str) -> dict:
    base = channel_dir(channel_id)
    return {
        "audio": os.path.join(base, "audio", f"{video_id}.m4a"),
        "video": os.path.join(base, "video", f"{video_id}.mp4"),
        "caption_yt": os.path.join(base, "captions", f"{video_id}.vtt"),
        "transcript_srt": os.path.join(base, "transcripts", f"{video_id}.srt"),
        "transcript_json": os.path.join(base, "transcripts", f"{video_id}.json"),
        "signals": os.path.join(base, "signals", f"{video_id}.json"),
        "frames_dir": os.path.join(base, "frames", video_id),
        "diarize": os.path.join(base, "transcripts", f"{video_id}.diarize.json"),
        "timeline": os.path.join(base, "timelines", f"{video_id}.json"),
    }