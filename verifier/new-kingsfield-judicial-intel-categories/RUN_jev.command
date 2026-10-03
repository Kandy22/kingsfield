#!/bin/bash
# Jev over OpenRouter for the judicial-intel catalog. Double-click to run.
# 1) smoke test (2 tiny calls)  2) 10-case F08/F09 validation  3) asks before the full corpus.
# Key: $OPENROUTER_API_KEY, else read from kingsfield/backend/.env (never printed).
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || exit 1
PY=""
for c in "$DIR/../venv-judicial/bin/python3" "$DIR/../venv/bin/python3" python3; do
  "$c" -c "import requests" 2>/dev/null && { PY="$c"; break; }
done
[ -n "$PY" ] || { echo "No python with 'requests' found. Press return."; read -r; exit 1; }
echo "python: $PY"

echo "=== 1/3 smoke test ==="
"$PY" src/jev.py --smoke
echo
read -r -p "Smoke OK? Run 10-case validation (~\$0.003)? [y/N] " a
[ "$a" = "y" ] || exit 0

echo "=== 2/3 validation: 10 cases ==="
"$PY" src/jev.py --job classify --channel fl_2dca --limit 10
echo
read -r -p "Run the rest of FL 2DCA (~1,400 cases, ~\$0.46) then FL 6DCA? [y/N] " b
[ "$b" = "y" ] || exit 0

echo "=== 3/3 full ==="
"$PY" src/jev.py --job classify --channel fl_2dca --workers 6
"$PY" src/jev.py --job classify --channel fl_6dca --workers 6
echo "Done. Outputs in data/jev/<channel>/. Press return to close."; read -r
