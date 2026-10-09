#!/usr/bin/env python3
"""
Same Jev questions, two transcripts of the same arguments: caption-only (">>" roles)
vs diarized (Nemotron speakers). Offline; reads the two panel CSVs.

    python3 pipeline/compare_diar_panel.py --channel fl_2dca

With ~35 cases this is a consistency check, not a significance test (see the n on every line).
"""
import argparse
import csv
import json
import os
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(p):
    out = {}
    for r in csv.DictReader(open(p, encoding="utf-8")):
        if r.get("error") or r.get("_gated_out"):
            continue
        out[r["video_id"]] = r
    return out


def i(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="fl_2dca")
    a = ap.parse_args()
    pd = os.path.join(ROOT, "data", a.channel, "panel")
    old, new = load(os.path.join(pd, "oa_results.csv")), load(os.path.join(pd, "oa_results.diar.csv"))
    ids = sorted(set(old) & set(new))
    rep = {"n_both": len(ids)}
    for side in ("appellant", "appellee"):
        k = f"bench_skepticism_toward_{side}__modal"
        pairs = [(i(old[v].get(k)), i(new[v].get(k))) for v in ids]
        pairs = [p for p in pairs if None not in p]
        rep[f"{side}_modal_same"] = f"{sum(1 for x, y in pairs if x == y)}/{len(pairs)}"
        rep[f"{side}_modal_within1"] = f"{sum(1 for x, y in pairs if abs(x - y) <= 1)}/{len(pairs)}"
        rep[f"{side}_bimodal_old_vs_new"] = (f"{sum(old[v].get(k.replace('modal', 'bimodal')) == 'True' for v in ids)} vs "
                                            f"{sum(new[v].get(k.replace('modal', 'bimodal')) == 'True' for v in ids)}")
    rep["ruling_lean_same"] = f"{sum(1 for v in ids if old[v].get('ruling_lean') == new[v].get('ruling_lean'))}/{len(ids)}"
    for name, src in (("old", old), ("new", new)):
        judged = [v for v in ids if src[v].get("ruling_lean_correct") in ("True", "False")]
        acc = sum(src[v]["ruling_lean_correct"] == "True" for v in judged)
        hi = [v for v in judged if (f(src[v].get("ruling_lean__confidence")) or 0) >= 0.7]
        rep[f"{name}_ruling_lean_acc"] = f"{acc}/{len(judged)}"
        rep[f"{name}_ruling_lean_acc_conf>=0.7"] = f"{sum(src[v]['ruling_lean_correct'] == 'True' for v in hi)}/{len(hi)}"
        gap = {}
        for v in ids:
            g, d = i(src[v].get("skepticism_gap")), src[v].get("disposition")
            if g is None or d not in ("affirm", "reverse", "mixed"):
                continue
            g = max(-1, min(1, g))
            gap.setdefault(g, []).append(d == "affirm")
        rep[f"{name}_affirm_by_gap"] = {f"{g:+d}": f"{sum(x)}/{len(x)}" for g, x in sorted(gap.items())}
    base = Counter(new[v].get("disposition") for v in ids)
    rep["dispositions"] = dict(base)
    out = os.path.join(pd, "compare_diar.json")
    json.dump(rep, open(out, "w"), indent=1)
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
