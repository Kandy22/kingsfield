#!/usr/bin/env python3
"""A jammed cite like 999So.3d999 is not an identifier."""
from pathlib import Path

path = Path("backend/src/middleware/hallucination_guard.ts")
text = path.read_text()
if "JAMMED_CITE" in text:
    print("already patched")
    raise SystemExit(0)
old = "const SSE_IDENT = /^[A-Za-z0-9_.:-]{1,64}$/;\nconst isIdent = (v: unknown) => typeof v === 'string' && SSE_IDENT.test(v);\n"
new = """const SSE_IDENT = /^[A-Za-z0-9_.:-]{1,64}$/;
const JAMMED_CITE = /\\d{1,4}so\\.?[23]d\\d{1,6}/i;
const isSafeIdent = (v: string) => SSE_IDENT.test(v) && !JAMMED_CITE.test(v);
const isIdent = (v: unknown) => typeof v === 'string' && isSafeIdent(v);
"""
if old not in text:
    raise SystemExit("ident lines missing")
text = text.replace(old, new, 1)
old = "else if (typeof v === 'string' && SSE_IDENT.test(v)) out[k] = v;"
new = "else if (typeof v === 'string' && isSafeIdent(v)) out[k] = v;"
if old not in text:
    raise SystemExit("scrub line missing")
path.write_text(text.replace(old, new, 1))
print("patched", path)
