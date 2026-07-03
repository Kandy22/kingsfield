"""
WINGMAN — Real-Time Tactical Earpiece Advisor
Kingsfield Lawfare · CONFIDENTIAL — TRADE SECRET
Built on Gemini 3.1 Flash Live · June 2026

INSTALL:  pip install google-genai pyaudio
RUN:      cd ~/code/kingsfield/wingman
          set -a && source ../.env && set +a
          .venv/bin/python wingman_live.py
"""

import asyncio
import sys
import os
import time
from pathlib import Path
from datetime import datetime

try:
    import pyaudio
except ImportError:
    print("[ABORT] Run: pip install pyaudio && brew install portaudio")
    sys.exit(1)

from google import genai
from google.genai import types

# ── Constants ──────────────────────────────────────────────────────────────────
MODEL_ID    = "gemini-3.1-flash-live-preview"
INPUT_RATE  = 16000
OUTPUT_RATE = 24000
CHUNK       = 800        # 50ms at 16kHz — tighter latency than 1600

SESSIONS_DIR = Path(__file__).parent / "sessions"
HARNESS_DIR  = Path(__file__).parent / "harness"

# ── Terminal colors ────────────────────────────────────────────────────────────
AQUA  = "\033[96m"
DIM   = "\033[2m"
BOLD  = "\033[1m"
RED   = "\033[91m"
GOLD  = "\033[93m"
RESET = "\033[0m"

def ts():
    return datetime.now().strftime("%H:%M:%S")

def log(src, msg, c=DIM):
    print(f"{c}[{ts()}] {src}: {msg}{RESET}", flush=True)

def advisory(msg):
    print(f"\n{AQUA}{BOLD}◈ WINGMAN [{ts()}]: {msg}{RESET}\n", flush=True)

# ── Agent definitions ──────────────────────────────────────────────────────────
AGENTS = {
    "1": {
        "name": "COURT — Pro Se Litigation",
        "description": "Silent tactical advisor for courtroom hearings, motions, depositions.",
        "system_instruction": (
            "You are a silent tactical courtroom advisor operating as a Kovel agent "
            "under licensed counsel direction. Your outputs are attorney work product. "
            "Listen to the live courtroom audio. Say NOTHING unless you hear one of these: "
            "(1) A misquoted or misapplied statute or rule — cite the correct authority in 5 words or fewer. "
            "(2) A direct contradiction of a prior sworn statement — name the contradiction in 5 words. "
            "(3) A textbook-inadmissible question: hearsay, leading on direct, assumes facts not in evidence, "
            "calls for speculation, privilege violation — name the objection type only. "
            "Default: SILENT. One accurate objection beats ten noise objections. "
            "When you fire: 5 words maximum. No filler. No explanation. No summaries. "
            "Do not comment on strategy, narrative, tone, or anything that is not a clear legal error. "
            "If a harness was injected at session start, apply it to every trigger decision."
        ),
        "voice": "Charon",
        "harness_file": "court_pro_se.md",
    },
    "2": {
        "name": "BROADCAST — News / Market Watch",
        "description": "Real-time factual and rhetorical monitor for TV news, interviews, market commentary.",
        "system_instruction": (
            "You are a real-time broadcast intelligence advisor. "
            "Listen to live TV audio — news interviews, market commentary, pundit panels. "
            "Fire only when you hear: "
            "(1) A verifiably false factual claim — state the correct fact in 6 words or fewer. "
            "(2) A logical fallacy being used as a rhetorical device — name the fallacy in 3 words. "
            "(3) A market figure, statistic, or data point stated incorrectly — give the correct figure. "
            "(4) A legal or regulatory claim stated incorrectly — correct it in 5 words. "
            "Default: SILENT. Do not comment on opinion, spin, framing, or political position — "
            "only fire on verifiable factual errors or named logical fallacies. "
            "When you fire: 6 words maximum. Crisp. Flat affect. No editorializing."
        ),
        "voice": "Fenrir",
        "harness_file": "broadcast_market.md",
    },
    "3": {
        "name": "DEPOSITION — Witness Examination",
        "description": "Tracks witness statements for inconsistencies against prior testimony.",
        "system_instruction": (
            "You are a deposition intelligence monitor operating as a Kovel agent "
            "under licensed counsel direction. Your outputs are attorney work product. "
            "Listen to deposition testimony. Fire only when: "
            "(1) Witness contradicts a prior statement from their own deposition or sworn filing — "
            "say: 'Contradicts prior: [topic]' in 5 words. "
            "(2) Witness claims no knowledge of something documented in evidence — "
            "say: 'Document contradicts this.' "
            "(3) Counsel asks a leading question on direct examination of own witness — "
            "say: 'Leading — FRE 611.' "
            "(4) Question calls for speculation, legal conclusion, or assumes a fact not established — "
            "name the defect in 4 words. "
            "Default: SILENT. Track everything. Speak rarely. "
            "When you fire: 5 words maximum."
        ),
        "voice": "Charon",
        "harness_file": "deposition.md",
    },
}

# ── Harness loader ─────────────────────────────────────────────────────────────
def load_harness(harness_file: str) -> str | None:
    """Load agent-specific harness if it exists, fall back to active.md."""
    paths = [
        HARNESS_DIR / harness_file,
        HARNESS_DIR / "active.md",
    ]
    for p in paths:
        if p.exists():
            content = p.read_text().strip()
            if content:
                log("HARNESS", f"Loaded: {p.name} ({len(content)} chars)", GOLD)
                return content
    log("HARNESS", "No harness found — running in generic mode", RED)
    return None

# ── Agent selector ─────────────────────────────────────────────────────────────
def select_agent() -> dict:
    print(f"\n{AQUA}╔══════════════════════════════════════════╗")
    print(f"║           W I N G M A N                 ║")
    print(f"║     Kingsfield Lawfare · Confidential   ║")
    print(f"╚══════════════════════════════════════════╝{RESET}\n")
    print(f"{BOLD}Select agent:{RESET}\n")
    for key, agent in AGENTS.items():
        print(f"  {AQUA}{key}{RESET}  {BOLD}{agent['name']}{RESET}")
        print(f"     {DIM}{agent['description']}{RESET}\n")
    while True:
        choice = input(f"{AQUA}Agent [{'/'.join(AGENTS.keys())}]: {RESET}").strip()
        if choice in AGENTS:
            return AGENTS[choice]
        print(f"{RED}Invalid choice.{RESET}")

# ── Session transcript ─────────────────────────────────────────────────────────
def open_transcript(agent_name: str):
    SESSIONS_DIR.mkdir(exist_ok=True)
    fname = SESSIONS_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{agent_name.split()[0].lower()}.txt"
    f = open(fname, "w")
    f.write(f"WINGMAN SESSION — {agent_name}\n")
    f.write(f"Started: {datetime.now().isoformat()}\n")
    f.write(f"Retention: Destroy after 30 days — CONFIDENTIAL — TRADE SECRET\n")
    f.write("=" * 60 + "\n\n")
    f.flush()
    log("TRANSCRIPT", f"Saving to {fname.name}", DIM)
    return f

# ── Audio ──────────────────────────────────────────────────────────────────────
async def stream_mic(session, transcript):
    p = pyaudio.PyAudio()
    mic = p.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=INPUT_RATE,
        input=True,
        frames_per_buffer=CHUNK,
    )
    log("MIC", f"Open — streaming {INPUT_RATE}Hz PCM to Gemini...", AQUA)
    try:
        while True:
            chunk = mic.read(CHUNK, exception_on_overflow=False)
            await session.send_realtime_input(
                audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000")
            )
            await asyncio.sleep(0)
    except asyncio.CancelledError:
        pass
    finally:
        mic.stop_stream()
        mic.close()
        p.terminate()

async def receive_advisory(session, transcript):
    p = pyaudio.PyAudio()
    speaker = p.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=OUTPUT_RATE,
        output=True,
    )
    log("EARPIECE", "Armed.", AQUA)
    try:
        async for response in session.receive():
            sc = response.server_content
            if not sc:
                continue
            if sc.model_turn:
                for part in sc.model_turn.parts:
                    if hasattr(part, "inline_data") and part.inline_data:
                        speaker.write(part.inline_data.data)
            if sc.output_transcription:
                text = sc.output_transcription.text.strip()
                if text:
                    advisory(text)
                    transcript.write(f"[{ts()}] WINGMAN: {text}\n")
                    transcript.flush()
    except asyncio.CancelledError:
        pass
    finally:
        speaker.stop_stream()
        speaker.close()
        p.terminate()

# ── Main ───────────────────────────────────────────────────────────────────────
async def main():
    agent = select_agent()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print(f"{RED}[ABORT] GEMINI_API_KEY not set. Run: set -a && source ../.env && set +a{RESET}")
        sys.exit(1)

    harness = load_harness(agent["harness_file"])

    live_config = {
        "response_modalities": ["AUDIO"],
        "output_audio_transcription": {},
        "system_instruction": agent["system_instruction"],
        "speech_config": {
            "voice_config": {
                "prebuilt_voice_config": {"voice_name": agent["voice"]}
            }
        },
        "thinking_config": {"thinking_level": "minimal"},
        "realtime_input_config": {
            "automatic_activity_detection": {
                "disabled": False,
                "start_of_speech_sensitivity": "START_SENSITIVITY_HIGH",
                "end_of_speech_sensitivity": "END_SENSITIVITY_HIGH",
            }
        },
    }

    print(f"\n{AQUA}{BOLD}▶ {agent['name']}{RESET}")
    log("SYSTEM", "Connecting to Gemini Live...", AQUA)

    client = genai.Client(api_key=api_key)
    transcript = open_transcript(agent["name"])

    try:
        async with client.aio.live.connect(model=MODEL_ID, config=live_config) as session:
            # Inject harness as first message if available
            if harness:
                await session.send_client_content(
                    turns=[{"role": "user", "parts": [{"text": harness}]}],
                    turn_complete=True,
                )
                log("HARNESS", "Injected into session context.", GOLD)

            log("SYSTEM", f"LIVE. Listening as: {agent['name']}", AQUA)
            print(f"{DIM}(Ctrl+C to stop){RESET}\n")

            async with asyncio.TaskGroup() as tg:
                tg.create_task(stream_mic(session, transcript))
                tg.create_task(receive_advisory(session, transcript))

    except* KeyboardInterrupt:
        pass
    finally:
        transcript.write(f"\n[{ts()}] SESSION ENDED\n")
        transcript.close()
        print(f"\n{DIM}Wingman offline. Transcript saved.{RESET}\n")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{DIM}Wingman offline.{RESET}")
