#!/bin/bash
# Retry the 23 batch-2 videos whose audio download failed, then run them end to end. Double-click to run.
# Download now falls back to the smallest stream with audio. Failures -> diarization/_download_failed.txt
#  1) download audio on this Mac (one at a time, 23 files)   2) upload to Modal
#  3) speaker separation on Modal GPU   4) score vs YouTube marks   5) speaker-labelled transcripts
#  6) Jev panel (OpenRouter)   7) compare with caption-only scores
# Safe to re-run: every step skips work already done.
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || exit 1
LOG="$DIR/data/fl_2dca/diarization/_retry23.log"
exec > >(tee -a "$LOG") 2>&1
echo "===== run started $(date) ====="
IDS=data/fl_2dca/diarization/retry23_ids.txt
V="$DIR/.venv-modal"; M="$V/bin/modal"; P="$V/bin/python"
[ -x "$M" ] || { echo "Modal client missing: run RUN_diarize_pilot.command once first."; read -r; exit 1; }
# yt-dlp[default] adds yt-dlp-ejs (YouTube JS challenge solver); deno is its default JS runtime.
"$V/bin/pip" install -q "yt-dlp[default]==2026.8.19" "deno==2.9.7" requests || { echo "install failed"; read -r; exit 1; }
"$V/bin/deno" --version | head -1 || echo "WARNING: deno not runnable"
if [ -z "$OPENROUTER_API_KEY" ]; then
  OPENROUTER_API_KEY="$(grep -m1 '^OPENROUTER_API_KEY=' "$DIR/../../backend/.env" | cut -d= -f2- | tr -d '"'"'"' ')"; export OPENROUTER_API_KEY
fi

echo "=== 1/7 download audio ==="
"$P" pipeline/download_audio_batch.py --ids "$IDS"
echo; echo "=== 2/7 upload to Modal ==="
"$M" run pipeline/modal_diarize.py --mode upload --ids "$IDS" || { read -r; exit 1; }
echo; echo "=== 3/7 speaker separation (GPU) ==="
"$M" run pipeline/modal_diarize.py --mode run --ids "$IDS"
echo; echo "=== 4/7 score vs YouTube speaker marks (all diarized videos) ==="
"$P" pipeline/score_diarization.py --channel fl_2dca
echo; echo "=== 5/7 speaker-labelled transcripts ==="
"$P" pipeline/build_diar_transcripts.py --channel fl_2dca | tail -2
echo; echo "=== 6/7 Jev panel ==="
if [ -n "$OPENROUTER_API_KEY" ]; then
  "$P" pipeline/run_oa_panel.py --channel fl_2dca --tr-subdir transcripts_diar --out-tag diar --workers 6
else echo "OPENROUTER_API_KEY not found; skipped"; fi
echo; echo "=== 7/7 compare with caption-only scores ==="
"$P" pipeline/compare_diar_panel.py --channel fl_2dca
echo; echo "Done. Press return to close."; read -r
