#!/usr/bin/env python3
"""Refuse MCP connector calls whose arguments carry an unverified cite."""
from pathlib import Path

path = Path("backend/src/lib/chatTools.ts")
text = path.read_text()
marker = "mcp arguments withheld before connector egress"
if marker in text:
    print("already patched")
    raise SystemExit(0)
needle = "      const { content, event } = await executeMcpToolCall("
idx = text.find(needle)
if idx < 0:
    raise SystemExit("executeMcpToolCall not found")
insert = (
    "      // mcp arguments withheld before connector egress\n"
    "      const mcpText = JSON.stringify(args ?? {});\n"
    "      if (!(await gateDocWriteText([mcpText], db))) {\n"
    "        toolResults.push({\n"
    "          role: \"tool\",\n"
    "          tool_call_id: tc.id,\n"
    "          content: JSON.stringify({ ok: false, error: DOC_WRITE_REFUSED_MESSAGE }),\n"
    "        });\n"
    "        continue;\n"
    "      }\n"
)
path.write_text(text[:idx] + insert + text[idx:])
print("patched", path)
