"""
verify_transcript.py
Kingsfield — Judicial Intelligence Pipeline, Stage 4
Compare Whisper transcript vs YouTube auto-captions + docket keywords.

This is the transcript integrity check before emotion/signal analysis.
A low match score = don't trust the transcript = don't analyze signals.

Usage:
  python3 judicial-intel/pipeline/verify_transcript.py \
    --manifest judicial-intel/data/fl_2dca/manifest.json

Output:
  - Adds verification scores to manifest.json
  - Writes data/<channel>/verified/<video_id>_verify.json per video
  - Prints a summary table

Scoring:
  word_overlap_pct  — WER-style word overlap between Whisper and YT captions
  keyword_hit_pct   — % of docket keywords found in transcript
  verdict           — PASS / WARN / FAIL
"""

from __future__ import annotations
import argparse, json, logging, re, sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s")
log = logging.getLogger("verify_transcript")

PASS_THRESHOLD  = 0.70   # word overlap >= 70% → PASS
WARN_THRESHOLD  = 0.50   # 50-70% → WARN (usable but flag)
                          # < 50% → FAIL

# Legal docket keywords to check presence in transcript
DOCKET_KEYWORDS = [
    "plaintiff", "defendant", "appellant", "appellee", "petitioner", "respondent",
    "motion", "order", "judgment", "ruling", "objection", "sustained", "overruled",
    "evidence", "exhibit", "witness", "testimony", "counsel", "court", "judge",
    "statute", "section", "florida", "appeal", "affirm", "reverse", "remand",
]


def normalize(text: str) -> list[str]:
    """Lowercase, strip punctuation, tokenize."""
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return [w for w in text.split() if len(w) > 1]


def parse_vtt(vtt_text: str) -> str:
    """Extract plain text from a WebVTT file."""
    lines = []
    for line in vtt_text.splitlines():
        line = line.strip()
        # Skip header, timestamps, empty lines
        if not line or line.startswith("WEBVTT") or "-->" in line:
            continue
        if re.match(r"^\d+$", line):
            continue
        # Strip HTML tags
        line = re.sub(r"<[^>]+>", "", line)
        if line:
            lines.append(line)
    return " ".join(lines)


def word_overlap(text_a: str, text_b: str) -> float:
    """Jaccard-style word overlap between two texts."""
    words_a = set(normalize(text_a))
    words_b = set(normalize(text_b))
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union        = words_a | words_b
    return len(intersection) / len(union)


def keyword_hit_rate(transcript_text: str, keywords: list[str]) -> float:
    words = set(normalize(transcript_text))
    hits  = sum(1 for kw in keywords if kw in words)
    return hits / len(keywords) if keywords else 0.0


def verify_entry(entry: dict, verified_dir: Path) -> dict | None:
    vid = entry["video_id"]
    out_path = verified_dir / f"{vid}_verify.json"

    if out_path.exists():
        return json.loads(out_path.read_text())

    # Get Whisper transcript text
    whisper_text = ""
    t_path = entry.get("transcript_path")
    if t_path and Path(t_path).exists():
        t_data = json.loads(Path(t_path).read_text())
        whisper_text = " ".join(s["text"] for s in t_data.get("segments", []))

    # Get YouTube captions text
    captions_text = ""
    c_path = entry.get("captions_path")
    if c_path and Path(c_path).exists():
        captions_text = parse_vtt(Path(c_path).read_text(errors="replace"))

    if not whisper_text and not captions_text:
        log.warning("No transcript or captions for %s — skip verify", vid)
        return None

    # Use whichever is available as the "reference" if only one exists
    if whisper_text and captions_text:
        overlap = word_overlap(whisper_text, captions_text)
        ref_source = "yt_captions"
    elif whisper_text:
        overlap = None
        ref_source = "whisper_only"
        captions_text = ""
    else:
        overlap = None
        ref_source = "captions_only"

    # Use the longer/available text for keyword check
    check_text = whisper_text or captions_text
    kw_rate    = keyword_hit_rate(check_text, DOCKET_KEYWORDS)

    # Verdict
    if overlap is None:
        verdict = "UNVERIFIED"   # only one source — can't cross-check
    elif overlap >= PASS_THRESHOLD:
        verdict = "PASS"
    elif overlap >= WARN_THRESHOLD:
        verdict = "WARN"
    else:
        verdict = "FAIL"

    result = {
        "video_id":          vid,
        "title":             entry.get("title", ""),
        "ref_source":        ref_source,
        "word_overlap_pct":  round(overlap, 3) if overlap is not None else None,
        "keyword_hit_pct":   round(kw_rate, 3),
        "verdict":           verdict,
        "whisper_word_count":  len(normalize(whisper_text)),
        "captions_word_count": len(normalize(captions_text)),
        "verified_at":       datetime.now(timezone.utc).isoformat(),
    }

    out_path.write_text(json.dumps(result, indent=2))
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        log.error("Manifest not found: %s", manifest_path)
        sys.exit(1)

    manifest     = json.loads(manifest_path.read_text())
    data_dir     = manifest_path.parent
    verified_dir = data_dir / "verified"
    verified_dir.mkdir(exist_ok=True)

    entries = list(manifest["entries"].values())
    results = []
    counts  = {"PASS": 0, "WARN": 0, "FAIL": 0, "UNVERIFIED": 0, "SKIP": 0}

    for i, entry in enumerate(entries, 1):
        vid = entry["video_id"]
        log.info("[%d/%d] %s", i, len(entries), vid)
        r = verify_entry(entry, verified_dir)
        if r is None:
            counts["SKIP"] += 1
            continue
        results.append(r)
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1

        # Update manifest
        manifest["entries"][vid]["verified"]          = True
        manifest["entries"][vid]["verify_verdict"]    = r["verdict"]
        manifest["entries"][vid]["word_overlap_pct"]  = r["word_overlap_pct"]
        manifest["entries"][vid]["keyword_hit_pct"]   = r["keyword_hit_pct"]

    manifest_path.write_text(json.dumps(manifest, indent=2))

    # Summary
    print(f"\n{'='*50}")
    print(f"Verification summary ({len(results)} videos)")
    for v, n in counts.items():
        print(f"  {v:12s}: {n}")
    print(f"{'='*50}")
    pass_rate = counts["PASS"] / max(len(results), 1) * 100
    print(f"  Pass rate: {pass_rate:.1f}%")


if __name__ == "__main__":
    main()
