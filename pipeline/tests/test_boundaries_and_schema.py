"""Structural attacks: network/hosted-LLM dependencies (Constraint C), schema
separation (Constraint B), Gate 1 ordering and bypass paths (Constraints A and D),
TS fallback and CLI contract."""

import ast
import json
import re
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate1_fixture as fx  # noqa: E402

REPO = fx.REPO
EXCLUDED_DIRS = {"tests", "builder_tests", "__pycache__", "node_modules", ".venv", "venv"}

NETWORK_ROOTS = {
    "urllib", "urllib2", "urllib3", "requests", "http", "socket", "ssl", "httpx", "aiohttp",
    "websocket", "websockets", "ftplib", "smtplib", "telnetlib", "xmlrpc", "poplib", "imaplib",
    "grpc", "pycurl", "treq", "twisted", "tornado", "paramiko", "asyncssh",
}
HOSTED_LLM_ROOTS = {
    "anthropic", "openai", "cohere", "mistralai", "groq", "together", "litellm", "vertexai",
    "langchain", "langchain_core", "langchain_openai", "langchain_anthropic", "boto3", "botocore",
    "ollama", "replicate", "huggingface_hub", "transformers",
}
HOSTED_LLM_DOTTED = ("google.generativeai", "google.genai", "google.ai", "google.cloud.aiplatform")
HOSTED_LLM_HOSTS = re.compile(
    r"api\.openai\.com|api\.anthropic\.com|generativelanguage\.googleapis\.com|api\.groq\.com|"
    r"api\.cohere\.(ai|com)|api\.mistral\.ai|openrouter\.ai|api-inference\.huggingface\.co", re.I)
NET_BINARIES = re.compile(r"\b(curl|wget|nc|ncat|ssh|scp|sftp|ftp|telnet|rsync)\b")

ROUTER_CLIENT = REPO / "router" / "system_one_client.py"


def py_files(dirname):
    root = REPO / dirname
    if not root.is_dir():
        raise AssertionError("expected directory %s to exist" % root)
    files = [p for p in sorted(root.rglob("*.py"))
             if not (set(p.relative_to(root).parts[:-1]) & EXCLUDED_DIRS)]
    if not files:
        raise AssertionError("no non-test python files under %s" % root)
    return files


def imported_modules(tree):
    """Yield (module_dotted_name, lineno) for every import, including literal dynamic imports."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name, node.lineno
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                yield node.module, node.lineno
                for a in node.names:
                    yield "%s.%s" % (node.module, a.name), node.lineno
        elif isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else None
            if name in ("__import__", "import_module"):
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    yield node.args[0].value, node.lineno
                else:
                    yield "<non-literal dynamic import>", node.lineno


def violations(path, banned_roots, allowed_dotted=()):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []
    for mod, line in imported_modules(tree):
        if mod == "<non-literal dynamic import>":
            found.append("%s:%d non-literal dynamic import" % (path.relative_to(REPO), line))
            continue
        if mod in allowed_dotted:
            continue
        root = mod.split(".")[0]
        if root in banned_roots or any(mod == d or mod.startswith(d + ".") for d in HOSTED_LLM_DOTTED):
            found.append("%s:%d imports %s" % (path.relative_to(REPO), line, mod))
    return found


def shell_network_calls(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        label = ast.unparse(fn)
        if not re.search(r"(subprocess\.|os\.(system|popen|exec|spawn))", label):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and NET_BINARIES.search(sub.value):
                found.append("%s:%d %s invokes %r" % (path.relative_to(REPO), node.lineno, label, sub.value))
    return found


def hosted_llm_hosts(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return ["%s:%d references %r" % (path.relative_to(REPO), n.lineno, n.value)
            for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and HOSTED_LLM_HOSTS.search(n.value)]


# ───── vector 5: network / hosted-LLM dependencies ─────

class NoNetworkInDbAndPipeline(unittest.TestCase):
    def test_no_network_imports_in_db_or_pipeline(self):
        found = []
        for d in ("db", "pipeline"):
            for p in py_files(d):
                found += violations(p, NETWORK_ROOTS | HOSTED_LLM_ROOTS)
        self.assertEqual(found, [], "network or hosted-LLM dependency in db/ or pipeline/:\n" + "\n".join(found))

    def test_no_shell_out_to_network_binaries_in_db_or_pipeline(self):
        found = []
        for d in ("db", "pipeline"):
            for p in py_files(d):
                found += shell_network_calls(p)
        self.assertEqual(found, [], "\n".join(found))

    def test_no_hosted_llm_hosts_anywhere_in_db_pipeline_router(self):
        found = []
        for d in ("db", "pipeline", "router"):
            for p in py_files(d):
                found += hosted_llm_hosts(p)
        self.assertEqual(found, [], "\n".join(found))

    def test_non_python_files_in_db_and_pipeline_make_no_network_calls(self):
        found = []
        pat = re.compile(r"\bfetch\s*\(|\bcurl\b|\bwget\b|node:https?|XMLHttpRequest|\baxios\b|\bundici\b")
        for d in ("db", "pipeline"):
            root = REPO / d
            for p in sorted(root.rglob("*")):
                if p.suffix not in (".sh", ".js", ".mjs", ".cjs", ".ts", ".bash", ".zsh"):
                    continue
                if set(p.relative_to(root).parts[:-1]) & EXCLUDED_DIRS:
                    continue
                for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if pat.search(line):
                        found.append("%s:%d %s" % (p.relative_to(REPO), i, line.strip()))
        self.assertEqual(found, [], "\n".join(found))


class RouterNetworkSurface(unittest.TestCase):
    def test_only_the_von_client_touches_the_network(self):
        found = []
        for p in py_files("router"):
            if p == ROUTER_CLIENT:
                continue
            found += violations(p, NETWORK_ROOTS | HOSTED_LLM_ROOTS)
            found += shell_network_calls(p)
        self.assertEqual(found, [], "network use in router/ outside system_one_client.py:\n" + "\n".join(found))

    def test_von_client_is_stdlib_urllib_only(self):
        self.assertTrue(ROUTER_CLIENT.is_file(), "router/system_one_client.py missing")
        banned = (NETWORK_ROOTS - {"urllib"}) | HOSTED_LLM_ROOTS
        found = violations(ROUTER_CLIENT, banned)
        found += shell_network_calls(ROUTER_CLIENT)
        self.assertEqual(found, [], "\n".join(found))

    def test_von_client_does_not_hardcode_a_remote_endpoint(self):
        src = ROUTER_CLIENT.read_text(encoding="utf-8")
        tree = ast.parse(src)
        urls = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and re.match(r"^https?://\S", n.value)  # bare "http://" is a scheme check, not an endpoint
                and not re.match(r"^https?://(127\.0\.0\.1|localhost|\[::1\])", n.value)]
        self.assertEqual(urls, [], "hardcoded non-loopback URL in Von client: %r" % urls)

    def test_direct_db_is_the_hardcoded_fallback(self):
        src = ROUTER_CLIENT.read_text(encoding="utf-8")
        self.assertIn("direct_db", src)
        self.assertIn("requires_gate1", src)


class TsGateIsOffline(unittest.TestCase):
    def _code(self):
        raw = fx.TS_GATE.read_text(encoding="utf-8")
        raw = re.sub(r"/\*.*?\*/", "", raw, flags=re.S)
        return "\n".join(re.sub(r"(^|\s)//.*$", "", line) for line in raw.splitlines())

    def test_no_fetch_or_network_imports(self):
        code = self._code()
        self.assertNotRegex(code, r"\bfetch\s*\(")
        self.assertNotRegex(code, r"XMLHttpRequest|\bWebSocket\b|\baxios\b|\bundici\b|node-fetch|\bcurl\b|\bwget\b")
        specs = re.findall(r"""(?:\bfrom\s+|\bimport\s*\(\s*|\brequire\s*\(\s*|\bimport\s+)['"]([^'"]+)['"]""", code)
        self.assertTrue(specs, "expected at least one import (node:sqlite)")
        banned = {"node:http", "node:https", "node:http2", "node:net", "node:dns", "node:tls", "node:dgram",
                  "node:dns/promises", "node:worker_threads", "http", "https", "net", "dns", "tls", "dgram"}
        for s in specs:
            self.assertTrue(s.startswith("node:"), "non-builtin import %r (gate must be self-contained)" % s)
            self.assertNotIn(s, banned, "network builtin imported: %s" % s)

    def test_fallback_child_process_has_no_shell(self):
        code = self._code()
        # shell-string exec reachable with untrusted citation text (RegExp#exec is a method call, hence the lookbehind)
        self.assertNotRegex(code, r"(?<![.\w])(?:exec|execSync)\s*\(")
        self.assertNotRegex(code, r"import\s*\{[^}]*\b(?:exec|execSync)\b[^}]*\}\s*from\s*['\"]node:child_process")
        self.assertNotRegex(code, r"shell\s*:\s*true")

    def test_readonly_and_no_writes(self):
        code = self._code()
        self.assertRegex(code, r"readOnly\s*:\s*true")
        self.assertNotRegex(code, r"(?i)\b(insert\s+into|update\s+\w+\s+set|delete\s+from|drop\s+table|alter\s+table|create\s+table|attach\s+database)\b")

    def test_python_gate_is_readonly_and_has_a_cli(self):
        src = (REPO / "pipeline" / "gate1.py").read_text(encoding="utf-8")
        self.assertIn("mode=ro", src)
        self.assertIn("--citation", src)
        self.assertIn("--db", src)
        self.assertNotRegex(src, r"(?i)\b(insert\s+into|update\s+\w+\s+set|delete\s+from|drop\s+table|alter\s+table|create\s+table|attach\s+database)\b")


# ───── vector 6: schema separation ─────

OPINION_FORBIDDEN = ("summary", "goodlaw", "good_law", "classif", "treatment", "analysis", "ai_", "generated")
ANALYSIS_FORBIDDEN_EXACT = {
    "plain_text", "html", "html_lawbox", "html_columbia", "html_anon_2020", "xml_harvard",
    "html_with_citations", "opinion_text", "raw_text", "text", "body", "content", "opinion",
}


def _cols(con, table):
    return [r[1].lower() for r in con.execute("PRAGMA table_info(%s)" % table)]


class SchemaSeparation(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect("file:%s?mode=ro" % fx.get_fixture().db, uri=True)
        self.addCleanup(self.con.close)

    def test_tables_exist(self):
        names = {r[0] for r in self.con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for t in ("citation_index", "caselaw_opinion", "caselaw_analysis"):
            self.assertIn(t, names)

    def test_opinion_table_holds_no_ai_generated_columns(self):
        bad = [c for c in _cols(self.con, "caselaw_opinion") if any(f in c for f in OPINION_FORBIDDEN)]
        self.assertEqual(bad, [], "AI/analysis columns in caselaw_opinion: %r" % bad)

    def test_analysis_table_holds_no_raw_opinion_text(self):
        bad = [c for c in _cols(self.con, "caselaw_analysis") if c in ANALYSIS_FORBIDDEN_EXACT]
        self.assertEqual(bad, [], "raw opinion text columns in caselaw_analysis: %r" % bad)

    def test_citation_index_holds_neither(self):
        cols = _cols(self.con, "citation_index")
        for needed in ("reporter", "volume", "page", "section", "cluster_id", "case_name", "court_id", "first_page", "last_page"):
            self.assertIn(needed, cols)
        bad = [c for c in cols if c in ANALYSIS_FORBIDDEN_EXACT or any(f in c for f in OPINION_FORBIDDEN)]
        self.assertEqual(bad, [], bad)

    def test_analysis_table_created_empty(self):
        n = self.con.execute("SELECT COUNT(*) FROM caselaw_analysis").fetchone()[0]
        self.assertEqual(n, 0, "build_index wrote rows into caselaw_analysis")

    def test_no_view_or_trigger_bridges_the_two_tables(self):
        rows = self.con.execute("SELECT type, name, sql FROM sqlite_master WHERE type IN ('view','trigger')").fetchall()
        bad = [r for r in rows if r[2] and "caselaw_opinion" in r[2] and "caselaw_analysis" in r[2]]
        self.assertEqual(bad, [], bad)
        views = [r for r in rows if r[0] == "view" and r[2] and re.search(r"caselaw_(opinion|analysis)", r[2])]
        self.assertEqual(views, [], "views over the separated tables: %r" % views)

    def test_no_sql_statement_in_code_touches_both_tables(self):
        offenders = []
        files = []
        for d in ("db", "pipeline", "router"):
            files += py_files(d)
        for p in files:
            for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and "caselaw_" in n.value:
                    for stmt in n.value.split(";"):
                        if "caselaw_opinion" in stmt and "caselaw_analysis" in stmt:
                            if re.match(r"(?is)^\s*CREATE\s+(TABLE|INDEX)\b", stmt) and not re.search(r"(?i)\bAS\s+SELECT\b", stmt):
                                continue
                            offenders.append("%s:%d %s" % (p.relative_to(REPO), n.lineno, " ".join(stmt.split())[:160]))
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_gate_logic_never_reads_analysis_table(self):
        for p in (REPO / "pipeline" / "gate1.py", fx.TS_GATE):
            self.assertNotIn("caselaw_analysis", p.read_text(encoding="utf-8"),
                             "%s consults AI-generated analysis in an existence check" % p.name)

    def test_non_florida_and_federal_rows_not_ingested(self):
        ids = {r[0] for r in self.con.execute("SELECT DISTINCT cluster_id FROM citation_index")}
        for leaked in (fx.ALABAMA, fx.LOUISIANA, fx.MISSISSIPPI, fx.FEDERAL, fx.FLW_FED):
            self.assertNotIn(leaked, ids, "cluster %d leaked into the Florida index" % leaked)
        courts = {r[0] for r in self.con.execute("SELECT DISTINCT court_id FROM citation_index WHERE reporter LIKE 'So.%'")}
        self.assertTrue(courts <= {"fla", "fladistctapp"}, courts)

    def test_expected_florida_rows_present_with_bounds(self):
        def row(cluster):
            return self.con.execute(
                "SELECT reporter, volume, page, case_name, first_page, last_page FROM citation_index WHERE cluster_id=?",
                (cluster,)).fetchall()
        self.assertEqual(row(fx.SMITH), [("So. 3d", 100, 200, "Smith v. State", 200, 215)])
        garcia = row(fx.GARCIA)
        self.assertEqual(len(garcia), 1)
        self.assertIsNone(garcia[0][5], "missing page-bounds row must give last_page NULL")
        self.assertEqual(row(fx.FLW)[0][0], "Fla. L. Weekly")
        self.assertEqual(row(fx.FLW_SUPP)[0][0], "Fla. L. Weekly Supp.")

    def test_lookup_uses_the_btree_index(self):
        plan = " ".join(str(r) for r in self.con.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM citation_index WHERE reporter=? AND volume=? AND page=?",
            ("So. 3d", 100, 200)))
        self.assertIn("idx_citation_rvp", plan, plan)
        cols = [r[2] for r in self.con.execute("PRAGMA index_info(idx_citation_rvp)")]
        self.assertEqual(cols, ["reporter", "volume", "page", "section"])
        plan = " ".join(str(r) for r in self.con.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM citation_index WHERE reporter=? AND volume=? AND page=? AND section=?",
            ("Fla. L. Weekly", 37, 500, "D")))
        self.assertIn("idx_citation_rvp", plan, plan)

    def test_build_index_returns_stats(self):
        self.assertIsInstance(fx.get_fixture().stats, dict)


# ───── vector 3: Gate 1 ordering and bypass paths ─────

BACKEND_SRC = REPO / "backend" / "src"
PIPELINE_TS = BACKEND_SRC / "verification" / "pipeline.ts"
CL_NETWORK_CALLS = ("citationLookup(", "readCache(", "getCluster(", "getOpinion(", "checkCurrency(")


def _fn_body(src, name):
    m = re.search(r"export\s+async\s+function\s+%s\b" % name, src)
    if not m:
        return None
    rest = src[m.start():]
    nxt = re.search(r"\n(export\s|// ─────)", rest[10:])
    return rest if not nxt else rest[: nxt.start() + 10]


class Gate1Ordering(unittest.TestCase):
    # Judged a false positive: enrichAuthorityCiteCounts only attaches a CourtListener citation_count to
    # authorities extracted from a user's own document. It makes no existence claim and releases no
    # model-written authority as verified. (Open UX question for the lead: a non-null cite_count does
    # imply the cite resolved at CourtListener.)
    CITATION_LOOKUP_ALLOWED = {BACKEND_SRC / "lib" / "caseIntelligence.ts"}

    def _citation_lookup_offenders(self):
        allowed = {BACKEND_SRC / "research" / "courtlistener.ts", PIPELINE_TS} | self.CITATION_LOOKUP_ALLOWED
        offenders = []
        for p in sorted(BACKEND_SRC.rglob("*.ts")):
            if "node_modules" in p.parts or p in allowed:
                continue
            for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if re.search(r"\bcitationLookup\s*\(", line) and not line.lstrip().startswith(("//", "*")):
                    offenders.append("%s:%d %s" % (p.relative_to(REPO), i, line.strip()))
        return offenders

    def _gate_imported_by_backend(self):
        for p in sorted(BACKEND_SRC.rglob("*.ts")):
            if "node_modules" in p.parts or p == fx.TS_GATE:
                continue
            if "local_sqlite_gate" in p.read_text(encoding="utf-8", errors="replace"):
                return True
        return False

    def test_no_backend_code_calls_citation_lookup_around_the_pipeline(self):
        offenders = self._citation_lookup_offenders()
        if not self._gate_imported_by_backend():
            # Deferred by decision (decisions.md 2026-10-05): backend wiring happens after module signoff and
            # a separate review. This test goes live the moment local_sqlite_gate is imported by any backend
            # file. Known open bypass at deferral time:
            #   backend/src/crew/researcher.ts:123  LLM-proposed citations -> citationLookup(), no local Gate 1
            #   (REAL: authorities materialized from a CourtListener match are released as VerifiedAuthority)
            self.skipTest("local_sqlite_gate not imported by backend yet. OPEN BYPASS, wire before release: "
                          "backend/src/crew/researcher.ts:123 (LLM-proposed cites go to citationLookup without "
                          "local Gate 1). Currently detected: %r" % (offenders,))
        self.assertEqual(offenders, [],
                         "legacy CourtListener lookup reachable without passing local Gate 1:\n" + "\n".join(offenders))

    def test_local_gate_runs_before_any_courtlistener_call_when_wired(self):
        src = PIPELINE_TS.read_text(encoding="utf-8")
        if "local_sqlite_gate" not in src:
            self.skipTest("local_sqlite_gate not wired into verification/pipeline.ts yet (lead wires after signoff)")
        self.assertRegex(src, r"import[^;]*localGate1[^;]*local_sqlite_gate")
        for fn in ("verifyCitation", "verifyDraft"):
            with self.subTest(fn=fn):
                body = _fn_body(src, fn)
                self.assertIsNotNone(body, "%s not found" % fn)
                gate = body.find("localGate1(")
                self.assertNotEqual(gate, -1, "%s never calls localGate1" % fn)
                early = [body.find(c) for c in CL_NETWORK_CALLS if body.find(c) != -1]
                self.assertTrue(all(gate < e for e in early),
                                "%s reaches a cache/CourtListener call before localGate1" % fn)
                self.assertRegex(body[gate:], r"['\"]veto['\"]", "%s never acts on a veto verdict" % fn)

    def test_veto_is_not_downgraded_when_wired(self):
        src = PIPELINE_TS.read_text(encoding="utf-8")
        if "local_sqlite_gate" not in src:
            self.skipTest("local_sqlite_gate not wired yet")
        body = _fn_body(src, "verifyCitation")
        gate = body.find("localGate1(")
        veto_branch = re.search(r"['\"]veto['\"][\s\S]{0,300}?(status\s*=\s*'vetoed'|status:\s*'vetoed')", body[gate:])
        self.assertTrue(veto_branch, "a local veto must set status 'vetoed'")
        self.assertNotRegex(body[gate:gate + 600], r"catch\s*\([^)]*\)\s*\{\s*\}", "empty catch around Gate 1 fails open")


# ───── TS fallback path and CLI contract ─────

class TsFallbackAndCli(unittest.TestCase):
    CITES = (
        "Smith v. State, 100 So. 3d 200, 210 (Fla. 2012)",
        "Doe v. Roe, 999 So. 3d 999 (Fla. 2015)",
        "Ex parte Johnson, 175 So. 3d 700 (Ala. 2015)",
        "100 So. 3d 200",
        "Hernandez v. Walmart Stores, Inc., 100 So. 3d 200 (Fla. 2012)",
        "Smith v. State, 100 So. 3d 200, 460 (Fla. 2012)",
    )

    def test_ts_default_db_comes_from_env(self):
        db = fx.get_fixture().db
        out = fx.ts_check_many(list(self.CITES), db, use_env_default=True)
        expected = [fx.py_check(c, db).verdict for c in self.CITES]
        self.assertEqual([o["verdict"] for o in out], expected)
        missing = fx.new_tempdir("kf_adv_env_") / "none.db"
        out = fx.ts_check_many([self.CITES[0]], missing, use_env_default=True)
        self.assertEqual(out[0]["verdict"], "veto", out)

    def test_ts_fallback_when_node_sqlite_unavailable_matches_python(self):
        db = fx.get_fixture().db
        try:
            out = fx.ts_check_many(list(self.CITES), db, node_flags=("--no-experimental-sqlite",))
        except fx.NodeFlagUnsupported:
            self.skipTest("this node has no --no-experimental-sqlite switch")
        expected = [fx.py_check(c, db).verdict for c in self.CITES]
        self.assertEqual([o["verdict"] for o in out], expected,
                         "fallback path diverged from reference gate: %r" % out)

    def test_ts_fallback_fails_closed_on_missing_db(self):
        missing = fx.new_tempdir("kf_adv_fb_") / "none.db"
        try:
            out = fx.ts_check_many([self.CITES[0]], missing, node_flags=("--no-experimental-sqlite",))
        except fx.NodeFlagUnsupported:
            self.skipTest("this node has no --no-experimental-sqlite switch")
        self.assertEqual(out[0]["verdict"], "veto", out)

    def test_cli_prints_gate_result_json_matching_check_citation(self):
        db = fx.get_fixture().db
        for cite in self.CITES:
            with self.subTest(cite=cite):
                proc = subprocess.run(
                    [sys.executable, str(REPO / "pipeline" / "gate1.py"), "--db", str(db), "--citation", cite],
                    capture_output=True, text=True, timeout=60, cwd=str(REPO))
                data = json.loads(proc.stdout.strip().splitlines()[-1])
                self.assertEqual(data["verdict"], fx.py_check(cite, db).verdict, proc.stdout + proc.stderr)

    def test_cli_vetoes_on_missing_db(self):
        missing = fx.new_tempdir("kf_adv_cli_") / "none.db"
        proc = subprocess.run(
            [sys.executable, str(REPO / "pipeline" / "gate1.py"), "--db", str(missing), "--citation", self.CITES[0]],
            capture_output=True, text=True, timeout=60, cwd=str(REPO))
        data = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(data["verdict"], "veto", proc.stdout + proc.stderr)
        self.assertFalse(missing.exists())

    def test_cli_does_not_shell_interpret_citation_text(self):
        db = fx.get_fixture().db
        marker = fx.new_tempdir("kf_adv_sh_") / "pwned"
        cite = "Doe v. Roe, 999 So. 3d 999 (Fla. 2015) ; touch %s ; $(touch %s)" % (marker, marker)
        proc = subprocess.run(
            [sys.executable, str(REPO / "pipeline" / "gate1.py"), "--db", str(db), "--citation", cite],
            capture_output=True, text=True, timeout=60, cwd=str(REPO))
        self.assertFalse(marker.exists())
        data = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertNotEqual(data["verdict"], "pass")


if __name__ == "__main__":
    unittest.main()
