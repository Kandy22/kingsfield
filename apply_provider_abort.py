#!/usr/bin/env python3
from pathlib import Path

claude = Path("backend/src/lib/llm/claude.ts")
text = claude.read_text()
old = """  maxTokens?: number;
  apiKeys?: { claude?: string | null };
}): Promise<string> {
  const anthropic = client(params.apiKeys?.claude);
"""
new = """  maxTokens?: number;
  apiKeys?: { claude?: string | null };
  signal?: AbortSignal;
}): Promise<string> {
  throwIfAborted(params.signal);
  const anthropic = client(params.apiKeys?.claude);
"""
if "signal?: AbortSignal" not in text.split("completeClaudeText")[-1]:
    if old not in text:
        raise SystemExit("claude complete missing")
    text = text.replace(old, new, 1)
old = """    resp = await anthropic.messages.create({
      model: params.model,
      max_tokens: params.maxTokens ?? 512,
      system: params.systemPrompt,
      messages: [{ role: "user", content: params.user }],
    });
"""
new = """    resp = await anthropic.messages.create({
      model: params.model,
      max_tokens: params.maxTokens ?? 512,
      system: params.systemPrompt,
      messages: [{ role: "user", content: params.user }],
    }, { signal: params.signal });
"""
if "signal: params.signal" not in text:
    if old not in text:
        raise SystemExit("claude create missing")
    text = text.replace(old, new, 1)
claude.write_text(text)
print("patched", claude)

researcher = Path("backend/src/crew/researcher.ts")
rt = researcher.read_text()
if "signal?: AbortSignal" not in rt:
    old = "courtListenerToken: string;\n"
    new = "courtListenerToken: string;\n  signal?: AbortSignal;\n"
    if old not in rt:
        raise SystemExit("ResearcherDeps missing")
    rt = rt.replace(old, new, 1)
old = "model: deps.model,\n"
new = "model: deps.model,\n    signal: deps.signal,\n"
if rt.count("signal: deps.signal") < 2:
    rt = rt.replace(old, new)
researcher.write_text(rt)
print("patched", researcher)

coord = Path("backend/src/crew/coordinator.ts")
ct = coord.read_text()
old = "courtListenerToken: deps.courtListenerToken }"
new = "courtListenerToken: deps.courtListenerToken, signal: deps.signal }"
if "signal: deps.signal" not in ct:
    if old not in ct:
        raise SystemExit("researcher deps call missing")
    coord.write_text(ct.replace(old, new))
    print("patched", coord)
else:
    print("coordinator already passes signal")
