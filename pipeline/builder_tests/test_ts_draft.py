"""localGate1Text (async TS wrapper) against the Python reference, and every fail-closed path.

The wrapper has no parser of its own: equality with gate1.check_text is the whole contract. The
failure paths are exercised by sabotaging the Python child from the outside (a sitecustomize on
PYTHONPATH) so the real wrapper, real spawn, real timers and real JSON validation run.
"""

import json
import os
import subprocess
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from _fixture import REPO_ROOT
from _draft_fixture import build_draft_db
from pipeline.gate1 import check_text

TS = REPO_ROOT / "backend" / "src" / "verification" / "local_sqlite_gate.ts"

RUNNER = """
import fs from 'node:fs';
const m = await import(process.env.GATE_URL);
const { drafts, dbPath, opts, concurrent } = JSON.parse(fs.readFileSync(0, 'utf8'));
const unhandled = [];
process.on('unhandledRejection', (e) => unhandled.push('unhandledRejection: ' + String(e)));
process.on('uncaughtException', (e) => unhandled.push('uncaughtException: ' + String(e)));
const marker = { __undefined: true };
async function one(d) {
  const t0 = Date.now();
  let value = d;
  if (d && typeof d === 'object' && d.__js) value = eval(d.__js);
  try {
    const p = m.localGate1Text(value, Object.assign({ dbPath }, opts));
    const isPromise = !!p && typeof p.then === 'function';
    const results = await p;
    return { ok: true, isPromise, results, ms: Date.now() - t0 };
  } catch (e) {
    return { ok: false, error: String(e), ms: Date.now() - t0 };
  }
}
let items;
if (concurrent) items = await Promise.all(drafts.map(one));
else { items = []; for (const d of drafts) items.push(await one(d)); }
await new Promise((r) => setTimeout(r, 150));
process.stdout.write(JSON.stringify({ items, unhandled }));
"""


def run_ts(drafts, db, env=None, opts=None, concurrent=False, timeout=600):
    e = dict(os.environ)
    e["GATE_URL"] = TS.as_uri()
    e.update(env or {})
    p = subprocess.run(["node", "--no-warnings", "--input-type=module", "-e", RUNNER],
                       input=json.dumps({"drafts": drafts, "dbPath": str(db), "opts": opts or {}, "concurrent": concurrent}),
                       capture_output=True, text=True, env=e, timeout=timeout, cwd=str(REPO_ROOT))
    if p.returncode != 0:
        raise AssertionError(p.stderr)
    out = json.loads(p.stdout)
    assert out["unhandled"] == [], out["unhandled"]
    return out["items"]


def make_sabotage(code):
    """(env, tmpdir): `code` runs inside the Python child before gate1 does. KF_PIDFILE gets its pid."""
    tmp = tempfile.TemporaryDirectory()
    (Path(tmp.name) / "sitecustomize.py").write_text(
        "import os, sys, time\n" + textwrap.dedent(code) + "\n", encoding="utf-8")
    prior = os.environ.get("PYTHONPATH")
    env = {"PYTHONPATH": tmp.name + (os.pathsep + prior if prior else ""), "KF_PIDFILE": str(Path(tmp.name) / "pid")}
    return env, tmp


def ts_view(r):
    return (r["verdict"], r["reason"], r.get("reporter"), r.get("volume"), r.get("page"), r.get("clusterId"),
            r["kind"], r["text"], r["fullCitation"], r["start"], r["end"])


def py_view(r):
    return (r.verdict, r.reason, r.reporter, r.volume, r.page, r.cluster_id, r.kind, r.text, r.full_citation,
            r.start, r.end)


SJ = "Smith v. Jones, 123 So. 3d 456 (Fla. 2013). "
SS = "Smith v. State, 100 So. 3d 200 (Fla. 2012). "

DRAFTS = [
    "No citations here.",
    SJ + "Smith, 123 So. 3d at 461. Id. at 462. Smith, supra, at 463.",
    SJ + "*Id.* at 461. Id. at 999. Hernandez, 123 So. 3d at 461.",
    "*Hernandez v. Walmart Stores, Inc.*, 100 So. 3d 200 (Fla. 2012)",
    SS + "Hernandez, 100 So. 3d at 205. Smith, 100 So. 3d at 205. See Smith v. State, 100 So. 3d at 206.",
    "Ex parte Johnson, 100 So. 3d 555 (Ala. 2015). Smith, 100 So. 3d at 205. Johnson, 100 So. 3d at 205.",
    "Roe v. Wade, 410 U.S. 113 (1973). Id. at 150. See Fla. Stat. § 90.803 (2020). Id.",
    "As held, 999So. 3d 5 and ___ So. 3d ___ and lOO So. 3d 5 and 45 Fla. L. Weekly D___.",
    "Fabricated v. Case, 999&nbsp;So\\. 3d 5 (Fla. 2012) <b>and</b> 999 So<!-- x -->. 3d 5 (Fla. 2012)",
    "Café 中文 \U0001F600 Smith v. Jones, 123 So. 3d 456 (Fla. 2013). Id.",
    "Fake v. Case, 999 So. 3d 5 (Fla. 2012). Id. at 6.",
    "Id.",
    "Smith, 123 So. 3d at 461.",
]


class TsDraftParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp, cls.db = build_draft_db()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_equals_python_reference(self):
        items = run_ts(DRAFTS, self.db)
        for d, it in zip(DRAFTS, items):
            with self.subTest(draft=d[:70]):
                self.assertTrue(it["ok"], it)
                self.assertTrue(it["isPromise"])
                got = [ts_view(r) for r in it["results"]]
                want = [py_view(r) for r in check_text(d, self.db)]
                self.assertEqual(got, want)

    def test_empty_and_whitespace_resolve_to_empty_list(self):
        items = run_ts(["", "   ", "\n\t", "​", "<!-- -->"], self.db)
        for it in items:
            self.assertEqual((it["ok"], it["results"]), (True, []))

    def test_non_strings_and_too_long(self):
        drafts = [None, 5, {"__js": "undefined"}, {"__js": "({})"}, {"__js": "['a']"}, {"__js": "'x'.repeat(200001)"}]
        items = run_ts(drafts, self.db)
        for it in items[:5]:
            self.assertTrue(it["ok"], it)
            self.assertEqual([(r["verdict"], r["reason"], r["kind"]) for r in it["results"]],
                             [("veto", "unparseable", "unparsed")])
        self.assertEqual([(r["verdict"], r["reason"]) for r in items[5]["results"]], [("veto", "too_long")])

    def test_missing_db_vetoes_florida_and_passes_federal_through(self):
        nodb = Path(self.tmp.name) / "nope.db"
        items = run_ts([SJ + "Id. at 460.", "Roe v. Wade, 410 U.S. 113 (1973). Id. at 150."], nodb)
        self.assertTrue(all(r["verdict"] == "veto" for r in items[0]["results"]))
        self.assertEqual([r["verdict"] for r in items[1]["results"]], ["fall_through", "fall_through"])
        self.assertFalse(nodb.exists())

    def test_concurrent_calls_do_not_interfere(self):
        items = run_ts(DRAFTS * 3, self.db, concurrent=True)
        for d, it in zip(DRAFTS * 3, items):
            self.assertEqual([ts_view(r) for r in it["results"]], [py_view(r) for r in check_text(d, self.db)])

    def test_event_loop_stays_responsive(self):
        script = RUNNER.replace("await new Promise((r) => setTimeout(r, 150));",
                                "await new Promise((r) => setTimeout(r, 150)); unhandled.push('ticks:' + globalThis.__ticks);")
        script = script.replace("const marker", "globalThis.__ticks = 0; setInterval(() => { globalThis.__ticks++; }, 20).unref();\nconst marker")
        e = dict(os.environ)
        e["GATE_URL"] = TS.as_uri()
        p = subprocess.run(["node", "--no-warnings", "--input-type=module", "-e", script],
                           input=json.dumps({"drafts": [SJ * 40], "dbPath": str(self.db), "opts": {}}),
                           capture_output=True, text=True, env=e, timeout=300, cwd=str(REPO_ROOT))
        out = json.loads(p.stdout)
        ticks = int([u for u in out["unhandled"] if u.startswith("ticks:")][0].split(":")[1])
        self.assertGreater(out["items"][0]["ms"], 100)
        self.assertGreater(ticks, out["items"][0]["ms"] // 20 // 3)  # timers kept running during the call


class TsDraftFailClosed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp, cls.db = build_draft_db()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def one_veto(self, it, reason):
        self.assertTrue(it["ok"], it)
        r = it["results"]
        self.assertEqual(len(r), 1, r)
        self.assertEqual((r[0]["verdict"], r[0]["reason"], r[0]["kind"], r[0]["fullCitation"]),
                         ("veto", reason, "unparsed", None))
        self.assertEqual((r[0]["text"], r[0]["start"], r[0]["end"]), ("", 0, 0))

    def sabotaged(self, code, opts=None, draft=SJ + "Id. at 461."):
        env, tmp = make_sabotage(code)
        try:
            return run_ts([draft], self.db, env=env, opts=opts)[0], tmp
        finally:
            pass

    def test_child_exits_nonzero(self):
        it, tmp = self.sabotaged("os._exit(3)")
        self.one_veto(it, "python_text_failed")
        tmp.cleanup()

    def test_child_killed_by_signal(self):
        it, tmp = self.sabotaged("import signal; os.kill(os.getpid(), signal.SIGKILL)")
        self.one_veto(it, "python_text_failed")
        tmp.cleanup()

    def test_child_prints_garbage(self):
        it, tmp = self.sabotaged('sys.stdout.write("not json"); sys.stdout.flush(); os._exit(0)')
        self.one_veto(it, "python_text_bad_output")
        tmp.cleanup()

    def test_child_prints_nothing_and_exits_zero(self):
        it, tmp = self.sabotaged("os._exit(0)")
        self.one_veto(it, "python_text_bad_output")
        tmp.cleanup()

    def test_child_prints_wrong_shapes(self):
        bad = {
            "object": '{"verdict": "pass"}',
            "string": '"pass"',
            "null": "null",
            "bad_verdict": '[{"verdict":"ok","reason":"x","kind":"full","text":"","start":0,"end":0}]',
            "empty_reason": '[{"verdict":"veto","reason":"","kind":"full","text":"","start":0,"end":0}]',
            "bad_kind": '[{"verdict":"veto","reason":"x","kind":"weird","text":"","start":0,"end":0}]',
            "missing_text": '[{"verdict":"veto","reason":"x","kind":"full","start":0,"end":0}]',
            "bad_span": '[{"verdict":"veto","reason":"x","kind":"full","text":"","start":5,"end":2}]',
            "float_span": '[{"verdict":"veto","reason":"x","kind":"full","text":"","start":0.5,"end":2}]',
            "negative_span": '[{"verdict":"veto","reason":"x","kind":"full","text":"","start":-1,"end":2}]',
            "pass_without_cluster": '[{"verdict":"pass","reason":"verified","kind":"full","text":"x","start":0,"end":1,"full_citation":"x","cluster_id":null}]',
            "pass_without_full_citation": '[{"verdict":"pass","reason":"verified","kind":"full","text":"x","start":0,"end":1,"full_citation":null,"cluster_id":1}]',
            "fall_through_without_full_citation": '[{"verdict":"fall_through","reason":"not_florida_key","kind":"full","text":"x","start":0,"end":1,"full_citation":null}]',
            "string_volume": '[{"verdict":"veto","reason":"x","kind":"full","text":"","start":0,"end":0,"volume":"5"}]',
            "item_not_object": "[1]",
            "array_item": "[[]]",
        }
        for name, payload in bad.items():
            with self.subTest(name):
                it, tmp = self.sabotaged("sys.stdout.write(%r); sys.stdout.flush(); os._exit(0)" % payload)
                self.one_veto(it, "python_text_bad_output")
                tmp.cleanup()

    def test_valid_output_is_accepted(self):
        nulls = '"reporter":null,"volume":null,"page":null,"cluster_id":null'
        good = ('[{"verdict":"fall_through","reason":"non_case_antecedent","kind":"id","text":"Id.","start":0,"end":3,'
                '"full_citation":null,' + nulls + '},{"verdict":"veto","reason":"x","kind":"short","text":"a",'
                '"start":1,"end":2,"full_citation":null,' + nulls + '}]')
        it, tmp = self.sabotaged("sys.stdout.write(%r); sys.stdout.flush(); os._exit(0)" % good)
        self.assertEqual([(r["verdict"], r["reason"], r["fullCitation"]) for r in it["results"]],
                         [("fall_through", "non_case_antecedent", None), ("veto", "x", None)])
        tmp.cleanup()

    def test_timeout_kills_the_child_and_resolves_once(self):
        it, tmp = self.sabotaged(
            'open(os.environ["KF_PIDFILE"], "w").write(str(os.getpid()))\ntime.sleep(60)', opts={"textTimeoutMs": 700})
        self.one_veto(it, "python_text_failed")
        self.assertLess(it["ms"], 8000)
        self.assertGreaterEqual(it["ms"], 600)
        pid = int((Path(tmp.name) / "pid").read_text())
        time.sleep(0.5)
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)  # the wrapper killed it
        tmp.cleanup()

    def test_tiny_timeout_never_rejects(self):
        items = run_ts([SJ] * 4, self.db, opts={"textTimeoutMs": 1}, concurrent=True)
        for it in items:
            self.one_veto(it, "python_text_failed")

    def test_output_over_the_buffer_cap_is_a_veto_and_kills_the_child(self):
        it, tmp = self.sabotaged(
            'open(os.environ["KF_PIDFILE"], "w").write(str(os.getpid()))\n'
            'w = sys.stdout.write\nfor _ in range(80):\n    w("x" * 1_000_000)\nsys.stdout.flush()\ntime.sleep(60)')
        self.one_veto(it, "python_text_failed")
        pid = int((Path(tmp.name) / "pid").read_text())
        time.sleep(0.5)
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        tmp.cleanup()

    def test_at_most_four_children_run_at_once(self):
        env, tmp = make_sabotage(
            'import json\n'
            'd = os.environ["KF_PIDFILE"] + ".d"\n'
            'os.makedirs(d, exist_ok=True)\n'
            't0 = time.time()\n'
            'time.sleep(1.0)\n'
            'open(os.path.join(d, str(os.getpid())), "w").write(json.dumps([t0, time.time()]))\n'
            'sys.stdout.write("[]"); sys.stdout.flush(); os._exit(0)')
        items = run_ts([SJ + "Id. at %d." % (460 + i) for i in range(10)], self.db, env=env, concurrent=True)
        for it in items:
            self.assertEqual((it["ok"], it["results"]), (True, []))
        spans = [json.loads(p.read_text()) for p in (Path(tmp.name) / "pid.d").iterdir()]
        self.assertEqual(len(spans), 10)
        events = sorted([(a, 1) for a, _b in spans] + [(b, -1) for _a, b in spans])
        live = peak = 0
        for _t, delta in events:
            live += delta
            peak = max(peak, live)
        self.assertLessEqual(peak, 4)
        self.assertGreaterEqual(peak, 2)  # it does run in parallel
        tmp.cleanup()

    def test_queue_wait_is_bounded_by_gate_busy(self):
        env, tmp = make_sabotage(
            'd = os.environ["KF_PIDFILE"] + ".d"\n'
            'os.makedirs(d, exist_ok=True)\n'
            'open(os.path.join(d, str(os.getpid())), "w").write("x")\n'
            'time.sleep(60)')
        items = run_ts([SJ + "Id. at %d." % (460 + i) for i in range(7)], self.db, env=env, concurrent=True,
                       opts={"textTimeoutMs": 4000, "textQueueWaitMs": 800})
        reasons = sorted(it["results"][0]["reason"] for it in items)
        self.assertEqual(reasons, ["gate_busy"] * 3 + ["python_text_failed"] * 4)
        for it in items:
            self.one_veto(it, it["results"][0]["reason"])
        busy = [it for it in items if it["results"][0]["reason"] == "gate_busy"]
        for it in busy:
            self.assertLess(it["ms"], 3000)  # resolved at the queue bound, not after the 4 running calls timed out
        self.assertEqual(len(list((Path(tmp.name) / "pid.d").iterdir())), 4)  # the queued three never spawned
        tmp.cleanup()

    def test_slot_is_released_only_after_the_killed_child_is_reaped(self):
        # 4 children hang and are killed at the 700 ms timeout; the 5th..8th calls wait for slots. Each
        # child records how many earlier children were still alive when it started: never more than 3.
        env, tmp = make_sabotage(
            'import json\n'
            'd = os.environ["KF_PIDFILE"] + ".d"\n'
            'os.makedirs(d, exist_ok=True)\n'
            'alive = 0\n'
            'for f in os.listdir(d):\n'
            '    try:\n'
            '        os.kill(int(f), 0); alive += 1\n'
            '    except (ProcessLookupError, ValueError):\n'
            '        pass\n'
            'open(os.path.join(d, str(os.getpid())), "w").write(str(alive))\n'
            'time.sleep(60)')
        items = run_ts([SJ + "Id. at %d." % (460 + i) for i in range(8)], self.db, env=env, concurrent=True,
                       opts={"textTimeoutMs": 700, "textQueueWaitMs": 30000})
        for it in items:
            self.one_veto(it, "python_text_failed")
        counts = sorted(int(p.read_text()) for p in (Path(tmp.name) / "pid.d").iterdir())
        self.assertEqual(len(counts), 8)
        self.assertLessEqual(max(counts), 3, counts)
        tmp.cleanup()

    def test_spawn_failure_releases_the_slot(self):
        # Python missing: every call fails at spawn; 12 calls (3x the cap) must all resolve, none stuck in the queue.
        empty_home = tempfile.TemporaryDirectory()
        items = run_ts([SJ + "Id. at %d." % (460 + i) for i in range(12)], self.db, env={"HOME": empty_home.name},
                       concurrent=True, opts={"textQueueWaitMs": 20000})
        for it in items:
            self.one_veto(it, "python_text_failed")
        empty_home.cleanup()

    def test_queued_calls_run_when_a_slot_frees(self):
        items = run_ts(DRAFTS * 2, self.db, concurrent=True)
        for d, it in zip(DRAFTS * 2, items):
            self.assertEqual([ts_view(r) for r in it["results"]], [py_view(r) for r in check_text(d, self.db)])

    def test_python_missing_is_a_veto(self):
        empty_home = tempfile.TemporaryDirectory()
        items = run_ts([SJ], self.db, env={"HOME": empty_home.name})
        self.one_veto(items[0], "python_text_failed")
        empty_home.cleanup()

    def test_child_that_closes_stdin_early_does_not_crash_node(self):
        # A big draft and a child that exits at once: EPIPE on stdin must not surface as an unhandled error.
        env, tmp = make_sabotage("os._exit(0)")
        items = run_ts(["Smith v. Jones, 123 So. 3d 456 (Fla. 2013). " * 4000], self.db, env=env)
        self.one_veto(items[0], "python_text_bad_output")
        tmp.cleanup()

    def test_stderr_noise_is_ignored(self):
        env, tmp = make_sabotage('sys.stderr.write("noise" * 100000)')
        it = run_ts([SJ + "Id. at 461."], self.db, env=env)[0]
        self.assertEqual([r["verdict"] for r in it["results"]], ["pass", "pass"])
        tmp.cleanup()

    def test_draft_travels_on_stdin_not_argv(self):
        # The sabotage records the child's argv; the draft text must not be in it.
        env, tmp = make_sabotage(
            'import subprocess\n'
            'open(os.environ["KF_PIDFILE"], "w").write(subprocess.run(["ps", "-o", "args=", "-p", str(os.getpid())], '
            'capture_output=True, text=True).stdout)')
        marker = "ZZUNIQUEMARKERZZ"
        run_ts([SJ + marker], self.db, env=env)
        argv = (Path(tmp.name) / "pid").read_text()
        self.assertIn("gate1.py", argv)
        self.assertNotIn(marker, argv)
        self.assertNotIn("Smith", argv)
        self.assertIn("--text -", argv)
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
