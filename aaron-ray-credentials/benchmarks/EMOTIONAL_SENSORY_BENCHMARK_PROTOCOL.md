# Emotional & Sensory Benchmark Protocol

**Version:** 0.1  
**Date:** June 2026  
**Focus Domains:** Music is Medicine (emotional regulation), Artificial Senses pillars, Forensic AV authentication, Narrative persuasion, Judicial analytics signals  
**License:** CC BY 4.0 (adaptable)  
**Methodology Inspiration:** Kingsfield Legal Citation Verification Benchmark (disagreement tracking, human grounding, multi-model + source validation)

---

## What This Is

A rigorous, publishable benchmark framework for **AI emotional and sensory processing**. It measures how well models (and systems) predict or induce human emotional and perceptual responses to media (audio, video, narrative, multimodal).

Core goal: Create objective, hard-to-fake metrics that eliminate the overclaiming and lies common in this space. Build directly on your cross-domain expertise (entertainment-scale emotional direction, forensic AV, ML, and live sensor work).

This is **not** another subjective emotion dataset. It is a **multi-modal verification benchmark** combining:
- In-silico brain response prediction (Meta TRIBE v2)
- Real physiological + behavioral ground truth (EEG/brainwave, HRV, task performance, validated scales)
- Human expert ratings with explicit disagreement analysis
- Source grounding against stimuli features

---

## Why This Matters Now

- TRIBE v2 (Meta FAIR, 2026) gives a powerful open **brain encoding foundation model**: tri-modal (video + audio + language) predictor of whole-brain fMRI responses trained on 500–1,000+ hours from 700+ subjects. Zero-shot, high resolution, in-silico experimentation.
- Your existing "Music is Medicine: Song Emotional Map" Google Sheet provides an excellent stimulus taxonomy (acoustic features → emotion labels + color spectrum).
- Competition (commercial emotion AI, "therapeutic audio," legal analytics, surveillance "safety" tools) already uses similar signals and routinely overclaims.
- You need published track record + replicable methodology to back the Executive Credential Synthesis positioning (AI Emotional Benchmarking + Forensic AV + Artificial Senses).

This protocol turns those assets into defensible benchmarks.

---

## Scope & Test Domains (The Four Agendas)

| Agenda | Primary Stimuli | Target Constructs | Primary Validation | TRIBE v2 Role | Real Data Layer |
|--------|-----------------|-------------------|--------------------|---------------|-----------------|
| 1. Music is Medicine | Songs / structured audio (your map) | Attention, arousal regulation, calm, focus (esp. pediatric ADHD non-pharma) | EEG bands (alpha ↑ calm, beta/theta ratio ↓), HRV, behavioral attention tasks, parent/teacher scales | Primary: predict regional responses to audio features | Consumer EEG (Muse/Emotiv/OpenBCI) + behavioral |
| 2. Kingsfield Lawfare (Moneyball for Court) | Testimony audio/video, arguments, narratives | Credibility signals, cognitive load, bias activation, persuasion impact | Judicial outcomes where available, human forensic raters, voice stress features | Secondary: predicted brain response to AV legal stimuli | Forensic AV features + public docket outcomes |
| 3. Artificial Senses (sensors) | Live sensor streams + media | Sensory sharpening, overload detection, manipulation resistance | Sensor fusion metrics, performance under load, physiological stress load | Stimulus encoding for comparison | Your existing live sensors + data |
| 4. Rashomon (multi-source emergency localization) | Drone AV + traffic/LPR + social context + CCTV | Location reconstruction accuracy, identity verification under stress, event reconstruction | Ground-truth GPS/timestamps (consented family test cases), public data fusion | AV stimulus → predicted stress/attention signatures | Public traffic data (Aspen/WPB vendor), DEFlock LPR, Shodan-reachable public cams (legal scope only), GPS |

Start with **Agenda 1 (Music is Medicine)** for fastest path to a publishable first benchmark. It has the cleanest claims, your sheet as stimuli base, and direct ties to non-pharmacological regulation.

---

## Core Methodology (Adapted from Kingsfield Citation Benchmark)

1. **Stimuli Curation & Feature Taxonomy**  
   Start with your Song Emotional Map. Expand to canonical dataset (CSV/JSON + stimulus files or references).

2. **Multi-Model + In-Silico Predictions**  
   - TRIBE v2: Feed audio (or AV) stimuli → predicted fMRI maps (whole-brain or ROI).  
   - Frontier LLMs / emotion models: Label emotions, predict regulation effect.  
   - Record full "verdicts" + reasons (analogous to yes/no/unsure + explanation).

3. **Ground Truth Construction (Human + Physiological)**  
   - Human raters (multiple, blinded): emotion labels, perceived regulation strength.  
   - Real measurements on target population (start small-N pilots with kids/adults): EEG during stimulus, pre/post attention tasks, validated scales (e.g., ADHD-RS, arousal/valence).  
   - For legal/forensic domains: expert raters + outcome grounding where possible.

4. **Disagreement & Error Analysis** (the secret sauce)  
   - Track where TRIBE predictions diverge from real EEG/fMRI.  
   - Where human raters disagree with each other or with models.  
   - High-value cases go into a `disagreements.json`-style artifact.  
   - Explicitly distinguish "verbatim/feature match" vs "substantive emotional effect."

5. **Scoring & Metrics**  
   - Predictive accuracy: correlation between TRIBE-predicted regions and measured EEG/physiology.  
   - Regulation validity: does "calming map" stimulus actually move target metrics more than controls?  
   - Inter-rater / inter-model agreement rates (aim to beat the ~33% unanimous seen in citation work).  
   - Error typology (false calm, missed stress, cultural bias, temporal mismatch fMRI vs EEG).  
   - Efficiency / zero-shot generalization (new subjects, new genres, new languages).

6. **Grounding Pipeline** (Grinder-style)  
   Adapt the verifiable pipeline idea: stimulus → TRIBE inference (cached) → real data collection queue → human/EEG grounding → update canonical results.

---

## Data Schema (Initial)

```json
{
  "idx": 1,
  "stimulus_id": "cyndi_lauper_girls_just_want_to_have_fun",
  "source": "user_song_map_v1",
  "features": {
    "key": "F major",
    "tempo": 120,
    "melody": "bright playful hook",
    "harmony": "I–V–vi–IV",
    ...
  },
  "map_emotion": "Joy / Freedom",
  "map_color": "Hot pink, neon yellow",
  "tribe_v2_prediction": {
    "regions": ["auditory_cortex", "nucleus_accumbens", "prefrontal"],
    "predicted_effect": "increased reward + reduced anxiety networks",
    "confidence": 0.87
  },
  "agent_verdicts": {
    "tribe_v2": {...},
    "llama_emotion": {"verdict": "high_joy", "reason": "..."},
    "deepseek_reasoner": {"verdict": "regulation_positive", "reason": "..."}
  },
  "human_labels": [{"rater": "expert1", "emotion": "...", "regulation_strength": 8}],
  "real_measurements": {
    "eeg_alpha_change": 0.24,
    "task_attention_improvement": 0.18,
    "subject_count": 12
  },
  "grounded_verdict": "positive_regulation_supported",
  "disagreement_notes": "..."
}
```

---

## Stimuli Dataset (Song Emotional Map)

**Source of truth:** Your original Google Sheet:  
https://docs.google.com/spreadsheets/d/1WHwVi7B4z46Hp0AMYCgExuB7xe0J1RUEdoiXIIwi1R0/edit?gid=1412552516#gid=1412552516

**Do not create or scan new local CSVs** for this work unless you explicitly export subsets yourself for scripting. Keep the sheet as the living source.

**Next steps for full dataset:**
- From the sheet, export only the tabs/rows you need (Main tab primarily) as needed for scripts.
- Add columns directly in the sheet or in a working export: `tribe_v2_regions`, `target_eeg_metrics`, `pilot_results`, `source_audio_url_or_file` (respect copyright — use short clips, timestamps, or descriptions for any public benchmark release).
- Version snapshots with the protocol when you publish.

---

## TRIBE v2 Integration Notes

- Repo: https://github.com/facebookresearch/tribev2
- Weights: Hugging Face `facebook/tribev2`
- Demo: aidemos.atmeta.com/tribev2 (or local)
- Input: Video/audio/text (or audio-only for music focus). Outputs predicted fMRI volumes or ROI activations.
- Usage pattern (see `tribe_integration.py` starter):
  ```python
  # Pseudo
  stimuli = load_song_map()
  for s in stimuli:
      pred = tribe_model.predict(audio=s["audio"], text=s["lyrics_or_description"])
      # Compare pred to real_eeg or map_emotion
  ```
- Strengths for you: Directly supports audio-heavy Music is Medicine and multimodal Rashomon/Narrative work.
- Limitations: fMRI (slow hemodynamics). Pair with EEG for brainwave temporal resolution. Always validate — it is a model, not ground truth.

Run in-silico experiments first (thousands of virtual subjects), then targeted real pilots only on the most promising or discrepant cases.

---

## Pilot Plan (First 6–9 Months)

1. **Month 1**: Formalize stimuli dataset (export full sheet + schema). Implement TRIBE v2 inference harness + basic comparison to your map labels.
2. **Month 2**: Small adult pilot (n=15–20) with EEG + song stimuli. Collect TRIBE predictions vs real data. Build disagreements set.
3. **Month 3**: Pediatric-friendly protocol (ethical, short sessions, game-like attention tasks). Initial kid data (small n, with proper IRB/parental consent).
4. **Month 4–5**: Expand to one other agenda (e.g., narrative persuasion clips or forensic AV stress examples). Add multi-model comparison.
5. **Month 6+**: Human rater pool + full disagreement analysis. Prepare first public release + paper draft modeled on Kingsfield citation benchmark.

Use the same philosophy as Kingsfield: publish the methodology, the disagreements, the grounding process. Transparency beats marketing claims.

---

## Risks & Ethical Guardrails

- **Privacy / biometrics**: Any real EEG or family data must be consented, minimal, and IRB-appropriate. For Rashomon-style work, stay strictly within legal public data sources and consented test cases. Never scrape private cameras or biometrics without explicit authorization.
- **Overclaim**: TRIBE predictions are not "reading minds." They are stimulus-to-average-brain-response models. Always report uncertainty and validation gaps.
- **Pediatric**: Extra caution on claims for kids. Regulation effects must be measured, not assumed.
- **Dual use**: Sensory/emotion tech can be used for manipulation. The benchmark should explicitly test resistance to co-opting (Agenda 3).

---

## Deliverables & Artifacts

- This protocol (`EMOTIONAL_SENSORY_BENCHMARK_PROTOCOL.md`)
- `tribe_integration.py` (starter script — self-contained with examples; pull additional data manually from the source Google Sheet as needed)
- `disagreements.json` (to be populated from runs)
- `results_full.json` (canonical benchmark results — future)
- Human review UI (adapt from `kingsfield/verifier/sandbox.html` if useful)

---

## Citation (When Published)

```
@dataset{aaron_ray_emotional_sensory_benchmark_2026,
  title     = {Emotional and Sensory Benchmark Protocol},
  author    = {Aaron Ray},
  year      = {2026},
  version   = {0.1},
  note      = {Built on TRIBE v2 (Meta FAIR) and Kingsfield citation benchmark methodology}
}
```

---

## Next Actions (Immediate)

1. Manually copy additional rows from your original Google Sheet as needed (no new automated scanning or local CSVs).
2. Clone the TRIBE v2 repo (https://github.com/facebookresearch/tribev2) and run a smoke test using the examples in `tribe_integration.py`.
3. Decide on pilot population + sensor hardware (e.g. consumer EEG) for first real data collection.
4. Adapt relevant pieces from your existing `kingsfield/verifier/` (grinder, disagreements handling, human review) into a "Stimulus Grinder" for this domain.

This is how you turn "I have deep experience" into something concrete, citable, and defensible.

The four agendas now have a shared measurement backbone. Execute the protocol and the credential synthesis becomes earned, not aspirational.

This is how you turn "I have deep experience" into something concrete, citable, and defensible.

The four agendas now have a shared measurement backbone. Execute the protocol and the credential synthesis becomes earned, not aspirational.

---

**Status:** Ready for implementation. Use your existing Kingsfield infrastructure patterns wherever possible for speed and consistency. 

Contact / updates: Track in this folder. Rebuild artifacts as data grows.