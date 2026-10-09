"""Adversarial suite for the JEV CPU router (CLAUDE.md Constraints C and E).

Everything here is stdlib unittest plus numpy (already in ~/.venv-cascade).
NO real GGUF is ever loaded and llama_cpp is never really imported: a stub
`llama_cpp` module with a toy token-level language model is injected into
sys.modules. The toy model is a pure function of its context, so the true
full-sequence log-likelihood of every option is known exactly (see Cfg).

The suite drives route() end to end (no dependence on builder-internal class
names) plus static AST checks over router/*.py. Every adversarial input must
reach `direct_db` with requires_gate1 True; controls (a confident, honest
model) must route to the chosen option so a router that always falls back
cannot satisfy the suite.

Toy model facts the tests rely on
  * Tokens: words / punctuation / whitespace; options are multi-token
    (boolean_search = boolean + _ + search; Yes / No are single tokens).
  * P(first token) = Cfg.choice_w (or Cfg.noul_w); P(second token | first)
    = Cfg.cont[option] (default 1); later tokens are deterministic. The full
    sequence probability of an option is therefore w * cont exactly.
  * Mass not on an option goes to an unrelated junk token.
  * Generated text (create_completion / __call__) is whatever Cfg.gen_text
    says, independent of the log-probs, so a router that decides from
    generated text can be told apart from one that decides from log-probs.
  * The stub reproduces llama-cpp-python's failure behaviour: a missing,
    unreadable, directory or non-GGUF model path raises ValueError, and
    eval past n_ctx raises ValueError. Both log-prob APIs are provided
    (tokenize/eval/scores/n_tokens and create_completion(echo, logprobs)).
"""

import ast
import json
import math
import os
import re
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.error
import urllib.request
import zlib
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import numpy as np

REPO = Path(__file__).resolve().parents[2]
ROUTER_DIR = REPO / "router"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

ROUTES = ("boolean_search", "vector_search", "direct_db")
Q = "What cases discuss adverse possession of beachfront property?"
CITE_Q = "Smith v. State, 100 So. 3d 200 (Fla. 4th DCA 2012)."

V = 1024
FLOOR = -1e4
BOS, JUNK = 1, 2


# --------------------------------------------------------------------------
# toy language model
# --------------------------------------------------------------------------

class Cfg:
    def __init__(self):
        self.reset()

    def reset(self):
        self.choice_w = {"boolean_search": 0.015, "vector_search": 0.97, "direct_db": 0.015}
        self.noul_w = {"Yes": 0.02, "No": 0.95}
        self.cont = {}                # option -> P(second token | first token)
        self.gen_text = None          # what generation "says" (independent of log-probs)
        self.poison_all = None        # nan | inf | ninf | zeros | none | narrow | empty
        self.poison_option = None     # (option, value) put on that option's final token
        self.raise_all = None         # exception instance raised by every entry point
        self.hang_infer = False       # block tokenize/eval/create_completion
        self.hang_ctor = False
        self.empty_tokenize = False
        self.empty_opt_tokenize = set()
        self.ctor_error = None
        self.ctor_attempts = 0
        self.constructed = 0
        self.calls = 0
        self.active = 0
        self.overlap = False
        self.lock = threading.Lock()
        self.release = threading.Event()
        self.gen_calls = 0
        self.entries = 0              # every entry into any stub model method (incl. tokenize)
        self.tok_merge = False        # tokenizing prompt+option merges the boundary (differs from separate calls)
        self.tok_bad = None           # bool | float | str | neg | huge : tokenizer returns unusable ids
        self.tok_calls = []           # (add_bos,) per tokenize call
        self.t2i = {}
        self.i2t = {BOS: "<s>", JUNK: "<junk>"}
        self.score_calls = 0
        # Per-test memo of the toy model's logit rows (a pure function of the config key and the
        # option-prefix state). Cleared here on every reset; switched OFF for the hang, breaker
        # and concurrency tests so they run the stub live.
        self.row_cache_on = True
        self.row_cache = {}
        self.seq_cache = {}
        self.cf_cache = {}

    def choice_first(self):
        key = tuple(self.choice_w)
        hit = self.cf_cache.get(key)
        if hit is None:
            hit = self.cf_cache[key] = {_seq(o)[0] for o in self.choice_w}
        return hit


S = Cfg()


def split_tokens(text):
    return re.findall(r"\s?[A-Za-z0-9]+|\s|[^\sA-Za-z0-9]", text, re.S)


def _seq(option):
    return [t.strip() for t in split_tokens(option) if t.strip()]


def _tid(text):
    i = S.t2i.get(text)
    if i is None:
        n = 3 + len(S.t2i)
        if n < V:
            i = n
            S.t2i[text] = i
            S.i2t[i] = text
        else:
            i = 3 + zlib.crc32(text.encode("utf-8", "replace")) % (V - 3)
    return i


def _cfg_key():
    return (tuple(S.choice_w.items()), tuple(S.noul_w.items()), tuple(S.cont.items()),
            S.poison_option, S.poison_all)


def make_row(words, fam):
    opts = S.choice_w if fam == "choice" else S.noul_w
    ckey = _cfg_key() if S.row_cache_on else None
    seqs = S.seq_cache.get((ckey, fam)) if ckey is not None else None
    if seqs is None:
        seqs = {o: _seq(o) for o in opts}
        if ckey is not None:
            S.seq_cache[(ckey, fam)] = seqs
    k_state, matches = 0, list(seqs)
    longest = max(len(s) for s in seqs.values())
    for k in range(min(len(words), longest - 1), 0, -1):
        m = [o for o, s in seqs.items() if len(s) > k and s[:k] == words[-k:]]
        if m:
            k_state, matches = k, m
            break
    rkey = (ckey, fam, k_state, tuple(matches)) if ckey is not None else None
    if rkey is not None:
        hit = S.row_cache.get(rkey)
        if hit is not None:
            return hit
    row = _build_row(opts, seqs, k_state, matches)
    if rkey is not None:
        S.row_cache[rkey] = row
    return row


def _build_row(opts, seqs, k_state, matches):
    probs = {}
    for o in matches:
        s = seqs[o]
        if k_state == 0:
            p = opts[o]
        elif k_state == 1:
            p = S.cont.get(o, 1.0)
        else:
            p = 1.0
        probs[s[k_state]] = probs.get(s[k_state], 0.0) + p
    row = np.full(V, FLOOR, dtype=np.float64)
    row[JUNK] = math.log(max(1.0 - sum(probs.values()), 1e-9))
    for text, p in probs.items():
        lp = math.log(p) if p > 0 else FLOOR
        for variant in ((text, " " + text) if k_state == 0 else (text,)):
            row[_tid(variant)] = lp
    if k_state == 0:
        for ws in (" ", "\n"):
            row[_tid(ws)] = math.log(0.25)
    if S.poison_option:
        opt, val = S.poison_option
        s = seqs.get(opt)
        if s and k_state == len(s) - 1 and (k_state == 0 or opt in matches):
            for variant in ((s[-1], " " + s[-1]) if k_state == 0 else (s[-1],)):
                row[_tid(variant)] = val
    mode = S.poison_all
    if mode == "nan":
        row[:] = np.nan
    elif mode == "inf":
        row[:] = np.inf
    elif mode == "ninf":
        row[:] = -np.inf
    elif mode == "zeros":
        row[:] = 0.0
    return row


def _advance(state, i):
    seen, tail = state
    if i != BOS:
        s = S.i2t.get(i, "?").strip()
        if s:
            tail = (tail + (s,))[-3:]
            if s in S.choice_first():
                seen = True
    return (seen, tail)


def _row_of(state):
    return make_row(list(state[1]), "choice" if state[0] else "noul")


def _log_softmax(row, axis=-1):
    row = np.asarray(row, dtype=np.float64)
    with np.errstate(all="ignore"):
        shifted = row - np.max(row, axis=axis, keepdims=True)
        return shifted - np.log(np.sum(np.exp(shifted), axis=axis, keepdims=True))


class FakeLlama:
    def __init__(self, model_path=None, *args, n_ctx=512, **kwargs):
        S.ctor_attempts += 1
        if S.hang_ctor:
            S.release.wait(30)
        if S.ctor_error is not None:
            raise S.ctor_error
        if not isinstance(model_path, (str, os.PathLike)):
            raise TypeError("model_path must be a path")
        p = str(model_path)
        if not os.path.exists(p):
            raise ValueError("Model path does not exist: %s" % p)
        if os.path.isdir(p):
            raise ValueError("Failed to load model from file: %s" % p)
        try:
            with open(p, "rb") as fh:
                magic = fh.read(4)
        except OSError as exc:
            raise ValueError("Failed to load model from file: %s (%s)" % (p, exc))
        if magic != b"GGUF":
            raise ValueError("Failed to load model from file: %s" % p)
        S.constructed += 1
        self.model_path = p
        self._n_ctx = min(int(n_ctx or 512), 2048)
        self._scores = np.full((self._n_ctx, V), np.nan, dtype=np.float32)
        self._ids = []
        self._states = [(False, ())]

    # -- guards --
    def _gate(self):
        S.entries += 1
        if S.raise_all is not None:
            raise S.raise_all
        if S.hang_infer:
            S.release.wait(30)

    @contextmanager
    def _exclusive(self):
        with S.lock:
            if S.active:
                S.overlap = True
            S.active += 1
        try:
            time.sleep(0.001)
            yield
        finally:
            with S.lock:
                S.active -= 1

    # -- tokenizer --
    def _tokenize(self, text, add_bos=True):
        if isinstance(text, bytes):
            text = text.decode("utf-8", "replace")
        if S.empty_tokenize:
            return []
        if text.strip() in S.empty_opt_tokenize:
            return []
        toks = split_tokens(text)
        if S.tok_merge:
            # Context-dependent tokenization: when an option is the tail of a longer text
            # (prompt + option in one call) the boundary tokenizes differently from
            # tokenize(prompt) + tokenize(" " + option).
            for opt in list(S.choice_w) + list(S.noul_w):
                k = len(_seq(opt))
                if text.endswith(opt) and len(text.strip()) > len(opt) + 1 and len(toks) > k:
                    i = len(toks) - k
                    first = toks[i]
                    if first[:1].isspace():
                        toks[i:i + 1] = [first[:1], first[1:]]
                    else:
                        toks[i - 1:i + 1] = [toks[i - 1] + first]
                    break
        ids = [_tid(t) for t in toks]
        if S.tok_bad and ids:
            bad = {"bool": True, "float": 1.5, "str": "a", "neg": -1, "huge": V + 10}[S.tok_bad]
            ids = [bad] * len(ids)
        return ([BOS] + ids) if add_bos and not S.tok_bad else ids

    def tokenize(self, text, add_bos=True, special=False):
        self._gate()
        S.tok_calls.append(bool(add_bos))
        return self._tokenize(text, add_bos)

    def detokenize(self, tokens, *args, **kwargs):
        self._gate()
        return "".join(S.i2t.get(t, "?") for t in tokens if t not in (BOS,)).encode()

    def n_vocab(self):
        self._gate()
        return V

    def n_ctx(self):
        self._gate()
        return self._n_ctx

    def token_bos(self):
        self._gate()
        return BOS

    def token_eos(self):
        self._gate()
        return JUNK

    @staticmethod
    def logits_to_logprobs(logits, axis=-1):
        return _log_softmax(logits, axis)

    # -- state --
    @property
    def n_tokens(self):
        self._gate()
        return len(self._ids)

    @n_tokens.setter
    def n_tokens(self, n):
        n = int(n)
        if n > len(self._ids) or n < 0:
            raise ValueError("bad n_tokens")
        del self._ids[n:]
        del self._states[n + 1:]

    def reset(self):
        self._gate()
        with self._exclusive():
            self._ids = []
            self._states = [(False, ())]

    @property
    def scores(self):
        self._gate()
        if S.poison_all == "none":
            return None
        if S.poison_all == "narrow":
            return np.zeros((len(self._ids), 1), dtype=np.float32)
        if S.poison_all == "empty":
            return np.zeros((0, V), dtype=np.float32)
        return self._scores[:len(self._ids)]

    def eval(self, tokens):
        self._gate()
        with self._exclusive():
            S.calls += 1
            tokens = list(tokens)
            if len(self._ids) + len(tokens) > self._n_ctx:
                raise ValueError("Requested tokens (%d) exceed context window of %d"
                                 % (len(self._ids) + len(tokens), self._n_ctx))
            for t in tokens:
                st = _advance(self._states[-1], int(t))
                pos = len(self._ids)
                self._ids.append(int(t))
                self._states.append(st)
                self._scores[pos] = _row_of(st).astype(np.float32)

    # -- completion API --
    def create_completion(self, prompt, suffix=None, max_tokens=16, temperature=0.0,
                          logprobs=None, echo=False, stop=None, **kwargs):
        self._gate()
        with self._exclusive():
            S.calls += 1
            S.gen_calls += 1
            if S.poison_all == "empty":
                return {"choices": []}
            if S.poison_all == "none":
                return {"choices": [{"text": "", "logprobs": None}]}
            if S.poison_all == "narrow":
                return {"choices": [{"text": "", "logprobs": {"tokens": [], "token_logprobs": [],
                                                              "top_logprobs": []}}]}
            if isinstance(prompt, (str, bytes)):
                ids = self._tokenize(prompt, True)
            else:
                ids = [int(t) for t in prompt]
            gen_ids, gen_text = [], ""
            n_gen = int(max_tokens or 0)
            if n_gen > 0:
                if S.gen_text is not None:
                    gen_text = S.gen_text
                    gen_ids = self._tokenize(gen_text, False)[:n_gen]
                else:
                    state = (False, ())
                    for t in ids:
                        state = _advance(state, t)
                    for _ in range(n_gen):
                        row = _row_of(state)
                        if not np.all(np.isfinite(row)):
                            break
                        t = int(np.argmax(row))
                        if t == JUNK:
                            break
                        gen_ids.append(t)
                        state = _advance(state, t)
                    gen_text = "".join(S.i2t.get(t, "?") for t in gen_ids)
            all_ids = ids + gen_ids
            lps, tops = ([None], [None]) if all_ids else ([], [])
            state = (False, ())
            prev_ls = None
            for i, t in enumerate(all_ids):
                if i > 0:
                    lps.append(float(prev_ls[t]))
                    if logprobs:
                        order = np.argsort(-np.nan_to_num(prev_ls, nan=-1e9))[:max(int(logprobs), 1)]
                        tops.append({S.i2t.get(int(j), "?"): float(prev_ls[j]) for j in order})
                state = _advance(state, t)
                prev_ls = _log_softmax(_row_of(state))
            toks = [S.i2t.get(t, "?") for t in all_ids]
            lo = 0 if echo else len(ids)
            lp_obj = None
            if logprobs is not None:
                lp_obj = {"tokens": toks[lo:], "token_logprobs": lps[lo:], "top_logprobs": tops[lo:],
                          "text_offset": list(range(len(toks[lo:])))}
            text = ("".join(S.i2t.get(t, "?") for t in ids if t != BOS) if echo else "") + gen_text
            return {"id": "cmpl-stub", "object": "text_completion",
                    "choices": [{"text": text, "index": 0, "logprobs": lp_obj,
                                 "finish_reason": "length"}]}

    def __call__(self, prompt, *args, **kwargs):
        return self.create_completion(prompt, *args, **kwargs)


def _fake_module():
    mod = types.ModuleType("llama_cpp")
    mod.Llama = FakeLlama
    return mod


def _purge_router_modules():
    for name in [m for m in sys.modules if m == "router" or m.startswith("router.")]:
        del sys.modules[name]


_DEFAULT = object()


def shorten_timeouts(module, seconds):
    """Shorten every timeout the module exposes (module constants named *TIMEOUT*/*DEADLINE*, and
    keyword/positional defaults of parameters named *timeout*/*deadline* on its functions and
    methods) so hang tests stay fast. Returns an undo list for restore_timeouts()."""
    import inspect
    undo = []
    for name, val in list(vars(module).items()):
        if (("TIMEOUT" in name.upper() or "DEADLINE" in name.upper()) and isinstance(val, (int, float))
                and not isinstance(val, bool) and val > seconds):
            undo.append(("const", module, name, val))
            setattr(module, name, float(seconds))
    funcs = []
    for val in vars(module).values():
        if inspect.isfunction(val) and val.__module__ == module.__name__:
            funcs.append(val)
        elif inspect.isclass(val) and val.__module__ == module.__name__:
            for attr in vars(val).values():
                fn = attr.__func__ if isinstance(attr, (classmethod, staticmethod)) else attr
                if inspect.isfunction(fn):
                    funcs.append(fn)
    for fn in funcs:
        try:
            params = list(inspect.signature(fn).parameters.values())
        except (TypeError, ValueError):
            continue
        pos = [p for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
        defaults = fn.__defaults__ or ()
        first_default = len(pos) - len(defaults)
        new_defaults = list(defaults)
        changed = False
        for i, p in enumerate(pos):
            if i >= first_default and ("timeout" in p.name.lower() or "deadline" in p.name.lower()):
                d = defaults[i - first_default]
                if isinstance(d, (int, float)) and not isinstance(d, bool) and d > seconds:
                    new_defaults[i - first_default] = float(seconds)
                    changed = True
        kwd = dict(fn.__kwdefaults__ or {})
        kchanged = False
        for k, d in list(kwd.items()):
            if ("timeout" in k.lower() or "deadline" in k.lower()) and isinstance(d, (int, float)) \
                    and not isinstance(d, bool) and d > seconds:
                kwd[k] = float(seconds)
                kchanged = True
        if changed or kchanged:
            undo.append(("func", fn, fn.__defaults__, fn.__kwdefaults__))
            if changed:
                fn.__defaults__ = tuple(new_defaults)
            if kchanged:
                fn.__kwdefaults__ = kwd
    return undo


def restore_timeouts(undo):
    for item in undo:
        if item[0] == "const":
            setattr(item[1], item[2], item[3])
        else:
            item[1].__defaults__, item[1].__kwdefaults__ = item[2], item[3]


def run_bounded(fn, timeout):
    """Run fn in a daemon thread; return (finished, box)."""
    box = {}

    def target():
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout)
    return (not t.is_alive()), box


# --------------------------------------------------------------------------
# base case
# --------------------------------------------------------------------------

# Tests whose name contains one of these run LIVE: no pre-check memo and no stub row cache.
# (hang, circuit-breaker, concurrency, and the "no network/database" pre-check test)
LIVE_KEYWORDS = ("hung", "hang", "breaker", "concurrent", "network")

_PRECHECK_MEMO = {}


def _install_precheck_memo(case):
    """Memoize pipeline.gate1.check_text by its exact input for the duration of one test.

    Shared across tests only because: the function is deterministic for identical input, the
    router state is rebuilt fresh for every test (modules purged, shared router reset, no open
    breaker, no prior hang), and only successful results are stored (exceptions are never cached).
    A test that patches check_text itself patches over this wrapper."""
    import pipeline.gate1 as g1
    real = g1.check_text

    def memo(text, *args, **kwargs):
        if args or kwargs or not isinstance(text, str):
            return real(text, *args, **kwargs)
        hit = _PRECHECK_MEMO.get(text)
        if hit is None:
            hit = _PRECHECK_MEMO[text] = tuple(real(text))
        return list(hit)

    p = mock.patch.object(g1, "check_text", memo)
    p.start()
    case.addCleanup(p.stop)


_ORACLE_REPORTS = {}


def edge_class_hits(texts):
    """Which adversarial edge-case classes the given item texts cover."""
    import unicodedata
    blob = "\n".join(texts)
    return {
        "OCR-damaged reporter": bool(re.search(r"\bS0\.|\bF1a\.|\bFIa\.|\b\d+\s+So\.\s?[23]cl\b", blob)),
        "homoglyph / non-Latin letters": any(
            ord(c) > 127 and c.isalpha() and not unicodedata.name(c, "").startswith("LATIN") for c in blob),
        "Ala. Southern Reporter cite": bool(re.search(r"So\.\s?(?:2d|3d)?\s?\d+\s*\(Ala\.", blob)),
        "La. Southern Reporter cite": bool(re.search(r"So\.\s?(?:2d|3d)?\s?\d+\s*\(La\.", blob)),
        "Miss. Southern Reporter cite": bool(re.search(r"So\.\s?(?:2d|3d)?\s?\d+\s*\(Miss\.", blob)),
        "Fla. L. Weekly Fed.": "Fla. L. Weekly Fed." in blob,
        "prompt injection": bool(re.search(r"(?i)ignore (?:all |the )?(?:previous|above)|route:|answer:|system prompt", blob)),
    }


class RouterCase(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        S.reset()
        self.live = any(k in self._testMethodName for k in LIVE_KEYWORDS)
        S.row_cache_on = not self.live
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        for key in ("VON_BASE_URL", "JEV_MODEL_PATH"):
            os.environ.pop(key, None)
        self._saved_llama = sys.modules.get("llama_cpp", "__absent__")
        sys.modules["llama_cpp"] = _fake_module()
        self.addCleanup(self._restore_llama)
        _purge_router_modules()
        self.addCleanup(_purge_router_modules)
        # LIFO: release any blocked stub thread first, then let stale threads drain
        # so they cannot touch the next test's counters after S.reset().
        self.addCleanup(lambda: time.sleep(0.1) if (S.hang_infer or S.hang_ctor) else None)
        self.addCleanup(S.release.set)
        self._qn = 0
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.model_path = os.path.join(self.tmp.name, "stub.gguf")
        with open(self.model_path, "wb") as fh:
            fh.write(b"GGUF" + b"\0" * 64)
        if not self.live:
            _install_precheck_memo(self)
        import router.system_one_client as sc
        self.sc = sc

    def _restore_llama(self):
        if self._saved_llama == "__absent__":
            sys.modules.pop("llama_cpp", None)
        else:
            sys.modules["llama_cpp"] = self._saved_llama

    # -- helpers --
    def use_model(self, path=None):
        os.environ["JEV_MODEL_PATH"] = path if path is not None else self.model_path

    def route(self, query=_DEFAULT, model=True, **kw):
        if query is _DEFAULT:
            # unique per call so a memoising router cannot replay a stale decision
            self._qn += 1
            query = "What cases discuss adverse possession of beachfront property number %d?" % self._qn
        if model:
            self.use_model()
        else:
            os.environ.pop("JEV_MODEL_PATH", None)
        return self.sc.route(query, **kw)

    def assertSafe(self, d):
        self.assertIsInstance(d, self.sc.RouteDecision)
        self.assertIn(d.route, ROUTES, "route is not an allowed option: %r" % (d.route,))
        self.assertIs(d.requires_gate1, True)

    def assertVetoed(self, d, msg="", hard=False):
        """Adversarial input must land on direct_db."""
        self.assertSafe(d)
        self.assertEqual(d.route, "direct_db", "LEAK %s: routed to %r (%s)" % (msg, d.route, d.reason))
        if hard:
            self.assertTrue(d.fallback, "hard failure must set fallback=True: %s (%s)" % (msg, d.reason))

    def resp(self, answer="vector_search", conf=0.95, raw=0.02, score=0.95, options=ROUTES):
        sc = self.sc
        return sc.SystemOneResponse(sc.Choice("q", tuple(options), answer, conf),
                                    sc.Noul("q", raw, "low"), sc.Score("q", score))

    def client(self, resp=None, exc=None):
        outer = self

        class _C:
            def query(self, q):
                if exc is not None:
                    raise exc
                return resp
        return _C()


# --------------------------------------------------------------------------
# controls: an honest, confident model must be followed
# --------------------------------------------------------------------------

class Controls(RouterCase):
    def test_confident_vector(self):
        d = self.route()
        self.assertSafe(d)
        self.assertEqual(d.route, "vector_search", d.reason)
        self.assertFalse(d.fallback)
        self.assertGreater(S.calls, 0, "local model was never consulted")

    def test_confident_boolean(self):
        S.choice_w = {"boolean_search": 0.97, "vector_search": 0.015, "direct_db": 0.015}
        d = self.route()
        self.assertSafe(d)
        self.assertEqual(d.route, "boolean_search", d.reason)

    def test_confidence_is_normalised_over_exactly_the_allowed_options(self):
        S.choice_w = {"boolean_search": 0.05, "vector_search": 0.80, "direct_db": 0.05}
        d = self.route()
        self.assertEqual(d.route, "vector_search", d.reason)
        self.assertIsNotNone(d.choice)
        expected = 0.80 / 0.90
        self.assertAlmostEqual(d.choice.confidence, expected, places=3)
        self.assertLessEqual(d.choice.confidence, 1.0 + 1e-9)

    def test_noul_is_p_yes_over_exactly_yes_no(self):
        S.noul_w = {"Yes": 0.54, "No": 0.36}   # 0.10 of the mass is elsewhere
        d = self.route()
        self.assertVetoed(d, "noul 0.6 is uncertain, must not follow the choice")
        self.assertIsNotNone(d.noul)
        self.assertAlmostEqual(d.noul.noul_raw, 0.6, places=3)

    def test_noul_low_follows_choice(self):
        S.noul_w = {"Yes": 0.01, "No": 0.98}
        d = self.route()
        self.assertEqual(d.route, "vector_search", d.reason)
        self.assertAlmostEqual(d.noul.noul_raw, 0.01 / 0.99, places=3)

    def test_citation_present_goes_to_direct_db_and_gate1(self):
        S.noul_w = {"Yes": 0.97, "No": 0.01}
        d = self.route(CITE_Q)
        self.assertVetoed(d, "citation present")
        self.assertIs(d.requires_gate1, True)

    def test_sequential_calls_reuse_one_model_instance(self):
        for _ in range(5):
            self.assertEqual(self.route().route, "vector_search")
        self.assertEqual(S.constructed, 1, "model reloaded per call")


# --------------------------------------------------------------------------
# Constraint C: only an exact allowed option, decided by log-probs
# --------------------------------------------------------------------------

class ConstraintC(RouterCase):
    def setUp(self):
        super().setUp()
        self.uniform = {o: 1 / 3 for o in ROUTES}

    def test_generated_text_never_decides_the_route(self):
        # log-probs say boolean_search; generation says something else.
        S.choice_w = {"boolean_search": 0.97, "vector_search": 0.015, "direct_db": 0.015}
        for text in ("vector_search", "direct_db", "garbage", "Yes"):
            with self.subTest(gen=text):
                S.gen_text = text
                self.assertEqual(self.route().route, "boolean_search")

    def test_substring_and_case_variants_in_generation_do_not_route(self):
        # no log-prob information (uniform) => must not follow free text
        S.choice_w = dict(self.uniform)
        for text in ("vector_search please", "VECTOR_SEARCH", "  vector_search \n", "Vector_Search.",
                     "the answer is vector_search", "boolean_search", "vector", "direct_db\nboolean_search",
                     "'vector_search'", "vector_search" * 3, "I think vector_search or direct_db"):
            with self.subTest(gen=repr(text)):
                S.gen_text = text
                self.assertVetoed(self.route(threshold=0.3), "free text %r" % text)

    def test_unparseable_generation_does_not_default_to_first_option(self):
        S.choice_w = dict(self.uniform)
        for text in ("", " ", "\n", "???", "0", "null", "None", "\x00", "unknown"):
            with self.subTest(gen=repr(text)):
                S.gen_text = text
                d = self.route(threshold=0.3)
                self.assertVetoed(d, "default-first path on %r" % text)
                self.assertNotEqual(d.route, ROUTES[0])

    def test_model_with_no_mass_on_any_option_does_not_default_to_first(self):
        S.choice_w = {o: 0.0 for o in ROUTES}
        self.assertVetoed(self.route(threshold=0.3), "zero mass on all options")

    def test_exact_three_way_tie(self):
        S.choice_w = dict(self.uniform)
        self.assertVetoed(self.route(threshold=0.3), "3-way tie")

    def test_exact_two_way_tie_for_first(self):
        for tied in (("boolean_search", "vector_search"), ("vector_search", "direct_db"),
                     ("boolean_search", "direct_db")):
            with self.subTest(tied=tied):
                S.choice_w = {o: (0.45 if o in tied else 0.10) for o in ROUTES}
                self.assertVetoed(self.route(threshold=0.4), "2-way tie %r" % (tied,))

    def test_tie_control_untied_is_followed_at_same_threshold(self):
        S.choice_w = {"boolean_search": 0.7, "vector_search": 0.2, "direct_db": 0.1}
        self.assertEqual(self.route(threshold=0.3).route, "boolean_search")

    def test_nonfinite_logprob_on_any_option_vetoes(self):
        for opt in ROUTES:
            for val in (np.nan, np.inf, -np.inf):
                with self.subTest(option=opt, value=val):
                    S.poison_option = (opt, val)
                    self.assertVetoed(self.route(), "non-finite %r on %s" % (val, opt))

    def test_nonfinite_noul_logprob_vetoes(self):
        for opt in ("Yes", "No"):
            for val in (np.nan, np.inf, -np.inf):
                with self.subTest(option=opt, value=val):
                    S.poison_option = (opt, val)
                    self.assertVetoed(self.route(), "non-finite %r on %s" % (val, opt))

    def test_nonfinite_everywhere_vetoes(self):
        for mode in ("nan", "inf", "ninf"):
            with self.subTest(mode=mode):
                S.poison_all = mode
                self.assertVetoed(self.route(), "all logits %s" % mode)

    def test_degenerate_model_outputs_veto(self):
        for mode in ("zeros", "none", "narrow", "empty"):
            with self.subTest(mode=mode):
                S.poison_all = mode
                self.assertVetoed(self.route(threshold=0.3), "model output mode %s" % mode)

    def test_empty_tokenization_vetoes(self):
        S.empty_tokenize = True
        self.assertVetoed(self.route(), "tokenizer returns nothing", hard=False)

    def test_option_with_empty_tokenization_cannot_win(self):
        # An empty continuation scores log-lik 0 (probability 1); it must not beat real options.
        for opt in ("boolean_search", "vector_search"):
            with self.subTest(option=opt):
                S.empty_opt_tokenize = {opt}
                S.choice_w = {o: (0.01 if o == opt else 0.495) for o in ROUTES}
                d = self.route(threshold=0.3)
                self.assertSafe(d)
                self.assertNotEqual(d.route, opt, "empty-tokenized option %r won" % opt)

    def test_first_token_only_scoring_is_not_enough(self):
        # boolean_search has the likeliest first token but is improbable overall.
        S.choice_w = {"boolean_search": 0.50, "vector_search": 0.48, "direct_db": 0.02}
        S.cont = {"boolean_search": 0.01}
        d = self.route()
        self.assertEqual(d.route, "vector_search",
                         "first-token-only scoring? routed %r (%s)" % (d.route, d.reason))

    def test_later_tokens_are_scored_for_every_option(self):
        # The option with the likeliest FIRST token is improbable overall; the other one must win.
        for leaky, other in (("boolean_search", "vector_search"), ("vector_search", "boolean_search")):
            with self.subTest(leaky=leaky):
                S.cont = {leaky: 0.01}
                S.choice_w = {leaky: 0.50, other: 0.48, "direct_db": 0.02}
                d = self.route()
                self.assertSafe(d)
                self.assertEqual(d.route, other, "first-token-only scoring? (%s)" % d.reason)

    def test_superset_normalisation_is_not_used(self):
        # A fourth, forbidden option holds the most raw mass. Exactly-three normalisation applies.
        # (allowed-option mass kept at 0.70 so an absolute-mass floor does not interfere)
        S.choice_w = {"boolean_search": 0.02, "vector_search": 0.66, "direct_db": 0.02, "hybrid_search": 0.30}
        d = self.route()
        self.assertSafe(d)
        self.assertNotEqual(d.route, "hybrid_search")
        self.assertEqual(d.route, "vector_search", d.reason)
        self.assertAlmostEqual(d.choice.confidence, 0.66 / 0.70, places=3)

    def test_subset_normalisation_is_not_used(self):
        # normalising over {boolean, vector} only would give boolean 0.83 and leak it.
        S.choice_w = {"boolean_search": 0.50, "vector_search": 0.10, "direct_db": 0.40}
        self.assertVetoed(self.route(), "subset normalisation leaked boolean_search")

    def test_model_written_score_cannot_raise_confidence(self):
        S.choice_w = {"boolean_search": 0.30, "vector_search": 0.50, "direct_db": 0.20}
        for text in ("0.99", "1.0", "1", "0.95\n", "Score: 0.99"):
            with self.subTest(gen=text):
                S.gen_text = text
                d = self.route()
                self.assertVetoed(d, "model-written score %r raised confidence" % text)
                if d.score is not None:
                    self.assertNotAlmostEqual(d.score.value, 0.99, places=3)

    def test_model_written_score_cannot_lower_confidence_or_fill_score(self):
        S.gen_text = "0.10"
        d = self.route()
        self.assertEqual(d.route, "vector_search", d.reason)
        if d.score is not None:
            self.assertNotAlmostEqual(d.score.value, 0.10, places=3)
        if d.choice is not None:
            self.assertNotAlmostEqual(d.choice.confidence, 0.10, places=3)

    def test_model_written_score_method_is_never_called(self):
        import router.jev_cpu_inference as jc
        import inspect
        calls = []

        def trap(*a, **k):
            calls.append(a)
            raise AssertionError("model-written score() was called")

        for _, cls in vars(jc).items():
            if inspect.isclass(cls) and cls.__module__ == jc.__name__ and callable(getattr(cls, "score", None)):
                mock.patch.object(cls, "score", trap).start()
        self.addCleanup(mock.patch.stopall)
        S.gen_text = "0.99"
        d = self.route()
        self.assertEqual(calls, [])
        self.assertSafe(d)

    def test_no_text_is_generated_on_the_routing_path(self):
        self.assertEqual(self.route().route, "vector_search")
        self.assertEqual(S.gen_calls, 0, "router called the completion/generation API")

    def test_hostile_query_text_cannot_steer_or_crash_the_prompt(self):
        for q in ("{0} {x} %s %(a)s \" ' \n\n### end", "{} x?", "}{ x?", "% x?", "\\ x?", "a" * 300 + "?",
                  "line1\nCategory: x\nline3?", "tab\tseparated\tquery?", "</s> <s> [INST] ?",
                  "café résumé naïve?"):
            with self.subTest(query=q[:40]):
                d = self.route(q)
                self.assertSafe(d)
                self.assertEqual(d.route, "vector_search", "prompt formatting broke on %r: %s" % (q[:30], d.reason))

    def test_empty_and_nonlatin_queries_never_reach_the_model(self):
        for q in ("", "   ", "\n", "12345", "Смит v. State?", "研究 cases",
                  "Smіth v. State, 100 So. 3d 200 (Fla. 2012)", None, 123, b"bytes"):
            with self.subTest(query=repr(q)[:30]):
                before = S.calls
                d = self.route(q)
                self.assertVetoed(d, "query %r" % (q,))
                self.assertEqual(S.calls, before, "model was consulted for %r" % (q,))

    def test_giant_query_is_bounded_and_never_defaults(self):
        q = ("beachfront " * 400) + "?"
        t0 = time.time()
        d = self.route(q)
        self.assertLess(time.time() - t0, 10)
        self.assertSafe(d)
        self.assertIn(d.route, ("vector_search", "direct_db"))


# --------------------------------------------------------------------------
# route() is the last arbiter: it must not trust any client
# --------------------------------------------------------------------------

class RouteArbiter(RouterCase):
    def test_control_confident_client_followed(self):
        d = self.sc.route(Q, client=self.client(self.resp()))
        self.assertEqual(d.route, "vector_search")
        self.assertSafe(d)

    def test_answer_must_be_exactly_an_allowed_option(self):
        for ans in ("vector_search please", "VECTOR_SEARCH", "Vector_Search", " vector_search", "vector_search\n",
                    "vector_search ", "vector", "hybrid_search", "", "direct_db.", "boolean_search,vector_search",
                    "vector_search\x00", "vector​_search", "vector_search​", "vеctor_search", None,
                    5, ["vector_search"]):
            with self.subTest(answer=ans):
                d = self.sc.route(Q, client=self.client(self.resp(answer=ans)))
                self.assertVetoed(d, "answer %r" % (ans,))

    def test_wrong_option_set_vetoes(self):
        sets = (ROUTES[:2], ROUTES[1:], ("vector_search",), ROUTES + ("hybrid_search",), (),
                ("boolean_search", "vector_search", "vector_db"), ROUTES + ROUTES)
        for opts in sets:
            with self.subTest(options=opts):
                d = self.sc.route(Q, client=self.client(self.resp(options=opts)))
                self.assertVetoed(d, "option set %r" % (opts,))

    def test_nonfinite_or_out_of_range_numbers_veto(self):
        bad = (float("nan"), float("inf"), float("-inf"), 1.5, -0.1, True, False, "0.99", None)
        for field in ("conf", "score", "raw"):
            for val in bad:
                with self.subTest(field=field, value=val):
                    kw = {field: val}
                    d = self.sc.route(Q, client=self.client(self.resp(**kw)))
                    self.assertVetoed(d, "%s=%r" % (field, val))

    def test_bool_confidence_pair_does_not_pass_the_threshold(self):
        d = self.sc.route(Q, client=self.client(self.resp(conf=True, score=True)))
        self.assertVetoed(d, "True == 1.0 confidence")

    def test_low_confidence_vetoes_and_boundary_is_inclusive_only_at_threshold(self):
        for conf, score in ((0.79, 0.95), (0.95, 0.79), (0.0, 0.0), (0.5, 0.5)):
            with self.subTest(conf=conf, score=score):
                self.assertVetoed(self.sc.route(Q, client=self.client(self.resp(conf=conf, score=score))),
                                  "conf %s score %s" % (conf, score))

    def test_noul_band_is_not_a_route_input(self):
        for raw in (0.21, 0.5, 0.79, 0.80, 0.95):
            with self.subTest(raw=raw):
                self.assertVetoed(self.sc.route(Q, client=self.client(self.resp(raw=raw))), "noul_raw %s" % raw)

    def test_client_exceptions_never_escape(self):
        excs = (RuntimeError("x"), ValueError("x"), OSError("x"), MemoryError(), KeyError("x"),
                self.sc.SystemOneError("x"), TimeoutError("x"), RecursionError(), UnicodeError("x"),
                ZeroDivisionError(), AttributeError("x"), ImportError("x"), NotImplementedError("x"))
        for exc in excs:
            with self.subTest(exc=type(exc).__name__):
                d = self.sc.route(Q, client=self.client(exc=exc))
                self.assertVetoed(d, type(exc).__name__, hard=True)

    def test_client_returning_garbage_vetoes(self):
        for junk in (None, 5, "vector_search", [], {}, {"choice": "vector_search"}, object(),
                     {"choice": {"answer": "vector_search please", "confidence": 0.99},
                      "noul": {"noul_raw": 0.0, "noul": "low"}, "score": {"value": 0.99}}):
            with self.subTest(junk=repr(junk)[:40]):
                d = self.sc.route(Q, client=self.client(junk))
                self.assertVetoed(d, "client returned %r" % (junk,), hard=True)

    def test_hostile_threshold_values_veto(self):
        for thr in (float("nan"), 1.5, float("inf"), -1.0, float("-inf"), 0.0, None, "0.8"):
            with self.subTest(threshold=thr):
                d = self.sc.route(Q, client=self.client(self.resp()), threshold=thr)
                self.assertVetoed(d, "threshold %r" % (thr,))
                self.assertEqual(d.cause, "invalid_threshold", d.reason)

    def test_threshold_does_not_alter_vetoes_for_noncitation_confident_client(self):
        # control: at the default threshold this client is followed
        self.assertEqual(self.sc.route(Q, client=self.client(self.resp())).route, "vector_search")


# --------------------------------------------------------------------------
# Gate 1 is never bypassed
# --------------------------------------------------------------------------

class Gate1NeverBypassed(RouterCase):
    def test_requires_gate1_true_across_every_outcome(self):
        outcomes = []
        outcomes.append(self.route())                                    # followed choice
        S.noul_w = {"Yes": 0.97, "No": 0.01}
        outcomes.append(self.route(CITE_Q))                              # citation present
        S.noul_w = {"Yes": 0.02, "No": 0.95}
        outcomes.append(self.route(""))                                  # empty query
        outcomes.append(self.sc.route(Q, client=self.client(exc=RuntimeError())))  # error
        outcomes.append(self.route(model=False))                         # nothing configured
        S.poison_all = "nan"
        outcomes.append(self.route())                                    # nan
        for d in outcomes:
            self.assertSafe(d)

    def test_confident_route_for_a_florida_cite_still_requires_gate1(self):
        # model confidently says "No citation" and "vector_search" for a query that holds a citation
        S.noul_w = {"Yes": 0.01, "No": 0.98}
        d = self.route(CITE_Q)
        self.assertSafe(d)
        self.assertIs(d.requires_gate1, True)
        # a misroute to vector_search is tolerated (Gate 1 still runs); skipping the veto is not

    def test_requires_gate1_cannot_be_turned_off(self):
        sc = self.sc
        d = sc.RouteDecision("direct_db", "r", None, None, None, True)
        self.assertIs(d.requires_gate1, True)
        with self.assertRaises((AttributeError, TypeError)):
            d.requires_gate1 = False
        with self.assertRaises((AttributeError, TypeError)):
            setattr(d, "requires_gate1", False)
        with self.assertRaises(TypeError):
            sc.RouteDecision("direct_db", "r", None, None, None, True, requires_gate1=False)
        for route in ROUTES:
            for fb in (True, False):
                self.assertIs(sc.RouteDecision(route, "r", None, None, None, fb).requires_gate1, True)

    def test_decision_has_no_skip_or_bypass_field(self):
        import dataclasses
        names = {f.name for f in dataclasses.fields(self.sc.RouteDecision)}
        for n in names:
            self.assertFalse(re.search(r"skip|bypass|gate", n, re.I), "suspicious field %r" % n)

    def test_router_sources_never_assign_requires_gate1(self):
        for path, text, tree in _router_sources():
            for node in ast.walk(tree):
                if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for t in targets:
                        name = t.attr if isinstance(t, ast.Attribute) else getattr(t, "id", "")
                        self.assertNotEqual(name, "requires_gate1", "%s:%d assigns requires_gate1" % (path, node.lineno))
            self.assertNotRegex(text, r"requires_gate1\s*=\s*False")


# --------------------------------------------------------------------------
# fail closed: loading, selection, errors, hangs, concurrency
# --------------------------------------------------------------------------

class FailClosed(RouterCase):
    def test_nothing_configured_is_direct_db_and_loads_nothing(self):
        d = self.route(model=False)
        self.assertVetoed(d, "no env", hard=True)
        self.assertEqual(S.ctor_attempts, 0)

    def test_blank_model_path_is_direct_db(self):
        for val in ("", " ", "\t", "\n"):
            with self.subTest(path=repr(val)):
                S.ctor_attempts = 0
                self.use_model(val)
                d = self.sc.route(Q)
                self.assertVetoed(d, "blank JEV_MODEL_PATH", hard=True)
                self.assertEqual(S.ctor_attempts, 0)

    def test_missing_model_file(self):
        self.use_model(os.path.join(self.tmp.name, "nope", "missing.gguf"))
        self.assertVetoed(self.sc.route(Q), "missing file", hard=True)

    def test_directory_unreadable_and_corrupt_model_files(self):
        d_path = os.path.join(self.tmp.name, "adir")
        os.mkdir(d_path)
        unreadable = os.path.join(self.tmp.name, "locked.gguf")
        with open(unreadable, "wb") as fh:
            fh.write(b"GGUF" + b"\0" * 16)
        os.chmod(unreadable, 0)
        self.addCleanup(os.chmod, unreadable, 0o600)
        empty = os.path.join(self.tmp.name, "empty.gguf")
        open(empty, "wb").close()
        garbage = os.path.join(self.tmp.name, "garbage.gguf")
        with open(garbage, "wb") as fh:
            fh.write(b"<html>404 not found</html>")
        for label, path in (("directory", d_path), ("unreadable", unreadable), ("empty", empty), ("garbage", garbage),
                            ("dangling", os.path.join(self.tmp.name, "x" * 300))):
            with self.subTest(kind=label):
                self.use_model(path)
                self.assertVetoed(self.sc.route(Q), label, hard=True)

    def test_llama_cpp_import_failure(self):
        for broken in (None, types.ModuleType("llama_cpp")):   # ImportError, and module without Llama
            with self.subTest(broken=repr(broken)[:20]):
                sys.modules["llama_cpp"] = broken
                _purge_router_modules()
                import router.system_one_client as sc
                self.sc = sc                       # fresh module objects after the purge
                self.use_model()
                d = sc.route(Q)
                self.assertSafe(d)
                self.assertEqual(d.route, "direct_db")
                self.assertTrue(d.fallback)

    def test_llama_cpp_import_raising_arbitrary_errors(self):
        class Boom(types.ModuleType):
            def __getattr__(self, name):
                raise RuntimeError("native library failed to initialise")
        sys.modules["llama_cpp"] = Boom("llama_cpp")
        _purge_router_modules()
        import router.system_one_client as sc
        self.sc = sc
        self.use_model()
        self.assertVetoed(sc.route(Q), "llama_cpp attribute error", hard=True)

    def test_loader_exceptions(self):
        for exc in (RuntimeError("bad"), MemoryError(), OSError("disk"), ValueError("v"), Exception("e"),
                    AssertionError("a"), NotImplementedError("n")):
            with self.subTest(exc=type(exc).__name__):
                S.ctor_error = exc
                self.assertVetoed(self.route(), "loader raised %s" % type(exc).__name__, hard=True)

    def test_inference_raising_everywhere(self):
        for exc in (RuntimeError("eval failed"), MemoryError(), ValueError("tokens exceed"), OSError("io"),
                    IndexError("i"), KeyError("k"), OverflowError("o"), FloatingPointError("f")):
            with self.subTest(exc=type(exc).__name__):
                S.raise_all = exc
                self.assertVetoed(self.route(), "inference raised %s" % type(exc).__name__, hard=True)

    def test_failed_then_recovered_model_is_not_stuck(self):
        S.raise_all = RuntimeError("transient")
        self.assertVetoed(self.route(), "transient", hard=True)
        S.raise_all = None
        d = self.route()
        self.assertSafe(d)  # recovery is allowed but not required; the bad state must not leak a route
        self.assertIn(d.route, ("vector_search", "direct_db"))

    # -- hangs. Router timeouts are shortened to ~1 s so the suite stays light; every
    #    bound below is in whole seconds and applies to a router that has a real timeout.

    def _short_timeouts(self):
        import router.jev_cpu_inference as jc
        self.shortened = shorten_timeouts(jc, 0.3)
        self.addCleanup(restore_timeouts, self.shortened)
        return jc

    def test_hung_inference_is_bounded(self):
        self._short_timeouts()
        S.hang_infer = True
        self.use_model()
        t0 = time.time()
        finished, box = run_bounded(lambda: self.sc.route(Q), 10)
        self.assertTrue(finished, "route() hung on a blocked model (no timeout)")
        self.assertLess(time.time() - t0, 8)
        self.assertNotIn("error", box, box.get("error"))
        self.assertVetoed(box["result"], "hung model", hard=True)
        # the router must not stay wedged behind the stuck worker
        finished2, box2 = run_bounded(lambda: self.sc.route(Q), 10)
        self.assertTrue(finished2, "second call wedged behind the hung one")
        self.assertVetoed(box2["result"], "call after hang", hard=True)
        S.release.set()

    def test_breaker_opens_and_a_later_call_is_direct_db_quickly(self):
        self._short_timeouts()
        S.hang_infer = True
        self.use_model()
        finished, box = run_bounded(lambda: self.sc.route(Q), 10)
        self.assertTrue(finished, "first call did not return")
        self.assertVetoed(box["result"], "hung call", hard=True)
        self.assertEqual(box["result"].cause, "timeout", box["result"].reason)
        entries, ctor = S.entries, S.ctor_attempts
        for i in range(3):
            t0 = time.time()
            finished, box = run_bounded(lambda: self.sc.route(Q), 5)
            took = time.time() - t0
            self.assertTrue(finished, "call %d after the hang did not return" % i)
            self.assertVetoed(box["result"], "call %d with the breaker open" % i, hard=True)
            self.assertEqual(box["result"].cause, "breaker", box["result"].reason)
            self.assertLess(took, 0.5, "breaker should answer immediately, took %.2fs" % took)
        self.assertEqual(S.entries, entries, "hung model instance was entered again after the breaker opened")
        self.assertEqual(S.ctor_attempts, ctor, "a second model instance was created while the first is hung")
        S.release.set()

    def test_breaker_stays_open_until_reset_shared_router(self):
        jc = self._short_timeouts()
        S.hang_infer = True
        self.use_model()
        finished, box = run_bounded(lambda: self.sc.route(Q), 10)
        self.assertTrue(finished)
        self.assertVetoed(box["result"], "hung call", hard=True)
        # the hang clears, but the breaker must still hold: no automatic retry
        S.hang_infer = False
        S.release.set()
        time.sleep(0.1)
        self.assertVetoed(self.sc.route(Q), "breaker must stay open without a reset", hard=True)
        jc.reset_shared_router()
        d = self.sc.route(Q)
        self.assertEqual(d.route, "vector_search", "reset_shared_router() did not close the breaker (%s)" % d.reason)
        self.assertEqual(S.constructed, 2, "the hung instance must be replaced, never reused")

    def test_hung_call_does_not_block_other_threads(self):
        self._short_timeouts()
        S.hang_infer = True
        self.use_model()
        a_box = {}
        a = threading.Thread(target=lambda: a_box.setdefault("d", self.sc.route(Q)), daemon=True)
        a.start()
        deadline = time.time() + 3
        while S.entries == 0 and time.time() < deadline:
            time.sleep(0.01)
        self.assertGreater(S.entries, 0, "first call never reached the model")
        t0 = time.time()
        finished, box = run_bounded(lambda: self.sc.route(Q), 8)
        self.assertTrue(finished, "second thread blocked behind the hung call (lock without timeout)")
        self.assertVetoed(box["result"], "thread behind a hung call", hard=True)
        S.release.set()
        a.join(8)
        self.assertFalse(a.is_alive())
        self.assertVetoed(a_box["d"], "the hung call itself", hard=True)

    def test_hung_model_load_is_bounded(self):
        self._short_timeouts()
        S.hang_ctor = True
        self.use_model()
        finished, box = run_bounded(lambda: self.sc.route(Q), 10)
        self.assertTrue(finished, "route() hung while loading the model (no timeout)")
        self.assertVetoed(box["result"], "hung load", hard=True)
        self.assertEqual(box["result"].cause, "timeout", box["result"].reason)
        t0 = time.time()
        finished, box = run_bounded(lambda: self.sc.route(Q), 8)
        self.assertTrue(finished, "call after a hung load blocked on the load lock")
        self.assertVetoed(box["result"], "call after hung load", hard=True)
        self.assertEqual(box["result"].cause, "breaker", box["result"].reason)
        S.release.set()

    def test_direct_router_call_on_a_hung_model_raises_in_bounded_time(self):
        jc = self._short_timeouts()
        r = jc.JevCPURouter.load(self.model_path, timeout=0.3)
        S.hang_infer = True
        finished, box = run_bounded(lambda: r.choice(Q), 8)
        self.assertTrue(finished, "JevCPURouter.choice() hung on a blocked model")
        self.assertIsInstance(box.get("error"), self.sc.SystemOneError, box)
        S.release.set()

    def test_concurrent_calls_share_one_model_without_overlap(self):
        self.use_model()
        results, errors = [], []
        lock = threading.Lock()

        def worker():
            try:
                for _ in range(3):
                    d = self.sc.route(Q)
                    with lock:
                        results.append(d)
            except BaseException as exc:  # noqa: BLE001
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker, daemon=True) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        self.assertFalse(any(t.is_alive() for t in threads), "deadlock under concurrency")
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 24)
        for d in results:
            self.assertSafe(d)
            self.assertEqual(d.route, "vector_search", d.reason)
        self.assertEqual(S.constructed, 1, "more than one model instance under concurrency")
        self.assertFalse(S.overlap, "model was entered concurrently (llama.cpp contexts are not thread-safe)")

    def test_concurrent_calls_with_a_failing_model_all_veto(self):
        S.raise_all = RuntimeError("boom")
        self.use_model()
        out = []

        def worker():
            out.append(self.sc.route(Q))

        threads = [threading.Thread(target=worker, daemon=True) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(20)
        self.assertEqual(len(out), 6)
        for d in out:
            self.assertVetoed(d, "concurrent failure", hard=True)


# --------------------------------------------------------------------------
# client selection: VON_BASE_URL -> Von; else JEV_MODEL_PATH -> local; else direct_db
# --------------------------------------------------------------------------

class _FakeHTTP:
    status = 200

    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def read(self, n=-1):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


VON_OK = {"choice": {"answer": "boolean_search", "confidence": 0.95},
          "noul": {"noul_raw": 0.02, "noul": "low"}, "score": {"value": 0.95}}


class ClientSelection(RouterCase):
    def test_von_takes_priority_over_local_model(self):
        os.environ["VON_BASE_URL"] = "http://von.invalid:9"
        with mock.patch.object(urllib.request.OpenerDirector, "open", lambda *a, **k: _FakeHTTP(VON_OK)):
            d = self.route()
        self.assertEqual(d.route, "boolean_search", d.reason)   # local model would say vector_search
        self.assertEqual(S.ctor_attempts, 0, "local model loaded although Von is configured")

    def test_von_unreachable_goes_to_direct_db_not_local(self):
        os.environ["VON_BASE_URL"] = "http://von.invalid:9"

        def boom(*a, **k):
            raise urllib.error.URLError("connection refused")
        with mock.patch.object(urllib.request.OpenerDirector, "open", boom):
            d = self.route()
        self.assertVetoed(d, "von unreachable", hard=True)

    def test_von_error_variants_go_to_direct_db(self):
        os.environ["VON_BASE_URL"] = "http://von.invalid:9"
        for exc in (TimeoutError("t"), OSError("o"), ConnectionResetError("c"), ValueError("v"), RuntimeError("r")):
            with self.subTest(exc=type(exc).__name__):
                def boom(*a, _e=exc, **k):
                    raise _e
                with mock.patch.object(urllib.request.OpenerDirector, "open", boom):
                    self.assertVetoed(self.route(), "von %s" % type(exc).__name__, hard=True)

    def test_only_local_model_when_no_von(self):
        d = self.route()
        self.assertEqual(d.route, "vector_search")
        self.assertGreater(S.constructed, 0)

    def test_blank_von_url_does_not_block_local_model(self):
        os.environ["VON_BASE_URL"] = "   "
        d = self.route()
        self.assertSafe(d)
        self.assertIn(d.route, ("vector_search", "direct_db"))

    def test_selection_never_touches_the_network_in_local_mode(self):
        with mock.patch.object(urllib.request.OpenerDirector, "open",
                               side_effect=AssertionError("network call in local mode")) as op:
            self.assertEqual(self.route().route, "vector_search")
            op.assert_not_called()


# --------------------------------------------------------------------------
# import-time behaviour and static checks
# --------------------------------------------------------------------------

BANNED_ROOTS = {
    "socket", "ssl", "http", "requests", "httpx", "aiohttp", "urllib3", "websocket", "websockets", "grpc",
    "ftplib", "smtplib", "telnetlib", "xmlrpc", "openai", "anthropic", "google", "cohere", "mistralai", "groq",
    "ollama", "together", "replicate", "litellm", "langchain", "langchain_core", "langchain_community",
    "huggingface_hub", "boto3", "botocore", "azure", "vertexai",
}
BANNED_HOSTS = re.compile(
    r"api\.openai\.com|api\.anthropic\.com|googleapis\.com|openrouter\.ai|api\.groq\.com|"
    r"api\.together|api\.cohere|api-inference\.huggingface|huggingface\.co", re.I)
BANNED_URL = re.compile(r"https?://", re.I)
BANNED_ENV = re.compile(
    r"ANTHROPIC_API_KEY|OPENAI_API_KEY|GEMINI_API_KEY|GOOGLE_API_KEY|OPENROUTER|HF_TOKEN|"
    r"HUGGING_?FACE_HUB_TOKEN|COHERE_API_KEY|GROQ_API_KEY|MISTRAL_API_KEY")
VON_FILE = "system_one_client.py"


def _router_sources():
    out = []
    for path in sorted(ROUTER_DIR.rglob("*.py")):
        rel = path.relative_to(ROUTER_DIR).parts
        if "tests" in rel or "__pycache__" in rel:
            continue
        text = path.read_text(encoding="utf-8")
        out.append((str(path.relative_to(REPO)), text, ast.parse(text, filename=str(path))))
    return out


def _docstring_nodes(tree):
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
                    and isinstance(body[0].value.value, str):
                ids.add(id(body[0].value))
    return ids


def _imports(tree):
    """Yield (module, toplevel, lineno). toplevel = not inside any function body."""
    results = []

    def visit(node, in_func):
        for child in ast.iter_child_nodes(node):
            fn = in_func or isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
            if isinstance(child, ast.Import):
                for a in child.names:
                    results.append((a.name, not in_func, child.lineno))
            elif isinstance(child, ast.ImportFrom):
                results.append(((child.module or "") if not child.level else "." * child.level + (child.module or ""),
                                not in_func, child.lineno))
            visit(child, fn)
    visit(tree, False)
    return results


class StaticChecks(unittest.TestCase):
    def test_router_has_python_sources(self):
        names = {Path(p).name for p, _, _ in _router_sources()}
        self.assertIn("system_one_client.py", names)
        self.assertIn("jev_cpu_inference.py", names)

    def test_llama_cpp_is_only_imported_lazily(self):
        for path, text, tree in _router_sources():
            for mod, toplevel, lineno in _imports(tree):
                if mod.split(".")[0] in ("llama_cpp", "llama_cpp_python"):
                    self.assertFalse(toplevel, "%s:%d imports llama_cpp at module level" % (path, lineno))

    def test_no_hosted_llm_or_network_imports_outside_the_von_client(self):
        for path, text, tree in _router_sources():
            is_von = Path(path).name == VON_FILE
            for mod, toplevel, lineno in _imports(tree):
                root = mod.split(".")[0]
                if root == "urllib":
                    self.assertTrue(is_von, "%s:%d imports urllib outside the Von client" % (path, lineno))
                    self.assertIn(mod, ("urllib.error", "urllib.request"), "%s:%d" % (path, lineno))
                    continue
                self.assertNotIn(root, BANNED_ROOTS, "%s:%d imports %s" % (path, lineno, mod))

    def test_no_dynamic_import_of_network_or_hosted_modules(self):
        for path, text, tree in _router_sources():
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    fn = node.func
                    name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                    if name in ("__import__", "import_module") and node.args \
                            and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        root = node.args[0].value.split(".")[0]
                        self.assertNotIn(root, BANNED_ROOTS | {"urllib"}, "%s:%d dynamic import of %s" % (path, node.lineno, root))
                    self.assertNotEqual(name, "from_pretrained",
                                        "%s:%d from_pretrained downloads a model" % (path, node.lineno))
                    self.assertNotIn(name, ("system", "popen", "Popen", "urlopen", "urlretrieve", "getaddrinfo",
                                            "create_connection", "check_output"),
                                     "%s:%d calls %s" % (path, node.lineno, name))
                    if isinstance(fn, ast.Name):   # builtin eval/exec of strings (llm.eval is a method, allowed)
                        self.assertNotIn(name, ("eval", "exec", "compile"), "%s:%d calls builtin %s" % (path, node.lineno, name))

    def test_no_urls_hostnames_or_api_key_env_in_router_code(self):
        for path, text, tree in _router_sources():
            doc = _docstring_nodes(tree)
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in doc:
                    self.assertIsNone(BANNED_HOSTS.search(node.value), "%s:%d string %r" % (path, node.lineno, node.value[:60]))
                    if Path(path).name != VON_FILE:
                        self.assertIsNone(BANNED_URL.search(node.value), "%s:%d URL %r" % (path, node.lineno, node.value[:60]))
            self.assertIsNone(BANNED_ENV.search(text), "%s references a hosted-API credential" % path)

    def test_router_only_reads_von_and_jev_environment_variables(self):
        pat = re.compile(r"os\.(?:environ\.get|environ\[|getenv)\(?\s*['\"]([A-Za-z_0-9]+)['\"]")
        for path, text, tree in _router_sources():
            for name in set(pat.findall(text)):
                self.assertRegex(name, r"^(VON_BASE_URL|JEV_[A-Z_]+)$", "%s reads env %s" % (path, name))

    def test_no_free_text_route_decision_patterns(self):
        for path, text, tree in _router_sources():
            for node in ast.walk(tree):
                # options[0] / ROUTES[0] default-to-first
                if isinstance(node, ast.Subscript) and isinstance(node.value, (ast.Name, ast.Attribute)):
                    nm = node.value.id if isinstance(node.value, ast.Name) else node.value.attr
                    sl = node.slice
                    if nm.lower() in ("options", "routes", "allowed", "choices", "valid_options") \
                            and isinstance(sl, ast.Constant) and sl.value == 0:
                        self.fail("%s:%d defaults to the first option (%s[0])" % (path, node.lineno, nm))
                # opt.lower() in result.lower() substring matching
                if isinstance(node, ast.Compare) and any(isinstance(o, (ast.In, ast.NotIn)) for o in node.ops):
                    for side in [node.left] + node.comparators:
                        for sub in ast.walk(side):
                            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) \
                                    and sub.func.attr in ("lower", "casefold", "upper"):
                                self.fail("%s:%d substring match on model text (%s)" % (path, node.lineno, ast.unparse(node)[:80]))

    def test_model_written_score_is_not_called_anywhere(self):
        for path, text, tree in _router_sources():
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    fn = node.func
                    name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                    self.assertNotEqual(name, "score", "%s:%d calls score()" % (path, node.lineno))

    def test_citation_precheck_precedes_every_model_call_in_its_function(self):
        model_calls = {"query", "choice", "noul", "get_shared_router", "load", "eval", "tokenize", "_classify",
                       "_score_options"}
        found = False
        for path, text, tree in _router_sources():
            for fn in ast.walk(tree):
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]

                def nm(c):
                    return c.func.attr if isinstance(c.func, ast.Attribute) else getattr(c.func, "id", "")
                pre = [c for c in calls if nm(c) in ("check_text", "citation_precheck")]
                if not pre:
                    continue
                found = True
                first = min((c.lineno, c.col_offset) for c in pre)
                for c in calls:
                    if nm(c) in model_calls and (c.lineno, c.col_offset) < first:
                        self.fail("%s:%d model call %s() precedes pipeline.gate1.check_text in %s()"
                                  % (path, c.lineno, nm(c), fn.name))
        self.assertTrue(found, "no router function calls pipeline.gate1.check_text")

    def test_uncalibrated_marker_and_placeholder_threshold_are_documented(self):
        blob = "\n".join(t for _, t, _ in _router_sources()).lower()
        self.assertIn("uncalibrated", blob, "router never says confidence is uncalibrated")
        self.assertIn("placeholder", blob, "router never says the 0.80 threshold is a placeholder")

    def test_router_never_reads_a_clients_calibrated_claim(self):
        for path, text, tree in _router_sources():
            if Path(path).name == "calibration.py":
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr == "calibrated" \
                        and isinstance(node.value, ast.Name) and node.value.id in ("resp", "response", "r", "res"):
                    self.fail("%s:%d reads %s.calibrated" % (path, node.lineno, node.value.id))
        # and the only module-level switch is a literal False
        import router.system_one_client as so
        self.assertIs(so.CALIBRATION_RECORDED, False)

    def test_calibrated_is_never_assigned_true_in_router_code(self):
        for path, text, tree in _router_sources():
            for node in ast.walk(tree):
                if isinstance(node, ast.keyword) and node.arg == "calibrated":
                    self.assertFalse(isinstance(node.value, ast.Constant) and node.value.value is True,
                                     "%s:%d passes calibrated=True" % (path, getattr(node.value, "lineno", 0)))
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    val = getattr(node, "value", None)
                    for t in targets:
                        nm = t.attr if isinstance(t, ast.Attribute) else getattr(t, "id", "")
                        if nm == "calibrated" and isinstance(val, ast.Constant) and val.value is True:
                            self.fail("%s:%d sets calibrated = True" % (path, node.lineno))


class ImportTime(unittest.TestCase):
    def setUp(self):
        S.reset()
        self._saved = sys.modules.get("llama_cpp", "__absent__")
        self._env = mock.patch.dict(os.environ, {}, clear=False)
        self._env.start()
        _purge_router_modules()

    def tearDown(self):
        self._env.stop()
        if self._saved == "__absent__":
            sys.modules.pop("llama_cpp", None)
        else:
            sys.modules["llama_cpp"] = self._saved
        _purge_router_modules()

    def test_import_succeeds_without_llama_cpp(self):
        sys.modules["llama_cpp"] = None      # `import llama_cpp` now raises ImportError
        os.environ["JEV_MODEL_PATH"] = "/nonexistent/model.gguf"
        import router.system_one_client  # noqa: F401
        import router.jev_cpu_inference  # noqa: F401
        self.assertIsNone(sys.modules["llama_cpp"])

    def test_import_loads_no_model_even_when_path_is_configured(self):
        sys.modules["llama_cpp"] = _fake_module()
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "m.gguf")
            with open(p, "wb") as fh:
                fh.write(b"GGUF" + b"\0" * 8)
            os.environ["JEV_MODEL_PATH"] = p
            import router.system_one_client  # noqa: F401
            import router.jev_cpu_inference  # noqa: F401
        self.assertEqual(S.ctor_attempts, 0)

    def test_import_does_not_touch_the_model_file(self):
        sys.modules["llama_cpp"] = _fake_module()
        os.environ["JEV_MODEL_PATH"] = "/definitely/not/here.gguf"
        import router.jev_cpu_inference  # noqa: F401
        self.assertEqual(S.ctor_attempts, 0)

    def test_constructing_the_von_client_never_loads_a_model(self):
        sys.modules["llama_cpp"] = _fake_module()
        import router.system_one_client as sc
        sc.SystemOneClient()
        self.assertEqual(S.ctor_attempts, 0)


# --------------------------------------------------------------------------
# the scoring API itself (JevCPURouter) and the one-model-per-process policy
# --------------------------------------------------------------------------

CITATION_QUERIES = {
    "florida supreme court": "What did Smith v. State, 123 So. 3d 456 (Fla. 2013) hold about landlord duty?",
    "florida dca": CITE_Q,
    "florida so. 2d": "Smith v. State, 98 So. 2d 1021 (Fla. 1st DCA 1957)",
    "florida so. no parenthetical": "Pull 123 So. 3d 456 please.",
    "fla. l. weekly": "See 45 Fla. L. Weekly D1203 (Fla. 2d DCA 2020).",
    "fla. l. weekly supp.": "Doe v. Roe, 30 Fla. L. Weekly Supp. 100 (Fla. 11th Cir. Ct. 2022).",
    "alabama": "Jones v. Ala. Power Co., 800 So. 2d 100 (Ala. 2001) says what about easements?",
    "louisiana": "Doe v. Roe, 900 So. 2d 50 (La. 2005).",
    "mississippi": "Doe v. Roe, 700 So. 2d 20 (Miss. 1998).",
    "federal reporter": "United States v. Smith, 100 F.3d 200 (11th Cir. 1996).",
    "u.s. reports": "Roe v. Wade, 410 U.S. 113 (1973).",
    "fla. l. weekly fed.": "United States v. Doe, 45 Fla. L. Weekly Fed. C100 (11th Cir. 2020).",
    "short cite": "Smith v. State, 123 So. 3d 456, 460 (Fla. 2013). Smith, 123 So. 3d at 462, controls.",
    "id.": "Smith v. State, 123 So. 3d 456 (Fla. 2013). Id. at 460.",
    "id. without antecedent": "Id. at 460.",
    "ocr S0.": "Smith v. State, 123 S0. 3d 456 (Fla. 2013)",
    "ocr F1a.": "Smith v. State, 123 So. 3d 456 (F1a. 2013)",
    "ocr FIa. L. Weekly": "Smith v. State, 45 FIa. L. Weekly D1203",
    "ocr glued page": "Smith v. State, 123 So. 3d456 (Fla. 2013)",
    "ocr 3cl": "Smith v. State, 123 So. 3cl 456 (Fla. 2013)",
    "homoglyph cyrillic o": "Smith v. State, 123 Sо. 3d 456 (Fla. 2013)",
    "homoglyph cyrillic a": "Smith v. State, 123 So. 3d 456 (Flа. 2013)",
    "fullwidth digits": "Smith v. State, １２３ So. 3d ４５６ (Fla. 2013)",
    "zero-width space": "Smith v. State, 123 So.​ 3d 456 (Fla. 2013)",
    "markdown bold": "**Smith v. State**, 123 So. 3d 456 (Fla. 2013)",
    "html tags": "<b>Smith v. State</b>, 123 So. 3d <i>456</i> (Fla. 2013)",
}
NON_CITATION_QUERIES = (
    "How does adverse possession work for beachfront property in Florida?",
    "What is the statute of limitations in 2020 for negligence claims?",
    "Explain the doctrine of laches in plain English?",
)


class CitationPrecheck(RouterCase):
    """pipeline.gate1.check_text(query) runs before the model: any result => direct_db, zero model calls."""

    def test_every_citation_shape_is_direct_db_with_zero_model_calls(self):
        for label, q in CITATION_QUERIES.items():
            with self.subTest(shape=label):
                before = (S.calls, S.entries, S.gen_calls)
                d = self.route(q)
                self.assertVetoed(d, "citation query %r" % label)
                self.assertIn(d.cause, ("citation_precheck", "english_gate"), d.reason)
                self.assertEqual((S.calls, S.entries, S.gen_calls), before,
                                 "model was consulted for citation query %r" % label)

    def test_citation_queries_skip_the_model_even_when_it_would_answer_confidently(self):
        S.noul_w = {"Yes": 0.01, "No": 0.98}                       # model insists "no citation"
        S.choice_w = {"boolean_search": 0.97, "vector_search": 0.015, "direct_db": 0.015}
        for label in ("florida dca", "alabama", "federal reporter", "short cite", "ocr S0."):
            with self.subTest(shape=label):
                d = self.route(CITATION_QUERIES[label])
                self.assertVetoed(d, label)
                self.assertEqual(S.calls, 0)

    def test_non_citation_control_reaches_the_model(self):
        for q in NON_CITATION_QUERIES:
            with self.subTest(query=q):
                before = S.calls
                d = self.route(q)
                self.assertEqual(d.route, "vector_search", d.reason)
                self.assertGreater(S.calls, before, "pre-check swallowed a plain-language query")

    def _patch_check_text(self, **kw):
        import pipeline.gate1 as g1
        p = mock.patch.object(g1, "check_text", **kw)
        m = p.start()
        self.addCleanup(p.stop)
        _purge_router_modules()            # a router that bound check_text at import must see the patch
        import router.system_one_client as sc
        self.sc = sc
        return m

    def test_precheck_is_called_with_the_query_and_an_empty_result_reaches_the_model(self):
        m = self._patch_check_text(return_value=[])
        q = "How does adverse possession work for beachfront property in Florida?"
        d = self.route(q)
        self.assertTrue(m.called, "route() never called pipeline.gate1.check_text")
        self.assertIn(q, str(m.call_args))
        self.assertEqual(d.route, "vector_search", d.reason)
        self.assertGreater(S.calls, 0)

    def test_any_result_at_all_is_direct_db_and_no_model_call(self):
        import types as _t
        for verdict in ("pass", "veto", "fall_through", "something_new"):
            with self.subTest(verdict=verdict):
                S.calls = 0
                self._patch_check_text(return_value=[_t.SimpleNamespace(verdict=verdict, reason="x", kind="full",
                                                                         text="1 So. 3d 1", full_citation="1 So. 3d 1")])
                d = self.route("How does adverse possession work for beachfront property in Florida?")
                self.assertVetoed(d, "check_text returned a %s result" % verdict)
                self.assertEqual(S.calls, 0)

    def test_check_text_exceptions_are_direct_db_and_no_model_call(self):
        import sqlite3
        excs = (RuntimeError("boom"), ValueError("v"), MemoryError(), RecursionError(), TimeoutError("t"),
                OSError("disk"), sqlite3.OperationalError("locked"), KeyError("k"), AttributeError("a"),
                ImportError("eyecite"), Exception("e"))
        for exc in excs:
            with self.subTest(exc=type(exc).__name__):
                S.calls = 0
                self._patch_check_text(side_effect=exc)
                d = self.route("How does adverse possession work for beachfront property in Florida?")
                self.assertVetoed(d, "check_text raised %s" % type(exc).__name__, hard=True)
                self.assertEqual(d.cause, "precheck_error")
                self.assertEqual(S.calls, 0, "model consulted after the pre-check failed")

    def test_unimportable_gate1_is_direct_db_and_no_model_call(self):
        import pipeline
        saved_mod = sys.modules.get("pipeline.gate1", "__absent__")
        had_attr = hasattr(pipeline, "gate1")
        saved_attr = getattr(pipeline, "gate1", None)

        def restore():
            if saved_mod == "__absent__":
                sys.modules.pop("pipeline.gate1", None)
            else:
                sys.modules["pipeline.gate1"] = saved_mod
            if had_attr:
                pipeline.gate1 = saved_attr
        self.addCleanup(restore)
        sys.modules["pipeline.gate1"] = None
        if had_attr:
            del pipeline.gate1
        _purge_router_modules()
        import router.system_one_client as sc
        self.sc = sc
        d = self.route("How does adverse possession work for beachfront property in Florida?")
        self.assertVetoed(d, "gate1 unimportable", hard=True)
        self.assertEqual(d.cause, "precheck_error")
        self.assertEqual(S.calls, 0)

    def test_precheck_runs_before_a_hung_or_failing_model_is_touched(self):
        S.raise_all = RuntimeError("boom")
        S.hang_infer = True
        t0 = time.time()
        finished, box = run_bounded(lambda: self.route(CITATION_QUERIES["florida dca"]), 5)
        self.assertTrue(finished)
        self.assertVetoed(box["result"], "citation with broken model")
        self.assertEqual(S.entries, 0)
        self.assertLess(time.time() - t0, 3)

    def test_precheck_protects_the_von_path_too(self):
        os.environ["VON_BASE_URL"] = "http://von.invalid:9"
        calls = []

        def spy(*a, **k):
            calls.append(a)
            return _FakeHTTP(VON_OK)
        with mock.patch.object(urllib.request.OpenerDirector, "open", spy):
            for label in ("florida dca", "alabama", "federal reporter", "short cite", "ocr S0.", "id."):
                with self.subTest(shape=label):
                    d = self.sc.route(CITATION_QUERIES[label])
                    self.assertVetoed(d, "citation query on the Von path (%s)" % label)
            self.assertEqual(calls, [], "Von was called with a citation-bearing query")
            # control: a plain-language query does reach Von
            d = self.sc.route("How does adverse possession work for beachfront property in Florida?")
            self.assertEqual(len(calls), 1)
            self.assertEqual(d.route, "boolean_search", d.reason)
        self.assertEqual(S.ctor_attempts, 0)

    def test_precheck_protects_a_custom_client_too(self):
        class _Spy:
            n = 0

            def query(_s, q):
                _Spy.n += 1
                return self.resp()
        self.assertVetoed(self.sc.route(CITATION_QUERIES["florida dca"], client=_Spy()), "custom client")
        self.assertEqual(_Spy.n, 0)

    def test_precheck_does_not_depend_on_a_database_or_network(self):
        with mock.patch.object(urllib.request.OpenerDirector, "open",
                               side_effect=AssertionError("network in pre-check")) as op:
            self.assertVetoed(self.route(CITATION_QUERIES["florida dca"]), "florida cite")
            op.assert_not_called()


class MassFloor(RouterCase):
    """Un-normalized option probability must clear an absolute floor (Choice and Noul separately)."""

    def test_tiny_choice_mass_with_lopsided_confidence_vetoes(self):
        for winner in ROUTES:
            with self.subTest(winner=winner):
                S.choice_w = {o: (1e-8 if o == winner else 1e-10) for o in ROUTES}   # normalised ~0.98
                d = self.route()
                self.assertVetoed(d, "tiny absolute mass, confident after normalising (%s)" % winner)
                self.assertEqual(d.cause, "mass_floor", d.reason)

    def test_tiny_noul_mass_vetoes_even_when_it_says_no(self):
        S.noul_w = {"Yes": 1e-10, "No": 1e-8}                                         # noul_raw ~0.01
        d = self.route()
        self.assertVetoed(d, "tiny noul mass read as 'no citation'")
        self.assertEqual(d.cause, "mass_floor", d.reason)

    def test_answered_decisions_carry_the_mass(self):
        d = self.route()
        self.assertEqual(d.route, "vector_search")
        self.assertEqual(d.cause, "model")
        for part in (d.choice, d.noul):
            self.assertIsNotNone(part.mass)
            self.assertTrue(0.0 < part.mass <= 1.0 + 1e-6, part.mass)
        self.assertGreaterEqual(d.choice.mass, 1e-2)       # CHOICE_MASS_FLOOR placeholder
        self.assertGreaterEqual(d.noul.mass, 5e-2)         # NOUL_MASS_FLOOR placeholder

    def test_zero_mass_everywhere_vetoes(self):
        S.noul_w = {"Yes": 0.0, "No": 0.0}
        self.assertVetoed(self.route(), "zero noul mass")
        S.noul_w = {"Yes": 0.02, "No": 0.95}
        S.choice_w = {o: 0.0 for o in ROUTES}
        self.assertVetoed(self.route(), "zero choice mass")

    def test_floors_are_independent_per_primitive(self):
        # healthy Choice, tiny Noul
        S.noul_w = {"Yes": 1e-10, "No": 1e-8}
        self.assertVetoed(self.route(), "healthy choice, tiny noul")
        # tiny Choice, healthy Noul
        S.noul_w = {"Yes": 0.02, "No": 0.95}
        S.choice_w = {"boolean_search": 1e-10, "vector_search": 1e-8, "direct_db": 1e-10}
        self.assertVetoed(self.route(), "tiny choice, healthy noul")

    def test_healthy_mass_is_followed(self):
        S.choice_w = {"boolean_search": 0.02, "vector_search": 0.90, "direct_db": 0.02}
        S.noul_w = {"Yes": 0.03, "No": 0.90}
        self.assertEqual(self.route().route, "vector_search")

    def test_floor_applies_to_unnormalised_probability_not_to_the_ratio(self):
        # identical ratios, only the absolute scale differs
        S.choice_w = {"boolean_search": 0.02, "vector_search": 0.90, "direct_db": 0.02}
        self.assertEqual(self.route().route, "vector_search")
        S.choice_w = {k: v * 1e-7 for k, v in S.choice_w.items()}
        self.assertVetoed(self.route(), "same ratios at 1e-7 scale")

    def test_direct_api_raises_on_tiny_mass(self):
        import router.jev_cpu_inference as jc
        r = jc.JevCPURouter.load(self.model_path)
        S.choice_w = {"boolean_search": 1e-8, "vector_search": 1e-10, "direct_db": 1e-10}
        with self.assertRaises(self.sc.SystemOneError):
            r.choice(Q)
        S.choice_w = {"boolean_search": 0.02, "vector_search": 0.90, "direct_db": 0.02}
        S.noul_w = {"Yes": 1e-8, "No": 1e-10}
        with self.assertRaises(self.sc.SystemOneError):
            r.noul(Q)

    def test_floor_is_documented_as_an_uncalibrated_placeholder(self):
        blob = "\n".join(t for _, t, _ in _router_sources()).lower()
        self.assertRegex(blob, r"mass[^\n]{0,80}floor|floor[^\n]{0,80}mass", "no absolute-mass floor in router code")


class TokenizationBoundary(RouterCase):
    def test_boundary_merge_between_prompt_and_option_vetoes(self):
        S.tok_merge = True
        self.assertVetoed(self.route(), "prompt/option tokenization boundary mismatch")

    def test_boundary_merge_on_the_direct_api_raises(self):
        import router.jev_cpu_inference as jc
        r = jc.JevCPURouter.load(self.model_path)
        S.tok_merge = True
        with self.assertRaises(self.sc.SystemOneError):
            r.choice(Q)
        with self.assertRaises(self.sc.SystemOneError):
            r.noul(Q)

    def test_without_the_mismatch_the_same_stub_is_followed(self):
        d = self.route()
        self.assertEqual(d.route, "vector_search", d.reason)
        self.assertGreater(len(S.tok_calls), 1)

    def test_unusable_token_ids_veto(self):
        for mode in ("bool", "float", "str", "neg", "huge"):
            with self.subTest(mode=mode):
                S.tok_bad = mode
                self.assertVetoed(self.route(), "tokenizer returned %s ids" % mode)


class ExactOptions(RouterCase):
    def _resp_with_options(self, opts, answer="vector_search"):
        sc = self.sc
        return sc.SystemOneResponse(sc.Choice("q", opts, answer, 0.95), sc.Noul("q", 0.02, "low"),
                                    sc.Score("q", 0.95))

    def test_only_the_exact_allowed_set_is_followed(self):
        d = self.sc.route(Q, client=self.client(self._resp_with_options(ROUTES)))
        self.assertEqual(d.route, "vector_search", d.reason)

    def test_every_other_option_set_vetoes(self):
        cases = {
            "none": None, "string": "boolean_search vector_search direct_db", "empty": (),
            "subset": ROUTES[:2], "superset": ROUTES + ("hybrid_search",), "duplicate": ("vector_search",) * 3,
            "six with duplicates": ROUTES + ROUTES, "None member": ROUTES + (None,),
            "nested list": (["boolean_search"],) + ROUTES[1:], "ints": (1, 2, 3),
            "case": ("Boolean_Search", "vector_search", "direct_db"),
            "leading space": (" boolean_search", "vector_search", "direct_db"),
            "zero-width": ("boolean​_search", "vector_search", "direct_db"),
            "homoglyph": ("bоolean_search", "vector_search", "direct_db"),
            "answer not in options": ("boolean_search", "direct_db", "hybrid_search"),
        }
        for label, opts in cases.items():
            with self.subTest(options=label):
                d = self.sc.route(Q, client=self.client(self._resp_with_options(opts)))
                self.assertVetoed(d, "option set %s" % label)
                self.assertEqual(d.cause, "invalid_response", d.reason)

    def test_answer_outside_the_options_vetoes_even_with_the_right_set(self):
        for ans in ("hybrid_search", "Direct_DB", "direct_db ", "boolean_search\n"):
            with self.subTest(answer=ans):
                d = self.sc.route(Q, client=self.client(self._resp_with_options(ROUTES, ans)))
                self.assertVetoed(d, "answer %r" % ans)


class DirectRouterAPI(RouterCase):
    def setUp(self):
        super().setUp()
        import router.jev_cpu_inference as jc
        self.jc = jc
        self.r = jc.JevCPURouter.load(self.model_path)

    def test_every_option_is_scored_over_all_its_tokens_and_normalised(self):
        S.choice_w = {"boolean_search": 0.50, "vector_search": 0.30, "direct_db": 0.20}
        S.cont = {"vector_search": 0.5}                 # vector full-sequence probability = 0.15
        res = self.r.choice(Q)
        want = {"boolean_search": 0.50, "vector_search": 0.15, "direct_db": 0.20}
        tot = sum(want.values())
        self.assertEqual(set(res.probabilities), set(ROUTES))
        for k, v in want.items():
            self.assertAlmostEqual(res.probabilities[k], v / tot, places=4, msg=k)
        self.assertAlmostEqual(sum(res.probabilities.values()), 1.0, places=9)
        self.assertEqual(res.answer, "boolean_search")
        self.assertAlmostEqual(res.confidence, res.probabilities[res.answer], places=12)
        self.assertIs(res.calibrated, False)

    def test_noul_is_exactly_yes_no(self):
        S.noul_w = {"Yes": 0.30, "No": 0.10}
        res = self.r.noul(Q)
        self.assertEqual(set(res.probabilities), {"Yes", "No"})
        self.assertAlmostEqual(res.noul_raw, 0.75, places=4)
        self.assertAlmostEqual(sum(res.probabilities.values()), 1.0, places=9)
        self.assertIs(res.calibrated, False)

    def test_wrong_option_sets_raise(self):
        bad = ([], (), ["a", "b", "c"], ROUTES[:2], ROUTES[1:], ROUTES + ("hybrid_search",), ["direct_db"] * 3,
               ("Florida", "Alabama", "Other"), "boolean_search", None, set(ROUTES),
               ("boolean_search", "vector_search", "vector_search"), ("Boolean_Search",) + ROUTES[1:],
               (" boolean_search",) + ROUTES[1:])
        for opts in bad:
            with self.subTest(options=repr(opts)):
                with self.assertRaises(self.sc.SystemOneError):
                    self.r.choice(Q, opts)

    def test_option_order_does_not_change_the_answer(self):
        S.choice_w = {"boolean_search": 0.2, "vector_search": 0.6, "direct_db": 0.2}
        a = self.r.choice(Q, ROUTES)
        b = self.r.choice(Q, tuple(reversed(ROUTES)))
        self.assertEqual(a.answer, b.answer)
        for k in ROUTES:
            self.assertAlmostEqual(a.probabilities[k], b.probabilities[k], places=12)

    def test_invalid_text_raises_instead_of_scoring(self):
        for t in ("", " ", "\n\t", None, 5, b"bytes", ["x"], "a" * (self.jc.MAX_QUERY_CHARS + 1)):
            with self.subTest(text=repr(t)[:20]):
                with self.assertRaises(self.sc.SystemOneError):
                    self.r.choice(t)
                with self.assertRaises(self.sc.SystemOneError):
                    self.r.noul(t)

    def test_tie_and_no_signal_raise_never_first_option(self):
        for weights in ({o: 1 / 3 for o in ROUTES}, {o: 0.0 for o in ROUTES},
                        {"boolean_search": 0.45, "vector_search": 0.45, "direct_db": 0.1}):
            with self.subTest(weights=weights):
                S.choice_w = weights
                with self.assertRaises(self.sc.SystemOneError):
                    self.r.choice(Q)

    def test_noul_tie_raises(self):
        S.noul_w = {"Yes": 0.4, "No": 0.4}
        with self.assertRaises(self.sc.SystemOneError):
            self.r.noul(Q)

    def test_no_model_generation_api_is_used(self):
        self.r.choice(Q)
        self.r.noul(Q)
        self.assertEqual(S.gen_calls, 0)

    def test_model_state_does_not_leak_between_calls(self):
        S.choice_w = {"boolean_search": 0.1, "vector_search": 0.7, "direct_db": 0.2}
        first = self.r.choice(Q)
        self.r.noul(CITE_Q)
        for _ in range(3):
            again = self.r.choice(Q)
            for k in ROUTES:
                self.assertAlmostEqual(first.probabilities[k], again.probabilities[k], places=12)

    def test_soft_timeout_between_evals_fails_closed(self):
        r = self.jc.JevCPURouter.load(self.model_path, timeout=-1.0)   # deadline already past
        with self.assertRaises(self.sc.SystemOneError):
            r.choice(Q)


class SharedRouterPolicy(RouterCase):
    def _second_model(self):
        p = os.path.join(self.tmp.name, "second.gguf")
        with open(p, "wb") as fh:
            fh.write(b"GGUF" + b"\0" * 32)
        return p

    def test_a_second_model_path_is_refused_not_answered_by_the_first_model(self):
        self.assertEqual(self.route().route, "vector_search")
        self.use_model(self._second_model())
        d = self.sc.route(Q)
        self.assertVetoed(d, "second JEV_MODEL_PATH in one process", hard=True)
        self.assertEqual(S.constructed, 1)

    def test_a_failed_load_does_not_poison_a_different_path(self):
        S.ctor_error = RuntimeError("oom")
        self.assertVetoed(self.route(), "load failed", hard=True)
        S.ctor_error = None
        self.use_model(self._second_model())
        self.assertEqual(self.sc.route(Q).route, "vector_search")

    def test_model_file_removed_after_load_fails_closed(self):
        self.assertEqual(self.route().route, "vector_search")
        os.remove(self.model_path)
        self.assertVetoed(self.sc.route(Q), "model file vanished", hard=True)


class CalibratedFlag(RouterCase):
    def test_calibrated_false_on_every_outcome(self):
        outcomes = [self.route()]
        S.noul_w = {"Yes": 0.97, "No": 0.01}
        outcomes.append(self.route(CITE_Q))
        S.noul_w = {"Yes": 0.02, "No": 0.95}
        outcomes.append(self.sc.route(Q, client=self.client(exc=RuntimeError())))
        outcomes.append(self.sc.route(Q, client=self.client(self.resp())))
        S.poison_all = "nan"
        outcomes.append(self.route())
        os.environ["VON_BASE_URL"] = "http://von.invalid:9"
        with mock.patch.object(urllib.request.OpenerDirector, "open", lambda *a, **k: _FakeHTTP(VON_OK)):
            outcomes.append(self.route())
        for d in outcomes:
            self.assertSafe(d)
            self.assertIs(d.calibrated, False, d.reason)

    def test_a_client_cannot_claim_calibration(self):
        sc = self.sc
        self.assertIs(sc.CALIBRATION_RECORDED, False)

        class _Liar:
            def query(_s, q):
                return sc.SystemOneResponse(sc.Choice("q", ROUTES, "vector_search", 0.95),
                                            sc.Noul("q", 0.02, "low"), sc.Score("q", 0.95),
                                            calibrated=True, source="von")
        d = sc.route(Q, client=_Liar())
        self.assertEqual(d.route, "vector_search")
        self.assertIs(d.calibrated, False, "route() copied a client's calibrated=True claim")
        # the citation-present branch too
        class _LiarCite(_Liar):
            def query(_s, q):
                return sc.SystemOneResponse(sc.Choice("q", ROUTES, "vector_search", 0.95),
                                            sc.Noul("q", 0.97, "high"), sc.Score("q", 0.95),
                                            calibrated=True, source="von")
        d2 = sc.route(Q, client=_LiarCite())
        self.assertEqual(d2.route, "direct_db")
        self.assertIs(d2.calibrated, False)

    def test_local_client_response_is_uncalibrated_with_log_prob_score(self):
        import router.jev_cpu_inference as jc
        resp = jc.LocalLlamaClient(self.model_path).query(Q)
        self.assertIs(resp.calibrated, False)
        self.assertEqual(resp.source, "local_llama")
        self.assertAlmostEqual(resp.score.value, resp.choice.confidence, places=12)
        self.assertEqual(tuple(resp.choice.options), ROUTES)
        self.assertEqual(S.gen_calls, 0)


# --------------------------------------------------------------------------
# calibration harness (router/calibration.py) and its Nimble contrastive pairs
# --------------------------------------------------------------------------

CITE_RE = re.compile(r"\b\d{1,4}\s+(?:So\.\s?(?:2d|3d)|Fla\. L\. Weekly)\s+[A-Z]?\d+")


class CalibrationHarness(RouterCase):
    def setUp(self):
        super().setUp()
        import router.calibration as cal
        self.cal = cal

    def oracle(self, wrong=()):
        sc, cal = self.sc, self.cal
        items = {i.text: i for i in cal.all_items()}

        class _O:
            def query(_s, q):
                it = items[q]
                if q in wrong:
                    raise RuntimeError("abstain")
                return sc.SystemOneResponse(
                    sc.Choice("q", ROUTES, it.choice_label, 0.99),
                    sc.Noul("q", 0.99 if it.citation_present else 0.01, "x"), sc.Score("q", 0.99))
        return _O()

    def test_import_never_loads_a_model(self):
        self.assertEqual(S.ctor_attempts, 0)

    def test_pair_ids_unique_and_texts_distinct(self):
        pairs = self.cal.CONTRASTIVE_PAIRS
        self.assertEqual(len({p.pair_id for p in pairs}), len(pairs))
        texts = [i.text for i in self.cal.all_items()]
        self.assertEqual(len(set(texts)), len(texts), "duplicate query text across items")
        for p in pairs:
            self.assertNotEqual(p.a.text, p.b.text)
            self.assertTrue(p.feature.strip())

    def test_each_pair_flips_exactly_what_it_claims(self):
        for p in self.cal.CONTRASTIVE_PAIRS:
            with self.subTest(pair=p.pair_id):
                if p.kind == "route":
                    self.assertNotEqual(p.a.choice_label, p.b.choice_label)
                    self.assertEqual(p.a.citation_present, p.b.citation_present)
                elif p.kind == "citation":
                    self.assertNotEqual(p.a.citation_present, p.b.citation_present)
                    # the cited member is taken by the pre-check, so it is direct_db whatever
                    # the plain member's route is (c04: boolean_search)
                    cited = p.a if p.a.citation_present else p.b
                    self.assertEqual(cited.choice_label, "direct_db")
                elif p.kind == "surface":      # surface feature held constant, intent flips the route
                    self.assertNotEqual(p.a.choice_label, p.b.choice_label)
                    self.assertEqual(p.a.citation_present, p.b.citation_present)
                elif p.kind == "edge":         # invariance: the perturbation changes neither label
                    self.assertEqual(p.a.choice_label, p.b.choice_label)
                    self.assertEqual(p.a.citation_present, p.b.citation_present)
                else:
                    self.fail("unknown kind %r" % p.kind)
                for it in (p.a, p.b):
                    self.assertIn(it.choice_label, ROUTES)

    def test_citation_labels_agree_with_the_text(self):
        # edge pairs are deliberately damaged (OCR, homoglyphs, Fed.), so a clean regex cannot judge them
        for p in self.cal.CONTRASTIVE_PAIRS:
            if p.kind == "edge":
                continue
            for it in (p.a, p.b):
                with self.subTest(pair=p.pair_id, text=it.text[:40]):
                    self.assertEqual(bool(CITE_RE.search(it.text)), it.citation_present)

    def test_pair_set_covers_adversarial_edge_cases(self):
        import unicodedata
        texts = [i.text for i in self.cal.all_items()]
        blob = "\n".join(texts)
        checks = {
            "OCR-damaged reporter (S0. / F1a. / FIa.)": re.search(r"\bS0\.|\bF1a\.|\bFIa\.|\b\d+\s+So\.\s?[23]cl\b", blob),
            "non-Latin letter / homoglyph": any(
                ord(c) > 127 and c.isalpha() and not unicodedata.name(c, "").startswith("LATIN") for c in blob),
            "non-Florida Southern Reporter cite (Ala./La./Miss.)": re.search(
                r"So\.\s?(?:2d|3d)?\s?\d+\s*\((?:Ala|La|Miss)\.", blob),
            "Fla. L. Weekly Fed.": "Fla. L. Weekly Fed." in blob,
            "prompt-injection text": re.search(r"(?i)ignore (?:all |the )?(?:previous|above)|route:|answer:|system prompt", blob),
        }
        for name, hit in checks.items():
            with self.subTest(edge_case=name):
                self.assertTrue(hit, "contrastive set has no item for: %s" % name)

    def test_items_do_not_reuse_the_prompt_examples(self):
        import router.jev_cpu_inference as jc
        prompts = jc.build_choice_prompt("x") + jc.build_noul_prompt("x")
        for it in self.cal.all_items():
            self.assertNotIn("100 So. 3d 200", it.text)
        for lit in re.findall(r"'([^']{6,})'", prompts):
            for it in self.cal.all_items():
                self.assertNotIn(lit, it.text, "item reuses a literal from the prompt")

    def test_oracle_control_scores_perfectly_but_stays_uncalibrated(self):
        rep = self._oracle_report()
        self.assertEqual(rep.abstained, 0)
        self.assertEqual(rep.pair_flip_accuracy, 1.0)
        self.assertEqual(rep.choice.accuracy, 1.0)
        self.assertIs(rep.calibrated, False)
        # a perfect oracle on a set below MIN_RELIABLE_N still earns no threshold suggestion
        self.assertLess(rep.n_items, self.cal.MIN_RELIABLE_N)
        self.assertIsNone(rep.suggested_threshold)
        self.assertIsNone(rep.suggested_choice_threshold)
        self.assertIsNone(rep.suggested_noul_threshold)

    def _reduced_pairs(self, n_model):
        """The shipped pair set once, unmodified (so EVERY edge-case class is present), plus clones of
        model-stage-only pairs (cheap: no citation, never gated) until `n_model` model-stage items
        exist. Asserts the edge-case coverage so a class can never be silently dropped."""
        import dataclasses
        cal = self.cal
        base = list(cal.CONTRASTIVE_PAIRS)

        def model_items(p):
            return sum(1 for it in (p.a, p.b) if it.gate != "english" and not it.citation_present)
        out = list(base)
        count = sum(model_items(p) for p in out)
        cloneable = [p for p in base if model_items(p) == 2]
        self.assertTrue(cloneable)
        i = 0
        while count + 2 <= n_model:
            p = cloneable[i % len(cloneable)]
            out.append(dataclasses.replace(
                p, pair_id="%s_x%d" % (p.pair_id, i),
                a=dataclasses.replace(p.a, text="%s (variant %d)" % (p.a.text, i)),
                b=dataclasses.replace(p.b, text="%s (variant %d)" % (p.b.text, i))))
            count += 2
            i += 1
        hits = edge_class_hits([it.text for p in out for it in (p.a, p.b)])
        missing = [k for k, v in hits.items() if not v]
        self.assertEqual(missing, [], "reduced calibration set dropped edge-case classes: %s" % missing)
        return out

    def _oracle_for(self, pairs):
        sc = self.sc
        items = {i.text: i for p in pairs for i in (p.a, p.b)}

        class _O:
            def query(_s, q):
                it = items[q]
                return sc.SystemOneResponse(
                    sc.Choice("q", ROUTES, it.choice_label, 0.99),
                    sc.Noul("q", 0.99 if it.citation_present else 0.01, "x"), sc.Score("q", 0.99))
        return _O()

    def test_reduced_sets_cover_every_edge_case_class(self):
        # the helper itself must be able to fail: dropping a class is detected
        full = [i.text for i in self.cal.all_items()]
        self.assertTrue(all(edge_class_hits(full).values()), edge_class_hits(full))
        for cls in edge_class_hits(full):
            stripped = [t for t in full if not edge_class_hits([t])[cls]]
            self.assertLess(len(stripped), len(full), "no item carries the class %r" % cls)
            self.assertFalse(all(edge_class_hits(stripped).values()),
                             "coverage check did not notice the loss of the %r class" % cls)
            self.assertFalse(edge_class_hits(stripped)[cls])
        for n in (self.cal.MIN_RELIABLE_N, self.cal.MIN_RELIABLE_N - 2):
            pairs = self._reduced_pairs(n)                      # asserts coverage internally
            texts = [it.text for p in pairs for it in (p.a, p.b)]
            self.assertEqual(len(texts), len(set(texts)))

    def test_threshold_is_suggested_only_at_or_above_min_reliable_n(self):
        pairs = self._reduced_pairs(self.cal.MIN_RELIABLE_N)
        rep = self.cal.evaluate(self._oracle_for(pairs), pairs=pairs)
        self.assertGreaterEqual(rep.n_model_stage, self.cal.MIN_RELIABLE_N)
        self.assertIsNotNone(rep.suggested_threshold, "a perfect oracle at n >= MIN_RELIABLE_N earns a suggestion")
        self.assertIs(rep.calibrated, False)
        self.assertEqual(rep.label_mismatches, [])
        # below the minimum (the same edge-case classes still present): no suggestion
        short_pairs = self._reduced_pairs(self.cal.MIN_RELIABLE_N - 2)
        short = self.cal.evaluate(self._oracle_for(short_pairs), pairs=short_pairs)
        self.assertLess(short.n_model_stage, self.cal.MIN_RELIABLE_N)
        self.assertIsNone(short.suggested_threshold)
        self.assertIsNone(short.suggested_choice_threshold)
        self.assertIsNone(short.suggested_noul_threshold)

    def _oracle_report(self):
        """evaluate(oracle) on the shipped set, memoized across the tests that only READ it. Valid to
        share: identical inputs, a pure client, no router state involved (a fresh process-level dict
        is never used by the hang/breaker/concurrency tests)."""
        rep = _ORACLE_REPORTS.get("shipped")
        if rep is None:
            rep = _ORACLE_REPORTS["shipped"] = self.cal.evaluate(self.oracle())
        return rep

    def test_abstentions_are_reported_and_do_not_inflate_accuracy(self):
        import re as _re
        sc, cal = self.sc, self.cal
        items = [i for i in cal.all_items() if i.gate != "english"]   # gated items never reach the client
        model_items = [i for i in items if not i.citation_present]    # the pre-check takes the rest
        n = len(model_items)
        by_text = {i.text: i for i in items}
        answered = {i.text for i in model_items[: n // 2]}

        class _Half:
            def query(_s, q):
                if q not in answered:
                    raise RuntimeError("abstain")
                it = by_text[q]
                return sc.SystemOneResponse(
                    sc.Choice("q", ROUTES, it.choice_label, 0.99),
                    sc.Noul("q", 0.99 if it.citation_present else 0.01, "x"), sc.Score("q", 0.99))
        rep = cal.evaluate(_Half())
        expect_abstained = sum(1 for i in model_items if i.text not in answered)
        self.assertEqual(rep.n_model_stage, n)
        self.assertEqual(rep.abstained, expect_abstained)
        self.assertEqual(rep.abstention_breakdown["error"], expect_abstained)   # the client raised
        self.assertEqual(rep.answered + rep.abstained, rep.n_model_stage)
        self.assertAlmostEqual(rep.abstain_rate, expect_abstained / n, places=9)
        self.assertAlmostEqual(rep.coverage, 1 - expect_abstained / n, places=9)
        # abstentions never inflate accuracy: the overall figures count them as misses, so they
        # cannot exceed coverage even though accuracy over the answered items is 1.0
        self.assertLessEqual(rep.choice_accuracy_overall, rep.coverage + 1e-9)
        self.assertLessEqual(rep.noul_accuracy_overall, rep.coverage + 1e-9)
        self.assertEqual(rep.choice.n, rep.answered)
        # pair flips are measured on routes actually taken, so they equal the recount from rep.items
        self.assertAlmostEqual(rep.pair_flip_accuracy, self._flips_from(rep, cal.CONTRASTIVE_PAIRS), places=9)
        self.assertLess(rep.pair_flip_accuracy, 1.0)
        self.assertTrue(any(_re.search(r"abstain|abstention|no usable", note, _re.I) for note in rep.notes),
                        "report notes do not mention the abstentions: %r" % (rep.notes,))
        self.assertIsNone(rep.suggested_threshold)

    def _flips_from(self, rep, pairs):
        ok = {r.text: r.correct_route for r in rep.items}
        n = 0
        for p in pairs:
            a = ok.get(p.a.text, p.a.gate == "english")      # gated items are caught by the English gate
            b = ok.get(p.b.text, p.b.gate == "english")
            n += bool(a and b)
        return n / len(pairs)

    def test_all_abstaining_client_has_no_accuracy_claim(self):
        rep = self.cal.evaluate(self.client(exc=RuntimeError("x")))
        n_model = sum(1 for i in self.cal.all_items() if i.gate != "english" and not i.citation_present)
        self.assertEqual(rep.n_model_stage, n_model)
        self.assertEqual(rep.abstained, n_model)
        self.assertEqual(rep.abstain_rate, 1.0)
        self.assertEqual(rep.coverage, 0.0)
        self.assertEqual(rep.choice_accuracy_overall, 0.0)
        self.assertEqual(rep.noul_accuracy_overall, 0.0)
        self.assertEqual(rep.abstention_breakdown["error"], n_model)
        self.assertAlmostEqual(rep.pair_flip_accuracy, self._flips_from(rep, self.cal.CONTRASTIVE_PAIRS), places=9)
        self.assertLess(rep.pair_flip_accuracy, 1.0)
        self.assertIsNone(rep.suggested_threshold)
        for v in (rep.choice.accuracy, rep.noul.accuracy):
            self.assertTrue(v != v or v == 0.0, "accuracy %r claimed with every item abstained" % v)  # NaN or 0

    def test_labels_are_consistent_with_the_choice_prompt_definitions(self):
        import router.jev_cpu_inference as jc
        prompt = jc.build_choice_prompt("x")
        # the rules below are read off these definitions; fail loudly if the prompt is reworded
        b_line = re.search(r"boolean_search:[^\n]*", prompt).group(0)
        self.assertRegex(b_line, r"operator|AND")
        self.assertRegex(b_line, r"phrase|quot")
        self.assertRegex(prompt, r"vector_search:[^\n]*plain-language")
        self.assertRegex(prompt, r"direct_db:[^\n]*(specific|known)[^\n]*(case|citation)")
        # Implications read off the definitions (a question is plain language even with quotes or
        # capitalised AND/OR/NOT; a search expression is not a question; a named case is direct_db).
        op = re.compile(r'\b(AND|OR|NOT)\b|"')
        names_case = re.compile(r"\b[A-Z][A-Za-z.'-]+ v\. [A-Z]")
        for it in self.cal.all_items():
            with self.subTest(text=it.text[:60]):
                question = it.text.rstrip().endswith("?")
                if it.choice_label == "boolean_search":
                    self.assertTrue(op.search(it.text) and not question,
                                    "boolean_search must be an operator/quote search expression, not a question")
                if question and op.search(it.text):
                    self.assertNotEqual(it.choice_label, "boolean_search")
                if it.choice_label == "vector_search":
                    self.assertFalse(names_case.search(it.text) or "opinion at" in it.text.lower(),
                                     "names one specific case => direct_db, not vector_search")
                    if op.search(it.text):
                        self.assertTrue(question, "vector_search with quotes/operators must be a plain-language question")
                if names_case.search(it.text) or "opinion at" in it.text.lower():
                    self.assertEqual(it.choice_label, "direct_db" if not op.search(it.text) else it.choice_label)
                if it.choice_label == "direct_db":
                    self.assertTrue(names_case.search(it.text) or CITE_RE.search(it.text)
                                    or "opinion at" in it.text.lower() or "decision" in it.text.lower(),
                                    "direct_db item names no specific case or citation")

    def test_deterministic_precheck_agrees_with_the_citation_labels(self):
        # The shipped route runs the pre-check BEFORE the model; the harness calls the client directly.
        # If the pre-check disagrees with a label, the measured Noul/Choice numbers do not describe
        # what production does with that item. A flagged item must also be labeled direct_db.
        for p in self.cal.CONTRASTIVE_PAIRS:
            for it in (p.a, p.b):
                if it.gate == "english":
                    continue
                with self.subTest(pair=p.pair_id, text=it.text[:60]):
                    found = self.sc.citation_precheck(it.text)
                    self.assertEqual(found is not None, it.citation_present,
                                     "pre-check says %r but the label says citation_present=%s"
                                     % (found, it.citation_present))
                    if found is not None:
                        self.assertEqual(it.choice_label, "direct_db")

    def test_report_label_mismatches_are_empty_against_the_real_precheck(self):
        rep = self._oracle_report()
        self.assertEqual(rep.label_mismatches, [], [(m.pair_id, m.text[:50]) for m in rep.label_mismatches])
        self.assertEqual(rep.gated_failures, [])
        self.assertTrue(all(r.label_agrees_with_precheck for r in rep.items))
        self.assertEqual(rep.precheck_routed, sum(1 for r in rep.items if r.precheck_flagged))
        self.assertEqual(rep.precheck_routed, rep.abstention_breakdown["precheck"])
        self.assertEqual(rep.n_model_stage, rep.n_items - rep.precheck_routed)

    def test_report_items_describe_what_route_did(self):
        rep = self._oracle_report()
        self.assertEqual(len(rep.items), rep.n_items)
        self.assertEqual(sum(rep.causes.values()), rep.n_items)
        for r in rep.items:
            with self.subTest(text=r.text[:50]):
                self.assertIn(r.route, ROUTES)
                self.assertEqual(r.correct_route, r.route == r.expected_route)
                if r.precheck_flagged:
                    self.assertEqual(r.cause, "citation_precheck")
                    self.assertEqual(r.route, "direct_db")
                    self.assertIsNone(r.choice_answer)          # the model was never consulted
                    self.assertIsNone(r.choice_mass)
                else:
                    self.assertEqual(r.cause, "model")
                    self.assertIsNotNone(r.choice_answer)

    def test_precheck_routed_items_never_reach_the_client(self):
        sc, cal = self.sc, self.cal
        seen = []

        class _Rec:
            def query(_s, q):
                seen.append(q)
                it = {i.text: i for i in cal.all_items()}[q]
                return sc.SystemOneResponse(sc.Choice("q", ROUTES, it.choice_label, 0.99),
                                            sc.Noul("q", 0.01, "x"), sc.Score("q", 0.99))
        rep = cal.evaluate(_Rec())
        flagged = {r.text for r in rep.items if r.precheck_flagged}
        self.assertTrue(flagged)
        self.assertFalse(flagged & set(seen), "the client was consulted for a pre-check-flagged item")
        gated = {i.text for i in cal.all_items() if i.gate == "english"}
        self.assertFalse(gated & set(seen), "the client was consulted for an English-gated item")

    def test_duplicate_item_texts_are_rejected(self):
        import dataclasses
        p = self.cal.CONTRASTIVE_PAIRS[0]
        dup = dataclasses.replace(p, pair_id="dup", b=dataclasses.replace(p.b, text=p.a.text))
        with self.assertRaises(ValueError):
            self.cal.evaluate(self.oracle(), pairs=[p, dup])
        dup2 = dataclasses.replace(p, pair_id="dup2")
        with self.assertRaises(ValueError):
            self.cal.evaluate(self.oracle(), pairs=[p, dup2])

    def test_mass_floor_and_breaker_abstentions_are_broken_out(self):
        # the breakdown separates why items had no usable model response
        sc, cal = self.sc, self.cal
        import router.jev_cpu_inference as jc

        class _Floor:
            def query(_s, q):
                raise jc.MassFloorError("floor")

        class _Breaker:
            def query(_s, q):
                raise jc.CircuitOpen("open")
        sub = cal.CONTRASTIVE_PAIRS[:6]      # route pairs: a cheap subset is enough for the breakdown
        n_model = sum(1 for p in sub for i in (p.a, p.b) if i.gate != "english" and not i.citation_present)
        r1 = cal.evaluate(_Floor(), pairs=sub)
        self.assertEqual(r1.abstention_breakdown["mass_floor"], n_model)
        self.assertEqual(r1.abstained, n_model)
        r2 = cal.evaluate(_Breaker(), pairs=sub)
        self.assertEqual(r2.abstention_breakdown["breaker"], n_model)
        self.assertEqual(r2.abstained, n_model)

    def test_below_threshold_items_keep_their_calibration_records(self):
        # items the model answered but the threshold vetoed still count as answered (the threshold
        # under study must not truncate its own data)
        sc, cal = self.sc, self.cal
        items = {i.text: i for i in cal.all_items()}

        class _Low:
            def query(_s, q):
                it = items[q]
                return sc.SystemOneResponse(sc.Choice("q", ROUTES, it.choice_label, 0.6),
                                            sc.Noul("q", 0.01, "x"), sc.Score("q", 0.6))
        rep = cal.evaluate(_Low())
        self.assertEqual(rep.answered, rep.n_model_stage)
        self.assertEqual(rep.abstained, 0)
        self.assertEqual(rep.abstention_breakdown["below_threshold"], rep.n_model_stage)
        self.assertEqual(rep.choice.n, rep.n_model_stage)

    def test_final_route_matches_route_rule(self):
        for it in self.cal.all_items():
            self.assertEqual(it.final_route, "direct_db" if it.citation_present else it.choice_label)

    def test_exposure_bias_both_labels_balanced_inside_every_pair(self):
        # a pair must contain a flip; the set must not be dominated by one label (no label leak)
        from collections import Counter
        labels = Counter(i.choice_label for i in self.cal.all_items())
        total = sum(labels.values())
        for lab in ROUTES:
            self.assertGreater(labels[lab], 0, "no item labeled %s" % lab)
            self.assertLessEqual(labels[lab] / total, 0.65, "label %s dominates the set" % lab)
        cites = [i.citation_present for i in self.cal.all_items()]
        self.assertGreater(sum(cites), 0)
        self.assertGreater(len(cites) - sum(cites), 0)

    def test_constant_confident_client_gets_no_suggested_threshold(self):
        sc = self.sc

        class _Const:
            def query(_s, q):
                return sc.SystemOneResponse(sc.Choice("q", ROUTES, "vector_search", 0.99),
                                            sc.Noul("q", 0.01, "x"), sc.Score("q", 0.99))
        rep = self.cal.evaluate(_Const())
        self.assertLess(rep.pair_flip_accuracy, 1.0)
        self.assertIsNone(rep.suggested_threshold, "a constant answer must not earn a threshold")
        self.assertIs(rep.calibrated, False)

    def test_abstentions_are_counted_and_garbage_is_abstention(self):
        sc = self.sc
        n = sum(1 for i in self.cal.all_items() if i.gate != "english" and not i.citation_present)
        rep = self.cal.evaluate(self.client(exc=RuntimeError("x")))
        self.assertEqual(rep.abstained, n)
        self.assertIsNone(rep.suggested_threshold)
        for conf in (float("nan"), float("inf"), 1.5, -0.1):
            with self.subTest(conf=conf):
                bad = self.client(sc.SystemOneResponse(sc.Choice("q", ROUTES, "vector_search", conf),
                                                       sc.Noul("q", 0.01, "x"), sc.Score("q", 0.9)))
                rep = self.cal.evaluate(bad)
                self.assertEqual(rep.abstained, n)
                self.assertIsNone(rep.suggested_threshold)
        rep = self.cal.evaluate(self.client(sc.SystemOneResponse(
            sc.Choice("q", ROUTES, "hybrid_search", 0.99), sc.Noul("q", 0.01, "x"), sc.Score("q", 0.9))))
        self.assertEqual(rep.abstained, n)

    def test_report_flags_a_small_sample(self):
        rep = self._oracle_report()
        self.assertLess(rep.n_model_stage, self.cal.MIN_RELIABLE_N)
        self.assertTrue(any(str(rep.n_model_stage) in note for note in rep.notes), rep.notes)

    def test_evaluate_never_changes_the_live_threshold_or_flag(self):
        before = self.sc.DEFAULT_THRESHOLD
        self.cal.evaluate(self.oracle())
        self.assertEqual(self.sc.DEFAULT_THRESHOLD, before)
        self.assertEqual(before, 0.80)
        self.assertIs(self.sc.CALIBRATION_RECORDED, False)
        self.assertIs(self.sc.RouteDecision.__dataclass_fields__["calibrated"].default, False)
        self.assertIs(self.sc.SystemOneResponse.__dataclass_fields__["calibrated"].default, False)

    def test_empty_pair_list_does_not_crash(self):
        rep = self.cal.evaluate(self.oracle(), pairs=[])
        self.assertEqual(rep.n_items, 0)
        self.assertIsNone(rep.suggested_threshold)


if __name__ == "__main__":
    unittest.main()
