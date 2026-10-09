#!/usr/bin/env python3
"""Apply the Part B document-write gate fix to chatTools.ts. Idempotent."""
from pathlib import Path

path = Path("backend/src/lib/chatTools.ts")
text = path.read_text()

helper = '''function floridaPeriodRestored(text: string): string {
  return text
    .replace(/\\bSo 2d\\b/g, "So. 2d")
    .replace(/\\bSo 3d\\b/g, "So. 3d")
    .replace(/\\bSo (\\d)/g, "So. $1");
}

'''
anchor = "function generatedDocxFilename(title: string): string {"
if "function floridaPeriodRestored" not in text:
    if anchor not in text:
        raise SystemExit("generatedDocxFilename not found")
    text = text.replace(anchor, helper + anchor, 1)

old_parts = "const parts: string[] = [title, title.toUpperCase(), generatedDocxFilename(title)];"
new_parts = """const parts: string[] = [
    title,
    title.toUpperCase(),
    generatedDocxFilename(title),
    floridaPeriodRestored(title),
    floridaPeriodRestored(generatedDocxFilename(title)),
  ];"""
if old_parts in text:
    text = text.replace(old_parts, new_parts, 1)
elif "floridaPeriodRestored(title)" not in text:
    raise SystemExit("gate parts line not found")

old_edit = '} = await applyTrackedEdits(current.bytes, edits, { author: "Kingsfield" });\n\n  if (changes.length === 0) {'
new_edit = '''} = await applyTrackedEdits(current.bytes, edits, { author: "Kingsfield" });

  const editedText = await extractDocxBodyText(editedBytes);
  if (!(await gateDocWriteText([editedText, versionFilename], db))) {
    return { ok: false, error: DOC_WRITE_REFUSED_MESSAGE };
  }

  if (changes.length === 0) {'''
if "const editedText = await extractDocxBodyText(editedBytes);" not in text:
    if old_edit not in text:
        raise SystemExit("applyTrackedEdits site not found")
    text = text.replace(old_edit, new_edit, 1)

path.write_text(text)
print("patched", path)
