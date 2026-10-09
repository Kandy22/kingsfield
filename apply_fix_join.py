#!/usr/bin/env python3
"""The last patch wrote a real line break inside a TypeScript string. Repair it."""
import json
from pathlib import Path

path = Path("backend/src/lib/chatTools.ts")
text = path.read_text()
start = text.find("parts.push([headingText, tableHead, contentText]")
if start < 0:
    raise SystemExit("render-order push not found")
end = text.find(");", start)
if end < 0:
    raise SystemExit("end of push not found")
end += 2
good = "parts.push([headingText, tableHead, contentText].filter(Boolean).join(" + json.dumps("\n\n") + ")"
path.write_text(text[:start] + good + text[end:])
print("repaired", path)
