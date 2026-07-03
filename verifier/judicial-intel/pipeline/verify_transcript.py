#!/usr/bin/env python3
"""
Verify our transcript against YouTube auto-captions (first sanity check).

Computes fuzzy overlap score. This is NOT legal citation verification —
it answers: did we transcribe what the platform's captions think was said?

Resumable via manifest.json.
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import entry_paths, load_manifest, save_manifest  # noqa: E402

try:
    from rapidfuzz import fuzz
except ImportError:
    sys.exit("rapidfuzz required: pip install rapidfuzz")

THRESHOLD_VERIFIED = 75
THRESHOLD_PARTIAL = 55


def parse_vtt(path: str) -> str:
    if not os.path.exists(path):
        return ""
    raw = open(path, encoding="utf-8", errors="ignore").read()
    lines = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("WEBVTT") or "-->" in line or re.match(r"^\d+$", line):
            continue
        if re.match(r"^\d{2}:\d{2}", line):
            continue
        lines.append(re.sub(r"<[^>]+>", "", line))
    return " ".join(lines)


def parse_srt(path: str) -> str:
    if not os.path.exists(path):
        return ""
    raw = open(path, encoding="utf-8", errors="ignore").read()
    lines = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or "-->" in line or re.match(r"^\d+$", line):
            continue
        lines.append(line)
    return " ".join(lines)


def normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def verify_pair(ours: str, theirs: str) -> dict:
    if not ours:
        return {"status": "no_transcript", "score": 0}
    if not theirs:
        return {"status": "no_captions", "score": 0}
    n1, n2 = normalize(ours), normalize(theirs)
    if len(n2) < 200:
        return {"status": "captions_too_short", "score": 0, "caption_chars": len(n2)}
    score = round(fuzz.token_set_ratio(n1, n2), 1)
    if score >= THRESHOLD_VERIFIED:
        status = "verified"
    elif score >= THRESHOLD_PARTIAL:
        status = "partial"
    else:
        status = "mismatch"
    return {
        "status": status,
        "score": score,
        "transcript_chars": len(n1),
        "caption_chars": len(n2),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", help="Path to manifest.json")
    ap.add_argument("--channel", help="Channel id")
    ap.add_argument("--video", help="Single video_id")
    ap.add_argument("--limit", type=int, default=0, help="0 = all pending")
    args = ap.parse_args()

    if args.manifest:
        manifest = json.load(open(args.manifest))
        channel_id = manifest.get("channel_id") or args.channel
    elif args.channel:
        channel_id = args.channel
        manifest = load_manifest(channel_id)
    else:
        raise SystemExit("Provide --manifest or --channel")

    entries = list(manifest.get("entries", {}).values())
    if args.video:
        entries = [e for e in entries if e.get("video_id") == args.video]
    else:
        pending = [e for e in entries if (e.get("transcription") or {}).get("status") == "done"
                   and not (e.get("transcript_verification") or {}).get("status")]
        entries = pending if args.limit == 0 else pending[: args.limit]

    stats = {"verified": 0, "partial": 0, "mismatch": 0, "no_captions": 0, "other": 0}

    for entry in entries:
        vid = entry["video_id"]
        paths = entry_paths(channel_id, vid)
        ours = parse_srt(paths["transcript_srt"])
        theirs = parse_vtt(paths["caption_yt"])
        result = verify_pair(ours, theirs)
        result["at"] = datetime.now(timezone.utc).isoformat()

        manifest["entries"][vid]["transcript_verification"] = result
        save_manifest(channel_id, manifest)

        st = result["status"]
        stats[st] = stats.get(st, 0) + 1
        print(f"  {vid}: {st} score={result.get('score', 0)}")

    print("Summary:", stats)


if __name__ == "__main__":
    main()