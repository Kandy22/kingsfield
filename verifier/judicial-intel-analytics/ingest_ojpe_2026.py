"""
ingest_ojpe_2026.py — fill judge_accounts, cultural_signals and judge_bio from
the 2026 OJPE evaluation narratives.

Input:  data/ojpe2026/narratives.json  (one record per judge, harvested from
        judicialperformance.colorado.gov; the site 403s non-browser clients, so
        the corpus is pulled through a real browser session, no UA spoofing)
Output: rows in judge_accounts, cultural_signals, judge_bio, plus data_gaps.

Why the narratives and not campaign accounts: under the Colorado Code of
Judicial Conduct a judge standing for retention may not campaign unless there
is active opposition. There are therefore almost no campaign sites, committees
or candidate questionnaires to resolve. The OJPE narrative is the one public,
per-judge, verbatim text that exists for all 123 judges on the ballot, and it
carries exactly the biographical/associational material the cultural layer
wants. Evidence is stored verbatim, never paraphrased.
"""

import json, os, re, sqlite3, unicodedata

DB = "co_judges.db"
SRC_FILE = "data/ojpe2026/narratives.json"
R = "2026-09-06"
BASE = "https://judicialperformance.colorado.gov/"


def fullkey(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.lower().replace('"', " ").replace("'", "")
    s = re.sub(r"[.,]", " ", s)
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", " ", s)
    return " ".join(s.split())


def surname(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"\b(jr|sr|ii|iii|iv|[0-9]+)\b\.?", "", s.lower())
    s = s.replace('"', "").replace("'", "")
    parts = [p for p in s.replace(",", " ").split() if p]
    return parts[-1].strip(".,") if parts else s


# The page text runs sentences together ("...MEETS PERFORMANCE STANDARDS.Judge
# Datz presided over..."), so the splitter must fire on a bare period followed by
# a capital. Guard against splitting inside initials and common abbreviations,
# which would otherwise cut "William W. Hood" in half.
_ABBR = r"(?<!\b[A-Z])(?<!\bMr)(?<!\bMrs)(?<!\bMs)(?<!\bDr)(?<!\bHon)(?<!\bJr)(?<!\bSr)(?<!\bSt)(?<!\bNo)(?<!\bv)"
_SPLIT = re.compile(_ABBR + r"(?<=[.!?])\s*(?=[A-Z“\"])")


def sentences(text):
    """Split narrative prose into sentences, keeping each one verbatim."""
    out = []
    for line in text.split("\n"):
        line = line.strip()
        if not line or line.startswith("Home") or "Retention Year:" in line:
            continue
        for s in _SPLIT.split(line):
            s = s.strip()
            if len(s) > 25:
                out.append(s)
    return out


# category -> (regex over the sentence, regex capturing the item)
PATTERNS = [
    ("education",    r"\b(undergraduate|bachelor|B\.A\.|B\.S\.|graduated from|earned (?:his|her|their)|College of Law|School of Law|law degree|J\.D\.|University|College)\b"),
    ("clerkship",    r"\b(law clerk|clerked|clerkship)\b"),
    ("career_track", r"\b(public defender|deputy district attorney|district attorney|prosecutor|magistrate|private practice|law firm|partner at|associate at|Attorney General|city attorney|municipal judge|solo practice)\b"),
    ("award",        r"\b(award|honor(?:ed|ee)?|recognition|recognized|excellence|distinguished)\b"),
    ("civic",        r"\b(volunteer|board of|serves on the board|nonprofit|non-profit|community service|mentor(?:ship|ing|s)?|pro bono|civic|charit|Rotary|Kiwanis|United Way|Boy Scouts|Girl Scouts)\b"),
    ("teaching",     r"\b(adjunct|taught|teaches|faculty|instructor|professor|lecturer|CLE)\b"),
    ("military",     r"\b(Army|Navy|Air Force|Marine|military|veteran|JAG|National Guard)\b"),
    ("origin",       r"\b(born (?:and )?raised|grew up|native of|hometown|moved to Colorado|raised (?:in|on))\b"),
    # "coach" alone is a false friend here - judges guest-coach mock trial and
    # moot court, which is not a sports signal. Require an actual sport, or
    # coaching tied to youth/school athletics.
    ("sports",       r"\b(soccer|baseball|basketball|football|hockey|ski(?:s|ed|ing|er)?|snowboard|cycling|bicycl|marathon|triathlon|rugby|lacrosse|softball|volleyball|wrestl|golf|tennis|climb(?:s|ed|ing|er)?|hik(?:es|ed|ing)|fly[- ]fish|rodeo|equestrian|athletic(?:s)?)\b"
                     r"|\bcoach(?:ed|es|ing)?\b(?=[^.]*\b(youth|kids|children|team|league|high school|little league|club)\b)"),
    # a sentence about mock trial/moot court coaching is civic, not sport
    ("__drop_sports", r"\b(mock trial|moot court)\b"),
    ("arts",         r"\b(music(?:ian)?|guitar|piano|violin|cello|band|choir|chorus|orchestra|symphony|opera|film|movie|cinema|theat(?:er|re)|novelist|novels|poetry|poet|painting|painter|sculpt|photograph(?:y|er)|ballet|dance company|book club)\b"),
    # "Temple University" is a school, not a house of worship
    ("faith",        r"\b(church|synagogue|mosque|parish|congregation|ministry"
                     r"|temple(?! University)|faith community|(?:his|her|their) faith)\b"),
    # personal family only - "parents and guardians" in a dependency-and-neglect
    # docket description is case terminology, not biography
    ("family",       r"\b(is married|married to|(?:his|her|their) (?:spouse|husband|wife|children|daughter|son|family)"
                     r"|father of|mother of|parent of|raising (?:his|her|their))\b"),
    # the direct-taste channel: what the judge does when not judging. Rare but
    # this is the highest-value category for the cultural thesis, so it gets its
    # own pattern rather than being folded into civic.
    ("leisure",      r"\b(enjoys|hobb(?:y|ies)|in (?:his|her|their) (?:free|spare) time|outside (?:the courtroom|of work)"
                     r"|spends (?:his|her|their) (?:free|spare) time|avid|loves to|likes to)\b"
                     r"|\bpassionate about\b(?![^.]*\b(the law|law|profession|work|job|role|career|public serv|mentor|community|being)\b)"),
    ("language",     r"\b(bilingual|Spanish[- ]speaking|fluent in|interpreter)\b"),
]

# things worth pulling out as a discrete item, not just a sentence
ITEM_RX = re.compile(
    r"\b((?:University|College|Institute|School) of [A-Z][A-Za-z.& ]{2,40}"
    r"|[A-Z][A-Za-z.&']+(?: [A-Z][A-Za-z.&']+){0,4} (?:University|College|Law School|School of Law))\b")


# The OJPE full-list TABLE and the LINK TEXT for the same judge disagree in
# places. Both spellings are kept here rather than silently picking one; the
# conflict itself is recorded in data_gaps.
ALIAS = {
    "laqunya latrese baker": "laqunya latrese baker-mckay",
}


def classify(sent):
    hits = []
    for cat, rx in PATTERNS:
        if re.search(rx, sent, re.I):
            hits.append(cat)
    # veto categories: a marker that disqualifies an otherwise-matching category
    if "__drop_sports" in hits:
        hits = [h for h in hits if h not in ("__drop_sports", "sports")]
    return hits


def main():
    if not os.path.exists(SRC_FILE):
        raise SystemExit(f"missing {SRC_FILE} - harvest the narratives first")
    recs = json.load(open(SRC_FILE, encoding="utf-8"))
    cx = sqlite3.connect(DB)

    jmap, smap = {}, {}
    for jid, name in cx.execute("SELECT judge_id, full_name FROM judges"):
        jmap[fullkey(name)] = jid
        smap.setdefault(surname(name), []).append(jid)

    acc = cult = bio = 0
    unmatched, votes = [], 0

    for rec in recs:
        if rec.get("err") or rec.get("s") != 200:
            unmatched.append((rec.get("n"), "fetch failed"))
            continue
        name, slug, txt = rec["n"], rec["u"], rec["txt"]

        fk = fullkey(name)
        j = jmap.get(fk) or jmap.get(ALIAS.get(fk, ""))
        if j is None:                       # link text can differ from table text
            cand = smap.get(surname(name), [])
            j = cand[0] if len(cand) == 1 else None
        if j is None:
            unmatched.append((name, "no roster match"))
            continue

        url = BASE + slug

        # --- judge_accounts: the public presence that actually exists --------
        rows = [(j, "ojpe", url, "evaluation_page", "linked from OJPE 2026 full list",
                 "2026", None, url, R)]
        for p in rec.get("pdfs", []):
            kind = ("survey_report_2026" if "2026" in p.rsplit("/", 1)[-1]
                    else "survey_report_interim")
            rows.append((j, "ojpe", p, kind, "linked from judge evaluation page",
                         "2026", None, url, R))
        cx.executemany("INSERT INTO judge_accounts VALUES (?,?,?,?,?,?,?,?,?)", rows)
        acc += len(rows)

        # --- commission vote, verbatim -------------------------------------
        m = re.search(r"by (?:a )?vote of \d+[-–]\d+[^.]*|by a vote of[^.]*|"
                      r"[Oo]f the \d+ [Cc]ommissioners[^.]*", txt)
        if m:
            cx.execute("INSERT INTO judge_bio VALUES (?,?,?,?,?,?)",
                       (j, "commission_vote", m.group(0).strip(), 2026, url, R))
            bio += 1
            votes += 1

        # --- cultural_signals: one row per (sentence, category) -------------
        seen = set()
        for sent in sentences(txt):
            for cat in classify(sent):
                item = None
                if cat in ("education", "clerkship"):
                    im = ITEM_RX.search(sent)
                    item = im.group(1) if im else None
                key = (cat, item, sent[:80])
                if key in seen:
                    continue
                seen.add(key)
                cx.execute("INSERT INTO cultural_signals VALUES (?,?,?,?,?,?,?,?,?)",
                           (j, cat, item, None, sent, "ojpe_evaluation_narrative",
                            "2026", url, R))
                cult += 1

    # --- conflicting recommendations, stored rather than resolved -----------
    # Christiansen carries TWO findings. The 13th JD commission concluded she did
    # not meet standards; after a Rule 21 complaint the State Commission found the
    # district commission had skipped the mandated initial interim evaluation and
    # issued its own narrative and recommendation of MEETS. The ballot-facing
    # value is the State Commission's. Both are kept.
    row = cx.execute("SELECT judge_id FROM judges WHERE full_name=?",
                     ("Dina M. Christiansen",)).fetchone()
    if row:
        cx.execute("""INSERT INTO retention_elections
                      (judge_id,year,ojpe_recommendation,src,retrieved_at)
                      VALUES (?,?,?,?,?)""",
                   (row[0], 2026,
                    "DOES NOT MEET PERFORMANCE STANDARDS (13th JD district "
                    "commission finding, superseded by State Commission after "
                    "Rule 21 complaint)",
                    BASE + "christiansen-dina-m-2026-evaluation", R))

    gaps = [
        ("judge_accounts", f"Resolved {acc} official/OJPE URLs. Campaign sites, "
         "Facebook Pages and X/Bluesky accounts are largely ABSENT BY RULE: under "
         "the Colorado Code of Judicial Conduct a judge standing for retention may "
         "not campaign unless there is active opposition, and no organised 2026 "
         "opposition committee was found. Treat a null campaign account as a "
         "verified null, not a missing lookup",
         "check SoS TRACER for any issue committee before assuming zero", R),
        ("cultural_signals", f"{cult} rows, all from OJPE narratives - the only "
         "per-judge verbatim public text covering all 123 ballot judges. Music/film/"
         "books are near-absent in this corpus; it yields education, career track, "
         "clerkships, awards, civic and some sports/arts. Direct taste signal needs "
         "a different channel (oral-argument video, bar journal profiles, investiture)",
         "ingest cojudicial.ompnetwork.org and CBA bar journal profiles", R),
        ("name conflict", "OJPE's own full-list table and its link text disagree "
         "for the 18th JD judge: the table reads 'LaQunya Latrese Baker-McKay', the "
         "evaluation link reads 'LaQunya Latrese Baker'. Roster keeps the table form "
         "and aliases the other. Separately, Daniel W. Warhola's evaluation lives at "
         "a slug reading 'warhola-david-w' - Daniel vs David unresolved at source",
         "confirm both against coloradojudicial.gov/contact before publishing", R),
        ("unfavorable recommendations", "THREE judges drew unfavorable 2026 findings, "
         "not one: Jeremy P. Boyce (16th, Crowley County), William David Alexander "
         "(10th, Pueblo district, 7-3 commission vote) and Dina M. Christiansen (13th). "
         "Christiansen is the subtle one - the ballot-facing recommendation is MEETS, "
         "but that is the STATE Commission overriding the 13th JD commission's DOES "
         "NOT MEET finding after a Rule 21 complaint established the district "
         "commission had skipped the mandated initial interim evaluation. Both "
         "findings are stored in retention_elections; do not treat her as a clean MEETS",
         "read the full state narrative before using her as a control case", R),
    ]
    cx.executemany("INSERT INTO data_gaps VALUES (?,?,?,?)", gaps)
    cx.commit()

    print(f"judge_accounts   +{acc}")
    print(f"cultural_signals +{cult}")
    print(f"judge_bio        +{bio}  (commission votes: {votes})")
    print(f"narratives read   {len(recs)}")
    if unmatched:
        print(f"\nUNMATCHED TOKENS ({len(unmatched)}) - roster holes live here:")
        for n, why in unmatched:
            print(f"  {n:<40} {why}")
    else:
        print("\nUNMATCHED TOKENS: none - all narratives matched the roster")
    cx.close()


if __name__ == "__main__":
    main()
