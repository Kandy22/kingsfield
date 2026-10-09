#!/bin/bash
# List the 1st, 4th and 5th DCA YouTube channels (titles and dates only, no video download)
# and report how many videos are single-case oral arguments. Double-click to run. Takes a few minutes.
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || exit 1
LOG="$DIR/data/_index_dcas.log"
exec > >(tee -a "$LOG") 2>&1
echo "===== run started $(date) ====="
V="$DIR/.venv-modal"; P="$V/bin/python"
export PATH="$V/bin:$PATH"
for ch in fl_5dca fl_4dca fl_1dca; do
  echo; echo "=== $ch ==="
  "$P" pipeline/index_channel.py --channel "$ch" || echo "$ch: index failed"
  sleep 20
done
echo; echo "=== summary ==="
"$P" pipeline/summarize_index.py fl_5dca fl_4dca fl_1dca fl_6dca fl_2dca
echo; echo "Done. Press return to close."; read -r
