"""Builder test: the live-event identifier allowlist rejects separator-jammed Southern Reporter forms."""

import re
import unittest
from pathlib import Path

GUARD = Path(__file__).resolve().parents[2] / "backend" / "src" / "middleware" / "hallucination_guard.ts"


def _rx(src, name):
    m = re.search(r"const %s = /(.+)/([a-z]*);" % name, src)
    assert m, name
    return re.compile(m.group(1), re.I if "i" in m.group(2) else 0)


class IdentAllowlist(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        src = GUARD.read_text(encoding="utf-8")
        cls.ident = _rx(src, "SSE_IDENT")
        cls.jammed = _rx(src, "JAMMED_CITE")

    def safe(self, v):
        return bool(self.ident.search(v)) and not self.jammed.search(v)

    def test_rejects_jammed_forms(self):
        for v in ("999So.3d999", "999_So.3d_999", "999So.3d-999", "Doe_v_Roe_999_So.3d_999",
                  "mcp_999_So.3d_999_search", "999-So-3d-999", "Doe_v._Roe_999_So._3d_999"):
            self.assertFalse(self.safe(v), v)

    def test_accepts_ordinary_names(self):
        for v in ("mcp_drive_create_file", "courtlistener_search_case_law", "doc-0", "123456",
                  "9f1c2d3e-0000-4000-8000-000000000000"):
            self.assertTrue(self.safe(v), v)


if __name__ == "__main__":
    unittest.main()
