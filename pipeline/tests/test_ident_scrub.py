"""The identifier allowlist of the live SSE events (hallucination_guard.ts: SSE_IDENT, JAMMED_CITE, isSafeIdent) against Gate 1.

A tool name (tool_call_start / mcp_tool_start), a cluster id or a count goes to the browser BEFORE Gate 1 has run, when it matches
SSE_IDENT and is not a jammed citation. An MCP server chooses its own tool names, so a name that Gate 1 itself reads as a
citation must never pass isSafeIdent. The regexes are read from the TypeScript source (no copy to drift), and every form the real
gate reads as a citation (a veto, a pass or a fall-through) must be rejected by the allowlist.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate1_fixture as fx  # noqa: E402

GUARD = fx.REPO / "backend" / "src" / "middleware" / "hallucination_guard.ts"


def _js_regex(src, name):
    m = re.search(r"const %s = /(.+)/([a-z]*);" % name, src)
    assert m, "cannot find %s in hallucination_guard.ts" % name
    flags = re.I if "i" in m.group(2) else 0
    return re.compile(m.group(1), flags)


class IdentAllowlistVersusGate1(unittest.TestCase):
    FORMS = (
        "999So.3d999", "999so3d999", "999So.2d999", "999So3d999",
        "999-So.3d-999", "999_So.3d_999", "999:So.3d:999", "999.So.3d.999", "999-So-3d-999", "999_So_3d_999",
        "999So.3d-999", "999-So.3d999", "999So.3d_999",
        "Doe_v_Roe_999_So.3d_999", "Doe-v-Roe-999-So.3d-999", "Doe_v._Roe_999_So._3d_999",
        "mcp_999_So.3d_999_search", "999So.3d999a",
    )

    @classmethod
    def setUpClass(cls):
        src = GUARD.read_text(encoding="utf-8")
        cls.ident = _js_regex(src, "SSE_IDENT")
        cls.jammed = _js_regex(src, "JAMMED_CITE")
        cls.db = fx.get_fixture().db

    def safe(self, value):
        return bool(self.ident.search(value)) and not self.jammed.search(value)

    def test_a_name_that_gate_1_reads_as_a_citation_never_passes_the_live_allowlist(self):
        leaks = []
        for form in self.FORMS:
            read = fx.py_check_text(form, self.db)
            if read and self.safe(form):
                leaks.append("%r is sent live as an identifier but Gate 1 reads it as %r"
                             % (form, [(r.verdict, r.reason) for r in read]))
        if leaks:
            self.fail("%d forms; first: %s" % (len(leaks), leaks[0]))

    def test_the_allowlist_still_accepts_ordinary_tool_names_and_ids(self):
        for ok in ("mcp_drive_create_file", "courtlistener_search_case_law", "doc-0", "9f1c2d3e-0000-4000-8000-000000000000", "123456"):
            with self.subTest(value=ok):
                self.assertTrue(self.safe(ok), ok)


if __name__ == "__main__":
    unittest.main()
