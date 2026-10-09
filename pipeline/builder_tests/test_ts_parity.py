"""Python reference gate vs TypeScript gate, same fixture DB, same inputs."""

import json
import subprocess
import unittest
from pathlib import Path

from _fixture import REPO_ROOT, build_fixture_db
from _cases import CASES, fuzz_cases
from pipeline.gate1 import check_citation

TS = REPO_ROOT / "backend" / "src" / "verification" / "local_sqlite_gate.ts"

RUNNER = """
import fs from 'node:fs';
const m = await import(%r);
const { cites, dbPath, force } = JSON.parse(fs.readFileSync(0, 'utf8'));
const out = cites.map((c) => { const r = m.localGate1(c, { dbPath, forcePythonFallback: force }); return r; });
process.stdout.write(JSON.stringify(out));
"""


def run_ts(cites, db, force=False):
    p = subprocess.run(
        ["node", "--no-warnings", "--input-type=module", "-e", RUNNER % TS.as_uri()],
        input=json.dumps({"cites": cites, "dbPath": str(db), "force": force}),
        capture_output=True, text=True, timeout=300, cwd=str(REPO_ROOT),
    )
    if p.returncode != 0:
        raise AssertionError(p.stderr)
    return json.loads(p.stdout)


def py_view(r):
    return (r.verdict, r.reason, r.reporter, r.volume, r.page, r.cluster_id)


def ts_view(r):
    return (r["verdict"], r["reason"], r.get("reporter"), r.get("volume"), r.get("page"), r.get("clusterId"))


class ParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp, cls.db, _ = build_fixture_db()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def compare(self, cites, force=False):
        ts = run_ts(cites, self.db, force)
        self.assertEqual(len(ts), len(cites))
        for c, t in zip(cites, ts):
            with self.subTest(cite=c[:90]):
                self.assertEqual(ts_view(t), py_view(check_citation(c, self.db)))

    def test_table_cases(self):
        self.compare([c for c, _, _ in CASES])

    def test_table_expectations_hold_in_ts(self):
        ts = run_ts([c for c, _, _ in CASES], self.db)
        for (c, verdict, reason), t in zip(CASES, ts):
            with self.subTest(cite=c[:90]):
                self.assertEqual(t["verdict"], verdict)
                if reason is not None:
                    self.assertEqual(t["reason"], reason)

    def test_fuzz(self):
        self.compare(fuzz_cases(400))

    def test_python_child_process_fallback(self):
        cases = [c for c, _, _ in CASES[:40]] + fuzz_cases(10, seed=7)
        ts = run_ts(cases, self.db, force=True)
        for c, t in zip(cases, ts):
            with self.subTest(cite=c[:90]):
                self.assertEqual(ts_view(t), py_view(check_citation(c, self.db)))

    def test_missing_db_vetoes_in_ts(self):
        ts = run_ts(["123 So. 3d 456 (Fla. 2013)"], Path(self.tmp.name) / "nope.db")
        self.assertEqual((ts[0]["verdict"], ts[0]["reason"]), ("veto", "db_unavailable"))
        self.assertFalse((Path(self.tmp.name) / "nope.db").exists())

    def test_missing_db_vetoes_in_ts_fallback(self):
        ts = run_ts(["123 So. 3d 456 (Fla. 2013)"], Path(self.tmp.name) / "nope.db", force=True)
        self.assertEqual(ts[0]["verdict"], "veto")

    def test_fall_through_in_ts_needs_no_db(self):
        ts = run_ts(["123 F.3d 456 (11th Cir. 1999)"], Path(self.tmp.name) / "nope.db")
        self.assertEqual(ts[0]["verdict"], "fall_through")

    def test_ts_never_throws_on_non_string(self):
        p = subprocess.run(
            ["node", "--no-warnings", "--input-type=module", "-e",
             f"const m = await import({TS.as_uri()!r}); process.stdout.write(JSON.stringify([m.localGate1(null), m.localGate1(5), m.localGate1(undefined)]));"],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual([r["verdict"] for r in json.loads(p.stdout)], ["veto"] * 3)


if __name__ == "__main__":
    unittest.main()
