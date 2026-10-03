#!/usr/bin/env python3
"""Chronological holdout for the emotion models: fit on the earlier half of decided cases
(by decision date), score the later half once. Same feature sets as analyze_emotion.py,
fixed before looking at the holdout. Output: data/<channel>/panel/holdout_emotion.json"""
import csv, json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import channel_dir  # noqa: E402
from analyze_emotion import auc, logit_fit  # noqa: E402

CH = sys.argv[1] if len(sys.argv) > 1 else "fl_2dca"
B = channel_dir(CH)
dates = {r["video_id"]: (r.get("decided_date") or "9999") for r in csv.DictReader(open(os.path.join(B, "panel", "oa_results.diar.csv")))}
rows = list(csv.DictReader(open(os.path.join(B, "panel", "emotion_features.csv"))))
voice = ["bench_a_diff", "bench_v_diff", "bench_d_diff", "bench_rms_db_diff", "bench_f0_iqr_diff", "bench_talk_share_diff"]
text = ["txt_bench_tone_diff"]
SETS = {"gap": ["skepticism_gap"], "gap+voice": ["skepticism_gap"] + voice, "gap+text": ["skepticism_gap"] + text,
        "gap+voice+text": ["skepticism_gap"] + voice + text, "voice only": voice, "text only": text}
rng = np.random.default_rng(11)


def run(cases, feats):
    cases = sorted(cases, key=lambda r: dates.get(r["video_id"], "9999"))
    h = len(cases) // 2
    tr, te = cases[:h], cases[h:]
    X = lambda S: np.array([[float(r[c]) for c in feats] for r in S])
    y = lambda S: np.array([int(r["y_not_affirmed"]) for r in S])
    mu, sd = X(tr).mean(0), X(tr).std(0) + 1e-9
    w, b = logit_fit((X(tr) - mu) / sd, y(tr))
    p = 1 / (1 + np.exp(-(((X(te) - mu) / sd) @ w + b)))
    yt = y(te)
    boot = []
    for _ in range(2000):
        i = rng.integers(0, len(yt), len(yt))
        a = auc(p[i], yt[i])
        if a is not None:
            boot.append(a)
    # accuracy at the cut that makes as many "not affirmed" calls in the test half as the train half's rate
    k = int(round(y(tr).mean() * len(yt)))
    cut = np.sort(p)[::-1][k - 1] if k > 0 else 1.1
    pred = (p >= cut).astype(int)
    return {"train_n": len(tr), "test_n": len(te), "test_dates": [dates[te[0]["video_id"]], dates[te[-1]["video_id"]]],
            "test_auc": round(auc(p, yt), 3), "test_auc_ci95": [round(float(np.percentile(boot, 2.5)), 3), round(float(np.percentile(boot, 97.5)), 3)],
            "test_not_affirmed": int(yt.sum()), "flagged": int(pred.sum()), "flagged_correct": int((pred & yt).sum()),
            "test_acc": round(float((pred == yt).mean()), 3), "test_always_affirm": round(float(1 - yt.mean()), 3)}


need = sorted(set(sum(SETS.values(), [])))
common = [r for r in rows if all(r.get(c) not in (None, "") for c in need)]
alltext = [r for r in rows if all(r.get(c) not in (None, "") for c in ["skepticism_gap"] + text)]
out = {"same_cases_n": len(common), "same_cases": {k: run(common, v) for k, v in SETS.items()},
       "text_all_cases_n": len(alltext), "text_all_cases": {k: run(alltext, SETS[k]) for k in ("gap", "gap+text", "text only")}}
json.dump(out, open(os.path.join(B, "panel", "holdout_emotion.json"), "w"), indent=1)
for grp in ("same_cases", "text_all_cases"):
    print(f"== {grp} (n={out[grp + '_n']})")
    for k, r in out[grp].items():
        print(f"  {k:15s} test AUC {r['test_auc']} {r['test_auc_ci95']} | acc {r['test_acc']} vs always-affirm {r['test_always_affirm']} | flagged {r['flagged']}, right {r['flagged_correct']} of {r['test_not_affirmed']} | test {r['test_n']} cases {r['test_dates'][0]}..{r['test_dates'][1]}")
