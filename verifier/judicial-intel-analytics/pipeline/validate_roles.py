#!/usr/bin/env python3
"""
Score pass-1 role inference (build_transcripts.py) against Gemini diarization
where it exists. Ground truth: Gemini speaker labels starting with "Judge" →
BENCH, anything else → COUNSEL. Each caption turn is matched to the Gemini
segment that overlaps it most in time.

    python3 pipeline/validate_roles.py --channel fl_2dca
"""
import argparse, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import channel_dir, entry_paths


def parse_ts(ts):
    m = re.match(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", ts or "")
    if not m: return 0.0
    a, b, c = m.groups()
    return (int(a)*3600 + int(b)*60 + int(c)) if c else (int(a)*60 + int(b))


def gemini_segments(path):
    d = json.load(open(path))
    out = []
    for s in d.get("segments", []):
        ts = s.get("timestamp", "")
        parts = [p.strip() for p in ts.split("-")]
        st = parse_ts(parts[0]); en = parse_ts(parts[1]) if len(parts) > 1 else st + 5
        spk = s.get("speaker", "")
        # only trust unambiguous labels: chunk-local "Speaker N" ids are excluded
        if re.match(r"judge", spk, re.I):
            role = "BENCH"
        elif re.match(r"attorney|counsel", spk, re.I) or re.match(r"[A-Z][a-z]+ [A-Z][a-z]+$", spk):
            role = "COUNSEL"
        else:
            continue
        # drop segments whose label contradicts a hard lexical cue
        if role == "BENCH" and re.search(r"\byour honou?r", s.get("content", ""), re.I):
            continue
        out.append((st, en, role, spk))
    return out


def hand_truth(path):
    d = json.load(open(path))
    return {int(k): v for k, v in d.items() if not k.startswith("_")}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--channel", default="fl_2dca"); args = ap.parse_args()
    base = channel_dir(args.channel)
    tr = os.path.join(base, "transcripts")
    tot = {"n": 0, "agree": 0}
    sources = []
    for name in sorted(os.listdir(tr)):
        if name.endswith(".diarize.json"):
            sources.append((name[:-len(".diarize.json")], "gemini", os.path.join(tr, name)))
        elif name.startswith("_truth_") and name.endswith(".json"):
            sources.append((name[len("_truth_"):-5], "hand", os.path.join(tr, name)))
    for vid, kind, path in sources:
        tpath = os.path.join(tr, f"{vid}.turns.json")
        if not os.path.exists(tpath):
            print(f"{vid}: no turns.json (run build_transcripts first)"); continue
        doc = json.load(open(tpath))
        if kind == "hand":
            truth = hand_truth(path)
            gem = [(sec, sec + 1, r, "hand") for sec, r in truth.items()]
        else:
            gem = gemini_segments(path)
        n = agree = 0
        by_src = {}
        confusion = {}
        for t in doc["turns"]:
            best, ov = None, 0
            if kind == "hand":
                best = dict((sec, r) for sec, _, r, _ in gem).get(int(t["start"]))
            else:
                for st, en, role, spk in gem:
                    o = min(t["end"], en) - max(t["start"], st)
                    if o > ov: best, ov = role, o
            if best is None: continue
            mine = "BENCH" if t["role"] == "BENCH" else "COUNSEL"
            n += 1; ok = (mine == best); agree += ok
            s = by_src.setdefault(t["role_src"], [0, 0]); s[0] += 1; s[1] += ok
            confusion[(best, mine)] = confusion.get((best, mine), 0) + 1
        tot["n"] += n; tot["agree"] += agree
        print(f"{vid} [{kind}]: {agree}/{n} turns agree ({100*agree/max(1,n):.1f}%)  segments={doc['role_summary']['segments']}  names={doc['role_summary'].get('names')}")
        for src, (c, ok) in sorted(by_src.items(), key=lambda kv: -kv[1][0]):
            print(f"    {src:<8} {ok}/{c}")
        print("    confusion (truth→mine):", {f"{k[0]}→{k[1]}": v for k, v in sorted(confusion.items())})
    if tot["n"]:
        print(f"\nOVERALL {tot['agree']}/{tot['n']} = {100*tot['agree']/tot['n']:.1f}% BENCH/COUNSEL agreement with Gemini")


if __name__ == "__main__":
    main()
