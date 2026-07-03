#!/usr/bin/env python3
"""
Index a YouTube court channel — metadata only, no media download.
Resumable: re-run merges new videos into index.json.
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import channel_dir  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(os.path.dirname(HERE), "florida", "config.json")


def load_config(path: str) -> dict:
    return json.load(open(path))


def find_channel(cfg: dict, channel_id: str) -> dict:
    for ch in cfg.get("priority_channels", []):
        if ch["id"] == channel_id:
            return ch
    raise SystemExit(f"Unknown channel id: {channel_id}")


def _flatten_entries(node) -> list:
    """yt-dlp channel pages nest tabs → playlists → videos. Flatten to video dicts."""
    if not node:
        return []
    if isinstance(node, list):
        out = []
        for item in node:
            out.extend(_flatten_entries(item))
        return out
    if not isinstance(node, dict):
        return []

    vid = node.get("id")
    # YouTube video IDs are 11 chars; channel/playlist IDs start with UC / PL
    if vid and len(vid) == 11 and not vid.startswith(("UC", "PL")):
        return [{
            "video_id": vid,
            "title": node.get("title", ""),
            "url": node.get("url") or f"https://www.youtube.com/watch?v={vid}",
            "upload_date": node.get("upload_date"),
            "duration": node.get("duration"),
        }]

    out = []
    for child in node.get("entries") or []:
        out.extend(_flatten_entries(child))
    return out


def yt_dlp_index(url: str) -> list:
    """Flat playlist dump for a channel /videos tab."""
    # Channel handles need /videos — otherwise yt-dlp returns tab metadata, not videos
    if "@" in url and not url.rstrip("/").endswith(("videos", "streams", "shorts")):
        url = url.rstrip("/") + "/videos"

    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--dump-single-json",
        "--no-warnings",
        url,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    except FileNotFoundError:
        raise SystemExit("yt-dlp not found. Install: brew install yt-dlp  OR  pip install yt-dlp")
    if proc.returncode != 0:
        raise SystemExit(f"yt-dlp failed: {proc.stderr[:500]}")

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise SystemExit("yt-dlp returned non-JSON output")

    seen = {}
    for e in _flatten_entries(data):
        seen[e["video_id"]] = e
    return list(seen.values())


def main():
    ap = argparse.ArgumentParser(description="Index court YouTube channel")
    ap.add_argument("--config", default=CONFIG)
    ap.add_argument("--channel", required=True, help="Channel id from config (e.g. fl_2dca)")
    args = ap.parse_args()

    cfg = load_config(args.config)
    ch = find_channel(cfg, args.channel)
    out_dir = channel_dir(args.channel)
    index_path = os.path.join(out_dir, "index.json")

    existing = {}
    if os.path.exists(index_path):
        for e in json.load(open(index_path)).get("videos", []):
            existing[e["video_id"]] = e

    print(f"Indexing {ch['name']} …")
    print(f"URL: {ch['url']}")
    fresh = yt_dlp_index(ch["url"])

    merged = dict(existing)
    new_count = 0
    for e in fresh:
        if e["video_id"] not in merged:
            new_count += 1
        merged[e["video_id"]] = e

    index = {
        "channel_id": args.channel,
        "channel_name": ch["name"],
        "channel_url": ch["url"],
        "video_count": len(merged),
        "videos": sorted(merged.values(), key=lambda x: x.get("upload_date") or "", reverse=True),
    }
    json.dump(index, open(index_path, "w"), indent=2)
    print(f"Total videos: {len(merged)} ({new_count} new)")
    print(f"Wrote {index_path}")


if __name__ == "__main__":
    main()