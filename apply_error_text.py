#!/usr/bin/env python3
from pathlib import Path
path = Path("frontend/src/app/components/assistant/AssistantMessage.tsx")
text = path.read_text()
if "failed-reply-text" in text:
    print("already patched")
    raise SystemExit(0)
old = """            <ResponseStatus status={status} />
            <div className="w-full font-inter relative mt-2">
"""
new = """            <ResponseStatus status={status} />
            {effectiveErrorMessage && !events?.some((event) => event.type === "content") && (
                <p className="failed-reply-text mb-2 text-sm font-sans text-gray-700 dark:text-paper">
                    {effectiveErrorMessage}
                </p>
            )}
            <div className="w-full font-inter relative mt-2">
"""
if old not in text:
    raise SystemExit("status block missing")
path.write_text(text.replace(old, new, 1))
print("patched", path)
