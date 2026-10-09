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

# ---- channel / district config ---------------------------------------------
import re as _re

_CFG = os.path.join(ROOT, "florida", "config.json")


def channel_config(channel_id: str) -> dict:
    """Entry from florida/config.json for this channel (district_prefix, district_name, url…)."""
    try:
        for ch in json.load(open(_CFG)).get("priority_channels", []):
            if ch["id"] == channel_id:
                return ch
    except FileNotFoundError:
        pass
    return {"id": channel_id}


# Every way a case number shows up in a court's YouTube title:
#   "25 1145"  "2D19 852"  "Case # 25-2288"  "Case #23 3607"  "25-0673"  "22_0553___23_1107"
_CASE_RE = _re.compile(r"(?<![\d-])(?:[1-6]D)?\s*(\d{2})\s*[-_ ]\s*(\d{1,5})(?!\d)")


def parse_case_numbers(title: str) -> list:
    """[(year, seq), ...] for every case number in a title. Two-digit years are
    read as 20YY; a 4-digit run that looks like a date component is skipped."""
    out = []
    for m in _CASE_RE.finditer(title or ""):
        yy, seq = int(m.group(1)), int(m.group(2))
        if not (15 <= yy <= 40):          # not a plausible appellate year
            continue
        if len(m.group(2)) == 4 and 1990 <= seq <= 2099:  # "12/17/2024" false hit
            continue
        out.append((2000 + yy, seq))
    return list(dict.fromkeys(out))


def format_case_number(prefix: str, year: int, seq: int) -> str:
    """CourtListener-style docket number, e.g. 2D2025-1145 / 6D2025-0673."""
    return f"{prefix}{year}-{seq:04d}"
