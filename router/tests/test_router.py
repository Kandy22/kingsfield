"""Router tests: contrastive pairs and fallback cases, no live server.

Contrastive pairs (Nimble's method, as applied here): each pair is two inputs
identical except for ONE controlled feature, and the test asserts the route
flips exactly when that feature flips. The in-process fake plays Von with a
fixed oracle (regex for a citation string) so only the router logic under
test varies.
"""
import os
import re
import socket
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from router import system_one_client as so  # noqa: E402
from router.system_one_client import (  # noqa: E402
    Choice, Noul, Score, SystemOneClient, SystemOneError, SystemOneResponse,
    route,
)

_PATCHES = []


def setUpModule():
    # route() with no client now selects the local model when JEV_MODEL_PATH is
    # set. Keep these tests independent of the developer's environment, and make
    # a real model load impossible (BaseException so route() cannot swallow it).
    from router import jev_cpu_inference as jev

    class RealModelLoadForbidden(BaseException):
        pass

    def forbid(*a, **k):
        raise RealModelLoadForbidden("router tests must never load a real model")

    for p in (mock.patch.object(jev, "_import_llama_class", forbid),
              mock.patch.dict(os.environ, {}, clear=False)):
        p.start()
        _PATCHES.append(p)
    os.environ.pop("VON_BASE_URL", None)
    os.environ.pop("JEV_MODEL_PATH", None)


def tearDownModule():
    for p in reversed(_PATCHES):
        p.stop()

CITE = re.compile(r"\d+\s+So\.\s*(2d|3d)?\s+\d+")


def resp(answer="vector_search", ch_conf=0.95, noul_raw=0.02, band="low",
         score=0.95):
    return SystemOneResponse(
        Choice(so.CHOICE_QUESTION, so.ROUTES, answer, ch_conf),
        Noul(so.NOUL_QUESTION, noul_raw, band),
        Score(so.SCORE_QUESTION, score))


class FakeClient:
    """Stands in for SystemOneClient; returns a canned or computed reply."""

    def __init__(self, reply=None, exc=None, fn=None):
        self.reply, self.exc, self.fn, self.calls = reply, exc, fn, []

    def query(self, query):
        self.calls.append(query)
        if self.exc:
            raise self.exc
        return self.fn(query) if self.fn else self.reply


def oracle(query):
    """Fake Von: a citation string drives noul_raw; keywords drive choice."""
    noul_raw = 0.97 if CITE.search(query) else 0.03
    answer = "boolean_search" if '"' in query or " AND " in query else "vector_search"
    return resp(answer=answer, noul_raw=noul_raw)


class ContrastivePairs(unittest.TestCase):
    def test_citation_string_present_vs_absent(self):
        with_cite = "What did Smith v. Jones, 123 So. 3d 456 (Fla. 2013) hold?"
        without = "What did Smith v. Jones, (Fla. 2013) hold?"
        a = route(with_cite, FakeClient(fn=oracle))
        b = route(without, FakeClient(fn=oracle))
        self.assertEqual(a.route, "direct_db")
        self.assertEqual(b.route, "vector_search")
        self.assertFalse(a.fallback)
        self.assertFalse(b.fallback)

    def test_boolean_operator_present_vs_absent(self):
        a = route('negligence AND "duty of care" landlord', FakeClient(fn=oracle))
        b = route("when is a landlord liable for negligence", FakeClient(fn=oracle))
        self.assertEqual((a.route, b.route), ("boolean_search", "vector_search"))

    def test_confidence_just_above_vs_just_below_threshold(self):
        hi = route("landlord duty", FakeClient(resp(score=0.80)))
        lo = route("landlord duty", FakeClient(resp(score=0.79)))
        self.assertEqual(hi.route, "vector_search")
        self.assertFalse(hi.fallback)
        self.assertEqual(lo.route, "direct_db")
        self.assertTrue(lo.fallback)

    def test_choice_confidence_also_gates(self):
        hi = route("landlord duty", FakeClient(resp(ch_conf=0.80)))
        lo = route("landlord duty", FakeClient(resp(ch_conf=0.79)))
        self.assertEqual((hi.route, lo.route), ("vector_search", "direct_db"))

    def test_gate_on_noul_raw_not_band_citation_present(self):
        # Same band label, only noul_raw differs.
        a = route("q", FakeClient(resp(noul_raw=0.95, band="low")))
        b = route("q", FakeClient(resp(noul_raw=0.05, band="low")))
        self.assertEqual((a.route, b.route), ("direct_db", "vector_search"))

    def test_gate_on_noul_raw_not_band_label_flip(self):
        # Same noul_raw, only the band label differs: route must not change.
        a = route("q", FakeClient(resp(noul_raw=0.05, band="high")))
        b = route("q", FakeClient(resp(noul_raw=0.05, band="low")))
        self.assertEqual(a.route, b.route)
        self.assertEqual(a.route, "vector_search")
        c = route("q", FakeClient(resp(noul_raw=0.95, band="low")))
        d = route("q", FakeClient(resp(noul_raw=0.95, band="high")))
        self.assertEqual((c.route, d.route), ("direct_db", "direct_db"))

    def test_noul_raw_boundaries(self):
        cases = [(0.80, "direct_db", False), (0.79, "direct_db", True),
                 (0.20, "vector_search", False), (0.21, "direct_db", True)]
        for raw, expect, fb in cases:
            with self.subTest(noul_raw=raw):
                d = route("q", FakeClient(resp(noul_raw=raw)))
                self.assertEqual((d.route, d.fallback), (expect, fb))

    def test_same_query_choice_answer_flips_route(self):
        a = route("q", FakeClient(resp(answer="boolean_search")))
        b = route("q", FakeClient(resp(answer="vector_search")))
        c = route("q", FakeClient(resp(answer="direct_db")))
        self.assertEqual([a.route, b.route, c.route],
                         ["boolean_search", "vector_search", "direct_db"])

    def test_custom_threshold_flips(self):
        r = resp(score=0.85)
        self.assertEqual(route("q", FakeClient(r), threshold=0.80).route, "vector_search")
        self.assertEqual(route("q", FakeClient(r), threshold=0.90).route, "direct_db")

    def test_english_vs_non_latin_script(self):
        eng = route("duty of care of a landlord", FakeClient(resp()))
        zh = FakeClient(resp())
        cn = route("房东的注意义务", zh)
        self.assertEqual(eng.route, "vector_search")
        self.assertEqual(cn.route, "direct_db")
        self.assertTrue(cn.fallback)
        self.assertEqual(zh.calls, [], "non-English query must not reach Von")


class FallbackCases(unittest.TestCase):
    def assert_fallback(self, d):
        self.assertEqual(d.route, "direct_db")
        self.assertTrue(d.fallback)
        self.assertTrue(d.requires_gate1)

    def test_von_base_url_unset(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VON_BASE_URL", None)
            self.assert_fallback(route("landlord duty"))

    def test_von_base_url_empty(self):
        with mock.patch.dict(os.environ, {"VON_BASE_URL": ""}):
            self.assert_fallback(route("landlord duty"))

    def test_unreachable_connection_refused(self):
        with mock.patch.dict(os.environ, {"VON_BASE_URL": "http://127.0.0.1:9"}):
            self.assert_fallback(route("landlord duty"))
        self.assert_fallback(route("q", SystemOneClient("http://127.0.0.1:9", timeout=0.5)))

    def test_non_http_scheme_rejected(self):
        for url in ("file:///etc/passwd", "ftp://x", "127.0.0.1:9"):
            with self.subTest(url=url):
                self.assert_fallback(route("q", SystemOneClient(url)))

    def test_exceptions_and_timeouts(self):
        for exc in (socket.timeout("t"), TimeoutError(), ConnectionRefusedError(),
                    SystemOneError("x"), RuntimeError("boom"), KeyError("k")):
            with self.subTest(exc=type(exc).__name__):
                self.assert_fallback(route("q", FakeClient(exc=exc)))

    def test_malformed_replies(self):
        good = {"choice": {"answer": "vector_search", "confidence": 0.9},
                "noul": {"noul_raw": 0.1, "noul": "low"},
                "score": {"value": 0.9}}
        self.assertEqual(route("q", FakeClient(good)).route, "vector_search")

        def mut(path, value):
            import copy
            d = copy.deepcopy(good)
            node = d
            for k in path[:-1]:
                node = node[k]
            if value is KeyError:
                del node[path[-1]]
            else:
                node[path[-1]] = value
            return d

        bad = [
            None, [], "x", {},
            mut(("choice",), KeyError),
            mut(("choice", "answer"), "llm_search"),
            mut(("choice", "answer"), None),
            mut(("choice", "confidence"), "0.9"),
            mut(("choice", "confidence"), True),
            mut(("noul", "noul_raw"), KeyError),
            mut(("noul", "noul_raw"), float("nan")),
            mut(("noul", "noul_raw"), 1.5),
            mut(("noul", "noul_raw"), -0.1),
            mut(("noul", "noul"), 3),
            mut(("score", "value"), None),
            mut(("score", "value"), float("nan")),
            mut(("score", "value"), 2),
        ]
        for i, payload in enumerate(bad):
            with self.subTest(i=i, payload=payload):
                self.assert_fallback(route("q", FakeClient(payload)))

    def test_nan_confidence_never_passes(self):
        r = resp()
        object.__setattr__(r.score, "value", float("nan"))
        self.assert_fallback(route("q", FakeClient(r)))

    def test_empty_and_non_string_query(self):
        for q in ("", "   ", "12345 §§", None, 42):
            with self.subTest(q=q):
                self.assert_fallback(route(q, FakeClient(resp())))


class ExactOptionAndRangeChecks(unittest.TestCase):
    """route() re-checks a response even when it was built in-process."""

    def assert_fallback(self, d):
        self.assertEqual((d.route, d.fallback), ("direct_db", True))

    def test_answer_must_be_exactly_an_allowed_route(self):
        for answer in ("vector_search ", "Vector_Search", "vector", "vector_search,boolean_search",
                       "", None, 3):
            with self.subTest(answer=answer):
                self.assert_fallback(route("q", FakeClient(resp(answer=answer))))

    def test_nan_or_out_of_range_noul_raw_falls_back(self):
        for raw in (float("nan"), float("inf"), -0.5, 1.5, True, None, "0.1"):
            with self.subTest(noul_raw=raw):
                self.assert_fallback(route("q", FakeClient(resp(noul_raw=raw))))

    def test_calibrated_defaults_false(self):
        d = route("q", FakeClient(resp()))
        self.assertEqual((d.route, d.calibrated), ("vector_search", False))
        self.assertFalse(resp().calibrated)
        self.assertEqual(so.DEFAULT_THRESHOLD, 0.80)


class GateOneAlwaysRequired(unittest.TestCase):
    def test_requires_gate1_on_every_route(self):
        replies = [resp(answer=a) for a in so.ROUTES] + [
            resp(noul_raw=0.99), resp(score=0.1), resp(noul_raw=0.5)]
        decisions = [route("q", FakeClient(r)) for r in replies]
        decisions.append(route("q", FakeClient(exc=RuntimeError())))
        decisions.append(route(""))
        for d in decisions:
            self.assertTrue(d.requires_gate1)
            self.assertIn(d.route, so.ROUTES)

    def test_requires_gate1_not_settable(self):
        d = route("q", FakeClient(resp()))
        with self.assertRaises(Exception):
            d.requires_gate1 = False
        with self.assertRaises(Exception):
            d.route = "boolean_search"


class ClientTransport(unittest.TestCase):
    """SystemOneClient against a patched urllib opener (no sockets)."""

    class FakeResp:
        def __init__(self, status=200, body=b""):
            self.status, self.body = status, body

        def read(self, n=-1):
            return self.body if n < 0 else self.body[:n]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(self, response=None, exc=None):
        op = mock.Mock()
        if exc:
            op.open.side_effect = exc
        else:
            op.open.return_value = response
        return op

    def run_with(self, op, base="http://von.invalid"):
        with mock.patch.object(so.urllib.request, "build_opener", return_value=op):
            return route("landlord duty", SystemOneClient(base))

    GOOD = (b'{"choice":{"answer":"boolean_search","confidence":0.9},'
            b'"noul":{"noul_raw":0.1,"noul":"low"},"score":{"value":0.9}}')

    def test_happy_path_and_request_shape(self):
        op = self.opener(self.FakeResp(200, self.GOOD))
        d = self.run_with(op, "http://von.invalid/")
        self.assertEqual((d.route, d.fallback), ("boolean_search", False))
        req = op.open.call_args.args[0]
        self.assertEqual(req.full_url, "http://von.invalid/v1/systemone")
        self.assertEqual(req.get_method(), "POST")
        import json
        body = json.loads(req.data)
        self.assertEqual(body["noul"]["question"], "Is a citation string present?")
        self.assertEqual(body["choice"]["options"], list(so.ROUTES))
        self.assertEqual(op.open.call_args.kwargs["timeout"], so.DEFAULT_TIMEOUT)

    def test_non_200_fallback(self):
        d = self.run_with(self.opener(self.FakeResp(500, self.GOOD)))
        self.assertTrue(d.fallback)

    def test_not_json_fallback(self):
        for body in (b"<html>", b"", b"\xff\xfe", b"[1,2]", b"NaN"):
            with self.subTest(body=body):
                self.assertTrue(self.run_with(self.opener(self.FakeResp(200, body))).fallback)

    def test_oversized_fallback(self):
        body = self.GOOD + b" " * (so.MAX_RESPONSE_BYTES + 10)
        self.assertTrue(self.run_with(self.opener(self.FakeResp(200, body))).fallback)

    def test_transport_errors_fallback(self):
        import urllib.error
        for exc in (urllib.error.URLError("refused"), socket.timeout(),
                    ConnectionResetError(), urllib.error.HTTPError("u", 302, "r", {}, None)):
            with self.subTest(exc=type(exc).__name__):
                self.assertTrue(self.run_with(self.opener(exc=exc)).fallback)

    def test_env_read_at_construction_time(self):
        with mock.patch.dict(os.environ, {"VON_BASE_URL": "http://a.invalid"}):
            self.assertEqual(SystemOneClient().base_url, "http://a.invalid")
        self.assertEqual(SystemOneClient("").base_url, "")

    def test_redirects_not_followed(self):
        h = so._NoRedirect()
        self.assertIsNone(h.redirect_request(None, None, 302, "", {}, "http://evil"))


if __name__ == "__main__":
    unittest.main()
