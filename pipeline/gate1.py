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
import bisect
import html as _html
import json
import logging
import re
import sqlite3
import sys
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional, Tuple

# eyecite logs a warning for every overlapping-citation case it cannot classify; the gate
# does not use that signal and the CLI must keep stderr quiet.
logging.getLogger("eyecite").setLevel(logging.ERROR)

DEFAULT_DB = Path(__file__).resolve().parent.parent / "kingsfield_florida.db"

PASS = "pass"
VETO = "veto"
FALL_THROUGH = "fall_through"

MAX_CITATION_CHARS = 2000
MAX_TEXT_CHARS = 200_000
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


def _restore_filename_cite(s: str) -> str:
    s = re.sub(r"(?i)\bSo 2d\b", "So. 2d", s)
    s = re.sub(r"(?i)\bSo 3d\b", "So. 3d", s)
    s = re.sub(r"(?i)\bSo (\d)", r"So. \1", s)
    s = re.sub(r"(?i)\bFla (\d{4})\b", r"(Fla. \1)", s)
    return s


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = _WS_RUN.sub(" ", s)
    s = _WS_EDGE.sub("", s)
    return _restore_filename_cite(s)


# ---------------------------------------------------------------------------
# Grammar (ASCII only; every class is explicit so Unicode digits/letters never match)
# ---------------------------------------------------------------------------

_CITE_START = re.compile(r"(?<![A-Za-z0-9])[0-9]{1,4}(?= )")
_GENERIC = re.compile(
    r"(?<![A-Za-z0-9])([0-9]{1,4}) "
    r"([A-Z][A-Za-z0-9.&']*(?: [A-Za-z0-9.&']+){0,4}?) "
    r"([A-Z]?[0-9]{1,6})(?![A-Za-z0-9])"
)
# _PIN and _PAREN are applied with pattern.match(s, pos) (anchored at pos), never to a slice of
# s: slicing the rest of a 200k draft per citation is quadratic.
_PIN = re.compile(r"(?:, ?(?:at )?| at )([0-9]{1,6})(?:[-–—]([0-9]{1,6}))?(?: ?n\.? ?[0-9]{1,3})?")
_PAREN = re.compile(r" ?\(([^()]*)\)")
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
    pos = end
    pins: List[Tuple[int, Optional[int]]] = []
    while True:
        pm = _PIN.match(s, pos)
        if not pm:
            break
        pins.append((int(pm.group(1)), int(pm.group(2)) if pm.group(2) else None))
        pos = pm.end()
    tail_end = pos
    cm = _PAREN.match(s, pos)
    if not cm:
        return pins, tail_end, None, None
    return pins, cm.end(), cm.group(1), (tail_end, cm.end())


def _court_name(content: str) -> str:
    m = _COURT_YEAR.match(content)
    name = m.group(1) if m else content
    return name.rstrip(" ,")


def _court_known(content: Optional[str]) -> bool:
    if content is None or _NON_ASCII.search(content):
        return False
    name = _court_name(content)
    return bool(_FLORIDA_COURT.match(name) or _NON_FLORIDA_COURT.match(name))


_MAX_COURT_SPAN = 400


def _scan(s: str) -> List[re.Match]:
    """All generic reporter-citation matches in s, including overlapping ones.

    A candidate that starts inside the court parenthetical of an earlier match is skipped,
    but only when that parenthetical is a recognized court ("La. App. 1 Cir. 2015" must not
    yield a second citation "1 Cir. 2015"). An unrecognized parenthetical hides nothing.
    """
    out = []
    # Recognized-court parentheticals, kept sorted by start. A recognized court string is short
    # (well under _MAX_COURT_SPAN), so only the few spans just before pos can contain it.
    starts: List[int] = []
    ends: List[int] = []
    for cand in _CITE_START.finditer(s):
        pos = cand.start()
        j = bisect.bisect_right(starts, pos) - 1
        inside = False
        while j >= 0 and starts[j] > pos - _MAX_COURT_SPAN:
            if pos < ends[j]:
                inside = True
                break
            j -= 1
        if inside:
            continue
        m = _GENERIC.match(s, pos)
        if not m:
            continue
        out.append(m)
        _pins, _end, content, span = _tail(s, m.end())
        if span is not None and _court_known(content):
            i = bisect.bisect_left(starts, span[0])
            starts.insert(i, span[0])
            ends.insert(i, span[1])
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
    p = p.rstrip(" ,")
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
    return _pin_problem(p.pins, p.page, first_page, last_page)


def _pin_problem(pins, page: int, first_page: Optional[int], last_page: Optional[int]) -> Optional[str]:
    """Pin cites must fall within the opinion's stored page bounds. Shared by full and short cites."""
    if pins:
        lo = first_page if first_page is not None else page
        if last_page is None:
            return "pin_unverifiable"
        if last_page < lo:
            return "bad_bounds"
        for a, b in pins:
            if b is not None and b < a:
                return "pin_out_of_bounds"
            for x in (a, b):
                if x is not None and not (lo <= x <= last_page):
                    return "pin_out_of_bounds"
    return None


def _check_florida(p: _Parsed, db_path, sink: Optional[list] = None) -> Gate1Result:
    rows = _lookup(db_path, p.reporter, p.volume, p.page, p.section)
    if not rows:
        return _veto("not_found", p)
    caption = _caption_from_prefix(p.prefix)
    first_problem = None
    for row in rows:
        problem = _row_problem(p, caption, row)
        if problem is None:
            if sink is not None:
                sink.append((row, p.page))
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


def _check_normalized(s: str, db_path, sink: Optional[list] = None) -> Gate1Result:
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
        return _check_florida(p, db_path, sink)
    except Exception:
        return _veto("db_unavailable", p)


def _digits(v: Optional[str]) -> Optional[int]:
    return int(v) if v is not None and re.fullmatch(r"[0-9]{1,9}", v) else None


def check_citation(citation: str, db_path=DEFAULT_DB, sink: Optional[list] = None) -> Gate1Result:
    """Check one citation. `sink` (internal): on a pass, receives (stored row, parsed page)."""
    try:
        if not isinstance(citation, str):
            return _veto("unparseable")
        return _check_normalized(normalize(citation), db_path, sink)
    except Exception:
        return _veto("internal_error")


_CONNECTORS = frozenset({"of", "the", "and", "de", "la", "del", "ex", "rel.", "for", "v.", "v", "et", "al.", "al"})
_PROLOGUE = re.compile(r"(?:^| )(?:In re|Ex parte|Matter of|Estate of|Application of) ")
_V_MARK = re.compile(r" v\.? | vs\.? ")
_MAX_CAPTION_TOKENS = 8
_MAX_DEFENDANT_TOKENS = 10
_MAX_PROSE_AFTER_NAME = 30
_TAIL_WINDOW = 600
_SHORT_NAME_TOKENS = 5
# Corporate / designation suffixes that may follow a comma inside one party name.
_NAME_SUFFIX = frozenset({"inc", "llc", "ltd", "co", "corp", "pa", "na", "lp", "llp", "plc", "pllc", "pc",
                          "jr", "sr", "ii", "iii", "iv", "et", "al", "etc"})
_TRAILING_CONNECTORS = frozenset({"of", "the", "and", "de", "la", "del", "ex", "for", "v.", "v", "rel."})
_ID_TOKENS = frozenset({"Id.", "id.", "Id", "Ibid.", "ibid.", "Ids."})
_NUM_DOT = re.compile(r"[0-9]+[.)]")
_LONG_WORD_DOT = re.compile(r"[A-Za-z']{6,}\.")
# Sentence openers that are not part of a party name ("In Smith v. Jones", "However, Smith, ...").
_LEAD_WORDS = frozenset({
    "in", "under", "per", "as", "and", "also", "then", "thus", "here", "however", "moreover", "further",
    "furthermore", "accordingly", "finally", "similarly", "likewise", "indeed", "yet", "but", "because",
    "since", "while", "although", "where", "when", "instead", "again", "notably", "specifically",
    "importantly", "first", "second", "third", "see", "cf", "accord", "compare", "contra", "e.g", "eg",
    "also", "cite", "citing", "quoting",
})

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


def _tail_window(text: str) -> str:
    """The last _TAIL_WINDOW characters of text, without a possibly-cut first token."""
    if len(text) <= _TAIL_WINDOW:
        return text
    cut = text[-_TAIL_WINDOW:]
    sp = cut.find(" ")
    return cut[sp + 1:] if sp >= 0 else cut


def _is_suffix(tok: str) -> bool:
    return tok.lower().replace(".", "").rstrip(",") in _NAME_SUFFIX


def _hard_stop(tok: str) -> bool:
    """A token that ends the name run in either direction: the previous sentence, a citation
    parenthetical, a list number or an Id."""
    return ("(" in tok or ")" in tok or tok[-1:] in (";", ":", "!", "?") or tok in _ID_TOKENS
            or _NUM_DOT.fullmatch(tok) is not None)


def _sentence_end(tok: str) -> bool:
    """A token that ends a sentence rather than an abbreviation: 'held.', 'Florida.'."""
    if _hard_stop(tok):
        return True
    if not tok.endswith("."):
        return False
    if tok[:1].isdigit():
        return True  # '90.803.', '2012).': a number that closes a sentence or a citation
    return (tok[:1].islower() and tok.lower() not in _CONNECTORS) or _LONG_WORD_DOT.fullmatch(tok) is not None


def _name_like(tok: str) -> bool:
    return tok[:1].isupper() or tok[:1].isdigit() or tok == "&" or tok.lower() in _CONNECTORS


def _strip_lead(name: str) -> str:
    """Drop leading signals and sentence openers ('See', 'In', 'However') from a plaintiff run."""
    for _ in range(6):
        n = _SIGNAL.sub("", name, count=1)
        first, _sp, rest = n.partition(" ")
        if rest and first.rstrip(",.").lower() in _LEAD_WORDS and not (first == "In" and rest.startswith("re ")):
            n = rest
        elif rest and first[:1].islower() and first in _CONNECTORS:
            n = rest  # a lower-case connector cannot open a party name ('of Smith v. Jones')
        if n == name:
            break
        name = n
    if " " not in name and name.rstrip(",.").lower() in _LEAD_WORDS:
        return ""  # a bare signal ('See', 'Cf.', 'E.g.') is not a name
    return name


def _names_before(tokens: List[str], limit: int) -> List[str]:
    """The run of name-like tokens ending at the end of `tokens` (read backwards, at most `limit`).

    A token ending in a comma belongs to the name only when a corporate suffix follows
    ('Walmart Stores, Inc.'); otherwise the comma ends the name and the token is left out.
    """
    taken: List[str] = []
    for tok in reversed(tokens):
        if len(taken) >= limit or tok == "":
            break
        if not _name_like(tok) or _sentence_end(tok):
            break
        if tok[-1:] == "," and not (taken and _is_suffix(taken[-1])):
            break
        taken.append(tok)
    taken.reverse()
    return taken


def _name_after(tokens: List[str]) -> Tuple[List[str], bool]:
    """Read the name run that starts `tokens` (a defendant). Returns (name tokens, attached).

    attached is False when a sentence ends between the name and the end of the gap (the name
    belongs to an earlier citation or to prose) or when the prose after the name is too long.
    """
    name: List[str] = []
    i = 0
    while i < len(tokens) and len(name) < _MAX_DEFENDANT_TOKENS:
        tok = tokens[i]
        if tok == "" or not _name_like(tok) or _hard_stop(tok):
            break
        name.append(tok)
        i += 1
        if tok[-1:] == "," and not (i < len(tokens) and _is_suffix(tokens[i])):
            break
    rest = tokens[i:]
    while name and name[-1].lower() in _TRAILING_CONNECTORS:
        name.pop()  # 'Smith v. Jones the court held': the 'the' is prose
    if len(rest) > _MAX_PROSE_AFTER_NAME or any(_sentence_end(t) for t in rest):
        return name, False
    return name, True


def _caption_in_gap(gap: str) -> Tuple[str, str]:
    """The caption immediately before a citation, from the text since the previous citation.

    Returns (caption, status). status is
      'ok'            caption extracted ('Plaintiff v. Defendant' or 'In re X')
      'none'          no case name is attached to this citation (no marker in the gap, or a
                      sentence ends between the last marker and the citation)
      'unverifiable'  a case-name marker is attached to the citation but no caption could be
                      read from it (lower-case or garbled name). The caller vetoes a pass.
    The gap is first stripped of markdown, HTML, quotes and brackets by _clean_draft.
    """
    g = _tail_window(gap).rstrip(" ,")
    last = None
    for mm in _V_MARK.finditer(g):
        last = mm
    if last is not None:
        name, attached = _name_after(g[last.end():].split(" "))
        if not attached:
            return "", "none"
        plaintiff = _strip_lead(" ".join(_names_before(g[:last.start()].split(" "), _MAX_CAPTION_TOKENS)))
        if not plaintiff or not name:
            return "", "unverifiable"
        return plaintiff + " v. " + " ".join(name).rstrip(","), "ok"
    lastp = None
    for pm in _PROLOGUE.finditer(g):
        lastp = pm
    if lastp is not None:
        name, attached = _name_after(g[lastp.end():].split(" "))
        if not attached:
            return "", "none"
        if not name:
            return "", "unverifiable"
        return lastp.group(0).strip() + " " + " ".join(name).rstrip(","), "ok"
    return "", "none"


def _short_name_before(s: str, pos: int) -> Tuple[Optional[str], str]:
    """The name written in front of a short-form citation that starts at pos.

    Returns (name, status): ('Smith', 'ok'), ('Smith v. Jones', 'ok'), (None, 'none') when the
    short cite carries no name, or (None, 'unverifiable') for an attached but unreadable name.
    """
    g = _tail_window(s[max(0, pos - _TAIL_WINDOW - 50):pos]).rstrip(" ,")
    cap, status = _caption_in_gap(g)
    if status == "ok":
        return cap, "ok"
    if status == "unverifiable":
        return None, "unverifiable"
    name = _strip_lead(" ".join(_names_before(g.split(" "), _SHORT_NAME_TOKENS)))
    name = name.rstrip(",")
    return (name, "ok") if name else (None, "none")


# ---------------------------------------------------------------------------
# Draft cleaning. A draft is model output: markdown, HTML, OCR damage and deliberate dressing
# all reach the gate. Everything below is linear; nothing backtracks over the whole draft.
# ---------------------------------------------------------------------------

_BLOCK_TAGS = frozenset({"p", "br", "div", "li", "ul", "ol", "tr", "td", "th", "table", "tbody", "thead", "hr",
                         "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "section", "article", "dd", "dt"})
_TAG = re.compile(r"<(/?)([A-Za-z][A-Za-z0-9]{0,15})((?:[ \t\r\n/][^<>]{0,2000})?)>")
_MD_ESCAPE = re.compile(r"\\([!-/:-@\[-`{-~])")
_MD_FOOTNOTE = re.compile(r"\[\^?[0-9]{1,3}\]")
# A hyphen (ASCII, U+2010 or U+2011) at a line end joins the pieces, also after a period
# ('So.-\n3d'); U+00AD soft hyphens are format characters and are stripped before this runs.
_HYPHEN_BREAK = re.compile("([A-Za-z0-9.])[-‐‑][ \\t]*\\r?\\n[ \\t]*([A-Za-z0-9])")
# '*' is emphasis, except the star page of a pin cite ("at *4"), which must stay visible so the
# pin parser rejects it rather than reading it as page 4.
_STARS = re.compile(r"\*{2,}|(?<!at )\*|\*(?![0-9])")
# '_' runs of one or two are emphasis when they hug a word; a run standing alone between spaces
# ("_ So. 3d _") or a run of three or more is a fill-in placeholder and stays.
_UNDERSCORE_EMPHASIS = re.compile(r"(?<![A-Za-z0-9_])_{1,2}(?=[^\s_])|(?<=[^\s_])_{1,2}(?![A-Za-z0-9_])")
_DQUOTES = re.compile("[\"\u201c\u201d\u201e\u00ab\u00bb]")
_EDGE_SQUOTES = re.compile("(?<![A-Za-z0-9])['\u2018\u2019]|['\u2018\u2019](?![A-Za-z0-9])")
_BLOCKQUOTE = re.compile(r"(?m)^[ \t]*>[> \t]*")
_HEADING = re.compile(r"(?m)^[ \t]*#{1,6}[ \t]+")


# The cleaner removes markup SYNTAX but never discards text content. Content that the renderer
# can show (HTML attribute values such as title/alt/aria-label, comment bodies, markdown link and
# image titles) is collected into `extras` and scanned as its own segments after the main text,
# so it is extracted, checked and covered by the residue detector. The main text still has the
# markup removed in place (that is what keeps 'So<!-- -->. 3d' and '<b>So.</b>' joined).
_HTML_TAGS = frozenset("""a abbr acronym address article aside audio b bdi bdo big blockquote body br button canvas caption
center cite code col colgroup data datalist dd del details dfn dialog dir div dl dt em embed fieldset figcaption figure
font footer form h1 h2 h3 h4 h5 h6 head header hgroup hr html i iframe img input ins kbd label legend li link main map
mark menu meta meter nav noscript object ol optgroup option output p param picture pre progress q rp rt ruby s samp
script section select small source span strike strong style sub summary sup svg table tbody td template textarea tfoot
th thead time title tr track tt u ul var video wbr""".split())
_ATTR = re.compile(r"([A-Za-z_:][-A-Za-z0-9_:.]{0,40})[ \t\r\n]*=[ \t\r\n]*(?:\"([^\"]*)\"|'([^']*)'|([^\s\"'<>=`]+))")
_NON_TEXT_ATTRS = frozenset({"href", "src", "srcset", "class", "id", "style", "rel", "target", "xmlns", "width",
                             "height", "lang", "dir", "type", "name", "for", "colspan", "rowspan"})
# [text](dest "title"), ![alt](dest 'title'), [text](<dest with spaces>): text (alt) stays in place,
# the title and a bracketed destination go to extras. A parenthesis may appear inside the quoted title.
_MD_LINK = re.compile(
    r"!?\[([^\[\]]{0,300})\]\([ \t]*(<[^<>\n]{0,500}>|[^()\s\"'<>]{0,500})"
    r"(?:[ \t]+(?:\"([^\"]{0,500})\"|'([^']{0,500})'))?[ \t]*\)"
)
_EXTRA_SEP = " ; "
_MAX_EXTRA_ROUNDS = 3


def _strip_comments(t: str, extras: List[str]) -> str:
    if "<!--" not in t:
        return t
    out: List[str] = []
    i = 0
    while True:
        j = t.find("<!--", i)
        if j < 0:
            out.append(t[i:])
            break
        out.append(t[i:j])
        k = t.find("-->", j + 4)
        if k < 0:
            out.append(t[j + 4:])  # unterminated: drop the marker, keep (and check) the text
            break
        extras.append(t[j + 4:k])  # the comment body can be rendered (code fences, entity-encoded)
        i = k + 3
    return "".join(out)


def _strip_markup(t: str, extras: List[str]) -> str:
    def tag_sub(m: re.Match) -> str:
        name = m.group(2).lower()
        attrs = m.group(3)
        if name not in _HTML_TAGS:
            # '<Doe v. Roe, 999 So. 3d 999>' is not an HTML element (a markdown '<destination>' or
            # plain text): only the angle brackets go, the words stay in place.
            return " " + m.group(2) + attrs + " "
        if attrs:
            for am in _ATTR.finditer(attrs):
                if am.group(1).lower() in _NON_TEXT_ATTRS:
                    continue
                value = am.group(2) if am.group(2) is not None else (am.group(3) if am.group(3) is not None else am.group(4))
                if value and value.strip():
                    extras.append(value)
            leftover = _ATTR.sub(" ", attrs).replace("/", " ").strip()
            if leftover:
                extras.append(leftover)  # malformed attributes ('title=Doe v. Roe, ...'): keep, do not drop
        return " " if name in _BLOCK_TAGS else ""

    def link_sub(m: re.Match) -> str:
        dest = m.group(2)
        if dest.startswith("<"):
            extras.append(dest[1:-1])
        for title in (m.group(3), m.group(4)):
            if title and title.strip():
                extras.append(title)
        return m.group(1)

    t = _TAG.sub(tag_sub, _strip_comments(t, extras))
    return _MD_LINK.sub(link_sub, t)


def _split_markup(text: str) -> Tuple[str, List[str]]:
    """(main text with markup syntax removed and entities decoded, raw extra text segments)."""
    extras: List[str] = []
    t = _strip_markup(text, extras)
    for _ in range(3):
        u = _html.unescape(t)
        if u == t:
            break
        t = u
    return _strip_markup(t, extras), extras


def _hyphen_sub(m: re.Match) -> str:
    a, b = m.group(1), m.group(2)
    return a + ("-" if a.isdigit() and b.isdigit() else "") + b


def _clean_draft(text: str) -> str:
    """Normalize a draft for citation extraction.

    Removes HTML comments, tags and entities (to a fixpoint, so '&amp;nbsp;' goes too), Unicode
    format and control characters, markdown escapes, links, emphasis, quotes and brackets, and
    joins hyphenated line breaks. The residue detector in check_text is the backstop for
    anything this leaves behind.
    """
    t, extras = _split_markup(text)
    # Text the renderer can show but the main text drops (attribute values, comment bodies,
    # link titles) is scanned as separate segments; each may itself hold entities or markup.
    segments: List[str] = []
    work = extras
    for _ in range(_MAX_EXTRA_ROUNDS):
        nxt: List[str] = []
        for e in work:
            main, more = _split_markup(e)
            segments.append(main)
            nxt.extend(more)
        work = nxt
        if not work:
            break
    segments.extend(work)  # anything deeper than the round limit is kept raw, never dropped
    if segments:
        t = t + _EXTRA_SEP + _EXTRA_SEP.join(segments)
    t = unicodedata.normalize("NFKC", t)
    t = "".join(
        ch for ch in t
        if (cat := unicodedata.category(ch)) != "Cf" and not (cat == "Cc" and ch not in "\t\n\r\f\v")
    )
    t = _MD_ESCAPE.sub(r"\1", t).replace("\\", "")  # escapes, then any stray backslash
    t = _BLOCKQUOTE.sub("", t)
    t = _HEADING.sub("", t)
    t = _HYPHEN_BREAK.sub(_hyphen_sub, t)
    t = _MD_FOOTNOTE.sub(" ", t)
    t = _STARS.sub("", t)
    t = _UNDERSCORE_EMPHASIS.sub("", t)
    t = t.replace("`", "").replace("~", "")
    t = _DQUOTES.sub("", t)
    t = _EDGE_SQUOTES.sub("", t)
    t = t.replace("[", "").replace("]", "")
    t = t.replace("|", " ")
    return normalize(t)


# ---------------------------------------------------------------------------
# Residue detector. Anything that looks like a Florida reporter next to a number or a fill-in
# blank, and that is not inside an emitted result, is a citation the extractors missed.
# ---------------------------------------------------------------------------

# Separators between the pieces of a reporter tolerate up to three stray non-alphanumeric
# characters ('So.\ 3d', 'So.. 3d', 'So.* 3d'), so junk inside the reporter cannot hide it.
_SEP = r"[^A-Za-z0-9]{0,3}"
_RES_SERIES = re.compile(
    r"(?<![A-Za-z])(?:S[o0]|Sou|South|Southern)" + _SEP + r"(?:Rep(?:orter|\.)?" + _SEP + r")?[234]" + _SEP
    + r"(?:d|nd|rd|th)(?![A-Za-z])",
    re.I,
)
_RES_BARE_SO = re.compile(r"(?<![A-Za-z])S[oO0]\.(?![A-Za-z])")
_RES_WEEKLY = re.compile(
    r"(?<![A-Za-z])(?:F[lI1]a" + _SEP + r"L" + _SEP + r"W(?:eekly|kly|k)?|FLW)(?![A-Za-z])(?![ ]?Fed)"
    r"(?:" + _SEP + r"Supp\.?)?"
)
_RES_ID = re.compile(r"(?<![A-Za-z])(?:Id|id|Ibid)\.?,?[ ]at[ ]\*?[0-9]")
# A number-like token: digits and fill-in underscores, possibly with OCR confusions (O/o for 0,
# l/I/| for 1), or a run of two or more OCR confusables on its own ("lOO").
_NUMISH = r"(?:[0-9OolI|_]{0,12}[0-9_][0-9OolI|_]{0,12}|(?<![A-Za-z])[OolI|]{2,12}[0-9OolI|]{0,12})"
_NUMISH_AFTER = re.compile(r"[ ,]{0,2}(?:[A-Z][ ]?)?" + _NUMISH)
_NUMISH_BEFORE = re.compile(_NUMISH + r"[ ,]{0,2}$")


def _numish_before(s: str, a: int) -> Optional[int]:
    """Start of a volume-like token (digits, blanks, OCR digits) ending just before a, or None."""
    w0 = max(0, a - 14)
    m = _NUMISH_BEFORE.search(s[w0:a])
    return w0 + m.start() if m else None


def _numish_after(s: str, b: int) -> Optional[int]:
    """End of a page-like token starting just after b, or None."""
    m = _NUMISH_AFTER.match(s, b)
    return m.end() if m else None


def _residue_hits(s: str) -> List[Tuple[int, int, int, int]]:
    """(token start, token end, span start, span end) for every suspicious Florida-reporter token."""
    hits = []
    for rx, need_both in ((_RES_SERIES, False), (_RES_WEEKLY, False), (_RES_BARE_SO, True)):
        for m in rx.finditer(s):
            a, b = m.start(), m.end()
            bs = _numish_before(s, a)
            ae = _numish_after(s, b)
            if (bs is None or ae is None) if need_both else (bs is None and ae is None):
                continue
            hits.append((a, b, bs if bs is not None else a, ae if ae is not None else b))
    return hits


@dataclass(frozen=True)
class TextResult(Gate1Result):
    """One case-citation occurrence in a draft (check_text).

    kind          full | short | id | supra | unparsed
    text          the citation as it appears in the cleaned draft: text == cleaned[start:end]
    start, end    offsets (Python code points) into the CLEANED draft, i.e. the draft after HTML /
                  markdown / entity / format-character removal and whitespace collapsing. They are
                  not offsets into the original draft and must not be used to slice it.
    full_citation the full-citation window this occurrence resolves to (the checked window for a
                  full cite, the antecedent's window for short / Id. / supra). None only for
                  vetoes without a known antecedent and for the non_case_antecedent fall-through.
    """

    kind: str = "unparsed"
    text: str = ""
    full_citation: Optional[str] = None
    start: int = 0
    end: int = 0


NON_CASE_ANTECEDENT = "non_case_antecedent"
_SHORT_KINDS = ("short", "id", "supra")
# After an Id./supra/short-form token, anything that looks like the start of a pin cite but
# does not parse as one (at *4, at para. 5, at 12 & n.3 is fine, at (b)) is vetoed, not ignored.
_AT_REPORTER = re.compile(r" at$")
_PIN_HINT = re.compile(r"(?:,? ?at\b|, ?([0-9*\u00b6\u00a7]))")


@dataclass
class _Entry:
    kind: str
    text: str
    start: int
    end: int
    result: Gate1Result
    window: Optional[str] = None             # full-citation window (full cites and eyecite-only full cites)
    core: Optional[Tuple[int, int]] = None   # scan span of the core citation, for eyecite mapping
    vol: Optional[int] = None
    pg: Optional[int] = None
    row: Optional[tuple] = None              # stored record, only when the result is a pass
    row_page: Optional[int] = None
    caption: str = ""                        # caption read from the draft in front of a full cite


def _tr(e: _Entry, full_citation: Optional[str]) -> TextResult:
    r = e.result
    verdict, reason = r.verdict, r.reason
    # Contract: every pass and every fall_through (bar non_case_antecedent) names a full citation.
    if verdict == PASS and (full_citation is None or r.cluster_id is None):
        verdict, reason = VETO, "internal_error"
    elif verdict == FALL_THROUGH and full_citation is None and reason != NON_CASE_ANTECEDENT:
        verdict, reason = VETO, "internal_error"
    return TextResult(verdict, reason, r.reporter, r.volume, r.page, r.cluster_id,
                      e.kind, e.text, full_citation, e.start, e.end)


def _text_veto(reason: str) -> TextResult:
    return TextResult(VETO, reason, kind="unparsed")


_SOUTHERN_LEAD = frozenset({"so", "sou", "south", "southern"})


def _southern_lead(raw_reporter: str) -> bool:
    """True if the reporter's leading token is loosely Southern ('So. Fla. counties since', 'So. Cal.',
    'South Carolina', OCR forms like 'S0.'). Draft mode only: such a would-be fall_through is
    prose or an unidentified Southern citation, and Southern Reporter falls through only on a
    positively identified non-Florida court."""
    first = raw_reporter.split(" ", 1)[0]
    return any(_loose(f) in _SOUTHERN_LEAD for f in (first, first.replace("0", "o")))


def _merged_spans(results) -> Tuple[List[int], List[int]]:
    """Disjoint sorted intervals covering every emitted result."""
    return _merge_intervals((r.start, r.end) for r in results)


def _merge_intervals(intervals) -> Tuple[List[int], List[int]]:
    ivs = sorted((a, b) for a, b in intervals if b > a)
    starts: List[int] = []
    ends: List[int] = []
    for a, b in ivs:
        if ends and a <= ends[-1]:
            ends[-1] = max(ends[-1], b)
        else:
            starts.append(a)
            ends.append(b)
    return starts, ends


def _overlaps(starts: List[int], ends: List[int], a: int, b: int) -> bool:
    i = bisect.bisect_right(starts, a) - 1
    if i >= 0 and ends[i] > a:
        return True
    return i + 1 < len(starts) and starts[i + 1] < b


def _residue_results(s: str, results) -> List[TextResult]:
    """Backstop: veto every Florida-reporter token (or Id. pin cite) that no emitted result covers.

    The scan, eyecite and the homoglyph scan can all miss a citation that was dressed (glued
    digits, OCR digits, fill-in blanks, stray markup). A Florida reporter next to a number or a
    blank that is not inside any result's span is such a citation: it becomes an
    unparsed_citation veto, never a silent drop.
    """
    starts, ends = _merged_spans(results)
    hits = sorted(_residue_hits(s), key=lambda h: (h[0], -h[1]))  # longest token first at a position
    out: List[TextResult] = []
    last_end = 0
    for a, b, sa, ea in hits:
        if a < last_end or _overlaps(starts, ends, a, b):
            continue
        sa = max(sa, last_end)
        if sa < a and _overlaps(starts, ends, sa, a):
            sa = a
        if ea > b and _overlaps(starts, ends, b, ea):
            ea = b
        out.append(TextResult(VETO, "unparsed_citation", kind="unparsed", text=s[sa:ea],
                              full_citation=None, start=sa, end=ea))
        last_end = ea
    rstarts = [r.start for r in out]  # disjoint and ascending by construction
    rends = [r.end for r in out]
    for m in _RES_ID.finditer(s):
        a, b = m.start(), m.end()
        if _overlaps(starts, ends, a, b) or _overlaps(rstarts, rends, a, b):
            continue
        out.append(TextResult(VETO, "unresolved_short_cite", kind="id", text=s[a:b],
                              full_citation=None, start=a, end=b))
    return out


def _resolve_id_any_pin(id_citation, last_resolution, resolutions):
    """eyecite's Id. resolver minus its 'pin cite more than 150 pages away' heuristic.

    That heuristic drops the Id. as unresolved, which also breaks every later Id. in the
    chain. Here the Id. resolves to the previous citation and this module's own pin rules
    (page bounds from the database) decide, so the veto carries the real pin reason.
    """
    from eyecite.models import FullCaseCitation

    if not last_resolution:
        return None
    full = resolutions[last_resolution][0]
    if type(full) is FullCaseCitation and full.groups.get("page") is None:
        return None
    return last_resolution


def _short_pin(s: str, c, kind: str, eyecite_pin: Optional[str]):
    """Return (pins, end, problem) for a short-form / Id. / supra citation.

    Pins are parsed with this module's _PIN grammar, the same one full cites use. eyecite only
    locates the token; it is not trusted for the pin itself.
    """
    ts, te = c.token.start, c.token.end
    if kind == "short":
        k = s[ts:te].rfind(" at ")
        if k < 0:
            return [], te, "pin_unparseable"
        pos = ts + k
    else:
        pos = te - 1 if s[te - 1:te] == "," else te
    pins: List[Tuple[int, Optional[int]]] = []
    while True:
        pm = _PIN.match(s, pos)
        if not pm:
            break
        if _GENERIC.match(s, pm.start(1)):
            break  # ", 5 F.3d 5": the number opens the next citation, it is not another pin
        pins.append((int(pm.group(1)), int(pm.group(2)) if pm.group(2) else None))
        pos = pm.end()
    end = max(te, pos)
    if kind == "short" and not pins:
        return pins, end, "pin_unparseable"
    if (not pins and eyecite_pin) or _looks_like_pin(s, pos):
        return pins, end, "pin_unparseable"
    return pins, end, None


def _looks_like_pin(s: str, pos: int) -> bool:
    """True if s[pos:] starts like a pin cite (the _PIN grammar did not consume it)."""
    hm = _PIN_HINT.match(s, pos)
    if hm is None:
        return False
    # ", 5 F.3d 5": a number that opens the next citation is not a pin.
    return not (hm.group(1) is not None and _GENERIC.match(s, hm.start(1)))


def _unresolved_reason(c, kind: str, preceding_fulls) -> str:
    """'ambiguous_short_cite' when eyecite had several candidate antecedents, else 'unresolved_short_cite'."""
    from eyecite.models import FullCaseCitation
    from eyecite.utils import strip_punct

    cands = set()
    if kind == "short":
        for f in preceding_fulls:
            if (isinstance(f, FullCaseCitation) and f.corrected_reporter() == c.corrected_reporter()
                    and f.groups.get("volume") == c.groups.get("volume")):
                cands.add(hash(f))
    elif kind == "supra":
        guess = strip_punct(c.metadata.antecedent_guess or "")
        for f in preceding_fulls:
            if isinstance(f, FullCaseCitation) and guess and (
                (f.metadata.defendant and guess in f.metadata.defendant)
                or (f.metadata.plaintiff and guess in f.metadata.plaintiff)
            ):
                cands.add(hash(f))
    return "ambiguous_short_cite" if len(cands) > 1 else "unresolved_short_cite"


def _split_parties(caption: str) -> List[str]:
    return [p for p in re.split(r"\s+(?:v|vs)\.?\s+", caption, flags=re.I) if p.strip()]


def _tokens_of(text: str, given: bool) -> frozenset:
    t = _TYPO_PUNCT.sub(" ", _fold(text))
    if not given:
        t = _NON_ASCII.sub(" ", t)
    return frozenset(_caption_tokens(t).split())


def _short_name_matches(name: str, reference: str) -> Tuple[bool, str]:
    """Is the name written before a short cite a party of the antecedent (or its whole caption)?

    Whole captions use the full-citation rules (caption_matches). A party name must be whole-word
    contained in one party of the reference ('Smith' in 'Smith v. State'; 'Smithson' is not).
    """
    ok, why = caption_matches(name, reference)
    if ok:
        return True, "ok"
    if why in ("caption_non_ascii", "caption_unverifiable"):
        return False, why
    if _NON_ASCII.search(_TYPO_PUNCT.sub(" ", _fold(name))):
        return False, "caption_non_ascii"
    want = _tokens_of(name, True)
    if want:
        for party in _split_parties(reference):
            if want <= _tokens_of(party, False):
                return True, "ok"
    return False, "caption_mismatch"


def _short_name_problem(s: str, ts: int, entry: "_Entry") -> Optional[str]:
    name, status = _short_name_before(s, ts)
    if status == "unverifiable":
        return "caption_unparseable"
    if name is None:
        return None
    if entry.result.verdict == PASS and entry.row is not None:
        reference: Optional[str] = entry.row[1]
    else:
        reference = entry.caption or None
    if not reference or normalize(reference) == "":
        return "caption_unverifiable"
    return None if _short_name_matches(name, reference)[0] else "caption_mismatch"


def _short_result(s: str, c, kind: str, fulls_of, fulls_all, res_of, full_map, idx_of) -> TextResult:
    """fulls_of: resource -> (ascending draft indexes, full citations resolving to it);
    fulls_all: the same for every full citation in the draft."""
    from eyecite.models import FullCaseCitation

    ts = c.token.start
    pins, end, pin_problem = _short_pin(s, c, kind, c.metadata.pin_cite)
    base = _Entry(kind, s[ts:end], ts, end, _veto("unresolved_short_cite"))

    def veto(reason, r=None, window=None):
        base.result = (_veto(reason) if r is None else
                       Gate1Result(VETO, reason, r.reporter, r.volume, r.page, r.cluster_id))
        return _tr(base, window)

    my_idx = idx_of[id(c)]
    resource = res_of.get(id(c))
    if resource is None:
        if kind == "id":
            return veto("unresolved_short_cite")
        # Only the nearest preceding full citations decide ambiguous vs unresolved (both veto).
        k = bisect.bisect_left(fulls_all[0], my_idx)
        return veto(_unresolved_reason(c, kind, fulls_all[1][max(0, k - 200):k]))
    idxs, cites = fulls_of[resource]
    k = bisect.bisect_left(idxs, my_idx)
    if k == 0:
        return veto("unresolved_short_cite")
    ant = cites[k - 1]
    if not isinstance(ant, FullCaseCitation):
        # Id. after a statute, regulation or journal article: not a case, nothing to check here.
        base.result = Gate1Result(FALL_THROUGH, NON_CASE_ANTECEDENT)
        return _tr(base, None)
    entry = full_map.get(id(ant))
    if entry is None:
        return veto("ambiguous_short_cite")
    ar = entry.result
    if ar.verdict == VETO:
        return veto("antecedent_vetoed", ar, entry.window)
    if kind in ("short", "supra"):
        # The name written in front of the short cite must be a party of the antecedent: the
        # stored case_name for a pass, the caption read from the draft for a fall_through.
        name_problem = _short_name_problem(s, ts, entry)
        if name_problem:
            return veto(name_problem, ar, entry.window)
    if ar.verdict == FALL_THROUGH:
        base.result = Gate1Result(FALL_THROUGH, ar.reason, ar.reporter, ar.volume, ar.page)
        return _tr(base, entry.window)
    # Antecedent passed: the short cite's own pin is checked against the same stored record.
    if pin_problem:
        return veto(pin_problem, ar, entry.window)
    if pins:
        if entry.row is None:
            return veto("pin_unverifiable", ar, entry.window)
        problem = _pin_problem(pins, entry.row_page, entry.row[2], entry.row[3])
        if problem:
            return veto(problem, ar, entry.window)
    base.result = Gate1Result(PASS, "verified", ar.reporter, ar.volume, ar.page, ar.cluster_id)
    return _tr(base, entry.window)


def check_text(text: str, db_path=DEFAULT_DB) -> List[TextResult]:
    """Check every case citation in a draft; one result per occurrence, ordered by position.

    Full citations: windows come from this module's own scan, not from eyecite's full_span(),
    which overlaps and runs ahead in prose, and each window goes through check_citation.
    eyecite still reads the whole text: a case citation it finds that the scan did not cover is
    vetoed when its reporter looks Florida, and otherwise falls through to CourtListener
    rather than being skipped. Unicode format characters (category Cf, e.g. zero-width space)
    are stripped first, and a citation-shaped span whose reporter is a non-ASCII homoglyph of a
    Florida reporter is vetoed as non_ascii_citation, never dropped.

    Short-form citations, Id. and supra are resolved with eyecite's resolve_citations against
    the full citations in the same draft and inherit the antecedent's verdict; a pass also
    needs the short cite's own pin to fall inside the same record's page bounds. An
    unresolved or ambiguous one is vetoed, never passed. Id. after a non-case citation falls
    through as non_case_antecedent.
    """
    try:
        if not isinstance(text, str):
            return [_text_veto("unparseable")]
        if len(text) > MAX_TEXT_CHARS:
            return [_text_veto("too_long")]
        from eyecite import get_citations
        from eyecite.models import FullCaseCitation, FullCitation, IdCitation, ShortCaseCitation, SupraCitation
        from eyecite.resolve import resolve_citations

        s = _clean_draft(text)
        if s == "":
            return []  # nothing to check: a chat answer without citations is never vetoed
        # Keep eyecite's own order out of it: it sorts by full_span(), which can place an Id.
        # after a later citation. Resolution must only ever look backwards in the draft.
        ey_sorted = [c for _i, c in sorted(enumerate(get_citations(s)), key=lambda t: (t[1].span()[0], t[0]))]
        idx_of = {id(c): i for i, c in enumerate(ey_sorted)}
        short_idx = _merge_intervals((c.token.start, c.token.end) for c in ey_sorted if isinstance(c, ShortCaseCitation))

        matches = _scan(s)
        entries: List[_Entry] = []
        scan_entries: List[_Entry] = []
        prev_end = 0
        covered: List[Tuple[int, int]] = []
        for m in matches:
            if _AT_REPORTER.search(m.group(2)):
                # The generic scan reads "123 So. 3d at 462" as a citation to a reporter named
                # "So. 3d at". It is a short-form cite: eyecite's short cite (below) owns it, and
                # one eyecite did not recognise cannot be resolved, so it is vetoed.
                if not _overlaps(short_idx[0], short_idx[1], m.start(), m.end()):
                    entries.append(_Entry("short", s[m.start():m.end()], m.start(), m.end(),
                                          _veto("unresolved_short_cite")))
                covered.append((m.start(), m.end()))
                continue
            parsed, problem = _parse_match(s, m)
            end = parsed.tail_end if parsed else m.end()
            gap_start = prev_end if prev_end <= m.start() else m.start()
            caption, cstat = (_caption_in_gap(s[max(gap_start, m.start() - _TAIL_WINDOW - 50):m.start()])
                              if parsed else ("", "none"))
            window = (caption + ", " if caption else "") + s[m.start():end]
            sink: list = []
            result = check_citation(window, db_path, sink)
            if result.verdict == PASS and cstat == "unverifiable":
                # A case name is attached to this citation but could not be read and compared.
                result = Gate1Result(VETO, "caption_unparseable", result.reporter, result.volume, result.page,
                                     result.cluster_id)
            ekind = "full"
            if result.verdict == FALL_THROUGH and result.reason == "not_florida_key" and _southern_lead(m.group(2)):
                # 'served 12 So. Fla. counties since 2010': reads as a citation to a reporter named
                # "So. Fla. counties since". A loosely-Southern reporter with no positively identified
                # non-Florida court never falls through.
                result = Gate1Result(VETO, "unparsed_citation", result.reporter, result.volume, result.page)
                ekind = "unparsed"
            letter = m.group(3)[:1].isalpha()
            e = _Entry(ekind, s[m.start():end], m.start(), end, result, window=window,
                       core=(m.start(), m.end()), vol=int(m.group(1)),
                       pg=int(m.group(3)[1:] if letter else m.group(3)), caption=caption)
            if result.verdict == PASS and sink:
                e.row, e.row_page = sink[0]
            entries.append(e)
            scan_entries.append(e)
            covered.append((m.start(), end))
            prev_end = max(prev_end, end)
        cov = _merge_intervals(covered)
        for cand in _WIDE_START.finditer(s):
            pos = cand.start()
            if _overlaps(cov[0], cov[1], pos, pos + 1):
                continue
            wm = _WIDE.match(s, pos)
            if wm and _NON_ASCII.search(wm.group(0)) and _looks_like_in_scope_reporter(_AT_REPORTER.sub("", wm.group(2))):
                entries.append(_Entry("unparsed", wm.group(0), pos, wm.end(), _veto("non_ascii_citation")))

        full_map = {}
        scan_starts = [e.core[0] for e in scan_entries]
        for c in ey_sorted:
            if not isinstance(c, FullCaseCitation):
                continue
            a, b = c.span()
            lo = bisect.bisect_left(scan_starts, a - _TAIL_WINDOW * 4)
            hi = bisect.bisect_left(scan_starts, b)
            overl = [e for e in scan_entries[lo:hi] if e.core[0] < b and a < e.core[1]]
            g = c.groups
            if (len(overl) == 1 and overl[0].vol == _digits(g.get("volume"))
                    and overl[0].pg == _digits(g.get("page"))):
                full_map[id(c)] = overl[0]
                continue
            full_map[id(c)] = None
            if overl or _overlaps(cov[0], cov[1], a, b):
                continue
            kind, _canon, problem = _classify(g.get("reporter") or "", "0")
            cite_text = s[a:b]
            if kind != "other" or problem is not None or _southern_lead(g.get("reporter") or ""):
                e = _Entry("unparsed", cite_text, a, b, _veto("unparsed_citation"))
            else:
                cap, _cstat = _caption_in_gap(s[max(0, a - _TAIL_WINDOW - 50):a])
                e = _Entry("full", cite_text, a, b, Gate1Result(FALL_THROUGH, "not_florida_key"),
                           window=(cap + ", " if cap else "") + cite_text, caption=cap)
            entries.append(e)
            full_map[id(c)] = e

        resolutions = resolve_citations(ey_sorted, resolve_id_citation=_resolve_id_any_pin)
        res_of = {id(cit): res for res, cits in resolutions.items() for cit in cits}
        fulls_of = {}
        for res, cits in resolutions.items():
            fl = sorted(((idx_of[id(f)], f) for f in cits if isinstance(f, FullCitation) and id(f) in idx_of),
                        key=lambda t: t[0])
            fulls_of[res] = ([i for i, _f in fl], [f for _i, f in fl])
        all_fl = [(i, c) for i, c in enumerate(ey_sorted) if isinstance(c, FullCitation)]
        fulls_all = ([i for i, _c in all_fl], [c for _i, c in all_fl])
        out: List[TextResult] = [_tr(e, e.window) for e in entries]
        for c in ey_sorted:
            if isinstance(c, ShortCaseCitation):
                kind = "short"
            elif isinstance(c, IdCitation):
                kind = "id"
            elif isinstance(c, SupraCitation):
                kind = "supra"
            else:
                continue
            out.append(_short_result(s, c, kind, fulls_of, fulls_all, res_of, full_map, idx_of))
        out.extend(_residue_results(s, out))
        out.sort(key=lambda r: (r.start, r.end))
        return out
    except Exception:
        return [_text_veto("internal_error")]


def _read_stdin_text() -> str:
    return sys.stdin.buffer.read().decode("utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Gate 1 local Florida citation existence check.")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--citation")
    g.add_argument("--text", help="draft text; '-' reads the draft from stdin (UTF-8)")
    args = ap.parse_args(argv)
    if args.citation is not None:
        print(json.dumps(check_citation(args.citation, args.db).to_dict(), sort_keys=True))
        return 0
    if args.text == "-":
        try:
            draft = _read_stdin_text()
        except Exception:
            print(json.dumps([_text_veto("bad_encoding").to_dict()], sort_keys=True))
            return 0
    else:
        draft = args.text
    print(json.dumps([r.to_dict() for r in check_text(draft, args.db)], sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
