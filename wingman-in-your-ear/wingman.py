import asyncio
import os
from google import genai
from google.genai import types

# 1. Initialize Client (Picks up GEMINI_API_KEY from environment)
client = genai.Client()

# 2. Configure the Live Engine
# We target the 3.1 Flash Live model to keep latency and token burn minimal
MODEL_ID = "gemini-3.1-flash-live-preview"

LIVE_CONFIG = {
    # Force the engine to output audio directly rather than basic text
    "response_modalities": ["AUDIO"], 
    
    # Inject your proprietary tactical legal rules/persona directly here
    "system_instruction": (
        "You are a silent tactical courtroom and litigation advisor. "
        "Listen to the live dialogue stream. Do not transcribe or repeat what you hear. "
        "Cross-reference the statements against the rules of evidence and logic. "
        "Only speak when you catch a blatant contradiction, a logic flaw, or a valid legal objection. "
        "Keep your spoken notes under 7 words total. Be crisp, brutal, and fast."
    ),
    
    # Set the target voice style
    "speech_config": {
        "voice_config": {
            "prebuilt_voice_config": {
                "voice_name": "Kore" # High-clarity, conversational profile
            }
        }
    }
}

async def audio_input_stream(session):
    """
    Simulates streaming raw audio up from the client device (e.g., iPhone).
    In a real iOS client app, you would continuously pipe chunks from the
    native AVCaptureAudioDataOutput hardware buffer.
    """
    print("[Pipeline] Hardware mic stream connected. Streaming 16kHz PCM...")
    try:
        while True:
            # Fake payload chunk simulating 100ms of raw little-endian 16-bit PCM audio
            # In production, replace this with your actual recorded byte array chunk
            mock_pcm_chunk = b'\x00\x00' * 1600 
            
            await session.send_realtime_input(
                audio=types.Blob(
                    data=mock_pcm_chunk,
                    mime_type="audio/pcm;rate=16000"
                )
            )
            # Sleep 100ms to maintain real-time cadence matching the audio chunk size
            await asyncio.sleep(0.1)
    except asyncio.CancelledError:
        pass

async def audio_output_listener(session):
    """
    Asynchronously listens to the returning analytical stream from Gemini
    and intercepts raw voice chunks for your earpiece.
    """
    print("[Pipeline] Listening for tactical audio advice...")
    try:
        async for response in session.receive():
            server_content = response.server_content
            if server_content and server_content.model_turn:
                for part in server_content.model_turn.parts:
                    if part.inline_data:
                        raw_audio_received = part.inline_data.data
                        # Handle the incoming chunk (base64 encoded string)
                        # Pipe this directly into your client speaker/earpiece core
                        print(f"[Earpiece Advisory Received] Captured {len(raw_audio_received)} bytes of voice instruction.")
    except asyncio.CancelledError:
        pass

async def main():
    # Establish the stateful real-time session
    async with client.aio.live.connect(model=MODEL_ID, config=LIVE_CONFIG) as session:
        print("[Pipeline] Stateful Live WebSocket Connection Established.")
        
        # Run input and output pipelines concurrently
        input_task = asyncio.create_task(audio_input_stream(session))
        output_task = asyncio.create_task(audio_output_listener(session))
        
        await asyncio.gather(input_task, output_task)

if __name__ == "__main__":
    # Run the application loop
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[Pipeline] Voice session terminated by user.")