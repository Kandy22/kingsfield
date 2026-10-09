"""Von System One client, client selection, and the deterministic query router.

STATUS: the Von wire format below is an ASSUMPTION made by this module, to be
reconciled with a real server when one exists (2026-10-06 decisions: routing
now runs on a local llama.cpp model in router/jev_cpu_inference.py, and Von is
an optional alternative when VON_BASE_URL is configured).

Client selection (select_client(), used by route() when no client is passed)
    VON_BASE_URL set and non-empty  -> SystemOneClient (Von, the only network
                                       call in router/, never redirected)
    else JEV_MODEL_PATH set         -> LocalLlamaClient (in-process llama.cpp)
    else                            -> a client that raises -> direct_db

Pre-check (route(), before any client or model is consulted)
    pipeline.gate1.check_text(query) runs first. ANY result (pass, veto or
    fall_through, any kind) means the query holds something citation-shaped:
    route is direct_db, the model is never called, fallback=False. A pre-check
    exception is direct_db with fallback=True. Gate 1 still runs downstream on
    every route.

Response validation (route(), for every SystemOneResponse, not only parsed
dicts): choice.confidence, score.value and noul_raw must be real finite
numbers in [0, 1] (bool, str, None, NaN, inf are rejected); choice.options must
be exactly the three allowed routes; choice.answer must equal one of them.

Constraint C: `direct_db` is the hardcoded fallback and the model never
decides a route in free text. No hosted LLM APIs. Von client is stdlib urllib
only, talks only to VON_BASE_URL, and does not follow redirects.

UNCALIBRATED: the default threshold of 0.80 is a PLACEHOLDER. Local-model
confidence is a normalized log-likelihood over the allowed options, not a
measured probability. Responses and decisions carry `calibrated=False` until
router/calibration.py has measured the model on labeled contrastive pairs.

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
# The ONLY place decision-level calibration could later be switched on. It
# stays False. route() forces RouteDecision.calibrated to this constant and
# never copies a client's own `calibrated` claim. Turning it on requires a
# recorded measurement of the model on labeled contrastive pairs
# (router/calibration.py), per docs/context/decisions.md 2026-10-06, and an
# adversary review of that record.
CALIBRATION_RECORDED = False
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
    mass: Optional[float] = None   # local model only: un-normalized option mass


@dataclass(frozen=True)
class Noul:
    question: str
    noul_raw: float
    noul: str  # banded label; informational only, never gated on
    mass: Optional[float] = None   # local model only: Yes/No un-normalized mass


@dataclass(frozen=True)
class Score:
    question: str
    value: float


@dataclass(frozen=True)
class SystemOneResponse:
    choice: Choice
    noul: Noul
    score: Score
    calibrated: bool = False   # a client's claim; route() IGNORES it (CALIBRATION_RECORDED)
    source: str = "von"


@dataclass(frozen=True)
class RouteDecision:
    route: str
    reason: str
    choice: Optional[Choice]
    noul: Optional[Noul]
    score: Optional[Score]
    fallback: bool
    calibrated: bool = False   # always CALIBRATION_RECORDED (False); never the client's claim
    # Why this route, as a stable machine-readable label (reason is free text):
    #   model, noul_citation          the model was consulted and answered
    #   citation_precheck             gate1 pre-check found something citation-shaped
    #   english_gate, invalid_threshold, precheck_error, invalid_response,
    #   below_threshold, noul_uncertain
    #   mass_floor, timeout, breaker, unavailable, error   (client raised; the
    #   exception's `cause` attribute, default "error")
    cause: str = ""

    @property
    def requires_gate1(self) -> bool:
        # Constant on purpose: no route bypasses the deterministic veto.
        return True


class SystemOneError(Exception):
    """Any failure talking to, or parsing a reply from, Von or the local model.

    `cause` becomes RouteDecision.cause when route() catches it.
    """
    cause = "error"


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


def _fallback(reason: str, choice=None, noul=None, score=None,
              cause: str = "error") -> RouteDecision:
    return RouteDecision(FALLBACK_ROUTE, reason, choice, noul, score, True,
                         CALIBRATION_RECORDED, cause)


def _is_english_scriptable(query: str) -> bool:
    """Von is English-only: reject empty queries and non-Latin scripts."""
    letters = [ch for ch in query if ch.isalpha()]
    if not letters:
        return False
    return all(unicodedata.name(ch, "").startswith("LATIN") for ch in letters)


class _NoClient:
    """Nothing configured: always raises, so route() falls back to direct_db."""

    def query(self, query):
        raise SystemOneError("no router configured (VON_BASE_URL, JEV_MODEL_PATH)")


def select_client():
    """Von if VON_BASE_URL is set, else the local model if JEV_MODEL_PATH is
    set, else a client that raises. Never loads a model and never raises."""
    von = (os.environ.get("VON_BASE_URL") or "").strip()
    if von:
        return SystemOneClient(von)
    model = (os.environ.get("JEV_MODEL_PATH") or "").strip()
    if model:
        try:
            from .jev_cpu_inference import LocalLlamaClient  # lazy: no llama_cpp here
            return LocalLlamaClient(model)
        except Exception:
            return _NoClient()
    return _NoClient()


def _is_unit_number(x) -> bool:
    """A real, finite number in [0, 1]. Rejects bool, str, None, NaN, inf."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return False
    return math.isfinite(x) and 0.0 <= x <= 1.0


def _options_are_exactly_the_routes(options) -> bool:
    """Exactly boolean_search / vector_search / direct_db: no subset, superset
    or duplicate. Order does not matter."""
    return (isinstance(options, (list, tuple))
            and len(options) == len(ROUTES)
            and all(isinstance(o, str) for o in options)
            and set(options) == set(ROUTES))


def _response_problem(resp) -> Optional[str]:
    """Why a SystemOneResponse cannot be trusted, or None. Applies to every
    response object (a Von parse, a local client, or a fake), not only dicts."""
    choice, noul, score = resp.choice, resp.noul, resp.score
    if not (isinstance(choice, Choice) and isinstance(noul, Noul)
            and isinstance(score, Score)):
        return "response parts have the wrong type"
    if not _options_are_exactly_the_routes(choice.options):
        return "choice options are not exactly the allowed routes"
    if not isinstance(choice.answer, str) or choice.answer not in ROUTES:
        return "choice answer is not an allowed option"
    if not _is_unit_number(choice.confidence):
        return "choice.confidence is not a finite number in [0, 1]"
    if not _is_unit_number(score.value):
        return "score.value is not a finite number in [0, 1]"
    if not _is_unit_number(noul.noul_raw):
        return "noul_raw is not a finite number in [0, 1]"
    return None


def citation_precheck(query: str) -> Optional[str]:
    """Deterministic citation-shaped check, run before any model is consulted.

    Reuses pipeline.gate1.check_text (no second parser; read-only; a missing
    database is fine because non-citation text never touches it). ANY result
    (pass, veto or fall_through, any kind) means the query contains something
    citation-shaped. Returns a short description, or None when there is none.
    Raises on any error; the caller turns that into direct_db.
    """
    from pipeline.gate1 import check_text  # lazy: eyecite loads only when routing
    results = check_text(query)
    if not results:
        return None
    first = results[0]
    kind = getattr(first, "kind", "?")
    verdict = getattr(first, "verdict", "?")
    reason = getattr(first, "reason", "?")
    return f"{kind}/{verdict}/{reason}"


def route(query: str, client=None,
          threshold: float = DEFAULT_THRESHOLD) -> RouteDecision:
    """Pick a retrieval route; never raises, never leaves Gate 1."""
    try:
        if not isinstance(query, str) or not _is_english_scriptable(query):
            return _fallback("fallback: query empty or not English-script",
                             cause="english_gate")
        if not _is_unit_number(threshold) or threshold <= 0.0:
            return _fallback("fallback: invalid threshold", cause="invalid_threshold")
        # Deterministic pre-check, before any model: anything citation-shaped
        # goes to direct_db and no model is called. Gate 1 still runs downstream.
        try:
            found = citation_precheck(query)
        except Exception as exc:
            return _fallback(f"fallback: citation pre-check failed: {type(exc).__name__}",
                             cause="precheck_error")
        if found is not None:
            return RouteDecision(
                FALLBACK_ROUTE,
                f"citation-shaped text found by gate1 pre-check ({found}); model not consulted",
                None, None, None, False, CALIBRATION_RECORDED, "citation_precheck")
        if client is None:
            client = select_client()
        resp = client.query(query)
        if not isinstance(resp, SystemOneResponse):
            resp = parse_response(resp)  # tolerate a fake returning a raw dict
        problem = _response_problem(resp)
        if problem is not None:
            return _fallback(f"fallback: {problem}", cause="invalid_response")
        choice, noul, score = resp.choice, resp.noul, resp.score

        confidence = min(score.value, choice.confidence)
        if not confidence >= threshold:
            return _fallback(
                f"fallback: confidence {confidence:.2f} below {threshold:.2f}",
                choice, noul, score, cause="below_threshold")

        # Gate on noul_raw only; the banded label is never consulted. The
        # decision's `calibrated` is CALIBRATION_RECORDED, never resp.calibrated.
        if noul.noul_raw >= threshold:
            return RouteDecision(
                FALLBACK_ROUTE, "citation string present (noul_raw)",
                choice, noul, score, False, CALIBRATION_RECORDED, "noul_citation")
        if noul.noul_raw > 1.0 - threshold + 1e-9:
            return _fallback("fallback: citation presence uncertain (noul_raw)",
                             choice, noul, score, cause="noul_uncertain")
        return RouteDecision(choice.answer, f"{resp.source} choice: {choice.answer}",
                             choice, noul, score, False, CALIBRATION_RECORDED, "model")
    except Exception as exc:  # any error fails to the deterministic route
        cause = getattr(exc, "cause", "error")
        return _fallback(f"fallback: {type(exc).__name__}: {exc}",
                         cause=cause if isinstance(cause, str) else "error")
