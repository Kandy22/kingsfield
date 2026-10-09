"""A fake llama.cpp surface with scripted, deterministic log-probs.

Exposes exactly what router/jev_cpu_inference.py uses and nothing else:
tokenize / reset / eval / scores / n_tokens / n_ctx. There is deliberately NO
generation method (no __call__, create_completion, generate), so any code that
tried to parse model text would fail on this stub. Trap versions of those
methods are available through `trap_generation=True`.

Token layout (ids are arbitrary but fixed):
    1            BOS
    2 / 3        prompt kind marker: 2 = Choice prompt, 3 = Noul prompt
    4            filler (one per ~10 query chars, so long queries overflow n_ctx)
    5            the query "looks like it has a citation string" (stub perception)
    6            the query "has boolean operators or quotes"
    7            the query "asks to pull one specific opinion"
    10,11        boolean_search     12,13  vector_search     14,15,16  direct_db
    17           Yes                18     No
A policy maps (kind, flags, option-token-prefix) to a next-token distribution,
given as {token_id: probability} (unlisted tokens get logit -inf, leftover mass
goes to token 0) or as a raw list of logits (to inject NaN / inf).
"""
import math
import re

VOCAB = 24
BOS, KIND_CHOICE, KIND_NOUL, FILLER = 1, 2, 3, 4
F_CITE, F_BOOL, F_PULL = 5, 6, 7

OPTION_TOKENS = {
    "boolean_search": (10, 11),
    "vector_search": (12, 13),
    "direct_db": (14, 15, 16),
    "Yes": (17,),
    "No": (18,),
}

_CITE = re.compile(r"\d+\s+So\.\s*(2d|3d)\s+\d+|\d+\s+Fla\. L\. Weekly")
_BOOL = re.compile(r'\bAND\b|\bOR\b|\bNOT\b|"')
_PULL = re.compile(r"^Pull the opinion")


def row_from_probs(probs, vocab=VOCAB):
    total = sum(probs.values())
    assert total <= 1.0 + 1e-12, f"probabilities sum to {total}"
    row = [-math.inf] * vocab
    for tok, p in probs.items():
        row[tok] = math.log(p)
    rest = 1.0 - total
    if rest > 1e-12:
        assert 0 not in probs
        row[0] = math.log(rest)
    return row


def tree(option_probs):
    """{option tokens: [p_tok0, p_tok1, ...]} -> {prefix: {token: p}}."""
    out = {}
    for toks, ps in option_probs.items():
        assert len(toks) == len(ps)
        for j, (t, p) in enumerate(zip(toks, ps)):
            out.setdefault(tuple(toks[:j]), {})[t] = p
    return out


def static_policy(choice=None, noul=None):
    """Same distributions for every query. choice/noul: {option: [per-token p]}."""
    trees = {
        KIND_CHOICE: tree({OPTION_TOKENS[o]: ps for o, ps in (choice or {}).items()}),
        KIND_NOUL: tree({OPTION_TOKENS[o]: ps for o, ps in (noul or {}).items()}),
    }

    def policy(kind, flags, prefix):
        return trees[kind].get(prefix, {0: 1.0})
    return policy


def choice_probs(winner, win=(0.90, 0.95, 0.99), lose=(0.05, 0.50, 0.50)):
    """Per-token conditional probabilities making `winner` the clear choice."""
    out = {}
    for opt in ("boolean_search", "vector_search", "direct_db"):
        n = len(OPTION_TOKENS[opt])
        out[opt] = list(win[:n]) if opt == winner else list(lose[:n])
    return out


def oracle_policy(confident=True):
    """Stub perception of the query: a regex stands in for the model's reading."""
    def policy(kind, flags, prefix):
        if kind == KIND_NOUL:
            p_yes = 0.97 if F_CITE in flags else 0.03
            return tree({OPTION_TOKENS["Yes"]: [p_yes],
                         OPTION_TOKENS["No"]: [1.0 - p_yes]}).get(prefix, {0: 1.0})
        if F_PULL in flags:
            winner = "direct_db"
        elif F_BOOL in flags:
            winner = "boolean_search"
        else:
            winner = "vector_search"
        return tree({OPTION_TOKENS[o]: ps
                     for o, ps in choice_probs(winner).items()}).get(prefix, {0: 1.0})
    return policy


class FakeLlama:
    def __init__(self, policy, n_ctx=128, tokens=None):
        self.policy = policy
        self._n_ctx = n_ctx
        self.n_tokens = 0
        self.scores = [None] * n_ctx
        self.ctx = []
        self.tokenize_calls = []
        self.eval_calls = []
        self.reset_calls = 0
        self.option_tokens = dict(tokens or OPTION_TOKENS)
        self.stuck_eval = False          # eval() that fails to advance n_tokens
        self.raise_in_eval = None
        self.generation_calls = 0
        self.merge_options = set()       # options whose joint tokenization differs
        self.hang = None                 # threading.Event: eval blocks until set

    def n_ctx(self):
        return self._n_ctx

    # ---- the llama.cpp surface -------------------------------------------
    def tokenize(self, text, add_bos=True, special=False):
        self.tokenize_calls.append((text, add_bos, special))
        return self._tok(text.decode("utf-8"), add_bos)

    def _tok(self, s, add_bos):
        if add_bos is False:  # an option continuation
            return list(self.option_tokens[s.strip()])
        # prompt + " " + option, tokenized jointly: normally the concatenation
        # of the two parts; options in merge_options model a tokenizer that
        # merges across the boundary and so yields different tokens.
        for opt, toks in self.option_tokens.items():
            suffix = " " + opt
            if s.endswith(suffix) and s[: -len(suffix)].endswith(("Route:", "Answer:")):
                base = self._tok(s[: -len(suffix)], True)
                tail = [t + 50 for t in toks] if opt in self.merge_options else list(toks)
                return base + tail
        for marker, kind in (("\nQuery: ", KIND_CHOICE), ("\nText: ", KIND_NOUL)):
            head, sep, tail = s.partition(marker)
            if sep:
                query = tail.rsplit("\n", 1)[0]
                flags = []
                if _CITE.search(query):
                    flags.append(F_CITE)
                if _BOOL.search(query):
                    flags.append(F_BOOL)
                if _PULL.search(query):
                    flags.append(F_PULL)
                return [BOS, kind] + flags + [FILLER] * (len(query) // 10)
        return [BOS, KIND_CHOICE]

    def reset(self):
        self.reset_calls += 1
        self.n_tokens = 0
        self.ctx = []

    def eval(self, tokens):
        if self.hang is not None:
            self.hang.wait(10)           # bounded so a failed test cannot leak a thread forever
        if self.raise_in_eval is not None:
            raise self.raise_in_eval
        self.eval_calls.append(list(tokens))
        if self.stuck_eval:
            return
        self.ctx = self.ctx[: self.n_tokens]          # rewind like kv_cache_seq_rm
        for tok in tokens:
            assert len(self.ctx) < self._n_ctx, "context overflow in stub"
            self.ctx.append(tok)
            self.scores[len(self.ctx) - 1] = self._row(tuple(self.ctx))
        self.n_tokens = len(self.ctx)

    def _row(self, ctx):
        if len(ctx) < 2:                  # BOS alone: nothing scripted
            return row_from_probs({0: 1.0})
        kind = ctx[1]
        flags = {t for t in ctx if t in (F_CITE, F_BOOL, F_PULL)}
        prefix = tuple(t for t in ctx if t >= 10)
        out = self.policy(kind, flags, prefix)
        return list(out) if isinstance(out, (list, tuple)) else row_from_probs(out)


def wait_for_workers(timeout=5.0):
    """Join orphaned jev-worker threads left by earlier hang tests (their events
    are already released), so they cannot race a patched clock."""
    import threading
    import time
    end = time.monotonic() + timeout
    for t in threading.enumerate():
        if t.name == "jev-worker" and t is not threading.current_thread():
            t.join(max(0.0, end - time.monotonic()))


def scripted_clock(values, real=None):
    """A time.monotonic replacement that serves `values` only to the FIRST thread
    that calls it (then repeats the last value) and the real clock to every other
    thread, so orphaned worker threads from earlier tests cannot consume ticks."""
    import threading
    import time
    real = real or time.monotonic
    state = {"owner": None, "i": 0}
    lock = threading.Lock()

    def clock():
        me = threading.get_ident()
        with lock:
            if state["owner"] is None:
                state["owner"] = me
            if state["owner"] != me:
                return real()
            i = min(state["i"], len(values) - 1)
            state["i"] += 1
            return values[i]
    return clock


class TrappedFakeLlama(FakeLlama):
    """Adds text-generation entry points that name a route. If the router ever
    parsed model text, it would pick up this answer. It must never be called."""

    def _trap(self, *a, **k):
        self.generation_calls += 1
        return {"choices": [{"text": " boolean_search"}, ]}

    __call__ = create_completion = generate = create_chat_completion = sample = _trap
