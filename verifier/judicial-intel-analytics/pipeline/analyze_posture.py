"""Robotics-ER posture + wide-shot gaze note for judicial analyzer."""
import base64
import json
import os
import re


def _api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    if not key:
        raise RuntimeError("Set GEMINI_API_KEY")
    return key


def _b64_image(frame_path: str) -> tuple[str, str]:
    with open(frame_path, "rb") as f:
        data = base64.b64encode(f.read()).decode("ascii")
    ext = os.path.splitext(frame_path)[1].lower()
    mime = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
    return mime, data


def analyze_posture(frame_path: str) -> dict:
    from google import genai

    mime, data = _b64_image(frame_path)
    client = genai.Client(api_key=_api_key())
    prompt = (
        "Detect body language in this court hearing frame. Return JSON only: "
        '{"shoulder_line":"level|tilted","arm_position":"crossed|open|neutral",'
        '"lean":"forward|back|neutral","points":[{"label":"left_shoulder","x":0.0,"y":0.0}]}'
    )
    response = client.models.generate_content(
        model="gemini-robotics-er-1.6-preview",
        contents=[
            {"inline_data": {"mime_type": mime, "data": data}},
            {"text": prompt},
        ],
        config={"response_mime_type": "application/json"},
    )
    text = (response.text or "{}").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        return json.loads(m.group(0)) if m else {"error": "parse_failed"}


def analyze_gaze_note(frame_path: str) -> str:
    from google import genai

    mime, data = _b64_image(frame_path)
    client = genai.Client(api_key=_api_key())
    prompt = (
        "In ≤7 words, describe where this person is looking "
        "(notes / podium / away / camera). Reply with words only."
    )
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            {"inline_data": {"mime_type": mime, "data": data}},
            {"text": prompt},
        ],
    )
    return (response.text or "").strip().split("\n")[0][:80]