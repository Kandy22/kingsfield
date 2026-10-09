#!/bin/bash
# Kingsfield Verifier — finish the judicial pipeline (diarize + merge).
# Double-click to run. Everything upstream (download/transcribe/verify/signals) is already done.
cd "$(dirname "$0")"   # -> verifier/

echo "=== Kingsfield Verifier: diarize + merge (fl_2dca) ==="

if [ ! -f venv-judicial/bin/activate ]; then
  echo "ERROR: venv-judicial not found in $(pwd). Aborting."
  echo "Press any key to close."; read -n1; exit 1
fi
source venv-judicial/bin/activate

# Load verifier/.env, then resolve the Gemini key (verifier GEMINI_KEY, else backend GEMINI_API_KEY)
set -a; [ -f .env ] && source .env; set +a
export GEMINI_API_KEY="${GEMINI_API_KEY:-${GEMINI_KEY:-$(grep '^GEMINI_API_KEY=' ../backend/.env 2>/dev/null | cut -d= -f2-)}}"
if [ -z "$GEMINI_API_KEY" ]; then
  echo "ERROR: No Gemini API key found in verifier/.env or backend/.env. Aborting."
  echo "Press any key to close."; read -n1; exit 1
fi

CHANNEL="fl_2dca"; LIMIT="5"

echo ">> [1/2] Diarize (Gemini) — hearings cwPVWKqwg4A, B2UqO1OV1BA"
python3 judicial-intel/pipeline/diarize.py --channel "$CHANNEL" --limit "$LIMIT" || { echo "diarize failed"; echo "Press any key."; read -n1; exit 1; }

echo ">> [2/2] Merge timeline"
python3 judicial-intel/pipeline/merge_signals.py --channel "$CHANNEL" --limit "$LIMIT" || { echo "merge failed"; echo "Press any key."; read -n1; exit 1; }

echo ""
echo "=== DONE. Manifest: judicial-intel/data/$CHANNEL/manifest.json ==="
echo "Press any key to close."; read -n1
