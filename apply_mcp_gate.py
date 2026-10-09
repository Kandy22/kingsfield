#!/usr/bin/env python3
"""Refuse MCP connector calls whose arguments carry an unverified cite."""
from pathlib import Path

path = Path("backend/src/lib/chatTools.ts")
text = path.read_text()
marker = "mcp arguments withheld before connector egress"
if marker in text:
    print("already patched")
    raise SystemExit(0)
old = '''    if (tc.function.name.startsWith("mcp_")) {
      write(
        `data: ${JSON.stringify({
          type: "mcp_tool_start",
          name: tc.function.name,
        })}\\n\\n`,
      );
      const { content, event } = await executeMcpToolCall(
        userId,
        tc.function.name,
        args,
        db,
      );
'''
new = '''    if (tc.function.name.startsWith("mcp_")) {
      // mcp arguments withheld before connector egress
      const mcpText = JSON.stringify(args ?? {});
      if (!(await gateDocWriteText([mcpText], db))) {
        toolResults.push({
          role: "tool",
          tool_call_id: tc.id,
          content: JSON.stringify({ ok: false, error: DOC_WRITE_REFUSED_MESSAGE }),
        });
        continue;
      }
      write(
        `data: ${JSON.stringify({
          type: "mcp_tool_start",
          name: tc.function.name,
        })}\\n\\n`,
      );
      const { content, event } = await executeMcpToolCall(
        userId,
        tc.function.name,
        args,
        db,
      );
'''
if old not in text:
    raise SystemExit("mcp dispatch block not found")
path.write_text(text.replace(old, new, 1))
print("patched", path)
