#!/bin/bash
# FL judicial intel — run all stages. Feed at leisure by changing LIMIT.
set -e
cd "$(dirname "$0")/../.."
source venv-judicial/bin/activate

# Load verifier/.env (OPENAI_API_KEY, WHISPER_MODEL, WHISPER_DEVICE, GEMINI_KEY, …)
if [ -f .env ]; then
  set -a; source .env; set +a
fi
# Gemini key: env var > verifier/.env GEMINI_KEY > backend/.env GEMINI_API_KEY
export GEMINI_API_KEY="${GEMINI_API_KEY:-${GEMINI_KEY:-$(grep '^GEMINI_API_KEY=' ../backend/.env 2>/dev/null | cut -d= -f2-)}}"
LIMIT="${1:-5}"
CHANNEL="${2:-fl_2dca}"

echo "=== DOWNLOAD (limit $LIMIT) ==="
python3 judicial-intel/pipeline/download.py --index judicial-intel/data/$CHANNEL/index.json --limit "$LIMIT"

echo "=== TRANSCRIBE ==="
python3 judicial-intel/pipeline/transcribe.py --channel "$CHANNEL" --limit "$LIMIT" --model small

echo "=== VERIFY TRANSCRIPT ==="
python3 judicial-intel/pipeline/verify_transcript.py --channel "$CHANNEL"

echo "=== GAI DIARIZE (echoscript) ==="
python3 judicial-intel/pipeline/diarize.py --channel "$CHANNEL" --limit "$LIMIT"

echo "=== ANALYZE SIGNALS ==="
python3 judicial-intel/pipeline/analyze_signals.py --channel "$CHANNEL" --limit "$LIMIT" --skip-frames

echo "=== MERGE TIMELINE ==="
python3 judicial-intel/pipeline/merge_signals.py --channel "$CHANNEL" --limit "$LIMIT"

echo "=== DONE ==="
echo "Manifest: judicial-intel/data/$CHANNEL/manifest.json"