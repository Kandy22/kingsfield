"""Stub Von System One client and the deterministic query router.

STATUS: STUB. No real Von server exists yet (Von does not run on this Intel
Mac; see docs/context/decisions.md). The wire format below is an ASSUMPTION
made by this module, to be reconciled with the real server when it is
available. Until then every production call routes to `direct_db`.

Constraint C: routing decisions go only to a Von System One endpoint through
this client, and `direct_db` is the hardcoded fallback. No hosted LLM APIs.
This client is the only network call in router/. It is stdlib urllib only,
talks only to VON_BASE_URL, and does not follow redirects.

Primitives (what Von is asked)
    Choice  "Which retrieval route fits this query?"
            options: boolean_search | vector_search | direct_db
    Noul    "Is a citation string present?"
            gated on `noul_raw` (float 0..1), never the banded `noul` label
    Score   "Confidence metric" (float 0..1)

Assumed request:  POST {VON_BASE_URL}/v1/systemone
    Content-Type: application/json
    {
      "query": "<user query, English>",
      "choice": {"question": "...", "options": ["boolean_search", "vector_search", "direct_db"]},
      "noul":   {"question": "Is a citation string present?"},
      "score":  {"question": "Confidence metric"}
    }

Assumed response (HTTP 200, JSON):
    {
      "choice": {"answer": "vector_search", "confidence": 0.93},
      "noul":   {"noul_raw": 0.04, "noul": "low"},
      "score":  {"value": 0.91}
    }
    `noul` is the banded label ("low" / "mid" / "high"); it is parsed and
    carried but never used to decide anything.

Routing rules (all deterministic code, evaluated here, never by a model)
    direct_db, with fallback=True, when: VON_BASE_URL unset or empty, bad URL
    scheme, connection refused, timeout, any exception, non-200, non-JSON,
    oversized or malformed response (missing field, wrong type, NaN, out of
    range, unknown choice answer), non-Latin-script or empty query (Von is
    English-only), or confidence below threshold. Confidence is the Score
    value and the Choice confidence; the lower of the two must reach the
    threshold (default 0.80, Von's measured default).

    With a well-formed, confident response:
      noul_raw >= threshold                  -> direct_db (citation present;
                                                 deterministic lookup)
      (1 - threshold) < noul_raw < threshold -> direct_db (cannot tell
                                                 whether a citation is present)
      noul_raw <= 1 - threshold              -> follow the Choice answer

Every route terminates at Gate 1: `RouteDecision.requires_gate1` is always
True. Routing picks a retrieval strategy; it never replaces the veto.
"""

from __future__ import annotations

import json
import math
import os
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

ROUTES = ("boolean_search", "vector_search", "direct_db")
FALLBACK_ROUTE = "direct_db"
DEFAULT_THRESHOLD = 0.80
DEFAULT_TIMEOUT = 2.0
MAX_RESPONSE_BYTES = 64 * 1024
ENDPOINT_PATH = "/v1/systemone"

CHOICE_QUESTION = "Which retrieval route fits this query?"
NOUL_QUESTION = "Is a citation string present?"
SCORE_QUESTION = "Confidence metric"


@dataclass(frozen=True)
class Choice:
    question: str
    options: tuple
    answer: str
    confidence: float


@dataclass(frozen=True)
class Noul:
    question: str
    noul_raw: float
    noul: str  # banded label; informational only, never gated on


@dataclass(frozen=True)
class Score:
    question: str
    value: float


@dataclass(frozen=True)
class SystemOneResponse:
    choice: Choice
    noul: Noul
    score: Score


@dataclass(frozen=True)
class RouteDecision:
    route: str
    reason: str
    choice: Optional[Choice]
    noul: Optional[Noul]
    score: Optional[Score]
    fallback: bool

    @property
    def requires_gate1(self) -> bool:
        # Constant on purpose: no route bypasses the deterministic veto.
        return True


class SystemOneError(Exception):
    """Any failure talking to, or parsing a reply from, Von."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _unit_float(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SystemOneError(f"malformed response: {name} is not a number")
    value = float(value)
    if math.isnan(value) or not 0.0 <= value <= 1.0:
        raise SystemOneError(f"malformed response: {name} outside [0, 1]")
    return value


def _section(payload, key: str) -> dict:
    section = payload.get(key) if isinstance(payload, dict) else None
    if not isinstance(section, dict):
        raise SystemOneError(f"malformed response: missing {key}")
    return section


def parse_response(payload) -> SystemOneResponse:
    """Validate a decoded Von reply; raise SystemOneError on any defect."""
    c = _section(payload, "choice")
    answer = c.get("answer")
    if answer not in ROUTES:
        raise SystemOneError("malformed response: unknown choice answer")
    choice = Choice(CHOICE_QUESTION, ROUTES, answer,
                    _unit_float(c.get("confidence"), "choice.confidence"))

    n = _section(payload, "noul")
    band = n.get("noul")
    if not isinstance(band, str):
        raise SystemOneError("malformed response: noul band is not a string")
    noul = Noul(NOUL_QUESTION, _unit_float(n.get("noul_raw"), "noul_raw"), band)

    s = _section(payload, "score")
    score = Score(SCORE_QUESTION, _unit_float(s.get("value"), "score.value"))
    return SystemOneResponse(choice, noul, score)


class SystemOneClient:
    """POSTs the three primitives to {base_url}/v1/systemone.

    base_url=None reads VON_BASE_URL at construction time. An empty or unset
    base URL is valid to construct; query() then raises SystemOneError so
    route() falls back to direct_db.
    """

    def __init__(self, base_url: Optional[str] = None,
                 timeout: float = DEFAULT_TIMEOUT):
        if base_url is None:
            base_url = os.environ.get("VON_BASE_URL")
        self.base_url = (base_url or "").strip()
        self.timeout = timeout

    def query(self, query: str) -> SystemOneResponse:
        if not self.base_url:
            raise SystemOneError("VON_BASE_URL not set")
        if not self.base_url.lower().startswith(("http://", "https://")):
            raise SystemOneError("VON_BASE_URL must be http(s)")
        body = json.dumps({
            "query": query,
            "choice": {"question": CHOICE_QUESTION, "options": list(ROUTES)},
            "noul": {"question": NOUL_QUESTION},
            "score": {"question": SCORE_QUESTION},
        }).encode("utf-8")
        req = urllib.request.Request(
            self.base_url.rstrip("/") + ENDPOINT_PATH, data=body, method="POST",
            headers={"Content-Type": "application/json",
                     "Accept": "application/json"})
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(req, timeout=self.timeout) as resp:
                if resp.status != 200:
                    raise SystemOneError(f"HTTP {resp.status}")
                raw = resp.read(MAX_RESPONSE_BYTES + 1)
        except SystemOneError:
            raise
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise SystemOneError(f"transport: {type(exc).__name__}") from exc
        if len(raw) > MAX_RESPONSE_BYTES:
            raise SystemOneError("malformed response: too large")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise SystemOneError("malformed response: not JSON") from exc
        return parse_response(payload)


def _fallback(reason: str, choice=None, noul=None, score=None) -> RouteDecision:
    return RouteDecision(FALLBACK_ROUTE, reason, choice, noul, score, True)


def _is_english_scriptable(query: str) -> bool:
    """Von is English-only: reject empty queries and non-Latin scripts."""
    letters = [ch for ch in query if ch.isalpha()]
    if not letters:
        return False
    return all(unicodedata.name(ch, "").startswith("LATIN") for ch in letters)


def route(query: str, client: Optional[SystemOneClient] = None,
          threshold: float = DEFAULT_THRESHOLD) -> RouteDecision:
    """Pick a retrieval route; never raises, never leaves Gate 1."""
    try:
        if not isinstance(query, str) or not _is_english_scriptable(query):
            return _fallback("fallback: query empty or not English-script")
        if client is None:
            client = SystemOneClient()
        resp = client.query(query)
        if not isinstance(resp, SystemOneResponse):
            resp = parse_response(resp)  # tolerate a fake returning a raw dict
        choice, noul, score = resp.choice, resp.noul, resp.score

        confidence = min(score.value, choice.confidence)
        if not confidence >= threshold:
            return _fallback(
                f"fallback: confidence {confidence:.2f} below {threshold:.2f}",
                choice, noul, score)

        # Gate on noul_raw only; the banded label is never consulted.
        if noul.noul_raw >= threshold:
            return RouteDecision(
                FALLBACK_ROUTE, "citation string present (noul_raw)",
                choice, noul, score, False)
        if noul.noul_raw > 1.0 - threshold + 1e-9:
            return _fallback("fallback: citation presence uncertain (noul_raw)",
                             choice, noul, score)
        return RouteDecision(choice.answer, f"von choice: {choice.answer}",
                             choice, noul, score, False)
    except Exception as exc:  # any error fails to the deterministic route
        return _fallback(f"fallback: {type(exc).__name__}: {exc}")
