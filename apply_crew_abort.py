#!/usr/bin/env python3
"""Skip the crew fallback and the send after the client disconnects."""
from pathlib import Path

path = Path("backend/src/routes/index.ts")
text = path.read_text()
if "crewAbort" in text:
    print("already patched")
    raise SystemExit(0)
old = "    const keepalive = startSseKeepalive(write);\n    res.on('close', () => keepalive.stop());\n"
new = """    const keepalive = startSseKeepalive(write);
    const crewAbort = new AbortController();
    res.on('close', () => {
      keepalive.stop();
      crewAbort.abort();
    });
"""
if old not in text:
    raise SystemExit("keepalive site missing")
text = text.replace(old, new, 1)
old = "        const out = await runCrew(\n"
new = "        if (crewAbort.signal.aborted) return;\n        const out = await runCrew(\n"
if old not in text:
    raise SystemExit("runCrew site missing")
text = text.replace(old, new, 1)
old = "        reply = out.reply;\n\n        // If the Coordinator decided to skip the crew, produce a simple answer.\n        if (!reply) {\n"
new = "        if (crewAbort.signal.aborted) return;\n        reply = out.reply;\n\n        // If the Coordinator decided to skip the crew, produce a simple answer.\n        if (!reply) {\n          if (crewAbort.signal.aborted) return;\n"
if old not in text:
    raise SystemExit("fallback site missing")
path.write_text(text.replace(old, new, 1))
print("patched", path)
