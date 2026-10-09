#!/usr/bin/env python3
"""
Pull YouTube auto-captions + full metadata for every clip in the index.
No media download. Resumable: skips any video that already has a .vtt or
.info.json on disk, so re-running only fetches what is missing.

Writes to data/<channel>/captions/:
    <video_id>.vtt          auto-captions (rolling-cue format, dedupe later)
    <video_id>.info.json    full yt-dlp metadata: upload_date, description,
                            view_count, duration, title — the join source for
                            the output CSV
    _pull_<n>.log           one log per worker

Usage:
    python3 pipeline/pull_captions.py --channel fl_2dca --workers 3
    python3 pipeline/pull_captions.py --channel fl_2dca --dry-run
"""
import argparse
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import channel_dir  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Second source of video ids. index_channel.py drops any 11-char id that
# happens to start with "UC" (mistaking it for a channel id), so the raw
# yt-dlp dump is unioned in to recover those.
FIRECRAWL = os.path.join(ROOT, "..", "..", "Firecrawl Data Scrapes", "fl_2dca_index.json")


def clip_ids(channel_id: str) -> dict:
    """{video_id: title} for every individual clip. Live-session streams are
    excluded — they duplicate the clips and exceed the model's state budget."""
    out = {}
    idx = os.path.join(channel_dir(channel_id), "index.json")
    for v in json.load(open(idx)).get("videos", []):
        out[v["video_id"]] = v.get("title", "")

    if channel_id == "fl_2dca" and os.path.exists(FIRECRAWL):
        fc = json.load(open(FIRECRAWL))
        for tab in fc.get("entries", []):
            if "Live" in (tab.get("title") or ""):
                continue
            for e in tab.get("entries") or []:
                vid = e.get("id")
                if vid and len(vid) == 11:
                    out.setdefault(vid, e.get("title", ""))
    return out


def already_pulled(cap_dir: str, vid: str) -> bool:
    return (
        os.path.exists(os.path.join(cap_dir, f"{vid}.vtt"))
        or os.path.exists(os.path.join(cap_dir, f"{vid}.en.vtt"))
    ) and os.path.exists(os.path.join(cap_dir, f"{vid}.info.json"))


def normalize_names(cap_dir: str) -> int:
    """yt-dlp writes <id>.en.vtt; the pipeline expects <id>.vtt."""
    n = 0
    for name in os.listdir(cap_dir):
        if name.endswith(".en.vtt"):
            src = os.path.join(cap_dir, name)
            dst = os.path.join(cap_dir, name[: -len(".en.vtt")] + ".vtt")
            if not os.path.exists(dst):
                os.replace(src, dst)
                n += 1
    return n


KEEP = (
    "id", "title", "upload_date", "timestamp", "release_timestamp", "duration",
    "view_count", "like_count", "comment_count", "description", "uploader",
    "channel_id", "webpage_url", "categories", "tags", "chapters", "live_status",
    "was_live", "availability", "language",
)


def slim_metadata(cap_dir: str) -> int:
    """Rewrite each info.json down to the join fields. The raw dump is ~500 KB
    per video, almost all of it format tables and per-language caption URLs."""
    n = 0
    for name in os.listdir(cap_dir):
        if not name.endswith(".info.json"):
            continue
        path = os.path.join(cap_dir, name)
        if os.path.getsize(path) < 20_000:
            continue  # already slim
        try:
            d = json.load(open(path))
        except Exception:
            continue
        slim = {k: d.get(k) for k in KEEP}
        slim["caption_langs_auto"] = sorted((d.get("automatic_captions") or {}).keys())
        slim["caption_langs_manual"] = sorted((d.get("subtitles") or {}).keys())
        with open(path, "w") as f:
            json.dump(slim, f, indent=1, ensure_ascii=False)
        n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="fl_2dca")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--sleep", type=float, default=1.0, help="seconds between requests per worker")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cap_dir = os.path.join(channel_dir(args.channel), "captions")
    os.makedirs(cap_dir, exist_ok=True)

    ids = clip_ids(args.channel)
    todo = [v for v in ids if not already_pulled(cap_dir, v)]
    pulled = len(ids) - len(todo)
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(ids)} clips indexed, {pulled} already pulled, {len(todo)} to fetch")
    if args.dry_run or not todo:
        return

    # Round-robin the work across N yt-dlp processes.
    batches = [todo[i :: args.workers] for i in range(args.workers)]
    procs = []
    for n, batch in enumerate(batches):
        if not batch:
            continue
        url_file = os.path.join(cap_dir, f"_urls_{n}.txt")
        with open(url_file, "w") as f:
            f.write("\n".join(f"https://www.youtube.com/watch?v={v}" for v in batch) + "\n")
        log = open(os.path.join(cap_dir, f"_pull_{n}.log"), "a")
        cmd = [
            "yt-dlp",
            "--skip-download",
            "--write-auto-sub", "--sub-lang", "en", "--sub-format", "vtt",
            "--write-info-json",
            "--no-write-playlist-metafiles",
            "--ignore-errors",
            "--no-warnings",
            "--retries", "3", "--extractor-retries", "3",
            "--sleep-requests", str(args.sleep),
            "-o", os.path.join(cap_dir, "%(id)s.%(ext)s"),
            "--batch-file", url_file,
        ]
        procs.append((n, subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT), log, len(batch)))
        print(f"  worker {n}: {len(batch)} videos -> _pull_{n}.log")

    t0 = time.time()
    while any(p.poll() is None for _, p, _, _ in procs):
        time.sleep(30)
        done = sum(1 for v in todo if already_pulled(cap_dir, v))
        # count vtt files, not info.json — some videos have metadata but no captions
        vtts = sum(1 for v in todo if os.path.exists(os.path.join(cap_dir, f"{v}.en.vtt"))
                   or os.path.exists(os.path.join(cap_dir, f"{v}.vtt")))
        print(f"  [{int(time.time()-t0)//60:>3}m] {done}/{len(todo)} complete, {vtts} with captions", flush=True)

    for n, p, log, _ in procs:
        log.close()
        print(f"  worker {n} exited {p.returncode}")

    renamed = normalize_names(cap_dir)
    slimmed = slim_metadata(cap_dir)
    have_vtt = sum(1 for v in ids if os.path.exists(os.path.join(cap_dir, f"{v}.vtt")))
    have_meta = sum(1 for v in ids if os.path.exists(os.path.join(cap_dir, f"{v}.info.json")))
    no_caps = [v for v in ids if os.path.exists(os.path.join(cap_dir, f"{v}.info.json"))
               and not os.path.exists(os.path.join(cap_dir, f"{v}.vtt"))]
    print(f"\ndone in {int(time.time()-t0)//60}m. renamed {renamed}, slimmed {slimmed} info.json.")
    print(f"  captions : {have_vtt}/{len(ids)}")
    print(f"  metadata : {have_meta}/{len(ids)}")
    print(f"  metadata but NO captions: {len(no_caps)}  (these need Whisper or Gemini)")
    with open(os.path.join(cap_dir, "_no_captions.txt"), "w") as f:
        f.write("\n".join(no_caps) + ("\n" if no_caps else ""))


if __name__ == "__main__":
    main()
