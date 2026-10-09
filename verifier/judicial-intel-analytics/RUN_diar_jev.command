#!/bin/bash
# Re-score the 35 diarized pilot arguments with Jev (OpenRouter) and compare with the
# caption-only scores. Double-click to run. Cost: ~35 x 8k tokens x $0.042/M ≈ $0.01.
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || exit 1
LOG="$DIR/data/fl_2dca/panel/_diar_run.log"
exec > >(tee -a "$LOG") 2>&1
echo "===== run started $(date) ====="

PY=""
for c in "$DIR/.venv-modal/bin/python" "$DIR/../venv-judicial/bin/python3" "$DIR/../venv/bin/python3" python3; do
  "$c" -c "import requests" 2>/dev/null && { PY="$c"; break; }
done
if [ -z "$PY" ] && [ -x "$DIR/.venv-modal/bin/pip" ]; then
  "$DIR/.venv-modal/bin/pip" install -q requests && PY="$DIR/.venv-modal/bin/python"
fi
[ -n "$PY" ] || { echo "No python with 'requests'. Press return."; read -r; exit 1; }

if [ -z "$OPENROUTER_API_KEY" ]; then
  OPENROUTER_API_KEY="$(grep -m1 '^OPENROUTER_API_KEY=' "$DIR/../../backend/.env" | cut -d= -f2- | tr -d '"'"'"' ')"
  export OPENROUTER_API_KEY
fi
[ -n "$OPENROUTER_API_KEY" ] || { echo "OPENROUTER_API_KEY not found (env or kingsfield/backend/.env)."; read -r; exit 1; }

echo "=== 1/3 build speaker-attributed transcripts (local, seconds) ==="
"$PY" pipeline/build_diar_transcripts.py --channel fl_2dca | tail -2

echo; echo "=== 2/3 Jev panel on diarized transcripts ==="
"$PY" pipeline/run_oa_panel.py --channel fl_2dca --tr-subdir transcripts_diar --out-tag diar \
      --ids data/fl_2dca/diarization/pilot_ids.txt --dump-raw --workers 6

echo; echo "=== 3/3 compare with caption-only scores ==="
"$PY" pipeline/compare_diar_panel.py --channel fl_2dca
echo; echo "Done. Press return to close."; read -r
