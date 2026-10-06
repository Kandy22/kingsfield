"""Draft-mode fixture: the base CourtListener-shaped corpus plus a second Florida record.

Extra record: cluster 20 "Smith v. State", 100 So. 3d 200 (Florida Supreme Court), pages 200-210.
Everything else is _fixture.py's data (Smith v. Jones at 123 So. 3d 456-470, State v. Rodriguez at
100 So. 2d 20-35 in a DCA, Alpha Corp. v. Beta Holdings at 321 So. 3d 789-800, ...).
"""

import tempfile
from pathlib import Path

import _fixture as base
from db.build_sqlite_index import build_index

EXTRA_DOCKETS = [("20", "fla")]
EXTRA_CLUSTERS = [("20", "Smith v. State", "20")]
EXTRA_CITATIONS = [("20", "100", "So. 3d", "200", "20")]
EXTRA_BOUNDS = [("20", "200", "210")]


def write_draft_corpus(directory: Path):
    base._write(directory / "dockets-2026-01-01.csv", ["id", "court_id", "docket_number"],
                [(i, c, "x") for i, c in base.DOCKETS + EXTRA_DOCKETS])
    base._write(directory / "opinion-clusters-2026-01-01.csv.bz2", ["id", "case_name", "docket_id", "headnotes"],
                [(i, n, d, "EDITORIAL HEADNOTE MUST NOT LOAD") for i, n, d in base.CLUSTERS + EXTRA_CLUSTERS], bz=True)
    base._write(directory / "citations-2026-01-01.csv", ["id", "volume", "reporter", "page", "type", "cluster_id"],
                [(a, b, c, d, "1", e) for a, b, c, d, e in base.CITATIONS + EXTRA_CITATIONS])
    base._write(directory / "page-bounds-2026.csv", ["cluster_id", "first_page", "last_page"],
                base.BOUNDS + EXTRA_BOUNDS)
    base._write(directory / "opinions-2026-01-01.csv", ["id", "cluster_id", "plain_text"], base.OPINIONS)


def build_draft_db():
    """Return (TemporaryDirectory, db_path). Caller keeps the TemporaryDirectory alive."""
    tmp = tempfile.TemporaryDirectory()
    corpus = Path(tmp.name) / "corpus"
    corpus.mkdir()
    write_draft_corpus(corpus)
    db = Path(tmp.name) / "kingsfield_florida.db"
    build_index(corpus, db)
    return tmp, db
