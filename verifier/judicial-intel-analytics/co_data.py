"""
co_data.py — verified Colorado judicial data, repulled 2026-09-06.

Every record carries its source. Where sources conflict, both are kept and the
conflict is flagged rather than silently resolved.
"""

RETRIEVED = "2026-09-06"

SRC_BP      = "https://ballotpedia.org/Colorado_Supreme_Court"
SRC_WIKI    = "https://en.wikipedia.org/wiki/Colorado_Supreme_Court"
SRC_CJ      = "https://www.coloradojudicial.gov/supreme-court/supreme-court-judges-and-staff"
SRC_OJPE26  = ("https://judicialperformance.colorado.gov/know-your-judges/"
               "2026-judicial-performance-evaluations")
SRC_OJPE_LOC = ("local:verifier/judicial-intel/judges/judicialperformance.csv "
                "(judicialperformance.colorado.gov)")

# ---------------------------------------------------------------------------
# CO Supreme Court — current bench.
# Chief Justice confirmed by coloradojudicial.gov; bio detail from Wikipedia.
# NOTE: Ballotpedia's "next retention" column conflicts with the OJPE 2026 slate
# (it lists Hood at 2024, but OJPE has him standing in 2026). Ballotpedia values
# are stored separately and flagged, not treated as fact.
# ---------------------------------------------------------------------------
SUPREME = [
    # name, joined, governor, party, law_school, birth_year, is_chief, bp_retention
    ("Monica M. Márquez",         "2010-12-10", "Bill Ritter",       "D", "Yale",     1969, True,  2020),
    ("Brian D. Boatright",        "2011-01-01", "John Hickenlooper", "D", "Denver",   1962, False, 2025),
    ("William W. Hood III",       "2014-01-13", "John Hickenlooper", "D", "Virginia", 1963, False, 2024),
    ("Richard L. Gabriel",        "2015-01-01", "John Hickenlooper", "D", "Penn",     1962, False, 2025),
    ("Carlos Armando Samour Jr.", "2018-01-01", "John Hickenlooper", "D", "Denver",   1966, False, 2028),
    ("Maria E. Berkenkotter",     "2021-01-01", "Jared Polis",       "D", "Denver",   1962, False, 2031),
    ("Susan Blanco",              "2026-01-01", "Jared Polis",       "D", "Boulder",  1977, False, 2036),
]
CHIEF_SINCE = "2024-07-26"

# ---------------------------------------------------------------------------
# 2026 OJPE retention slate, from the OJPE **full list** page (below), which is
# the complete slate. An earlier pull used the "know-your-judges" landing page,
# which is paginated/truncated and yielded 96 rows keyed by page-section ordinal
# rather than judicial district. Every district number below is the real one.
#
# Corrections this repull made:
#   - judicial_district was ordinal, not the district number. 52 of 65 district
#     judges carried a wrong district (e.g. Datz stored 3, actually 17th).
#   - 28 judges were missing entirely, including all of the 10th, 19th and 21st
#     district benches and every county after Jefferson.
#   - A SECOND judge does not meet standards: William David Alexander, 10th JD
#     district judge (Pueblo). The earlier file had only Boyce.
#   - Dina M. Christiansen carries an asterisked recommendation pointing to the
#     evaluation narrative; kept distinct rather than flattened to plain MEETS.
MEETS = "MEETS PERFORMANCE STANDARDS"
NOT_MEETS = "DOES NOT MEET PERFORMANCE STANDARDS"
# Printed on the source page as "MEETS PERFORMANCE STANDARDS**" with the footnote
# "Please see evaluation narrative for more details."
MEETS_QUALIFIED = "MEETS PERFORMANCE STANDARDS (qualified - see narrative)"

SRC_OJPE26_FULL = ("https://judicialperformance.colorado.gov/"
                   "2026-judicial-performance-evaluations-full-list")

OJPE_2026_APPELLATE = [
    ("William W. Hood, III",     "CO Supreme",           None, MEETS),
    ("Rebecca Rankin Freyre",    "CO Court of Appeals",  None, MEETS),
    ("Elizabeth L. Harris",      "CO Court of Appeals",  None, MEETS),
    ("Katharine E. Lum",         "CO Court of Appeals",  None, MEETS),
    ("Pax Moultrie",             "CO Court of Appeals",  None, MEETS),
    ("Karl L. Schock",           "CO Court of Appeals",  None, MEETS),
    ("Grant Sullivan",           "CO Court of Appeals",  None, MEETS),
]

# district number -> [(judge, recommendation)]
# Districts 5, 6, 8 and 16 have no district judges standing in 2026 (the page
# says so explicitly); that is a verified empty, not a gap.
OJPE_2026_DISTRICT = {
    1:  [("Chantel E. Contiguglia", MEETS), ("Ryan P. Loewer", MEETS),
         ("Meegan Miloud", MEETS), ("Andrew C. Poland", MEETS),
         ("Christopher Rhamey", MEETS), ("Tamara S. Russell", MEETS),
         ("Christopher C. Zenisek", MEETS)],
    2:  [("Christopher J. Baumann", MEETS), ("Michael W.V. Angel", MEETS),
         ("John Eric Elliff", MEETS), ("Lisa Gomez", MEETS),
         ("Elizabeth D. Leith", MEETS), ("Andrew Luxen", MEETS),
         ("Elizabeth Joan McCarthy", MEETS), ("Jon J. Olafson", MEETS),
         ("Sarah Block Wallace", MEETS)],
    3:  [("Pierce L. Fowler", MEETS)],
    4:  [("Erin Lynn Sokol", MEETS), ("William B. Bain", MEETS),
         ("Hilary Gurney", MEETS), ("Dennis L. McGuire", MEETS),
         ("Amanda J. Philipps", MEETS), ("Gregory Robert Werner", MEETS)],
    7:  [("D. Cory Jackson", MEETS), ("Kellie L. Starritt", MEETS)],
    9:  [("Elise Myer", MEETS)],
    10: [("William David Alexander", NOT_MEETS), ("Michelle Chostner", MEETS),
         ("Allison P. Ernst", MEETS), ("Tayler M. Thomas", MEETS)],
    11: [("Amanda Hunter", MEETS), ("Dayna L. Vise", MEETS)],
    12: [("Amanda C. Hopkins", MEETS), ("Michael A. Gonzales", MEETS)],
    13: [("Dina M. Christiansen", MEETS_QUALIFIED)],
    14: [("Brittany Schneider", MEETS)],
    15: [("Tarryn L. Johnson", MEETS)],
    17: [("Caryn A. Datz", MEETS), ("Sean Patrick Finn", MEETS),
         ("Priscilla Loew", MEETS), ("Jeffrey Dean Ruff", MEETS),
         ("Kelley R. Southerland", MEETS)],
    18: [("Michelle Ann Amico", MEETS), ("LaQunya Latrese Baker-McKay", MEETS),
         ("Jacob A. Edson", MEETS), ("Thomas W. Henderson", MEETS),
         ("Michelle Jones", MEETS), ("David N. Karpel", MEETS),
         ("Natalie G. Stricklin", MEETS), ("Darren L. Vahle", MEETS),
         ("Christine A. Washburn", MEETS)],
    19: [("Audrey A. Galloway", MEETS), ("Timothy Gerard Kerns", MEETS)],
    20: [("Nancy Woodruff Salomone", MEETS), ("Michael Kotlarczyk", MEETS),
         ("J. Chris Larson", MEETS)],
    21: [("Jeremy Chaffin", MEETS), ("Craig Peter Henderson", MEETS),
         ("Gretchen B. Larson", MEETS), ("JenniLynn E. Lawrence", MEETS)],
    22: [("William Young Furse", MEETS)],
    23: [("Andrew Baum", MEETS), ("Victoria E. Klingensmith", MEETS),
         ("Theresa Slade", MEETS), ("Daniel W. Warhola", MEETS)],
}

# county -> (judicial district, [(judge, recommendation)])
# County judges sit in a judicial district too; that mapping was previously NULL
# for every county judge, which broke any district-level join.
OJPE_2026_COUNTY = {
    "Gilpin":     (1,  [("Timothy Lane", MEETS)]),
    "Jefferson":  (1,  [("Sara Garrido", MEETS), ("Corinne Magid", MEETS),
                        ("Jennifer Lynn Melton", MEETS)]),
    "Denver":     (2,  [("Kerri Lombardi", MEETS), ("Andrea Eddy", MEETS),
                        ("Olympia Z. Fay", MEETS), ("Chelsea Malone", MEETS),
                        ("Michelle Martinez-Thomas", MEETS),
                        ("Isaam L. Shamsid-Deen", MEETS), ("Judith Smith", MEETS)]),
    "Huerfano":   (3,  [("Dawn Mann", MEETS)]),
    "El Paso":    (4,  [("Sam Burney", MEETS), ("Marika Frady", MEETS),
                        ("Meredith Patrick Cord", MEETS), ("Ann M. Rotolo", MEETS)]),
    "Eagle":      (5,  [("Inga Haagenson Causey", MEETS)]),
    "Hinsdale":   (7,  [("James R. McDonald", MEETS)]),
    "Jackson":    (8,  [("Chelsea Williams Ryan", MEETS)]),
    "Larimer":    (8,  [('Katharine "Jenny" Ellison', MEETS),
                        ("Thomas L. Lynch", MEETS), ("Matthew R. Zehe", MEETS)]),
    "Garfield":   (9,  [("Jonathan Bruce Pototsky", MEETS)]),
    "Rio Blanco": (9,  [("Jay A. Edwards", MEETS)]),
    "Custer":     (11, [("Michael Patrick Halpin", MEETS)]),
    "Fremont":    (11, [("Alexandra Robak", MEETS)]),
    "Park":       (11, [("Brian Louis Green", MEETS)]),
    "Alamosa":    (12, [("Daniel Walzl", MEETS)]),
    "Costilla":   (12, [("Tamara McSherry Sullivan", MEETS)]),
    "Mineral":    (12, [("Hollie Wheelwright", MEETS)]),
    "Washington": (13, [("Kelly S. Hansen", MEETS)]),
    "Grand":      (14, [("Nicholas Catanzarite", MEETS)]),
    "Moffat":     (14, [("James Hesson", MEETS)]),
    "Prowers":    (15, [("Curtis Lane Porter", MEETS)]),
    "Crowley":    (16, [("Jeremy P. Boyce", NOT_MEETS)]),
    "Otero":      (16, [("William Culver", MEETS)]),
    "Adams":      (17, [("Lara M. Jimenez", MEETS),
                        ('MaryAnn "Mariana" Vielma', MEETS)]),
    "Arapahoe":   (18, [("Christina Marie Apostoli", MEETS),
                        ("Colleen Clark", MEETS), ("Cheryl Rowles-Stokes", MEETS)]),
    "Weld":       (19, [("John J. Briggs", MEETS), ("Michele Lynn Meyer", MEETS),
                        ("Dana Nichols", MEETS)]),
    "Boulder":    (20, [("Elizabeth House Moulton Brodsky", MEETS),
                        ("Monica Haenselman", MEETS),
                        ("Zachary Ilya Malkinson", MEETS)]),
    "Mesa":       (21, [("Scott Joseph Burrill", MEETS), ("Bruce R. Raaum", MEETS)]),
    "Douglas":    (23, [("Lawrence Bowling", MEETS), ("Kolony L. Fields", MEETS)]),
}

# The full-list page enumerates every district and every county, stating
# explicitly where nobody is standing, so the slate is now complete rather than
# alphabetically truncated. Retained as a constant so the old gap row can be
# closed rather than silently dropped.
COUNTY_TRUNCATED_AFTER = None

# ---------------------------------------------------------------------------
# Historic CO Supreme Court, from CourtListener positions?court=colo
# ---------------------------------------------------------------------------
HISTORIC = [
    # Coats is the roster's only Republican appointee and its most recent former
    # Chief Justice. He was absent from both the Ballotpedia current bench and the
    # CourtListener pull, and surfaced only because his name appeared 16 times as an
    # unmatched token in the panel strings. Source: en.wikipedia.org/wiki/Nathan_B._Coats
    (None, "Nathan B. Coats",       "2000-01-01", "2020-12-31", "1948-01-01"),
    (3931, "Nancy E. Rice",         "1998-08-05", None,         "1950-06-02"),
    (3909, "Gregory J. Hobbs Jr.",  "1996-04-18", None,         "1944-01-01"),
    (3902, "Allison H. Eid",        "2006-03-13", None,         "1965-01-01"),
    (3927, "Mary J. Mullarkey",     "1987-06-29", "2010-11-30", "1943-04-25"),
    (3924, "Alex J. Martinez",      "1997-01-01", "2011-10-31", "1951-01-01"),
    (3917, "Rebecca Love Kourlis",  "1995-05-01", "2006-01-10", "1952-11-11"),
    (3934, "Gregory K. Scott",      "1993-01-12", "2000-03-15", "1943-01-01"),
    (3938, "Anthony Vollack",       "1986-02-01", "1998-07-31", "1929-01-01"),
    (3915, "Howard M. Kirshbaum",   "1983-05-02", "1997-01-14", "1938-06-17"),
    (3921, "George E. Lohr",        "1979-12-14", "1997-01-14", "1931-07-15"),
    (3903, "William H. Erickson",   "1971-02-03", "1996-05-01", "1924-09-16"),
    (3932, "Luis D. Rovira",        "1979-02-01", "1995-06-30", "1923-01-01"),
    (3930, "Joseph R. Quinn",       "1980-06-02", "1993-01-12", "1932-03-14"),
    (3901, "Jean E. Dubofsky",      "1979-07-16", "1987-06-29", "1942-05-11"),
    (3928, "William D. Neighbors",  "1983-01-11", "1986-02-01", "1939-09-05"),
    (3937, "Leonard v. B. Sutton",  "1956-03-02", "1968-04-01", "1914-12-21"),
    (3929, "Edward E. Pringle",     "1961-10-30", "1979-07-10", "1914-04-12"),
    (3919, "Robert B. Lee",         "1969-01-11", "1983-01-11", "1912-11-21"),
    (3910, "Paul V. Hodges",        "1967-01-01", "1987-01-13", "1913-12-27"),
    (3905, "James K. Groves",       "1968-05-13", "1980-04-06", "1910-11-28"),
]

# ---------------------------------------------------------------------------
# District judges already in the workspace (judge folders)
# ---------------------------------------------------------------------------
WORKSPACE_DISTRICT = [
    ("Michael A. O'Hara III", 14, "active"),
    ("Anne K. Norrdin",        9, "active"),
    ("John F. Neiley",         9, "active"),
    ("Christopher G. Seldin",  9, "former"),
    ("Laura C. Makar",      None, "active"),
]

# Verified bio facts, OJPE evaluation text held locally
COATS_BIO = [
    ("Nathan B. Coats", "law_school", "University of Colorado Law School", 1977),
    ("Nathan B. Coats", "undergrad", "undergraduate degree", 1971),
    ("Nathan B. Coats", "prior_role", "US Army officer, military intelligence, Germany (3 yrs)", None),
    ("Nathan B. Coats", "prior_role", "Private practice, Longmont", 1977),
    ("Nathan B. Coats", "prior_role", "CO Attorney General appellate unit", 1978),
    ("Nathan B. Coats", "prior_role", "Chief appellate deputy DA, Denver", 1986),
    ("Nathan B. Coats", "appointment", "Appointed by Gov. Bill Owens (R)", 2000),
    ("Nathan B. Coats", "role", "Chief Justice", 2018),
]
SRC_COATS = "https://en.wikipedia.org/wiki/Nathan_B._Coats"

BIO_SEED = [
    ("Michael A. O'Hara III", "birthplace",  "California", None),
    ("Michael A. O'Hara III", "undergrad",   "St. Mary's Seminary (Missouri)", None),
    ("Michael A. O'Hara III", "law_school",  "University of San Diego", 1984),
    ("Michael A. O'Hara III", "prior_role",  "Litigation practice, San Diego (~7 yrs)", 1984),
    ("Michael A. O'Hara III", "prior_role",  "Managing partner, Steamboat Springs firm (11 yrs)", 1991),
    ("Michael A. O'Hara III", "practice_area", "Family law, personal injury, criminal defense", None),
    ("Michael A. O'Hara III", "award",       "NW Colorado Bar Assn Professionalism Award", 1999),
    ("Michael A. O'Hara III", "appointment", "District Judge, 14th JD (Moffat/Routt/Grand)", 2003),
    ("Michael A. O'Hara III", "award",       "Judicial Excellence Award, CO Judicial Institute", 2016),
    ("Michael A. O'Hara III", "prior_role",  "Chief Judge, 14th JD; Water Judge Division 6", None),
]
