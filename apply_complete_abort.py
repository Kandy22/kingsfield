#!/usr/bin/env python3
from pathlib import Path

llm = Path("backend/src/lib/llm/index.ts")
text = llm.read_text()
old = """    maxTokens?: number;
    apiKeys?: UserApiKeys;
}): Promise<string> {"""
new = """    maxTokens?: number;
    apiKeys?: UserApiKeys;
    signal?: AbortSignal;
}): Promise<string> {"""
if "signal?: AbortSignal" not in text:
    if old not in text:
        raise SystemExit("completeText params missing")
    llm.write_text(text.replace(old, new, 1))
    print("patched", llm)
else:
    print("completeText already accepts signal")

gem = Path("backend/src/lib/llm/gemini.ts")
g = gem.read_text()
old = """  apiKeys?: { gemini?: string | null };
}): Promise<string> {
  const ai = client(params.apiKeys?.gemini);
"""
new = """  apiKeys?: { gemini?: string | null };
  signal?: AbortSignal;
}): Promise<string> {
  throwIfAborted(params.signal);
  const ai = client(params.apiKeys?.gemini);
"""
if "signal?: AbortSignal" not in g.split("completeGeminiText")[-1]:
    if old not in g:
        raise SystemExit("gemini complete missing")
    g = g.replace(old, new, 1)
old = """      config: params.systemPrompt
        ? { systemInstruction: params.systemPrompt }
        : undefined,
"""
new = """      config: {
        ...(params.systemPrompt ? { systemInstruction: params.systemPrompt } : {}),
        abortSignal: params.signal,
      },
"""
if "abortSignal: params.signal" not in g:
    if old not in g:
        raise SystemExit("gemini config missing")
    g = g.replace(old, new, 1)
gem.write_text(g)
print("patched", gem)

route = Path("backend/src/routes/index.ts")
rt = route.read_text()
old = """          reply = await completeText({
            model,
            systemPrompt: 'You are Kingsfield, a plain-English legal AI. Answer concisely.',
            user: userMessage ?? '',
            maxTokens: 1024,
          });
"""
new = """          reply = await completeText({
            model,
            systemPrompt: 'You are Kingsfield, a plain-English legal AI. Answer concisely.',
            user: userMessage ?? '',
            maxTokens: 1024,
            signal: crewAbort.signal,
          });
"""
if "signal: crewAbort.signal" not in rt.split("completeText")[-1]:
    if old not in rt:
        raise SystemExit("fallback completeText missing")
    route.write_text(rt.replace(old, new, 1))
    print("patched", route)
else:
    print("fallback already passes signal")
