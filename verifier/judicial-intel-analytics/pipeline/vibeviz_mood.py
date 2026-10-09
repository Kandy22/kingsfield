"""VibeViz mood heuristic — ported from remix_-vibeviz FaceLandmarker blendshapes."""
from __future__ import annotations

from typing import Any


def _get_score(blendshapes: dict[str, float], name: str) -> float:
    return float(blendshapes.get(name, 0.0))


def mood_from_blendshapes(
    blendshapes: dict[str, float],
    base: dict[str, float] | None = None,
    smoothed: dict[str, float] | None = None,
) -> tuple[dict[str, float], float, str, dict[str, float]]:
    """
    Returns (smoothed_emotions, mood_score 0-1, dominant_emotion, blendshapes_out).
    mood_score: 0 = negative, 1 = positive (VibeViz vibe check).
    """
    base = base or {"biu": 0.0, "bd": 0.0, "bid": 0.0, "ns": 0.0}

    def avg(*keys: str) -> float:
        return sum(_get_score(blendshapes, k) for k in keys) / len(keys)

    current_raw = {
        "biu": _get_score(blendshapes, "browInnerUp"),
        "bd": avg("browDownLeft", "browDownRight"),
        "bid": avg("browInnerDownLeft", "browInnerDownRight"),
        "ns": avg("noseSneerLeft", "noseSneerRight"),
    }
    n_biu = max(0.0, current_raw["biu"] - base["biu"])
    n_bd = max(0.0, current_raw["bd"] - base["bd"])
    n_bid = max(0.0, current_raw["bid"] - base["bid"])
    n_ns = max(0.0, current_raw["ns"] - base["ns"])

    jo = _get_score(blendshapes, "jawOpen")
    mf = avg("mouthFrownLeft", "mouthFrownRight")
    ew = avg("eyeWideLeft", "eyeWideRight")
    sm = avg("mouthSmileLeft", "mouthSmileRight")
    eb = avg("eyeBlinkLeft", "eyeBlinkRight")
    sq = avg("eyeSquintLeft", "eyeSquintRight")
    ms = avg("mouthStretchLeft", "mouthStretchRight")
    bou = avg("browOuterUpLeft", "browOuterUpRight")

    anger_base = 0.0
    max_brow_down = max(n_bd, n_bid)
    if max_brow_down > 0.03:
        anger_base = (max_brow_down - 0.03) * 4.0 + sq * 0.5 + n_ns * 0.2

    laugh_base = (
        min(1.0, sm * 0.6 + jo * 0.8) if sm > 0.4 and jo > 0.15 else 0.0
    )
    smile_base = 0.2 if laugh_base > 0.5 else sm
    sad_base = (n_biu * 0.5 + mf * 0.5) * (1 - jo * 1.2)

    targets = {
        "Smile": smile_base,
        "Laugh": laugh_base,
        "Sad": max(0.0, sad_base),
        "Angry": max(0.0, anger_base),
        "Surprised": jo * 0.8 + ew * 0.2,
        "Fear": max(0.0, (n_biu * 0.4 + bou * 0.3 + ew * 0.3 + ms * 0.1) - 0.15),
        "Sleepy": max(0.0, (eb - 0.6) * 2.5),
    }

    if smoothed is None:
        smoothed = {k: 0.0 for k in targets}
    for key in smoothed:
        smoothed[key] = smoothed[key] * 0.8 + targets[key] * 0.2

    dom = "Neutral"
    max_score = 0.15
    for name, score in smoothed.items():
        if name == "Sad":
            continue
        if score > max_score:
            max_score = score
            dom = name

    pos = (
        (smoothed["Smile"] * 2.0 if smoothed["Smile"] > 0.05 else 0.0)
        + (smoothed["Laugh"] * 2.5 if smoothed["Laugh"] > 0.05 else 0.0)
        + (smoothed["Surprised"] * 0.5 if smoothed["Surprised"] > 0.15 else 0.0)
    )
    neg = (
        (smoothed["Angry"] * 2.0 if smoothed["Angry"] > 0.05 else 0.0)
        + (smoothed["Sad"] * 1.5 if smoothed["Sad"] > 0.05 else 0.0)
        + (smoothed["Fear"] * 1.2 if smoothed["Fear"] > 0.15 else 0.0)
    )
    mood_target = max(0.0, min(1.0, (pos - neg + 1) / 2))
    if dom == "Neutral":
        mood_target = 0.5

    return smoothed, mood_target, dom, blendshapes