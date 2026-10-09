#!/usr/bin/env python3
import re
from pathlib import Path

openai = Path("backend/src/lib/llm/openai.ts")
text = openai.read_text()
old = """  maxTokens?: number;
  apiKeys?: { openai?: string | null };
}): Promise<string> {
  const response = await createResponse({
    model: params.model,
    instructions: params.systemPrompt,
    input: [{ role: "user", content: params.user }],
    maxTokens: params.maxTokens ?? 512,
    apiKey: apiKey(params.apiKeys?.openai),
  });
"""
new = """  maxTokens?: number;
  apiKeys?: { openai?: string | null };
  signal?: AbortSignal;
}): Promise<string> {
  throwIfAborted(params.signal);
  const response = await createResponse({
    model: params.model,
    instructions: params.systemPrompt,
    input: [{ role: "user", content: params.user }],
    maxTokens: params.maxTokens ?? 512,
    apiKey: apiKey(params.apiKeys?.openai),
    signal: params.signal,
  });
"""
if "signal: params.signal" not in text.split("completeOpenAIText")[-1]:
    if old not in text:
        raise SystemExit("openai complete missing")
    openai.write_text(text.replace(old, new, 1))
    print("patched", openai)
else:
    print("openai already passes signal")

root = Path("backend/src/crew")
for path in root.rglob("*.ts"):
    if path.name in {"coordinator.ts", "researcher.ts"}:
        continue
    body = path.read_text()
    if "completeText(" not in body or "signal: signal" in body:
        continue
    body = body.replace(
        "export async function run",
        "export async function run",
    )
    body = re.sub(
        r"(export async function run\w+\([\s\S]*?model: string)",
        r"\1, signal?: AbortSignal",
        body,
        count=1,
    )
    body = body.replace("await completeText({\n    model,", "await completeText({\n    model,\n    signal,")
    body = body.replace("await completeText({\n      model,", "await completeText({\n      model,\n      signal,")
    path.write_text(body)
    print("patched", path)

coord = Path("backend/src/crew/coordinator.ts")
ct = coord.read_text()
ct2 = ct.replace(", deps.model)", ", deps.model, deps.signal)")
ct2 = ct2.replace(", deps.model,\n    );", ", deps.model,\n      deps.signal,\n    );")
if ct2 == ct:
    print("coordinator call sites unchanged")
else:
    coord.write_text(ct2)
    print("patched", coord)
