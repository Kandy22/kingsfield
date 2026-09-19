#!/usr/bin/env python3
"""
YouTube auto-caption VTT → deduplicated, turn-segmented transcript with
inferred roles. Pass-1 speaker labeling (no audio, no model).

    captions/<id>.vtt  →  transcripts/<id>.turns.json

Rolling-caption dedupe: every cue shows the previous line plus the new one,
and 10 ms "hold" cues repeat the previous line. The new content of a cue is
its last non-blank line; emit it only when it differs from the last emitted
line. ">>" marks a speaker change and splits turns.

Role inference — deterministic, inspectable, overridden later by Gemini
diarization (pass 2):
  1. Segment anchors: a turn containing "may it please the court" or
     "on behalf of / representing the appellant|appellee" opens a counsel
     segment and names the side. A counsel segment that follows the appellee
     segment with no new introduction is rebuttal (appellant).
  2. Inside a segment, a 2-state Viterbi labels each turn BENCH / COUNSEL
     from lexical cues ("your honor" → counsel; questions, "let me ask",
     "counsel," → bench) and length (long turns are counsel), with a prior
     that favours — but does not force — alternation, since captions both
     drop and invent ">>" boundaries.
  3. Before the first anchor: BENCH (the court opening). After the last
     counsel turn: BENCH (the court closing).

Every turn carries role_src = anchor | rollcall | handoff | synth | lexical | viterbi | default so the
runner and the validation step can see how much of a transcript is guessed.
Nothing here is sent to the model until the gate in run_oa_panel.py passes.

Usage:
    python3 pipeline/build_transcripts.py --channel fl_2dca
    python3 pipeline/build_transcripts.py --channel fl_2dca --video eLU5je2C12I --print
"""
import argparse
import html
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import channel_dir  # noqa: E402

TS_RE = re.compile(r"(\d{2}):(\d{2}):(\d{2})\.(\d{3})")
INLINE_TS_RE = re.compile(r"<(\d{2}:\d{2}:\d{2}\.\d{3})>")
TAG_RE = re.compile(r"<[^>]+>")
SPEAKER_RE = re.compile(r"\s*>>\s*")

# --- role lexicon ---------------------------------------------------------
# Auto-captions garble the legal vocabulary ("May I please the court",
# "on behalf of the appeal", "Appal US Bank", "appellent"), so every anchor is
# fuzzy and side words are only trusted inside a "for / on behalf of" frame.
INTRO_RE = re.compile(r"\bmay (?:it|i) please the court\b", re.I)
# What "may it please the court" looks like after auto-captioning: "may police
# court", "May please", "Made please the court", "my please". Plus the other
# ways counsel opens.
INTRO_LIKE_RE = re.compile(
    r"\b(?:may|made|my|i)\s+(?:it\s+|i\s+)?(?:please|police|pleas|plead)\b"
    r"|\bpleas(?:e|ed)?\s+(?:the\s+|to\s+)?(?:the\s+)?court\b"
    r"|\bon behalf of\b"
    r"|\bmy name is\b"
    r"|\bi(?:'m| am) (?:here )?(?:on behalf|represent|for the)\b"
    r"|\b(?:good )?(?:morning|afternoon)\b.{0,80}?\b(?:from|with|of)\b.{0,60}?\b(?:firm|office|attorney general|p\.?a\.?|represent)"
    r"|\bcounsel for\b", re.I)
SIDE_FRAME = r"(?:on behalf of|for|represent(?:ing|s)?|counsel for)\s+(?:the\s+)?"
APPELLANT_WORD = r"(?:appell?[ae]nts?|appellents?|apell?ants?|petitioners?|cross[- ]appellees?)"
APPELLEE_WORD = r"(?:appell?ees?|appal\w*|appeal(?:ee)?s?|app'?s|respondents?|cross[- ]appellants?)"
APPELLANT_RE = re.compile(SIDE_FRAME + APPELLANT_WORD + r"\b", re.I)
APPELLEE_RE = re.compile(SIDE_FRAME + APPELLEE_WORD + r"\b", re.I)
NAME_RE = re.compile(r"\b(Mr|Ms|Mrs|Miss|Dr)\.?\s+([A-Z][A-Za-z'\-]+)")
ROLLCALL_RE = re.compile(r"\b(calling|we (?:should )?have|next case|the case (?:of|involving)|versus)\b", re.I)
PROCEED_RE = re.compile(r"\b(whenever you'?re ready|you may proceed|please proceed|go ahead|how much time)\b", re.I)
REBUTTAL_RE = re.compile(r"\brebuttal\b", re.I)
COUNSEL_LEX_RE = re.compile(
    r"\byour honou?rs?\b|\bmay (?:it|i) please\b|\bjudge\b,|\bthis court should (?:affirm|reverse)\b|"
    r"\bwe(?:'d| would)? (?:respectfully )?(?:ask|request|submit)\b|\bmy client\b|\bi'?d like to reserve\b", re.I)
BENCH_LEX_RE = re.compile(
    r"\bcounsel\b[,.?]|\bthank you,? counsel\b|\blet me ask\b|\bmy question is\b|\bhelp me\b|"
    r"\bunder advisement\b|\bwhenever you'?re ready\b|\byou may proceed\b|\bplease proceed\b|"
    r"\byour time is up\b|\byou have \w+ minutes?\b|\bminutes? (?:left|remaining)\b|\bthe next case\b|"
    r"\bwe(?:'ll| will) (?:take|hear)\b|\byou'?re about to get into\b|\bisn'?t it\b|\bam i correct\b", re.I)
CEREMONY_RE = re.compile(r"induction|investiture|ceremony|memorial|portrait|swearing", re.I)
LONG_TURN = 100  # words; bench turns this long are rare


def ts_to_sec(ts: str) -> float:
    m = TS_RE.match(ts)
    if not m:
        return 0.0
    h, mi, s, ms = (int(x) for x in m.groups())
    return h * 3600 + mi * 60 + s + ms / 1000


def parse_vtt(path: str) -> list:
    """→ [{start, end, text}] deduplicated caption lines in order."""
    raw = open(path, encoding="utf-8", errors="ignore").read()
    blocks = re.split(r"\n\s*\n", raw)
    lines = []
    last = None
    for blk in blocks:
        rows = blk.strip("\n").split("\n")
        hdr = next((r for r in rows if "-->" in r), None)
        if not hdr:
            continue
        m = re.match(r"(\S+)\s+-->\s+(\S+)", hdr.strip())
        if not m:
            continue
        cue_start, cue_end = ts_to_sec(m.group(1)), ts_to_sec(m.group(2))
        body = [r for r in rows[rows.index(hdr) + 1:]]
        # last non-blank line is the new content of this cue
        new = ""
        new_raw = ""
        for r in reversed(body):
            if TAG_RE.sub("", r).strip():
                new_raw = r
                new = html.unescape(TAG_RE.sub("", r)).strip()
                break
        if not new or new == last:
            continue
        # word-level tag inside the line gives the true start of that line
        first_inline = INLINE_TS_RE.search(new_raw)
        start = ts_to_sec(first_inline.group(1)) if first_inline else cue_start
        lines.append({"start": round(start, 2), "end": round(cue_end, 2), "text": new})
        last = new
    return lines


def lines_to_turns(lines: list) -> list:
    """Split on '>>' speaker markers → [{start, end, text}]."""
    turns = []
    cur = None
    for ln in lines:
        parts = SPEAKER_RE.split(ln["text"])
        for k, part in enumerate(parts):
            part = part.strip()
            if k > 0:  # a '>>' preceded this part → new turn
                if cur and cur["text"]:
                    turns.append(cur)
                cur = {"start": ln["start"], "end": ln["end"], "text": ""}
            if not part:
                continue
            if cur is None:
                cur = {"start": ln["start"], "end": ln["end"], "text": ""}
            cur["text"] = (cur["text"] + " " + part).strip()
            cur["end"] = ln["end"]
    if cur and cur["text"]:
        turns.append(cur)
    out = []
    for t in turns:
        if re.fullmatch(r"(\[[^\]]+\]\s*)+", t["text"]):  # "[Music]", "[clears throat]"
            continue
        out.append(t)
    return out


def _side_of(txt: str):
    a = APPELLANT_RE.search(txt)
    e = APPELLEE_RE.search(txt)
    if a and e:
        return "BOTH"
    if a:
        return "APPELLANT"
    if e:
        return "APPELLEE"
    return None


def _names_by_side(txt: str) -> dict:
    """Roll call: 'Mr. Rubi for the appellant and Mr. Donovan on behalf of the
    appellee' → {'Rubi': 'APPELLANT', 'Donovan': 'APPELLEE'} (name nearest
    before each side phrase)."""
    out = {}
    names = [(m.start(), m.group(2)) for m in NAME_RE.finditer(txt)]
    for side, rx in (("APPELLANT", APPELLANT_RE), ("APPELLEE", APPELLEE_RE)):
        for m in rx.finditer(txt):
            prior = [n for pos, n in names if pos < m.start()]
            if prior:
                out.setdefault(prior[-1].lower(), side)
    return out


def infer_roles(turns: list) -> dict:
    """Assign role / segment / role_src to each turn in place. Returns summary."""
    from collections import Counter
    n = len(turns)
    role = [None] * n
    src = [None] * n
    segment = [None] * n
    words = [len(t["text"].split()) for t in turns]
    names = {}          # lowercase surname -> side
    sides_seen = []
    anchors = 0

    # pass A: roll call (bench names both counsel) — only in the first few turns
    for i in range(min(n, 6)):
        txt = turns[i]["text"]
        if _side_of(txt) == "BOTH" or (ROLLCALL_RE.search(txt) and _side_of(txt)):
            names.update(_names_by_side(txt))
            role[i], src[i] = "BENCH", "rollcall"
            break

    # pass B: counsel introductions → segment anchors. Gather every
    # intro-like turn first, then decide by position and order: an explicit
    # side word in the head wins; otherwise the first intro is the appellant
    # UNLESS it sits ≥35% of the way through the argument with nothing before
    # it — then it is the appellee and the appellant intro was garbled (pass C
    # synthesizes it). A second intro must be well clear of the first.
    total_end = turns[-1]["end"] if turns else 0
    cands = []
    for i in range(n):
        if role[i]:
            continue
        head = " ".join(turns[i]["text"].split()[:45])
        side_head = _side_of(head)
        intro_like = bool(INTRO_LIKE_RE.search(head)) and words[i] >= 15
        if intro_like or side_head in ("APPELLANT", "APPELLEE"):
            cands.append((i, turns[i]["start"] / max(1, total_end), side_head, head))

    last_anchor_i = -10
    for i, frac, side_head, head in cands:
        if side_head in ("APPELLANT", "APPELLEE"):
            s2 = side_head
        elif not sides_seen:
            s2 = "APPELLEE" if frac >= 0.35 else "APPELLANT"
        else:
            s2 = "APPELLANT" if "APPELLANT" not in sides_seen else "APPELLEE"
        far_enough = (i - last_anchor_i >= 8) and (frac >= 0.2 or not sides_seen)
        if s2 in sides_seen:
            # only a rebuttal re-entry is allowed to repeat a side
            if not (s2 == "APPELLANT" and "APPELLEE" in sides_seen and far_enough):
                continue
        elif s2 == "APPELLEE" and sides_seen and not far_enough:
            continue
        seg_name = "REBUTTAL" if (s2 == "APPELLANT" and "APPELLEE" in sides_seen) else f"{s2}_ARG"
        sides_seen.append(s2)
        anchors += 1
        last_anchor_i = i
        role[i], src[i] = f"{s2}_COUNSEL", "anchor"
        for m in NAME_RE.finditer(head):
            names.setdefault(m.group(2).lower(), s2)
        segment[i] = seg_name

    # fill segments forward from anchors
    seg = "OPENING"
    for i in range(n):
        if src[i] == "anchor":
            seg = segment[i]
        segment[i] = seg

    # pass C: synthesize the appellant anchor when captions garbled every intro:
    # the first long turn after the opening is appellant's counsel by convention.
    first_appellee = next((i for i in range(n) if role[i] == "APPELLEE_COUNSEL" and src[i] == "anchor"), n)
    if "APPELLANT" not in sides_seen:
        for i in range(first_appellee):
            if role[i]:
                continue
            if words[i] >= 60:
                role[i], src[i] = "APPELLANT_COUNSEL", "synth"
                sides_seen.insert(0, "APPELLANT")
                for k in range(i, first_appellee):
                    segment[k] = "APPELLANT_ARG"
                break

    # pass D: bench hand-offs move the segment forward.
    #   in APPELLANT_ARG, bench addresses appellee's name  → APPELLEE_ARG
    #   in APPELLEE_ARG,  bench says "rebuttal"            → REBUTTAL
    #   in APPELLANT_ARG with no names, a bench turn ≤25 words followed by a
    #   long turn opening with a greeting/intro              → APPELLEE_ARG
    cur = None
    for i in range(n):
        if segment[i] in ("APPELLANT_ARG", "APPELLEE_ARG", "REBUTTAL"):
            cur = segment[i]
        if cur is None or role[i] == "APPELLANT_COUNSEL" and src[i] == "anchor":
            continue
        txt = turns[i]["text"]
        low = txt.lower()
        advance = None
        if cur == "APPELLANT_ARG":
            for nm, sd in names.items():
                if sd == "APPELLEE" and re.search(r"\b(mr|ms|mrs|miss|dr)\.?\s+" + re.escape(nm) + r"\b", low):
                    advance = "APPELLEE_ARG"
                    break
            if not advance and words[i] <= 25 and i + 1 < n and words[i + 1] >= 60 \
                    and re.match(r"^(thank you\.?\s*)?(good (morning|afternoon)|may (it|i) please)", turns[i + 1]["text"], re.I) \
                    and "APPELLEE" not in sides_seen:
                advance = "APPELLEE_ARG"
        elif cur == "APPELLEE_ARG" and REBUTTAL_RE.search(txt) and words[i] <= 40:
            advance = "REBUTTAL"
        if advance and advance != cur:
            role[i], src[i] = "BENCH", "handoff"
            if advance == "APPELLEE_ARG":
                sides_seen.append("APPELLEE")
            for k in range(i + 1, n):
                if segment[k] in ("APPELLANT_ARG", "APPELLEE_ARG", "REBUTTAL", None) and src[k] != "anchor":
                    segment[k] = advance
                elif src[k] == "anchor":
                    break
            cur = advance

    # pass E: 2-state Viterbi over the unlabeled turns. Emissions come from
    # lexical cues and length; the transition prior favours alternation, but
    # not absolutely, because captions both drop and invent ">>" boundaries.
    import math
    YOU_RE = re.compile(r"\byou(?:'re|r|'ve|'d)?\b", re.I)
    WE_RE = re.compile(r"\b(?:we|our|my client|the record|the trial court|we filed|we argued)\b", re.I)
    ANSWER_RE = re.compile(r"^(?:yes|no|correct|that's correct|absolutely|right|exactly|it is|it was|that's right)\b", re.I)

    def emis(i):
        txt = turns[i]["text"]
        w = words[i] or 1
        q = txt.rstrip().endswith("?")
        b = c = 0.0
        if BENCH_LEX_RE.search(txt): b += 1.6
        if COUNSEL_LEX_RE.search(txt): c += 2.0
        if q and w <= 40: b += 1.2
        elif q: b += 0.4
        if w >= LONG_TURN: c += 1.6
        elif w >= 50: c += 0.8
        b += min(1.0, 0.25 * len(YOU_RE.findall(txt)) * 20 / w)
        c += min(1.0, 0.30 * len(WE_RE.findall(txt)) * 20 / w)
        if w <= 6 and ANSWER_RE.match(txt) and i > 0 and turns[i - 1]["text"].rstrip().endswith("?"):
            c += 1.2
        return {"BENCH": b, "COUNSEL": c}

    HARD = 6.0
    LOG_SWITCH, LOG_SAME = math.log(0.72), math.log(0.28)
    states = ("BENCH", "COUNSEL")
    score = [dict() for _ in range(n)]
    back = [dict() for _ in range(n)]
    for i in range(n):
        e = emis(i)
        if role[i]:  # anchored turns are (almost) fixed
            fixed = "BENCH" if role[i] == "BENCH" else "COUNSEL"
            e = {st: (HARD if st == fixed else -HARD) for st in states}
        for st in states:
            if i == 0:
                score[i][st] = e[st] + (0.0 if st == "BENCH" else -0.5)
                back[i][st] = None
                continue
            best_prev, best_val = None, -1e18
            for pv in states:
                v = score[i - 1][pv] + (LOG_SAME if pv == st else LOG_SWITCH)
                if v > best_val:
                    best_prev, best_val = pv, v
            score[i][st] = best_val + e[st]
            back[i][st] = best_prev
    if n:
        st = max(states, key=lambda k: score[n - 1][k])
        path = [None] * n
        for i in range(n - 1, -1, -1):
            path[i] = st
            st = back[i][st] if back[i][st] else st
        for i in range(n):
            if role[i]:
                continue
            e = emis(i)
            margin = abs(e["BENCH"] - e["COUNSEL"])
            role[i] = path[i]
            src[i] = "lexical" if margin >= 1.2 else "viterbi"
        # a turn in OPENING before any anchor with no evidence stays bench
        for i in range(n):
            if segment[i] in ("OPENING", None) and src[i] == "viterbi":
                role[i], src[i] = "BENCH", "default"

    # resolve generic COUNSEL → the segment's side
    for i in range(n):
        if role[i] == "COUNSEL":
            s = segment[i]
            role[i] = ("APPELLANT_COUNSEL" if s in ("APPELLANT_ARG", "REBUTTAL")
                       else "APPELLEE_COUNSEL" if s == "APPELLEE_ARG" else "COUNSEL")
    last_counsel = max((i for i in range(n) if role[i] != "BENCH"), default=-1)
    for i in range(last_counsel + 1, n):
        segment[i] = "CLOSING"

    for i, t in enumerate(turns):
        t["role"], t["role_src"], t["segment"] = role[i], src[i], segment[i]

    return {
        "anchors": anchors,
        "names": names,
        "sides_seen": sides_seen,
        "segments": dict(Counter(segment)),
        "role_src": dict(Counter(src)),
        "roles": dict(Counter(role)),
    }


def build_one(vtt_path: str, video_id: str, title: str) -> dict:
    lines = parse_vtt(vtt_path)
    turns = lines_to_turns(lines)
    summary = infer_roles(turns) if turns else {}
    n_words = sum(len(t["text"].split()) for t in turns)
    return {
        "video_id": video_id,
        "title": title,
        "source": "yt_auto_captions",
        "built_at": datetime.now(timezone.utc).isoformat(),
        "n_lines": len(lines),
        "n_turns": len(turns),
        "n_words": n_words,
        "speech_end_sec": turns[-1]["end"] if turns else 0,
        "gate": {
            "title_is_ceremony": bool(CEREMONY_RE.search(title or "")),
            # few ">>" markers → giant merged turns → role labels are unreliable
            "turns_coarse": (len(turns) < 12 and n_words > 2000)
                            or (n_words / max(1, len(turns)) > 250),
            "has_intro_anchor": summary.get("anchors", 0) > 0 or "synth" in summary.get("role_src", {}),
            "has_both_sides": {"APPELLANT", "APPELLEE"} <= set(summary.get("sides_seen", [])),
            "n_bench_turns": summary.get("roles", {}).get("BENCH", 0),
            "n_counsel_turns": sum(v for k, v in summary.get("roles", {}).items() if k != "BENCH"),
            "pct_role_guessed": round(
                100 * (summary.get("role_src", {}).get("viterbi", 0) + summary.get("role_src", {}).get("default", 0))
                / max(1, len(turns)), 1),
        },
        "role_summary": summary,
        "turns": [{"i": i, **t} for i, t in enumerate(turns)],
    }


def fmt_ts(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="fl_2dca")
    ap.add_argument("--video")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--print", action="store_true", help="print the labeled transcript to stdout")
    args = ap.parse_args()

    base = channel_dir(args.channel)
    cap_dir = os.path.join(base, "captions")
    tr_dir = os.path.join(base, "transcripts")
    os.makedirs(tr_dir, exist_ok=True)

    titles = {}
    idx_path = os.path.join(base, "index.json")
    if os.path.exists(idx_path):
        for v in json.load(open(idx_path)).get("videos", []):
            titles[v["video_id"]] = v.get("title", "")

    vids = sorted(
        n[:-4] for n in os.listdir(cap_dir)
        if n.endswith(".vtt") and not n.endswith(".en.vtt")
    )
    if args.video:
        vids = [v for v in vids if v == args.video]

    built = skipped = 0
    gate_fail = 0
    for vid in vids:
        out = os.path.join(tr_dir, f"{vid}.turns.json")
        if os.path.exists(out) and not args.force and not args.print:
            skipped += 1
            continue
        title = titles.get(vid, "")
        meta = os.path.join(cap_dir, f"{vid}.info.json")
        if not title and os.path.exists(meta):
            title = json.load(open(meta)).get("title", "")
        doc = build_one(os.path.join(cap_dir, f"{vid}.vtt"), vid, title)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=1, ensure_ascii=False)
        built += 1
        g = doc["gate"]
        if g["title_is_ceremony"] or doc["n_words"] < 1500:   # same gate run_oa_panel.py applies
            gate_fail += 1
        if args.print:
            print(f"# {vid}  {title}  turns={doc['n_turns']} words={doc['n_words']}  gate={g}")
            for t in doc["turns"]:
                print(f"[{fmt_ts(t['start'])}] {t['role']:<18} ({t['role_src']:<7} {t['segment']:<13}) {t['text']}")
        elif built % 100 == 0:
            print(f"  built {built}")
    print(f"built {built}, skipped {skipped} existing, {gate_fail} would fail the python gate")


if __name__ == "__main__":
    main()
