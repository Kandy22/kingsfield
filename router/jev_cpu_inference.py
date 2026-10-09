"""Local llama.cpp (GGUF) router for Kingsfield Lawfare, CPU only.

Foundation: the user-authored JevCPURouter. Reworked in place so that it obeys
CLAUDE.md Constraint C (routing is deterministic code around a local model, and
`direct_db` is the hardcoded fallback) and the 2026-10-06 decisions entry.

What changed from the original, and why
    * `choice()` used to substring-match generated text and default to the
      first option. Both violate Constraint C. No text is generated now. The
      model is only asked "how likely is each allowed option as the
      continuation of this prompt?", and the answer is an argmax over exactly
      the allowed options.
    * `score()` (a model-written number parsed from free text) is gone.
      Confidence comes from token log-probabilities.
    * `llama_cpp` is imported lazily, only inside `_import_llama_class()`, so
      this module and its tests import without touching it.
    * No `logging.basicConfig`, no hard-coded model path, no network call.

How confidence is computed (never model-generated)
    For each allowed option the router sums the log-probabilities of ALL of
    that option's tokens, given the prompt (full-sequence log-likelihood, not
    first token only):

        loglik(option) = sum_j  log softmax(logits at position n_prompt+j-1)[tok_j]

    The option log-likelihoods are then softmax-normalized across EXACTLY the
    allowed options. The answer is the argmax; its confidence is its normalized
    probability. Choice options are exactly boolean_search / vector_search /
    direct_db. Noul uses the same method over exactly {"Yes", "No"} and
    noul_raw = normalized P("Yes").

    Score (the third primitive) is not an independent model output. The Score
    value handed to route() is the Choice confidence itself (the normalized
    probability of the winning route). route() already takes min(score, choice
    confidence), so this adds no extra gate; it is kept only so the response
    shape matches the Von wire format.

Absolute-mass floor
    Normalizing across the allowed options hides a model that puts almost no
    probability on ANY of them (it wants to say something else). So the total
    un-normalized probability, sum over options of exp(loglik), must clear a
    floor, separately for Choice (CHOICE_MASS_FLOOR) and Noul (NOUL_MASS_FLOOR).
    Below the floor the answer is direct_db. Both floors are PLACEHOLDERS,
    uncalibrated, like the 0.80 threshold. A total above 1 (impossible for
    mutually exclusive continuations) also fails closed.

Tokenization boundary check
    Each option is scored as tokenize(" " + option) appended after
    tokenize(prompt). That is only valid if the tokenizer would have produced
    the same tokens for the joined string, so for every option the router
    checks  tokenize(prompt + " " + option) == tokenize(prompt) +
    tokenize(" " + option, no BOS)  and fails closed to direct_db on any
    mismatch. This makes the leading-space / no-BOS assumption safe on any
    tokenizer (it may also reject some tokenizers outright; see calibration).

Hangs and the circuit breaker
    A llama.cpp call cannot be interrupted from Python. So every model load
    and every scoring call runs on a daemon worker thread with a join timeout
    (LOCAL_LOAD_TIMEOUT_S, LOCAL_INFERENCE_TIMEOUT_S), locks are acquired with
    a timeout (LOCAL_LOCK_TIMEOUT_S) and never held without a bound, and a
    timeout (hard or the soft deadline between evals) trips a circuit breaker: that router instance is marked
    unhealthy and is never used again, and the process-wide breaker keeps every
    route at direct_db until reset_shared_router() is called or the process is
    restarted. The abandoned worker thread cannot be killed; if a model truly
    hangs, restart the process rather than resetting.

UNCALIBRATED. These are normalized likelihoods over a closed set, not
calibrated probabilities. Small models are typically overconfident. Every
response and decision carries `calibrated=False`, and the 0.80 threshold in
system_one_client.py is a placeholder until `router/calibration.py` has been
run on labeled contrastive pairs with the real model.

Anything unusual goes to direct_db (by raising, so route() falls back): a tie
for the top option, a NaN/inf log-prob, an empty option tokenization, a
tokenization boundary mismatch, an option set that is not exactly the allowed
set, probability mass below the floor, a prompt that does not fit n_ctx, a
timeout, an open circuit breaker, a missing model file, a failed llama_cpp
import, a failed load.

llama.cpp surface this code uses (and the test stub fakes, nothing more)
    llm.tokenize(bytes, add_bos=bool, special=False) -> list[int]
    llm.reset()
    llm.eval(list[int])
    llm.scores[row]        (needs logits_all=True; row i = logits after token i)
    llm.n_tokens           (read, and assigned to rewind to the shared prompt)
    llm.n_ctx()            (optional; the configured n_ctx is used if absent)

REQUIRED BEFORE PRODUCTION, NOT YET DONE: a smoke test against a real GGUF
that the KV-cache rewind (assigning llm.n_tokens, then llm.eval) gives the same
log-probs as a fresh reset and full re-evaluation of prompt plus option.

Load policy for this Intel Mac's heat limits
    Nothing is sampled, so there is no decoding temperature. Threads: 4.
    Context: n_ctx=512. One model instance per process, behind a lock. With
    logits_all=True llama-cpp-python allocates n_ctx x n_vocab float32 logits,
    so keep n_ctx small.
"""

from __future__ import annotations

import math
import os
import threading
import time
from dataclasses import dataclass
from typing import Optional, Sequence

from .system_one_client import (
    CHOICE_QUESTION, NOUL_QUESTION, ROUTES, SCORE_QUESTION, Choice, Noul,
    Score, SystemOneError, SystemOneResponse, _unit_float,
)

MODEL_ENV = "JEV_MODEL_PATH"
NOUL_OPTIONS = ("Yes", "No")

DEFAULT_N_CTX = 512
DEFAULT_N_THREADS = 4
DEFAULT_N_BATCH = 256
# Module-level on purpose, so tests can shorten them. Read at call time.
LOCAL_INFERENCE_TIMEOUT_S = 15.0  # per primitive: worker join timeout and soft deadline
LOCAL_LOAD_TIMEOUT_S = 120.0      # worker join timeout for import + model load
LOCAL_LOCK_TIMEOUT_S = 30.0       # how long to wait for the router lock
MAX_QUERY_CHARS = 2000
TIE_EPSILON = 1e-6                # nats; top two option log-likelihoods this close = tie

# PLACEHOLDERS, uncalibrated: minimum total un-normalized probability of the
# allowed options (sum of exp(loglik)). Scale: a model answering in format puts
# about 0.5-0.9 of its mass on them and must pass; a total near 1e-7 or below
# means it wants to say something else and must veto. These sit well inside that
# range (two to five orders of magnitude from each side). Noul's Yes/No are
# single tokens, so its floor is a little higher.
CHOICE_MASS_FLOOR = 1e-2
NOUL_MASS_FLOOR = 5e-2
MASS_CEILING = 1.0 + 1e-6     # mutually exclusive continuations cannot exceed 1

# Placeholder band edges for the informational `noul` label. Never gated on.
BAND_LOW = 0.20
BAND_HIGH = 0.80


class ScoringError(SystemOneError):
    """Scoring could not produce a trustworthy answer; route() falls back."""


class MassFloorError(ScoringError):
    """The allowed options carry too little total probability mass."""
    cause = "mass_floor"


class InferenceTimeout(ScoringError):
    """A scoring call exceeded its time budget; the circuit breaker trips."""
    cause = "timeout"


class ModelUnavailable(SystemOneError):
    """Model file missing, llama_cpp not importable, or the load failed."""
    cause = "unavailable"


class CircuitOpen(ModelUnavailable):
    """The circuit breaker is open: a router instance or load timed out."""
    cause = "breaker"


class LoadTimeout(ModelUnavailable):
    """Importing or loading the model exceeded its time budget."""
    cause = "timeout"


class _Timeout(Exception):
    pass


def _call_with_timeout(fn, timeout: float):
    """Run fn() on a daemon worker thread; raise _Timeout if it does not finish.

    The worker cannot be killed. The caller must treat a _Timeout as "that
    llama object is poisoned" and never use it again.
    """
    box: dict = {}
    done = threading.Event()

    def target():
        try:
            box["value"] = fn()
        except BaseException as exc:  # carried back to the caller
            box["error"] = exc
        finally:
            done.set()

    worker = threading.Thread(target=target, name="jev-worker", daemon=True)
    worker.start()
    if not done.wait(timeout):
        raise _Timeout()
    if "error" in box:
        err = box["error"]
        if isinstance(err, Exception):
            raise err
        raise ScoringError(f"worker aborted: {type(err).__name__}")
    return box["value"]


# --------------------------------------------------------------------------
# Prompts. The model never writes the route; it only scores the continuations.
# --------------------------------------------------------------------------

def build_choice_prompt(text: str) -> str:
    return (
        "You route legal research queries to one retrieval method.\n"
        "boolean_search: the query is written as a search expression, with "
        "operators such as AND, OR, NOT between terms, or quoted exact "
        "phrases used as search terms.\n"
        "vector_search: the query is a plain-language question or topic about "
        "a legal concept. Quotation marks, or the words and/or used in "
        "ordinary English, do not make it a search expression.\n"
        "direct_db: the query asks for one specific known case or citation.\n\n"
        f"Query: {text}\n"
        "Route:"
    )


def build_noul_prompt(text: str) -> str:
    return (
        "Does the following text contain a formal legal citation string such "
        "as '100 So. 3d 200'? Answer Yes or No.\n\n"
        f"Text: {text}\n"
        "Answer:"
    )


# --------------------------------------------------------------------------
# Numerics
# --------------------------------------------------------------------------

def _token_logprob(row, token_id: int) -> float:
    """log softmax(row)[token_id]. Raises ScoringError on any non-finite value.

    NaN or +inf anywhere in the row is corruption. -inf on other tokens is a
    masked token and harmless. -inf on the target token means the option is
    impossible, which is not usable evidence, so it raises.
    """
    try:
        import numpy as np
    except ImportError:
        np = None
    if np is not None:
        arr = np.asarray(row, dtype=np.float64)
        if arr.ndim != 1 or not 0 <= token_id < arr.shape[0]:
            raise ScoringError("logits row has the wrong shape")
        if bool(np.isnan(arr).any()):
            raise ScoringError("NaN in logits")
        top = float(arr.max())
        target = float(arr[token_id])
        if not math.isfinite(top) or not math.isfinite(target):
            raise ScoringError("non-finite logit")
        with np.errstate(all="ignore"):
            total = float(np.exp(arr - top).sum())
    else:
        vals = [float(x) for x in row]
        if not 0 <= token_id < len(vals):
            raise ScoringError("logits row has the wrong shape")
        if any(math.isnan(v) for v in vals):
            raise ScoringError("NaN in logits")
        top = max(vals)
        target = vals[token_id]
        if not math.isfinite(top) or not math.isfinite(target):
            raise ScoringError("non-finite logit")
        total = math.fsum(math.exp(v - top) for v in vals)
    lp = (target - top) - math.log(total)
    if not math.isfinite(lp) or lp > 1e-9:
        raise ScoringError("non-finite log-prob")
    return min(lp, 0.0)


def normalize_logliks(logliks: dict) -> dict:
    """Softmax across exactly the given options. Raises on non-finite input."""
    if not logliks:
        raise ScoringError("no options")
    for k, v in logliks.items():
        if not isinstance(v, float) or not math.isfinite(v):
            raise ScoringError(f"non-finite log-likelihood for {k!r}")
    top = max(logliks.values())
    exps = {k: math.exp(v - top) for k, v in logliks.items()}
    total = math.fsum(exps.values())
    if not math.isfinite(total) or total <= 0.0:
        raise ScoringError("cannot normalize")
    return {k: e / total for k, e in exps.items()}


def pick_top(logliks: dict, probs: dict):
    """Argmax by log-likelihood. A tie for the top raises (never first-wins)."""
    ordered = sorted(logliks.items(), key=lambda kv: kv[1], reverse=True)
    if len(ordered) > 1 and ordered[0][1] - ordered[1][1] <= TIE_EPSILON:
        raise ScoringError("tie for the top option")
    answer = ordered[0][0]
    return answer, probs[answer]


@dataclass(frozen=True)
class ChoiceResult:
    answer: str
    confidence: float          # normalized probability of the answer
    probabilities: dict        # option -> normalized probability
    mass: float = 1.0          # un-normalized total probability of the options
    calibrated: bool = False


@dataclass(frozen=True)
class NoulResult:
    noul_raw: float            # normalized P("Yes") in [0, 1]
    probabilities: dict
    mass: float = 1.0
    calibrated: bool = False


# --------------------------------------------------------------------------
# Router over a llama.cpp-like object
# --------------------------------------------------------------------------

class JevCPURouter:
    """Scores closed option sets with a llama.cpp model. Never generates text."""

    def __init__(self, llm, n_ctx: Optional[int] = None,
                 timeout: Optional[float] = None, path: Optional[str] = None,
                 lock_timeout: Optional[float] = None,
                 choice_mass_floor: Optional[float] = None,
                 noul_mass_floor: Optional[float] = None):
        self.llm = llm
        self.path = path
        self.timeout = LOCAL_INFERENCE_TIMEOUT_S if timeout is None else timeout
        self.lock_timeout = LOCAL_LOCK_TIMEOUT_S if lock_timeout is None else lock_timeout
        self.choice_mass_floor = (CHOICE_MASS_FLOOR if choice_mass_floor is None
                                  else choice_mass_floor)
        self.noul_mass_floor = (NOUL_MASS_FLOOR if noul_mass_floor is None
                                else noul_mass_floor)
        if n_ctx is None:
            n_ctx = llm.n_ctx()
        if isinstance(n_ctx, bool) or not isinstance(n_ctx, int) or n_ctx < 8:
            raise ModelUnavailable("invalid n_ctx")
        self.n_ctx = n_ctx
        self._lock = threading.Lock()  # a llama context is not thread-safe
        self._unhealthy: Optional[str] = None

    @property
    def unhealthy(self) -> Optional[str]:
        """Reason the circuit breaker tripped for this instance, else None."""
        return self._unhealthy

    def _trip(self, reason: str) -> None:
        if self._unhealthy is None:
            self._unhealthy = reason

    @classmethod
    def load(cls, model_path: str, n_ctx: int = DEFAULT_N_CTX,
             n_threads: int = DEFAULT_N_THREADS,
             timeout: Optional[float] = None,
             load_timeout: Optional[float] = None) -> "JevCPURouter":
        """Load a GGUF. Raises ModelUnavailable (LoadTimeout on a hang)."""
        if not isinstance(model_path, str) or not model_path.strip():
            raise ModelUnavailable("no model path")
        model_path = os.path.realpath(os.path.expanduser(model_path.strip()))
        if not os.path.isfile(model_path):
            raise ModelUnavailable("model file not found")

        def build():
            try:
                llama_cls = _import_llama_class()
            except Exception as exc:
                raise ModelUnavailable(
                    f"llama_cpp unavailable: {type(exc).__name__}") from exc
            try:
                return llama_cls(
                    model_path=model_path, n_ctx=n_ctx, n_batch=DEFAULT_N_BATCH,
                    n_threads=n_threads, n_threads_batch=n_threads,
                    n_gpu_layers=0, logits_all=True, seed=0, verbose=False)
            except Exception as exc:
                raise ModelUnavailable(
                    f"model load failed: {type(exc).__name__}") from exc

        budget = LOCAL_LOAD_TIMEOUT_S if load_timeout is None else load_timeout
        try:
            llm = _call_with_timeout(build, budget)
        except _Timeout:
            raise LoadTimeout("model import/load timed out") from None
        return cls(llm, n_ctx=n_ctx, timeout=timeout, path=model_path)

    # -- core scoring -------------------------------------------------------

    def _score_options(self, prompt: str, options: Sequence[str]) -> dict:
        """Full-sequence log-likelihood of each option given the prompt."""
        llm = self.llm
        deadline = time.monotonic() + self.timeout

        def check_time():
            if time.monotonic() > deadline:
                self._trip("soft deadline exceeded")
                raise InferenceTimeout("soft deadline exceeded")

        prompt_tokens = list(llm.tokenize(prompt.encode("utf-8"),
                                          add_bos=True, special=False))
        n_prompt = len(prompt_tokens)
        if n_prompt < 1:
            raise ScoringError("empty prompt tokenization")

        option_tokens = {}
        for opt in options:
            # Leading space lives on the continuation (lm-eval convention).
            cont = " " + opt
            toks = list(llm.tokenize(cont.encode("utf-8"),
                                     add_bos=False, special=False))
            if not toks:
                raise ScoringError(f"empty tokenization for option {opt!r}")
            if not all(isinstance(t, int) and not isinstance(t, bool)
                       for t in toks):
                raise ScoringError("tokenizer returned non-integer tokens")
            # The split is only valid if the joined string tokenizes the same.
            joint = list(llm.tokenize((prompt + cont).encode("utf-8"),
                                      add_bos=True, special=False))
            if joint != prompt_tokens + toks:
                raise ScoringError(
                    f"tokenization boundary mismatch for option {opt!r}")
            option_tokens[opt] = toks
        if n_prompt + max(len(t) for t in option_tokens.values()) > self.n_ctx:
            raise ScoringError("prompt does not fit in n_ctx")

        llm.reset()
        llm.eval(prompt_tokens)
        if llm.n_tokens != n_prompt:
            raise ScoringError("unexpected model state after prompt")
        check_time()

        logliks = {}
        for opt in options:
            toks = option_tokens[opt]
            llm.n_tokens = n_prompt           # rewind to the shared prompt
            llm.eval(toks)
            if llm.n_tokens != n_prompt + len(toks):
                raise ScoringError("unexpected model state after option")
            total = 0.0
            for j, tok in enumerate(toks):
                # logits row (n_prompt + j - 1) predicts the token at n_prompt + j
                total += _token_logprob(llm.scores[n_prompt + j - 1], tok)
            if not math.isfinite(total):
                raise ScoringError("non-finite log-likelihood")
            logliks[opt] = float(total)
            check_time()
        return logliks

    def _classify(self, prompt: str, options: Sequence[str], mass_floor: float):
        logliks = self._score_options(prompt, options)
        mass = math.fsum(math.exp(v) for v in logliks.values())
        if not math.isfinite(mass) or mass > MASS_CEILING:
            raise ScoringError("option probability mass is not a valid probability")
        if not mass >= mass_floor:
            raise MassFloorError(
                f"option probability mass {mass:.3g} below floor {mass_floor}")
        probs = normalize_logliks(logliks)
        answer, conf = pick_top(logliks, probs)
        return answer, conf, probs, mass

    def _guarded(self, prompt: str, options: Sequence[str], mass_floor: float):
        """Lock with a timeout, health check, then score on a bounded worker."""
        if self._unhealthy is not None:
            raise CircuitOpen(f"circuit open: {self._unhealthy}")
        if not self._lock.acquire(timeout=self.lock_timeout):
            raise ScoringError("router busy: lock timeout")
        try:
            if self._unhealthy is not None:
                raise CircuitOpen(f"circuit open: {self._unhealthy}")
            try:
                return _call_with_timeout(
                    lambda: self._classify(prompt, options, mass_floor),
                    self.timeout)
            except _Timeout:
                self._trip("inference timed out")
                raise InferenceTimeout("inference timed out") from None
        finally:
            self._lock.release()

    # -- primitives ---------------------------------------------------------

    @staticmethod
    def _check_text(text) -> None:
        if not isinstance(text, str) or not text.strip():
            raise ScoringError("empty or non-string query")
        if len(text) > MAX_QUERY_CHARS:
            raise ScoringError("query too long")

    def choice(self, text: str, options: Sequence[str] = ROUTES) -> ChoiceResult:
        """Closed choice over exactly boolean_search / vector_search / direct_db."""
        self._check_text(text)
        if (not isinstance(options, (list, tuple))
                or len(options) != len(ROUTES)
                or set(options) != set(ROUTES)):
            raise ScoringError("option set is not exactly the allowed routes")
        ordered = list(ROUTES)  # canonical order; never depends on caller order
        answer, conf, probs, mass = self._guarded(
            build_choice_prompt(text), ordered, self.choice_mass_floor)
        return ChoiceResult(answer, conf, probs, mass)

    def noul(self, text: str) -> NoulResult:
        """Is a citation string present? noul_raw = normalized P("Yes")."""
        self._check_text(text)
        _, _, probs, mass = self._guarded(
            build_noul_prompt(text), list(NOUL_OPTIONS), self.noul_mass_floor)
        return NoulResult(probs["Yes"], probs, mass)


# --------------------------------------------------------------------------
# Lazy llama_cpp import and the lock-guarded one-per-process singleton
# --------------------------------------------------------------------------

def _import_llama_class():
    """The only place llama_cpp is imported."""
    from llama_cpp import Llama
    return Llama


_STATE_LOCK = threading.Lock()   # guards the three fields below; held briefly
_LOAD_LOCK = threading.Lock()    # serializes loads; held at most load_timeout + slack
_SHARED: Optional[JevCPURouter] = None
_SHARED_FAILURE: Optional[tuple] = None  # (path, message): do not retry a load
_BREAKER: Optional[str] = None           # process-wide: a load hung


def reset_shared_router() -> None:
    """Drop the process-wide router, any cached load failure, and close the
    circuit breaker. A hung worker thread cannot be killed; if a model really
    hung, restart the process instead."""
    global _SHARED, _SHARED_FAILURE, _BREAKER
    with _STATE_LOCK:
        _SHARED = None
        _SHARED_FAILURE = None
        _BREAKER = None


def _shared_or_raise(real: str) -> Optional[JevCPURouter]:
    """Caller holds _STATE_LOCK. Return a usable router, None to load, or raise."""
    if _BREAKER is not None:
        raise CircuitOpen(f"circuit open: {_BREAKER}")
    if _SHARED is not None:
        if _SHARED.unhealthy is not None:
            raise CircuitOpen(f"circuit open: {_SHARED.unhealthy}")
        if _SHARED.path != real:
            raise ModelUnavailable(
                "a different model is already loaded in this process")
        return _SHARED
    if _SHARED_FAILURE is not None and _SHARED_FAILURE[0] == real:
        raise ModelUnavailable(f"earlier load failed: {_SHARED_FAILURE[1]}")
    return None


def get_shared_router(model_path: str, n_ctx: Optional[int] = None,
                      n_threads: Optional[int] = None,
                      load_timeout: Optional[float] = None) -> JevCPURouter:
    """One model instance per process. Raises ModelUnavailable on any problem.

    The model file is checked on every call (a missing file is never cached).
    A failed load is cached by path so repeated queries do not re-attempt a
    heavy load; a hung load or a timed-out scoring call opens the circuit
    breaker. Both clear only through reset_shared_router(). Asking for a
    different path while a model is loaded raises: one instance per process.
    A hung instance is never reused. No lock is held without a bound.
    """
    global _SHARED, _SHARED_FAILURE, _BREAKER
    if not isinstance(model_path, str) or not model_path.strip():
        raise ModelUnavailable("no model path")
    real = os.path.realpath(os.path.expanduser(model_path.strip()))
    if not os.path.isfile(real):
        raise ModelUnavailable("model file not found")
    with _STATE_LOCK:
        found = _shared_or_raise(real)
    if found is not None:
        return found
    budget = LOCAL_LOAD_TIMEOUT_S if load_timeout is None else load_timeout
    if not _LOAD_LOCK.acquire(timeout=budget + 5.0):
        raise ModelUnavailable("another model load is taking too long")
    try:
        with _STATE_LOCK:
            found = _shared_or_raise(real)
        if found is not None:
            return found
        try:
            router = JevCPURouter.load(
                real, n_ctx=DEFAULT_N_CTX if n_ctx is None else n_ctx,
                n_threads=DEFAULT_N_THREADS if n_threads is None else n_threads,
                load_timeout=budget)
        except LoadTimeout as exc:
            with _STATE_LOCK:
                _BREAKER = str(exc)
            raise
        except Exception as exc:
            with _STATE_LOCK:
                _SHARED_FAILURE = (real, str(exc))
            if isinstance(exc, ModelUnavailable):
                raise
            raise ModelUnavailable(f"load failed: {type(exc).__name__}") from exc
        with _STATE_LOCK:
            _SHARED = router
        return router
    finally:
        _LOAD_LOCK.release()


# --------------------------------------------------------------------------
# Client with the same interface route() already uses
# --------------------------------------------------------------------------

def _band(noul_raw: float) -> str:
    if noul_raw >= BAND_HIGH:
        return "high"
    if noul_raw <= BAND_LOW:
        return "low"
    return "mid"


class LocalLlamaClient:
    """query(query) -> SystemOneResponse, answered by the local model.

    Construction never loads anything and never raises. The model is loaded
    (once per process) on the first query(); any failure raises SystemOneError
    subclasses, which route() turns into direct_db.
    """

    source = "local_llama"

    def __init__(self, model_path: Optional[str] = None, *,
                 router: Optional[JevCPURouter] = None,
                 n_ctx: Optional[int] = None,
                 n_threads: Optional[int] = None):
        if model_path is None:
            model_path = os.environ.get(MODEL_ENV)
        self.model_path = (model_path or "").strip()
        self._router = router
        self.n_ctx = n_ctx
        self.n_threads = n_threads

    def query(self, query: str) -> SystemOneResponse:
        router = self._router
        if router is None:
            router = get_shared_router(self.model_path, self.n_ctx, self.n_threads)
        ch = router.choice(query)
        nl = router.noul(query)
        conf = _unit_float(ch.confidence, "choice.confidence")
        noul_raw = _unit_float(nl.noul_raw, "noul_raw")
        return SystemOneResponse(
            Choice(CHOICE_QUESTION, ROUTES, ch.answer, conf, ch.mass),
            Noul(NOUL_QUESTION, noul_raw, _band(noul_raw), nl.mass),
            # Score is the Choice confidence (log-prob derived), not a
            # separately generated number. See the module docstring.
            Score(SCORE_QUESTION, conf),
            calibrated=False,
            source=self.source,
        )
