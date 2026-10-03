#!/bin/bash
# Facial-expression probe, take 2. YouTube blocks Modal's servers, so this Mac downloads
# 3 argument videos (360p, picture only, about 50-100 MB each, one at a time) into
# data/fl_2dca/video/, uploads them to Modal, and Modal returns 4 frames per video with faces
# boxed plus face counts and sizes. Double-click to run. About 5 minutes.
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || exit 1
LOG="$DIR/data/fl_2dca/face_probe/_probe.log"
exec > >(tee -a "$LOG") 2>&1
echo "===== run started $(date) ====="
V="$DIR/.venv-modal"; M="$V/bin/modal"
export PATH="$V/bin:$PATH"
IDS=data/fl_2dca/face_probe/probe_ids.txt
mkdir -p data/fl_2dca/video
echo "=== 1/2 download 3 videos (360p, no audio) ==="
while read -r v; do
  [ -z "$v" ] && continue
  if [ -f "data/fl_2dca/video/$v.mp4" ]; then echo "  $v already here"; continue; fi
  "$V/bin/yt-dlp" --js-runtimes "deno:$V/bin/deno" -f "134/bv*[height<=360][ext=mp4]/18" \
     --no-playlist --no-progress --no-part -o "data/fl_2dca/video/$v.mp4" "https://www.youtube.com/watch?v=$v" 2>&1 | tail -1
  ls -la "data/fl_2dca/video/$v.mp4" 2>/dev/null || echo "  $v FAILED"
  sleep 5
done < "$IDS"
echo; echo "=== 2/2 upload + probe on Modal ==="
"$M" run pipeline/modal_face.py --mode upload --ids "$IDS"
"$M" run pipeline/modal_face.py --mode probe --ids "$IDS"
echo; echo "Done. Press return to close."; read -r
