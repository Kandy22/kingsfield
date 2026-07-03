"""
download.py
Kingsfield — Judicial Intelligence Pipeline, Stage 2
Video/audio + YouTube auto-captions → manifest.json

Usage:
  python3 judicial-intel/pipeline/download.py \
    --index judicial-intel/data/fl_2dca/index.json \
    --limit 10

  python3 judicial-intel/pipeline/download.py \
    --index judicial-intel/data/fl_2dca/index.json \
    --audio-only          # skip video, saves ~80% disk

Resumable: skips anything already in manifest.json.
"""

from __future__ import annotations
import argparse, json, logging, subprocess, sys, time, random
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s")
log = logging.getLogger("download")

SLEEP_MIN = 3
SLEEP_MAX = 7
RETRIES   = 3


def load_index(path: Path) -> dict:
    return json.loads(path.read_text())


def load_manifest(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {"entries": {}}


def save_manifest(path: Path, manifest: dict):
    path.write_text(json.dumps(manifest, indent=2))


def download_entry(entry: dict, media_dir: Path, subs_dir: Path,
                   audio_only: bool) -> dict:
    vid = entry["video_id"]
    url = entry["url"]
    result = {
        "video_id":    vid,
        "title":       entry["title"],
        "court":       entry.get("court", ""),
        "date":        entry.get("upload_date"),
        "docket":      entry.get("docket_number"),
        "url":         url,
        "audio_path":  None,
        "video_path":  None,
        "captions_path": None,
        "downloaded_at": None,
        "error":       None,
    }

    # Audio path (always)
    audio_out = media_dir / f"{vid}.m4a"
    video_out = media_dir / f"{vid}.mp4"
    sub_glob  = list(subs_dir.glob(f"{vid}*.vtt"))

    # Skip if already done
    audio_done = audio_out.exists() and audio_out.stat().st_size > 0
    video_done = (not audio_only) and video_out.exists() and video_out.stat().st_size > 0
    subs_done  = bool(sub_glob)

    if (audio_done or video_done) and subs_done:
        result["audio_path"]    = str(audio_out) if audio_done else None
        result["video_path"]    = str(video_out) if video_done else None
        result["captions_path"] = str(sub_glob[0])
        result["downloaded_at"] = "cached"
        return result

    # Build yt-dlp command
    if audio_only:
        fmt_args = ["-f", "bestaudio[ext=m4a]/bestaudio", "-o", str(audio_out)]
    else:
        fmt_args = [
            "-f", "bv*[height<=720]+ba/b[height<=720]",
            "--merge-output-format", "mp4",
            "-o", str(video_out),
        ]

    for attempt in range(1, RETRIES + 1):
        r = subprocess.run(
            ["yt-dlp"] + fmt_args +
            [
                "--write-sub", "--write-auto-sub",
                "--sub-lang", "en.*",
                "--sub-format", "vtt",
                "--convert-subs", "vtt",
                "--sub-langs", "en",
                "--write-sub",
                "--paths", f"subtitle:{subs_dir}",
                url,
            ],
            capture_output=True, text=True
        )
        if r.returncode == 0:
            break
        log.warning("yt-dlp attempt %d/%d failed for %s: %s",
                    attempt, RETRIES, vid, r.stderr.strip()[:150])
        time.sleep(SLEEP_MIN * attempt)

    # Check outputs
    if audio_only and audio_out.exists():
        result["audio_path"] = str(audio_out)
    elif video_out.exists():
        result["video_path"] = str(video_out)
    else:
        result["error"] = "download failed after retries"
        log.error("Download failed: %s", vid)
        return result

    sub_glob = list(subs_dir.glob(f"{vid}*.vtt"))
    if sub_glob:
        result["captions_path"] = str(sub_glob[0])
        log.info("  captions: %s", sub_glob[0].name)
    else:
        log.info("  no captions found — transcribe.py will run Whisper")

    result["downloaded_at"] = datetime.now(timezone.utc).isoformat()
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", required=True,
        help="Path to index.json from index_channel.py")
    ap.add_argument("--limit", type=int, default=None,
        help="Process only first N entries")
    ap.add_argument("--audio-only", action="store_true",
        help="Download audio only (no video). Saves ~80pct disk. Captions still fetched.")
    ap.add_argument("--force", action="store_true",
        help="Re-download even if manifest says done")
    args = ap.parse_args()

    index_path = Path(args.index)
    if not index_path.exists():
        log.error("Index not found: %s — run index_channel.py first", index_path)
        sys.exit(1)

    index     = load_index(index_path)
    data_dir  = index_path.parent
    media_dir = data_dir / "media"
    subs_dir  = data_dir / "subs"
    manifest_path = data_dir / "manifest.json"

    media_dir.mkdir(parents=True, exist_ok=True)
    subs_dir.mkdir(parents=True, exist_ok=True)

    manifest = load_manifest(manifest_path)
    entries  = index.get("entries", [])
    if args.limit:
        entries = entries[:args.limit]

    log.info("Processing %d/%d entries (audio_only=%s)",
             len(entries), index.get("total", "?"), args.audio_only)

    ok = skip = err = 0
    for i, entry in enumerate(entries, 1):
        vid = entry["video_id"]
        if vid in manifest["entries"] and not args.force:
            log.info("[%d/%d] skip (manifest): %s", i, len(entries), vid)
            skip += 1
            continue

        log.info("[%d/%d] %s — %s", i, len(entries), vid, entry["title"][:60])
        result = download_entry(entry, media_dir, subs_dir, args.audio_only)

        manifest["entries"][vid] = result
        if result.get("error"):
            err += 1
        else:
            ok += 1

        # Save manifest after every entry (resumable)
        save_manifest(manifest_path, manifest)

        if i < len(entries):
            time.sleep(random.uniform(SLEEP_MIN, SLEEP_MAX))

    log.info("Done — ok:%d  skip:%d  err:%d", ok, skip, err)
    log.info("Manifest → %s", manifest_path)


if __name__ == "__main__":
    main()
