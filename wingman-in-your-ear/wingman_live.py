"""
WINGMAN — Real-Time Tactical Earpiece Advisor
Built on Gemini 3.1 Flash Live · Monologue design aesthetic (terminal output)
June 2026

INSTALL:
    pip install google-genai pyaudio

RUN:
    export GEMINI_API_KEY="your_key_here"
    python wingman_live.py

WHAT IT DOES:
    Listens to your mic. Silent unless it catches a contradiction,
    logic flaw, or valid legal objection. When it speaks: ≤7 words,
    via your default speakers/earpiece. No chatter, no filler.
"""

import asyncio
import sys
import os
import wave
import io
from datetime import datetime
from google import genai
from google.genai import types

try:
    import pyaudio
except ImportError:
    print("[ABORT] pyaudio not found. Run: pip install pyaudio")
    sys.exit(1)

# ── CONFIG ──────────────────────────────────────────────────────────────────

MODEL_ID = "gemini-3.1-flash-live-preview"

LIVE_CONFIG = {
    "response_modalities": ["AUDIO"],
    "input_audio_transcription": {},   # lets us log what was heard
    "output_audio_transcription": {},  # lets us log what was said

    "system_instruction": (
        "You are a silent tactical courtroom and litigation advisor. "
        "Listen to the live dialogue stream. Do not transcribe or repeat what you hear. "
        "Cross-reference the statements against the rules of evidence and logic. "
        "Only speak when you catch a blatant contradiction, a logic flaw, or a valid legal objection. "
        "Keep your spoken notes under 7 words total. Be crisp, brutal, and fast."
    ),

    "speech_config": {
        "voice_config": {
            "prebuilt_voice_config": {
                "voice_name": "Kore"
            }
        }
    },

    # Minimal thinking — optimize for lowest latency
    "thinking_config": {
        "thinking_level": "minimal"
    }
}

# Audio specs — DO NOT CHANGE
INPUT_RATE  = 16000   # Gemini expects 16kHz in
OUTPUT_RATE = 24000   # Gemini returns 24kHz out
CHUNK       = 1600    # 100ms of audio at 16kHz
FORMAT      = pyaudio.paInt16
CHANNELS    = 1

# ── TERMINAL STYLE (Monologue aesthetic) ────────────────────────────────────

AQUA  = "\033[96m"
DIM   = "\033[2m"
BOLD  = "\033[1m"
RESET = "\033[0m"
RED   = "\033[91m"

def ts():
    return datetime.now().strftime("%H:%M:%S")

def log(source, msg, color=DIM):
    print(f"{color}[{ts()}] {source}: {msg}{RESET}")

def advisory(msg):
    """Wingman spoke — highlight it."""
    print(f"\n{AQUA}{BOLD}◈ WINGMAN [{ts()}]: {msg}{RESET}\n")

def header():
    print(f"""
{AQUA}╔══════════════════════════════════════════╗
║          W I N G M A N                  ║
║  Silent Tactical Courtroom Advisor       ║
╚══════════════════════════════════════════╝{RESET}
{DIM}Model : {MODEL_ID}
Voice : Kore  |  In: 16kHz  |  Out: 24kHz{RESET}
""")

# ── AUDIO I/O ───────────────────────────────────────────────────────────────

p = pyaudio.PyAudio()

def open_input():
    return p.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=INPUT_RATE,
        input=True,
        frames_per_buffer=CHUNK
    )

def open_output():
    return p.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=OUTPUT_RATE,
        output=True
    )

async def stream_mic(session):
    """Capture mic → send PCM chunks to Gemini Live."""
    mic = open_input()
    log("MIC", "Open — streaming 16kHz PCM to Gemini...", AQUA)
    try:
        while True:
            chunk = mic.read(CHUNK, exception_on_overflow=False)
            await session.send_realtime_input(
                audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000")
            )
            await asyncio.sleep(0)  # yield event loop
    except asyncio.CancelledError:
        pass
    finally:
        mic.stop_stream()
        mic.close()
        log("MIC", "Closed.", DIM)

async def receive_advisory(session):
    """Receive audio + transcripts from Gemini, play to earpiece."""
    speaker = open_output()
    log("EARPIECE", "Armed. Listening for advisories...", AQUA)
    try:
        async for response in session.receive():
            sc = response.server_content
            if not sc:
                continue

            # Log what the model transcribed from input
            if sc.input_transcription:
                log("HEARD", sc.input_transcription.text, DIM)

            # Play and log advisory audio
            if sc.model_turn:
                for part in sc.model_turn.parts:
                    if part.inline_data:
                        raw = part.inline_data.data
                        speaker.write(raw)
                    if part.text:
                        advisory(part.text)

            # Log what the model said (transcript)
            if sc.output_transcription:
                advisory(sc.output_transcription.text)

    except asyncio.CancelledError:
        pass
    finally:
        speaker.stop_stream()
        speaker.close()
        log("EARPIECE", "Closed.", DIM)

# ── MAIN ─────────────────────────────────────────────────────────────────────

async def main():
    header()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print(f"{RED}[ABORT] GEMINI_API_KEY not set.{RESET}")
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    log("SYSTEM", "Connecting to Gemini Live...", AQUA)
    try:
        async with client.aio.live.connect(model=MODEL_ID, config=LIVE_CONFIG) as session:
            log("SYSTEM", "WebSocket established. Session live.", AQUA)
            log("SYSTEM", "Speak freely. Wingman will interject only when it matters.", DIM)
            print(f"{DIM}─────────────────────────────────────────────{RESET}\n")

            mic_task      = asyncio.create_task(stream_mic(session))
            earpiece_task = asyncio.create_task(receive_advisory(session))

            try:
                await asyncio.gather(mic_task, earpiece_task)
            except KeyboardInterrupt:
                mic_task.cancel()
                earpiece_task.cancel()
                await asyncio.gather(mic_task, earpiece_task, return_exceptions=True)

    except Exception as e:
        print(f"{RED}[ERROR] {e}{RESET}")
        raise

    finally:
        p.terminate()
        print(f"\n{DIM}[{ts()}] SYSTEM: Session terminated.{RESET}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{DIM}Wingman offline.{RESET}")
