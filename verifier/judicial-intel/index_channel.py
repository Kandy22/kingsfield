"""
index_channel.py
Kingsfield — Judicial Intelligence Pipeline, Stage 1
YouTube/archive metadata → channel_index.json

Usage:
  python3 judicial-intel/pipeline/index_channel.py \
    --config judicial-intel/florida/config.json \
    --channel fl_2dca

If ~/Desktop/fl_2dca_index.json already exists (from a prior yt-dlp run),
this script will consume it directly and normalize it into the pipeline format
rather than re-fetching.

Output: judicial-intel/data/<channel>/index.json
"""

from __future__ import annotations
import argparse, json, logging, re, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s")
log = logging.getLogger("index_channel")

# ── Default channel configs (override with --config) ──────────────────────────

BUILTIN_CONFIGS = {
    "fl_2dca": {
        "channel_id": "@seconddistrictcourtofappea8708",
        "channel_url": "https://www.youtube.com/@seconddistrictcourtofappea8708",
        "court": "FL 2nd DCA",
        "state": "FL",
        "data_dir": "judicial-intel/data/fl_2dca",
        "legacy_index": "~/Desktop/fl_2dca_index.json",   # reuse if present
    },
    "fl_supreme": {
        "channel_id": "@FloridaSupremeCourtTallahassee",
        "channel_url": "https://www.youtube.com/@FloridaSupremeCourtTallahassee",
        "court": "Florida Supreme Court",
        "state": "FL",
        "data_dir": "judicial-intel/data/fl_supreme",
        "legacy_index": None,
    },
    "fl_1dca": {
        "channel_id": "@firstdistrictcourtofappeal493",
        "channel_url": "https://www.youtube.com/@firstdistrictcourtofappeal493",
        "court": "FL 1st DCA",
        "state": "FL",
        "data_dir": "judicial-intel/data/fl_1dca",
        "legacy_index": None,
    },
    "co_judicial": {
        "channel_id": "@cojudicial",
        "channel_url": "https://www.youtube.com/@cojudicial",
        "court": "Colorado Judicial Branch",
        "state": "CO",
        "data_dir": "judicial-intel/data/co_judicial",
        "legacy_index": None,
        "note": "Primary archive at cojudicial.ompnetwork.org — needs separate scraper",
    },
    "tenth_circuit": {
        "channel_id": "@UCz4oP87ziTjb7WpRwIGZf0g",
        "channel_url": "https://www.youtube.com/@UCz4oP87ziTjb7WpRwIGZf0g",
        "court": "10th Circuit",
        "state": "federal",
        "data_dir": "judicial-intel/data/tenth_circuit",
        "legacy_index": None,
        "note": "Removes recordings after live stream — capture live or lose them",
    },
}


def fmt_date(yyyymmdd: str | None) -> str | None:
    if not yyyymmdd or len(yyyymmdd) != 8:
        return None
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"


def parse_docket(title: str) -> str | None:
    m = re.search(r"\b(\d?D?\d{2,4}[-– ]\d{3,5})\b", title)
    return m.group(1).replace(" ", "-").replace("–", "-") if m else None


def normalize_entry(raw: dict, cfg: dict) -> dict:
    vid = raw.get("id") or raw.get("url", "").split("v=")[-1]
    title = raw.get("title", "")
    return {
        "video_id":      vid,
        "title":         title,
        "url":           raw.get("webpage_url") or f"https://www.youtube.com/watch?v={vid}",
        "upload_date":   fmt_date(raw.get("upload_date")),
        "duration":      raw.get("duration"),
        "court":         cfg["court"],
        "state":         cfg["state"],
        "docket_number": parse_docket(title),
        "thumbnail":     raw.get("thumbnail"),
        # pipeline state — all False at index time
        "downloaded":    False,
        "transcribed":   False,
        "verified":      False,
        "analyzed":      False,
    }


def load_legacy(path: Path, cfg: dict) -> list[dict]:
    raw = path.read_text()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = [json.loads(l) for l in raw.splitlines() if l.strip()]
    if isinstance(data, dict):
        data = data.get("entries", [data])
    entries = []
    for e in data:
        if not e.get("id"):
            continue
        entries.append(normalize_entry(e, cfg))
    return entries


def fetch_yt_index(cfg: dict) -> list[dict]:
    """Run yt-dlp --flat-playlist to get fresh metadata."""
    url = cfg["channel_url"]
    log.info("Fetching YouTube index for %s ...", url)
    r = subprocess.run(
        ["yt-dlp", "--flat-playlist", "--dump-single-json", url],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        log.error("yt-dlp failed: %s", r.stderr[:300])
        return []
    data = json.loads(r.stdout)
    entries = data.get("entries", [])
    log.info("Got %d entries from YouTube", len(entries))
    return [normalize_entry(e, cfg) for e in entries if e.get("id")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", required=True,
        help="Channel key e.g. fl_2dca, fl_supreme, co_judicial")
    ap.add_argument("--config", default=None,
        help="Optional JSON config file (overrides builtin)")
    ap.add_argument("--force-fetch", action="store_true",
        help="Ignore legacy index and re-fetch from YouTube")
    ap.add_argument("--base", default=".",
        help="Base directory (default: current dir)")
    args = ap.parse_args()

    # Load config
    if args.config and Path(args.config).exists():
        cfg = json.loads(Path(args.config).read_text())
    elif args.channel in BUILTIN_CONFIGS:
        cfg = BUILTIN_CONFIGS[args.channel]
    else:
        log.error("Unknown channel '%s' and no --config provided", args.channel)
        sys.exit(1)

    base = Path(args.base)
    data_dir = base / cfg["data_dir"]
    data_dir.mkdir(parents=True, exist_ok=True)
    out_path = data_dir / "index.json"

    # Check for existing index
    if out_path.exists() and not args.force_fetch:
        existing = json.loads(out_path.read_text())
        log.info("Index already exists: %d entries. Use --force-fetch to refresh.",
                 len(existing.get("entries", [])))
        return

    # Try legacy desktop index first (fl_2dca only)
    entries = []
    legacy = cfg.get("legacy_index")
    if legacy and not args.force_fetch:
        legacy_path = Path(legacy).expanduser()
        if legacy_path.exists():
            log.info("Found legacy index at %s — consuming it", legacy_path)
            entries = load_legacy(legacy_path, cfg)
            log.info("Loaded %d entries from legacy index", len(entries))

    # Fall back to fresh yt-dlp fetch
    if not entries:
        entries = fetch_yt_index(cfg)

    if not entries:
        log.error("No entries found. Check channel URL or run yt-dlp manually.")
        sys.exit(1)

    # Deduplicate
    seen = set()
    unique = []
    for e in entries:
        if e["video_id"] not in seen:
            seen.add(e["video_id"])
            unique.append(e)
    log.info("%d unique videos after dedup", len(unique))

    output = {
        "channel":    args.channel,
        "court":      cfg["court"],
        "state":      cfg["state"],
        "indexed_at": datetime.now(timezone.utc).isoformat(),
        "total":      len(unique),
        "entries":    unique,
    }
    out_path.write_text(json.dumps(output, indent=2))
    log.info("Index written → %s", out_path)


if __name__ == "__main__":
    main()
