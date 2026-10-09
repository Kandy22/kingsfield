#!/usr/bin/env python3
"""Gate generate_docx sections in renderer order.

The page is heading, then table, then content. JSON key order can put content
first, so a cite split across a table header and the body was joined backwards
and released. Also join each table column top to bottom.
"""
from pathlib import Path

path = Path("backend/src/lib/chatTools.ts")
text = path.read_text()
marker = "renderer order: heading, table, content"
if marker in text:
    print("already patched")
    raise SystemExit(0)
old = '''    if (typeof heading === "string") parts.push(heading.toUpperCase());
    if (table && typeof table === "object") {
      const { headers, rows } = table as { headers?: unknown; rows?: unknown };
      const across = (cells: unknown) => {
        if (!Array.isArray(cells)) return;
        const strs = cells.filter((c): c is string => typeof c === "string");
        if (strs.length > 1) parts.push(strs.join(" "));
      };
      across(headers);
      if (Array.isArray(rows)) for (const row of rows) across(row);
    }
  }
  return parts;
}'''
new = '''    if (typeof heading === "string") parts.push(heading.toUpperCase());
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
    // renderer order: heading, table, content. JSON key order is not page order.
    parts.push([headingText, tableHead, contentText].filter(Boolean).join("\n\n"));
  }
  return parts;
}'''
if old not in text:
    raise SystemExit("gate parts loop not found")
path.write_text(text.replace(old, new, 1))
print("patched", path)
