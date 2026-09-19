"""Readers for the pipeline outputs the producers draw on.

Data root: $KINGSFIELD_DATA, else ../judicial-intel-analytics/data relative to
this repo. Per channel (fl_2dca, fl_6dca):

    flcourts/decisions.jsonl      every decision the court issued (flcourts API)
    panel/oa_results.csv          Jev oral-argument panel, joined to ground truth
    dockets/<video_id>.json       per-video decision record (flcourts / CourtListener / PDF parse)
    captions/<video_id>.info.json YouTube metadata (upload_date ≈ argument date)

Nothing here computes; it loads and normalizes so producers stay readable.
"""
from __future__ import annotations

import csv
import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("KINGSFIELD_DATA") or (ROOT.parent / "judicial-intel-analytics" / "data"))

DISPO_WORDS = ("affirmed", "reversed", "denied", "dismissed", "granted", "quashed", "vacated", "remanded")


def channel_dir(channel: str) -> Path:
    return DATA / channel


# ---- decisions (the court's whole output) -----------------------------------

def disposition_text(rec: dict) -> str:
    """Same reassembly as enrich_flcourts.py: older records carry the disposition
    in `opinion_type` with `note` as a continuation; 2026 records carry the type
    there and the disposition in `note`."""
    typ = (rec.get("opinion_type") or "").strip()
    note = (rec.get("note") or "").strip()
    if typ and typ.lower().split()[0].rstrip(".;,") in DISPO_WORDS:
        return (typ + (" " + note if note and not note.startswith("**") else "")).strip()
    if note and not note.startswith("**"):
        return note
    if "Per Curiam Affirmed" in typ or "PC Affirmed" in typ:
        return "Affirmed"
    if "PC Denied" in typ:
        return "Denied"
    return ""


def classify(dispo: str) -> str:
    d = (dispo or "").lower()
    if not d:
        return "unknown"
    if "in part" in d and ("revers" in d or "vacat" in d):
        return "mixed"
    if d.startswith(("reversed", "vacated", "quashed", "remanded")):
        return "reverse"
    if d.startswith("affirmed"):
        return "affirm"
    if d.startswith(("dismissed", "petition dismissed")):
        return "dismissed"
    if d.startswith(("denied", "petition denied")):
        return "denied"
    if d.startswith(("granted", "petition granted")):
        return "granted"
    return "other"


CASE_KEY_RE = re.compile(r"^\s*(?:[1-6]D)?(\d{2}|\d{4})-(\d{1,5})\s*$")


def case_key(raw: str | None) -> tuple[int, int] | None:
    m = CASE_KEY_RE.match(raw or "")
    if not m:
        return None
    y = int(m.group(1))
    return (2000 + y if y < 100 else y, int(m.group(2)))


def load_decisions(channel: str) -> dict[tuple[int, int], dict]:
    """One dispositive record per case: {(year, seq): {disposition, decided_date, is_pca, ...}}."""
    path = channel_dir(channel) / "flcourts" / "decisions.jsonl"
    by: dict[tuple[int, int], list[dict]] = {}
    if not path.exists():
        return {}
    for line in path.open(encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        k = case_key(r.get("case_number_raw"))
        if k:
            by.setdefault(k, []).append(r)
    out: dict[tuple[int, int], dict] = {}
    for k, recs in by.items():
        with_text = [r for r in recs if disposition_text(r)]
        r = sorted(with_text or recs, key=lambda x: x.get("decided_date") or "")[-1]
        typ = r.get("opinion_type") or ""
        out[k] = {
            "case_key": k,
            "case_number": f"{k[0]}-{k[1]:04d}",
            "case_style": r.get("case_style"),
            "disposition_text": disposition_text(r),
            "disposition": classify(disposition_text(r)),
            "decided_date": r.get("decided_date"),
            "is_pca": r.get("opinion_type_label") == "PCA" or "Per Curiam Affirmed" in typ or r.get("listing_type") == "pca",
            "n_records": len(recs),
        }
    return out


# ---- OA panel rows (Jev outputs + joined ground truth) ---------------------

def _f(v: Any) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _i(v: Any) -> int | None:
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _b(v: Any) -> bool | None:
    if v in ("True", True):
        return True
    if v in ("False", False):
        return False
    return None


def load_oa_rows(channel: str) -> list[dict]:
    """Rows of panel/oa_results.csv with typed columns. Only rows that passed
    both gates (python + model) and were actually scored."""
    path = channel_dir(channel) / "panel" / "oa_results.csv"
    if not path.exists():
        return []
    rows = []
    for r in csv.DictReader(path.open(encoding="utf-8")):
        if r.get("error") or r.get("_gated_out"):
            continue
        if (_f(r.get("transcript_sufficient")) or 0) < 0.5 or (_f(r.get("is_oral_argument")) or 0) < 0.5:
            continue
        rows.append({
            "video_id": r["video_id"],
            "case_number": r.get("case_number"),
            "case_name": r.get("case_name") or None,
            "upload_date": r.get("upload_date") or None,
            "decided_date": r.get("decided_date") or None,
            "disposition": r.get("disposition") or None,
            "decision_found": _b(r.get("decision_found")),
            "is_pca": _b(r.get("is_pca")),
            "panel_judges": [j.strip() for j in (r.get("panel_judges") or "").split(";") if j.strip()],
            "author": r.get("author") or None,
            "trial_judge": r.get("trial_judge") or None,
            "county": r.get("county") or None,
            "appellant_counsel": r.get("appellant_counsel") or None,
            "appellee_counsel": r.get("appellee_counsel") or None,
            "has_dissent": _b(r.get("has_dissent")),
            # ---- Jev outputs (the only model-derived inputs in this repo)
            "ruling_lean": r.get("ruling_lean") or None,
            "ruling_lean_confidence": _f(r.get("ruling_lean__confidence")),
            "ruling_lean_p_affirm": _f(r.get("ruling_lean__p_affirm")),
            "ruling_lean_p_reverse": _f(r.get("ruling_lean__p_reverse")),
            "skepticism_gap": _i(r.get("skepticism_gap")),
            "appellant_hostile_mass": _f(r.get("appellant_hostile_mass")),
            "appellee_hostile_mass": _f(r.get("appellee_hostile_mass")),
            "appellant_modal": _i(r.get("bench_skepticism_toward_appellant__modal")),
            "appellee_modal": _i(r.get("bench_skepticism_toward_appellee__modal")),
            "appellant_bimodal": _b(r.get("bench_skepticism_toward_appellant__bimodal")),
            "appellee_bimodal": _b(r.get("bench_skepticism_toward_appellee__bimodal")),
            "trial_court_posture": r.get("bench_posture_toward_trial_court") or None,
            "panel_disagreement": _f(r.get("panel_disagreement")),
            "bench_says_issue_unraised": _f(r.get("bench_says_issue_unraised")),
            "bench_raises_jurisdiction": _f(r.get("bench_raises_jurisdiction")),
            # ---- transcript quality
            "n_words": _i(r.get("n_words")),
            "has_both_sides": _b(r.get("has_both_sides")),
            "turns_coarse": _b(r.get("turns_coarse")),
        })
    return rows


# ---- helpers ----------------------------------------------------------------

def parse_date(s: str | None) -> date | None:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s[:10] if fmt == "%Y-%m-%d" else s[:8], fmt).date()
        except ValueError:
            continue
    return None


def days_between(a: str | None, b: str | None) -> int | None:
    da, db = parse_date(a), parse_date(b)
    if not da or not db:
        return None
    return (db - da).days


def judge_id(name: str) -> str:
    """Stable id from a surname as it appears in an opinion ('Rothstein-Youakim' → 'rothstein-youakim')."""
    return re.sub(r"[^a-z\-]", "", name.strip().lower().replace(" ", "-"))


COUNSEL_RE = re.compile(r"^(?P<names>.+?)\s+of\s+(?P<firm>.+?)(?:,\s*(?P<city>[A-Z][A-Za-z .]+))?$")


def split_counsel(s: str | None) -> list[dict]:
    """'Jawdet I. Rubaii of Jawdet I. Rubaii, P.A., Clearwater' → [{name, firm}].
    Multiple counsel: 'A and B of Firm, City' → two rows sharing the firm.
    Anything unparseable becomes {name: s, firm: None}."""
    if not s:
        return []
    s = " ".join(s.split())
    s = re.sub(r",?\s*for Appell(?:ant|ee)s?.*$", "", s, flags=re.I).strip().rstrip(".;,")
    m = COUNSEL_RE.match(s)
    if not m:
        return [{"name": s, "firm": None}]
    names = re.split(r",\s*(?:and\s+)?|\s+and\s+", m.group("names"))
    firm = m.group("firm").strip().rstrip(",")
    return [{"name": n.strip(), "firm": firm} for n in names if n.strip()]
