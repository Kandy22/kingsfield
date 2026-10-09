#!/usr/bin/env python3
"""Abort the crew route when the client closes the socket.

This stops the single-agent fallback and skips the send. A model call already
in flight still finishes; specialists do not yet take the signal.
"""
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
old = "      const out = await runCrew(\n"
new = "      if (crewAbort.signal.aborted) return;\n      const out = await runCrew(\n"
if old not in text:
    raise SystemExit("runCrew site missing")
text = text.replace(old, new, 1)
# pass signal as third-to-last by extending the deps object if present
old = "          courtListenerToken: deps.courtListenerToken,\n        },\n      );"
new = "          courtListenerToken: deps.courtListenerToken,\n          signal: crewAbort.signal,\n        },\n      );\n      if (crewAbort.signal.aborted) return;"
if old not in text:
    raise SystemExit("crew deps missing")
text = text.replace(old, new, 1)
old = "      if (!reply) {\n        const { completeText } = await import('../lib/llm/index.js');\n"
new = "      if (!reply) {\n        if (crewAbort.signal.aborted) return;\n        const { completeText } = await import('../lib/llm/index.js');\n"
if old not in text:
    raise SystemExit("fallback site missing")
text = text.replace(old, new, 1)
path.write_text(text)
print("patched", path)
