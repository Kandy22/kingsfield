"""
csv_to_index.py
Kingsfield — Judicial Intelligence Pipeline, Stage 0.5
Browser-scraped YouTube CSV → pipeline index.json

Accepts the browser-extension channel scrapes (columns like
"ytLockupViewModelContentImage href", "ytBadgeShapeText" = duration,
"ytAttributedStringHost" = title, "... 2" = views, "... 3" = streamed/age).

Usage:
  python3 judicial-intel/pipeline/csv_to_index.py \
      --channel fl_supreme \
      --channel-name "Florida Supreme Court" \
      --channel-url "https://www.youtube.com/@FloridaSupremeCourtTallahassee" \
      "fl-supreme-court-yt/youtube-117-videos.csv" \
      "fl-supreme-court-yt/youtube-168-videos.csv"

Merges into judicial-intel/data/<channel>/index.json (dedupes by video_id,
never overwrites richer yt-dlp metadata with CSV data). The rest of the
pipeline (download.py, transcribe.py, verify_transcript.py,
analyze_signals.py) consumes the same index.json unchanged.
"""
from __future__ import annotations
import argparse, csv, json, re, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # judicial-intel/

VIDEO_ID_RE = re.compile(r"[?&]v=([A-Za-z0-9_-]{11})")

URL_COLS = ("ytLockupViewModelContentImage href", "yt-simple-endpoint href")
DUR_COLS = ("ytBadgeShapeText",)
TITLE_COLS = ("ytAttributedStringHost",)
VIEWS_COLS = ("ytAttributedStringHost 2",)
AGE_COLS = ("ytAttributedStringHost 3",)


def pick(row: dict, cols) -> str | None:
    for c in cols:
        v = (row.get(c) or "").strip()
        if v:
            return v
    return None


def duration_to_seconds(s: str | None) -> float | None:
    if not s:
        return None
    parts = s.strip().split(":")
    if not all(p.strip().isdigit() for p in parts):
        return None
    parts = [int(p) for p in parts]
    if len(parts) == 3:
        return float(parts[0] * 3600 + parts[1] * 60 + parts[2])
    if len(parts) == 2:
        return float(parts[0] * 60 + parts[1])
    if len(parts) == 1:
        return float(parts[0])
    return None


def parse_csv(path: Path) -> list[dict]:
    out = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            url = pick(row, URL_COLS)
            if not url:
                continue
            m = VIDEO_ID_RE.search(url)
            if not m:
                continue
            vid = m.group(1)
            out.append({
                "video_id": vid,
                "title": pick(row, TITLE_COLS),
                "url": f"https://www.youtube.com/watch?v={vid}",
                "upload_date": None,
                "duration": duration_to_seconds(pick(row, DUR_COLS)),
                "views": pick(row, VIEWS_COLS),
                "age_text": pick(row, AGE_COLS),
                "source": f"csv:{path.name}",
            })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csvs", nargs="+", help="one or more scraped CSV files")
    ap.add_argument("--channel", required=True, help="channel key, e.g. fl_supreme")
    ap.add_argument("--channel-name", default=None)
    ap.add_argument("--channel-url", default=None)
    args = ap.parse_args()

    data_dir = ROOT / "data" / args.channel
    data_dir.mkdir(parents=True, exist_ok=True)
    index_path = data_dir / "index.json"

    if index_path.exists():
        index = json.loads(index_path.read_text())
    else:
        index = {
            "channel_id": args.channel,
            "channel_name": args.channel_name or args.channel,
            "channel_url": args.channel_url,
            "video_count": 0,
            "videos": [],
        }

    existing = {v["video_id"]: v for v in index["videos"]}
    added = updated = skipped = bad = 0

    for c in args.csvs:
        p = Path(c)
        if not p.exists():
            print(f"!! missing: {p}", file=sys.stderr)
            bad += 1
            continue
        rows = parse_csv(p)
        if not rows:
            print(f"!! no parseable rows (wrong CSV format?): {p}", file=sys.stderr)
            bad += 1
            continue
        for r in rows:
            cur = existing.get(r["video_id"])
            if cur is None:
                existing[r["video_id"]] = r
                added += 1
            else:
                # fill gaps only — never clobber yt-dlp metadata
                changed = False
                for k, v in r.items():
                    if v is not None and cur.get(k) in (None, ""):
                        cur[k] = v
                        changed = True
                updated += changed
                skipped += not changed
        print(f"   {p.name}: {len(rows)} rows")

    index["videos"] = list(existing.values())
    index["video_count"] = len(index["videos"])
    index["csv_import_at"] = datetime.now(timezone.utc).isoformat()
    if args.channel_name:
        index["channel_name"] = args.channel_name
    if args.channel_url:
        index["channel_url"] = args.channel_url
    index_path.write_text(json.dumps(index, indent=2))

    print(f"\n→ {index_path}")
    print(f"   total {index['video_count']} | +{added} new, {updated} enriched, {skipped} already present, {bad} bad files")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
