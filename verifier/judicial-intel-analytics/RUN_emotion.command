#!/bin/bash
# Emotion analysis of the 235 speaker-labelled 2DCA arguments, compared with the final orders.
# Double-click to run. No YouTube downloads: audio is already on Modal.
#  1) Jev emotion questions on the transcripts (OpenRouter, ~$0.10), 2-case check first
#  2) vocal emotion per speaker turn on Modal GPU (arousal / valence / dominance, loudness, pitch)
#  3) join to final orders and test (AUC, gap-0 cases, cross-validated vs the skepticism gap)
# Safe to re-run: every step skips work already done.
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || exit 1
LOG="$DIR/data/fl_2dca/panel/_emotion.log"
exec > >(tee -a "$LOG") 2>&1
echo "===== run started $(date) ====="
V="$DIR/.venv-modal"; M="$V/bin/modal"; P="$V/bin/python"
[ -x "$M" ] || { echo "Modal client missing: run RUN_diarize_pilot.command once first."; read -r; exit 1; }
"$V/bin/pip" install -q numpy requests || { echo "install failed"; read -r; exit 1; }
if [ -z "$OPENROUTER_API_KEY" ]; then
  OPENROUTER_API_KEY="$(grep -m1 '^OPENROUTER_API_KEY=' "$DIR/../../backend/.env" | cut -d= -f2- | tr -d '"'"'"' ')"; export OPENROUTER_API_KEY
fi
IDS=data/fl_2dca/diarization/emotion_ids.txt

echo "=== 1/3 transcript emotion (Jev) ==="
"$P" pipeline/run_oa_emotion.py --channel fl_2dca --limit 2 --workers 2
if grep -q '"error"' data/fl_2dca/panel/oa_emotion.diar.jsonl; then
  echo "STOPPED: the 2-case check returned errors (see the lines above)."; read -r; exit 1
fi
"$P" pipeline/run_oa_emotion.py --channel fl_2dca --workers 6

echo; echo "=== 2/3 voice emotion (Modal GPU) ==="
"$M" run pipeline/modal_emotion.py --ids "$IDS"

echo; echo "=== 3/3 compare with final orders ==="
"$P" pipeline/analyze_emotion.py fl_2dca

echo; echo "Done. Press return to close."; read -r
