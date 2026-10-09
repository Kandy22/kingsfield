"""Build kingsfield_florida.db from CourtListener bulk CSVs (stdlib only).

Constraint A: Gate 1 (pipeline/gate1.py, backend/src/verification/local_sqlite_gate.ts)
answers existence for Florida state-court reporter keys from this file only.
Constraint B: raw opinion text goes to caselaw_opinion; summaries and GoodLaw
tags go to caselaw_analysis. The two tables are never joined or written together,
and this script creates caselaw_analysis empty.

Inputs (plain .csv or .csv.bz2, found by prefix in --corpus):
    citations*.csv          id, volume, reporter, page, cluster_id
    opinion-clusters*.csv   id, case_name, docket_id
    dockets*.csv            id, court_id
    page-bounds*.csv        OPTIONAL: cluster_id, first_page, last_page   (CAP-derived)
    opinions*.csv           OPTIONAL: cluster_id, id, plain_text         (raw text only)

No headnotes, syllabi, summaries, or key numbers are read from any column.

Every file is streamed row by row; none is loaded whole. The citations file is read
twice (once to find Fla. L. Weekly clusters and collect start pages, once to insert),
which keeps memory proportional to the Florida subset rather than the corpus.

Page bounds (citation_index.first_page / last_page / bounds_source)
-------------------------------------------------------------------
Real bounds come from an optional CAP-derived page-bounds CSV (bounds_source = 'cap').
When that file is absent, or has no last_page for a cluster, last_page is INFERRED from
the full citations CSV (bounds_source = 'inferred_next_case'):

    first_page = the case's own start page (this citation row's page).
    last_page  = the smallest distinct start page STRICTLY GREATER than this case's start
                 page among ALL citations (any state, any court, any cluster) in the same
                 reporter + volume (+ section for Fla. L. Weekly), minus one.
                 NULL when no later case exists in that group.

Why "minus one" (--last-page-convention prev_page, the default): the gate compares a pin
inclusively (first_page <= pin <= last_page). The real last page is either next_start - 1
or, when the next case begins mid-page, next_start itself. Using next_start - 1 can only
make the gate veto a genuine pin on a shared final page (a withheld answer); using
next_start can pass a pin that actually sits in the next case's opinion (a wrong cite
dressed as right). Gate 1 fails closed, so the default is next_start - 1.
--last-page-convention next_start opts into the permissive reading.

Limits that cannot be fixed from this data: a case missing from the citations CSV widens
its neighbour's bound over the gap; two cases that start on the same page get the same
bound. Fla. L. Weekly is sparse and interleaved with non-opinion matter, so its inferred
span is capped (--weekly-max-span, default 25 pages; 0 disables) and Fla. L. Weekly Supp.
is never inferred (no section letter, trial-court orders, very sparse coverage).

The build writes <db>.tmp and renames it into place on success, so a failed build
never leaves a half-written database at the real path. Never point this at the
corpus volume without the lead's go-ahead; the volume holds the multi-GB inputs.
"""

from __future__ import annotations

import argparse
import bisect
import bz2
import csv
import functools
import io
import os
import re
import sqlite3
import sys
from array import array
from pathlib import Path
from typing import Dict, Iterator, Optional, Set, Tuple

DEFAULT_CORPUS = "/Volumes/Kingsfield_Corpus"
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "kingsfield_florida.db"

# CourtListener court ids for Florida state courts: Supreme Court and the
# District Courts of Appeal (all six DCAs share one id).
FLORIDA_COURT_IDS = frozenset({"fla", "fladistctapp"})

SOUTHERN_KEYS = ("So.", "So. 2d", "So. 3d")
WEEKLY_KEYS = ("Fla. L. Weekly", "Fla. L. Weekly Supp.")

# loose key (lowercase alphanumerics) -> canonical reporters_db key. Stdlib only,
# so this is the small closed set CourtListener actually emits for these reporters.
_LOOSE_TO_CANON = {
    "so": "So.",
    "so2d": "So. 2d",
    "so3d": "So. 3d",
    "flalweekly": "Fla. L. Weekly",
    "flalweeklysupp": "Fla. L. Weekly Supp.",
}

SCHEMA = """
CREATE TABLE citation_index (
    reporter    TEXT    NOT NULL,
    volume      INTEGER NOT NULL,
    page        INTEGER NOT NULL,
    section     TEXT    NOT NULL DEFAULT '',
    cluster_id  INTEGER NOT NULL,
    case_name   TEXT,
    court_id    TEXT,
    first_page  INTEGER,
    last_page   INTEGER,
    bounds_source TEXT
);
CREATE UNIQUE INDEX uq_citation_row ON citation_index(reporter, volume, page, section, cluster_id);
CREATE TABLE caselaw_opinion (
    cluster_id  INTEGER NOT NULL,
    opinion_id  INTEGER,
    plain_text  TEXT
);
CREATE TABLE caselaw_analysis (
    cluster_id  INTEGER NOT NULL,
    summary     TEXT,
    goodlaw_tag TEXT,
    source      TEXT
);
"""

INDEXES = """
CREATE INDEX idx_citation_rvp ON citation_index(reporter, volume, page, section);
CREATE INDEX idx_opinion_cluster ON caselaw_opinion(cluster_id);
CREATE INDEX idx_analysis_cluster ON caselaw_analysis(cluster_id);
"""


# CourtListener opinion rows hold whole opinions in one field; raise the csv cap.
_limit = sys.maxsize
while True:
    try:
        csv.field_size_limit(_limit)
        break
    except OverflowError:
        _limit //= 10


BOUNDS_CAP = "cap"
BOUNDS_INFERRED = "inferred_next_case"
LAST_PAGE_CONVENTIONS = ("prev_page", "next_start")
DEFAULT_LAST_PAGE_CONVENTION = "prev_page"
DEFAULT_WEEKLY_MAX_SPAN = 25
# Keys whose bounds are never inferred (see module docstring).
NO_INFERENCE_KEYS = frozenset({"Fla. L. Weekly Supp."})


@functools.lru_cache(maxsize=None)
def canonical_reporter(raw: str) -> Optional[str]:
    """Map a CourtListener reporter string to the canonical key, or None."""
    loose = re.sub(r"[^a-z0-9]", "", (raw or "").lower())
    return _LOOSE_TO_CANON.get(loose)


def infer_last_page(
    starts: Optional["array"],
    page: int,
    convention: str = DEFAULT_LAST_PAGE_CONVENTION,
    max_span: int = 0,
) -> Tuple[Optional[int], Optional[str]]:
    """Return (last_page, null_reason) for a case starting at `page`.

    `starts` is the sorted array of distinct start pages in the case's reporter+volume
    (+section) group. null_reason is None when last_page is set, else 'last_in_volume' or
    'span_exceeded'. max_span 0 means no cap.
    """
    if starts is None:
        return None, "last_in_volume"
    i = bisect.bisect_right(starts, page)
    if i >= len(starts):
        return None, "last_in_volume"
    nxt = starts[i]
    if max_span and nxt - page > max_span:
        return None, "span_exceeded"
    return (nxt - 1 if convention == "prev_page" else nxt), None


def _find(corpus: Path, prefix: str) -> Optional[Path]:
    """Locate '<prefix>*.csv' or '<prefix>*.csv.bz2' (first by sorted name)."""
    hits = sorted(
        p for p in corpus.iterdir()
        if p.is_file() and p.name.startswith(prefix)
        and (p.name.endswith(".csv") or p.name.endswith(".csv.bz2"))
    )
    return hits[0] if hits else None


def _rows(path: Path) -> Iterator[Dict[str, str]]:
    """Stream a CSV (optionally bz2) as dict rows."""
    if path.name.endswith(".bz2"):
        raw = bz2.open(path, "rb")
    else:
        raw = open(path, "rb")
    with raw:
        text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="")
        yield from csv.DictReader(text)


def split_page(reporter: str, value: Optional[str]) -> Optional[Tuple[str, int]]:
    """Return (section, page) or None. Fla. L. Weekly pages carry a division letter:
    "D500" -> ("D", 500). Every other key takes digits only ("" section)."""
    if value is None:
        return None
    value = value.strip()
    if reporter == "Fla. L. Weekly":
        m = re.fullmatch(r"([A-Z]?)([0-9]{1,9})", value)
        return (m.group(1), int(m.group(2))) if m else None
    n = _int(value)
    return ("", n) if n is not None else None


def _int(value: Optional[str]) -> Optional[int]:
    """Strict base-10 ASCII integer; None for anything else (blank, 'D123', unicode digits)."""
    if value is None:
        return None
    value = value.strip()
    if not re.fullmatch(r"[0-9]{1,9}", value):
        return None
    return int(value)


def build_index(
    corpus_dir,
    db_path,
    florida_court_ids=FLORIDA_COURT_IDS,
    infer_bounds: bool = True,
    last_page_convention: str = DEFAULT_LAST_PAGE_CONVENTION,
    weekly_max_span: int = DEFAULT_WEEKLY_MAX_SPAN,
) -> dict:
    if last_page_convention not in LAST_PAGE_CONVENTIONS:
        raise ValueError(f"last_page_convention must be one of {LAST_PAGE_CONVENTIONS}")
    corpus = Path(corpus_dir)
    db_path = Path(db_path)

    citations = _find(corpus, "citations")
    clusters = _find(corpus, "opinion-clusters")
    dockets = _find(corpus, "dockets")
    bounds = _find(corpus, "page-bounds")
    opinions = _find(corpus, "opinions")
    missing = [n for n, p in (("citations", citations), ("opinion-clusters", clusters), ("dockets", dockets)) if p is None]
    if missing:
        raise FileNotFoundError(f"missing required CSV(s) in {corpus}: {', '.join(missing)}")

    stats = {
        "dockets_florida": 0,
        "weekly_clusters": 0,
        "clusters_kept": 0,
        "citations_seen": 0,
        "citations_inserted": 0,
        "skipped_bad_page": 0,
        "skipped_no_cluster": 0,
        "bounds_rows": 0,
        "opinions_inserted": 0,
        # Inference counters. The three null_* reasons count candidate rows before the
        # INSERT OR IGNORE de-duplication; the bounds_* totals below are read from the DB.
        "start_pages_collected": 0,
        "bounds_null_last_in_volume": 0,
        "bounds_null_span_exceeded": 0,
        "bounds_null_not_inferred": 0,
        "bounds_cap": 0,
        "bounds_inferred": 0,
        "last_page_null_total": 0,
    }

    # Pass 1: Florida docket ids.
    docket_court: Dict[str, str] = {}
    for row in _rows(dockets):
        if row.get("court_id") in florida_court_ids:
            docket_court[row["id"]] = row["court_id"]
    stats["dockets_florida"] = len(docket_court)

    # Pass 2: clusters named by Fla. L. Weekly citations (kept regardless of court).
    # The same pass collects every start page of the five in-scope reporter keys, from ALL
    # states and clusters, keyed by (reporter, volume, section), for bounds inference.
    weekly_clusters: Set[str] = set()
    start_pages: Dict[Tuple[str, int, str], "array"] = {}
    for row in _rows(citations):
        rep = canonical_reporter(row.get("reporter", ""))
        if rep is None:
            continue
        if rep in WEEKLY_KEYS:
            weekly_clusters.add(row.get("cluster_id", ""))
        if infer_bounds and rep not in NO_INFERENCE_KEYS:
            vol, sp = _int(row.get("volume")), split_page(rep, row.get("page"))
            if vol is not None and sp is not None:
                key = (rep, vol, sp[0])
                arr = start_pages.get(key)
                if arr is None:
                    arr = start_pages[key] = array("i")
                arr.append(sp[1])
    stats["weekly_clusters"] = len(weekly_clusters)
    # Sorted distinct pages per group; int32 arrays keep 18M-row corpora to a few MB.
    for key in list(start_pages):
        uniq = array("i", sorted(set(start_pages[key])))
        start_pages[key] = uniq
        stats["start_pages_collected"] += len(uniq)

    # Pass 3: clusters. Only id, case_name, docket_id are read.
    cluster_name: Dict[str, str] = {}
    cluster_court: Dict[str, Optional[str]] = {}
    for row in _rows(clusters):
        cid = row.get("id", "")
        court = docket_court.get(row.get("docket_id", ""))
        if court is not None or cid in weekly_clusters:
            cluster_name[cid] = row.get("case_name", "") or ""
            cluster_court[cid] = court
    stats["clusters_kept"] = len(cluster_name)

    bounds_map: Dict[str, Tuple[Optional[int], Optional[int]]] = {}
    if bounds is not None:
        for row in _rows(bounds):
            cid = row.get("cluster_id", "")
            if cid in cluster_name:
                bounds_map[cid] = (_int(row.get("first_page")), _int(row.get("last_page")))
        stats["bounds_rows"] = len(bounds_map)

    tmp = db_path.with_name(db_path.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    conn = sqlite3.connect(str(tmp))
    try:
        conn.executescript(SCHEMA)

        # Pass 4: insert citations.
        batch = []
        for row in _rows(citations):
            stats["citations_seen"] += 1
            reporter = canonical_reporter(row.get("reporter", ""))
            if reporter is None:
                continue
            cid = row.get("cluster_id", "")
            if cid not in cluster_name:
                # So.* rows outside Florida courts land here by design.
                if reporter in SOUTHERN_KEYS:
                    continue
                stats["skipped_no_cluster"] += 1
                continue
            if reporter in SOUTHERN_KEYS and cluster_court.get(cid) not in florida_court_ids:
                continue
            volume, sp = _int(row.get("volume")), split_page(reporter, row.get("page"))
            if volume is None or sp is None:
                stats["skipped_bad_page"] += 1
                continue
            section, page = sp
            cap_first, cap_last = bounds_map.get(cid, (None, None))
            first = cap_first if cap_first is not None else page
            last, source = cap_last, (BOUNDS_CAP if cap_last is not None else None)
            if last is None and infer_bounds:
                if reporter in NO_INFERENCE_KEYS or (reporter in WEEKLY_KEYS and weekly_max_span <= 0):
                    stats["bounds_null_not_inferred"] += 1
                else:
                    cap = weekly_max_span if reporter in WEEKLY_KEYS else 0
                    inferred, why = infer_last_page(
                        start_pages.get((reporter, volume, section)), page, last_page_convention, cap)
                    if inferred is not None and inferred >= first:
                        last, source = inferred, BOUNDS_INFERRED
                    elif why == "span_exceeded":
                        stats["bounds_null_span_exceeded"] += 1
                    else:
                        stats["bounds_null_last_in_volume"] += 1
            batch.append((
                reporter, volume, page, section, int(cid), cluster_name[cid],
                cluster_court.get(cid), first, last, source,
            ))
            if len(batch) >= 5000:
                stats["citations_inserted"] += _flush(conn, batch)
                batch = []
        if batch:
            stats["citations_inserted"] += _flush(conn, batch)

        # Optional raw opinion text. plain_text only; no other column is read.
        if opinions is not None:
            obatch = []
            for row in _rows(opinions):
                cid = row.get("cluster_id", "")
                if cid not in cluster_name or _int(cid) is None:
                    continue
                obatch.append((int(cid), _int(row.get("id")), row.get("plain_text", "") or ""))
                if len(obatch) >= 500:
                    conn.executemany("INSERT INTO caselaw_opinion VALUES (?,?,?)", obatch)
                    stats["opinions_inserted"] += len(obatch)
                    obatch = []
            if obatch:
                conn.executemany("INSERT INTO caselaw_opinion VALUES (?,?,?)", obatch)
                stats["opinions_inserted"] += len(obatch)

        conn.executescript(INDEXES)
        conn.commit()
        for src, n in conn.execute("SELECT bounds_source, COUNT(*) FROM citation_index GROUP BY 1"):
            if src == BOUNDS_CAP:
                stats["bounds_cap"] = n
            elif src == BOUNDS_INFERRED:
                stats["bounds_inferred"] = n
        stats["last_page_null_total"] = conn.execute(
            "SELECT COUNT(*) FROM citation_index WHERE last_page IS NULL").fetchone()[0]
    except BaseException:
        conn.close()
        if tmp.exists():
            tmp.unlink()
        raise
    conn.close()
    os.replace(tmp, db_path)
    return stats


def _flush(conn: sqlite3.Connection, batch: list) -> int:
    before = conn.total_changes
    conn.executemany("INSERT OR IGNORE INTO citation_index VALUES (?,?,?,?,?,?,?,?,?,?)", batch)
    return conn.total_changes - before


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build kingsfield_florida.db from CourtListener bulk CSVs.")
    ap.add_argument("--corpus", default=DEFAULT_CORPUS)
    ap.add_argument("--out", default=str(DEFAULT_DB))
    ap.add_argument("--no-infer-bounds", action="store_true",
                    help="do not infer last_page from neighbouring citations (CAP bounds only)")
    ap.add_argument("--last-page-convention", choices=LAST_PAGE_CONVENTIONS, default=DEFAULT_LAST_PAGE_CONVENTION,
                    help="prev_page (default, fail-closed): last_page = next case start - 1; "
                         "next_start: last_page = next case start")
    ap.add_argument("--weekly-max-span", type=int, default=DEFAULT_WEEKLY_MAX_SPAN,
                    help="Fla. L. Weekly: leave last_page NULL when the next case is more than this many "
                         "pages away (0 disables Weekly inference)")
    args = ap.parse_args(argv)
    stats = build_index(
        args.corpus, args.out,
        infer_bounds=not args.no_infer_bounds,
        last_page_convention=args.last_page_convention,
        weekly_max_span=args.weekly_max_span,
    )
    for k, v in stats.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
