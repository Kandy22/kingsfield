#!/usr/bin/env python3
"""
Populate the catalog from the pipeline. Produces JudgeIntelSnapshot payloads
(types.ts) for a court, its appellate judges, and the trial judges whose
cases it heard, plus per-case F26 probability cards and taxonomy/COVERAGE.md.

    python3 src/build_snapshots.py --channel fl_2dca
    python3 src/build_snapshots.py --channel fl_6dca

Writes data/snapshots/<channel>/
    court.json                    F12 F13 F17 F19 F22 F25 F26(model) for the court
    judges/<judge_id>.json        F12 F13 F19 for each appellate judge's panels
    trial_judges/<judge_id>.json  F19 appellate trail per trial judge
    counsel.json                  F21 / F29 dossier (floor n ≥ 5)
    cases.jsonl                   one F26 probability card per argued case
    coverage.json                 which facts are populated, for which entities

Every producer returns (value, provenance) or None. Producers only do
arithmetic on public records and on the Jev panel outputs already on disk;
no model is called here. The jev hint in the catalog says which facts a
model may touch downstream; it is recorded in provenance, not acted on.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from catalog import load as load_catalog  # noqa: E402
from sources import (ROOT, channel_dir, days_between, judge_id, load_decisions, load_oa_rows,  # noqa: E402
                     split_counsel)
from value_types import validate  # noqa: E402
from voting import banzhaf_result, condorcet_result  # noqa: E402

NOW = datetime.now(timezone.utc).isoformat(timespec="seconds")
FLOOR_N = 5           # F29: suppress counsel rows below this
CAL_MIN_N = 20        # F26: abstain when the calibration bin is smaller than this
CAL_MIN_LIFT = 0.10   # F26: abstain when the bin is within ±10 pts of the base rate


def wilson(k: int, n: int, z: float = 1.96) -> dict:
    if n == 0:
        return {"lo": 0.0, "hi": 1.0, "method": "wilson"}
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return {"lo": round(max(0.0, c - h), 3), "hi": round(min(1.0, c + h), 3), "method": "wilson"}


def prov(source: str, note: str | None = None) -> dict:
    d = {"source": source, "collected_at": NOW}
    if note:
        d["note"] = note
    return d


# ---- producers -------------------------------------------------------------

def appeals_row(dispos: list[str], scope: str, by_year: dict[int, list[str]] | None = None) -> dict:
    c = Counter(dispos)
    a, r, m = c["affirm"], c["reverse"], c["mixed"]
    den = a + r + m
    row = {
        "scope": scope, "n": len(dispos), "affirmed": a, "reversed": r, "mixed": m,
        "other": len(dispos) - den,
        "reversal_rate": round((r + m) / den, 3) if den else None,
        "reversal_rate_ci95": wilson(r + m, den),
    }
    if by_year:
        row["by_year"] = []
        for y in sorted(by_year):
            cy = Counter(by_year[y]); dy = cy["affirm"] + cy["reverse"] + cy["mixed"]
            if dy:
                row["by_year"].append({"year": y, "n": len(by_year[y]), "reversal_rate": round((cy["reverse"] + cy["mixed"]) / dy, 3)})
    return row


def named_shares(items: list[str]) -> list[dict]:
    c = Counter(items); tot = sum(c.values())
    return [{"name": k, "count": v, "share": round(v / tot, 3)} for k, v in c.most_common()]


def duration(days: list[int], frm: str, to: str) -> dict | None:
    days = [d for d in days if d is not None and 0 <= d <= 1500]
    if len(days) < 5:
        return None
    s = sorted(days)
    return {"n": len(s), "median": statistics.median(s), "mean": round(statistics.fmean(s), 1),
            "p10": s[int(0.10 * (len(s) - 1))], "p90": s[int(0.90 * (len(s) - 1))], "from_event": frm, "to_event": to}


def milestone_forecast(days: list[int]) -> list[dict] | None:
    days = sorted(d for d in days if d is not None and 0 <= d <= 1500)
    if len(days) < 20:
        return None
    q = lambda f: days[int(f * (len(days) - 1))]
    return [{"milestone": "decision", "from_event": "oral_argument", "n": len(days),
             "p50_days": q(0.5), "p80_days": q(0.8), "p90_days": q(0.9),
             "basis": "empirical quantiles of argument→decision days for this court; upload date stands in for argument date"}]


def gap_bin(g: int | None) -> str:
    if g is None:
        return "no_gap"
    return "gap<=-2" if g <= -2 else "gap=-1" if g == -1 else "gap=0" if g == 0 else "gap=+1" if g == 1 else "gap>=+2"


def calib_bin(r: dict) -> str:
    """The bin a case falls in. Gap first (strongest); inside gap=0, ruling_lean
    at ≥0.7 confidence; else the uninformative middle."""
    g = gap_bin(r["skepticism_gap"])
    if g in ("gap<=-2", "gap=-1", "gap=+1", "gap>=+2"):
        return g
    c = r["ruling_lean_confidence"] or 0.0
    if r["ruling_lean"] in ("affirm", "reverse") and c >= 0.7:
        return f"gap=0|lean={r['ruling_lean']}|conf>=0.7"
    return "gap=0|uninformative"


def fit_calibration(rows: list[dict]) -> tuple[dict, float]:
    """Empirical P(affirm) per bin over cases with a decision. This is the whole model."""
    judged = [r for r in rows if r["disposition"] in ("affirm", "reverse", "mixed")]
    base = sum(1 for r in judged if r["disposition"] == "affirm") / len(judged) if judged else 0.0
    bins: dict[str, list[bool]] = defaultdict(list)
    for r in judged:
        bins[calib_bin(r)].append(r["disposition"] == "affirm")
    table = {b: {"n": len(v), "p_affirm": round(sum(v) / len(v), 3)} for b, v in bins.items()}
    return table, round(base, 3)


def probability_card(r: dict, table: dict, base: float) -> dict:
    b = calib_bin(r)
    cell = table.get(b, {"n": 0, "p_affirm": None})
    n, p = cell["n"], cell["p_affirm"]
    abstain = n < CAL_MIN_N or p is None or abs(p - base) < CAL_MIN_LIFT
    why = ("bin too small" if n < CAL_MIN_N else "bin within ±10 pts of base rate" if p is not None and abs(p - base) < CAL_MIN_LIFT else "calibrated bin")
    return {"outcome": "affirm", "p": None if abstain else p, "base_rate": base, "n_calibration": n, "bin": b,
            "abstain": abstain, "why": why,
            "inputs": {"skepticism_gap": r["skepticism_gap"], "ruling_lean": r["ruling_lean"],
                       "ruling_lean_confidence": r["ruling_lean_confidence"],
                       "appellant_bimodal": r["appellant_bimodal"], "appellee_bimodal": r["appellee_bimodal"],
                       "signal_source": "typesafe/jev-1.13 oral-argument panel"}}


def decision_tree(table: dict, base: float, n: int) -> dict:
    """The if-then rule the calibration table implies, with support at every leaf."""
    def leaf(b, label):
        c = table.get(b, {"n": 0, "p_affirm": base})
        return {"leaf": True, "n": c["n"], "p_affirm": c["p_affirm"], "label": label}
    def gap_leaf(bins, label):
        ns = sum(table.get(b, {"n": 0})["n"] for b in bins)
        ks = sum(table.get(b, {"n": 0, "p_affirm": 0})["n"] * (table.get(b, {"p_affirm": 0})["p_affirm"] or 0) for b in bins)
        return {"leaf": True, "n": ns, "p_affirm": round(ks / ns, 3) if ns else None, "label": label}
    root = {
        "leaf": False, "feature": "skepticism_gap", "op": ">=", "threshold": 1,
        "left": gap_leaf(["gap=+1", "gap>=+2"], "bench harder on appellant → affirm"),
        "right": {
            "leaf": False, "feature": "skepticism_gap", "op": "<=", "threshold": -1,
            "left": gap_leaf(["gap=-1", "gap<=-2"], "bench harder on appellee → reversal-leaning; low support"),
            "right": {
                "leaf": False, "feature": "ruling_lean_confidence", "op": ">=", "threshold": 0.7,
                "left": {
                    "leaf": False, "feature": "ruling_lean", "op": "==", "threshold": "affirm",
                    "left": leaf("gap=0|lean=affirm|conf>=0.7", "confident affirm lean"),
                    "right": leaf("gap=0|lean=reverse|conf>=0.7", "confident reverse lean"),
                },
                "right": leaf("gap=0|uninformative", "abstain"),
            },
        },
    }
    rules = [
        f"IF skepticism_gap >= +1 THEN affirm  (p={root['left']['p_affirm']}, n={root['left']['n']})",
        f"ELIF skepticism_gap <= -1 THEN reversal-leaning  (p_affirm={root['right']['left']['p_affirm']}, n={root['right']['left']['n']})",
        f"ELIF ruling_lean_confidence >= 0.7 AND ruling_lean == affirm THEN affirm  (p={root['right']['right']['left']['left']['p_affirm']}, n={root['right']['right']['left']['left']['n']})",
        f"ELIF ruling_lean_confidence >= 0.7 AND ruling_lean == reverse THEN reverse-leaning  (p_affirm={root['right']['right']['left']['right']['p_affirm']}, n={root['right']['right']['left']['right']['n']})",
        f"ELSE abstain  (p_affirm={root['right']['right']['right']['p_affirm']} ≈ base {base}, n={root['right']['right']['right']['n']})",
    ]
    return {"target": "affirm", "fit_on": "argued cases with a decision; bins are empirical rates, no smoothing", "n": n, "root": root, "rules_text": rules}


def counsel_rows(rows: list[dict], court_id: str) -> dict:
    agg: dict[tuple[str, str, str], dict] = {}
    for r in rows:
        if r["disposition"] not in ("affirm", "reverse", "mixed"):
            continue
        for side, col, mass in (("appellant", "appellant_counsel", "appellant_hostile_mass"),
                                ("appellee", "appellee_counsel", "appellee_hostile_mass")):
            for c in split_counsel(r[col]):
                key = (c["name"], c["firm"] or "", side)
                a = agg.setdefault(key, {"counsel": c["name"], "firm": c["firm"], "side": side, "n": 0, "wins": 0, "mass": [], "cases": []})
                a["n"] += 1
                won = (r["disposition"] in ("reverse", "mixed")) if side == "appellant" else (r["disposition"] == "affirm")
                a["wins"] += int(won)
                if r[mass] is not None:
                    a["mass"].append(r[mass])
                a["cases"].append(r["case_number"])
    out = []
    for a in agg.values():
        if a["n"] < FLOOR_N:
            continue
        out.append({"counsel": a["counsel"], "firm": a["firm"], "side": a["side"], "n": a["n"], "wins": a["wins"],
                    "win_rate": round(a["wins"] / a["n"], 3), "win_rate_ci95": wilson(a["wins"], a["n"]),
                    "bench_hostile_mass_mean": round(statistics.fmean(a["mass"]), 3) if a["mass"] else None,
                    "cases": a["cases"]})
    out.sort(key=lambda x: -x["n"])
    return {"entity_type": "counsel", "court_id": court_id, "rows": out, "floor_n": FLOOR_N}


# ---- snapshot assembly -----------------------------------------------------

def snapshot(judge: str, court: str, fields: dict, provenance: dict) -> dict:
    cat = load_catalog()
    vt = {f["id"]: f["value_type"] for f in cat["factual"]}
    problems = {}
    for fid, val in fields.items():
        p = validate(vt[fid], val)
        if p:
            problems[fid] = p
    return {"judge_id": judge, "court_id": court, "as_of": NOW[:10], "fields": fields, "provenance": provenance,
            **({"validation_problems": problems} if problems else {})}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="fl_2dca")
    args = ap.parse_args()
    ch = args.channel
    out = ROOT / "data" / "snapshots" / ch
    (out / "judges").mkdir(parents=True, exist_ok=True)
    (out / "trial_judges").mkdir(parents=True, exist_ok=True)

    decisions = load_decisions(ch)
    rows = load_oa_rows(ch)
    judged = [r for r in rows if r["disposition"] in ("affirm", "reverse", "mixed")]
    print(f"{ch}: {len(decisions)} court decisions, {len(rows)} argued cases scored, {len(judged)} with a decision")

    # ---- court snapshot
    all_d = [d["disposition"] for d in decisions.values()]
    by_year: dict[int, list[str]] = defaultdict(list)
    for k, d in decisions.items():
        if d["decided_date"]:
            by_year[int(d["decided_date"][:4])].append(d["disposition"])
    court_fields, court_prov = {}, {}
    f19 = appeals_row(all_d, "court", by_year)
    f19["pca_share"] = round(sum(1 for d in decisions.values() if d["is_pca"]) / max(1, len(decisions)), 3)
    f19["argued_share"] = round(len(judged) / max(1, len(decisions)), 3)
    f19["argued"] = appeals_row([r["disposition"] for r in judged], "court")
    court_fields["F19"], court_prov["F19"] = f19, prov("flcourts opinion API + youtube", "argued subset from the 2DCA/6DCA YouTube clips")
    court_fields["F12"], court_prov["F12"] = named_shares(all_d), prov("flcourts opinion API")
    days = [days_between(r["upload_date"], r["decided_date"]) for r in judged]
    f13 = duration(days, "oral_argument", "decision")
    if f13:
        court_fields["F13"], court_prov["F13"] = f13, prov("youtube upload_date → flcourts decided_date")
    f17 = milestone_forecast(days)
    if f17:
        court_fields["F17"], court_prov["F17"] = f17, prov("empirical quantiles; no model")
    table, base = fit_calibration(rows)
    court_fields["F22"], court_prov["F22"] = decision_tree(table, base, len(judged)), prov("fit on typesafe/jev-1.13 panel outputs vs flcourts dispositions", "jev role score_rule_fit is downstream; nothing here calls a model")
    court_fields["F26"] = {"model": "calibration_table", "base_rate": base, "bins": table, "abstain_rule": f"n<{CAL_MIN_N} or |p-base|<{CAL_MIN_LIFT}",
                           "vendor_claims": "Pre/Dicta '85%' is their claim; Kingsfield reports bin rates with n"}
    court_prov["F26"] = prov("calibration of jev ruling_lean + skepticism_gap against flcourts dispositions")
    court_fields["F25"], court_prov["F25"] = [condorcet_result(3, 0.7), banzhaf_result([1, 1, 1], 2)], prov("pure math; illustrative parameters")
    (out / "court.json").write_text(json.dumps(snapshot("court", ch, court_fields, court_prov), indent=1, ensure_ascii=False))

    # ---- per-case F26 cards
    with (out / "cases.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            card = probability_card(r, table, base)
            f.write(json.dumps({"video_id": r["video_id"], "case_number": r["case_number"], "case_name": r["case_name"],
                                "actual_disposition": r["disposition"], "F26": card}, ensure_ascii=False) + "\n")

    # ---- appellate judges (panel membership; bench-level signals, not per-judge attribution)
    jrows: dict[str, list[dict]] = defaultdict(list)
    for r in judged:
        for j in r["panel_judges"]:
            jrows[j].append(r)
    n_judges = 0
    for j, rs in jrows.items():
        if len(rs) < FLOOR_N:
            continue
        fields = {"F19": appeals_row([r["disposition"] for r in rs], "appellate_judge_panels")}
        fields["F19"]["note"] = "cases argued on video where this judge sat; reversal is a panel outcome, not an individual vote"
        fields["F12"] = named_shares([r["disposition"] for r in rs])
        d13 = duration([days_between(r["upload_date"], r["decided_date"]) for r in rs], "oral_argument", "decision")
        if d13:
            fields["F13"] = d13
        gaps = [r["skepticism_gap"] for r in rs if r["skepticism_gap"] is not None]
        fields["F22"] = {"target": "affirm", "fit_on": "panel-level skepticism gap on this judge's panels", "n": len(gaps),
                         "root": {"leaf": True, "n": len(gaps), "p_affirm": None, "label": "see court F22"},
                         "rules_text": [f"share of panels with gap>=+1: {sum(1 for g in gaps if g >= 1) / max(1, len(gaps)):.2f}",
                                        f"share with gap<=-1: {sum(1 for g in gaps if g <= -1) / max(1, len(gaps)):.2f}",
                                        f"authored: {sum(1 for r in rs if r['author'] == j)} of {len(rs)}"]}
        p = {k: prov("flcourts opinion PDF (panel) + youtube + jev panel") for k in fields}
        (out / "judges" / f"{judge_id(j)}.json").write_text(json.dumps(snapshot(judge_id(j), ch, fields, p), indent=1, ensure_ascii=False))
        n_judges += 1

    # ---- trial judges: appellate trail
    trows: dict[str, list[dict]] = defaultdict(list)
    for r in judged:
        if r["trial_judge"]:
            trows[r["trial_judge"]].append(r)
    n_trial = 0
    for tj, rs in trows.items():
        if len(rs) < 3:
            continue
        f19t = appeals_row([r["disposition"] for r in rs], "trial_judge_trail")
        f19t["county"] = Counter(r["county"] for r in rs if r["county"]).most_common(1)[0][0] if any(r["county"] for r in rs) else None
        f19t["note"] = "argued appeals only (a selected, harder subset); n is small — read the CI, not the point"
        f19t["cases"] = [r["case_number"] for r in rs]
        fields = {"F19": f19t}
        p = {"F19": prov("flcourts opinion PDF (trial judge, disposition)")}
        (out / "trial_judges" / f"{judge_id(tj)}.json").write_text(json.dumps(snapshot(judge_id(tj), ch, fields, p), indent=1, ensure_ascii=False))
        n_trial += 1

    # ---- counsel dossier
    dossier = counsel_rows(judged, ch)
    (out / "counsel.json").write_text(json.dumps({"F21": dossier, "F29": dossier["rows"], "provenance": prov("flcourts opinion PDF (counsel) + jev panel")}, indent=1, ensure_ascii=False))

    # ---- coverage
    cat = load_catalog()
    cov = {}
    for fct in cat["factual"]:
        fid = fct["id"]
        ent = []
        if fid in court_fields: ent.append("court")
        if fid in ("F12", "F13", "F19", "F22") and n_judges: ent.append(f"appellate_judges({n_judges})")
        if fid == "F19" and n_trial: ent.append(f"trial_judges({n_trial})")
        if fid in ("F21", "F29") and dossier["rows"]: ent.append(f"counsel({len(dossier['rows'])})")
        if fid == "F26": ent.append(f"cases({len(rows)})")
        cov[fid] = {"name": fct["name"], "populated": bool(ent), "entities": ent, "jev_role": fct["jev"]["role"],
                    "status": "populated" if ent else ("needs_trial_dockets" if fct["top"] == "T1" or fid in ("F16", "F17", "F18", "F20", "F27") else "needs_source")}
    (out / "coverage.json").write_text(json.dumps(cov, indent=1))
    lines = [f"# Coverage — {ch} ({NOW[:10]})", "", "| Fact | Name | Status | Entities | Jev role |", "|---|---|---|---|---|"]
    for fid, c in cov.items():
        lines.append(f"| {fid} | {c['name']} | {c['status']} | {', '.join(c['entities']) or '—'} | {c['jev_role']} |")
    pop = sum(1 for c in cov.values() if c["populated"])
    lines += ["", f"**{pop} of 29 facts populated** from the oral-argument pipeline. The rest need trial-court dockets (T1) or a source not yet integrated (see judicial-intel-analytics/DATA-SOURCES.md)."]
    (ROOT / "taxonomy" / f"COVERAGE-{ch}.md").write_text("\n".join(lines) + "\n")

    print(f"wrote {out}: court.json, {n_judges} appellate judges, {n_trial} trial judges, counsel rows {len(dossier['rows'])}, {len(rows)} case cards")
    print(f"coverage: {pop}/29 facts populated → taxonomy/COVERAGE-{ch}.md")
    print("F22 rules:"); [print("   ", t) for t in court_fields["F22"]["rules_text"]]


if __name__ == "__main__":
    main()
