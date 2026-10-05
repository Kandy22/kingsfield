"""Gate 1 (Existence): deterministic local Florida citation check. Reference implementation.

Constraint A. No model calls, no network, identical output on every run. Fails closed:
any error, unparseable input, missing database or missing table is a veto.

Verdicts (identical to backend/src/verification/local_sqlite_gate.ts):
    pass          Florida citation found locally; caption (if given) and pin (if given) check out.
    veto          Florida (or malformed Southern Reporter) citation that fails ANY check, or any error.
    fall_through  Not a Florida key; the caller sends it to CourtListener citationLookup().

Florida keys: So., So. 2d, So. 3d with a Florida court in the parenthetical, plus
Fla. L. Weekly and Fla. L. Weekly Supp. (in scope even before data is loaded).
Southern Reporter with no court parenthetical is vetoed as malformed. Fla. L. Weekly Fed.
is federal and falls through.

Division of labour. eyecite finds citations in free text (check_text) and cross-checks the
single-citation parse; reporters_db supplies the reporter variants that are normalized to
canonical keys. The verdict itself comes from the strict grammar below, which the TypeScript
gate mirrors line for line. Scope is decided from the raw reporter text, never from eyecite's
edition guess: eyecite reads "Fla. L. Weekly D123" as the federal "Fla. L. Weekly Fed. D".

The grammar is ASCII-only on purpose. Input is NFKC-normalized and whitespace-collapsed,
then matched exactly; anything that is still non-ASCII in the citation core (a surviving
homoglyph, a non-ASCII digit, a zero-width character) fails to parse and is vetoed.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional, Tuple

DEFAULT_DB = Path(__file__).resolve().parent.parent / "kingsfield_florida.db"

PASS = "pass"
VETO = "veto"
FALL_THROUGH = "fall_through"

MAX_CITATION_CHARS = 2000
DB_TIMEOUT_SECONDS = 2.0

# Caption similarity: Jaccard over pg_trgm-style trigrams, all-integer so Python and
# TypeScript agree exactly. Pass if jaccard >= 1/2, or if the smaller trigram set (at
# least CONTAINMENT_MIN_TRIGRAMS) is >= 9/10 contained in the larger one (short form vs
# full form of the same caption).
JACCARD_NUM, JACCARD_DEN = 1, 2
CONTAINMENT_NUM, CONTAINMENT_DEN = 9, 10
CONTAINMENT_MIN_TRIGRAMS = 8


@dataclass(frozen=True)
class Gate1Result:
    verdict: str
    reason: str
    reporter: Optional[str] = None
    volume: Optional[int] = None
    page: Optional[int] = None
    cluster_id: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Reporter tables, derived from reporters_db
# ---------------------------------------------------------------------------

SOUTHERN_KEYS = ("So.", "So. 2d", "So. 3d")
WEEKLY = "Fla. L. Weekly"
WEEKLY_SUPP = "Fla. L. Weekly Supp."


def _loose(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _build_reporter_tables() -> Tuple[dict, frozenset]:
    """Return (exact variant -> canonical Southern key, loose keys of every in-scope spelling)."""
    import reporters_db

    exact = {}
    loose = set()
    for entry in reporters_db.REPORTERS["So."]:
        for ed in entry["editions"]:
            if ed in SOUTHERN_KEYS:
                exact[ed] = ed
        for variant, canon in entry["variations"].items():
            if canon in SOUTHERN_KEYS:
                loose.add(_loose(variant))
                # A variant containing a comma or parenthesis can never be one reporter
                # token; it is left out of the exact table and caught by the loose guard.
                if not re.search(r"[(),]", variant) and re.fullmatch(r"[A-Za-z0-9.&' ]+", variant):
                    exact[variant] = canon
    for k in SOUTHERN_KEYS:
        loose.add(_loose(k))
    loose.update(_loose(k) for k in (WEEKLY, WEEKLY_SUPP))
    return exact, frozenset(loose)


SOUTHERN_EXACT, IN_SCOPE_LOOSE = _build_reporter_tables()


def _build_known_reporters() -> frozenset:
    """Every reporter spelling reporters_db recognizes (editions and variations), restricted
    to what the ASCII grammar can ever produce as a reporter token."""
    import reporters_db

    known = set()
    for entries in reporters_db.REPORTERS.values():
        for entry in entries:
            known.update(entry["editions"])
            known.update(entry["variations"])
    return frozenset(k for k in known if re.fullmatch(r"[A-Za-z0-9.&' ]+", k))


# Recognized, non-Florida-key reporters (WL, F.3d, Fla. Supp., Fla.) fall through under
# Constraint A even when cited with a Florida court; unrecognized ones do not.
KNOWN_REPORTERS = _build_known_reporters()

_SOUTHERN_LOOSE_SHAPE = re.compile(r"^(?:so|sou|south|southern)(?:rep|reporter)?(?:[234](?:d|nd|rd|th))?$")
_WEEKLY_PLAIN = re.compile(r"^Fla\. L\. Weekly(?: ([A-Z]))?$")

# ---------------------------------------------------------------------------
# Normalization (mirrored in TypeScript)
# ---------------------------------------------------------------------------

_WS = "[ \\t\\n\\r\\f\\v\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000]"
_WS_RUN = re.compile(_WS + "+")
_WS_EDGE = re.compile("^" + _WS + "+|" + _WS + "+$")


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = _WS_RUN.sub(" ", s)
    return _WS_EDGE.sub("", s)


# ---------------------------------------------------------------------------
# Grammar (ASCII only; every class is explicit so Unicode digits/letters never match)
# ---------------------------------------------------------------------------

_CITE_START = re.compile(r"(?<![A-Za-z0-9])[0-9]{1,4}(?= )")
_GENERIC = re.compile(
    r"(?<![A-Za-z0-9])([0-9]{1,4}) "
    r"([A-Z][A-Za-z0-9.&']*(?: [A-Za-z0-9.&']+){0,4}?) "
    r"([A-Z]?[0-9]{1,6})(?![A-Za-z0-9])"
)
_PIN = re.compile(r"^(?:, ?(?:at )?| at )([0-9]{1,6})(?:[-–—]([0-9]{1,6}))?(?: ?n\.? ?[0-9]{1,3})?")
_PAREN = re.compile(r"^ ?\(([^()]*)\)")
_MONTH = "(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)"
_COURT_YEAR = re.compile(r"^(.*?),? ?(?:" + _MONTH + r"\.? [0-9]{1,2}, )?([0-9]{4})$")
_FLORIDA_COURT = re.compile(
    r"^Fla\.(?: (?:[1-6](?:st|nd|rd|th|d) (?:DCA|Dist\. Ct\. App\.|Dist\.)"
    r"|Dist\. Ct\. App\.|Sup\. Ct\.|App\.(?: [1-6](?:st|nd|rd|th|d) Dist\.)?))?$"
)
# Positive identification of non-Florida courts. A Southern Reporter cite falls through only
# when its parenthetical matches one of these exactly; anything else vetoes.
_STATE_ABBREVS = (
    "Ala.", "Alaska", "Ariz.", "Ark.", "Cal.", "Colo.", "Conn.", "Del.", "Fla.", "Ga.", "Haw.", "Idaho",
    "Ill.", "Ind.", "Iowa", "Kan.", "Ky.", "La.", "Me.", "Md.", "Mass.", "Mich.", "Minn.", "Miss.", "Mo.",
    "Mont.", "Neb.", "Nev.", "N.H.", "N.J.", "N.M.", "N.Y.", "N.C.", "N.D.", "Ohio", "Okla.", "Or.", "Pa.",
    "R.I.", "S.C.", "S.D.", "Tenn.", "Tex.", "Utah", "Vt.", "Va.", "Wash.", "W. Va.", "Wis.", "Wyo.",
    "D.C.", "P.R.",
)
_STATES_RE = "|".join(re.escape(x) for x in _STATE_ABBREVS)
_CIRCUIT_ORD = "[1-5](?:st|nd|rd|th|d)?"
_NON_FLORIDA_COURT = re.compile(
    "^(?:"
    r"Ala\.(?: (?:App\.|Civ\. App\.|Crim\. App\.|Ct\. App\.|Ct\. Civ\. App\.|Ct\. Crim\. App\.|Cir\. Ct\.|Sup\. Ct\.))?"
    r"|La\.(?: (?:Ct\. )?App\.(?: " + _CIRCUIT_ORD + r" Cir\.| Orleans)?| Dist\. Ct\.| Sup\. Ct\.)?"
    r"|Miss\.(?: (?:Ct\. App\.|App\.|Cir\. Ct\.|Ch\. Ct\.|Cnty\. Ct\.|Sup\. Ct\.))?"
    r"|(?:1st|2d|3d|4th|5th|6th|7th|8th|9th|10th|11th) Cir\.|D\.C\. Cir\.|Fed\. Cir\."
    r"|U\.S\.(?: Sup\. Ct\.)?|Fed\. Cl\.|Ct\. Int'l Trade"
    r"|(?:Bankr\. )?(?:[NSEWMC]\.D\.|D\.) (?:" + _STATES_RE + ")"
    ")$"
)
_FLORIDAISH = re.compile(r"fla|\bfl")
# OCR confusables: 0 reads as o; 1, i, | read as l.
_OCR_COURT_TABLE = str.maketrans({"1": "l", "i": "l", "|": "l", "0": "o"})
_OCR_REPORTER_TABLE = str.maketrans({"0": "o", "1": "l", "I": "l"})
_SIGNAL = re.compile(r"^(?:See also|See generally|See|Cf\.|Accord|But see|But cf\.|Compare|Contra|E\.g\.),? ")
_CASE_NAME = re.compile(r"(?: v\.? )|^(?:In re|Ex parte|Matter of|Estate of|State ex rel\.|Application of) ")

_NON_ASCII = re.compile(r"[^\x00-\x7f]")


@dataclass(frozen=True)
class _Parsed:
    reporter: str            # canonical key, or raw reporter text when kind == "other"
    volume: int
    page: int
    section: str             # Fla. L. Weekly division letter ("D500" -> "D"); "" otherwise
    kind: str                # "southern" | "weekly" | "other"
    pins: Tuple[Tuple[int, Optional[int]], ...]
    court: Optional[str]     # text of the first parenthetical after the pin cites
    prefix: str              # text before the volume
    start: int
    end: int                 # end of the core reporter citation
    tail_end: int            # end of core + pin cites + first parenthetical


def _veto(reason: str, p: Optional[_Parsed] = None, cluster_id: Optional[int] = None) -> Gate1Result:
    if p is None:
        return Gate1Result(VETO, reason)
    return Gate1Result(VETO, reason, p.reporter, p.volume, p.page, cluster_id)


def _tail(s: str, end: int):
    """Parse pin cites and the first parenthetical after a core citation ending at `end`.

    Returns (pins, tail_end, paren_content_or_None, paren_span_or_None).
    """
    rest = s[end:]
    pins: List[Tuple[int, Optional[int]]] = []
    while True:
        pm = _PIN.match(rest)
        if not pm:
            break
        pins.append((int(pm.group(1)), int(pm.group(2)) if pm.group(2) else None))
        rest = rest[pm.end():]
    tail_end = len(s) - len(rest)
    cm = _PAREN.match(rest)
    if not cm:
        return pins, tail_end, None, None
    return pins, tail_end + cm.end(), cm.group(1), (tail_end, tail_end + cm.end())


def _court_name(content: str) -> str:
    m = _COURT_YEAR.match(content)
    name = m.group(1) if m else content
    return re.sub(r"[ ,]+$", "", name)


def _court_known(content: Optional[str]) -> bool:
    if content is None or _NON_ASCII.search(content):
        return False
    name = _court_name(content)
    return bool(_FLORIDA_COURT.match(name) or _NON_FLORIDA_COURT.match(name))


def _scan(s: str) -> List[re.Match]:
    """All generic reporter-citation matches in s, including overlapping ones.

    A candidate that starts inside the court parenthetical of an earlier match is skipped,
    but only when that parenthetical is a recognized court ("La. App. 1 Cir. 2015" must not
    yield a second citation "1 Cir. 2015"). An unrecognized parenthetical hides nothing.
    """
    out = []
    spans: List[Tuple[int, int]] = []
    for cand in _CITE_START.finditer(s):
        pos = cand.start()
        if any(a <= pos < b for a, b in spans):
            continue
        m = _GENERIC.match(s, pos)
        if not m:
            continue
        out.append(m)
        _pins, _end, content, span = _tail(s, m.end())
        if span is not None and _court_known(content):
            spans.append(span)
    return out


def _classify(raw_reporter: str, page_text: str) -> Tuple[str, Optional[str], Optional[str]]:
    """Return (kind, canonical, problem). problem is a veto reason or None."""
    letter = page_text[0] if page_text[:1].isalpha() else None
    canon = SOUTHERN_EXACT.get(raw_reporter)
    if canon is not None:
        return ("southern", canon, "bad_page" if letter else None)
    if raw_reporter == WEEKLY_SUPP:
        return ("weekly", WEEKLY_SUPP, "bad_page" if letter else None)
    wm = _WEEKLY_PLAIN.match(raw_reporter)
    if wm:
        if wm.group(1) and letter:
            return ("weekly", WEEKLY, "bad_page")
        return ("weekly", WEEKLY, None)
    for lk in (_loose(raw_reporter), _loose(raw_reporter.translate(_OCR_REPORTER_TABLE))):
        if (
            lk in IN_SCOPE_LOOSE
            or _SOUTHERN_LOOSE_SHAPE.match(lk)
            or (lk.startswith("fl") and ("weekly" in lk or "wkly" in lk) and "fed" not in lk)
        ):
            return ("other", None, "ambiguous_reporter")
    return ("other", raw_reporter, None)


def _parse_match(s: str, m: re.Match) -> Tuple[Optional[_Parsed], Optional[str]]:
    kind, canon, problem = _classify(m.group(2), m.group(3))
    if problem:
        return None, problem
    page_text = m.group(3)
    letter = page_text[0] if page_text[:1].isalpha() else None
    page = int(page_text[1:] if letter else page_text)
    section = ""
    if kind == "weekly":
        wm = _WEEKLY_PLAIN.match(m.group(2))
        section = (wm.group(1) if wm and wm.group(1) else None) or (letter or "")
    pins, tail_end, court, _span = _tail(s, m.end())
    parsed = _Parsed(
        reporter=canon or m.group(2),
        volume=int(m.group(1)),
        page=page,
        section=section,
        kind=kind,
        pins=tuple(pins),
        court=court,
        prefix=s[: m.start()],
        start=m.start(),
        end=m.end(),
        tail_end=tail_end,
    )
    return parsed, None


def _floridaish(name: str) -> bool:
    return bool(_FLORIDAISH.search(name.lower().translate(_OCR_COURT_TABLE)))


def _ocr_florida_court(name: str) -> bool:
    """True if name is a Florida court exactly, or after OCR-folding only its leading 'Fla.' token."""
    if _FLORIDA_COURT.match(name):
        return True
    tok, _, rest = name.partition(" ")
    if tok.lower().translate(_OCR_COURT_TABLE) == "fla.":
        return bool(_FLORIDA_COURT.match("Fla." + (" " + rest if rest else "")))
    return False


def _court_scope(court: Optional[str]) -> Tuple[str, str]:
    """Return (decision, reason): decision is 'florida' | 'fall_through' | 'veto'.

    Fall-through requires a positive match against a known non-Florida court. Everything
    unrecognized vetoes: 'ambiguous_court' when it looks like a (possibly OCR-damaged)
    Florida court, 'malformed' otherwise.
    """
    if court is None:
        return ("veto", "malformed")
    if _NON_ASCII.search(court):
        return ("veto", "non_ascii_court")
    name = _court_name(court)
    if name == "":
        return ("veto", "malformed")
    if _FLORIDA_COURT.match(name):
        return ("florida", "ok")
    if _NON_FLORIDA_COURT.match(name):
        return ("fall_through", "non_florida_court")
    if _floridaish(name) or _ocr_florida_court(name):
        return ("veto", "ambiguous_court")
    return ("veto", "malformed")


# ---------------------------------------------------------------------------
# Caption trigrams
# ---------------------------------------------------------------------------

_DESIGNATION = re.compile(r"\b(?:et al|et ux|et vir)\b\.?")
# Typographic punctuation that is common in captions and carries no identity.
_TYPO_PUNCT = re.compile("[\u00a7\u00b6\u00b7\u2010-\u2015\u2018-\u201f\u2022\u2026\u02bc]")


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = unicodedata.normalize("NFD", s)
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn")


def _caption_tokens(folded: str) -> str:
    s = folded.lower().replace("&", " and ")
    s = _DESIGNATION.sub(" ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return s.strip()


def _trigrams(tokens: str) -> frozenset:
    grams = set()
    for word in tokens.split(" "):
        if not word:
            continue
        padded = "  " + word + " "
        for i in range(len(padded) - 2):
            grams.add(padded[i:i + 3])
    return frozenset(grams)


def caption_matches(given: str, stored: Optional[str]) -> Tuple[bool, str]:
    """Return (ok, reason). Strict on the given side: a surviving non-ASCII character fails."""
    if stored is None or normalize(stored) == "":
        return False, "caption_unverifiable"
    g = _TYPO_PUNCT.sub(" ", _fold(given))
    if _NON_ASCII.search(g):
        return False, "caption_non_ascii"
    a = _trigrams(_caption_tokens(g))
    b = _trigrams(_caption_tokens(_NON_ASCII.sub(" ", _TYPO_PUNCT.sub(" ", _fold(stored)))))
    if not a or not b:
        return False, "caption_mismatch"
    inter = len(a & b)
    union = len(a | b)
    if inter * JACCARD_DEN >= union * JACCARD_NUM:
        return True, "ok"
    small = min(len(a), len(b))
    if small >= CONTAINMENT_MIN_TRIGRAMS and inter * CONTAINMENT_DEN >= small * CONTAINMENT_NUM:
        return True, "ok"
    return False, "caption_mismatch"


def _caption_from_prefix(prefix: str) -> Optional[str]:
    p = prefix
    for _ in range(4):
        n = _SIGNAL.sub("", p, count=1)
        if n == p:
            break
        p = n
    p = re.sub(r"[ ,]+$", "", p)
    if p and _CASE_NAME.search(p):
        return p
    return None


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------


def _lookup(db_path, reporter: str, volume: int, page: int, section: str) -> List[tuple]:
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=DB_TIMEOUT_SECONDS)
    try:
        conn.execute("PRAGMA query_only = 1")
        return conn.execute(
            "SELECT cluster_id, case_name, first_page, last_page, court_id FROM citation_index "
            "WHERE reporter = ? AND volume = ? AND page = ? AND section = ? ORDER BY cluster_id",
            (reporter, volume, page, section),
        ).fetchall()
    finally:
        conn.close()


def _court_level(court: Optional[str]) -> Optional[str]:
    """'fla' (Supreme Court) or 'dca' from the citing parenthetical; None if not a Florida court.

    DCA district numbers are deliberately not compared: CourtListener lumps every DCA into
    the single court_id 'fladistctapp'.
    """
    if court is None or _NON_ASCII.search(court):
        return None
    name = _court_name(court)
    if name in ("Fla.", "Fla. Sup. Ct."):
        return "fla"
    return "dca" if _FLORIDA_COURT.match(name) else None


def _row_problem(p: _Parsed, caption: Optional[str], row: tuple) -> Optional[str]:
    _cluster_id, case_name, first_page, last_page, court_id = row
    level = _court_level(p.court)
    if (level == "dca" and court_id == "fla") or (level == "fla" and court_id == "fladistctapp"):
        return "court_mismatch"
    if caption is not None:
        ok, why = caption_matches(caption, case_name)
        if not ok:
            return why
    if p.pins:
        lo = first_page if first_page is not None else p.page
        if last_page is None:
            return "pin_unverifiable"
        if last_page < lo:
            return "bad_bounds"
        for a, b in p.pins:
            if b is not None and b < a:
                return "pin_out_of_bounds"
            for x in (a, b):
                if x is not None and not (lo <= x <= last_page):
                    return "pin_out_of_bounds"
    return None


def _check_florida(p: _Parsed, db_path) -> Gate1Result:
    rows = _lookup(db_path, p.reporter, p.volume, p.page, p.section)
    if not rows:
        return _veto("not_found", p)
    caption = _caption_from_prefix(p.prefix)
    first_problem = None
    for row in rows:
        problem = _row_problem(p, caption, row)
        if problem is None:
            return Gate1Result(PASS, "verified", p.reporter, p.volume, p.page, row[0])
        if first_problem is None:
            first_problem = (problem, row[0])
    return _veto(first_problem[0], p, first_problem[1])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _eyecite_full_cites(s: str):
    from eyecite import get_citations
    from eyecite.models import FullCaseCitation

    return [c for c in get_citations(s) if isinstance(c, FullCaseCitation)]


def _check_normalized(s: str, db_path) -> Gate1Result:
    if len(s) > MAX_CITATION_CHARS:
        return _veto("too_long")
    matches = _scan(s)
    if not matches:
        return _veto("unparseable")
    if len(matches) > 1:
        return _veto("multiple_citations")
    parsed, problem = _parse_match(s, matches[0])
    if problem:
        return _veto(problem)
    p = parsed
    assert p is not None

    if p.kind == "other":
        if p.reporter not in KNOWN_REPORTERS and p.court is not None and not _NON_ASCII.search(p.court):
            cname = _court_name(p.court)
            if cname and _ocr_florida_court(cname):
                return _veto("florida_court_unknown_reporter", p)
        return Gate1Result(FALL_THROUGH, "not_florida_key", p.reporter, p.volume, p.page)

    if p.kind == "southern":
        decision, why = _court_scope(p.court)
        if decision == "veto":
            return _veto(why, p)
        if decision == "fall_through":
            return Gate1Result(FALL_THROUGH, why, p.reporter, p.volume, p.page)

    # Cross-check against eyecite. It can only tighten: a second citation, or a different
    # volume/page for the same Southern key, is a veto. Silence from eyecite is not.
    try:
        cites = _eyecite_full_cites(s)
    except Exception:
        return _veto("extractor_error", p)
    if len(cites) > 1:
        return _veto("multiple_citations", p)
    if len(cites) == 1 and p.kind == "southern":
        g = cites[0].groups
        e_canon = SOUTHERN_EXACT.get(g.get("reporter") or "")
        if e_canon == p.reporter and (_digits(g.get("volume")), _digits(g.get("page"))) != (p.volume, p.page):
            return _veto("extractor_disagreement", p)

    try:
        return _check_florida(p, db_path)
    except Exception:
        return _veto("db_unavailable", p)


def _digits(v: Optional[str]) -> Optional[int]:
    return int(v) if v is not None and re.fullmatch(r"[0-9]{1,9}", v) else None


def check_citation(citation: str, db_path=DEFAULT_DB) -> Gate1Result:
    try:
        if not isinstance(citation, str):
            return _veto("unparseable")
        return _check_normalized(normalize(citation), db_path)
    except Exception:
        return _veto("internal_error")


_CONNECTORS = frozenset({"of", "the", "and", "de", "la", "del", "ex", "rel.", "for", "v.", "v"})
_PROLOGUE = re.compile(r"(?:^| )(?:In re|Ex parte|Matter of|Estate of|Application of) ")
_MAX_CAPTION_TOKENS = 8

# Wide scan used only by check_text: a citation-shaped span with non-ASCII anywhere in the
# volume, reporter or page. If the reporter is a homoglyph of an in-scope spelling, the span
# is a fabricated Florida cite dressed to evade the ASCII grammar and must not vanish.
_WIDE_START = re.compile(r"(?<![A-Za-z0-9])\d{1,4}(?= )")
_WIDE = re.compile(r"(?<![A-Za-z0-9])(\d{1,4}) ([^ ,;()]+(?: [^ ,;()]+){0,4}?) ([A-Z]?\d{1,6})(?![A-Za-z0-9])")
_IN_SCOPE_SPELLINGS = frozenset(
    v.lower() for v in list(SOUTHERN_EXACT) + [WEEKLY, WEEKLY_SUPP, WEEKLY + " D", WEEKLY + " S"]
)


def _strip_format_chars(s: str) -> str:
    return "".join(ch for ch in s if unicodedata.category(ch) != "Cf")


def _looks_like_in_scope_reporter(r: str) -> bool:
    rl = r.lower()
    if rl in _IN_SCOPE_SPELLINGS:
        return True
    if not _NON_ASCII.search(r):
        return False
    dropped = _NON_ASCII.sub("", r).lower()
    for v in _IN_SCOPE_SPELLINGS:
        if dropped == v:
            return True
        if len(rl) == len(v) and all(a == b or ord(a) > 127 for a, b in zip(rl, v)):
            return True
    return False


def _caption_in_gap(gap: str) -> str:
    """Best-effort caption immediately before a citation: the last 'X v. Y' (or In re ...) run."""
    gap = re.sub(r"[ ,]+$", "", gap)
    k = gap.rfind(" v. ")
    if k < 0:
        k = gap.rfind(" v ")
    if k >= 0:
        defendant = gap[k:]
        tokens = gap[:k].split(" ")
        taken: List[str] = []
        for tok in reversed(tokens):
            if len(taken) >= _MAX_CAPTION_TOKENS:
                break
            if tok[:1].isupper() or tok[:1].isdigit() or tok[:1] == "&" or tok in _CONNECTORS:
                taken.append(tok)
            else:
                break
        return " ".join(reversed(taken)) + defendant
    last = None
    for pm in _PROLOGUE.finditer(gap):
        last = pm
    if last is not None:
        return gap[last.start():].lstrip(" ")
    return ""


def check_text(text: str, db_path=DEFAULT_DB) -> List[Gate1Result]:
    """Check every case citation in free text; results are ordered by position in the text.

    Windows come from this module's own scan, not from eyecite's full_span(), which
    overlaps and runs ahead in prose. eyecite still reads the whole text: any case
    citation it finds with a Florida-looking reporter that the scan did not cover is
    vetoed rather than skipped. Unicode format characters (category Cf, e.g. zero-width
    space) are stripped first, and a citation-shaped span whose reporter is a non-ASCII
    homoglyph of a Florida reporter is vetoed as non_ascii_citation, never dropped.
    """
    try:
        s = normalize(_strip_format_chars(normalize(text)))
        matches = _scan(s)
        out: List[Tuple[int, Gate1Result]] = []
        prev_end = 0
        covered: List[Tuple[int, int]] = []
        for m in matches:
            parsed, problem = _parse_match(s, m)
            end = parsed.tail_end if parsed else m.end()
            gap_start = prev_end if prev_end <= m.start() else m.start()
            caption = _caption_in_gap(s[gap_start:m.start()]) if parsed else ""
            window = (caption + ", " if caption else "") + s[m.start():end]
            out.append((m.start(), check_citation(window, db_path)))
            covered.append((m.start(), end))
            prev_end = max(prev_end, end)
        for cand in _WIDE_START.finditer(s):
            pos = cand.start()
            if any(a <= pos < b for a, b in covered):
                continue
            wm = _WIDE.match(s, pos)
            if wm and _NON_ASCII.search(wm.group(0)) and _looks_like_in_scope_reporter(wm.group(2)):
                out.append((pos, _veto("non_ascii_citation")))
        for c in _eyecite_full_cites(s):
            a, b = c.span()
            if any(x < b and a < y for x, y in covered):
                continue
            kind, _canon, problem = _classify(c.groups.get("reporter") or "", "0")
            if kind != "other" or problem is not None:
                out.append((a, _veto("unparsed_citation")))
        out.sort(key=lambda t: t[0])
        return [r for _pos, r in out]
    except Exception:
        return [_veto("internal_error")]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Gate 1 local Florida citation existence check.")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--citation")
    g.add_argument("--text")
    args = ap.parse_args(argv)
    if args.citation is not None:
        print(json.dumps(check_citation(args.citation, args.db).to_dict(), sort_keys=True))
    else:
        print(json.dumps([r.to_dict() for r in check_text(args.text, args.db)], sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
