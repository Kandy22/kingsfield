"""Tiny CourtListener-shaped CSV fixtures and a DB built from them. Temp dirs only."""

import bz2
import csv
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from db.build_sqlite_index import build_index  # noqa: E402

DOCKETS = [
    ("10", "fla"), ("11", "fladistctapp"), ("12", "fladistctapp"), ("13", "fla"),
    ("14", "ala"), ("15", "flsd"), ("16", "fla"), ("17", "fladistctapp"),
]
CLUSTERS = [
    ("1", "Smith v. Jones", "10"),
    ("2", "State v. Rodriguez", "11"),
    ("3", "Alpha Corp. v. Beta Holdings, Inc.", "12"),
    ("4", "Gamma v. Delta", "13"),
    ("5", "Wrongstate v. Alabama", "14"),
    ("6", "Weekly Case v. Example", "15"),
    ("7", "Peña v. State", "16"),
    ("8", "Smith v. Jones", "17"),
    ("9", "Supreme Weekly v. Example", "15"),
    ("10", "Plain Weekly v. Example", "15"),
    ("11", "Weekly Dca v. Example", "11"),
    ("12", "Weekly Sup v. Example", "10"),
]
# (id, volume, reporter, page, cluster_id)
CITATIONS = [
    ("1", "123", "So. 3d", "456", "1"),
    ("2", "100", "So. 2d", "20", "2"),
    ("3", "321", "So. 3d", "789", "3"),
    ("4", "200", "So. 3d", "1", "4"),
    ("5", "100", "So. 2d", "20", "5"),       # Alabama cluster, same key as cluster 2: must be excluded
    ("6", "45", "Fla. L. Weekly", "D123", "6"),  # kept regardless of court; section D
    ("7", "150", "So.", "300", "7"),
    ("8", "400", "So. 3d", "10", "8"),
    ("9", "400", "So. 3d", "10", "8"),       # duplicate row: must collapse
    ("10", "999", "F.3d", "1", "1"),         # not a Florida key: dropped
    ("11", "12", "So. 3d", "D5", "1"),       # bad page: skipped
    ("12", "45", "Fla. L. Weekly", "S123", "9"),   # same volume/page, section S: a different case
    ("13", "45", "Fla. L. Weekly", "123", "10"),   # no section
    ("14", "46", "Fla. L. Weekly", "D7", "11"),    # DCA cluster
    ("15", "46", "Fla. L. Weekly Supp.", "3", "12"),  # Supreme Court cluster
]
BOUNDS = [("1", "456", "470"), ("2", "20", "35"), ("3", "789", "800"), ("7", "300", "305"), ("8", "10", "20")]
OPINIONS = [("501", "1", "Plain text of Smith v. Jones."), ("502", "5", "Alabama text must not load.")]


def _write(path: Path, header, rows, bz=False):
    opener = bz2.open if bz else open
    with opener(path, "wt", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def write_corpus(directory: Path, with_bounds=True, with_opinions=True):
    _write(directory / "dockets-2026-01-01.csv", ["id", "court_id", "docket_number"], [(i, c, "x") for i, c in DOCKETS])
    _write(directory / "opinion-clusters-2026-01-01.csv.bz2", ["id", "case_name", "docket_id", "headnotes"],
           [(i, n, d, "EDITORIAL HEADNOTE MUST NOT LOAD") for i, n, d in CLUSTERS], bz=True)
    _write(directory / "citations-2026-01-01.csv", ["id", "volume", "reporter", "page", "type", "cluster_id"],
           [(a, b, c, d, "1", e) for a, b, c, d, e in CITATIONS])
    if with_bounds:
        _write(directory / "page-bounds-2026.csv", ["cluster_id", "first_page", "last_page"], BOUNDS)
    if with_opinions:
        _write(directory / "opinions-2026-01-01.csv", ["id", "cluster_id", "plain_text"], OPINIONS)


def build_fixture_db(**kw):
    """Return (TemporaryDirectory, db_path, stats). Caller keeps the TemporaryDirectory alive."""
    tmp = tempfile.TemporaryDirectory()
    corpus = Path(tmp.name) / "corpus"
    corpus.mkdir()
    write_corpus(corpus, **kw)
    db = Path(tmp.name) / "kingsfield_florida.db"
    stats = build_index(corpus, db)
    return tmp, db, stats
