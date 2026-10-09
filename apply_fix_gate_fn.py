#!/usr/bin/env python3
"""Replace generatedDocxGateParts. The prior patch left a broken join."""
import json
from pathlib import Path

path = Path("backend/src/lib/chatTools.ts")
text = path.read_text()
start = text.find("function generatedDocxGateParts(")
end = text.find("function editDocumentGateParts(")
if start < 0 or end < 0 or end < start:
    raise SystemExit("function bounds not found")
join = json.dumps("\n\n")
fn = '''function generatedDocxGateParts(
  title: unknown,
  sections: unknown,
): string[] | null {
  if (typeof title !== "string" || !Array.isArray(sections)) return null;
  const parts: string[] = [
    title,
    title.toUpperCase(),
    generatedDocxFilename(title),
    floridaPeriodRestored(title),
    floridaPeriodRestored(generatedDocxFilename(title)),
  ];
  if (!collectModelStrings(sections, parts)) return null;
  for (const section of sections) {
    if (!section || typeof section !== "object") continue;
    const { heading, table } = section as { heading?: unknown; table?: unknown };
    if (typeof heading === "string") parts.push(heading.toUpperCase());
    const content = (section as { content?: unknown }).content;
    const headingText = typeof heading === "string" ? heading : "";
    const contentText = typeof content === "string" ? content : "";
    let tableHead = "";
    if (table && typeof table === "object") {
      const { headers, rows } = table as { headers?: unknown; rows?: unknown };
      const across = (cells: unknown) => {
        if (!Array.isArray(cells)) return;
        const strs = cells.filter((c): c is string => typeof c === "string");
        if (strs.length > 1) parts.push(strs.join(" "));
      };
      across(headers);
      if (Array.isArray(rows)) for (const row of rows) across(row);
      if (Array.isArray(headers)) {
        tableHead = headers.filter((c): c is string => typeof c === "string").join(" ");
      }
      const columns: string[][] = [];
      const addColumn = (cells: unknown) => {
        if (!Array.isArray(cells)) return;
        cells.forEach((cell, index) => {
          if (typeof cell !== "string") return;
          columns[index] = columns[index] ?? [];
          columns[index].push(cell);
        });
      };
      addColumn(headers);
      if (Array.isArray(rows)) for (const row of rows) addColumn(row);
      for (const column of columns) parts.push(column.join(" "));
    }
    parts.push([headingText, tableHead, contentText].filter(Boolean).join(JOIN));
  }
  return parts;
}

'''
fn = fn.replace("JOIN", join)
path.write_text(text[:start] + fn + text[end:])
print("replaced generatedDocxGateParts")
