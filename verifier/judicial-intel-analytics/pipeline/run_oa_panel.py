#!/usr/bin/env python3
"""
Score every oral-argument transcript with TypeSafe's Jev decision model.
Resumable, concurrent, cached. Structure follows ~/Downloads/run_panel.py.

    export OPENROUTER_API_KEY=sk-or-...        # never written to disk by this script
    python3 pipeline/run_oa_panel.py --channel fl_2dca --limit 10 --dump-raw   # validation
    python3 pipeline/run_oa_panel.py --channel fl_2dca                          # full corpus

Input : data/<channel>/transcripts/<id>.turns.json   (build_transcripts.py)
        data/<channel>/captions/<id>.info.json       (pull_captions.py) — join only
Output: data/<channel>/panel/oa_results.jsonl         one line per video, append-only
        data/<channel>/panel/oa_results.csv           every answer, confidence, level
                                                      probability, joined to metadata
        data/<channel>/panel/raw/<id>.json            full API response (--dump-raw)

Design rules this script enforces (see the panel comments):
  1. one proposition per question                 4. gate on sufficiency, in Python
  2. never average a score — every level is a       first and again in the model
     column, plus modal level and a bimodal flag   5. no counting, no dates in questions
  3. nothing under test goes into state; the       6. state is the labeled transcript
     case number, date, and disposition are           and nothing else
     joined back from metadata after scoring
"""
import argparse
import csv
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import channel_dir, channel_config, parse_case_numbers, format_case_number  # noqa: E402

WORKERS = 12
PRICE_PER_M_INPUT = 0.042
STATE_TOKEN_BUDGET = 28_000       # leave headroom under the ~32k state+question budget
TOKENS_PER_WORD = 1.35            # conservative for courtroom English
MIN_WORDS = 1500                  # python gate: below this there is no argument to judge

# Two ways to reach Jev. Same {model, state, questions} -> {answers} shape.
PROVIDERS = {
    "typesafe": {
        "url": "https://api.typesafe.ai/v1/systemone",
        "model": "jev-latest",
        "env": "TYPESAFE_API_KEY",
    },
    "openrouter": {
        "url": "https://openrouter.ai/api/alpha/decisions",
        "model": "typesafe/jev-1.13",
        "env": "OPENROUTER_API_KEY",
    },
}

# ---------------------------------------------------------------- panel
#
# Every question is one proposition about `transcript`. Scores spell out each
# level. Nothing asks the model to count, compare dates, or know anything that
# is not on the page (what was briefed, who won).

SKEPTICISM_LEVELS = [
    "Receptive: the bench's questions to this side are clarifying or friendly, and judges signal agreement or help counsel develop the argument.",
    "Mildly probing: ordinary testing questions with no sign the bench doubts the position.",
    "Skeptical: judges push back on the position, raise contrary authority or facts, or ask counsel to justify it.",
    "Strongly skeptical: judges reject the position's premises or express doubt it can succeed.",
    "Hostile: judges are dismissive or exasperated, openly say the position fails, or admonish counsel.",
]

OA_QUESTIONS = {
    # ---- gates (evaluated in the same call; rows failing them are dropped downstream)
    "transcript_sufficient": {
        "type": "noul",
        "instructions": (
            "Does `transcript` contain enough of an appellate oral argument — questions from judges "
            "and answers from counsel about the merits — to judge how the bench is responding? "
            "Answer false if it is mostly ceremony, announcements, silence markers, or garbled text."
        ),
    },
    "is_oral_argument": {
        "type": "noul",
        "instructions": "Is `transcript` an oral argument in an appeal, as opposed to a ceremony, induction, speech, or announcement?",
    },
    # ---- bench posture toward each side
    "bench_skepticism_toward_appellant": {
        "type": "score",
        "instructions": "How does the bench treat the APPELLANT's position in `transcript`? Judge the judges' words to and about the appellant's argument, not the strength of the argument itself.",
        "criteria": SKEPTICISM_LEVELS,
    },
    "bench_skepticism_toward_appellee": {
        "type": "score",
        "instructions": "How does the bench treat the APPELLEE's position in `transcript`? Judge the judges' words to and about the appellee's argument, not the strength of the argument itself.",
        "criteria": SKEPTICISM_LEVELS,
    },
    "ruling_lean": {
        "type": "choice",
        "instructions": "From the judges' questions and comments in `transcript` alone, which way does the bench appear to lean?",
        "criteria": {
            "affirm": "The bench appears inclined to affirm the lower court's ruling.",
            "reverse": "The bench appears inclined to reverse or vacate the lower court's ruling, in whole or in part.",
            "mixed_or_unclear": "The bench gives no clear signal, or different judges signal different directions.",
        },
    },
    "panel_disagreement": {
        "type": "noul",
        "instructions": "Do the judges signal disagreement with one another in `transcript` — one judge pushing back on, correcting, or distancing themself from another judge's point?",
    },
    # ---- observable bench behaviors (rephrased to what is on the page)
    "bench_says_issue_unraised": {
        "type": "noul",
        "instructions": "Does a judge in `transcript` say that an issue was not raised, briefed, or preserved by a party?",
    },
    "bench_raises_jurisdiction": {
        "type": "noul",
        "instructions": "Does a judge in `transcript` question whether the court has jurisdiction to hear the appeal or whether the order is appealable?",
    },
    "bench_says_appellant_counsel_not_answering": {
        "type": "noul",
        "instructions": "Does a judge in `transcript` express frustration or impatience that the APPELLANT's counsel is not answering the question that was asked? Ordinary follow-up questions do not count.",
    },
    "bench_says_appellee_counsel_not_answering": {
        "type": "noul",
        "instructions": "Does a judge in `transcript` express frustration or impatience that the APPELLEE's counsel is not answering the question that was asked? Ordinary follow-up questions do not count.",
    },
    "appellant_concedes_point": {
        "type": "noul",
        "instructions": "Does the APPELLANT's counsel in `transcript` concede a point that weakens the appellant's own position? Agreeing with a judge who is helping their side does not count.",
    },
    "appellee_concedes_point": {
        "type": "noul",
        "instructions": "Does the APPELLEE's counsel in `transcript` concede a point that weakens the appellee's own position? Agreeing with a judge who is helping their side does not count.",
    },
    # ---- pro se (split into two propositions)
    "bench_remarks_on_pro_se_status": {
        "type": "noul",
        "instructions": "Does a judge in `transcript` comment on a party being self-represented (pro se), for example noting that a party has no lawyer?",
    },
    "bench_remarks_on_pro_se_filing_quality": {
        "type": "noul",
        "instructions": "Does a judge in `transcript` comment on the quality, clarity, or adequacy of a self-represented party's filings or arguments?",
    },
    # ---- posture toward the trial court
    "bench_posture_toward_trial_court": {
        "type": "choice",
        "instructions": "How does the bench characterize the trial court's handling of the case in `transcript`?",
        "criteria": {
            "deferential": "Judges defend or excuse the trial court's decision, or emphasize its discretion.",
            "neutral": "Judges discuss the trial court's decision without evaluating it.",
            "critical": "Judges criticize the trial court's reasoning, process, or findings.",
            "not_discussed": "The trial court's handling is not discussed.",
        },
    },
}

# ---------------------------------------------------------------- state

def norm_case_number(title: str, prefix: str = "2D"):
    """First case number in the title as a CourtListener docket number."""
    nums = parse_case_numbers(title)
    return format_case_number(prefix, *nums[0]) if nums else None


def fmt_ts(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


ROLE_LABEL = {
    "BENCH": "JUDGE",
    "APPELLANT_COUNSEL": "APPELLANT'S COUNSEL",
    "APPELLEE_COUNSEL": "APPELLEE'S COUNSEL",
    "COUNSEL": "COUNSEL",
}
SEG_LABEL = {
    "OPENING": "--- court opens ---",
    "APPELLANT_ARG": "--- appellant's argument ---",
    "APPELLEE_ARG": "--- appellee's argument ---",
    "REBUTTAL": "--- appellant's rebuttal ---",
    "CLOSING": "--- court closes ---",
}


def build_state(doc: dict) -> tuple:
    """Labeled transcript → (state dict, est_tokens, truncated). Nothing else goes in.

    Trims to the token budget by first dropping the closing, then cutting the
    longest COUNSEL turns to their first 150 words. Bench turns are never cut —
    they carry the signal every question asks about.
    """
    turns = [dict(t) for t in doc["turns"]]
    truncated = False

    def render(ts):
        lines = []
        seg = None
        for t in ts:
            if t["segment"] != seg:
                seg = t["segment"]
                lines.append("")
                lines.append(SEG_LABEL.get(seg, f"--- {seg} ---"))
            lines.append(f"[{fmt_ts(t['start'])}] {ROLE_LABEL.get(t['role'], t['role'])}: {t['text']}")
        return "\n".join(lines).strip()

    def est(ts):
        return int(sum(len(t["text"].split()) for t in ts) * TOKENS_PER_WORD) + 200

    if est(turns) > STATE_TOKEN_BUDGET:
        truncated = True
        turns = [t for t in turns if t["segment"] != "CLOSING"]
    while est(turns) > STATE_TOKEN_BUDGET:
        counsel = sorted(
            (i for i, t in enumerate(turns) if t["role"] != "BENCH"),
            key=lambda i: -len(turns[i]["text"].split()),
        )
        if not counsel or len(turns[counsel[0]]["text"].split()) <= 150:
            break
        i = counsel[0]
        turns[i]["text"] = " ".join(turns[i]["text"].split()[:150]) + " [...]"

    state = {
        "note": (
            "Auto-captioned transcript of an appellate oral argument. Speaker roles were inferred "
            "automatically and may be wrong for some turns. Words may be mis-transcribed."
        ),
        "transcript": render(turns),
    }
    return state, est(turns), truncated


# ---------------------------------------------------------------- plumbing

_print_lock = threading.Lock()


def call_jev(session, state, questions, api_key, api_url, model, max_retries=6):
    payload = {"model": model, "state": state, "questions": questions}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    delay = 1.0
    for attempt in range(max_retries):
        try:
            r = session.post(api_url, json=payload, headers=headers, timeout=90)
        except requests.RequestException as e:
            if attempt == max_retries - 1:
                return {"error": f"request failed: {e}"}
            time.sleep(delay)
            delay *= 2
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503, 504, 520, 521, 522, 523, 524, 529):
            time.sleep(delay)
            delay *= 2
            continue
        return {"error": f"HTTP {r.status_code}: {r.text[:400]}"}
    return {"error": "exhausted retries"}


def _level_key(k, criteria):
    """Score probability keys may be '0'..'n', ints, or the level text."""
    ks = str(k)
    if ks.isdigit():
        return int(ks)
    if criteria and ks in criteria:
        return criteria.index(ks)
    return ks


def flatten(answers, questions):
    """Answers → flat columns. Every score level is its own column; the mean is
    never written. A bimodal flag marks rows where the model is split between
    two non-adjacent levels — the modal level, not the score, is reportable there."""
    out = {}
    for key, a in (answers or {}).items():
        t = a.get("type") or questions.get(key, {}).get("type")
        probs = a.get("probabilities") or {}
        if t == "choice":
            out[key] = a.get("choice")
            out[f"{key}__confidence"] = a.get("confidence")
            for opt, p in probs.items():
                out[f"{key}__p_{opt}"] = p
        elif t == "score":
            crit = questions.get(key, {}).get("criteria") or []
            lv = {_level_key(k, crit): v for k, v in probs.items()}
            out[key] = a.get("score")
            out[f"{key}__confidence"] = a.get("confidence")
            for k in sorted(lv, key=lambda x: (isinstance(x, str), x)):
                out[f"{key}__p{k}"] = lv[k]
            out[f"{key}__modal"] = modal_level(lv)
            out[f"{key}__bimodal"] = is_bimodal(lv)
        elif t == "noul":
            out[key] = a.get("noul")
        else:
            out[key] = json.dumps(a)
    return out


def modal_level(probs):
    if not probs:
        return None
    return max(probs.items(), key=lambda kv: kv[1])[0]


def is_bimodal(probs, gap=2, floor=0.20):
    heavy = sorted(k for k, v in probs.items() if isinstance(k, int) and v >= floor)
    if len(heavy) < 2:
        return False
    return (heavy[-1] - heavy[0]) >= gap


def load_meta(cap_dir, vid):
    p = os.path.join(cap_dir, f"{vid}.info.json")
    if not os.path.exists(p):
        return {}
    try:
        return json.load(open(p))
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="fl_2dca")
    ap.add_argument("--limit", type=int, default=0, help="stop after N new rows")
    ap.add_argument("--video", help="single video id")
    ap.add_argument("--workers", type=int, default=WORKERS)
    ap.add_argument("--provider", default="openrouter", choices=sorted(PROVIDERS))
    ap.add_argument("--api-url", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--dump-raw", action="store_true", help="save each full API response")
    ap.add_argument("--rebuild-csv", action="store_true", help="only rebuild the CSV from the JSONL")
    args = ap.parse_args()

    base = channel_dir(args.channel)
    tr_dir = os.path.join(base, "transcripts")
    cap_dir = os.path.join(base, "captions")
    out_dir = os.path.join(base, "panel")
    raw_dir = os.path.join(out_dir, "raw")
    os.makedirs(out_dir, exist_ok=True)
    if args.dump_raw:
        os.makedirs(raw_dir, exist_ok=True)
    jsonl_path = os.path.join(out_dir, "oa_results.jsonl")
    csv_path = os.path.join(out_dir, "oa_results.csv")

    prefix = channel_config(args.channel).get("district_prefix", "2D")
    prov = PROVIDERS[args.provider]
    api_url = args.api_url or prov["url"]
    model = args.model or prov["model"]
    api_key = os.environ.get(prov["env"])
    if not args.rebuild_csv and not api_key:
        sys.exit(f"{prov['env']} is not set. export {prov['env']}=...")

    # ---- gather transcripts
    vids = sorted(n[: -len(".turns.json")] for n in os.listdir(tr_dir) if n.endswith(".turns.json"))
    if args.video:
        vids = [v for v in vids if v == args.video]

    done = set()
    if os.path.exists(jsonl_path):
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    if "error" in rec:
                        done.discard(rec["video_id"])   # transient failures re-run
                    else:
                        done.add(rec["video_id"])
                except Exception:
                    pass

    todo = [v for v in vids if v not in done]
    if args.limit:
        todo = todo[: args.limit]

    if not args.rebuild_csv:
        print(f"provider={args.provider}  url={api_url}  model={model}")
        print(f"{len(vids)} transcripts, {len(done)} already scored, {len(todo)} to run")

    out_lock = threading.Lock()
    counter = {"n": 0, "err": 0, "gated": 0, "tokens": 0}
    session = requests.Session()

    def work(vid):
        doc = json.load(open(os.path.join(tr_dir, f"{vid}.turns.json")))
        g = doc["gate"]
        rec = {
            "video_id": vid,
            "title": doc.get("title"),
            "case_number": norm_case_number(doc.get("title"), prefix),
            # ---- transcript quality columns (never sent to the model)
            "n_words": doc["n_words"],
            "n_turns": doc["n_turns"],
            "has_both_sides": g["has_both_sides"],
            "turns_coarse": g.get("turns_coarse", False),
            "pct_role_guessed": g["pct_role_guessed"],
        }
        # ---- python gate (rule 4): don't pay to score the absence of an argument
        if g["title_is_ceremony"]:
            rec["_gated_out"] = "title_is_ceremony"
            return rec
        if doc["n_words"] < MIN_WORDS:
            rec["_gated_out"] = f"under_{MIN_WORDS}_words"
            return rec

        state, est_tokens, truncated = build_state(doc)
        rec["_est_tokens"] = est_tokens
        rec["_truncated"] = truncated

        resp = call_jev(session, state, OA_QUESTIONS, api_key, api_url, model)
        if "error" in resp:
            rec["error"] = resp["error"]
            return rec
        if args.dump_raw:
            with open(os.path.join(raw_dir, f"{vid}.json"), "w", encoding="utf-8") as f:
                json.dump({"state": state, "questions": OA_QUESTIONS, "response": resp}, f, indent=1, ensure_ascii=False)
        rec.update(flatten(resp.get("answers"), OA_QUESTIONS))
        usage = resp.get("usage") or {}
        rec["_input_tokens"] = usage.get("input_tokens", 0)
        rec["_request_id"] = resp.get("request_id") or resp.get("id")
        rec["_eval_ms"] = resp.get("evaluation_time_ms")
        rec["_model"] = resp.get("model")
        return rec

    if todo and not args.rebuild_csv:
        outf = open(jsonl_path, "a", encoding="utf-8")
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(work, v): v for v in todo}
            for fut in as_completed(futs):
                rec = fut.result()
                with out_lock:
                    outf.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    outf.flush()
                    counter["n"] += 1
                    if "error" in rec:
                        counter["err"] += 1
                    if "_gated_out" in rec:
                        counter["gated"] += 1
                    counter["tokens"] += rec.get("_input_tokens", 0)
                    if counter["n"] % 25 == 0 or counter["n"] == len(todo):
                        with _print_lock:
                            print(
                                f"  {counter['n']}/{len(todo)} done, {counter['err']} errors, "
                                f"{counter['gated']} gated out, {counter['tokens']:,} input tokens "
                                f"(${counter['tokens'] * PRICE_PER_M_INPUT / 1_000_000:.4f}), "
                                f"{int(time.time() - t0)}s", flush=True)
        outf.close()

    # ---- rebuild the joined CSV from everything on disk
    recs = []
    if os.path.exists(jsonl_path):
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                try:
                    recs.append(json.loads(line))
                except Exception:
                    pass
    # latest record per video wins (re-runs append)
    by_vid = {}
    for r in recs:
        by_vid[r["video_id"]] = r
    recs = sorted(by_vid.values(), key=lambda r: r["video_id"])

    dk_dir = os.path.join(base, "dockets")
    DOCKET_COLS = ["case_name", "decided_date", "disposition", "disposition_text", "is_pca", "per_curiam",
                   "author", "panel_judges", "has_dissent", "dissenting_judges", "has_special_concurrence",
                   "trial_judge", "county", "appellant_counsel", "appellee_counsel", "cl_url"]
    for r in recs:
        r["case_number"] = norm_case_number(r.get("title"), prefix)  # recomputed: format may have changed
        m = load_meta(cap_dir, r["video_id"])
        r["upload_date"] = m.get("upload_date")
        r["duration_sec"] = m.get("duration")
        r["view_count"] = m.get("view_count")
        r["url"] = m.get("webpage_url") or f"https://www.youtube.com/watch?v={r['video_id']}"
        # ---- ground truth from enrich_dockets.py, joined AFTER scoring (rule 3)
        dk = {}
        dp = os.path.join(dk_dir, f"{r['video_id']}.json")
        if os.path.exists(dp):
            try:
                dk = json.load(open(dp))
            except Exception:
                dk = {}
        r["decision_found"] = bool(dk.get("found"))
        for c in DOCKET_COLS:
            r[c] = dk.get(c) if dk.get("found") else None
        # ---- composed signals (rule 5: arithmetic lives here, never in a question)
        def _p(k):
            v = r.get(k)
            return float(v) if v not in (None, "") else None
        a3, a4 = _p("bench_skepticism_toward_appellant__p3"), _p("bench_skepticism_toward_appellant__p4")
        e3, e4 = _p("bench_skepticism_toward_appellee__p3"), _p("bench_skepticism_toward_appellee__p4")
        r["appellant_hostile_mass"] = round((a3 or 0) + (a4 or 0), 3) if a3 is not None else None
        r["appellee_hostile_mass"] = round((e3 or 0) + (e4 or 0), 3) if e3 is not None else None
        try:
            r["skepticism_gap"] = int(r["bench_skepticism_toward_appellant__modal"]) - int(r["bench_skepticism_toward_appellee__modal"])
        except (TypeError, ValueError, KeyError):
            r["skepticism_gap"] = None
        # python-side correctness flag for ruling_lean; "reverse" is credited for a partial reversal
        lean, actual = r.get("ruling_lean"), r.get("disposition")
        if lean and actual in ("affirm", "reverse", "mixed"):
            r["ruling_lean_correct"] = (lean == actual) or (lean in ("reverse", "mixed_or_unclear") and actual == "mixed")
        else:
            r["ruling_lean_correct"] = None

    lead = ["video_id", "case_number", "title", "case_name", "upload_date", "decided_date", "disposition",
            "ruling_lean", "ruling_lean__confidence", "ruling_lean_correct", "skepticism_gap",
            "appellant_hostile_mass", "appellee_hostile_mass", "bench_posture_toward_trial_court",
            "panel_judges", "author", "is_pca", "has_dissent",
            "trial_judge", "county", "duration_sec", "view_count", "url", "cl_url"]
    cols = list(lead)
    for r in recs:
        for k in r:
            if k not in cols:
                cols.append(k)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in recs:
            w.writerow(r)

    scored = [r for r in recs if "error" not in r and "_gated_out" not in r]
    gated = [r for r in recs if "_gated_out" in r]
    errored = [r for r in recs if "error" in r]
    total_tokens = sum(r.get("_input_tokens", 0) for r in recs)
    print(
        f"\n{len(recs)} rows in {csv_path} | {len(scored)} scored | {len(gated)} gated out | "
        f"{len(errored)} errors | {total_tokens:,} input tokens | "
        f"${total_tokens * PRICE_PER_M_INPUT / 1_000_000:.4f}"
    )
    if errored:
        seen = {}
        for r in errored:
            seen.setdefault(str(r["error"])[:160], []).append(r["video_id"])
        print("errors:")
        for msg, ids in sorted(seen.items(), key=lambda kv: -len(kv[1])):
            print(f"  [{len(ids)}x] {', '.join(ids[:5])}{' ...' if len(ids) > 5 else ''}\n        {msg}")

    if scored:
        passed = [r for r in scored if (r.get("transcript_sufficient") or 0) >= 0.5
                  and (r.get("is_oral_argument") or 0) >= 0.5]
        print(f"{len(passed)}/{len(scored)} passed the model gate (transcript_sufficient & is_oral_argument)")
        from collections import Counter
        lean = Counter(r.get("ruling_lean") for r in passed)
        print(f"ruling_lean: {dict(lean)}")
        for side in ("appellant", "appellee"):
            k = f"bench_skepticism_toward_{side}"
            modal = Counter(r.get(f"{k}__modal") for r in passed)
            bim = sum(1 for r in passed if r.get(f"{k}__bimodal"))
            print(f"{k}: modal levels {dict(sorted(modal.items(), key=lambda kv: str(kv[0])))}  bimodal={bim}/{len(passed)}")

        # ---- calibration readout: ruling_lean vs the court's actual disposition
        judged = [r for r in passed if r.get("ruling_lean_correct") is not None]
        if judged:
            acc = sum(1 for r in judged if r["ruling_lean_correct"]) / len(judged)
            base = Counter(r["disposition"] for r in judged)
            majority = max(base.values()) / len(judged)
            print(f"\nruling_lean vs actual disposition: {len(judged)} cases with decisions | "
                  f"accuracy {acc:.1%} | always-affirm baseline {majority:.1%}")
            print("  by predicted class:")
            for cls in ("affirm", "reverse", "mixed_or_unclear"):
                rs = [r for r in judged if r["ruling_lean"] == cls]
                if rs:
                    print(f"    {cls:<18} n={len(rs):<4} precision {sum(1 for r in rs if r['ruling_lean_correct'])/len(rs):.1%}")
            print("  by confidence bucket (choice confidence):")
            for lo, hi in ((0.0, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 1.01)):
                rs = [r for r in judged if lo <= (r.get("ruling_lean__confidence") or 0) < hi]
                if rs:
                    print(f"    [{lo:.1f}, {min(hi,1.0):.1f})  n={len(rs):<4} accuracy {sum(1 for r in rs if r['ruling_lean_correct'])/len(rs):.1%}")
            print("  by skepticism gap (appellant modal − appellee modal):")
            gaps = {}
            for r in judged:
                if r.get("skepticism_gap") is not None:
                    g = max(-2, min(2, r["skepticism_gap"]))
                    gaps.setdefault(g, []).append(r["disposition"] == "affirm")
            for g in sorted(gaps):
                v = gaps[g]
                print(f"    gap {'≤' if g == -2 else '≥' if g == 2 else ' '}{g:+d}  n={len(v):<4} affirmed {sum(v)/len(v):.1%}")
            print("  actual dispositions:", dict(base))


if __name__ == "__main__":
    main()
