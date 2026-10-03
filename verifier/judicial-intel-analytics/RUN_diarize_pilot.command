#!/bin/bash
# Nemotron 3 Diarization pilot on Modal (cloud GPU). Double-click to run.
# Your Mac only uploads 35 audio files (~1.2 GB) and receives small JSON results.
# Steps: 1) Modal client + login  2) upload  3) YouTube download test  4) diarize  5) score
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || exit 1
# Everything shown in Terminal is also saved here, so Claude can read it without copy-paste.
LOG="$DIR/data/fl_2dca/diarization/_run.log"
exec > >(tee -a "$LOG") 2>&1
echo "===== run started $(date) ====="
pause(){ read -r -p "$1 [y/N] " a; [ "$a" = "y" ]; }

PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  command -v "$c" >/dev/null && "$c" -c 'import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)' && { PY="$c"; break; }
done
[ -n "$PY" ] || { echo "Need Python 3.10+ (Modal requirement). Press return."; read -r; exit 1; }

VENV="$DIR/.venv-modal"
# cbor2 6.x (a Modal dependency) ships Mac wheels for Apple Silicon only; on an Intel Mac pip
# tries to compile it with Rust and fails. cbor2 5.9.0 is pure Python and installs anywhere.
if [ ! -x "$VENV/bin/modal" ]; then
  echo "=== setting up Modal client in $VENV ==="
  "$PY" -m venv "$VENV" && "$VENV/bin/pip" install -q "modal==1.5.5" "cbor2<6" || { echo "install failed"; read -r; exit 1; }
fi
M="$VENV/bin/modal"

if [ ! -f "$HOME/.modal.toml" ]; then
  echo "=== 1/5 Modal login (opens your browser) ==="
  "$M" setup || { echo "login failed"; read -r; exit 1; }
fi

echo "=== 2/5 upload 35 audio files to Modal volume kf-oa-audio ==="
"$M" run pipeline/modal_diarize.py --mode upload --ids data/fl_2dca/diarization/pilot_ids.txt || { read -r; exit 1; }

# 3/5 YouTube download test: done 2026-09-25. Modal is blocked by YouTube's bot check, so
# further audio is downloaded on the Mac. Re-run manually with --mode ytprobe if needed.

echo; pause "=== 4/5 diarize the 35 videos on an L4 GPU (first run builds the image, a few minutes)?" || exit 0
"$M" run pipeline/modal_diarize.py --mode run --ids data/fl_2dca/diarization/pilot_ids.txt

echo; echo "=== 5/5 score against YouTube speaker marks ==="
"$PY" pipeline/score_diarization.py --channel fl_2dca
echo; echo "Results: data/fl_2dca/diarization/  (one JSON per video + _score.json). Press return to close."; read -r
