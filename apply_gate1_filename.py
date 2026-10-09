#!/usr/bin/env python3
"""Teach Gate 1 to treat stored-filename Florida cites as local keys.

Filename storage strips periods and parentheses, so
'Smith v. State, 100 So. 3d 200 (Fla. 2012)' becomes
'Smith v State 100 So 3d 200 Fla 2012.docx'. The grammar then returns
fall_through/not_florida_key. Restore the Southern reporter period and the
Florida court parentheses inside normalize(), in both the Python reference
and the TypeScript mirror.
"""
from pathlib import Path

PY_OLD = '''def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = _WS_RUN.sub(" ", s)
    return _WS_EDGE.sub("", s)
'''
PY_NEW = '''def _restore_filename_cite(s: str) -> str:
    s = re.sub(r"(?i)\\bSo 2d\\b", "So. 2d", s)
    s = re.sub(r"(?i)\\bSo 3d\\b", "So. 3d", s)
    s = re.sub(r"(?i)\\bSo (\\d)", r"So. \\1", s)
    s = re.sub(r"(?i)\\bFla (\\d{4})\\b", r"(Fla. \\1)", s)
    return s


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = _WS_RUN.sub(" ", s)
    s = _WS_EDGE.sub("", s)
    return _restore_filename_cite(s)
'''
TS_OLD = '''function normalize(s: string): string {
  return s.normalize('NFKC').replace(WS_RUN, ' ').replace(WS_EDGE, '');
}
'''
TS_NEW = '''function restoreFilenameCite(s: string): string {
  return s
    .replace(/\\bSo 2d\\b/gi, "So. 2d")
    .replace(/\\bSo 3d\\b/gi, "So. 3d")
    .replace(/\\bSo (\\d)/gi, "So. $1")
    .replace(/\\bFla (\\d{4})\\b/gi, "(Fla. $1)");
}

function normalize(s: string): string {
  return restoreFilenameCite(s.normalize('NFKC').replace(WS_RUN, ' ').replace(WS_EDGE, ''));
}
'''

def patch(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    if new in text:
        print("already patched", path)
        return
    if old not in text:
        raise SystemExit("pattern missing in " + path)
    file.write_text(text.replace(old, new, 1))
    print("patched", path)

patch("pipeline/gate1.py", PY_OLD, PY_NEW)
patch("backend/src/verification/local_sqlite_gate.ts", TS_OLD, TS_NEW)
