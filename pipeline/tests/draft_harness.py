"""Harness for the draft-mode (localGate1Text) attacks.

Provides: an extended CourtListener-format fixture (two extra Florida records so volume-level
ambiguity can be built), a node runner that awaits localGate1Text through the real TS wrapper
(and therefore through the real Python child process), the Gate1TextResult contract checker, and
helpers that sabotage the Python child through PYTHONPATH/sitecustomize so the wrapper's
fail-closed behaviour can be observed from the outside, without editing application code.

localGate1Text is async: it returns Promise<Gate1TextResult[]> and must never reject. The node
script therefore records, per call: whether a Promise came back, whether it rejected, how long it
took, and whether the event loop stayed responsive (a 50 ms setInterval keeps ticking) meanwhile.
Unhandled rejections and uncaught exceptions anywhere in the process are collected too.
"""

import json
import os
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate1_fixture as fx  # noqa: E402

SMITH2 = 4001   # 101 So. 3d 600, fla, pages 600-610, "Smith v. Acme Corp." (second Smith, other volume)
DAVIS = 4002    # 100 So. 3d 300, fla, pages 300-310, "Davis v. State"      (same volume as SMITH)

_EXTRA_CITATIONS = [
    (101, 101, "So. 3d", 600, 1, SMITH2),
    (102, 100, "So. 3d", 300, 1, DAVIS),
]
_EXTRA_CLUSTERS = [
    (SMITH2, "Smith v. Acme Corp.", "Smith v. Acme Corporation", 509, "2013-01-01"),
    (DAVIS, "Davis v. State", "Davis v. State", 510, "2012-07-01"),
]
_EXTRA_DOCKETS = [(509, "fla", "SC12-500"), (510, "fla", "SC11-510")]
_EXTRA_BOUNDS = [(SMITH2, 600, 610), (DAVIS, 300, 310)]

_draft_fixture = None


def get_draft_fixture():
    """Base fixture plus the extra records. Built once; never touches the real corpus."""
    global _draft_fixture
    if _draft_fixture is None:
        from db.build_sqlite_index import build_index
        root = fx.new_tempdir("kf_adv_draft_")
        corpus = root / "corpus"
        corpus.mkdir()
        fx._write_csv(corpus / "citations-2026-01-01.csv",
                      ["id", "volume", "reporter", "page", "type", "cluster_id"], fx.CITATIONS + _EXTRA_CITATIONS)
        fx._write_csv(corpus / "opinion-clusters-2026-01-01.csv",
                      ["id", "case_name", "case_name_full", "docket_id", "date_filed"], fx.CLUSTERS + _EXTRA_CLUSTERS)
        fx._write_csv(corpus / "dockets-2026-01-01.csv",
                      ["id", "court_id", "docket_number"], fx.DOCKETS + _EXTRA_DOCKETS)
        fx._write_csv(corpus / "page-bounds-2026-01-01.csv",
                      ["cluster_id", "first_page", "last_page"], fx.PAGE_BOUNDS + _EXTRA_BOUNDS)
        db = root / "kingsfield_florida.db"
        stats = build_index(corpus, db)
        _draft_fixture = fx.Fixture(root, corpus, db, stats)
    return _draft_fixture


# ───── node runner for localGate1Text (async) ─────

# Drafts arrive on stdin as JSON (ensure_ascii), so size and odd characters never touch argv/env limits.
_TS_TEXT_SCRIPT = """
import { readFileSync } from 'node:fs';
const mod = await import(process.env.GATE_URL);
const inputs = JSON.parse(readFileSync(0, 'utf8'));
const unhandled = [];
process.on('unhandledRejection', (e) => unhandled.push('unhandledRejection: ' + String(e)));
process.on('uncaughtException', (e) => unhandled.push('uncaughtException: ' + String(e)));
const opts = Object.assign({ dbPath: process.env.GATE_DB }, JSON.parse(process.env.GATE_OPTS || '{}'));

async function one(d) {
  const t0 = Date.now();
  const stamps = [t0];
  const timer = setInterval(() => stamps.push(Date.now()), 50);
  let out;
  try {
    const p = mod.localGate1Text(d, opts);
    const isPromise = !!p && typeof p.then === 'function';
    const results = await p;
    out = { ok: true, results, isPromise };
  } catch (e) {
    out = { ok: false, error: String(e), isPromise: false };
  }
  clearInterval(timer);
  const t1 = Date.now();
  stamps.push(t1);
  let maxGap = 0;
  for (let i = 1; i < stamps.length; i++) maxGap = Math.max(maxGap, stamps[i] - stamps[i - 1]);
  return Object.assign(out, { ms: t1 - t0, ticks: stamps.length - 2, maxGap });
}

let items;
if (process.env.GATE_CONCURRENT === '1') {
  items = await Promise.all(inputs.map(one));
} else {
  items = [];
  for (const d of inputs) items.push(await one(d));
}
await new Promise((r) => setTimeout(r, 150)); // let any stray rejection surface
console.log(JSON.stringify({ items, unhandled }));
"""

_batch_cache = {}


def ts_text_batch(cases, db, env_extra=None, timeout=900, opts_extra=None, concurrent=False):
    """Await localGate1Text on every draft in `cases` (name -> draft) in one node process.

    Returns (out, unhandled). out maps name -> (status, payload, ms, extra):
      status "ok":  payload is the resolved result list
      status "err": payload is a message; the promise rejected/threw, which the contract forbids
      extra: {"isPromise", "ticks", "maxGap"}; maxGap is the longest stretch (ms) the event loop went
             without running a 50 ms timer while the call was in flight
    unhandled lists any unhandled rejection or uncaught exception seen anywhere in the process.
    Cases may carry non-string values (null, numbers, objects): the contract says those resolve to a veto.
    """
    names = list(cases)
    key = (json.dumps([(n, cases[n]) for n in names], sort_keys=True), str(db),
           tuple(sorted((env_extra or {}).items())), json.dumps(opts_extra or {}, sort_keys=True), concurrent)
    if key in _batch_cache:
        return _batch_cache[key]
    env = _node_env(db, env_extra, opts_extra, concurrent)
    payload = json.dumps([cases[n] for n in names])
    empty = {"isPromise": False, "ticks": 0, "maxGap": 0}
    try:
        proc = subprocess.run(
            [fx._NODE, "--no-warnings", "--input-type=module", "-e", _TS_TEXT_SCRIPT],
            input=payload, capture_output=True, text=True, env=env, timeout=timeout, cwd=str(fx.REPO))
    except subprocess.TimeoutExpired:
        res = ({n: ("err", "harness timeout after %ss (the promise never settled)" % timeout, timeout * 1000, empty)
                for n in names}, [])
        _batch_cache[key] = res
        return res
    res = _parse_node_output(names, proc.returncode, proc.stdout, proc.stderr)
    _batch_cache[key] = res
    return res


def _node_env(db, env_extra, opts_extra, concurrent):
    env = dict(os.environ)
    env["GATE_URL"] = fx.TS_GATE.as_uri()
    env["GATE_DB"] = str(db)
    env["GATE_OPTS"] = json.dumps(opts_extra or {})
    env["GATE_CONCURRENT"] = "1" if concurrent else "0"
    env.update(env_extra or {})
    return env


def _parse_node_output(names, returncode, stdout, stderr):
    empty = {"isPromise": False, "ticks": 0, "maxGap": 0}
    if returncode != 0:
        msg = "node exit %s: %s" % (returncode, " | ".join(
            l.strip() for l in stderr.splitlines() if "rror" in l)[:400])
        return ({n: ("err", msg, 0, empty) for n in names}, [msg])
    try:
        raw = json.loads(stdout.strip().splitlines()[-1])
        out = {}
        for n, r in zip(names, raw["items"]):
            extra = {"isPromise": bool(r.get("isPromise")), "ticks": r.get("ticks", 0),
                     "maxGap": r.get("maxGap", 0)}
            if r.get("ok"):
                out[n] = ("ok", r["results"], r.get("ms", 0), extra)
            else:
                out[n] = ("err", r.get("error"), r.get("ms", 0), extra)
        return (out, list(raw.get("unhandled", [])))
    except Exception as e:  # noqa: BLE001
        msg = "harness could not parse node output (%s): %r" % (e, stdout[-200:])
        return ({n: ("err", msg, 0, empty) for n in names}, [msg])


class LiveBatch:
    """Start a concurrent node batch WITHOUT waiting for it, so a test can drive the Python children from outside
    (hold them on a file, release them one at a time, count live pids at known points) and then collect the result.

    The children are stubs installed through make_sabotage; none of them imports eyecite, so each is cheap.
    """

    def __init__(self, cases, db=None, env_extra=None, opts_extra=None):
        self.cases = dict(cases)
        self.names = list(cases)
        db = db if db is not None else get_draft_fixture().db
        env = _node_env(db, env_extra, opts_extra, True)
        self.proc = subprocess.Popen(
            [fx._NODE, "--no-warnings", "--input-type=module", "-e", _TS_TEXT_SCRIPT],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
            cwd=str(fx.REPO))
        self.proc.stdin.write(json.dumps([self.cases[n] for n in self.names]))
        self.proc.stdin.close()
        # Drain both pipes on threads so node can never block on a full pipe while the test drives the children.
        self._out, self._err = [], []
        self._threads = [threading.Thread(target=self._drain, args=(self.proc.stdout, self._out), daemon=True),
                         threading.Thread(target=self._drain, args=(self.proc.stderr, self._err), daemon=True)]
        for t in self._threads:
            t.start()

    @staticmethod
    def _drain(stream, sink):
        try:
            for chunk in iter(lambda: stream.read(65536), ""):
                sink.append(chunk)
        except Exception:  # noqa: BLE001
            pass
        finally:
            try:
                stream.close()
            except Exception:  # noqa: BLE001
                pass

    def finish(self, timeout=120):
        """Wait for node to exit and return a Batch over the recorded results."""
        empty = {"isPromise": False, "ticks": 0, "maxGap": 0}
        try:
            self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.kill()
            raw = ({n: ("err", "harness timeout after %ss (the promise never settled)" % timeout, timeout * 1000, empty)
                    for n in self.names}, [])
        else:
            for t in self._threads:
                t.join(timeout=10)
            raw = _parse_node_output(self.names, self.proc.returncode, "".join(self._out), "".join(self._err))
        return Batch(self.cases, _prefetched=raw)

    def kill(self):
        try:
            self.proc.kill()
            self.proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            pass


class Batch:
    def __init__(self, cases, db=None, env_extra=None, timeout=900, opts_extra=None, concurrent=False,
                 _prefetched=None):
        self.cases = dict(cases)
        self.db = db if db is not None else get_draft_fixture().db
        if _prefetched is not None:
            self.raw, self.unhandled = _prefetched
        else:
            self.raw, self.unhandled = ts_text_batch(self.cases, self.db, env_extra, timeout, opts_extra, concurrent)

    def results(self, name):
        status, payload = self.raw[name][:2]
        if status != "ok":
            raise AssertionError("localGate1Text did not resolve to a result list for case %r: %s\n  draft=%s"
                                 % (name, payload, repr(self.cases[name])[:200]))
        return payload

    def ms(self, name):
        return self.raw[name][2]

    def loop(self, name):
        return self.raw[name][3]


# ───── Gate1TextResult contract ─────

VERDICTS = {"pass", "veto", "fall_through"}
KINDS = {"full", "short", "id", "supra", "unparsed"}


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def contract_problems(results):
    """Every way a result list can violate the approved contract. Empty list means conformant."""
    if not isinstance(results, list):
        return ["results is not a list: %r" % (results,)]
    problems = []
    prev_start = -1
    for i, r in enumerate(results):
        tag = "result[%d]" % i
        if not isinstance(r, dict):
            problems.append("%s is not an object: %r" % (tag, r))
            continue
        for key in ("verdict", "reason", "kind", "text", "start", "end", "fullCitation"):
            if key not in r:
                problems.append("%s missing %r (fullCitation must be a string or null, never undefined)" % (tag, key))
        v, kind, reason = r.get("verdict"), r.get("kind"), r.get("reason")
        if v not in VERDICTS:
            problems.append("%s bad verdict %r" % (tag, v))
        if kind not in KINDS:
            problems.append("%s bad kind %r" % (tag, kind))
        if not isinstance(reason, str):
            problems.append("%s reason is not a string" % tag)
        if not isinstance(r.get("text"), str):
            problems.append("%s text is not a string" % tag)
        s, e = r.get("start"), r.get("end")
        if not (_is_int(s) and _is_int(e) and 0 <= s <= e):
            problems.append("%s bad span start=%r end=%r" % (tag, s, e))
        elif s < prev_start:
            problems.append("%s out of order (start %d < previous start %d)" % (tag, s, prev_start))
        else:
            prev_start = s
        if v == "pass":
            if not _is_int(r.get("clusterId")):
                problems.append("%s pass without an integer clusterId" % tag)
            if kind == "unparsed":
                problems.append("%s an unparsed citation can never pass" % tag)
            if reason == "non_case_antecedent":
                problems.append("%s pass with reason non_case_antecedent" % tag)
        fc = r.get("fullCitation")
        if fc is not None and not isinstance(fc, str):
            problems.append("%s fullCitation is neither string nor null" % tag)
        if v in ("pass", "fall_through") and fc is None and not (v == "fall_through" and reason == "non_case_antecedent"):
            problems.append("%s non-veto with null fullCitation (only non_case_antecedent may)" % tag)
        if reason == "non_case_antecedent" and (v != "fall_through" or fc is not None):
            problems.append("%s non_case_antecedent must be fall_through with fullCitation null" % tag)
        if kind in ("short", "id", "supra") and reason == "malformed":
            problems.append("%s a %s cite was vetoed as malformed" % (tag, kind))
    return problems


def compact(results):
    if not isinstance(results, list):
        return repr(results)
    return "[" + "; ".join(
        "%s/%s/%s cluster=%s full=%r text=%r" % (r.get("kind"), r.get("verdict"), r.get("reason"), r.get("clusterId"),
                                                (r.get("fullCitation") or "")[:60] if r.get("fullCitation") else None,
                                                (r.get("text") or "")[:50])
        for r in results if isinstance(r, dict)) + "]"


def normalized(draft):
    """The text start/end index: the gate's own normalization of the draft (NFKC, format characters stripped)."""
    from pipeline import gate1
    return gate1.normalize(gate1._strip_format_chars(gate1.normalize(draft)))


# ───── sabotaging the Python child from the outside ─────

_SITE_HEADER = """\
import os, sys
if os.environ.get("KF_ADV_MARKER"):
    open(os.environ["KF_ADV_MARKER"], "w").write("loaded")
"""


def make_sabotage(code):
    """Return (env_extra, marker_path). `code` runs inside the Python child before gate1 does.

    KF_ADV_PIDFILE names a file the sabotage code may write its pid to, so a test can check afterwards
    whether the wrapper really killed the child.
    """
    tmp = fx.new_tempdir("kf_adv_site_")
    (tmp / "sitecustomize.py").write_text(_SITE_HEADER + textwrap.indent(textwrap.dedent(code), "    ") + "\n",
                                          encoding="utf-8")
    marker = tmp / "marker"
    prior = os.environ.get("PYTHONPATH")
    env = {"PYTHONPATH": str(tmp) + (os.pathsep + prior if prior else ""), "KF_ADV_MARKER": str(marker),
           "KF_ADV_PIDFILE": str(tmp / "pid")}
    return env, marker


# ───── cheap stub children for the concurrency tests ─────
#
# A stub replaces the whole Python gate: it runs from sitecustomize, never imports eyecite or gate1, registers
# itself in a live directory, optionally blocks until the TEST releases it (a file named after its pid), then
# answers with a contract-shaped result derived from its own stdin draft: the draft's first letter picks the
# verdict (P pass, V veto, F fall_through) and the draft is echoed back as `text`, so every call can be checked
# against its own draft (no cross-talk) while each child costs a few milliseconds.

_STUB_PROLOGUE = """
import json, time
_d = sys.stdin.buffer.read().decode("utf-8")
_me = str(os.getpid())
_live = os.environ["KF_ADV_LIVEDIR"]
os.makedirs(_live, exist_ok=True)
open(os.path.join(_live, _me), "w").close()
def _alive(p):
    try:
        os.kill(p, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
_n = sum(1 for f in os.listdir(_live) if f.isdigit() and _alive(int(f)))
open(os.environ["KF_ADV_PEAKLOG"], "a").write("%d\\n" % _n)
"""

_STUB_RESPOND = """
try:
    os.remove(os.path.join(_live, _me))
except OSError:
    pass
_k = _d[:1]
_r = {"verdict": {"P": "pass", "V": "veto", "F": "fall_through"}[_k],
      "reason": {"P": "verified", "V": "not_found", "F": "not_florida_key"}[_k],
      "reporter": None, "volume": None, "page": None,
      "cluster_id": 1001 if _k == "P" else None, "kind": "full", "text": _d,
      "full_citation": None if _k == "V" else _d, "start": 0, "end": len(_d)}
sys.stdout.write(json.dumps([_r]))
sys.stdout.flush()
os._exit(0)
"""

_STUB_GATE = """
_rel = os.path.join(os.environ["KF_ADV_RELDIR"], _me)
while not os.path.exists(_rel):
    time.sleep(0.01)
"""


def stub_code(gated=False, hold=0.0):
    """Stub child source. gated: block until the test creates KF_ADV_RELDIR/<pid>. hold: else sleep this long."""
    wait = _STUB_GATE if gated else "\ntime.sleep(%r)\n" % float(hold)
    return _STUB_PROLOGUE + wait + _STUB_RESPOND


def stub_env(code):
    """(env_extra, marker, live_dir, release_dir, peak_log) for a stub child. Directories are created here."""
    env, marker = make_sabotage(code)
    tmp = Path(env["KF_ADV_MARKER"]).parent
    live, rel, peak = tmp / "live", tmp / "release", tmp / "peak.log"
    rel.mkdir()
    env["KF_ADV_LIVEDIR"] = str(live)
    env["KF_ADV_RELDIR"] = str(rel)
    env["KF_ADV_PEAKLOG"] = str(peak)
    return env, marker, live, rel, peak


def stub_draft(kind, i):
    """A draft whose first letter selects the stub's verdict and whose text is unique per call."""
    return "%s-draft-%03d" % (kind, i)
