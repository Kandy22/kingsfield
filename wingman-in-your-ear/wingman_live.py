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
from google.genai import errors as genai_errors

try:
    import pyaudio
except ImportError:
    print("[ABORT] pyaudio not found. Run: pip install pyaudio")
    sys.exit(1)

# ── CONFIG ──────────────────────────────────────────────────────────────────

MODEL_ID = "gemini-3.1-flash-live-preview"

# Agent harnesses — same files wingman-demo's server.ts loads (harness/*.md).
# Select with: python wingman_live.py [court_pro_se|broadcast_market|deposition]
HARNESS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "harness")
AGENTS = {
    "court_pro_se":     {"file": "court_pro_se.md",     "voice": "Charon", "label": "Court Pro Se"},
    "broadcast_market": {"file": "broadcast_market.md", "voice": "Fenrir", "label": "Broadcast Market Watch"},
    "deposition":       {"file": "deposition.md",       "voice": "Charon", "label": "Deposition"},
}
DEFAULT_AGENT = "court_pro_se"

FALLBACK_INSTRUCTION = (
    "You are a silent tactical courtroom and litigation advisor. "
    "Listen to the live dialogue stream. Do not transcribe or repeat what you hear. "
    "Cross-reference the statements against the rules of evidence and logic. "
    "Only speak when you catch a blatant contradiction, a logic flaw, or a valid legal objection. "
    "Keep your spoken notes under 7 words total. Be crisp, brutal, and fast. "
    "When silent, produce no output whatsoever — no placeholders."
)

def load_harness(agent_key):
    """Read the agent's harness file; fall back to the built-in instruction."""
    agent = AGENTS.get(agent_key, AGENTS[DEFAULT_AGENT])
    path = os.path.join(HARNESS_DIR, agent["file"])
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), agent
    except OSError:
        print(f"[WARN] Harness file missing: {path} — using built-in fallback instruction.")
        return FALLBACK_INSTRUCTION, agent

def build_live_config(agent_key, resume_handle=None):
    # Harness goes in system_instruction at connect time. Do NOT inject it via
    # send_client_content — on gemini-3.1 live models that call is restricted to
    # seeding initial history and silently no-ops without history_config.
    instruction, agent = load_harness(agent_key)
    return {
        "response_modalities": ["AUDIO"],
        "input_audio_transcription": {},   # lets us log what was heard
        "output_audio_transcription": {},  # lets us log what was said

        "system_instruction": instruction,

        "speech_config": {
            "voice_config": {
                "prebuilt_voice_config": {
                    "voice_name": agent["voice"]
                }
            }
        },

        # Minimal thinking — optimize for lowest latency
        "thinking_config": {
            "thinking_level": "minimal"
        },

        # NOTE: proactivity/proactive_audio is NOT supported on this model
        # (rejected at setup, tested 2026-07-03) — silence is enforced by the
        # harness instruction instead.
        # Sliding-window compression reduces token growth mid-session, but does
        # NOT lift the hard session-duration cap — the server still sends a
        # GoAway + closes with code 1008 around the ~10min mark regardless.
        # session_resumption + the reconnect loop in main() are what actually
        # carry a hearing across that boundary.
        "context_window_compression": {"sliding_window": {}},
        "session_resumption": {"handle": resume_handle} if resume_handle else {},
    }, agent

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

def header(agent):
    print(f"""
{AQUA}╔══════════════════════════════════════════╗
║          W I N G M A N                  ║
║  Silent Tactical Courtroom Advisor       ║
╚══════════════════════════════════════════╝{RESET}
{DIM}Model : {MODEL_ID}
Agent : {agent["label"]}  |  Voice : {agent["voice"]}  |  In: 16kHz  |  Out: 24kHz{RESET}
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

async def receive_advisory(session, state):
    """Receive audio + transcripts from Gemini, play to earpiece."""
    speaker = open_output()
    log("EARPIECE", "Armed. Listening for advisories...", AQUA)
    try:
        async for response in session.receive():
            if response.go_away:
                log("SYSTEM", f"GoAway — session closing in {response.go_away.time_left}, will reconnect.", RED)

            if response.session_resumption_update and response.session_resumption_update.resumable:
                state["handle"] = response.session_resumption_update.new_handle

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
    agent_key = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_AGENT
    if agent_key not in AGENTS:
        print(f"{RED}[ABORT] Unknown agent '{agent_key}'. Options: {', '.join(AGENTS)}{RESET}")
        sys.exit(1)

    header(AGENTS[agent_key])

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print(f"{RED}[ABORT] GEMINI_API_KEY not set.{RESET}")
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    # Carries the session-resumption handle across reconnects so a hearing
    # that outlives the ~10min Live session cap doesn't kill Wingman outright.
    state = {"handle": None}

    try:
        while True:
            live_config, _ = build_live_config(agent_key, state["handle"])

            log("SYSTEM", "Reconnecting..." if state["handle"] else "Connecting to Gemini Live...", AQUA)
            try:
                async with client.aio.live.connect(model=MODEL_ID, config=live_config) as session:
                    log("SYSTEM", "WebSocket established. Session live.", AQUA)
                    log("SYSTEM", "Speak freely. Wingman will interject only when it matters.", DIM)
                    print(f"{DIM}─────────────────────────────────────────────{RESET}\n")

                    mic_task      = asyncio.create_task(stream_mic(session))
                    earpiece_task = asyncio.create_task(receive_advisory(session, state))

                    await asyncio.gather(mic_task, earpiece_task)

                # Gather returned cleanly (session closed by the server after a
                # GoAway) with a resumption handle in hand — loop and reconnect.
                if state["handle"]:
                    continue
                break

            except genai_errors.APIError as e:
                # 1008 = policy violation close, the expected shape of hitting
                # the session-duration cap. Reconnect if we have a resumption
                # handle to carry the conversation forward; otherwise this is a
                # real error (bad key, quota, etc.) and should surface.
                if e.code == 1008 and state["handle"]:
                    log("SYSTEM", f"Session limit hit — resuming ({e}).", RED)
                    continue
                print(f"{RED}[ERROR] {e}{RESET}")
                raise

    except KeyboardInterrupt:
        pass

    finally:
        p.terminate()
        print(f"\n{DIM}[{ts()}] SYSTEM: Session terminated.{RESET}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{DIM}Wingman offline.{RESET}")
