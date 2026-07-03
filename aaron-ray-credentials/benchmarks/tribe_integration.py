#!/usr/bin/env python3
"""
TRIBE v2 + Song Emotional Map Integration Starter
For Emotional & Sensory Benchmark Protocol v0.1

Purpose:
- Load your song emotional map as stimuli.
- Prepare inputs for Meta's TRIBE v2 (tri-modal brain encoder).
- Run predictions (or mock if no weights locally).
- Compare against map labels + prepare for real EEG / human grounding.
- Log disagreements for benchmark analysis (Kingsfield style).

Requirements (real run):
    pip install torch torchaudio transformers soundfile
    # Then clone https://github.com/facebookresearch/tribev2
    # Download weights from HF: facebook/tribev2

This is a scaffold. Fill in the real inference once you have the repo running.
"""

import json
from pathlib import Path
from typing import Dict, List, Any

# --- Config ---
OUTPUT_RESULTS = Path("tribe_results_v0.1.json")
DISAGREEMENTS = Path("disagreements.json")

# Mock mode: True until you wire real TRIBE v2
MOCK_MODE = True

# Source of truth for stimuli data: your original Google Sheet
# https://docs.google.com/spreadsheets/d/1WHwVi7B4z46Hp0AMYCgExuB7xe0J1RUEdoiXIIwi1R0/edit?gid=1412552516#gid=1412552516
# Do NOT create or rely on new scanned local CSVs. Manually copy rows or export subsets only when needed for scripting.
# Examples below are pulled directly from the sheet data you shared.

def get_song_examples() -> List[Dict[str, Any]]:
    """Hardcoded examples from the sheet (no CSV scanning). Add more manually from the Google Sheet as needed."""
    return [
        {
            "idx": 1,
            "song": "Cyndi Lauper – Girls Just Want to Have Fun",
            "key": "F major",
            "tempo": "120 BPM",
            "melody": "Bright, playful, high-pitched hook",
            "harmony": "I–V–vi–IV variation",
            "instruments": "Synths, drum machine, guitar",
            "tone": "Fun, rebellious, carefree",
            "imagery": "Neon lights, 80s fashion, girlfriends laughing",
            "emotion": "Joy / Freedom",
            "color": "Hot pink, neon yellow",
            "target_eeg_metrics": "alpha_up, reward_network",
            "audio_ref": "short_clip_or_youtube_ref",
        },
        {
            "idx": 2,
            "song": "Fleetwood Mac – Landslide",
            "key": "C major",
            "tempo": "75 BPM",
            "melody": "Gentle, descending, reflective",
            "harmony": "C–G/B–Am–G",
            "instruments": "Acoustic guitar, soft vocals",
            "tone": "Tender, nostalgic, bittersweet",
            "imagery": "Mountains, falling leaves, self-reflection",
            "emotion": "Nostalgia / Vulnerability",
            "color": "Earth tones, soft green",
            "target_eeg_metrics": "alpha, dmN",
            "audio_ref": "short_clip_or_youtube_ref",
        },
        {
            "idx": 3,
            "song": "Pharrell Williams – Happy",
            "key": "F minor",
            "tempo": "160 BPM",
            "melody": "Simple, repetitive, hook-driven",
            "harmony": "i–♭VII–IV",
            "instruments": "Handclaps, bass, funky guitar, Rhodes",
            "tone": "Optimistic, uplifting, infectious",
            "imagery": "Sunlight, dancing in the street, kids clapping",
            "emotion": "Optimism / Celebration",
            "color": "Yellow, sky blue",
            "target_eeg_metrics": "beta_attention, reward",
            "audio_ref": "short_clip_or_youtube_ref",
        },
        {
            "idx": 4,
            "song": "Guns N’ Roses – Welcome to the Jungle",
            "key": "B minor",
            "tempo": "120 BPM",
            "melody": "Screamed, blues-pentatonic",
            "harmony": "Riff-based, chromatic",
            "instruments": "Distorted guitars, bass, drums",
            "tone": "Menacing, dangerous, chaotic",
            "imagery": "Dark alleys, neon signs, lawless city",
            "emotion": "Adrenaline / Fear-Excitement",
            "color": "Red, black",
            "target_eeg_metrics": "beta_up, arousal",
            "audio_ref": "short_clip_or_youtube_ref",
        },
        {
            "idx": 5,
            "song": "Metallica – Enter Sandman",
            "key": "E minor",
            "tempo": "123 BPM",
            "melody": "Dark, ominous riff",
            "harmony": "Modal riff vamp",
            "instruments": "Guitars, bass, pounding drums",
            "tone": "Nightmarish, tense, foreboding",
            "imagery": "Creeping shadows, nightmares",
            "emotion": "Fear / Unease",
            "color": "Black, steel gray",
            "target_eeg_metrics": "theta_up, anxiety_markers",
            "audio_ref": "short_clip_or_youtube_ref",
        },
    ]

def prepare_tribe_input(song: Dict[str, Any]) -> Dict[str, Any]:
    """
    Prepare stimulus for TRIBE v2.
    TRIBE expects video/audio/text (or audio + transcript for music).
    For pure music, use audio + descriptive text (lyrics summary or "instrumental").
    """
    text_desc = f"{song['song']}. Key: {song['key']}. Tempo: {song['tempo']}. " \
                f"Melody: {song['melody']}. Harmony: {song['harmony']}. " \
                f"Tone: {song['tone']}. Imagery: {song['imagery']}."

    return {
        "audio": song.get("audio_ref", "path_or_url_to_audio"),  # real path needed for inference
        "text": text_desc,
        "video": None,  # or path to static image / simple visual for AV version
        "metadata": {
            "emotion_label_from_map": song["emotion"],
            "target_eeg": song.get("target_eeg_metrics"),
        }
    }

def run_tribe_prediction(tribe_input: Dict[str, Any], mock: bool = True) -> Dict[str, Any]:
    """
    Call TRIBE v2 (or mock it).
    In real mode: load the model from facebookresearch/tribev2 and run inference.
    """
    if mock:
        # Mock realistic output based on known TRIBE behavior
        # In reality this would be fMRI voxel predictions or ROI activations
        emotion = tribe_input["metadata"]["emotion_label_from_map"]
        mock_regions = {
            "Joy / Freedom": ["auditory_cortex", "nucleus_accumbens", "ventromedial_prefrontal"],
            "Nostalgia / Vulnerability": ["default_mode_network", "hippocampus", "auditory"],
            "Optimism / Celebration": ["reward_circuit", "auditory", "prefrontal"],
        }.get(emotion, ["auditory", "limbic"])

        return {
            "model": "tribe_v2_mock",
            "predicted_regions": mock_regions,
            "predicted_effect": f"Strong {emotion.lower()} signature per map",
            "confidence": 0.81,
            "notes": "Mock until real weights + audio loaded. Replace with real inference.",
        }

    # === REAL TRIBE v2 INFERENCE (uncomment & adapt when ready) ===
    # from tribev2 import FmriEncoderModel  # or whatever the entrypoint is
    # model = FmriEncoderModel.from_pretrained("facebook/tribev2")
    # pred = model.predict(audio=tribe_input["audio"], text=tribe_input["text"])
    # return {
    #     "model": "tribe_v2",
    #     "predicted_regions": extract_rois(pred),
    #     "raw_fMRI_prediction": pred,  # or save NIfTI
    #     ...
    # }
    raise NotImplementedError("Wire real TRIBE v2 here. See github.com/facebookresearch/tribev2")

def compare_to_grounding(song: Dict[str, Any], tribe_pred: Dict[str, Any]) -> Dict[str, Any]:
    """Simple agreement / disagreement detector (expand this massively)."""
    map_emotion = song["emotion"]
    pred_effect = tribe_pred.get("predicted_effect", "").lower()

    agreement = any(word in pred_effect for word in map_emotion.lower().split(" / "))

    verdict = "supported" if agreement else "discrepancy"
    reason = (
        f"TRIBE predicted regions/effect align with map emotion '{map_emotion}'"
        if agreement else
        f"TRIBE effect '{pred_effect}' diverges from map label '{map_emotion}'"
    )

    return {
        "verdict": verdict,
        "reason": reason,
        "map_emotion": map_emotion,
        "tribe_effect": tribe_pred.get("predicted_effect"),
    }

def main():
    print("=== Emotional Sensory Benchmark — TRIBE v2 Integration ===")
    songs = get_song_examples()
    print(f"Loaded {len(songs)} example stimuli from sheet data (add more manually from the Google Sheet)")

    results = []
    disagreements = []

    for song in songs:
        tribe_input = prepare_tribe_input(song)
        tribe_pred = run_tribe_prediction(tribe_input, mock=MOCK_MODE)
        comparison = compare_to_grounding(song, tribe_pred)

        entry = {
            "idx": song["idx"],
            "song": song["song"],
            "stimulus_features": {k: song[k] for k in ["key", "tempo", "harmony", "tone"] if k in song},
            "map_emotion": song["emotion"],
            "tribe_prediction": tribe_pred,
            "comparison": comparison,
        }
        results.append(entry)

        if comparison["verdict"] != "supported":
            disagreements.append(entry)

    # Write canonical results
    with open(OUTPUT_RESULTS, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"Wrote {len(results)} results to {OUTPUT_RESULTS}")

    # Write high-value disagreements (the gold for benchmark rigor)
    with open(DISAGREEMENTS, "w", encoding="utf-8") as f:
        json.dump(disagreements, f, indent=2, ensure_ascii=False)
    print(f"Captured {len(disagreements)} disagreements → {DISAGREEMENTS}")

    print("\nNext:")
    print("- Add more stimuli manually by copying rows from the original Google Sheet into get_song_examples()")
    print("- Set MOCK_MODE=False and wire real TRIBE v2 inference (see github.com/facebookresearch/tribev2)")
    print("- Collect real EEG on the discrepant items")
    print("- Feed disagreements into human review (adapt kingsfield/verifier/sandbox.html)")
    print("- See EMOTIONAL_SENSORY_BENCHMARK_PROTOCOL.md for full plan")

if __name__ == "__main__":
    main()