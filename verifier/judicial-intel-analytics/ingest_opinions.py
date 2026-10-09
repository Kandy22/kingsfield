"""
ingest_opinions.py — CO Supreme Court panel participation -> opinions + co-panel edges.

CourtListener has no author/dissent typing for `colo` (every sub-opinion is
010combined with a null author). But the cluster-level `judges` string IS populated
for roughly 1995-2016 and lists the justices associated with the case, e.g.

    "Hood, Coats, Eid, Márquez, Boatright"
    "Coats, Gabriel, Rice, Hood"
    "Coats, Dlssents, Eid"        <- OCR'd "Dissents"

That gives panel participation, which is what the co-panel network and the MaxEnt
panel selection both need. It does NOT give vote direction — see LIMITS below.

Run modes:
  seed   : load the 100 clusters already retrieved (no network, no token)
  full   : page the CourtListener API for all colo clusters (needs CL_TOKEN)

LIMITS — read before using any number this produces:
  * Participation != authorship. The string is a list of associated justices; it
    does not say who wrote, who joined, or who dissented.
  * "Dissents"/"Dlssents"/"Does" tokens appear inline and are OCR-corrupted. They
    are captured as a flag on the cluster, NOT attributed to a justice.
  * Coverage collapses after ~2016 (strings go empty) and before ~1995.
  * Duplicate clusters exist for the same case (multiple sources merged).
  So co-panel counts are a lower bound, and no grant/dissent rate should be
  computed from this table. Vote direction requires opinion-text parsing.
"""

import os, re, sqlite3, unicodedata, urllib.request, json, time

DB = "co_judges.db"
SRC = "CourtListener clusters?docket__court=colo (cluster.judges string)"
RETRIEVED = "2026-09-06"

NOISE = {"dissents", "dlssents", "does", "dissent", "disciplinary", "eed",
         "per", "curiam", "percuriam", "justice", "chief", "judge", "the"}


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return s.lower().strip(" .,;")


def parse_judges(field):
    """'Hood, Coats, Eid' -> (['hood','coats','eid'], dissent_flag)"""
    if not field:
        return [], 0
    toks = [norm(t) for t in re.split(r"[,;/&]| and ", field) if t.strip()]
    dissent = any(t.startswith(("dissent", "dlssent")) for t in toks)
    names = [t for t in toks if t and t not in NOISE and len(t) > 2 and t.isalpha()]
    return names, int(dissent)


def resolve(cx):
    """surname -> judge_id, for CO Supreme justices only."""
    out = {}
    for jid, name in cx.execute(
            "SELECT judge_id, full_name FROM judges WHERE court='CO Supreme'"):
        s = norm(name)
        s = re.sub(r"\b(jr|sr|ii|iii|iv|[0-9]+)\b\.?", "", s)
        parts = [p for p in s.split() if p]
        if parts:
            out.setdefault(parts[-1], jid)
    return out


def fetch_full(token, court="colo", lo="1990-01-01", hi="2026-12-31", cap=5000):
    """Page the CourtListener API. Requires a token."""
    url = ("https://www.courtlistener.com/api/rest/v4/clusters/"
           f"?docket__court={court}&date_filed__gte={lo}&date_filed__lte={hi}"
           "&fields=id,case_name,date_filed,judges,citation_count&order_by=-date_filed")
    out = []
    while url and len(out) < cap:
        req = urllib.request.Request(url, headers={"Authorization": f"Token {token}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            page = json.loads(r.read())
        out.extend(page.get("results", []))
        url = page.get("next")
        time.sleep(0.4)
    return out


def load_seed():
    with open("co_clusters_seed.json") as f:
        return json.load(f)


def ingest(rows):
    cx = sqlite3.connect(DB)
    cx.execute("DELETE FROM opinions WHERE src=?", (SRC,))
    cx.execute("DELETE FROM judge_edges WHERE edge_type='co_panel'")
    sur = resolve(cx)

    seen, unmatched, pairs = set(), {}, {}
    n_op = 0
    for r in rows:
        cid = r.get("id")
        if cid in seen:
            continue
        seen.add(cid)
        names, dissent = parse_judges(r.get("judges"))
        jids = []
        for n in names:
            if n in sur:
                jids.append(sur[n])
            else:
                unmatched[n] = unmatched.get(n, 0) + 1
        for j in set(jids):
            cx.execute("""INSERT INTO opinions
                (judge_id,cluster_id,case_name,date_filed,role,vote_direction,
                 text_url,src,retrieved_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                (j, cid, r.get("case_name"), r.get("date_filed"),
                 "participated_dissent_present" if dissent else "participated",
                 None, f"https://www.courtlistener.com/opinion/{cid}/",
                 SRC, RETRIEVED))
            n_op += 1
        u = sorted(set(jids))
        for a in range(len(u)):
            for b in range(a + 1, len(u)):
                pairs[(u[a], u[b])] = pairs.get((u[a], u[b]), 0) + 1

    id2name = dict(cx.execute("SELECT judge_id, full_name FROM judges"))
    for (a, b), w in pairs.items():
        for x, y in ((a, b), (b, a)):
            cx.execute("""INSERT INTO judge_edges
                (judge_id,alter_name,alter_type,edge_type,weight,src,retrieved_at)
                VALUES (?,?,?,?,?,?,?)""",
                (x, id2name[y], "judge", "co_panel", float(w), SRC, RETRIEVED))
    cx.commit()

    print(f"clusters ingested      {len(seen)}")
    print(f"participation rows     {n_op}")
    print(f"co-panel edges         {len(pairs)*2}  ({len(pairs)} pairs)")
    print(f"unmatched name tokens  {len(unmatched)}")
    if unmatched:
        top = sorted(unmatched.items(), key=lambda x: -x[1])[:12]
        print("  " + ", ".join(f"{k}({v})" for k, v in top))

    print("\nTOP CO-PANEL PAIRS")
    q = """SELECT j.full_name, e.alter_name, e.weight FROM judge_edges e
           JOIN judges j USING(judge_id) WHERE e.edge_type='co_panel'
           AND j.judge_id < (SELECT judge_id FROM judges WHERE full_name=e.alter_name)
           ORDER BY e.weight DESC LIMIT 10"""
    for a, b, w in cx.execute(q):
        print(f"  {int(w):>3}  {a}  +  {b}")

    print("\nPARTICIPATION BY JUSTICE")
    for n, c in cx.execute("""SELECT j.full_name, COUNT(*) FROM opinions o
                              JOIN judges j USING(judge_id) GROUP BY 1 ORDER BY 2 DESC"""):
        print(f"  {c:>4}  {n}")
    cx.close()


if __name__ == "__main__":
    tok = os.environ.get("CL_TOKEN")
    if tok:
        print("full pull via CourtListener API...")
        rows = fetch_full(tok)
        json.dump(rows, open("co_clusters_full.json", "w"))
        print(f"fetched {len(rows)} clusters -> co_clusters_full.json")
    else:
        print("no CL_TOKEN set — using seed corpus "
              "(set CL_TOKEN to pull the full ~2,786 colo clusters)\n")
        rows = load_seed()
    ingest(rows)
