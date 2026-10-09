"""Shared fixtures and harness for the Gate 1 adversarial suite.

Builds a CourtListener-format corpus in a temp dir, indexes it with
db.build_sqlite_index.build_index, and exposes two ways to run a verdict:
the Python reference gate and the TS gate (via a node subprocess).

Never touches /Volumes/Kingsfield_Corpus or the repo-root database.
"""

import atexit
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import unittest.result  # noqa: E402

# Keep failure output readable: the suite has hundreds of subtests and the lead reads the traces.
_orig_exc_info_to_string = unittest.result.TestResult._exc_info_to_string


def _compact_exc_info_to_string(self, err, test):
    lines = _orig_exc_info_to_string(self, err, test).splitlines()
    if len(lines) > 12:
        lines = lines[:1] + ["  ..."] + lines[-10:]
    return "\n".join(l if len(l) <= 400 else l[:400] + " ...[cut]" for l in lines) + "\n"


unittest.result.TestResult._exc_info_to_string = _compact_exc_info_to_string

_SUMMARY_PATH = Path("/private/tmp/claude-501/-Users-aaronray-kingsfield/fff182ea-0231-4ca7-a26b-7ade3531129e/scratchpad/last_run.txt")
_orig_run = unittest.TextTestRunner.run


def _run_and_summarise(self, test):
    result = _orig_run(self, test)
    try:
        if _SUMMARY_PATH.parent.is_dir():
            out = ["ran=%d failures=%d errors=%d skipped=%d" % (
                result.testsRun, len(result.failures), len(result.errors), len(result.skipped))]
            for kind, items in (("FAIL", result.failures), ("ERROR", result.errors)):
                for t, tb in items:
                    tail = " ".join(tb.strip().splitlines()[-4:])
                    out.append("%s %s :: %s" % (kind, t.id() if hasattr(t, "id") else t, tail[:420]))
            for t, why in result.skipped:
                out.append("SKIP %s :: %s" % (t.id(), why))
            _SUMMARY_PATH.write_text("\n".join(out), encoding="utf-8")
    except Exception:
        pass
    return result


unittest.TextTestRunner.run = _run_and_summarise

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

TS_GATE = REPO / "backend" / "src" / "verification" / "local_sqlite_gate.ts"

# cluster ids used by the fixture
SMITH = 1001          # 100 So. 3d 200, fla, pages 200-215
JONES = 1002          # 150 So. 3d 500, fladistctapp, pages 500-512
BROWN = 1003          # 400 So. 2d 100, fla, pages 100-130
GARCIA = 1004         # 200 So. 3d 300, fladistctapp, NO page-bounds row
WILLIAMS = 1005       # 150 So. 100, fla, pages 100-110
FLW = 1006            # 36 Fla. L. Weekly 1234, fla, pages 1234-1240
FLW_SUPP = 1007       # 20 Fla. L. Weekly Supp. 300, fla, pages 300-305
FLW_LETTERED = 1008   # 37 Fla. L. Weekly D500, fladistctapp
ALABAMA = 2001        # 175 So. 3d 700, ala
LOUISIANA = 2002      # 180 So. 3d 800, la
MISSISSIPPI = 2003    # 190 So. 3d 900, miss
FEDERAL = 3001        # 600 F.3d 100, ca11
FLW_FED = 3002        # 22 Fla. L. Weekly Fed. 500, ca11

CITATIONS = [
    # id, volume, reporter, page, type, cluster_id
    (1, 100, "So. 3d", 200, 1, SMITH),
    (2, 150, "So. 3d", 500, 1, JONES),
    (3, 400, "So. 2d", 100, 1, BROWN),
    (4, 200, "So. 3d", 300, 1, GARCIA),
    (5, 150, "So.", 100, 1, WILLIAMS),
    (6, 36, "Fla. L. Weekly", 1234, 1, FLW),
    (7, 20, "Fla. L. Weekly Supp.", 300, 1, FLW_SUPP),
    (8, 37, "Fla. L. Weekly", "D500", 1, FLW_LETTERED),
    (9, 175, "So. 3d", 700, 1, ALABAMA),
    (10, 180, "So. 3d", 800, 1, LOUISIANA),
    (11, 190, "So. 3d", 900, 1, MISSISSIPPI),
    (12, 600, "F.3d", 100, 1, FEDERAL),
    (13, 22, "Fla. L. Weekly Fed.", 500, 1, FLW_FED),
]

# id, case_name, case_name_full, docket_id, date_filed
CLUSTERS = [
    (SMITH, "Smith v. State", "Smith v. State of Florida", 501, "2012-06-14"),
    (JONES, "Jones v. Acme Insurance Co.", "Jones v. Acme Insurance Company", 502, "2014-03-05"),
    (BROWN, "Brown v. Florida Power Corp.", "Brown v. Florida Power Corporation", 503, "1981-02-11"),
    (GARCIA, "Garcia v. Miami-Dade County", "Garcia v. Miami-Dade County", 504, "2016-09-21"),
    (WILLIAMS, "State v. Williams", "State v. Williams", 505, "1933-05-02"),
    (FLW, "Rodriguez v. State", "Rodriguez v. State", 506, "2011-04-01"),
    (FLW_SUPP, "Doe v. Board of Trustees", "Doe v. Board of Trustees", 507, "2012-08-15"),
    (FLW_LETTERED, "Peterson v. Tallahassee Housing Authority", "Peterson v. Tallahassee Housing Authority", 508, "2012-02-10"),
    (ALABAMA, "Ex parte Johnson", "Ex parte Johnson", 601, "2015-01-09"),
    (LOUISIANA, "State v. Landry", "State v. Landry", 602, "2016-02-18"),
    (MISSISSIPPI, "Doe v. Mississippi Department of Human Services", "Doe v. Mississippi Department of Human Services", 603, "2016-07-07"),
    (FEDERAL, "United States v. Perez", "United States v. Perez", 701, "2010-05-12"),
    (FLW_FED, "Acme Corp. v. Widget LLC", "Acme Corp. v. Widget LLC", 702, "2010-03-01"),
]

# id, court_id, docket_number
DOCKETS = [
    (501, "fla", "SC11-100"),
    (502, "fladistctapp", "1D13-0001"),
    (503, "fla", "SC80-200"),
    (504, "fladistctapp", "3D15-0002"),
    (505, "fla", "SC1933-1"),
    (506, "fla", "SC10-300"),
    (507, "fla", "SC11-400"),
    (508, "fladistctapp", "1D11-0500"),
    (601, "ala", "1140001"),
    (602, "la", "2015-K-0100"),
    (603, "miss", "2015-CA-0200"),
    (701, "ca11", "09-10000"),
    (702, "ca11", "09-10001"),
]

# cluster_id, first_page, last_page (GARCIA deliberately absent)
PAGE_BOUNDS = [
    (SMITH, 200, 215),
    (JONES, 500, 512),
    (BROWN, 100, 130),
    (WILLIAMS, 100, 110),
    (FLW, 1234, 1240),
    (FLW_SUPP, 300, 305),
    (FLW_LETTERED, 500, 506),
    (ALABAMA, 700, 710),
    (LOUISIANA, 800, 812),
    (MISSISSIPPI, 900, 915),
    (FEDERAL, 100, 120),
    (FLW_FED, 500, 505),
]


def _write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def write_corpus(corpus_dir):
    corpus_dir = Path(corpus_dir)
    corpus_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(corpus_dir / "citations-2026-01-01.csv",
               ["id", "volume", "reporter", "page", "type", "cluster_id"], CITATIONS)
    _write_csv(corpus_dir / "opinion-clusters-2026-01-01.csv",
               ["id", "case_name", "case_name_full", "docket_id", "date_filed"], CLUSTERS)
    _write_csv(corpus_dir / "dockets-2026-01-01.csv",
               ["id", "court_id", "docket_number"], DOCKETS)
    _write_csv(corpus_dir / "page-bounds-2026-01-01.csv",
               ["cluster_id", "first_page", "last_page"], PAGE_BOUNDS)


@dataclass
class Fixture:
    root: Path
    corpus: Path
    db: Path
    stats: object


_fixture = None


def new_tempdir(prefix="kf_adv_"):
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    atexit.register(shutil.rmtree, str(tmp), True)
    return tmp


def get_fixture():
    """Build once; a failed build is retried (and re-raised) on every call."""
    global _fixture
    if _fixture is None:
        from db.build_sqlite_index import build_index
        root = new_tempdir()
        corpus = root / "corpus"
        write_corpus(corpus)
        db = root / "kingsfield_florida.db"
        stats = build_index(corpus, db)
        _fixture = Fixture(root, corpus, db, stats)
    return _fixture


# ───── verdict runners ─────

def py_check(citation, db_path):
    from pipeline import gate1
    return gate1.check_citation(citation, db_path)


def py_check_text(text, db_path):
    from pipeline import gate1
    return gate1.check_text(text, db_path)


_NODE = shutil.which("node") or next(
    (p for p in ("/usr/local/bin/node", "/opt/homebrew/bin/node") if os.path.exists(p)), "node")

_TS_SCRIPT = """
const mod = await import(process.env.GATE_URL);
const inputs = JSON.parse(process.env.GATE_INPUTS);
const out = inputs.map((c) => {
  try { return mod.localGate1(c, { dbPath: process.env.GATE_DB }); }
  catch (e) { return { verdict: 'THROW', reason: String(e) }; }
});
console.log(JSON.stringify(out));
"""

_ts_cache = {}


class NodeFlagUnsupported(Exception):
    pass


# Same as _TS_SCRIPT but relies on the gate's own dbPath default (KINGSFIELD_FLORIDA_DB).
_TS_SCRIPT_DEFAULT_DB = _TS_SCRIPT.replace("{ dbPath: process.env.GATE_DB }", "undefined")


# One long-lived node process answers the default-mode requests (no node flags, explicit dbPath). It imports the same
# local_sqlite_gate.ts and calls the same localGate1(citation, { dbPath }) for every citation; the gate opens and closes
# the database on every call and keeps no state between calls, so a verdict is the one a fresh process gives. This only
# removes the ~0.3 s node start-up per citation. Requests that need their own process (node flags, the KINGSFIELD_FLORIDA_DB
# default) and any worker failure take the one-shot path below, unchanged.
_TS_WORKER_SCRIPT = """
import readline from 'node:readline';
const mod = await import(process.env.GATE_URL);
const rl = readline.createInterface({ input: process.stdin });
for await (const line of rl) {
  let out;
  try {
    const req = JSON.parse(line);
    out = req.inputs.map((c) => {
      try { return mod.localGate1(c, { dbPath: req.db }); }
      catch (e) { return { verdict: 'THROW', reason: String(e) }; }
    });
  } catch (e) { out = { workerError: String(e) }; }
  process.stdout.write(JSON.stringify(out) + '\\n');
}
"""

_worker = None
_WORKER_REQUEST_TIMEOUT_S = 120


class _TsWorker:
    def __init__(self):
        import select  # noqa: F401  (POSIX only; this suite runs on macOS)
        env = dict(os.environ)
        env["GATE_URL"] = TS_GATE.as_uri()
        self.proc = subprocess.Popen(
            [_NODE, "--no-warnings", "--input-type=module", "-e", _TS_WORKER_SCRIPT],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=env, cwd=str(REPO), bufsize=0,
        )
        self.buf = b""

    def ask(self, citations, db_path):
        import select
        req = (json.dumps({"inputs": list(citations), "db": str(db_path)}) + "\n").encode("utf-8")
        self.proc.stdin.write(req)
        self.proc.stdin.flush()
        deadline = _WORKER_REQUEST_TIMEOUT_S
        while b"\n" not in self.buf:
            ready, _, _ = select.select([self.proc.stdout], [], [], deadline)
            if not ready:
                raise TimeoutError("TS gate worker did not answer")
            chunk = os.read(self.proc.stdout.fileno(), 1 << 20)
            if not chunk:
                raise EOFError("TS gate worker exited")
            self.buf += chunk
        line, _, self.buf = self.buf.partition(b"\n")
        out = json.loads(line.decode("utf-8"))
        if not isinstance(out, list) or len(out) != len(citations):
            raise ValueError("TS gate worker answered %r" % (out,))
        return out

    def stop(self):
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.kill()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=5)
        except Exception:
            pass


def _worker_check(citations, db_path):
    global _worker
    try:
        if _worker is None or _worker.proc.poll() is not None:
            _worker = _TsWorker()
            atexit.register(_worker.stop)
        return _worker.ask(citations, db_path)
    except Exception:
        if _worker is not None:
            _worker.stop()
        _worker = None
        return None


def ts_check_many(citations, db_path, node_flags=(), use_env_default=False):
    key = (tuple(citations), str(db_path), tuple(node_flags), use_env_default)
    if key in _ts_cache:
        return _ts_cache[key]
    if not node_flags and not use_env_default:
        out = _worker_check(citations, db_path)
        if out is not None:
            _ts_cache[key] = out
            return out
    env = dict(os.environ)
    env["GATE_URL"] = TS_GATE.as_uri()
    env["GATE_INPUTS"] = json.dumps(list(citations))
    env["GATE_DB"] = str(db_path)
    if use_env_default:
        env["KINGSFIELD_FLORIDA_DB"] = str(db_path)
    script = _TS_SCRIPT_DEFAULT_DB if use_env_default else _TS_SCRIPT
    proc = subprocess.run(
        [_NODE, "--no-warnings", *node_flags, "--input-type=module", "-e", script],
        capture_output=True, text=True, env=env, timeout=120, cwd=str(REPO),
    )
    if proc.returncode != 0:
        if "bad option" in proc.stderr:
            raise NodeFlagUnsupported(proc.stderr)
        raise AssertionError(
            "TS gate subprocess failed (exit %s)\nstdout: %s\nstderr: %s"
            % (proc.returncode, proc.stdout[-300:], " | ".join(
                l.strip() for l in proc.stderr.splitlines() if "Error" in l or "error" in l)[:500]))
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    _ts_cache[key] = out
    return out


def ts_check(citation, db_path, **kw):
    return ts_check_many([citation], db_path, **kw)[0]
