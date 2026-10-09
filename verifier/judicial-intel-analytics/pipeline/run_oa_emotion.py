#!/usr/bin/env python3
"""
Emotion questions on the speaker-labelled transcripts, with TypeSafe Jev via OpenRouter.
Same state, provider and plumbing as run_oa_panel.py (imported, not copied), and the same
rules: one proposition per question, every score level spelled out, nothing under test
(case number, date, disposition) in the state. The outcome is joined back only in
analyze_emotion.py.

    python3 pipeline/run_oa_emotion.py --channel fl_2dca --limit 3     # check
    python3 pipeline/run_oa_emotion.py --channel fl_2dca               # all

Output: data/<channel>/panel/oa_emotion.diar.jsonl (append-only, resumable)
        data/<channel>/panel/raw.emotion/<id>.json (full response)
"""
import argparse
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import channel_dir  # noqa: E402
from run_oa_panel import PROVIDERS, PRICE_PER_M_INPUT, MIN_WORDS, build_state, call_jev, flatten  # noqa: E402

TONE = [
    "Warm: judges are friendly, encouraging, or appreciative toward this side's counsel.",
    "Calm: judges are even and businesslike toward this side's counsel, with no emotional charge.",
    "Tense: judges sound pressed or uneasy with this side's counsel; exchanges are clipped or insistent.",
    "Irritated: judges show annoyance or impatience with this side's counsel.",
    "Angry: judges are openly exasperated, sharp, or scolding toward this side's counsel.",
]
COMPOSURE = [
    "Composed: counsel answers steadily and stays on point under questioning.",
    "Strained: counsel hesitates, repeats, or struggles to answer, but stays respectful and on point.",
    "Flustered: counsel loses the thread, backtracks, or gives confused answers under questioning.",
    "Combative: counsel argues with or talks over the judges, or pushes back in a heated way.",
]

EMOTION_QUESTIONS = {
    "transcript_sufficient": {
        "type": "noul",
        "instructions": ("Does `transcript` contain enough of an appellate oral argument — questions from judges "
                         "and answers from counsel about the merits — to judge how the bench is responding? "
                         "Answer false if it is mostly ceremony, announcements, silence markers, or garbled text."),
    },
    "bench_tone_toward_appellant": {
        "type": "score",
        "instructions": "What is the emotional tone of the judges toward the APPELLANT's counsel in `transcript`? Judge tone only, not whether the judges agree with the argument.",
        "criteria": TONE,
    },
    "bench_tone_toward_appellee": {
        "type": "score",
        "instructions": "What is the emotional tone of the judges toward the APPELLEE's counsel in `transcript`? Judge tone only, not whether the judges agree with the argument.",
        "criteria": TONE,
    },
    "bench_sympathy_for_appellant_party": {
        "type": "noul",
        "instructions": "Does a judge in `transcript` express sympathy or concern for the APPELLANT as a person or party — their hardship, situation, or treatment — as opposed to their legal argument?",
    },
    "bench_sympathy_for_appellee_party": {
        "type": "noul",
        "instructions": "Does a judge in `transcript` express sympathy or concern for the APPELLEE as a person or party — their hardship, situation, or treatment — as opposed to their legal argument?",
    },
    "bench_condemns_appellant_conduct": {
        "type": "noul",
        "instructions": "Does a judge in `transcript` describe the APPELLANT party's conduct in morally charged terms, such as unfair, troubling, egregious, or bad faith?",
    },
    "bench_condemns_appellee_conduct": {
        "type": "noul",
        "instructions": "Does a judge in `transcript` describe the APPELLEE party's conduct in morally charged terms, such as unfair, troubling, egregious, or bad faith?",
    },
    "bench_humor_with_appellant_counsel": {
        "type": "noul",
        "instructions": "Does a judge in `transcript` joke, laugh, or trade light remarks with the APPELLANT's counsel?",
    },
    "bench_humor_with_appellee_counsel": {
        "type": "noul",
        "instructions": "Does a judge in `transcript` joke, laugh, or trade light remarks with the APPELLEE's counsel?",
    },
    "appellant_counsel_composure": {
        "type": "score",
        "instructions": "How composed is the APPELLANT's counsel in `transcript` when answering the judges?",
        "criteria": COMPOSURE,
    },
    "appellee_counsel_composure": {
        "type": "score",
        "instructions": "How composed is the APPELLEE's counsel in `transcript` when answering the judges?",
        "criteria": COMPOSURE,
    },
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="fl_2dca")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    prov = PROVIDERS["openrouter"]
    key = os.environ.get(prov["env"])
    if not key:
        raise SystemExit(f"{prov['env']} not set")
    base = channel_dir(a.channel)
    tr_dir = os.path.join(base, "transcripts_diar")
    out = os.path.join(base, "panel", "oa_emotion.diar.jsonl")
    raw = os.path.join(base, "panel", "raw.emotion")
    os.makedirs(raw, exist_ok=True)
    done = set()
    if os.path.exists(out):
        for l in open(out):
            try:
                r = json.loads(l)
                if "error" not in r:
                    done.add(r["video_id"])
            except Exception:
                pass
    vids = sorted(f[:-len(".turns.json")] for f in os.listdir(tr_dir) if f.endswith(".turns.json"))
    todo = [v for v in vids if v not in done]
    if a.limit:
        todo = todo[:a.limit]
    print(f"{len(vids)} transcripts, {len(done)} already scored, {len(todo)} to run")
    lock = threading.Lock()
    tok = [0]
    sess = requests.Session()

    def one(v):
        doc = json.load(open(os.path.join(tr_dir, f"{v}.turns.json")))
        rec = {"video_id": v}
        if (doc.get("n_words") or 0) < MIN_WORDS:
            rec["_gated_out"] = "too few words"
            return rec
        state, est, trunc = build_state(doc)
        resp = call_jev(sess, state, EMOTION_QUESTIONS, key, prov["url"], prov["model"])
        rec.update({"_est_tokens": est, "_truncated": trunc})
        if "error" in resp:
            rec["error"] = resp["error"]
            return rec
        json.dump({"questions": EMOTION_QUESTIONS, "response": resp}, open(os.path.join(raw, f"{v}.json"), "w"), indent=1)
        rec.update(flatten(resp.get("answers"), EMOTION_QUESTIONS))
        with lock:
            tok[0] += est
        return rec

    n = err = 0
    with ThreadPoolExecutor(a.workers) as ex, open(out, "a") as f:
        for fut in as_completed([ex.submit(one, v) for v in todo]):
            r = fut.result()
            f.write(json.dumps(r) + "\n"); f.flush()
            n += 1; err += "error" in r
            if n % 25 == 0 or n == len(todo):
                print(f"  {n}/{len(todo)} done, {err} errors, ~{tok[0]:,} input tokens (~${tok[0]/1e6*PRICE_PER_M_INPUT:.4f})", flush=True)
    print("done")


if __name__ == "__main__":
    main()
