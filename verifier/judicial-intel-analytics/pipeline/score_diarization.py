#!/usr/bin/env python3
"""
Score Nemotron diarization against YouTube's own speaker-change marks (">>").

Offline, no network. Only meaningful on videos whose captions carry ">>" marks
(cohorts/marked.csv). The marks are not perfect ground truth — captions both drop
and invent them — so treat the score as agreement, not accuracy.

    python3 pipeline/score_diarization.py --channel fl_2dca [--tol 1.5] [--closing 0.5]

Output: data/<channel>/diarization/_score.json and a printed summary.
"""
import argparse
import glob
import json
import os
import statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def change_points(segs, closing):
    """Speaker-change times after merging same-speaker gaps shorter than `closing` s."""
    merged = []
    for a, b, s in sorted(segs, key=lambda x: (x[0], x[1])):
        if merged and merged[-1][2] == s and a - merged[-1][1] < closing:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b, s])
    cps, prev = [], None
    for a, b, s in merged:
        if prev is not None and s != prev:
            cps.append(a)
        prev = s
    return cps, merged


def match(ref, hyp, tol):
    used, hits, offs = set(), 0, []
    for r in ref:
        best = None
        for j, h in enumerate(hyp):
            if j in used or abs(h - r) > tol:
                continue
            if best is None or abs(h - r) < abs(hyp[best] - r):
                best = j
        if best is not None:
            used.add(best); hits += 1; offs.append(hyp[best] - r)
    p = hits / len(hyp) if hyp else 0.0
    rc = hits / len(ref) if ref else 0.0
    f = 2 * p * rc / (p + rc) if p + rc else 0.0
    return p, rc, f, offs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="fl_2dca")
    ap.add_argument("--tol", type=float, default=1.5, help="seconds either side counted as a match")
    ap.add_argument("--closing", type=float, default=0.5, help="merge same-speaker gaps shorter than this")
    a = ap.parse_args()
    base = os.path.join(ROOT, "data", a.channel)
    rows = []
    for f in sorted(glob.glob(os.path.join(base, "diarization", "*.json"))):
        if os.path.basename(f).startswith("_"):
            continue
        d = json.load(open(f))
        tp = os.path.join(base, "transcripts", f"{d['video_id']}.turns.json")
        if not os.path.exists(tp):
            continue
        t = json.load(open(tp))
        ref = [x["start"] for x in t["turns"][1:]]          # each ">>" split starts a turn
        hyp, merged = change_points(d["segments"], a.closing)
        if len(ref) < 10:                                     # no usable ">>" marks: can't score
            rows.append({"video_id": d["video_id"], "scorable": False, "n_speakers": d["n_speakers"]})
            continue
        p, r, f1, offs = match(ref, hyp, a.tol)
        rows.append({"video_id": d["video_id"], "scorable": True, "n_speakers": d["n_speakers"],
                     "ref_changes": len(ref), "hyp_changes": len(hyp), "precision": round(p, 3),
                     "recall": round(r, 3), "f1": round(f1, 3),
                     "median_offset_s": round(st.median(offs), 2) if offs else None,
                     "minutes": round(d["duration_sec"] / 60, 1), "gpu_sec": d.get("gpu_sec")})
    sc = [x for x in rows if x["scorable"]]
    summ = {"n_files": len(rows), "n_scorable": len(sc), "tol_s": a.tol, "closing_s": a.closing}
    if sc:
        for k in ("precision", "recall", "f1"):
            summ[f"median_{k}"] = round(st.median(x[k] for x in sc), 3)
        summ["speakers_found"] = dict(sorted({n: sum(1 for x in rows if x["n_speakers"] == n)
                                              for n in {x["n_speakers"] for x in rows}}.items()))
        summ["total_audio_min"] = round(sum(x["minutes"] for x in sc), 1)
        summ["total_model_sec"] = round(sum(x["gpu_sec"] or 0 for x in sc), 1)
    json.dump({"summary": summ, "rows": rows}, open(os.path.join(base, "diarization", "_score.json"), "w"), indent=1)
    print(json.dumps(summ, indent=1))
    worst = sorted(sc, key=lambda x: x["f1"])[:5]
    if worst:
        print("lowest agreement:", ", ".join(f"{x['video_id']} f1={x['f1']}" for x in worst))


if __name__ == "__main__":
    main()
