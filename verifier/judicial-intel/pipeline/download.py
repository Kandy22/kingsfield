#!/usr/bin/env python3
"""
Download audio + YouTube auto-captions for indexed court videos.
Updates manifest.json per video — resumable.
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import entry_paths, load_manifest, save_manifest  # noqa: E402


def ensure_dir(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)


def already_done(paths: dict, download_video: bool = False) -> bool:
    audio_ok = os.path.exists(paths["audio"]) and os.path.getsize(paths["audio"]) > 1000
    if not audio_ok:
        return False
    if download_video:
        return os.path.exists(paths["video"]) and os.path.getsize(paths["video"]) > 1000
    return True


def download_one(video: dict, channel_id: str, download_video: bool) -> dict:
    vid = video["video_id"]
    paths = entry_paths(channel_id, vid)
    ensure_dir(paths["audio"])
    ensure_dir(paths["caption_yt"])

    if already_done(paths, download_video):
        return {"status": "skipped", "video_id": vid}

    url = video["url"]
    audio_tpl = os.path.join(os.path.dirname(paths["audio"]), "%(id)s.%(ext)s")

    cmd = [
        "yt-dlp",
        "-f", "bestaudio[ext=m4a]/bestaudio/best",
        "--write-auto-sub", "--sub-lang", "en", "--convert-subs", "vtt",
        "--no-warnings",
        "-o", audio_tpl,
        url,
    ]
    if download_video:
        ensure_dir(paths["video"])
        video_tpl = os.path.join(os.path.dirname(paths["video"]), "%(id)s.%(ext)s")
        cmd = [
            "yt-dlp",
            "-f", "bestvideo[height<=720]+bestaudio/best[height<=720]",
            "--write-auto-sub", "--sub-lang", "en", "--convert-subs", "vtt",
            "--merge-output-format", "mp4",
            "--no-warnings",
            "-o", video_tpl,
            url,
        ]

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if proc.returncode != 0:
        return {"status": "error", "video_id": vid, "error": proc.stderr[:300]}

    # Normalize caption path — yt-dlp often writes <id>.en.vtt next to audio
    for search_dir in (os.path.dirname(paths["audio"]), os.path.dirname(paths["caption_yt"])):
        if not os.path.isdir(search_dir):
            continue
        for name in os.listdir(search_dir):
            if name.startswith(vid) and name.endswith(".vtt"):
                src = os.path.join(search_dir, name)
                if src != paths["caption_yt"]:
                    os.replace(src, paths["caption_yt"])
                break
        if os.path.exists(paths["caption_yt"]):
            break

    return {
        "status": "downloaded",
        "video_id": vid,
        "audio_path": paths["audio"] if os.path.exists(paths["audio"]) else None,
        "caption_path": paths["caption_yt"] if os.path.exists(paths["caption_yt"]) else None,
        "video_path": paths["video"] if download_video and os.path.exists(paths["video"]) else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", required=True, help="Path to channel index.json")
    ap.add_argument("--channel", help="Channel id (inferred from index if omitted)")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--video", help="Single video_id override")
    ap.add_argument("--with-video", action="store_true", help="Also download video for signal analysis")
    args = ap.parse_args()

    index = json.load(open(args.index))
    channel_id = args.channel or index.get("channel_id")
    if not channel_id:
        raise SystemExit("--channel required if not in index.json")

    manifest = load_manifest(channel_id)
    videos = index.get("videos", [])

    if args.video:
        videos = [v for v in videos if v["video_id"] == args.video]
    else:
        videos = videos[args.offset: args.offset + args.limit]

    print(f"Downloading {len(videos)} videos for {channel_id} …")

    for i, video in enumerate(videos, 1):
        vid = video["video_id"]
        print(f"  [{i}/{len(videos)}] {vid} {video.get('title','')[:60]}")
        result = download_one(video, channel_id, args.with_video)
        manifest["entries"].setdefault(vid, {})
        manifest["entries"][vid].update({
            "video_id": vid,
            "title": video.get("title"),
            "url": video.get("url"),
            "upload_date": video.get("upload_date"),
            "download": result,
            "download_at": datetime.now(timezone.utc).isoformat(),
        })
        save_manifest(channel_id, manifest)
        print(f"    → {result['status']}")

    print(f"Manifest: {save_manifest(channel_id, manifest)}")


if __name__ == "__main__":
    main()