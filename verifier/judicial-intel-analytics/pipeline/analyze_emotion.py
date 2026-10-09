#!/usr/bin/env python3
"""
Join vocal emotion (modal_emotion.py) and transcript emotion (run_oa_emotion.py) to the
final orders and test whether emotion predicts affirm vs reverse/mixed.

Voice features are built so each judge is compared with themself: every bench turn is
z-scored within its own speaker label in its own video, then averaged separately over
the appellant's argument and the appellee's argument. "bench_*_diff" = appellant phase
minus appellee phase. Counsel features are raw means (each counsel speaks in one phase).

Tests, outcome = reversed or mixed (1) vs affirmed (0), decided cases only:
  1. AUC per feature with a bootstrap 95% interval (0.5 = no signal)
  2. the same inside the gap = 0 cases, where the skepticism gap says nothing
  3. repeated 5-fold cross-validated logistic regression: gap alone vs gap + emotion
Needs numpy only.

Output: data/<channel>/panel/emotion_features.csv, emotion_report.json
"""
import csv
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import channel_dir  # noqa: E402

CH = sys.argv[1] if len(sys.argv) > 1 else "fl_2dca"
BASE = channel_dir(CH)
RNG = np.random.default_rng(7)


def wmean(xs, ws):
    xs, ws = np.array(xs, float), np.array(ws, float)
    return float(np.sum(xs * ws) / np.sum(ws)) if len(xs) and np.sum(ws) > 0 else None


def voice_features(vid):
    p = os.path.join(BASE, "emotion", f"{vid}.json")
    if not os.path.exists(p):
        return None
    emo = {t["i"]: t for t in json.load(open(p))["turns"]}
    doc = json.load(open(os.path.join(BASE, "transcripts_diar", f"{vid}.turns.json")))
    turns = [dict(t, **emo[t["i"]]) for t in doc["turns"] if t["i"] in emo]
    f = {}
    dims = ["a", "d", "v", "rms_db", "f0_med", "f0_iqr"]
    # z-score bench turns within each speaker label
    bench = [t for t in turns if t["role"] == "BENCH"]
    by_spk = {}
    for t in bench:
        by_spk.setdefault(t["speaker"], []).append(t)
    for spk, ts in by_spk.items():
        for k in dims:
            vals = np.array([t[k] for t in ts if t.get(k) is not None], float)
            mu, sd = (vals.mean(), vals.std()) if len(vals) > 2 else (0, 0)
            for t in ts:
                t["z_" + k] = (t[k] - mu) / sd if sd > 0 and t.get(k) is not None else None
    for k in dims:
        ph = {}
        for seg in ("APPELLANT_ARG", "APPELLEE_ARG"):
            ts = [t for t in bench if t["segment"] == seg and t.get("z_" + k) is not None]
            ph[seg] = wmean([t["z_" + k] for t in ts], [t["sec"] for t in ts])
        if None not in ph.values():
            f[f"bench_{k}_diff"] = ph["APPELLANT_ARG"] - ph["APPELLEE_ARG"]
    for role, tag in (("APPELLANT_COUNSEL", "aplt"), ("APPELLEE_COUNSEL", "aple")):
        ts = [t for t in turns if t["role"] == role]
        for k in ("a", "d", "v"):
            f[f"{tag}_counsel_{k}"] = wmean([t[k] for t in ts], [t["sec"] for t in ts])
    for k in ("a", "d", "v"):
        if f.get(f"aplt_counsel_{k}") is not None and f.get(f"aple_counsel_{k}") is not None:
            f[f"counsel_{k}_diff"] = f[f"aplt_counsel_{k}"] - f[f"aple_counsel_{k}"]
    # how much of each side's argument time the bench took (all turns, not only scored ones)
    share = {}
    for seg in ("APPELLANT_ARG", "APPELLEE_ARG"):
        ts = [t for t in doc["turns"] if t["segment"] == seg]
        tot = sum(t["end"] - t["start"] for t in ts)
        share[seg] = sum(t["end"] - t["start"] for t in ts if t["role"] == "BENCH") / tot if tot > 0 else None
    if None not in share.values():
        f["bench_talk_share_diff"] = share["APPELLANT_ARG"] - share["APPELLEE_ARG"]
    return f


def auc(x, y):
    """P(score of a reversed/mixed case > score of an affirmed case); ties count half."""
    x, y = np.asarray(x, float), np.asarray(y, int)
    pos, neg = x[y == 1], x[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return None
    gt = (pos[:, None] > neg[None, :]).mean()
    eq = (pos[:, None] == neg[None, :]).mean()
    return float(gt + 0.5 * eq)


def auc_ci(x, y, B=2000):
    x, y = np.asarray(x, float), np.asarray(y, int)
    bs = []
    for _ in range(B):
        idx = RNG.integers(0, len(x), len(x))
        a = auc(x[idx], y[idx])
        if a is not None:
            bs.append(a)
    return [round(float(np.percentile(bs, 2.5)), 3), round(float(np.percentile(bs, 97.5)), 3)]


def logit_fit(X, y, l2=1.0, iters=3000, lr=0.1):
    w = np.zeros(X.shape[1]); b = 0.0
    for _ in range(iters):
        p = 1 / (1 + np.exp(-(X @ w + b)))
        g = X.T @ (p - y) / len(y) + l2 * w / len(y)
        w -= lr * g; b -= lr * float(np.mean(p - y))
    return w, b


def cv_auc(X, y, reps=50, k=5):
    out = []
    n = len(y)
    for _ in range(reps):
        perm = RNG.permutation(n); folds = np.array_split(perm, k)
        pred = np.zeros(n)
        for fo in folds:
            tr = np.setdiff1d(perm, fo)
            mu, sd = X[tr].mean(0), X[tr].std(0) + 1e-9
            w, b = logit_fit((X[tr] - mu) / sd, y[tr])
            pred[fo] = 1 / (1 + np.exp(-(((X[fo] - mu) / sd) @ w + b)))
        out.append(auc(pred, y))
    return round(float(np.median(out)), 3), [round(float(np.percentile(out, 5)), 3), round(float(np.percentile(out, 95)), 3)]


def main():
    res = {r["video_id"]: r for r in csv.DictReader(open(os.path.join(BASE, "panel", "oa_results.diar.csv")))}
    txt = {}
    p = os.path.join(BASE, "panel", "oa_emotion.diar.jsonl")
    if os.path.exists(p):
        for l in open(p):
            r = json.loads(l)
            if "error" not in r and "_gated_out" not in r:
                txt[r["video_id"]] = r
    rows = []
    for vid, r in res.items():
        if r.get("disposition") not in ("affirm", "reverse", "mixed") or r.get("skepticism_gap") in ("", None):
            continue
        row = {"video_id": vid, "disposition": r["disposition"], "y_not_affirmed": int(r["disposition"] != "affirm"),
               "skepticism_gap": float(r["skepticism_gap"])}
        vf = voice_features(vid)
        if vf:
            row.update(vf)
        t = txt.get(vid)
        if t:
            for side in ("appellant", "appellee"):
                m = t.get(f"bench_tone_toward_{side}__modal")
                row[f"txt_bench_tone_{side}"] = float(m) if m not in (None, "") else None
                m = t.get(f"{side}_counsel_composure__modal")
                row[f"txt_{side}_composure"] = float(m) if m not in (None, "") else None
                for q in (f"bench_sympathy_for_{side}_party", f"bench_condemns_{side}_conduct", f"bench_humor_with_{side}_counsel"):
                    row["txt_" + q] = t.get(q)
            if row.get("txt_bench_tone_appellant") is not None and row.get("txt_bench_tone_appellee") is not None:
                row["txt_bench_tone_diff"] = row["txt_bench_tone_appellant"] - row["txt_bench_tone_appellee"]
        rows.append(row)
    cols = sorted({k for r in rows for k in r})
    with open(os.path.join(BASE, "panel", "emotion_features.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)

    feats = [c for c in cols if c not in ("video_id", "disposition", "y_not_affirmed")]
    report = {"n_decided": len(rows), "n_with_voice": sum("bench_a_diff" in r for r in rows),
              "n_with_text": sum("txt_bench_tone_diff" in r for r in rows),
              "not_affirmed": sum(r["y_not_affirmed"] for r in rows), "features": {}}
    for sub, name in ((rows, "all"), ([r for r in rows if r["skepticism_gap"] == 0], "gap0")):
        for c in feats:
            xs = [(r[c], r["y_not_affirmed"]) for r in sub if r.get(c) not in (None, "")]
            if len(xs) < 30 or len({y for _, y in xs}) < 2:
                continue
            x = np.array([a for a, _ in xs], float); y = np.array([b for _, b in xs], int)
            a = auc(x, y)
            report["features"].setdefault(c, {})[name] = {
                "n": len(xs), "auc": round(a, 3), "ci95": auc_ci(x, y),
                "mean_affirmed": round(float(x[y == 0].mean()), 3), "mean_not_affirmed": round(float(x[y == 1].mean()), 3)}
    # cross-validated: gap alone vs gap + emotion (complete cases only)
    voice = ["bench_a_diff", "bench_v_diff", "bench_d_diff", "bench_rms_db_diff", "bench_f0_iqr_diff", "bench_talk_share_diff"]
    text = ["txt_bench_tone_diff"]
    sets = {"gap": ["skepticism_gap"], "gap+voice": ["skepticism_gap"] + voice,
            "gap+text": ["skepticism_gap"] + text, "gap+voice+text": ["skepticism_gap"] + voice + text,
            "voice only": voice}
    need = sorted(set(sum(sets.values(), [])))
    cc = [r for r in rows if all(r.get(k) not in (None, "") for k in need)]
    report["cv_n"] = len(cc)
    if len(cc) >= 60:
        y = np.array([r["y_not_affirmed"] for r in cc], int)
        report["cv_auc_median_[p5,p95]"] = {k: cv_auc(np.array([[float(r[c]) for c in v] for r in cc]), y) for k, v in sets.items()}
    json.dump(report, open(os.path.join(BASE, "panel", "emotion_report.json"), "w"), indent=1)

    print(f"decided {report['n_decided']} | with voice {report['n_with_voice']} | with text {report['n_with_text']} | not affirmed {report['not_affirmed']}")
    print("AUC (0.5 = no signal; >0.5 = higher value goes with reversal/mixed). 95% CI.")
    ranked = sorted(report["features"].items(), key=lambda kv: -abs((kv[1].get("all") or {"auc": .5})["auc"] - .5))
    for c, d in ranked:
        a = d.get("all"); g = d.get("gap0")
        s = f"  {c:36s} all: {a['auc']:.3f} {a['ci95']} n={a['n']}" if a else f"  {c:36s}"
        if g:
            s += f" | gap0: {g['auc']:.3f} {g['ci95']} n={g['n']}"
        print(s)
    if "cv_auc_median_[p5,p95]" in report:
        print(f"cross-validated AUC, n={report['cv_n']}:")
        for k, v in report["cv_auc_median_[p5,p95]"].items():
            print(f"  {k:16s} {v[0]}  {v[1]}")


if __name__ == "__main__":
    main()
