"""Constraint C: routing goes only to a Von System One endpoint; any failure
falls back to direct_db, and every route terminates at Gate 1."""

import os
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate1_fixture as fx  # noqa: E402,F401  (puts the repo root on sys.path)

QUERIES = (
    "100 So. 3d 200 (Fla. 2012)",
    "find Florida cases about comparative negligence in slip and fall",
    "Smith v. State, 100 So. 3d 200, 210 (Fla. 2012)",
    "",
    "​Ѕmith v. State 999 So. 3d 999",
)


NON_CITATION = QUERIES[1]   # reaches the client; citation queries are short-circuited by the pre-check


def _route():
    from router import system_one_client
    return system_one_client


class _Handler(BaseHTTPRequestHandler):
    mode = "garbage"

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        mode = self.server.mode
        if mode == "slow":
            time.sleep(2.0)
        if mode == "http500":
            self.send_response(500)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = {
            "garbage": b"not json {{{",
            "slow": b"{}",
            "empty_object": b"{}",
            "wrong_types": b'{"choice": {"answer": 12345, "confidence": "high"}, "noul": [], "score": "x"}',
            "null": b"null",
            "list": b"[1, 2, 3]",
        }[mode]
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class _Server:
    def __init__(self, mode):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.httpd.daemon_threads = True
        self.httpd.mode = mode
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return "http://127.0.0.1:%d" % self.httpd.server_address[1]

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


class RouterFallback(unittest.TestCase):
    def assertDirectDb(self, decision, ctx=""):
        self.assertEqual(decision.route, "direct_db", "%s: %r" % (ctx, decision))
        self.assertIs(decision.requires_gate1, True, "%s: %r" % (ctx, decision))
        # Citation-shaped queries are answered by the deterministic pre-check (fallback=False, the
        # client is never called, 2026-10-06 ruling). Every other path here is a failure fallback.
        if "pre-check" not in decision.reason:
            self.assertTrue(decision.fallback, "%s: fallback flag not set: %r" % (ctx, decision))

    def test_von_base_url_unset_routes_direct_db(self):
        env = {k: v for k, v in os.environ.items() if k != "VON_BASE_URL"}
        with mock.patch.dict(os.environ, env, clear=True):
            sc = _route()
            for q in QUERIES:
                with self.subTest(query=q):
                    self.assertDirectDb(sc.route(q), "unset")

    def test_von_base_url_empty_routes_direct_db(self):
        with mock.patch.dict(os.environ, {"VON_BASE_URL": ""}):
            sc = _route()
            d = sc.route(NON_CITATION)
            self.assertDirectDb(d, "empty")
            self.assertNotIn("pre-check", d.reason)
            self.assertTrue(d.fallback)

    def test_unreachable_von_via_env_routes_direct_db(self):
        with mock.patch.dict(os.environ, {"VON_BASE_URL": "http://127.0.0.1:9"}):
            sc = _route()
            started = time.monotonic()
            for q in QUERIES:
                with self.subTest(query=q):
                    self.assertDirectDb(sc.route(q), "refused via env")
            self.assertLess(time.monotonic() - started, 30, "fallback was not prompt")

    def test_unreachable_von_via_explicit_client_routes_direct_db(self):
        sc = _route()
        client = sc.SystemOneClient(base_url="http://127.0.0.1:9", timeout=0.5)
        for q in QUERIES:
            with self.subTest(query=q):
                self.assertDirectDb(sc.route(q, client=client), "refused via client")

    def test_unresolvable_host_routes_direct_db(self):
        sc = _route()
        client = sc.SystemOneClient(base_url="http://von.invalid", timeout=0.5)
        d = sc.route(NON_CITATION, client=client)
        self.assertDirectDb(d, "dns failure")
        self.assertTrue(d.fallback)

    def test_malformed_scheme_routes_direct_db(self):
        sc = _route()
        for url in ("not a url", "ftp://127.0.0.1:9", "file:///etc/passwd", "http://"):
            with self.subTest(url=url):
                client = sc.SystemOneClient(base_url=url, timeout=0.5)
                d = sc.route(NON_CITATION, client=client)
                self.assertDirectDb(d, url)
                self.assertTrue(d.fallback)

    def test_bad_responses_route_direct_db(self):
        sc = _route()
        for mode in ("garbage", "http500", "empty_object", "wrong_types", "null", "list"):
            with self.subTest(mode=mode), _Server(mode) as url:
                client = sc.SystemOneClient(base_url=url, timeout=1.0)
                for q in QUERIES[:3]:
                    self.assertDirectDb(sc.route(q, client=client), mode)
                d = sc.route(NON_CITATION, client=client)       # the one that really reaches the client
                self.assertDirectDb(d, mode)
                self.assertTrue(d.fallback, mode)

    def test_timeout_routes_direct_db(self):
        sc = _route()
        with _Server("slow") as url:
            client = sc.SystemOneClient(base_url=url, timeout=0.3)
            started = time.monotonic()
            d = sc.route(NON_CITATION, client=client)
            self.assertDirectDb(d, "timeout")
            self.assertTrue(d.fallback)
            self.assertLess(time.monotonic() - started, 1.8, "client did not honour its timeout")

    def test_any_transport_exception_routes_direct_db(self):
        import urllib.error
        sc = _route()
        client = sc.SystemOneClient(base_url="http://127.0.0.1:9", timeout=0.2)
        for exc in (urllib.error.URLError("down"), TimeoutError("t"), ConnectionResetError("r"),
                    OSError("o"), ValueError("v"), RuntimeError("boom"), MemoryError()):
            with self.subTest(exc=type(exc).__name__):
                with mock.patch("urllib.request.urlopen", side_effect=exc):
                    d = sc.route(NON_CITATION, client=client)
                    self.assertDirectDb(d, type(exc).__name__)
                    self.assertTrue(d.fallback)

    def test_requires_gate1_is_never_false(self):
        sc = _route()
        client = sc.SystemOneClient(base_url="http://127.0.0.1:9", timeout=0.2)
        for q in QUERIES:
            for threshold in (0.0, 0.5, 0.8, 1.0):
                with self.subTest(query=q, threshold=threshold):
                    d = sc.route(q, client=client, threshold=threshold)
                    self.assertIs(d.requires_gate1, True, repr(d))
                    self.assertEqual(d.route, "direct_db", repr(d))

if __name__ == "__main__":
    unittest.main()
