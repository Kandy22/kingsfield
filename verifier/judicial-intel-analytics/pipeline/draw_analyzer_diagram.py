#!/usr/bin/env python3
"""Judicial ANALYZER diagram — perceive stage, court shots, GAI reaction chain."""
import glob
import os
from PIL import Image, ImageDraw, ImageFont

OUT = "/Users/aaronray/Desktop/JUDICIAL-ANALYZER-DIAGRAM.png"
SHOTS_DIR = "/Users/aaronray/kingsfield/judicial-court-videos/color-judicial"
W, H = 1600, 1100


def _fonts():
    try:
        return (
            ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 30),
            ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 17),
            ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 13),
        )
    except OSError:
        d = ImageFont.load_default()
        return d, d, d


def _box(draw, xy, title, body, color="#38bdf8", fill="#1e293b"):
    x1, y1, x2, y2 = xy
    title_f, body_f, _ = _fonts()
    draw.rounded_rectangle([x1, y1, x2, y2], radius=10, fill=fill, outline=color, width=2)
    draw.text((x1 + 12, y1 + 10), title, fill=color, font=body_f)
    draw.multiline_text((x1 + 12, y1 + 34), body, fill="#cbd5e1", font=_fonts()[2], spacing=3)


def _arrow(draw, a, b):
    draw.line([a, b], fill="#64748b", width=3)
    dx, dy = b[0] - a[0], b[1] - a[1]
    if abs(dx) >= abs(dy):
        tip = (b[0] - 12 if dx > 0 else b[0] + 12, b[1])
    else:
        tip = (b[0], b[1] - 12 if dy > 0 else b[1] + 12)
    draw.polygon([b, (tip[0] - 7, tip[1] - 7), (tip[0] + 7, tip[1] + 7)], fill="#64748b")


def _paste_shots(canvas, x, y, cols=4, thumb_w=170, thumb_h=110):
    paths = sorted(glob.glob(os.path.join(SHOTS_DIR, "*.png")))[:7]
    for i, p in enumerate(paths):
        try:
            im = Image.open(p).convert("RGB")
            im.thumbnail((thumb_w, thumb_h))
            row, col = divmod(i, cols)
            px = x + col * (thumb_w + 8)
            py = y + row * (thumb_h + 8)
            canvas.paste(im, (px, py))
            ImageDraw.Draw(canvas).rectangle(
                [px, py, px + im.width, py + im.height], outline="#475569", width=1
            )
        except OSError:
            pass


def main():
    img = Image.new("RGB", (W, H), "#0b0f14")
    draw = ImageDraw.Draw(img)
    title_f, _, small = _fonts()

    draw.text((40, 18), "Judicial Analyzer — Court Reaction Perceive Layer", fill="#f1f5f9", font=title_f)
    draw.text(
        (40, 52),
        "Tight vs wide shot routing · EchoScript #1 · VibeViz visual · GAI mood→music bridge",
        fill="#94a3b8",
        font=small,
    )

    # Court reference grid (your color-judicial shots)
    draw.rounded_rectangle([40, 85, 780, 340], radius=12, outline="#334155", width=2, fill="#111827")
    draw.text((52, 95), "COURT VIDEO INPUT (color-judicial reference frames)", fill="#a5b4fc", font=small)
    _paste_shots(img, 52, 120, cols=4)

    # Central router
    _box(draw, (820, 120, 1080, 220), "SHOT ROUTER", "face height > 80px?\nYES → tight path\nNO  → wide path", "#fbbf24")

    # Tight path
    _box(
        draw,
        (40, 380, 360, 520),
        "TIGHT SHOT",
        "MediaPipe FaceLandmarker\n52 blendshapes\nVibeViz mood_score_visual\nIris gaze dx/dy",
        "#34d399",
    )
    _box(
        draw,
        (380, 380, 700, 520),
        "ECHOSCRIPT (#1)",
        "diarize.py — Gemini audio\nspeaker + timestamp\nemotion_audio:\nHappy/Sad/Angry/Neutral\n10-min chunking",
        "#22d3ee",
    )

    # Wide path
    _box(
        draw,
        (820, 380, 1140, 520),
        "WIDE SHOT",
        "Robotics-ER 1.6 posture\nshoulders / arms / lean\nGemini gaze_note ≤7 words\n(notes / podium / away)",
        "#fb923c",
    )
    _box(
        draw,
        (1160, 380, 1560, 520),
        "MERGE",
        "merge_signals.py\ntimeline.json per segment\nmood_score_visual +\nemotion_audio + gaze",
        "#a78bfa",
    )

    # GAI reaction → music bridge (NOT skip)
    _box(
        draw,
        (40, 560, 400, 700),
        "LYRIA-CAMERA",
        "Live court reaction\ncapture → ambient score",
        "#f472b6",
    )
    _box(
        draw,
        (420, 560, 780, 700),
        "GEMINI-SLINGSHOT",
        "Rapid multimodal\nreaction scoring",
        "#f472b6",
    )
    _box(
        draw,
        (800, 560, 1160, 700),
        "PROMPTDJ / SCORE-VIDEO",
        "Mood → music param\nbridge for hearings",
        "#f472b6",
    )
    _box(
        draw,
        (1180, 560, 1560, 700),
        "WINGMAN :3002",
        "Face mood panel +\nlive advisor harness\njudicial reaction cues",
        "#4ade80",
    )

    # Downstream
    _box(
        draw,
        (420, 740, 900, 860),
        "KINGSFIELD VERIFIER",
        "Four-gate citations\nGRINDER grounding\nCouncil predict lean",
        "#60a5fa",
    )
    _box(
        draw,
        (920, 740, 1400, 860),
        "JUDGE TIMELINE STORE",
        "judges/<Name>/<hearing>/timeline.json\nSpeaker 1 → manual judge tag",
        "#60a5fa",
    )

    # Arrows
    _arrow(draw, (410, 250), (820, 170))
    _arrow(draw, (950, 220), (200, 380))
    _arrow(draw, (950, 220), (980, 380))
    _arrow(draw, (360, 450), (820, 450))
    _arrow(draw, (700, 450), (1160, 450))
    _arrow(draw, (200, 520), (220, 560))
    _arrow(draw, (600, 520), (600, 560))
    _arrow(draw, (980, 520), (980, 560))
    _arrow(draw, (1360, 520), (1280, 560))
    _arrow(draw, (660, 700), (660, 740))

    draw.text(
        (40, 1020),
        "Files: verifier/judicial-intel/pipeline/{analyze_signals,diarize,merge_signals}.py | Desktop: JUDICIAL-FLOW-DIAGRAM.png",
        fill="#64748b",
        font=small,
    )
    img.save(OUT)
    print(OUT)


if __name__ == "__main__":
    main()