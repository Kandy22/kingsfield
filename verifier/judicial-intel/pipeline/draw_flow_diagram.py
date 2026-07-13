#!/usr/bin/env python3
"""Render judicial uploader + analytics flow diagram to PNG."""
from PIL import Image, ImageDraw, ImageFont

OUT = "/Users/aaronray/Desktop/JUDICIAL-FLOW-DIAGRAM.png"
W, H = 1400, 900

BOXES = [
    (80, 60, 360, 190, "UPLOAD", "Audio / video / PDF\npilot + fl_2dca"),
    (400, 60, 680, 190, "TRANSCRIBE", "faster-whisper\n+ existing SRT"),
    (720, 60, 1000, 190, "VERIFY", "Caption cross-check\nscore 0-100"),
    (1040, 60, 1320, 190, "ECHOSCRIPT", "diarize.py\naudio emotion"),
    (180, 260, 460, 390, "VIBEVIZ", "analyze_signals.py\nblendshape mood"),
    (500, 260, 780, 390, "ROBOTICS-ER", "posture / gaze note\n(wide shots)"),
    (820, 260, 1100, 390, "MERGE", "merge_signals.py\ntimeline.json"),
    (1140, 260, 1320, 390, "VERIFIER", "four-gate citations\nGRINDER grounding"),
    (430, 480, 750, 610, "KINGSFIELD", "Council + Wingman\npro se routes"),
    (830, 480, 1150, 610, "PREDICT", "judge timelines\n→ case_predictions"),
]

ARROWS = [
    ((360, 125), (400, 125)),
    ((680, 125), (720, 125)),
    ((1000, 125), (1040, 125)),
    ((1180, 190), (1180, 260)),
    ((220, 190), (220, 260)),
    ((640, 325), (820, 325)),
    ((960, 325), (1140, 325)),
    ((1230, 390), (990, 480)),
    ((750, 390), (590, 480)),
    ((750, 545), (830, 545)),
]


def main():
    img = Image.new("RGB", (W, H), "#0f1419")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 18)
        small = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 14)
        title_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 28)
    except OSError:
        font = ImageFont.load_default()
        small = font
        title_font = font

    draw.text((80, 16), "Judicial Intel Pipeline — Uploader → Analytics → Kingsfield", fill="#e2e8f0", font=title_font)

    for x1, y1, x2, y2, title, body in BOXES:
        draw.rounded_rectangle([x1, y1, x2, y2], radius=12, fill="#1e293b", outline="#38bdf8", width=2)
        draw.text((x1 + 14, y1 + 12), title, fill="#7dd3fc", font=font)
        draw.multiline_text((x1 + 14, y1 + 40), body, fill="#cbd5e1", font=small, spacing=4)

    for a, b in ARROWS:
        draw.line([a, b], fill="#64748b", width=3)
        dx, dy = b[0] - a[0], b[1] - a[1]
        if abs(dx) >= abs(dy):
            tip = (b[0] - 10 if dx > 0 else b[0] + 10, b[1])
        else:
            tip = (b[0], b[1] - 10 if dy > 0 else b[1] + 10)
        draw.polygon([b, (tip[0] - 6, tip[1] - 6), (tip[0] + 6, tip[1] + 6)], fill="#64748b")

    draw.text((80, 820), "EchoScript = #1 judicial integration | VibeViz = visual mood | Face mood in Wingman :3002", fill="#94a3b8", font=small)
    img.save(OUT)
    print(OUT)


if __name__ == "__main__":
    main()