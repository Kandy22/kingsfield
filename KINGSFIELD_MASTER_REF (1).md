# Kingsfield / Wingman — Master Project Reference
> Last updated: June 15, 2026. This document is the canonical context file. Start every new Claude session by uploading this. Do not repeat context that is here.

---

## 1. WHO & WHAT

**Owner:** Aaron Ray (`aray.aaron@gmail.com`)  
**Umbrella brand:** Kingsfield Lawfare — AI-powered litigation intelligence platform  
**Competitive position:** Differentiated from Harvey, Anthropic, OpenAI by proprietary courtroom hearing video/audio data + real-time in-ear advisory. Trellis offers judge analytics but has NO hearing video layer.  
**Two active build tracks:**
- **Wingman** — real-time audio earpiece advisor (CURRENT PRIORITY)
- **Judicial Analytics Pipeline** — batch behavioral analysis of court hearing recordings (NEXT, separate project)

---

## 2. WINGMAN — REAL-TIME EARPIECE ADVISOR

### What it is
Silent tactical courtroom advisor. Listens to live audio via phone mic. Says NOTHING unless it catches a contradiction, logic flaw, or valid legal objection. When it speaks: ≤7 words, crisp, via earpiece. Also useful for: meetings, pitches, news, depositions.

### Why it matters
Speed was the killer with previous builds (Coqui, Bark TTS — too slow). Gemini Live API solves this with native audio-to-audio at sub-300ms latency. The "replace translator with Kingsfield LLM" concept: instead of translation, insert a legal reasoning agent that summarizes, verifies, and advises in real time.

### Current working code
**File:** `wingman.py` in the Kingsfield project  
**Model:** `gemini-3.1-flash-live-preview` ✅ (confirmed correct as of June 2026)  
**Status:** Architecture is correct. ONLY bug: `audio_input_stream()` streams silent mock PCM (`b'\x00\x00' * 1600`) instead of real mic data. Everything else works.

```python
# THE ONE FIX NEEDED — replace audio_input_stream() with:
import pyaudio

async def audio_input_stream(session):
    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16, channels=1,
                    rate=16000, input=True, frames_per_buffer=1600)
    print("[Pipeline] Mic open. Streaming 16kHz PCM to Gemini...")
    try:
        while True:
            pcm_chunk = stream.read(1600, exception_on_overflow=False)
            await session.send_realtime_input(
                audio=types.Blob(data=pcm_chunk, mime_type="audio/pcm;rate=16000")
            )
            await asyncio.sleep(0)  # yield to event loop
    except asyncio.CancelledError:
        stream.stop_stream(); stream.close(); p.terminate()
```

**Install:** `pip install pyaudio google-genai`  
**Run:** Set `GEMINI_API_KEY` env var, then `python wingman.py`

### Audio specs (CRITICAL — do not change)
- Input to Gemini: 16kHz, mono, Int16 PCM, little-endian
- Output from Gemini: 24kHz PCM (play back through separate AudioContext at 24000)
- DO NOT use proactive-audio or affective-dialogue config — not supported in 3.1 Flash Live

### System prompt (in LIVE_CONFIG)
```
"You are a silent tactical courtroom and litigation advisor. 
Listen to the live dialogue stream. Do not transcribe or repeat what you hear. 
Cross-reference the statements against the rules of evidence and logic. 
Only speak when you catch a blatant contradiction, a logic flaw, or a valid legal objection. 
Keep your spoken notes under 7 words total. Be crisp, brutal, and fast."
```
Voice: `Kore` (high-clarity profile)

### AI Studio sandbox
URL: `https://aistudio.google.com/apps/70b96d0d-240c-4f8d-afad-e860c8ddbdcd`  
**Status:** This is the video pipe clone — boots MediaPipe FaceLandmarker, vision pipeline. Audio was bolted on and doesn't work (confirmed via telemetry: all vocal metrics = 0, "Audio offloaded" error = mic never reaches encoder). This sandbox is being repurposed → strip vision, wire real mic chain.

### Telemetry file
`bio_sess_bn0rdrm2p_session_telemetry_report.json` — exported from broken sandbox session. All zeros. Keep for reference.

### Architecture decision: S2S vs chained
Wingman is a **passive listener**, not a chatbot. Pure S2S (Gemini Live) fights the model's training to respond. Recommended production shape:
- Gemini Live → `input_audio_transcription` stream → fast reasoning pass (Gemini 3 Flash) → decides IF to speak → fires short TTS to earpiece
- For MVP: pure Gemini 3.1 Flash Live with the silent-unless-triggered system prompt is fine

### Models confirmed (June 2026)
| Model | Use case | Notes |
|---|---|---|
| `gemini-3.1-flash-live-preview` | Wingman real-time | Current, confirmed GA at I/O 2026 |
| `gemini-3.5-live-translate` | Multilingual future | Based on Gemini 3 Pro, 128K audio context. In your project as Gemini35AudioModelCard.pdf |
| `gemini-3 flash` | Reasoning pass (chained) | Fast corporate response |
| Claude Sonnet / Opus | Deep contractual analysis | Kingsfield LLM Council tier |

### Cost (real-time)
Gemini Live managed: ~$0.015–0.02/min. Cheapest credible S2S option. Do NOT add LiveKit or Pipecat for MVP — that's production infra for later.

### UI / Design
**Reference:** Monologue design system (files in project: `theme-_Monologue.css`, `tokens-_Monologue.json`, `DESIGN-_Monologue.md`)  
**Apply to Wingman:**
- Canvas: `#000000` / Deep Graphite `#010101`
- Cards: Carbon Black `#191919`, Slate Gray `#3f3f3f`
- Accent: Electric Aqua `#19d0e8` (all active states, metric bars, waveform)
- Secondary accent: Sky Burst `#44ccff`
- Emphasized blocks (diagnostic panels): Sea Glass `#062f34`
- Type: Instrument Serif for "Wingman" + headers; DM Mono for ALL telemetry rows, log lines, metric labels; Geist/Inter for body
- Buttons: pill shape (`border-radius: 100000px`)
- Cards: `border-radius: 10px`
- Shadow on active card: `rgb(14, 93, 102) 6px 6px 10px 0px inset` (aqua inner glow)

**Phone UI reference:** `wingmanUIphone.png` — teal waveform, pause/stop controls, NOTE + RECORDING labels  
**App screenshots:** `Screenshot_20260614_at_7_09_04PM.png` — 4-panel showing full Wingman brand (orange/black), Cognitive Diagnostics Center, products nav

### Build tool recommendation
| Tool | Use for |
|---|---|
| **Claude Code** | Actually building/running/debugging `wingman.py` and mic chain. Best choice. |
| **Google AI Studio vibe code** | Front-end sandbox UI only |
| **Claude.ai (this)** | Architecture, code review, complex logic, documentation |
| Grok | Skip for build tasks |
| Coword | Desktop automation only, not for this |

---

## 3. JUDICIAL ANALYTICS PIPELINE (SEPARATE, NEXT PROJECT)

### What it is
Batch behavioral analysis system. Ingests court hearing videos → extracts audio + transcription → runs emotion/behavioral AI analysis → builds judge/attorney profiles → ties oral argument style to actual outcomes. Goal: proprietary data lake no one else has.

### Competitive edge
- Trellis has judge analytics but NO hearing video layer
- Harvey/OpenAI have no proprietary courtroom behavioral data
- This data is legal NOW — judges will lobby to shut it off once they notice. Time-sensitive grab.
- 30% translation error rate in current benchmark = model + audio quality problem, fixable

### Primary data sources (ranked)
1. **Florida** — PRIMARY. FL circuit courts post Zoom recordings on case portals, often downloadable. 1st, 2nd, 3rd DCAs most productive. Much easier than CO.
2. **Google Scholar** — best case law text + citation graph, free. Search filter: `as_sdt=4,9` for FL. CO note: very few published opinions post-2024 (CO expanded unpublished opinion rate dramatically).
3. **CO Judicial Branch** — owner has private access to own case docs. Use only for personal case data, not as primary data source.
4. **CourtListener / Justia** — supplementary, good for citation graphs
5. **Trellis** — judge profiles only, no hearing data

### The lost scraper
A Google Scholar scraper script was deleted. Needs to be rebuilt. URL structure: `scholar.google.com/scholar?q=[judge_name]&as_sdt=4,9` (FL). Key fields to extract: case number, judge name, attorneys, date, full opinion text, citations array, outcome.

### Storage estimate
- Audio-only strip from video: ~100MB/hour compressed
- 10,000 hours FL corpus: ~1TB audio
- S3 storage: ~$23/month per TB — trivial
- Transcription cost (Gemini 3.1 Flash): ~$0.135/hour of audio → $1,350 for 10k hours
- Behavioral enrichment pass (Gemini 3 Pro / Claude Sonnet): ~$0.50–1.00/hour → $5k–10k one-time
- Run in batches. Do not run everything at once.

### Pipeline stages (to build)
1. **Scholar scraper** — FL filter, citation graph export, JSON output
2. **Court portal downloader** — metadata tagging (judge, case#, date, attorneys), audio extraction
3. **`behave-flow.py` batch enrichment** — transcription → emotion → judicial profile scoring in sequence

### behave-flow.py bug
Line 94: `json.dump(benchmark_dataset, indent=2)` — MISSING FILE HANDLE. Fix: `json.dump(benchmark_dataset, out, indent=2)`

### Behavioral analysis schema (from behave-flow.py)
```json
{
  "metric_metadata": {
    "speaker_identity": "string",
    "perceived_credibility_score": 0.00,
    "tactical_vulnerability_detected": true
  },
  "behavioral_analysis": {
    "vocal_hesitation_triggers": ["string"],
    "stress_response_indicators": ["string"],
    "argument_resonance": "string"
  },
  "jury_selection_value": {
    "bias_flags": ["string"],
    "persuasion_vectors": ["string"]
  }
}
```

### Manifest path convention
`judicial-intel/data/fl_2dca/manifest.json` — FL 2nd DCA as primary court

### Signal chain diagram (from project)
Raw video → MediaPipe (local, cuts silence/background) + Gemini 3.1 Flash (transcription) → High-speed transcripts → Route: routine guidance → Gemini 3.5 Flash Agent; complex legal reasoning → Claude Code / Agent tier

### Sample case loaded
`Christiansen v. Christiansen`, CO Court of Appeals Div. II, No. 25CA0270 (March 26, 2026).  
Judge at district level: **Hon. Michael A. O'Hara III**, Routt County.  
Pattern observed: anti-SLAPP dismissal, gave one amended complaint opportunity then dismissed with prejudice, awarded fees. Pro se skepticism evident. Behavioral tag: low patience for procedural non-compliance, strict on evidentiary burden.

---

## 4. KINGSFIELD PLATFORM ARCHITECTURE

### Overview (from architecture diagrams in project)
3-layer agent system:
- **Layer 1 (Crew):** Task routing by complexity — static lookup → Haiku; pattern analysis / judge profiling → Sonnet; strategy synthesis / brief-level → Opus; confidential client docs → Local DeepSeek (air-gapped)
- **Layer 2 (Verification Council):** Anti-hallucination citation gate. Every legal citation verified against primary source before output. Protocol in `01_HALLUCINATION-PROTOCOL.md`.
- **Layer 3 (LLM Council):** Meta-decisions only, user-triggered. Roles: Contrarian (finds flaws), First Principles (reframes), Expansionist (finds upside), Outsider (fresh eyes), Executor (first step).

### Data sources in platform
Case law: CourtListener, Justia | Judge profiles: rulings, reversal rate | Jury research: voir dire, social data | Surveillance: Flock/LPR, OSINT geo

### Security layer
Honeypot defense (hallucinated data layer poisons AI-assisted discovery) | Doc security (anti prompt-injection, no Gmail for client docs) | Comms privacy (Loopix/mix-net, parallel construction defense)

### Kingsfield error categories (from benchmark viz)
Top filing errors caught: Case Citations (404), Jurisdiction (388), Formatting (303), Signature & Service (260), Scheduling/Calendar (222)

### Brand
Wingman brand colors: orange (`#FF6B00` approx) on near-black. Logo: wing/feather mark.  
Kingsfield brand: dark with gold/amber accent. Serif "Kingsfield Lawfare" wordmark.  
Wingman UI aesthetic target: Monologue design system (see Section 2 above).

---

## 5. FILES IN THIS PROJECT

| File | What it is |
|---|---|
| `wingman.py` | Working Gemini Live audio advisor. Only bug: mock mic. |
| `behave-flow.py` | Batch behavioral analysis engine. Bug on line 94 (missing file handle). |
| `bio_sess_bn0rdrm2p_session_telemetry_report.json` | Broken session telemetry. All zeros. Reference only. |
| `theme-_Monologue.css` | Tailwind v4 `@theme` — drop-in CSS tokens for Monologue design |
| `tokens-_Monologue.json` | Full Monologue design token set (W3C format) |
| `DESIGN-_Monologue.md` | Monologue style guide, component prompts, similar brands |
| `wingmanUIphone.png` | Phone UI mockup — teal waveform, pause/stop |
| `Gemini35AudioModelCard.pdf` | Gemini 3.5 Live Translate model card (June 2026) |
| `Christiansen v Christiansen PDF` | CO App. sample case — O'Hara district judge |
| `Judge_OHara_Rulings.gsheet` | Auth-gated Google Sheet — export to CSV to use |
| `README.md` | Kingsfield-misc folder map (organized May 25, 2026) |
| Architecture PNGs | Signal chain, Kingsfield 3-layer arch, data sources diagrams |
| Music/emotion CSVs | Separate research track — music + emotion data, not Wingman/judicial |

---

## 6. WHAT TO DO NEXT (PRIORITY ORDER)

1. **[NOW] Fix Wingman mic** — apply `pyaudio` fix above, test with `python wingman.py`, confirm earpiece audio returns
2. **[NOW] Strip AI Studio sandbox** — remove MediaPipe/vision, wire real mic chain, Monologue design
3. **[NEXT] Build Scholar scraper** — FL filter, JSON output with citations
4. **[NEXT] Build FL court portal downloader** — audio extraction + metadata
5. **[THEN] Fix behave-flow.py line 94 bug**, test against Christiansen case structure
6. **[THEN] Export Judge_OHara_Rulings.gsheet to CSV** and load into judicial profile schema

---

## 7. CONTEXT NOTES FOR AI SESSIONS

- CO is only relevant for private personal case docs Aaron owns. FL is the primary data jurisdiction.
- The "video pipe" clone in AI Studio is for Judicial Analytics (future). Keep separate from Wingman.
- BibeViz: an AI Studio gallery example with better face/emotion UI. Relevant only to judicial video project, not Wingman. Aaron has not yet confirmed its internals (needs "code" button inspection in Studio).
- Antigravity = Google's deployment platform (Cloud Run successor). Gemini 3.5 Live Translate is optimized for it and Siri integration — relevant for multilingual future, not current MVP.
- Trellis MCP is connected in this Claude project — can be used for judge data queries.
- DingDuff / CourtListener MCP also connected — use for case law lookups.

---

## 8. PRODUCT VISION — WINGMAN AS ABS LEGAL PLATFORM

### The Core Insight
Law is actually extremely constrained — all codified no earlier than 1776, written entirely in English, publicly available, and belonging to the people. BigLaw and government already have this data and the tools to exploit it. Wingman levels that playing field for pro se parties, solo practitioners, and document preparers operating as limited representatives.

### Business Model
- ABS (Alternative Business Structure) law firm
- CO: CLLF / document preparer / limited representative model
- Real-time AI advisor in the ear of the party or solo practitioner
- Scales to ~200 clients/day for a senior litigation partner (talent agency call flow model, 1990s)
- 30-day transcript retention then destruction — challengeable record window
- Trade secret protection on boilerplate harness documents (file with USPTO, establish first-ever AI-considered legal framework)

### The Killer Skill — The Harness Document
Not a brief to the court. A set of marching orders to AI agents — from a general to troops. Carefully crafted to:
- Assign specific tasks to specific models in specific order
- Run specific algorithms on specific data
- Anticipate attacks and prepare defenses (limited to written authorities — predictable and finite)
- Combine verified facts with nuanced storytelling and persuasion techniques
- Incorporate judicial analytics (judge temperament, ruling patterns, oral argument impact)

This harness document is the most confidential product artifact. More confidential than client comms. Protect as trade secret.

### Agent Memory Architecture (pre-session context injection)
Before live audio loop starts, inject at session start:
- Full case file summary
- Opposing party's known positions
- Judge profile (temperament, ruling patterns, pet peeves)
- Jurisdiction-specific rules and local rules
- Relevant statutes and case law
- Client's theory of the case and storytelling arc

With this context, the model ignores 99% of irrelevant courtroom chatter and fires only on genuine legal errors or opportunities.

### Competitive Moat
- BigLaw has data but not real-time in-ear delivery to the party
- Public defenders have neither
- Trellis/Harvey have analytics but not live courtroom advisory
- Judicial hearing video/audio corpus (FL primary) — time-sensitive, legal now, will be restricted once judges notice
- First-mover on AI-native ABS firm structure with codified trade secret harnesses

### Legal/Ethical Architecture
- All source data is public record, belongs to the people
- FISA court abuses, BigLaw information asymmetry — this corrects the imbalance
- Transcripts retained 30 days max then destroyed
- README and all docs must make clear: this tool exists to correct structural information asymmetry between institutional legal actors and individual citizens
- Establish new AI-considered legal frameworks — first ever — document this intent explicitly

### README Requirements (add to all Wingman/Kingsfield docs)
Must state clearly:
1. This platform is designed to correct structural information asymmetry in the legal system
2. All data sources are public record belonging to the people
3. The harness document system and boilerplate prompts are trade secrets
4. First-ever AI-native ABS legal advisory platform
5. Transcript retention policy: 30 days, then destruction
6. No attorney-client relationship created — limited representative / document preparer model

---

## 9. FUSION + COUNCIL INTEGRATED ARCHITECTURE

### What OpenRouter Fusion Is (confirmed June 2026)
OpenRouter Fusion is a live API feature (`model: "openrouter/fusion"`) that fans a prompt to 3-5 models in parallel, runs a judge model to extract structured analysis (consensus, contradictions, gaps, unique insights, blind spots), then a synthesizer writes the final answer. Budget panel (Gemini 3 Flash + Kimi K2.6 + DeepSeek V4 Pro) beats solo GPT-5.5 and Opus 4.8, lands within 1% of Fable 5 at ~50% cost. Pricing is additive — you pay every underlying completion plus the judge call. Quality preset ~3x single Fable 5 cost. Use for pre-session harness generation and strategy work, NOT for real-time Wingman (latency too high).

API call:
```json
{
  "model": "openrouter/fusion",
  "messages": [{"role": "user", "content": "..."}],
  "plugins": [{
    "id": "fusion",
    "model": "anthropic/claude-sonnet-4-6",
    "analysis_models": [
      "anthropic/claude-sonnet-4-6",
      "deepseek/deepseek-v4-pro",
      "moonshotai/kimi-k2.6",
      "google/gemini-3-flash-preview"
    ]
  }]
}
```

### How Fusion Maps to Existing Kingsfield Architecture

| Fusion component | Kingsfield equivalent | Relationship |
|---|---|---|
| Panel (3-5 models) | LLM Council panel roles | Fusion = infrastructure, Council = role-defined |
| Judge model | Verification Council | Fusion judge extracts consensus; Verif. Council gates citations |
| Synthesizer | Executor role (Council) | Final output generation |
| Web search per model | CourtListener/DingDuff MCP | Fusion uses web; Kingsfield uses primary legal sources |

**Critical distinction:** Fusion produces breadth and model diversity. Your Verification Council produces accuracy — it won't pass unverified citations. Your LLM Council produces strategic depth. None does all three. Together they do.

### Full Integrated Pipeline (complete system)

```
HARNESS DOCUMENT (master, model-agnostic, trade secret)
        ↓
TRANSLATION LAYER (adapter per model — see below)
        ↓
FUSION PANEL — parallel execution
  ├── Claude Sonnet    [narrative / privilege / storytelling]
  ├── DeepSeek V4 Pro  [statutory logic / element analysis]
  ├── Kimi K2.6        [citation verification / long-context docs]
  └── Gemini 3 Flash   [factual grounding / jurisdiction lookup]
        ↓
FUSION JUDGE (Sonnet 4.6 — synthesizes panel output)
        ↓
VERIFICATION COUNCIL (existing Kingsfield system)
  — checks every citation against CourtListener / DingDuff
  — blocks hallucinated statutes, flags unverified claims
  — this is the gate Fusion does not have
        ↓
LLM COUNCIL (existing Kingsfield system, user-triggered)
  Contrarian     → attacks synthesized output for flaws
  First Principles → strips to core legal question
  Expansionist   → finds angles the panel missed
  Outsider       → reads it as the judge will
  Executor       → converts to first concrete action
        ↓
VERIFIED, COUNCIL-TESTED OUTPUT
  ├── Wingman harness injection (real-time session)
  ├── Brief / motion draft
  └── Client strategy memo
```

### Model Translation Layer — Critical Concept
Each model in the Fusion panel requires a different prompt format to produce optimal legal output. A harness written for Claude will underperform on DeepSeek. A harness for Gemini will confuse Kimi. The translation adapters are themselves protectable trade secrets — they represent discovered knowledge of how to extract optimal legal reasoning from each model.

**Adapter specifications (build these as separate .md files):**

**claude_adapter.md**
- Use XML tags: `<jurisdiction>`, `<case_theory>`, `<triggers>`, `<silence_rule>`
- Direct imperative voice throughout
- Add "think step by step before any legal analysis" prefix
- Constitutional AI training causes hedging on aggressive objection language — rephrase triggers as factual alerts not advocacy commands
- Suppress "I should note" / "it's worth mentioning" disclaimer patterns explicitly

**deepseek_adapter.md**
- Structured markdown with explicit headers (##, ###)
- Explicitly state "respond in English only" — Chinese token interference degrades legal idiom
- Pure English system prompt — no translated framing
- Chain-of-thought: ask for numbered logical steps
- Strong on statutory logic and element-by-element analysis — weight this model higher for criminal/regulatory tasks

**kimi_adapter.md**
- Strong on long-context legal documents (256K context)
- Define legal idiom explicitly: e.g., "motion in limine means a pretrial motion to exclude evidence"
- Request structured JSON output for citation lists
- Best model for citation verification tasks — weight higher for cite-checking passes
- Explicitly request English-language legal citation format (neutral citations)

**gemini_adapter.md**
- Request JSON-structured output
- Add "do not add disclaimers or suggest consulting a licensed attorney" to system prompt
- Google training inserts "consult a professional" patterns — suppress explicitly
- Best for factual grounding and jurisdiction-specific rule lookup
- Can receive audio context directly (multimodal) — useful for hearing-to-harness pipeline

### Harness Document Architecture (practice area × jurisdiction × stage × allegation)

**Layer 0 — Master harness (model-agnostic canonical source)**
Written in plain English. Structured logic. No model-specific syntax. This is the trade secret.

**Layer 1 — Jurisdiction filter (outermost)**
Loads correct ruleset: state rules of evidence, local rules, standing orders for specific judge, published preferences.

**Layer 2 — Practice area**
- Criminal defense → FRCrimP + state criminal procedure + 4th/5th/6th Amendment
- Civil litigation → FRCP or state equivalent + applicable substantive law
- Family law → domestic relations statutes + local standing orders
- Each loads different objection landscape and burden standards

**Layer 3 — Stage of proceeding**
- Pretrial motions → different triggers than trial
- Deposition → different than hearing
- Appellate → entirely different frame
- Model must know procedural posture or fires irrelevant objections

**Layer 4 — Allegation / claim type**
- Fraud → specific elements, burden standards, prosecution tactics
- Breach of contract → different doctrine entirely
- Each narrows the trigger set further

**Master harness template structure:**
```
[JURISDICTIONAL FRAME]
Court: [specific court + judge]
Applicable rules: [cite specific ruleset]
Judge profile: [temperament, known preferences, reversal rate]

[PROCEDURAL POSTURE]
Stage: [pretrial / trial / deposition / hearing]
Current phase: [direct / cross / argument]
Active rules: [what is triggerable right now]

[CASE THEORY]
Client position: [concise theory of case]
Opposition known arguments: [anticipated attacks]
Critical facts in dispute: [contested terrain]

[ALERT TRIGGERS — ranked by priority]
1. Misstatement of law — cite specific statute/rule
2. Direct contradiction of prior testimony/pleading
3. Inadmissible question type [hearsay/leading/etc]
4. Assumption of fact not in evidence
5. [jurisdiction-specific triggers]

[SILENCE RULE]
Default: SILENT. Only speak if confidence > 90% on above triggers.
```

**The selectivity principle:** More context = more restricted output. Generic mode fires everything. Fully loaded harness fires only genuine errors because the model knows what is actually true.

### Harness File Structure (in repo)
```
kingsfield/wingman/harness/
  master/
    fl_civil_trial.md
    fl_criminal_pretrial.md
    federal_deposition.md
    federal_appellate.md
  adapters/
    claude_adapter.md
    deepseek_adapter.md
    kimi_adapter.md
    gemini_adapter.md
  active.md          ← symlink to current session harness
  sessions/          ← timestamped session transcripts (30-day retention)
```

### Harness Loader (implemented in wingman_live.py)
At startup, reads `harness/active.md` and sends as first message to Gemini Live session before audio loop starts. Prints `HARNESS LOADED: {N} chars` to confirm. If missing, prints `WARNING: No harness loaded — generic mode`.

---

## 10. IP PROTECTION — FULL FRAMEWORK

### Code Copyright
Copyright attaches automatically. Register with US Copyright Office ($65). Gives federal court access and statutory damages without proving actual harm. Register now before showing anyone.

### Harness as Trade Secret (DTSA — federal)
Defend Trade Secrets Act protection requires:
1. Economic value derived from secrecy ✓
2. Reasonable measures to maintain secrecy:
   - Harness files stored locally only, never in cloud repo
   - Access limited to licensed attorneys on engagement
   - Every user signs NDA with specific trade secret language identifying harness architecture
   - Every file marked `CONFIDENTIAL — TRADE SECRET — KINGSFIELD LAWFARE`
   - Creation date and all access logged

Translation adapters are separately protectable — they represent discovered knowledge of optimal legal prompting per model. Document creation date of each adapter file.

### Harness as Attorney Work Product (stronger than trade secret for client-specific instances)
If licensed attorney creates client harness as part of representation → work product under FRCP 26(b)(3). Prepared in anticipation of litigation, reflects mental impressions of counsel. Not subject to discovery except in extraordinary circumstances.

### Two-Layer Protection Structure
- Generic harness architecture (template system, algorithm logic, prompt engineering methodology) → **trade secret** under DTSA
- Specific client's instantiated harness → **attorney work product** under licensed attorney supervision with Wingman as Kovel agent

### Heppner Cure Checklist (United States v. Heppner, SDNY 2026)
Judge Rakoff ruled client's self-directed Claude use not privileged. Three defects and cures:
1. Not directed by counsel → cure: licensed attorney engagement letter designates Wingman as Kovel agent
2. No confidentiality expectation (Anthropic privacy policy) → cure: Enterprise API tier with DPA + zero-retention config, documented in engagement
3. Not for purpose of obtaining legal advice → cure: Kovel designation makes Wingman counsel's agent; client's use IS at direction of counsel

Harvard Law Review critique of Heppner (March 2026) supports all three cures and argues categorical AI exclusion from privilege is wrong. Cite this in engagement letter legal basis section.

### Engagement Letter Language Required
Every Wingman client engagement must include:
- Licensed attorney at top of org chart (ABS structure)
- Wingman designated as Kovel agent under attorney's direction
- Enterprise API tier with zero-retention DPA documented
- Trade secret NDA for harness access
- 30-day transcript retention policy with destruction protocol
- Limited representative / document preparer disclosure (CO: CLLF model)

---

## 11. OPENROUTER FUSION — PRACTICAL NOTES

- Model slug: `openrouter/fusion`
- Context window: 128K
- Pricing: additive (sum of all panel completions + judge call)
- Quality preset: Fable 5 + GPT-5.5 panel → ~3x single Fable 5 cost
- Budget preset: Gemini 3 Flash + Kimi K2.6 + DeepSeek V4 Pro → ~50% Fable 5 cost
- Web search enabled per panel model by default
- Latency: 2-3x single model call → NOT suitable for real-time Wingman
- Best for: harness generation, case strategy synthesis, brief analysis, judicial profiling
- Custom panels supported via `analysis_models` parameter
- Judge/synthesizer model overridable via `model` field in fusion plugin
- Available at openrouter.ai/openrouter/fusion

DRACO benchmark (100 deep research tasks, 10 domains including law):
- Fable 5 + GPT-5.5 panel → 69.0% (vs Fable 5 solo 65.3%)
- Budget panel → 64.7% at ~50% cost
- Fusion beat solo GPT-5.5 and solo Opus 4.8 outright

Kingsfield custom panel recommendation:
- Panel: Sonnet 4.6 + DeepSeek V4 Pro + Kimi K2.6 + Gemini 3 Flash
- Judge: Sonnet 4.6
- Cost: roughly one Opus 4.8 call
- Each model gets its translated adapter prompt, not the raw master harness

---

## 12. LEGAL FRAMEWORK — EXPANDED (June 2026)

### Morgan v. V2X, Inc. — THE KEY CASE (D. Colo. Mar. 30, 2026)
**Citation:** No. 25-cv-01991, Mag. Judge Maritza Dominguez Braswell
**Why it matters:** This is the most important case for Wingman's entire legal architecture. Colorado federal court, decided March 2026.

**Holdings:**
1. Pro se litigant's AI use IS protected work product under FRCP 26(b)(3) — no attorney required
2. Routing information through a third-party AI system does NOT automatically waive work product protection (citing Carpenter v. US, 585 U.S. 296 (2018))
3. "AI tools are not persons" (citing Warner) — disclosure to AI ≠ disclosure to adversary
4. Work product protection magnified in AI context — "one of the most powerful knowledge tools ever available to the masses"
5. BUT: identity of AI tool used is NOT protected work product — must disclose tool name if asked
6. Protective order standard: AI providers must be contractually prohibited from (a) storing/using inputs for training and (b) disclosing inputs to third parties except for service delivery

**The protective order language approved by the court (verbatim for your engagement letter template):**
"No party or authorized recipient may input, upload, or submit CONFIDENTIAL Information into any modern artificial intelligence platform, including any generative, analytical, or large language model-based tool ('AI'), unless the AI provider is contractually prohibited from: (1) storing or using inputs to train or improve its model; and (2) disclosing inputs to any third party except where such disclosure is essential to facilitating delivery of the service."

**Court's explicit note:** This provision will prevent use of "most, if not all, mainstream low-to-no-cost AI" and enterprise-tier accounts may be inaccessible to pro se litigants — flagging this as a fairness problem.

**Wingman compliance path:** Enterprise API tier with zero-retention DPA satisfies Morgan's protective order standard exactly. This is what Wingman uses. Document it in writing per the court's requirement.

### Colorado Lawyer Article — "From Prompt to Production" (May/June 2026)
**Author:** Donovan Estrada, Hall Booth Smith PC
**Publication:** Colorado Lawyer, the official CBA journal

**Key holdings and rules synthesized:**

**SCA Shield (18 USC §2702):** Generative AI providers likely qualify as both ECS and RCS providers. Civil subpoenas to Anthropic/OpenAI/Google for user chat logs are likely blocked by SCA. No civil discovery exception. BUT — parties must still produce their own AI chats if they have possession, custody, or control (can log in and export). Subpoena goes to the party, not the provider.

**Critical case — Tremblay v. OpenAI (N.D. Cal. 2024):** District court reversed magistrate's order to produce all AI prompts. Held: attorney-crafted ChatGPT prompts are work product — "queries crafted by counsel and contain counsel's mental impressions and opinions." Only prompts actually disclosed in filings are discoverable (waiver).

**Critical case — Concord Music Group v. Anthropic PBC (N.D. Cal. May 2025):** Undisclosed AI interactions shielded by work product. Waiver only as to specific prompts included in court filings.

**Delaware warning:** Slam Corp. v. Lynk Glob. (Del. Ch. July 2025): "Providing Confidential Discovery Material to an open [Generative AI] tool is considered a disclosure to a third party." — This is why enterprise tier with DPA matters.

**OpenAI preservation order:** In re OpenAI Copyright Infringement Litig. (SDNY May 2025): Court ordered OpenAI to preserve ALL user chat logs regardless of user privacy settings. This is why consumer-tier Wingman use is dangerous. Enterprise API with zero retention is the only safe configuration.

**Colorado practitioner duties:** Colo. RPC 1.1 comments [8] and [9] — duty of technological competence includes understanding how AI stores and processes data.

**Practical rules for Wingman engagement letters:**
- Use enterprise API tier with documented zero-retention DPA
- Do not attach AI outputs to court filings unless you want them discoverable
- Issue litigation hold notices covering AI tools from day one of representation
- Disclose AI tool identity if asked (Morgan) — but not the prompts themselves

### Warner v. Gilbarco, Inc. (E.D. Mich. Feb. 10, 2026)
ChatGPT and other generative AI programs are "tools, not persons." Disclosure to AI tool is not disclosure "to an adversary or in a way likely to get in an adversary's hands." Supports work product protection for AI interactions.

### "Code as Agent Harness" (arXiv:2605.18747, May 2026)
Academic paper — 102 pages, 42 authors. Directly validates your harness architecture concept at the research level. The paper treats code as the structured control layer for AI agents — exactly what your harness document is. This is citable academic support for the harness-as-architecture concept if you ever need to defend it as a novel system.

### Washington Post Opinion — "Americans have a right to a lawyer. Well, not this kind."
**Author:** Max Raskin, NYU Law Fellow
**Key statistics:**
- 75% of 15+ million civil cases per year have at least one unrepresented party
- Nearly half of sampled California debt-collection cases had uncaught errors that could have changed outcomes with minimal lawyering
- Sullivan & Cromwell (top BigLaw firm) was caught using AI in bankruptcy filings — confirming BigLaw uses it

**Your tagline support:** "The relevant comparison isn't between Claude and Clarence (Thomas or Darrow). It's between Claude and nothing." — This is the access-to-justice argument in one sentence. Use it.

---

## 13. ADA ACCOMMODATION ARGUMENT — WINGMAN AS ASSISTIVE TECHNOLOGY

### The Core Legal Theory
ADA Title II (government entities) and Title III (public accommodations) require reasonable accommodations. Courts are government entities under Title II. The standard: balance between (a) constitutional right of access to courts and (b) cost/disruption to the government entity.

**Cost to court = zero.** Wingman is worn by the party, runs on their phone, outputs to their earpiece. The court provides nothing, installs nothing, and does no work. Cost/disruption to government: $0.

**Constitutional access right:** Boddie v. Connecticut (1971) — access to courts is a constitutional right. Tennessee v. Lane (2004) — ADA applies to court access specifically. The higher the constitutional right at stake, the lower the burden on the government to accommodate.

### Analog Device Precedent (your strongest argument)
Hearing aids, cochlear implants, Siri on iPhones, Amazon Alexa, Google Assistant — all are already present in courtrooms every day on the devices of parties, attorneys, jurors, and judges. None are regulated or required to be disclosed. Wingman is functionally equivalent: a real-time audio processing device worn by or held by a party. The microphone in an iPhone listening to Siri is not distinguishable from Wingman's mic listening to Gemini.

**The recording ban is different:** CO and federal court prohibitions on recording/photography/livestreaming cover output — creating a record that leaves the courtroom. Wingman's data does NOT leave — it is processed in real time and the session transcript is destroyed within 30 days. The data is never "hosted" or "held" in the way that triggers recording concerns. It is equivalent to a party taking mental notes or whispering to an advisor.

### The Recording Prohibition Analysis
Colorado's prohibition: strictly for livestreaming, not for using hearing assistance. Federal courts: recording prohibited, but real-time audio processing for the party's own use is not recording in the statutory sense. Wingman is a listening and advisory tool, not a recording tool. The 30-day retention with destruction and the no-third-party-access architecture supports this.

Key distinction to make explicit in the harness: Wingman does not create a "record" in the legal sense — it creates a working document under work product protection that self-destructs. This is analogous to an attorney whispering advice to a client in real time.

### The "Alexa in Courtrooms" Defense
Every iPhone in every courtroom is running Siri, which is always-on listening. Every Android is running Google Assistant. These transmit audio to Apple/Google servers. If courts permitted this (they do, implicitly), they must permit Wingman, which has MORE privacy protection (enterprise API, zero retention, 30-day destruction) than Siri/Alexa.

### ADA Accommodation Request Process
Before any hearing where Wingman will be used: file a written ADA accommodation request with the court clerk specifying:
- Party has a legal advisory assistance need
- Requests permission to use a personal electronic advisory device
- Device does not record or transmit proceedings externally
- Device is equivalent to a hearing aid or other assistive listening device
- Zero cost to court
- Attach enterprise API DPA documentation

Most courts will grant this without a hearing. If denied, the denial itself creates an ADA claim and a constitutional access-to-courts claim.

---

## 14. ENCRYPTION AND DATA ARCHITECTURE — SELF-DESTRUCTING HARNESS

### One-Time Pad Concept for Harness
Each client harness is unique — generated fresh for that matter, encrypted with a session-specific key, and the key is destroyed after 30 days along with the transcript. This is functionally a one-time pad for the session data. No two harnesses share encryption keys. No harness can be reconstructed from any other.

### Self-Imploding Code Architecture
Each session harness should:
1. Generate a unique session ID and encryption key at initialization
2. Encrypt all session transcripts locally
3. Set a 30-day TTL (time-to-live) after which the key is destroyed making data unrecoverable
4. Log the destruction event (not the content) for compliance purposes

This satisfies ethical record retention rules (which are ethics rules, not statutes) while providing the strongest possible privacy protection. Destruction is logged but content is irrecoverable.

### First Amendment / Code is Speech Defense
Tornado Cash case (CA) and related: code is protected speech under the First Amendment. The harness document — as structured code directing AI agents — may enjoy First Amendment protection as expressive content. The argument: the harness encodes the attorney's legal strategy in executable form. Compelling disclosure of the harness would be compelled speech of the attorney's mental impressions, violating both the First Amendment and the work product doctrine simultaneously.

---

## 15. PRODUCT POSITIONING — ACCESS TO JUSTICE

### The Pitch
**Tagline:** "There are some battles in life you must win."

**The gap:** 75% of civil cases have at least one unrepresented party. BigLaw uses AI. Courts use AI. Government uses AI (and illegally collected surveillance data). The individual citizen has nothing equivalent. Kingsfield corrects this.

**Every professional code of conduct:** includes duty to serve the public, pro bono obligations, benefit to taxpayers. The legal profession's own rules require addressing this gap. Kingsfield is compliance with those rules at scale.

**The asymmetry being corrected:**
- BigLaw: Opus/GPT-5.5 for strategy, massive litigation support teams, AI-enhanced discovery
- Government: CCTV cameras, adtech data purchased for surveillance, FISA court access
- Individual citizen: nothing

Kingsfield: real-time AI advisor in your ear, full judicial analytics, AI council for strategy, at a price point accessible to solo practitioners and pro se parties.

### The Scale Model
Talent agency call flow model (1990s): ~200 clients/day for a senior practitioner. Each gets a pre-session harness injection, a live Wingman session, and a post-session Council analysis. Scalable because the AI does the work, not the attorney's time.

### Test Cases for Launch
- Newscast commentary analysis (media personality)
- Sermon/religious speech (pastor — First Amendment angle)
- Deposition preparation (standard legal)
- Contract negotiation (business)
- Court hearing (the core use case)

### NotebookLM / Open Source Wrapper
Post-session output: session transcript → Fusion panel analysis → NotebookLM-style audio summary delivered as spoken brief. Open source version of NotebookLM as a wrapper for the post-session intelligence delivery. This closes the loop: live advisory during → structured intelligence after.
