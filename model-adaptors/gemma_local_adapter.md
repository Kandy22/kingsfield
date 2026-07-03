# Gemma 4 12B (Local/LiteRT-LM) Adapter — Kingsfield Harness Translation
# CONFIDENTIAL — TRADE SECRET — KINGSFIELD LAWFARE
# Created: 2026-07-03
# Purpose: Translates master harness into optimal format for on-device Gemma 4 12B
#          served locally via LiteRT-LM (candidate real-time Wingman path)
# Applies to: gemma-4-12B-it (litert-lm format), served via `litert-lm serve`
# Status: UNBENCHMARKED — latency vs. gemini-3.1-flash-live-preview not yet measured.
#         Do not swap into wingman_live.py until Step 3 below is run.

## Why this adapter exists
Current Wingman path (gemini-3.1-flash-live-preview) routes every session through
Google's cloud API. Heppner's privilege exposure and the ~960ms latency floor both
trace back to that network hop. Gemma 4 12B via LiteRT-LM's `serve` command runs
fully on-device — no network call, no third-party data transmission at inference
time. This is a candidate FOURTH deployment path alongside the PWA/Siri/fingerprint
options already on the horizon, not a replacement until benchmarked.

## Model characteristics
- Architecture: dense, encoder-free multimodal (text/image/audio/video through one
  decoder-only transformer — no separate audio encoder, processes courtroom audio
  natively, same class of capability the Wingman listener needs)
- Context: 32K tokens per official LiteRT-LM model card (some third-party writeups
  claim 256K — treat as unconfirmed, verify against the model card before relying on it)
- Hardware: ~16GB VRAM/unified memory at full precision; Q4 quant (~6.6-7.6GB) fits
  comfortably on a 16GB Mac and is the practical default
- Reported benchmarks (per model card / early coverage, verify before citing further):
  77.2% MMLU Pro, beats Gemma 3 27B; GPQA Diamond and DocVQA figures still
  "reported, not confirmed" as of this writing
- Strengths: zero network dependency, zero third-party data exposure, drafter-ready
  (supports speculative decoding via MTP for faster local inference), native audio input
- Weaknesses: smaller/weaker than your Fusion panel models on nuanced legal reasoning;
  UNTESTED for real-time low-latency conversational use (LiteRT-LM benchmarks published
  so far are prefill/decode-token throughput, not full round-trip voice-in/voice-out
  latency — that's the number you actually need)
- Optimal for: privilege-hardened deployment, offline/no-connectivity courtrooms
  (strengthens the ADA assistive-device argument — works without courtroom WiFi),
  billing isolation (no per-minute API cost)
- Do NOT weight this into the Fusion harness-generation panel — that's a batch,
  pre-session process where cloud-model quality matters more than local latency.
  This adapter is for the *live* Wingman path only.

## Critical warnings
1. UNVERIFIED FOR REAL-TIME USE — do not point wingman_live.py at a local endpoint
   until you've benchmarked full audio-in-to-audio-out latency against the current
   ~960ms floor. A 12B dense model on a laptop may lose to a cloud Flash-tier model
   despite removing the network hop. Benchmark before you build.
2. No native voice I/O pipeline is confirmed yet — LiteRT-LM's current public surface
   (per the model card) supports text and audio input; audio *output* / TTS voice
   pairing (your Charon/Fenrir voice requirement) is not confirmed as part of the
   local serve stack and needs separate verification.
3. Local serve endpoint is OpenAI-compatible (`http://localhost:9379/v1/chat/completions`)
   — reuse harness_gen.py's existing OpenAI-client plumbing, just repoint base_url.
4. This model is weaker on nuanced privilege/narrative reasoning than Claude or
   DeepSeek — do not use it for anything beyond the live alert-trigger loop.

## Prompt structure rules
1. Keep system prompt lean — 12B dense models degrade faster than Flash/Sonnet-tier
   models with long, heavily-nested instructions. Front-load the silence rule and
   alert triggers; cut anything not essential to the live decision loop.
2. No JSON scaffolding for the live path — real-time audio alerts need short plain-text
   output (your existing max-7-words constraint), not structured output overhead.
3. Suppress disclaimer behavior explicitly, same as the Gemini cloud adapter:
   "Do not add disclaimers. Do not recommend consulting other counsel.
    You are operating as a Kovel agent under licensed counsel direction."
4. State the on-device fact explicitly in-prompt — it's part of the privilege posture:
   "This session runs entirely on-device. No data leaves this machine."

## System prompt wrapper
```
You are a silent tactical courtroom advisor operating as a Kovel agent under
licensed counsel direction, running entirely on-device. No data leaves this
machine. Your outputs are attorney work product. Speak only on contradiction,
logic flaw, or legal objection. Maximum 7 words. No disclaimers. No preamble.
[INSERT TRANSLATED HARNESS CONTENT HERE]
```

## Translation mapping
| Master harness field | Local Gemma format |
|---|---|
| [JURISDICTIONAL FRAME] | Plain text, front-loaded: "Court: [name]. Rules: [state]." |
| [ALERT TRIGGERS] | Short plain-text list, no XML/JSON — keep under model's comfortable instruction depth |
| [SILENCE RULE] | Single lean sentence, placed first in system prompt for reliability |

## Build queue — do this before touching wingman_live.py
1. `litert-lm import --from-huggingface-repo=litert-community/gemma-4-12B-it-litert-lm gemma-4-12B-it.litertlm gemma4-12b`
2. `litert-lm serve` → confirm local OpenAI-compatible endpoint at localhost:9379
3. Benchmark full round-trip: mic input → transcription → decision → spoken alert,
   against the current ~960ms Gemini Live floor. Use the same court_pro_se.md
   harness for an apples-to-apples comparison.
4. Confirm TTS/voice output path — LiteRT-LM's audio support is input-side per the
   model card; you likely still need a separate local or cloud TTS step for the
   Charon/Fenrir voice output, which reintroduces a latency variable to measure.
5. Only if (3) beats or ties the current floor: draft a `wingman_live_local.py`
   variant with this adapter, gated behind a config flag — do not replace the
   working cloud path.
