"""
build_co_judges.py — Colorado judicial identification table.

The spine every enrichment layer attaches to. Verified data only; every field
carries a source and retrieval date; unknown is NULL, never a guess. Where two
sources conflict, both are stored and the conflict is reported.

Covers the full request set: cultural (music/film/books/sports), social accounts,
network (closest-N), promotion/auditioning, press, bio, opinions/transcripts/video,
campaign finance, docket metrics, geodemographic, keyword vectors for MaxEnt.

Data lives in co_data.py so a repull edits one file.
"""

import sqlite3, csv, os, unicodedata, re as _re
import co_data as D

DB = "co_judges.db"
R = D.RETRIEVED


def surname(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = _re.sub(r"\b(jr|sr|ii|iii|iv|[0-9]+)\b\.?", "", s.lower())
    s = s.replace('"', "").replace("'", "")
    parts = [p for p in s.replace(",", " ").split() if p]
    return parts[-1].strip(".,") if parts else s


def fullkey(s):
    """Identity key for a roster person.

    Surname alone is NOT an identity: the 2026 slate contains two Sullivans,
    two Larsons, two Hendersons and a Thomas/Martinez-Thomas pair. Keying on
    surname silently dropped Costilla County's Tamara McSherry Sullivan and
    hung her retention row on Court of Appeals Judge Grant Sullivan instead.
    """
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.lower().replace('"', " ").replace("'", "")
    s = _re.sub(r"[.,]", " ", s)
    s = _re.sub(r"\b(jr|sr|ii|iii|iv)\b", " ", s)
    return " ".join(s.split())


SCHEMA = """
PRAGMA foreign_keys=ON;

CREATE TABLE judges (
  judge_id            INTEGER PRIMARY KEY,
  full_name           TEXT NOT NULL,
  court               TEXT NOT NULL,
  judicial_district   INTEGER,
  county              TEXT,
  seat_status         TEXT,
  is_chief            INTEGER DEFAULT 0,
  chief_since         TEXT,
  date_start          TEXT,
  date_termination    TEXT,
  selection_method    TEXT,
  appointing_governor TEXT,
  appointing_party    TEXT,
  law_school          TEXT,
  birth_year          INTEGER,
  mandatory_retire_year INTEGER,
  bp_retention_year_reported INTEGER,
  courtlistener_id    INTEGER,
  date_dob            TEXT,
  src_roster          TEXT,
  retrieved_at        TEXT
);

CREATE TABLE judge_bio (
  judge_id INTEGER REFERENCES judges(judge_id),
  field TEXT, value TEXT, year INTEGER, src TEXT, retrieved_at TEXT);

CREATE TABLE judge_edges (
  judge_id INTEGER REFERENCES judges(judge_id),
  alter_name TEXT NOT NULL, alter_type TEXT, edge_type TEXT, weight REAL,
  start_year INTEGER, end_year INTEGER, src TEXT, retrieved_at TEXT);

CREATE TABLE vacancy_events (
  event_id INTEGER PRIMARY KEY, court_above TEXT, vacancy_date TEXT,
  filled_date TEXT, filled_by TEXT, src TEXT, retrieved_at TEXT);

CREATE TABLE shortlist_membership (
  judge_id INTEGER REFERENCES judges(judge_id),
  event_id INTEGER REFERENCES vacancy_events(event_id),
  source_type TEXT, src TEXT, retrieved_at TEXT);

CREATE TABLE retention_elections (
  judge_id INTEGER REFERENCES judges(judge_id),
  year INTEGER, yes_pct REAL, no_pct REAL,
  ojpe_recommendation TEXT, src TEXT, retrieved_at TEXT);

CREATE TABLE contributions (
  judge_id INTEGER REFERENCES judges(judge_id),
  donor_name TEXT, donor_type TEXT, donor_firm TEXT, amount REAL,
  donation_date TEXT, filing_url TEXT, src TEXT, retrieved_at TEXT);

CREATE TABLE judge_accounts (
  judge_id INTEGER REFERENCES judges(judge_id),
  platform TEXT, handle_or_url TEXT, account_kind TEXT, verified_by TEXT,
  active_from TEXT, active_to TEXT, src TEXT, retrieved_at TEXT);

CREATE TABLE cultural_signals (
  judge_id INTEGER REFERENCES judges(judge_id),
  category TEXT, item TEXT, stance TEXT, evidence TEXT,
  source_kind TEXT, source_date TEXT, src TEXT, retrieved_at TEXT);

CREATE TABLE keyword_observations (
  judge_id INTEGER REFERENCES judges(judge_id),
  corpus TEXT, window_id TEXT, keyword TEXT, used INTEGER,
  src TEXT, retrieved_at TEXT);

CREATE TABLE press_mentions (
  judge_id INTEGER REFERENCES judges(judge_id),
  headline TEXT, outlet TEXT, url TEXT, published TEXT, tone REAL,
  topics TEXT, src TEXT, retrieved_at TEXT);

CREATE TABLE opinions (
  judge_id INTEGER REFERENCES judges(judge_id),
  cluster_id INTEGER, case_name TEXT, date_filed TEXT, role TEXT,
  vote_direction INTEGER, text_url TEXT, src TEXT, retrieved_at TEXT);

CREATE TABLE media_sessions (
  judge_id INTEGER REFERENCES judges(judge_id),
  media_kind TEXT, case_ref TEXT, url TEXT, session_date TEXT,
  transcript_path TEXT, diarized INTEGER, src TEXT, retrieved_at TEXT);

CREATE TABLE motion_rulings (
  judge_id INTEGER REFERENCES judges(judge_id),
  case_ref TEXT, motion_class TEXT, movant_role TEXT, movant_pro_se INTEGER,
  filed_date TEXT, signed_date TEXT, entered_date TEXT, disposition TEXT,
  agreed_order INTEGER, src TEXT, retrieved_at TEXT);

CREATE TABLE district_geodemo (
  judicial_district INTEGER, geo_level TEXT, geo_id TEXT, segment_system TEXT,
  segment_code TEXT, segment_label TEXT, share REAL, src TEXT, retrieved_at TEXT);

CREATE TABLE financial_interests (
  judge_id INTEGER REFERENCES judges(judge_id),
  holding TEXT, value_low REAL, value_high REAL, year INTEGER,
  src TEXT, retrieved_at TEXT);

CREATE TABLE data_gaps (
  area TEXT, detail TEXT, blocker TEXT, retrieved_at TEXT);

CREATE VIEW coverage AS
  SELECT 'judges' t,1 o,COUNT(*) n FROM judges
  UNION ALL SELECT 'judge_bio',2,COUNT(*) FROM judge_bio
  UNION ALL SELECT 'retention_elections',3,COUNT(*) FROM retention_elections
  UNION ALL SELECT 'judge_edges',4,COUNT(*) FROM judge_edges
  UNION ALL SELECT 'vacancy_events',5,COUNT(*) FROM vacancy_events
  UNION ALL SELECT 'contributions',6,COUNT(*) FROM contributions
  UNION ALL SELECT 'judge_accounts',7,COUNT(*) FROM judge_accounts
  UNION ALL SELECT 'cultural_signals',8,COUNT(*) FROM cultural_signals
  UNION ALL SELECT 'keyword_observations',9,COUNT(*) FROM keyword_observations
  UNION ALL SELECT 'press_mentions',10,COUNT(*) FROM press_mentions
  UNION ALL SELECT 'opinions',11,COUNT(*) FROM opinions
  UNION ALL SELECT 'media_sessions',12,COUNT(*) FROM media_sessions
  UNION ALL SELECT 'motion_rulings',13,COUNT(*) FROM motion_rulings
  UNION ALL SELECT 'district_geodemo',14,COUNT(*) FROM district_geodemo
  UNION ALL SELECT 'financial_interests',15,COUNT(*) FROM financial_interests;
"""

STATUS = {
    "judges": "POPULATED",
    "judge_bio": "POPULATED",
    "retention_elections": "POPULATED (2026 OJPE slate)",
    "judge_edges": "needs clerkship + law-school cohort pull",
    "vacancy_events": "needs CO nominating commission + press",
    "contributions": "needs FollowTheMoney / OpenSecrets",
    "judge_accounts": "needs campaign-site resolution (retention judges first)",
    "cultural_signals": "needs questionnaires, investiture, oral argument",
    "keyword_observations": "needs corpus + vocabulary build",
    "press_mentions": "needs GDELT",
    "opinions": "needs CourtListener bulk — API has no CO authorship/dissent",
    "media_sessions": "needs cojudicial.ompnetwork.org ingest",
    "motion_rulings": "needs CO AOC bulk docket request",
    "district_geodemo": "needs PRIZM/Mosaic license",
    "financial_interests": "CO judicial disclosure rules — confirm availability",
}


def build():
    if os.path.exists(DB):
        os.remove(DB)
    cx = sqlite3.connect(DB)
    cx.executescript(SCHEMA)
    jid, ids, fids, conflicts = 1, {}, {}, []

    # --- CO Supreme, current bench -----------------------------------------
    for name, joined, gov, party, ls, by, chief, bp_ret in D.SUPREME:
        cx.execute(
            """INSERT INTO judges (judge_id,full_name,court,seat_status,is_chief,
               chief_since,date_start,selection_method,appointing_governor,
               appointing_party,law_school,birth_year,mandatory_retire_year,
               bp_retention_year_reported,src_roster,retrieved_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (jid, name, "CO Supreme", "active", int(chief),
             D.CHIEF_SINCE if chief else None, joined, "assisted_appointment",
             gov, party, ls, by, by + 72 if by else None, bp_ret,
             f"{D.SRC_BP}; {D.SRC_WIKI}; {D.SRC_CJ}", R))
        ids.setdefault(surname(name), jid)
        fids[fullkey(name)] = jid
        jid += 1

    # --- CO Supreme, historic (CourtListener) -------------------------------
    for clid, name, start, term, dob in D.HISTORIC:
        sn = surname(name)
        if sn in ids:
            cx.execute("""UPDATE judges SET courtlistener_id=COALESCE(courtlistener_id,?),
                          date_dob=COALESCE(date_dob,?) WHERE judge_id=?""",
                       (clid, dob, ids[sn]))
            continue
        cx.execute(
            """INSERT INTO judges (judge_id,full_name,court,seat_status,date_start,
               date_termination,selection_method,courtlistener_id,date_dob,
               src_roster,retrieved_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (jid, name, "CO Supreme", "retired" if term else "unknown", start, term,
             "assisted_appointment", clid, dob,
             "CourtListener positions?court=colo", R))
        ids.setdefault(sn, jid)
        fids[fullkey(name)] = jid
        jid += 1

    # --- 2026 OJPE retention slate: appellate --------------------------------
    def upsert(name, court, dist=None, county=None, src=None):
        """Insert or merge one roster person, keyed on the normalised full name."""
        nonlocal jid
        fk = fullkey(name)
        if fk in fids:
            j = fids[fk]
            # a judge already seeded from another source gains district/county here
            cx.execute("""UPDATE judges
                          SET judicial_district=COALESCE(judicial_district,?),
                              county=COALESCE(county,?)
                          WHERE judge_id=?""", (dist, county, j))
            return j
        cx.execute(
            """INSERT INTO judges (judge_id,full_name,court,judicial_district,county,
               seat_status,selection_method,src_roster,retrieved_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (jid, name, court, dist, county, "active", "assisted_appointment",
             src or D.SRC_OJPE26_FULL, R))
        fids[fk] = jid
        ids.setdefault(surname(name), jid)
        jid += 1
        return fids[fk]

    def retention(j, name, rec):
        cx.execute("""INSERT INTO retention_elections
                      (judge_id,year,ojpe_recommendation,src,retrieved_at)
                      VALUES (?,?,?,?,?)""",
                   (j, 2026, rec, D.SRC_OJPE26_FULL, R))

    for name, court, dist, rec in D.OJPE_2026_APPELLATE:
        j = upsert(name, court, dist)
        retention(j, name, rec)

    for dist, rows in D.OJPE_2026_DISTRICT.items():
        for name, rec in rows:
            j = upsert(name, "CO District", dist=dist)
            retention(j, name, rec)

    # county judges sit in a judicial district too - carry it so district-level
    # joins (geodemo, auditioning) reach them instead of hitting NULL
    for county, (dist, rows) in D.OJPE_2026_COUNTY.items():
        for name, rec in rows:
            j = upsert(name, "CO County", dist=dist, county=county)
            retention(j, name, rec)

    # --- district judges already in the workspace ---------------------------
    for name, dist, status in D.WORKSPACE_DISTRICT:
        sn = surname(name)
        if sn in ids:
            cx.execute("UPDATE judges SET judicial_district=COALESCE(judicial_district,?) "
                       "WHERE judge_id=?", (dist, ids[sn]))
            continue
        cx.execute(
            """INSERT INTO judges (judge_id,full_name,court,judicial_district,seat_status,
               selection_method,src_roster,retrieved_at) VALUES (?,?,?,?,?,?,?,?)""",
            (jid, name, "CO District", dist, status, "assisted_appointment",
             "local:verifier/judicial-intel/judges/", R))
        ids[sn] = jid
        jid += 1

    cx.execute("""UPDATE judges SET appointing_governor='Bill Owens',
                  appointing_party='R', law_school='Colorado', birth_year=1948,
                  is_chief=0, seat_status='retired' WHERE full_name='Nathan B. Coats'""")
    for name, field, value, year in D.COATS_BIO:
        cx.execute("INSERT INTO judge_bio VALUES (?,?,?,?,?,?)",
                   (ids[surname(name)], field, value, year, D.SRC_COATS, R))

    for name, field, value, year in D.BIO_SEED:
        cx.execute("INSERT INTO judge_bio VALUES (?,?,?,?,?,?)",
                   (ids[surname(name)], field, value, year, D.SRC_OJPE_LOC, R))

    # law school / birth year also land as bio rows for uniform querying
    for name, joined, gov, party, ls, by, chief, _ in D.SUPREME:
        j = ids[surname(name)]
        cx.execute("INSERT INTO judge_bio VALUES (?,?,?,?,?,?)",
                   (j, "law_school", ls, None, D.SRC_WIKI, R))
        cx.execute("INSERT INTO judge_bio VALUES (?,?,?,?,?,?)",
                   (j, "birth_year", str(by), by, D.SRC_WIKI, R))

    # --- known gaps ---------------------------------------------------------
    gaps = [
        ("county judges", "CLOSED 2026-09-06. The earlier truncation after Jefferson "
         "was an artefact of the paginated know-your-judges landing page. The OJPE "
         "full-list page enumerates every district and county and states explicitly "
         "where nobody is standing, so counties K-Z are now captured (16 further "
         "county judges) and the empties are verified empties",
         None, R),
        ("judicial_district", "CORRECTED 2026-09-06. The column previously held the "
         "ordinal position of each section on the OJPE landing page, not the judicial "
         "district. 52 of 65 district judges carried a wrong district (Datz stored 3, "
         "actually 17th; Amico stored 4, actually 18th; Kotlarczyk stored 5, actually "
         "20th). Any analysis joined on district before this date is invalid",
         None, R),
        ("roster completeness", "The earlier landing-page pull missed 28 judges, "
         "including the entire 10th, 19th and 21st district benches. A second judge "
         "DOES NOT MEET standards - William David Alexander, 10th JD (Pueblo) district "
         "judge - which the earlier file did not have; Boyce was not the only one",
         None, R),
        ("qualified recommendation", "Dina M. Christiansen (13th JD) is listed as "
         "MEETS PERFORMANCE STANDARDS** with a footnote directing readers to the "
         "evaluation narrative; stored as MEETS_QUALIFIED, not flattened to MEETS",
         "read the 13th JD narrative to find what the asterisk qualifies", R),
        ("surname collisions", "upsert() keyed identity on surname alone until "
         "2026-09-06, which silently dropped Costilla County's Tamara McSherry "
         "Sullivan and attached her retention row to Grant Sullivan (CoA). The 2026 "
         "slate also holds two Larsons, two Hendersons and a Thomas/Martinez-Thomas "
         "pair. Identity is now the normalised full name",
         None, R),
        ("retention year", "Ballotpedia 'next retention' conflicts with OJPE 2026 slate "
         "(lists Hood 2024, OJPE has him standing 2026)",
         "treat bp_retention_year_reported as unverified; OJPE is authoritative", R),
        ("CO opinions", "CourtListener has no author/dissent typing for colo; all "
         "sub-opinions are 010combined with null author",
         "parse opinion text, or CourtListener bulk", R),
        ("local OJPE csv", "5 of 6 judicialperformance*.csv in workspace are browser "
         "table-scrapes of nav menus and Google Translate lists",
         "discard; refetch from source", R),
        ("workspace district judges", "Norrdin, Neiley, Seldin, Makar not on the 2026 "
         "retention slate", "confirm current seat status per judge", R),
    ]
    cx.executemany("INSERT INTO data_gaps VALUES (?,?,?,?)", gaps)
    cx.commit()

    # --- report -------------------------------------------------------------
    print(f"{'TABLE':<22}{'ROWS':>6}   STATUS")
    print("-" * 74)
    for t, _, n in cx.execute("SELECT t,o,n FROM coverage ORDER BY o"):
        print(f"{t:<22}{n:>6}   {STATUS.get(t,'')}")

    print("\nBY COURT")
    for c, n in cx.execute("SELECT court,COUNT(*) FROM judges GROUP BY court ORDER BY 2 DESC"):
        print(f"  {c:<22}{n:>4}")

    print("\nFLAGGED")
    for r in cx.execute("""SELECT j.full_name, j.court, COALESCE(j.county, 'District '||j.judicial_district),
                           re.ojpe_recommendation FROM retention_elections re
                           JOIN judges j USING(judge_id)
                           WHERE re.ojpe_recommendation LIKE 'DOES NOT%'"""):
        print("  " + " | ".join(str(x) for x in r))

    print("\nGAPS")
    for a, d, b, _ in cx.execute("SELECT * FROM data_gaps"):
        print(f"  [{a}] {d}\n      -> {b}")

    with open("co_judges_roster.csv", "w", newline="") as f:
        cur = cx.execute("SELECT * FROM judges ORDER BY court, judicial_district, county, full_name")
        w = csv.writer(f)
        w.writerow([d[0] for d in cur.description])
        w.writerows(cur)
    cx.close()
    print(f"\nwrote {DB} + co_judges_roster.csv")


if __name__ == "__main__":
    build()
