import json
import os
from google import genai
from google.genai import types

# Initialize the Gemini Client
client = genai.Client()

# Using Gemini 3.5 Pro to manage high-context behavioral reasoning
MODEL_ID = "gemini-3.5-pro"

def build_behavioral_prompt(transcript_segment, physical_signals):
    """
    Constructs a highly structured system prompt that forces the model
    to output raw analytics instead of soft, conversational summaries.
    """
    return f"""
    You are an advanced biometric and litigation analysis engine. Your goal is to construct a verified 
    behavioral dataset mapping courtroom dynamics for jury selection and judicial profiles.
    
    CRITICAL ANALYSIS CRITERIA:
    1. Assess the target speaker's tactical comfort level based on the physical signal data.
    2. Quantify hidden micro-tensions, conversational hesitation markers, and potential bias indicators.
    3. Determine the speaker's probable likes, dislikes, or triggers based on structural pivots.
    
    TRANSCRIPT DATA:
    {json.dumps(transcript_segment, indent=2)}
    
    LOCAL BIOMETRIC SIGNALS (MediaPipe/Acoustic):
    {json.dumps(physical_signals, indent=2)}
    
    Output your analysis EXCLUSIVELY as a valid JSON object matching this schema:
    {{
        "metric_metadata": {{
            "speaker_identity": "string",
            "perceived_credibility_score": 0.00, # 0.00 to 1.00
            "tactical_vulnerability_detected": true/false
        }},
        "behavioral_analysis": {{
            "vocal_hesitation_triggers": ["string"],
            "stress_response_indicators": ["string"],
            "argument_resonance": "Did the judge lean in or pull away textually?"
        }},
        "jury_selection_value": {{
            "bias_flags": ["string"],
            "persuasion_vectors": ["What specific rhetorical style worked on this speaker?"]
        }}
    }}
    """

def process_courtroom_archive(manifest_path):
    """
    Iterates through the verified court transcripts and local signals
    to compile the benchmark dataset.
    """
    print(f"[Dataset Engine] Loading manifest from: {manifest_path}")
    with open(manifest_path, 'r') as f:
        manifest = json.load(f)
        
    benchmark_dataset = []
    
    # Process segments (e.g., specific trial cross-examinations)
    for case in manifest.get("cases", []):
        print(f"[Processing Case] Evaluating: {case['case_number']} - {case['title']}")
        
        # Pull your pre-extracted local behavioral telemetry
        transcript = case.get("transcript_segments", [])
        signals = case.get("mediapipe_signals", {})
        
        # Generate the structured analytical layer
        prompt = build_behavioral_prompt(transcript, signals)
        
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1 # Low temperature ensures strict, repeatable data metrics
            )
        )
        
        # Parse the output directly into the final dataset index
        try:
            structured_data = json.loads(response.text)
            structured_data["case_id"] = case["case_number"]
            benchmark_dataset.append(structured_data)
            print(f"[Success] Indexed behavioral map for {case['case_number']}")
        except json.JSONDecodeError:
            print(f"[Error] Failed to parse model output for case {case['case_number']}")
            
    # Save the finalized benchmark layer
    output_file = "judicial_analytics_benchmark.json"
    with open(output_file, 'w') as out:
        json.dump(benchmark_dataset, indent=2)
    print(f"\n[Dataset Complete] Finalized dataset saved to {output_file}. Ready for Hugging Face upload.")

if __name__ == "__main__":
    # Point this to your nested data directory path
    MOCK_MANIFEST = "judicial-intel/data/fl_2dca/manifest.json"
    
    # Ensure file structure exists before running
    if os.path.exists(MOCK_MANIFEST):
        process_courtroom_archive(MOCK_MANIFEST)
    else:
        print(f"[Abort] Please verify your nested file path exists at: {MOCK_MANIFEST}")