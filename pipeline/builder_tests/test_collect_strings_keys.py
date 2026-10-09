"""collectStrings (routes/index.ts, used by GET /analytics and POST /analytics/extract) also gates object KEYS."""

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

INDEX = Path(__file__).resolve().parent.parent.parent / "backend" / "src" / "routes" / "index.ts"


def _function_source():
    src = INDEX.read_text(encoding="utf-8")
    m = re.search(r"function collectStrings\(.*?\n}\n", src, re.S)
    assert m, "collectStrings not found"
    body = m.group(0)
    body = body.replace("function collectStrings(value: unknown, out: string[], depth = 0): boolean {",
                        "function collectStrings(value, out, depth = 0) {")
    body = body.replace("([key, item])", "([key, item])").replace("value as Record<string, unknown>", "value")
    return body


def _run(value):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node missing")
    js = _function_source() + "\nconst out=[];const ok=collectStrings(JSON.parse(process.argv[1]),out);" \
        "console.log(JSON.stringify({ok,out}));"
    p = subprocess.run([node, "-e", js, json.dumps(value)], capture_output=True, text=True, timeout=30)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


class CollectStringsKeys(unittest.TestCase):
    def test_keys_are_collected(self):
        cite = "Doe v. Roe, 999 So. 3d 999 (Fla. 2015)"
        got = _run({"entities": {cite: 1}, "rarity": [{cite + " b": "x"}]})
        self.assertTrue(got["ok"])
        self.assertIn(cite, got["out"])
        self.assertIn(cite + " b", got["out"])
        self.assertIn("x", got["out"])

    def test_values_still_collected_and_depth_fails_closed(self):
        self.assertEqual(_run({"a": "v"})["out"], ["a", "v"])
        deep = cur = {}
        for _ in range(15):
            cur["k"] = {}
            cur = cur["k"]
        self.assertFalse(_run(deep)["ok"])

    def test_many_keys_fail_closed(self):
        self.assertFalse(_run({f"k{i}": 1 for i in range(20_001)})["ok"])


if __name__ == "__main__":
    unittest.main()
