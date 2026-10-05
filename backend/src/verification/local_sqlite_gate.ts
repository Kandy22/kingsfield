/**
 * Gate 1 (Existence), local SQLite pre-filter. Constraint A / Constraint D.
 *
 * Synchronous, deterministic, no network, no model calls. Opens
 * kingsfield_florida.db read-only with node:sqlite; if node:sqlite cannot load, runs
 * pipeline/gate1.py synchronously under ~/.venv-cascade/bin/python. Fails closed: any
 * error, unparseable input, missing database or missing table is a veto.
 *
 * Verdicts:
 *   pass          Florida citation found locally; caption (if given) and pin (if given) check out.
 *   veto          Florida (or malformed Southern Reporter) citation that fails any check, or any error.
 *   fall_through  Not a Florida key; the caller sends it to CourtListener citationLookup().
 *
 * This is a line-for-line mirror of pipeline/gate1.py (the reference gate); parity is tested in
 * pipeline/builder_tests. The grammar is ASCII-only on purpose: input is NFKC-normalized and
 * whitespace-collapsed, then matched exactly, so a homoglyph, non-ASCII digit or zero-width
 * character that survives normalization fails to parse and is vetoed.
 *
 * Self-contained: node: builtins only and erasable TypeScript syntax, so plain `node` can load
 * this file directly via type stripping. Not wired into pipeline.ts.
 */

import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { homedir } from 'node:os';
import { join, resolve } from 'node:path';

export type Gate1Verdict = 'pass' | 'veto' | 'fall_through';

export type Gate1Result = {
  verdict: Gate1Verdict;
  reason: string;
  reporter?: string;
  volume?: number;
  page?: number;
  clusterId?: number | null;
};

export type LocalGate1Options = {
  dbPath?: string;
  /** Skip node:sqlite and use the Python child process (tests; also what a load failure does). */
  forcePythonFallback?: boolean;
};

const MAX_CITATION_CHARS = 2000;
const DB_TIMEOUT_MS = 2000;
const PY_TIMEOUT_MS = 10000;

// Caption similarity: Jaccard over pg_trgm-style trigrams, integer arithmetic only.
const JACCARD_NUM = 1;
const JACCARD_DEN = 2;
const CONTAINMENT_NUM = 9;
const CONTAINMENT_DEN = 10;
const CONTAINMENT_MIN_TRIGRAMS = 8;

// ---------------------------------------------------------------------------
// Reporter tables. Generated from reporters_db (Python) and asserted equal to it
// by pipeline/builder_tests/test_reporter_table_sync.py.
// ---------------------------------------------------------------------------

const SOUTHERN_EXACT: Record<string, string> = {
  'SO.': 'So.',
  'So.': 'So.',
  'So. 2d': 'So. 2d',
  'So. 2d.': 'So. 2d',
  'So. 2nd': 'So. 2d',
  'So. 3d': 'So. 3d',
  'So. Rep.': 'So.',
  'So. Rep. 2d': 'So. 2d',
  'So. Rep. 3d': 'So. 3d',
  'So. Reporter': 'So.',
  'So.2d': 'So. 2d',
  'So.3d': 'So. 3d',
  'Sou.': 'So.',
  'Sou. Rep.': 'So.',
  'South': 'So.',
  'South.': 'So.',
  'South. Rep.': 'So.',
  'South.2d': 'So. 2d',
  'South.3d': 'So. 3d',
};

const IN_SCOPE_LOOSE: ReadonlySet<string> = new Set([
  'flalweekly', 'flalweeklysupp', 's2nd', 'so', 'so2d', 'so2dseries', 'so2nd', 'so2ndseries',
  'so3d', 'sorep', 'sorep2d', 'sorep3d', 'soreporter', 'sou', 'sou2nd', 'sourep', 'south',
  'south2d', 'south3d', 'southrep',
]);

// Every reporter spelling reporters_db recognizes (editions and variations, ASCII-token only).
// Generated from reporters_db; asserted equal by test_reporter_table_sync.py. A recognized
// reporter that is not a Florida key falls through even when cited with a Florida court
// (Constraint A); an unrecognized one with a Florida court vetoes.
const KNOWN_REPORTERS: ReadonlySet<string> = new Set([
  "A .2d", "A.", "A. 2d", "A. 3d", "A.2d", "A.2d.", "A.3d", "A.3d.", "A.D.", "A.D. 2d", "A.D. 3d",
  "A.D. Cases", "A.D.2d", "A.D.3d", "A.E.C.", "A.F.Rep.", "A.F.T.R.", "A.F.T.R. 2d", "A.F.T.R.2d",
  "A.K. Marsh.", "A.L.R.", "A.L.R. 2d", "A.L.R. 3d", "A.L.R. 4th", "A.L.R. 5th", "A.L.R. 6th", "A.L.R. Fed.",
  "A.L.R. Fed. 2d", "A.L.R. Fed.2d", "A.L.R.2d", "A.L.R.3d", "A.L.R.4th", "A.L.R.5th", "A.L.R.6th",
  "A.L.T. Bankr.", "A.M.C.", "A.N.", "A.N.C.", "A.R.", "A.Rep.", "A2d", "AD", "AD 2d", "AD 3d", "AD2d",
  "AD3d", "ALR", "ALR 2d", "ALR 3d", "ALR 4th", "ALR 5th", "ALR 6th", "AMC", "AOA", "ARK.", "AWCC", "AZ",
  "Abb", "Abb.", "Abb. Adm.", "Abb. Ct. App.", "Abb. Ct. App. Dec.", "Abb. N. C.", "Abb. N. Cas.",
  "Abb. Pr.", "Abb. Rep.", "Abb. U. S.", "Abb.N. Cas.", "Abb.N.C.", "Abb.N.Cas.", "Abb.P.R.", "Abb.Pr.Rep.",
  "Abb.Prac.", "Abbott P.R.", "Abbott Pr.Rep.", "Abbott Pract.Cas.", "Abbott's Pr.Rep.",
  "Abbott's Prac.Rep.", "Abbotts", "Abs", "Abs.", "Add.", "Adm. Rec.", "Adv. S.", "Adv.S.", "Agric. Dec",
  "Agric. Dec.", "Aik.", "Aik. Rep.", "Ak.", "Ak. App.", "Ala.", "Ala. 2d", "Ala. App.", "Ala. App. LEXIS",
  "Ala. Civ. App. LEXIS", "Ala. Crim. App. LEXIS", "Ala. LEXIS", "Ala. Rep.", "Ala.App.", "Alas. App. LEXIS",
  "Alas. LEXIS", "Alaska", "Alaska Fed.", "Alaska Fed.R.", "Alaska Fed.Rep.", "Alb. Law J.", "Alk.", "All.",
  "All. Rep.", "Allen", "Am Dec.", "Am Law Rev.", "Am. & Eng. R. Cas.", "Am. Ann. Cas.", "Am. B.R.",
  "Am. D.", "Am. Dec's.", "Am. Dec.", "Am. Disabilities Dec.", "Am. Jur.", "Am. L. C.", "Am. L. Cas",
  "Am. Law J.", "Am. Law Rec.", "Am. Law Reg.", "Am. Law Rev.", "Am. Law T.", "Am. Law T. Rep.",
  "Am. Law T. Rep. Bankr.", "Am. Law T. Rep. U. S. Cts.", "Am. Law T. Rep. U.S. Cts.", "Am. Law. Rec.",
  "Am. Lead. Cas.", "Am. Leading Cas", "Am. Neg. Ca.", "Am. Neg. Cas.", "Am. Neg. Cases", "Am. Negl. Cas.",
  "Am. Rep.", "Am. Reports", "Am. Ry. Rep.", "Am. S. R.", "Am. Samoa", "Am. Samoa 2d", "Am. Samoa 3d",
  "Am. St. R.", "Am. St. Rep.", "Am. Tribal Law", "Am.Ann.Cas.", "Am.Negl.Cas.", "Am.Rep.", "Am.S.R.",
  "Am.St.R.", "Am.St.Rep.", "Amer. Jur.", "Amer. L. Rev.", "Amer. Law J.", "Amer. Law Reg.",
  "Amer. Law Rev.", "Amer. Law T. Rep.", "American Leading Cases", "Anderson's Ohio App. Cas.",
  "Ant. N.P. Cas.", "Anth.", "Ap.", "Ap.2d.", "App Div", "App Div.", "App.", "App. Com'r Pat.",
  "App. Com'r of Pat.", "App. Com'r. Pat.", "App. Com'rs Pat.", "App. Com. Pat.", "App. Comm. Pat.",
  "App. Comr. Pat.", "App. D.C.", "App. Div", "App. Div.", "App. Div. 2d", "App. Div. 2d.", "App. Div. 3d",
  "App. Div. 3d.", "App. Div. Rep.", "App.D.C.", "App.Div.", "App.Div.2d.", "App.Div.3d.", "Ariz.",
  "Ariz. Adv. Rep.", "Ariz. App.", "Ariz. App. LEXIS", "Ariz. App. Unpub. LEXIS", "Ariz. LEXIS",
  "Ariz. Tax LEXIS", "Ariz. Unpub. LEXIS", "Ariz.App.", "Arizona Cases Digest", "Ark", "Ark App", "Ark.",
  "Ark. Adv. Op.", "Ark. App'x", "Ark. App.", "Ark. App. LEXIS", "Ark. Appx.", "Ark. LEXIS", "Ark. Rep.",
  "Ark. Terr. Rep.", "Ark.App.", "Armstrong. Election Cases", "At.", "At. Rep.", "Atl.", "Atl. Rep.",
  "Atl.2d", "Atl.R.", "Auto. Cas.", "Auto. Cas. 2d", "Auto. Cas.2d", "Av. Cas.", "B Stockton", "B.",
  "B. Mon", "B. Mon.", "B. Mon. Rep.", "B. R.", "B. Stockton", "B.C.D.", "B.R.", "B.Stockton", "B.T.A.",
  "BCA", "BNA IER CAS", "BNA OSHC", "BNH", "BR", "BTA LEXIS", "BTR", "Backes", "Bai.", "Bai.Eq.", "Bail.",
  "Bail. Eq.", "Bail. Rep.", "Bail.L.", "Bailey", "Bailey Ch.", "Bailey Eq.", "Bailey Rep.", "Bald",
  "Bald. C.C.", "Baldw", "Baldw.", "Baldwin's C.C. U.S. Rep", "Baldwin's Rep.", "Balt. C. Rep.",
  "Balt. Law Trans.", "Ban. & A.", "Bankr. Ct. Dec.", "Bankr. Ct. Rep.", "Bankr. L. Rep.", "Bankr. LEXIS",
  "Bankr. Reg. Supp.", "Bankr.Ct.Dec.", "Barb.", "Barb. Ch.", "Barb. Ch. Rep.", "Barb. Rep.", "Barb.S.C.",
  "Bax.", "Baxt.", "Baxter", "Bay", "Bayard's Notebook", "Bedell", "Bee", "Bee.", "Beeler", "Ben", "Ben.",
  "Bett's D. C. MS.", "Betts D. C. MS.", "Betts' C. C. MS.", "Betts' D. C. MS.", "Betts' D. C. MSS.",
  "Betts' Dec.", "Betts' Scr. Bk.", "Betts. C. C. MS.", "Betts. D C. MS.", "Betts. D. C. MS.",
  "Betts. D. C. MSS.", "Bibb", "Bibb Rep.", "Bigelow's Insurance Reports", "Bigelow. Ins. Rep.", "Bin.",
  "Bin. Rep.", "Binn.", "Binn. Rep.", "Biss", "Biss.", "Bissell", "Bk. Reg.", "Bl.", "Bl. C.C.",
  "Bl. C.C.R.", "Black", "Black R.", "Black Rep.", "Black.", "Black. Rep.", "Blackf.", "Blackf. Rep.",
  "Bland", "Blat. C.C.R.", "Blatch", "Blatchf.", "Blatchf. & H.", "Blatchf. C.C.", "Blatchf. C.C. Rep.",
  "Blatchf. Pr. Cas.", "Blatchf. Prize Cas.", "Blm. Neg.", "Bloom. Man.", "Bloom. Man. Neg. Cas.",
  "Blue Sky L. Rep.", "Blume Op.", "Blume Sup. Ct. Trans.", "Blume Sup.Ct.Trans.", "Blume Unrep. Op.",
  "Bond", "Bond.", "Bosw.", "Bosworth Super. Ct. Rep.", "Boyce", "Brad.", "Bradf.", "Bradford", "Brayt.",
  "Breese", "Brev.", "Brev. Rep.", "Brief Times Rptr.", "Brightly", "Brock.", "Brock. Rep.", "Brown Adm",
  "Brown Adm.", "Brown's Adm", "Brown's Adm.", "Brown. Adm.", "Brun. Col. Cas.", "Brunn. Coll. Cas.",
  "Brunner. Col. Cas.", "Buch.", "Buchan.", "Buchanan", "Buchanan.", "Bur.", "Bur. Rep.", "Burnett",
  "Burr's Trial", "Busb.", "Busb. Eq.", "Busb.L.", "Bush", "C.", "C. C. A.", "C. C. A. Rep.", "C. Cls.",
  "C. Cls. R.", "C.& C.", "C.B.", "C.B.C.", "C.C.", "C.C.A.", "C.C.L.J.", "C.C.P.A.", "C.I.T.", "C.M.A.",
  "C.M.R.", "CAAF LEXIS", "CCA LEXIS", "CCH OSHD", "CCH Tax Ct. Mem.", "CCH Unemployment Ins. Rep.",
  "CCPA LEXIS", "CIT", "CJ C.A.R.", "CLR", "CMA LEXIS", "CMR", "CMR LEXIS", "CO", "COA", "CSCR", "Cai.",
  "Cai. Cas.", "Cai. R.", "Cai.Cas.Err.", "Cai.R.", "Cain.", "Cain. Rep.", "Caines", "Caines Cas.",
  "Caines Rep.", "Cal.", "Cal. 2d", "Cal. 3d", "Cal. 3d Spec. Trib Supp.", "Cal. 4th", "Cal. 4th CJP Supp.",
  "Cal. 5th", "Cal. 5th CJP Supp.", "Cal. App.", "Cal. App. 2d", "Cal. App. 2d Supp", "Cal. App. 2d Supp.",
  "Cal. App. 3d", "Cal. App. 3d Supp.", "Cal. App. 4th", "Cal. App. 4th Supp.", "Cal. App. 5th",
  "Cal. App. 5th Supp.", "Cal. App. LEXIS", "Cal. App. Rep.", "Cal. App. Supp", "Cal. App. Supp.",
  "Cal. App. Supp. 2d", "Cal. App. Supp. 3d", "Cal. App. Supp. 4th", "Cal. App. Supp. 5th",
  "Cal. App. Unpub. LEXIS", "Cal. App.2d", "Cal. App.3d", "Cal. App.4th", "Cal. Bankr. Ct. Rep.",
  "Cal. Comm. Jud. Perform. LEXIS", "Cal. Comp. Cas", "Cal. Comp. Cases", "Cal. Daily Op. Serv.",
  "Cal. Daily Op. Service", "Cal. Dist. Ct.", "Cal. I.A.C.", "Cal. Jud. Ethics Op. LEXIS", "Cal. LEXIS",
  "Cal. Law J.", "Cal. Law J. & Lit. Rev.", "Cal. Rep.", "Cal. Rptr.", "Cal. Rptr. 2d", "Cal. Rptr. 3d",
  "Cal. Rptr.2d", "Cal. Rptr.3d", "Cal. Sup.", "Cal. Super. Ct.", "Cal. Super. LEXIS", "Cal. Supp.",
  "Cal. Unrep.", "Cal. WCC", "Cal.2d", "Cal.2nd", "Cal.3d", "Cal.3rd", "Cal.4th", "Cal.5th", "Cal.App.",
  "Cal.App. 2d", "Cal.App. 2d Supp.", "Cal.App. 3d", "Cal.App. 3d Supp.", "Cal.App. 4th",
  "Cal.App. Supp. 2d", "Cal.App. Supp. 3d", "Cal.App. Supp.2d", "Cal.App. Supp.3d", "Cal.App.2d",
  "Cal.App.2d Supp.", "Cal.App.3d", "Cal.App.3d Supp.", "Cal.App.4th", "Cal.App.4th Supp.", "Cal.App.5th",
  "Cal.App.5th Supp.", "Cal.App.Supp.", "Cal.App.Supp.2d", "Cal.Rptr.", "Cal.Rptr. 2d", "Cal.Rptr. 3d",
  "Cal.Rptr.2d", "Cal.Rptr.3d", "Cal.Unrep.", "Cal.Unrep.Cas.", "Call", "Call Rep.", "Cam. & Nor.",
  "Cam.& N.", "Car. L. Rep.", "Car. Law Repos.", "Car. Law. Repos.", "Car.Law.Repos.",
  "Carpenter's Report of Burr's Trial", "Cates", "Cates.", "Cent. Law J.", "Cent. Law. J.", "Centre Co.L.J.",
  "Ch.Sent.", "Chand.", "Chandl.", "Charl. R.", "Charlt.", "Charlt. R.M.", "Charlton", "Charlton Rep.",
  "Charlton's", "Chase", "Chase's Trial. Append.", "Chase.", "Chest.", "Chester Co. Rep.", "Chev.",
  "Chev. Eq.", "Chev.Ch.", "Cheves", "Chi Leg. News", "Chi. Law J.", "Chi. Leg. News", "Chi. Leg. News.",
  "Chi.Leg.N.", "Chip.", "Chip. Rep.", "Chip.D.", "Chip.N.", "Chit. Cr. L.", "Chit. Cr. Law",
  "Chit. Crim. Law", "Cin. L. Bull.", "Cin. Law Bul.", "Cin. Law Bull.", "Cin. R.", "Cin. Rep.",
  "Cin. S.C. Rep.", "Cin. S.C.R.", "Cin. Sup. Ct. Rep.", "Cin.Law. Bul.", "Cinc. L. Bul.", "City H. Rec.",
  "Civ. Proc. N.S.", "Civ. Proc. R.", "Civil Proc. R.", "Cl. Ch.", "Cl. Ct.", "Cl.Ct.", "Cl.R.", "Clarke",
  "Clarke Ch.", "Clayton's Notebook", "Cliff.", "Codd. Dig.", "Coddington's Digest", "Code Rep.", "Coffey",
  "Col.", "Col. L. Rep.", "Col. Law Rep.", "Col.& C.Cas.", "Col.& Cai.", "Col.Cas.", "Cold.", "Coldw.",
  "Cole. & Cai. Cas.", "Cole. Cas.", "Cole.& C.Cas.", "Cole.& Cai.", "Cole.Cas.Pr.", "Colem.& C.Cas.",
  "Colem.Cas.", "Collier Bankr. Cas.", "Collier Bankr. Cas. 2d", "Collier Bankr.Cas.2d", "Colo Bankr Ct Rep",
  "Colo.", "Colo. App.", "Colo. App. LEXIS", "Colo. Bankr. Ct. Rep.", "Colo. Discipl. LEXIS", "Colo. J.",
  "Colo. J. C.A.R.", "Colo. L. Rep.", "Colo. LEXIS", "Colo. Law Rep.", "Colo. N. P.", "Colo. R.",
  "Colo.App.", "Colorado Journal", "Comm. Fut. L. Rep.", "Comp. Gen.", "Conn", "Conn.", "Conn. App.",
  "Conn. App. LEXIS", "Conn. Cir. Ct", "Conn. Cir. Ct.", "Conn. Cir. LEXIS", "Conn. L. Rptr.", "Conn. LEXIS",
  "Conn. Rep.", "Conn. Sup.", "Conn. Super. Ct.", "Conn. Super. LEXIS", "Conn. Supp.", "Conn. Surr.",
  "Conn.App.", "Conn.Cir.Ct.", "Conn.Sup.", "Conn.Super.Ct.", "Conn.Supp.", "Conn.Surr.", "Connoly",
  "Connoly Sur. Rep.", "Connoly Surr. Rep.", "Const.", "Const. Rep.", "Const.S.C.", "Cont. Cas. Fed.",
  "Cooke", "Coombs' Trial of Aaron Burr", "Coop. Chy.", "Copr.L.Dec.", "Court Cl.", "Cow.", "Cow. Rep.",
  "Cow.N.Y.", "Cra.", "Crabbe", "Crabbe.", "Cranch", "Cranch C.C.", "Cranch D.C.", "Cranch Rep.",
  "Cranch. C. C.", "Ct. Cl.", "Ct. Cl. R.", "Ct. Cl. Rep.", "Ct. Cls. R.", "Ct. Cust.", "Ct. Cust. Appls.",
  "Ct. Cust. LEXIS", "Ct. Int'l Trade", "Ct. Intl. Trade LEXIS", "Ct. Sup.", "Ct.Cl.", "Ct.Int'l Trade",
  "Ct.Sup.", "Curt", "Curt.", "Cush.", "Cush. Rep.", "Cushing", "Cust. B. & Dec.", "Cust. Ct.",
  "Cust. Ct. LEXIS", "Cust.Ct.", "D.", "D. Chip.", "D. Chip. Rep.", "D. Haw.", "D. L. N.", "D.& B.",
  "D.A.R.", "D.C.", "D.C. App.", "D.C. App. LEXIS", "D.C. Super. LEXIS", "D.Chipm.", "D.L.N.", "D.N.H.",
  "D.P.R.", "D.S.D.", "DJCAR", "DNH", "DPR", "DSD", "DTA", "DTS", "Daily Journal D.A.R.",
  "Daily Journal DAR", "Daily L.N.", "Daily L.R.", "Daily Wash. L. Rptr.", "Dak.", "Dakota", "Dakota LEXIS",
  "Dal.", "Dal. Rep.", "Dall.", "Dall. Rep.", "Dall.Dig.", "Dall.S.C.", "Dallam", "Dallas", "Dallas Rep.",
  "Daly", "Daly's R.", "Dan.", "Dana", "Dana Rep.", "Davis. L. Ct. Cas.", "Day", "Day.", "Deady", "Deady.",
  "Dec. Com. Pat.", "Dec. Comm'r Pat.", "Dec. Commr. Pat.", "Del.", "Del. C.P. LEXIS", "Del. Cas.",
  "Del. Ch.", "Del. Ch. LEXIS", "Del. Ch. Rep.", "Del. Co.", "Del. Co. Rep.", "Del. Fam. Ct. LEXIS",
  "Del. LEXIS", "Del. Rep.", "Del. Super. LEXIS", "Del.Ch.", "Del.Co.", "Del.Co.Rep.",
  "Delaware Co. Reports", "Dem.", "Dem. Sur.", "Dem. Surr.", "Dem.Surr.", "Den.", "Denio", "Denio Rep.",
  "Des.", "Des. Eq.", "Des. Rep.", "Desaus.", "Desaus. Rep.", "Desaus.Eq.", "Dev.", "Dev. & Bat.",
  "Dev. & Bat. Eq.", "Dev. & Bat. Law", "Dev. Eq.", "Dev. Eq. Rep.", "Dev. Rep.", "Dev.& B.", "Dev.& B.Eq.",
  "Dev.& B.L.", "Dev.L.", "Dickinson", "Dill", "Dill.", "Dis. R.", "Dist.Rep.", "Div.", "Doug.",
  "Doug. Rep.", "Dud.", "Dud. Eq.", "Dud.Ch.", "Dud.L.", "Dudl.", "Dudley Rep.", "Duer",
  "Duer Super. Ct. Rep.", "Duv.", "E.A.D.", "E.D. Pa.", "E.D. Smith", "E.H. Smith", "E.H.Smith's", "ELR",
  "ERC", "Ed. Law Rep.", "Ed.C.R.", "Ed.Ch.", "Edm. Sel. Cas.", "Edm.Sel.Ca.", "Edmond", "Educ L Rep",
  "Educ. L. Rep.", "Edw.", "Edw. Ch.", "Edw. Ch. Rep.", "Edw. Rep.", "Empl. Prac. Dec.", "Empl. Prac.Dec.",
  "Employee Benefits Cas.", "Energy Mgt.", "Envtl. L. Rep.", "Envtl. L.Rep.", "F 2d", "F Supp", "F Supp 2d",
  "F Supp.", "F.", "F. 2d", "F. 3d", "F. 4th", "F. App'x", "F. App'x.", "F. Appx.", "F. Cas.", "F. Supp",
  "F. Supp.", "F. Supp. 2d", "F. Supp. 3d", "F. Supp.2d", "F.2d", "F.2d.", "F.3d", "F.3d.", "F.4 th",
  "F.4th", "F.4th.", "F.App'x", "F.App'x.", "F.Appx.", "F.C.", "F.C.C.", "F.C.C.2d", "F.Cas.", "F.L.R.A.",
  "F.R.D.", "F.Supp.", "F.Supp. 2d", "F.Supp. 3D", "F.Supp. 3d", "F.Supp.2d", "F.Supp.3d", "F.Supp.3d.",
  "F.T.C.", "F3d", "F3d.", "F4th", "FCC", "FCC 2d", "FCC Rcd", "FCDR", "FED App.", "FERC", "FL", "FLW Fed",
  "FMSHRC", "FPSC", "FS3d", "FSupp3d", "Fair Empl.Prac.Cas.", "Fed Appx", "Fed.", "Fed. App'x", "Fed. App.",
  "Fed. Appx", "Fed. Appx.", "Fed. Banking L. Rep.", "Fed. Carr. Cas.", "Fed. Cas.", "Fed. Cl.",
  "Fed. R. Evid. Serv.", "Fed. R. Evid. Serv. 2d", "Fed. R. Evid. Serv. 3d", "Fed. R. Serv.",
  "Fed. R. Serv. 2d", "Fed. R. Serv. 3d", "Fed. Sec. L. Rep.", "Fed. Sent'g Rep", "Fed. Sent. R.",
  "Fed.App'x", "Fed.App.", "Fed.Appx.", "Fed.Ca.", "Fed.Cl.", "Fed.R.", "Fed.R.2d", "Fed.R.3d", "Fed.R.4th",
  "Fed.R.Serv.", "Fed.R.Serv.2d", "Fed.R.Serv.3d", "Fed.Rep.", "Fed.Rep.2d", "Fed.Rep.3d", "Fed.Rep.4th",
  "Fed.Sent.R.", "Fire & Casualty Cas.", "Fish. Pat. Cas.", "Fish. Pat. Rep.", "Fish. Pr. Cas.",
  "Fish. Prize", "Fish. Prize Cas.", "Fl.S.", "Fla.", "Fla. App. LEXIS", "Fla. L. Weekly",
  "Fla. L. Weekly Fed.", "Fla. L. Weekly Fed. B", "Fla. L. Weekly Fed. C", "Fla. L. Weekly Fed. D",
  "Fla. L. Weekly Fed. S", "Fla. L. Weekly S", "Fla. L. Weekly Supp.", "Fla. LEXIS", "Fla. Rep.",
  "Fla. Supp.", "Fla. Supp. 2d", "Flip.", "Flor.", "Florida", "Florida Rep.", "Foster", "Fr. Ch.",
  "Fr. Chy.", "Free. Ch.", "Freem.", "Freem. Ch.", "Fulton County D. Rep.", "G. & J.", "G.D.R.", "Ga.",
  "Ga. App.", "Ga. App. LEXIS", "Ga. L. Rep.", "Ga. LEXIS", "Ga. Law Reporter", "Ga. Rep.", "Ga.App.",
  "Gall.", "Gall. C.C.R.", "Gall. Rep.", "Gallison", "Gallison's Rep.", "Georgia Decisions", "Gibb. Surr.",
  "Gibbons", "Gil.", "Gild.", "Gildersleeve", "Gildr.", "Gill", "Gilm.", "Gilman", "Gilmer", "Gilp", "Gilp.",
  "Goebel", "Goebel's Rep.", "Gr.", "Grant", "Grant Cas.", "Grant Pa.", "Gratt.", "Gray", "Greene", "Guam",
  "Guam LEXIS", "Gummere", "Gunby", "H.", "H. & G.", "H. & J.", "H. & McH.", "H. Rep.", "H.& M.", "HOW",
  "Hall", "Hall R.", "Hall Rep.", "Hall Super. Ct. Rep.", "Hall's R.", "Hall's Sup. Court Rep.",
  "Hall's Sup. Ct. R.", "Hall.", "Hall. Law J.", "Han", "Hand.", "Handy", "Handy R.", "Har.", "Har. & J.",
  "Har. Ch.", "Har. Chy.", "Hard.", "Hardes", "Hardes.", "Hardesty", "Hardin", "Harp.", "Harp. Eq.",
  "Harp.L.", "Harper", "Harr.", "Harr. Ch.", "Harr. Ch. R.", "Harr. Rep.", "Harring.", "Harrington", "Hasb.",
  "Hask.", "Haskell C.C.", "Havw. & H.", "Haw.", "Haw. App.", "Haw. App. LEXIS", "Haw. LEXIS", "Haw. Rep.",
  "Haw.App.", "Hawai'i", "Hawaii", "Hawaii App.", "Hawaii Rep.", "Hawks", "Hawks Rep.", "Hay.", "Hay. & H.",
  "Hay. & Haz.", "Hay. Rep.", "Hayw.", "Hayw. & H.", "Hayw. & H.D.C.", "Hayw. & Haz.", "Hayw. N. C.",
  "Hayw. Rep.", "Hayw.& H.", "Hayw.N.C.", "Hayw.Tenn.", "Haz. Reg. Pa.", "Haz. Reg. U. S.",
  "Haz. U. S. Reg.", "Head", "Heisk.", "Hemp.", "Hempst", "Hempst.", "Hen.", "Hen. & M.", "Hen.& Mun.",
  "Hill", "Hill & D.Supp.", "Hill & Den.", "Hill & Den.Supp.", "Hill Ch.", "Hill Ch. Rep.", "Hill Eq.",
  "Hill Law", "Hill Rep.", "Hill S.C.", "Hill.N.Y.", "Hilles' Notebook", "Hilt.", "Hoff Land Cas.", "Hoff.",
  "Hoff. Ch.", "Hoff. Ch. Rep.", "Hoff. Dec.", "Hoff. Land Cas.", "Hoff. Land. Cas.", "Hoff. Op.",
  "Hoff.Cha.", "Hoff.N.Y.", "Hoffm.", "Holmes", "Hopk. Ch.", "Hopk. Ch. Rep.", "Hopk. Works", "Hopk. Works.",
  "Hosea's Rep.", "Houst.", "Houston", "Houston Criminal", "How.", "How. App. Cas.", "How. N.P.", "How. Pr.",
  "How. Pr. Rep.", "How. Prac.", "How. Rep.", "How.N.P.", "How.P.R.", "Howard", "Howard Rep.", "Howell N.P.",
  "Howison", "Hugh.", "Hughes", "Hughes.", "Hum.", "Hum. Rep.", "Humph.", "Humph. Rep.", "Hun", "Hun.",
  "Hunt Mer. Mag.", "Hunt. Mer. Mag.", "I & N Dec.", "I&N", "I&N Dec", "I&N Dec.", "I&NDec.", "I. & N. Dec.",
  "I.C.C.", "I.C.C.2d", "I.E.R.", "I.E.R. Cas.", "I.R.B.", "I.T.R.D.", "IER Cases", "IL", "IN Dec.", "ITRD",
  "Ia.", "Ida.", "Ida. App. LEXIS", "Ida. App. Unpub. LEXIS", "Ida. LEXIS", "Idaho", "Ill.", "Ill. 2d",
  "Ill. App.", "Ill. App. 2d", "Ill. App. 3d", "Ill. App. LEXIS", "Ill. App. Rep.", "Ill. App. Unpub. LEXIS",
  "Ill. App.2d", "Ill. App.3d", "Ill. C.C.", "Ill. Cir. Ct.", "Ill. Cir. Ct. Rep.", "Ill. Ct. Cl.",
  "Ill. Ct. Cl. LEXIS", "Ill. Dec.", "Ill. LEXIS", "Ill. Rep.", "Ill.2d", "Ill.A.", "Ill.A.2d", "Ill.A.3d",
  "Ill.App.", "Ill.App.2d", "Ill.App.3d", "Ill.C.C.", "Ill.Dec.", "Ill.Decs.", "Ind.", "Ind. App.",
  "Ind. App. LEXIS", "Ind. App. Unpub. LEXIS", "Ind. Cl. Com.", "Ind. Cl. Comm.", "Ind. Dec.",
  "Ind. L. Rep.", "Ind. LEXIS", "Ind. T.", "Ind. Tax LEXIS", "Ind.App.", "Ind.Rep.", "Ind.T.",
  "Indian Terr.", "Indian Terr. LEXIS", "Ins Law J.", "Ins. L.J.", "Ins. Law J.", "Ins. Law. J.",
  "Int Rev. Rec.", "Int. Rev. Rec.", "Intelligencer", "Interior Dec.", "Iowa", "Iowa App. LEXIS",
  "Iowa Rep.", "Iowa Sup. LEXIS", "Ired.", "Ired. Eq.", "Ired. Eq. Rep.", "Ired. Law", "Ired. Law Rep.",
  "Ired. Rep.", "Ired.L.", "J.", "J. Rep.", "J.Ch.", "J.J. Marsh.", "J.J.Mar.", "JTS", "Jahn", "Jeff.",
  "Jefferson", "John.", "John. Rep.", "Johns.", "Johns. Cas.", "Johns. Ch.", "Johns. Ch. Rep.",
  "Johns.Ch.Cas.", "Johns.Ct.Err.", "Johns.N.Y.", "Johns.Rep.", "Johnson", "Johnson Rep.", "Jones",
  "Jones & S.", "Jones & Spencer", "Jones Eq.", "Jones L.", "Jones Law", "Jones Law.", "Jones N.C.",
  "Jones and Spencer's Super. Ct. Rep.", "Jour. Fr. Inst.", "Jour. Jur.", "Juris P.R.", "Just.", "Kan.",
  "Kan. App.", "Kan. App. 2d", "Kan. App. LEXIS", "Kan. App. Unpub. LEXIS", "Kan. App.2d", "Kan. LEXIS",
  "Kan. Rep.", "Kan. Unpub. LEXIS", "Kan.App.", "Kan.App. 2d", "Kan.App.2d", "Kans.", "Kans.App.", "Kas.",
  "Kelly", "Ken.Dec.", "Ken.L.Re.", "Ken.Opin.", "Keyes", "Kir.", "Kirb.", "Kirby", "Kulp", "Ky.",
  "Ky. App.", "Ky. App. LEXIS", "Ky. App. Unpub. LEXIS", "Ky. L. Rptr.", "Ky. L. Summ.", "Ky. LEXIS",
  "Ky. Law Rep.", "Ky. Op.", "Ky. Rep.", "Ky. Unpub. LEXIS", "Ky.L.R.", "Ky.L.Rptr.", "Ky.Law.Rep.", "L Ed",
  "L Ed 2d", "L.", "L. Ed.", "L. Ed. 2d", "L. Ed.2d", "L. Rep.", "L.E.", "L.E.2d", "L.Ed.", "L.Ed. 2d",
  "L.Ed.2d", "L.J.Q.B.", "L.R.A.", "L.R.A.N.S.", "L.R.R.M.", "LA", "LAW ED", "LCR", "LEXIS", "LEd", "LEd2d",
  "La.", "La. Ann.", "La. Ann. Rep.", "La. App.", "La. App. LEXIS", "La. App. Unpub. LEXIS", "La. LEXIS",
  "La. Law J.", "La. Rep.", "La.A.", "La.Ann.", "La.App.", "La.App. 1 Cir.", "La.App. 2 Cir.",
  "La.App. 3 Cir.", "La.App. 4 Cir.", "La.App. 5 Cir.", "La.App. 6 Cir.", "Lab.Cas.", "Lac. Jur.",
  "Lack. L.N.", "Lack. Leg.", "Lack.Jur.", "Lack.Jurist", "Lack.L.N.", "Lacka. Leg. News", "Lalor",
  "Lalor Supp.", "Lanc. L. Rev.", "Lans.", "Lans. Ch.", "Law & Eq. Rep.", "Law J. Q.B.", "Law Rep.",
  "Law Reporter", "Law. Rep.", "Law.Ed.", "Lea", "Lea.", "Leg. Gaz.", "Leg. Gaz. Rep.", "Leg. Int.",
  "Leg. Intel. or Intell.", "Leg. Op.", "Leg. Rec.", "Leg. Rec. Rep.", "Leg. Rep.", "Leg.Int.", "Leg.Rec.",
  "Legal Gaz.", "Legal Int.", "Legal Intel.", "Legal Intell.", "Legal Intelligencer", "Lehigh",
  "Lehigh V.L.R.", "Lehigh Val. L. Rep.", "Lehigh Val. L.R.", "Lehigh Val. Law Rep", "Leigh", "Leigh Rep.",
  "Liquor Tax Rep.", "Lit.", "Lit. Rep.", "Lit.Sel.Ca.", "Litt.", "Litt. Rep.", "Litt. Sel. Cas.", "Littell",
  "Littell Rep.", "Liv. Law Mag.", "Lock. Rev. Cas.", "Low.", "Low. Dec.", "Low. Dis.", "Lowell", "Lowell.",
  "Luz. L.R.", "Luz. Leg. Reg.", "Luz. Leg. Reg. Rep.", "Luz.L.R.", "M.", "M. J.", "M.& Y.", "M.& Y.R.",
  "M.D.L.R.", "M.J.", "M.S.P.B.", "M.S.P.R.", "M.T.C.A.", "M.T.C.R.", "MDBT", "MDLR", "ME", "MJ", "ML", "MP",
  "MS", "MSPB", "MT", "Ma.", "Ma.A.", "Mac. A. Pat. Cas.", "MacA. Pat Cas.", "MacA. Pat. Cas.", "MacAr.",
  "MacAr.& M.", "MacAr.& Mackey", "MacArth.", "MacArth. & M.", "MacArthur", "MacArthur & M.", "Mackey",
  "Mai.", "Maine", "Maine Rep.", "Man. Unrep. Cas.", "Mann. Unrep. Cas.", "Manning La.", "Manning's U.C.",
  "Manning's Unrep. Cases", "Manum.", "Manum. Cas.", "Mar.", "Mar. Rep.", "Marsh.", "Marsh. Rep.",
  "Marsh.A.K.", "Marsh.J.J.", "Mart.", "Mart. & Yer.", "Mart. N. C.", "Mart. Rep.", "Mart.& Y.",
  "Mart.& Yerg.", "Mart.Dec.", "Mart.N.C.", "Martin", "Martin Rep.", "Marv.", "Marvel", "Maryland",
  "Maryland Rep.", "Mas.", "Mas. Rep.", "Mason", "Mason C.C.", "Mason C.C.R.", "Mason Circt. Ct. R.",
  "Mason R.", "Mason U.S.", "Mason.", "Mass.", "Mass. App. Ct.", "Mass. App. Dec.", "Mass. App. Div.",
  "Mass. App. Div. Adv. Sh.", "Mass. App. Div. LEXIS", "Mass. App. LEXIS", "Mass. App. Unpub. LEXIS",
  "Mass. L. Rptr.", "Mass. LCR LEXIS", "Mass. LEXIS", "Mass. Law Rep", "Mass. Law Rep.", "Mass. R.",
  "Mass. Rep.", "Mass. Super. LEXIS", "Mass. Supp.", "Mass.App.", "Mass.App.Ct.", "Mc Lean",
  "Mc.A. Pat. Cas.", "McA. Pat. Cas.", "McAl.", "McAll.", "McAllister U.S. Circ. Court R.", "McCah.",
  "McCahon", "McCanless", "McCord", "McCord Ch.", "McCord Ch. Rep.", "McCord Eq.", "McCord Rep.", "McCrary",
  "McCrary's Cir. Ct. Rpts", "McGl.", "McGloin", "McGrath", "McGrdath", "McLean", "McLean.", "McMul.",
  "McMul. Eq.", "Md.", "Md. App.", "Md. App. LEXIS", "Md. Ch.", "Md. Cir. Ct. LEXIS", "Md. LEXIS",
  "Md. Law Rec.", "Md. Rep.", "Md. Tax LEXIS", "Md.App.", "Me.", "Me. LEXIS", "Me. Super. LEXIS",
  "Me. Unpub. LEXIS", "Media L. Rep.", "Meigs", "Met.", "Met. Rep.", "Metc.", "Metc. Rep.", "Metc.Ky.",
  "Metc.Mass.", "Mich", "Mich App", "Mich.", "Mich. App.", "Mich. App. LEXIS", "Mich. Ct. App.",
  "Mich. Ct. Cl.", "Mich. LEXIS", "Mich. Lawy.", "Mich. N.P.", "Mich. N.P. R.", "Mich. Pr.", "Mich. Rep.",
  "Mich.App.", "Miles", "Mill", "Mill Const.", "Miller's Notebook", "Mills", "Mills Surr.", "Mills.", "Min.",
  "Min. Rep.", "Minn.", "Minn. App. LEXIS", "Minn. App. Unpub. LEXIS", "Minn. Dist. LEXIS", "Minn. LEXIS",
  "Minn. Rep.", "Minn. Tax LEXIS", "Minor", "Mis.", "Mis. Rep.", "Misc", "Misc 2d", "Misc 3d", "Misc Rep",
  "Misc Rep.", "Misc.", "Misc. 2d", "Misc. 3d", "Misc. Rep", "Misc. Rep.", "Misc.2d", "Misc.3d", "Miss.",
  "Miss. App. LEXIS", "Miss. Dec.", "Miss. LEXIS", "Miss. R.", "Miss. Rep.", "Mo.", "Mo. App.",
  "Mo. App. LEXIS", "Mo. LEXIS", "Mo. Rep.", "Mo.App.", "Mo.App.Rep.", "Mon.", "Mon. Rep.", "Mon.B.",
  "Mon.T.B.", "Mona.", "Monag.", "Monaghan", "Mont", "Mont'g. Co. L. Rep.", "Mont'g. L. Rep.", "Mont.",
  "Mont. Dist. LEXIS", "Mont. LEXIS", "Mont. St. Rep.", "Mont. Water LEXIS", "Montg.", "Montg. CLR",
  "Montg. CLR.", "Montg. Co.", "Montg. Co. L. Rep'r", "Montg. Co. L.R.", "Montg. Co. Law Rep'r.",
  "Month. Jur.", "Month. West. Jur.", "Mor. Min. Rep.", "Mor. St. Ca.", "Mor. St. Cas.", "Mor.Ia.", "Morr.",
  "Morr. M.R.", "Morr. Min. R.", "Morr. Min. Rep.", "Morr. St. Cas.", "Morris", "Morris St. Cas.", "Mt",
  "Mt.", "Munf.", "Munf. Rep.", "Mur.", "Mur. Rep.", "Murph.", "Murph. Rep.", "Myrick", "N W. Rep.",
  "N. B. R.", "N. Bk. R.", "N. Bkpt. R.", "N. Bkpt. Reg.", "N. C.", "N. C. Rep.", "N. Chip.", "N. D.",
  "N. E.", "N. E. 2d", "N. E. 3d", "N. E.2d", "N. E.3d", "N. H. Rep.", "N. J. Law J.", "N. Mar. I.",
  "N. Mar. I. Commw.", "N. Mar. I. Commw. Rptr.", "N. Mar. I. LEXIS", "N. W.", "N. W. 2d", "N. W. Rep.",
  "N. W.2d", "N. Y.", "N. Y. Ann. Cas.", "N. Y. City H. Rec.", "N. Y. Law J.", "N. Y. Leg. Ob.",
  "N. Y. Leg. Obs.", "N. Y. Rep.", "N. Y. Supp.", "N. Y. Supplement", "N. Y. Wkly. Dig.", "N.& Mc.",
  "N.B.R.", "N.C.", "N.C. App.", "N.C. App. LEXIS", "N.C. LEXIS", "N.C.App.", "N.C.Conf.", "N.C.Conf.Rep.",
  "N.C.T.Rep.", "N.C.Term.R.", "N.C.Term.Rep.", "N.Chipm.", "N.D.", "N.D. App. LEXIS", "N.D. LEXIS",
  "N.D.App.", "N.E.", "N.E. 2d", "N.E. 3d", "N.E.2d", "N.E.3d", "N.E.Rep.", "N.H", "N.H.", "N.H. LEXIS",
  "N.H. Rep.", "N.H. Super. LEXIS", "N.H.R.", "N.J.", "N.J. Admin.", "N.J. Admin. 2d", "N.J. Ch. LEXIS",
  "N.J. Eq.", "N.J. LEXIS", "N.J. Law J.", "N.J. Misc.", "N.J. Misc. LEXIS", "N.J. Prerog. Ct. LEXIS",
  "N.J. Sup. Ct. LEXIS", "N.J. Super.", "N.J. Super. LEXIS", "N.J. Super. Unpub. LEXIS", "N.J. Tax",
  "N.J. Tax Ct.", "N.J. Tax.", "N.J.L.", "N.J.L.J.", "N.J.Law", "N.J.M.", "N.J.S.", "N.J.Super.", "N.J.Tax",
  "N.L.R.B.", "N.M.", "N.M. App. LEXIS", "N.M. App. Unpub. LEXIS", "N.M. Ct. App.", "N.M. LEXIS",
  "N.M. St. B. Bull.", "N.M. Unpub. LEXIS", "N.M.B.", "N.R.C.", "N.T.S.B.", "N.W.", "N.W. 2d", "N.W. 2nd",
  "N.W. Rep.", "N.W.2.d", "N.W.2d", "N.W.2d.", "N.W.2nd", "N.W.3d", "N.Y", "N.Y.", "N.Y. 2d", "N.Y. 3d",
  "N.Y. Ann. Ca.", "N.Y. Ann. Cas.", "N.Y. Anno. Cas.", "N.Y. App. Div. LEXIS", "N.Y. Ch. Ann.",
  "N.Y. City Ct. Rep.", "N.Y. City H. Rec.", "N.Y. Civ. Proc. R.", "N.Y. Civ. Proc. Rep.", "N.Y. Cr. R.",
  "N.Y. Cr. Rep.", "N.Y. Crim.", "N.Y. Crim. R.", "N.Y. Crim. Rep.", "N.Y. LEXIS", "N.Y. Leg. Obs.",
  "N.Y. Legal Observer", "N.Y. Misc. LEXIS", "N.Y. Proc. Ct. Ass.", "N.Y. Slip Op", "N.Y. Slip Op.",
  "N.Y. St. R.", "N.Y. St. Rep'r", "N.Y. St. Rep.", "N.Y. St. Repr.", "N.Y. St. Rptr.", "N.Y. Sup. Ct.",
  "N.Y. Super. Ct.", "N.Y. Super.Ct.", "N.Y. Supp.", "N.Y.2d", "N.Y.3d", "N.Y.Ann.Cas.", "N.Y.App.Dec.",
  "N.Y.App.Div.", "N.Y.Cas.Err.", "N.Y.Ch.R.Ann.", "N.Y.Ch.Sent.", "N.Y.Civ.Proc.R.", "N.Y.Crim.R.",
  "N.Y.L.J.", "N.Y.S.", "N.Y.S. 2d", "N.Y.S. 3d", "N.Y.S.2d", "N.Y.S.3d", "N.Y.Spec.Term R.",
  "N.Y.Spec.Term Rep.", "N.Y.St.Rep.", "N.Y.Super.Ct.", "N.Y.Supr.Ct.", "N.Y.Suprm.Ct.", "NCA", "NCBC",
  "NCBC LEXIS", "ND", "ND APP", "ND App", "NDLR", "NE", "NE 2d", "NE 3d", "NE2d", "NE3d", "NJM", "NLRB",
  "NLRB No.", "NM", "NMCA", "NMCERT", "NMSC", "NV", "NW", "NW 2d", "NW.2d", "NW2D", "NW2d", "NW3d", "NY",
  "NY 2d", "NY 3d", "NY App Div LEXIS", "NY Misc LEXIS", "NY Slip Op", "NY Slip Op.", "NY2d", "NY3d", "NYS",
  "NYS 2d", "NYS 3d", "NYS2d", "NYS3d", "NYSlipOp", "Nat. Bank. Reg.", "Nat. Bankr. Reg.", "Navajo Rptr.",
  "Neb App", "Neb App.", "Neb.", "Neb. App.", "Neb. App. LEXIS", "Neb. Ct. App.", "Neb. LEXIS", "Neb. Unoff",
  "Neb.App.", "Neb.App.R.", "Neb.C.A.", "Nev.", "Nev. Adv. Op.", "Nev. Adv. Op. No.", "Nev. Adv. Rep.",
  "Nev. Advance Rep.", "Nev. LEXIS", "Nev. Unpub. LEXIS", "Nev.Ad.Op.", "Nev.Adv.Op.", "New York Supp.",
  "New York Supplement", "Newb.", "Newb. Adm.", "Niles Reg.", "Niles' Reg.", "No.East Rep.", "No.West Rep.",
  "Northumb. L.J", "Northumb. L.J.", "Northumb. Legal. J.", "Northumb.L.J", "Northumb.L.J.",
  "Northumberland Co. Leg. Jour", "Northumberland L.J.", "Northw.Rep.", "Nott & McC.", "Nuclear Reg. Rep.",
  "O.", "O. App.", "O. App. 2d", "O. App. 3d", "O. C. A.", "O. G.", "O. Supp", "O. Supp.", "O.A.R.",
  "O.A.R. 2d", "O.A.R. 3d", "O.A.R.2d", "O.A.R.3d", "O.App.", "O.App.2d", "O.App.3d", "O.B.A.J.", "O.B.R.",
  "O.C.C.", "O.C.C.N.S.", "O.C.D.", "O.Cr.", "O.D.", "O.Dec.Rep.", "O.G.", "O.G. Pat. Off.", "O.L.A.",
  "O.L.Abs.", "O.Misc.", "O.Misc.2d", "O.N.P.", "O.N.P.N.S.", "O.O.", "O.O.2d", "O.O.3d", "O.R.W.", "O.S.",
  "O.S.2d", "O.S.3d", "O.S.C.D.", "O.S.H. Cas.", "O.S.H. Cases", "O.S.H.D.", "O.S.U.", "OH", "OHIO", "OK",
  "OK AG", "OK CIV APP", "OK CR", "OK JUD", "OK JUD ETH", "OKla.", "OS.", "OTR", "Off. Gaz.",
  "Off. Gaz. Pat.", "Off. Gaz. Pat. Off.", "Oh. A.", "Oh. A. 2d", "Oh. A. 3d", "Oh. App.", "Oh. App. 2d",
  "Oh. App. 3d", "Oh. S.C.D.", "Oh.A.", "Oh.A.2d", "Oh.A.3d", "Oh.App.", "Oh.App.2d", "Oh.App.3d",
  "Oh.Cir.Ct.", "Oh.Cir.Ct.N.S.", "Oh.Cir.Dec.", "Oh.Dec.", "Oh.N.P.", "Oh.St.", "Ohio", "Ohio Abs.",
  "Ohio App.", "Ohio App. 2d", "Ohio App. 3d", "Ohio App. LEXIS", "Ohio App. Rep.", "Ohio App. Unrep.",
  "Ohio App.2d", "Ohio App.3d", "Ohio B.", "Ohio B. Rep.", "Ohio C.A.", "Ohio C.C.", "Ohio C.C. Dec.",
  "Ohio C.C.N.S.", "Ohio C.C.R.", "Ohio C.C.R.N.S.", "Ohio C.D.", "Ohio C.Dec.", "Ohio Ch.",
  "Ohio Cir. Dec.", "Ohio Cir.Ct.", "Ohio Cir.Ct.R.N.S.", "Ohio Cr.Ct.R.", "Ohio Ct. App.", "Ohio Dec.",
  "Ohio Dec. Rep.", "Ohio Dec. Reprint", "Ohio F. Dec.", "Ohio F.D.", "Ohio F.Dec", "Ohio F.Dec.",
  "Ohio Fed. Dec.", "Ohio L. Abs.", "Ohio L.Abs.", "Ohio L.R.", "Ohio LEXIS", "Ohio Law Abs",
  "Ohio Law Abs.", "Ohio Law Abst.", "Ohio Law R", "Ohio Law Rep.", "Ohio Law. Abs.", "Ohio Laws Abs.",
  "Ohio Misc.", "Ohio Misc. 2d", "Ohio Misc. LEXIS", "Ohio Misc.2d", "Ohio Misc.Dec.", "Ohio N.P.",
  "Ohio N.P.N.S.", "Ohio Nisi Prius", "Ohio Nisi Prius Decisions", "Ohio Op.", "Ohio Op. 2d", "Ohio Op. 3d",
  "Ohio Op.2d", "Ohio Op.3d", "Ohio Ops.", "Ohio Prob.", "Ohio Prob. Ct.", "Ohio Rep.", "Ohio S.U.",
  "Ohio St.", "Ohio St. 2d", "Ohio St. 3d", "Ohio St. Rep.", "Ohio St.2d", "Ohio St.3d", "Ohio St.3d.",
  "Ohio State", "Ohio Supp.", "Ohio W.L. Bull.", "Ohio. Unrept.Cas.", "Oil & Gas", "Oil & Gas Rep.",
  "Oil & Gas Reptr.", "Oil & Gas Rptr.", "Okl Jud.", "Okl.", "Okl.Cr.", "Okla.", "Okla. Civ. App. LEXIS",
  "Okla. Cr.", "Okla. Cr. Rep.", "Okla. Crim.", "Okla. Crim. App. LEXIS", "Okla. Crim. Rep.",
  "Okla. JUD LEXIS", "Okla. LEXIS", "Okla. Rep.", "Okla. Trib.", "Okla.Cr.", "Okla.Crim.", "Olc.", "Olcott",
  "Oliver's Forms", "Op. Att'y Gen.", "Op. O.L.C.", "Op. OLC.", "Ops. Cal. Atty. Gen.", "Ops.Cal.Atty.Gen.",
  "Or", "Or App", "Or App.", "Or.", "Or. App.", "Or. Tax", "Or.A.", "Or.App.", "Ore.", "Ore. App.",
  "Ore. App. LEXIS", "Ore. LEXIS", "Ore. Tax LEXIS", "Oreg.", "Otto", "Overt.", "P", "P 2d", "P 3d", "P.",
  "P. & H.", "P. 2d", "P. 3d", "P. R.", "P. Rep.", "P.& W.", "P.2", "P.2 d", "P.2d", "P.2d.", "P.3", "P.3d",
  "P.3d.", "P.C.L.J.", "P.C.R.", "P.H.", "P.Jr. & H.", "P.L. Rep.", "P.L.M.", "P.L.R.", "P.O.R.", "P.R.",
  "P.R. Dec.", "P.R. Fed.", "P.R. Fed. Rep.", "P.R. Offic. Trans.", "P.R. Sent.", "P.R.R.", "P.S.R.",
  "P.U.R.", "P.U.R.3d", "P.U.R.4th", "P2.d", "P2d", "P3.d", "P3d", "PA", "PA Super", "POR", "PR App. LEXIS",
  "PR Sup. LEXIS", "Pa.", "Pa. C.", "Pa. Cmwlth", "Pa. Co. Ct.", "Pa. Co. Ct. Rep.", "Pa. Commonwealth Ct.",
  "Pa. Commw.", "Pa. Commw. LEXIS", "Pa. Commw. Unpub. LEXIS", "Pa. Corp.", "Pa. Corp. R.", "Pa. Corp. Rep.",
  "Pa. D.", "Pa. D. & C.", "Pa. D. & C. 2d", "Pa. D. & C. 3d", "Pa. D. & C. 4th", "Pa. D. & C. 5th",
  "Pa. D. & C.2d", "Pa. D. & C.3d", "Pa. D. & C.4th", "Pa. D. & C.5th", "Pa. Dist. & Cnty. Dec. LEXIS",
  "Pa. Fid.", "Pa. Jud. Disc. LEXIS", "Pa. Just. L. Rep.", "Pa. LEXIS", "Pa. Law J.", "Pa. Law J. Rep.",
  "Pa. Rawle", "Pa. Super", "Pa. Super.", "Pa. Super. Ct.", "Pa. Super. LEXIS", "Pa. Super. Unpub. LEXIS",
  "Pa. Superior Ct.", "Pa.C.", "Pa.C.C.", "Pa.Cas.", "Pa.Cmwlth", "Pa.Cmwlth.", "Pa.Co.Ct.", "Pa.Co.Ct.R.",
  "Pa.Commw.Ct.", "Pa.Corp", "Pa.Corp.", "Pa.County Ct.", "Pa.Dist.", "Pa.Dist.& C.Rep.", "Pa.Dist.& Co.",
  "Pa.Dist.R.", "Pa.Rep.", "Pa.S.", "Pa.St.", "Pa.State", "Pa.Super.", "Pa.Super.Ct.", "PaC.", "Pac", "Pac.",
  "Pac. 2d", "Pac. Law Mag.", "Pac. Law Rep.", "Pac. Law Reptr.", "Pac. Law. Rep.", "Pac. Rep.", "Pac.2d",
  "Pac.R.", "Pac.Rep.", "Pacific", "Pacific Law Mag.", "Pacific Rep.", "Pai.", "Pai.Ch.", "Paige",
  "Paige Ch.", "Paige Ch. Rep.", "Paige Rep.", "Paine", "Paine.", "Park. C.R.", "Park. Cr.",
  "Park. Cr. Rep.", "Park. Crim. R.", "Park. Crim. Rep.", "Parker Cr.", "Parker Cr. Rep.", "Parker's Cr. R.",
  "Parker's Crim. R.", "Parker's Crim. Rep.", "Parsons", "Pat. & H.", "Patt. & H.", "Patt. & Heath R.",
  "Patton & H.", "Patton & Heath", "Pears.", "Peck", "Pelt.", "Pen. & W.", "Penn.", "Penn. Del.",
  "Penn. L. J.", "Penn. L.J.", "Penn. Law J.", "Penn. Law Jour.", "Penn.Co.Ct.Rep.", "Penn.Dist.Rep.",
  "Penn.Rep.", "Penn.St.", "Penn.St.R.", "Penne.", "Pennew.", "Pennewill", "Pennewill.", "Penny.", "Pennyp.",
  "Penr.& W.", "Pet C. C.", "Pet.", "Pet. Adm.", "Pet. C. C.", "Pet. C.C.", "Pet. Cir. C.R.", "Pet. Rep.",
  "Pet.S.C.", "Peters", "Peters C.C.", "Peters Rep.", "Phil.", "Phil. Eq.", "Phil. Law", "Phil. Rep.",
  "Phil.N.C.", "Phila.", "Phila. Ct. Com. Pl. LEXIS", "Phila. Cty. Rptr. LEXIS", "Phila. Leg. Int.",
  "Phila. Rep.", "Philadelphia Leg. Int.", "Phill.", "Phill. Rep.", "Phillips", "Pick.", "Pick. Rep.",
  "Pickle", "Pin.", "Pinn.", "Pitt.L.J.", "Pitts L.J.", "Pitts. L. J.", "Pitts. Leg. J.",
  "Pitts. Leg. Joor.", "Pitts. R.", "Pitts. Rep.", "Pitts. Rpts.", "Pitts.L.J.", "Pittsb. L. Rev.",
  "Pittsb. L.J.", "Pittsb. Leg. J.", "Pittsburgh Leg. J.", "Pittsburgh Leg. Journal",
  "Pittsburgh Legal Journal", "Port.", "Port. Rep.", "Porter", "Porter Rep.", "Posey", "Posey U.C.",
  "Posey's U.C.", "Pow. Surr.", "Power", "Pub. Lands Dec.", "Pub. Util. Rep. 4th", "Puerto Rico",
  "Quart. Law J.", "R.", "R.I.", "R.I. Dec.", "R.I. LEXIS", "R.I. Super. LEXIS", "RIA TM",
  "RICO Bus. Disp. Guide", "RICO Bus.Disp.Guide", "Rad. Reg.", "Rand.", "Rand. Rep.", "Raw.", "Rawle",
  "Rawle Rep.", "Read's Notebook", "Rec. Co. Ct.", "Redf.", "Rep. Cont. El.", "Rep. Cont. Elect. Cas.",
  "Rep. Cont. Elect. Case.", "Reporter.", "Rice", "Rice Ch.", "Rice Eq.", "Rich.", "Rich. Cas.", "Rich. Eq.",
  "Rich. Eq. Rep.", "Rich. Rep.", "Rich.Eq.Ch.", "Ridgely's Notebook", "Ridgely's Notebook I",
  "Ridgely's Notebook II", "Ridgely's Notebook III", "Ridgely's Notebook IV", "Ridgely's Notebook V", "Ril.",
  "Ril. Eq.", "Riley", "Riley Ch.", "Riley Eq.", "Rob.", "Rob. Rep.", "Rob.Consc.Cas.", "Rob.La.", "Rob.Va.",
  "Robard", "Robards", "Robb.", "Robbins", "Robbins.", "Robertson's Report of the Trial of Aaron Burr.",
  "Robertson's Super. Ct. Rep.", "Robinson", "Rodney's Notes", "Root", "S Ct", "S. & M.", "S. Ct", "S. Ct.",
  "S. Ct. Rep.", "S. E.", "S. E. 2d", "S. E. Rep.", "S. E.2d", "S. R.", "S. W.", "S. W. 2d",
  "S. W. 2d Series.", "S. W. 3d", "S. W. Rep.", "S. W.2d", "S. W.3d", "S.& Mar.", "S.C.", "S.C. App. LEXIS",
  "S.C. App. Unpub. LEXIS", "S.C. Eq.", "S.C. LEXIS", "S.C. Unpub. LEXIS", "S.C.L.", "S.C.R.", "S.Car.",
  "S.Ct", "S.Ct.", "S.D.", "S.D. LEXIS", "S.Dak.", "S.E.", "S.E. 2d", "S.E. Rep.", "S.E.2d", "S.E.2d.",
  "S.E.C. Docket", "S.E2.d", "S.T.B.", "S.W.", "S.W. 2d", "S.W. 3d", "S.W. Rep.", "S.W. Series", "S.W.2d",
  "S.W.3d", "S.W.3d.", "SCDB", "SCt", "SD", "SE", "SE 2d", "SE2d", "SEC Docket", "SEC Jud. Dec.", "SO.",
  "SW", "SW 2d", "SW 3d", "SW.3d", "SW2D", "SW2d", "SW3D", "SW3d", "Sad.Pa.Cas.", "Sad.Pa.Cs.", "Sadl.",
  "Sadler", "San Fran. Law J.", "San Fran. Law. J.", "Sand. Ch.", "Sand. Ch. Rep.", "Sand.Chy.", "Sandf.",
  "Sandf. Rep.", "Sandf.Ch.", "Sandf.Chy.", "Sandford Super. Ct. Rep.", "Sar.Ch.Sen.", "Sarat. Ch. Sent.",
  "Saw.", "Sawy.", "Sawyer Circt.", "Sawyer U.S. Ct. Rep.", "Sc.", "Scam.", "Scam. Rep.", "Sch. Reg.",
  "Schuy. Reg.", "Seld. Notes", "Serg. & Rawl.", "Serg. & Rawle", "Serg.& R.", "Serg.& Raw.", "Serg.& Rawl.",
  "Shan.", "Shan. Cas.", "Sick.", "Sickels", "Silv. Ct. App.", "Silv. Sup.", "Silvernail", "Sm.& M.",
  "Smed.& M.", "Smedes & M.", "Smith", "Smith & H.", "Smith's N. H. Reports", "Smiths E.H.", "Sneed",
  "Sneed Dec.", "So.", "So. 2d", "So. 2d.", "So. 2nd", "So. 3d", "So. Rep.", "So. Rep. 2d", "So. Rep. 3d",
  "So. Reporter", "So.2d", "So.3d", "So.C.", "So.Car.", "Som.", "Som. L.J.", "Som.L.J.", "Somerset L.J.",
  "SomersetL.J.", "Sou.", "Sou. Rep.", "South", "South Car.", "South.", "South. Rep.", "South.2d",
  "South.3d", "Sp.", "Sp.Ch.", "Spear Ch.", "Spear Eq.", "Spears", "Spears Eq.", "Speers", "Speers Eq.",
  "Spr.", "Sprague", "Sprague.", "St. Rep.", "St.Rep.", "State Reptr.", "State Rptr.", "Stew.", "Stew. & P.",
  "Stew. Rep.", "Stewart", "Sto.", "Sto. Rep.", "Stock.", "Storey", "Story", "Story Rep.", "Story.",
  "Strob.", "Strob. Eq.", "Sum.", "Sumn.", "Sumn. Rep.", "Sup.Ct.", "Sup.Ct.Rep.", "Super. Ct. Jud.",
  "Supp. Tex.", "Suppl. Ga.", "Supr.Ct.Rep.", "Swan", "Sweeney Super. Ct. Rep.", "Sweeny", "Syllabi",
  "T. C.", "T. C. Memo.", "T. C. No.", "T. C. Summary Opinion", "T.B. Mon.", "T.C.", "T.C. Memo",
  "T.C. Memo.", "T.C. No.", "T.C. Summary Opinion", "T.C. at", "T.C.A.", "T.C.M.", "T.Ct", "T.Ct.", "TN WC",
  "TN WC App.", "TNT", "TSPR", "Taney", "Taney.", "Tapp. Rep.", "Tax Ct. Memo LEXIS",
  "Tax Ct. Summary LEXIS", "Tay.", "Tay.J.L.", "Tay.N.C.", "Tayl.N.C.", "Taylor", "Teiss.", "Teissier",
  "Ten.", "Ten. Rep.", "Tenn.", "Tenn. App.", "Tenn. App. LEXIS", "Tenn. Cas.", "Tenn. Ch. App.",
  "Tenn. Ch. App. LEXIS", "Tenn. Ch. R.", "Tenn. Chancery", "Tenn. Chancery App.", "Tenn. Crim. App.",
  "Tenn. Crim. App. LEXIS", "Tenn. LEXIS", "Tenn. Leg. Rep.", "Tenn. Rep.", "Tenn.App.", "Tenn.Cas.",
  "Tenn.Crim.App.", "Ter.", "Ter. Rep.", "Terry", "Tex.", "Tex. App. LEXIS", "Tex. Bankr. Ct. Rep.",
  "Tex. Bus.", "Tex. Bus. Ct.", "Tex. Civ. App.", "Tex. Cr. R.", "Tex. Crim.", "Tex. Crim. App. LEXIS",
  "Tex. Crim. App. Unpub. LEXIS", "Tex. Ct. App.", "Tex. L. R.", "Tex. LEXIS", "Tex. Law J.", "Tex. Rep.",
  "Tex. Sup. Ct. J.", "Tex. Sup. J.", "Tex. Unrep. Cas.", "Tex.A.Civ.", "Tex.A.Civ.Cas.", "Tex.App.",
  "Tex.Bankr.Ct.Rep.", "Tex.C.C.", "Tex.Civ.App.", "Tex.Civ.Cas.", "Tex.Cr.", "Tex.Cr.App.", "Tex.Cr.R.",
  "Tex.Crim.", "Tex.Crim.Rep.", "Tex.Ct.App.Dec.Civ.", "Tex.Ct.App.R.", "Tex.S.Ct.", "Texas",
  "Texas Cr. Rep.", "Texas Crim. Rep.", "Texas Rep.", "Thomp. & Cook", "Thomp. Cas.", "Thompson", "Tiess.",
  "Tiff", "Tiff.", "Tiffany", "Trade Cas.", "Trade Cases", "Trans. App.", "Tread", "Tread.", "Tread. Const.",
  "Treas. Dec.", "Treas. Dec. Int. Rev.", "Tribal", "Tuck.", "Tuck. & Cl.", "Tuck. Surr.", "Tuck.& C.",
  "Tyl.", "Tyler", "Tyng", "U. S.", "U. S. Law Int.", "U. S. Law J.", "U. S. R.", "U. S. Rep.",
  "U.C.C. Rep. Serv.", "U.C.C. Rep. Serv. 2d", "U.C.C. Rep. Serv.2d", "U.C.C. Rep.Serv.",
  "U.C.C. Rep.Serv.2d", "U.S.", "U.S. App. D.C.", "U.S. App. LEXIS", "U.S. App. Vet. Claims LEXIS",
  "U.S. Appx.", "U.S. CMCR LEXIS", "U.S. Cl. Ct. LEXIS", "U.S. Claims LEXIS", "U.S. Commerce Ct. LEXIS",
  "U.S. Ct. Cl. LEXIS", "U.S. Dist. LEXIS", "U.S. LEXIS", "U.S. Law Int.", "U.S. Tax Ct. LEXIS",
  "U.S. Vet. App. LEXIS", "U.S.App.D.C.", "U.S.C.M.A.", "U.S.L.Ed.", "U.S.L.Ed.2d", "U.S.L.W.",
  "U.S.Law.Ed.", "U.S.P.Q.", "U.S.P.Q.2d", "U.S.R.", "U.S.S.C.Rep.", "UCC Rep. Serv.", "UCC Rep. Serv. 2d",
  "UCC Rep. Serv.2d", "UCC Rep.Serv.", "UCC Rep.Serv.2d", "UNITED STATES TAX COURT REPORT",
  "UNITED STATES TAX COURT REPORTS", "US", "US Dist LEXIS", "USCMA", "USLW", "USPQ", "USPQ 2d", "USPQ2d",
  "USSCR", "USTC", "UT", "UT App", "UT App.", "UT Ct. App.", "UTApp", "Unemployment Ins. Rep.",
  "Unrep. Tenn. Cas.", "Utah", "Utah 2d", "Utah Adv. Rep.", "Utah App", "Utah App.", "Utah App. LEXIS",
  "Utah Ct. App.", "Utah LEXIS", "Util. L. Rep.", "V.", "V.I.", "V.I. LEXIS", "V.I. Super", "V.I. Super.",
  "V.I. Supreme LEXIS", "V.R.", "VI", "VI Super", "VI Super.", "VT", "Va.", "Va. App.", "Va. App. LEXIS",
  "Va. Cas.", "Va. Ch. Dec.", "Va. Cir.", "Va. Cir. LEXIS", "Va. Col. Dec.", "Va. Dec.", "Va. LEXIS",
  "Va. Law J.", "Va. Law Rep.", "Va. Leigh", "Va. Rep.", "Va. Unpub. LEXIS", "Va.App.", "Va.Dec.",
  "Van Ness", "Vaux", "Verm.", "Verm. Rep.", "Vet. App.", "Vet.App.", "Vir. L.J.", "Virg.", "Vr.", "Vroom",
  "Vroom.", "Vt Super", "Vt.", "Vt. LEXIS", "Vt. Rep.", "Vt. Super.", "Vt. Super. LEXIS", "Vt. Unpub. LEXIS",
  "W.", "W. & S.", "W. Va.", "W. Va. LEXIS", "W.& W.", "W.2d", "W.App.", "W.L. Bull.", "W.L. M.",
  "W.L. Monthly", "W.L.B.", "W.L.J.", "W.L.M.", "W.N.C.", "W.R.", "W.St.", "W.T.", "W.Ty.R.", "W.V.",
  "W.Va.", "W.W. Harr.", "W.W. Harr. Del", "W.W.H", "W.W.Harr.", "WASH", "WI", "WI App", "WI.App.", "WL",
  "WY", "WYO", "Wa.", "Wa.2d", "Wa.3d", "Wa.A.", "Wage & Hour Cas.", "Wage & Hour Cas. 2d", "Walk.",
  "Walk. Ch.", "Walk.Miss.", "Walk.Pa.", "Walker", "Wall.", "Wall. C.C", "Wall. Cir. Ct.", "Wall. Jr.",
  "Wall. Jr. Append.", "Wall. Jr. C.C.", "Wall.Rep.", "Wall.S.C.", "Wallace R.", "Ware", "Ware.", "Wash.",
  "Wash. 2d", "Wash. 3d", "Wash. App.", "Wash. App. 2d", "Wash. App. LEXIS", "Wash. C. C.",
  "Wash. C. C. Rep.", "Wash. Co.", "Wash. Co. R.", "Wash. Co. Rep.", "Wash. Co. Repr.", "Wash. LEXIS",
  "Wash. Rep.", "Wash. Terr.", "Wash. Terr. LEXIS", "Wash.2d", "Wash.3d", "Wash.App.", "Wash.App.2d",
  "Wash.Co.", "Wash.St.", "Wash.T.", "Wash.Ter.", "Wash.Ter.N.S.", "Wash.Terr.", "Wash.Ty.", "Wash.Va.",
  "Watts", "Watts & S.", "Watts & Serg.", "Watts Rep.", "Week. Law Gaz.", "Week. No.", "Week. Notes Cas.",
  "Weekly L. Bull.", "Weekly Law Bulletin", "Weekly LawBulletin", "Wells' Notebook", "Wend.", "Wend. Rep.",
  "Wendell", "Wendell Rep.", "West Co. Rep.", "West Coast Rep.", "West Law Month.", "West Va.", "West. Jur.",
  "West. Law J.", "West. Law Month.", "West. Law. J.", "Wh.", "Wh. Rep.", "Whar.", "Whar. Rep.", "Whart.",
  "Whart. Hom.", "Whart. Rep.", "Whart. St. Tr.", "Whart.Pa.", "Wharton", "Wheat.", "Wheat. Rep.", "Wheaton",
  "Wheaton Rep.", "Wheel. Cr. Cas.", "Wheeler. Cr. Cas.", "White & W.", "White & W.Civ.Cas.Ct.App.",
  "Wi.& Will.", "Will.", "Will.Mass.", "Williams", "Willson", "Willson Rep.", "Wils. Ind.", "Wils. Minn.",
  "Wils. Oreg.", "Wilson", "Wilson's Red Book", "Win.", "Wis 2d", "Wis.", "Wis. 2d", "Wis. Rep.", "Wis.2d",
  "Wisc. App. LEXIS", "Wisc. Cir. LEXIS", "Wisc. LEXIS", "Wkly. Dig.", "Wkly. Law Gaz.",
  "Wkly. Law Gaz. No.", "Wkly. N.C", "Wkly. Notes Cas.", "Wkly. Notes. Cas.", "Wl", "Wn", "Wn.", "Wn. 2d",
  "Wn. App.", "Wn. App. 2d", "Wn. Terr.", "Wn.2d", "Wn.3d", "Wn.App.", "Wood. & Minot", "Woodb. & M.",
  "Woods", "Woods C.C.", "Woods.", "Wool.", "Woolw.", "Woolw. Rep.", "Woolworth", "Woolworth's Cir. Ct. R.",
  "Wright", "Wy.", "Wyo.", "Wyo. LEXIS", "Wythe", "Wythe's R.", "Wythe's Rep.", "Y.", "Yates",
  "Yates Sel. Cas.", "Yea.", "Yeates", "Yeates Rep.", "Yer.", "Yer. Rep.", "Yerg.", "Yerg. Rep.", "York",
  "York Leg. Rec.", "York Leg. Record", "York Legal Record", "cal. 4th", "mills", "mt", "p.2 d", "p.2d",
  "wl"
]);

const WEEKLY = 'Fla. L. Weekly';
const WEEKLY_SUPP = 'Fla. L. Weekly Supp.';

const SOUTHERN_LOOSE_SHAPE = /^(?:so|sou|south|southern)(?:rep|reporter)?(?:[234](?:d|nd|rd|th))?$/;
const WEEKLY_PLAIN = /^Fla\. L\. Weekly(?: ([A-Z]))?$/;

// ---------------------------------------------------------------------------
// Normalization
// ---------------------------------------------------------------------------

const WS = '[ \\t\\n\\r\\f\\v\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000]';
const WS_RUN = new RegExp(WS + '+', 'g');
const WS_EDGE = new RegExp('^' + WS + '+|' + WS + '+$', 'g');

function normalize(s: string): string {
  return s.normalize('NFKC').replace(WS_RUN, ' ').replace(WS_EDGE, '');
}

function loose(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]/g, '');
}

// ---------------------------------------------------------------------------
// Grammar (ASCII only; every class is explicit)
// ---------------------------------------------------------------------------

const CITE_START = /(?<![A-Za-z0-9])[0-9]{1,4}(?= )/g;
const GENERIC_SRC =
  "(?<![A-Za-z0-9])([0-9]{1,4}) " +
  "([A-Z][A-Za-z0-9.&']*(?: [A-Za-z0-9.&']+){0,4}?) " +
  "([A-Z]?[0-9]{1,6})(?![A-Za-z0-9])";
const PIN = /^(?:, ?(?:at )?| at )([0-9]{1,6})(?:[-–—]([0-9]{1,6}))?(?: ?n\.? ?[0-9]{1,3})?/;
const PAREN = /^ ?\(([^()]*)\)/;
const MONTH = '(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)';
const COURT_YEAR = new RegExp('^(.*?),? ?(?:' + MONTH + '\\.? [0-9]{1,2}, )?([0-9]{4})$');
const FLORIDA_COURT =
  /^Fla\.(?: (?:[1-6](?:st|nd|rd|th|d) (?:DCA|Dist\. Ct\. App\.|Dist\.)|Dist\. Ct\. App\.|Sup\. Ct\.|App\.(?: [1-6](?:st|nd|rd|th|d) Dist\.)?))?$/;
// Positive identification of non-Florida courts. A Southern Reporter cite falls through only
// when its parenthetical matches one of these exactly; anything else vetoes.
// STATE_ABBREVS is asserted equal to the Python list by test_reporter_table_sync.py.
const STATE_ABBREVS = [
  'Ala.', 'Alaska', 'Ariz.', 'Ark.', 'Cal.', 'Colo.', 'Conn.', 'Del.', 'Fla.', 'Ga.', 'Haw.', 'Idaho',
  'Ill.', 'Ind.', 'Iowa', 'Kan.', 'Ky.', 'La.', 'Me.', 'Md.', 'Mass.', 'Mich.', 'Minn.', 'Miss.', 'Mo.',
  'Mont.', 'Neb.', 'Nev.', 'N.H.', 'N.J.', 'N.M.', 'N.Y.', 'N.C.', 'N.D.', 'Ohio', 'Okla.', 'Or.', 'Pa.',
  'R.I.', 'S.C.', 'S.D.', 'Tenn.', 'Tex.', 'Utah', 'Vt.', 'Va.', 'Wash.', 'W. Va.', 'Wis.', 'Wyo.',
  'D.C.', 'P.R.',
];
const STATES_RE = STATE_ABBREVS.map((x) => x.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|');
const CIRCUIT_ORD = '[1-5](?:st|nd|rd|th|d)?';
const NON_FLORIDA_COURT = new RegExp(
  '^(?:' +
    String.raw`Ala\.(?: (?:App\.|Civ\. App\.|Crim\. App\.|Ct\. App\.|Ct\. Civ\. App\.|Ct\. Crim\. App\.|Cir\. Ct\.|Sup\. Ct\.))?` +
    String.raw`|La\.(?: (?:Ct\. )?App\.(?: ` + CIRCUIT_ORD + String.raw` Cir\.| Orleans)?| Dist\. Ct\.| Sup\. Ct\.)?` +
    String.raw`|Miss\.(?: (?:Ct\. App\.|App\.|Cir\. Ct\.|Ch\. Ct\.|Cnty\. Ct\.|Sup\. Ct\.))?` +
    String.raw`|(?:1st|2d|3d|4th|5th|6th|7th|8th|9th|10th|11th) Cir\.|D\.C\. Cir\.|Fed\. Cir\.` +
    String.raw`|U\.S\.(?: Sup\. Ct\.)?|Fed\. Cl\.|Ct\. Int'l Trade` +
    String.raw`|(?:Bankr\. )?(?:[NSEWMC]\.D\.|D\.) (?:` + STATES_RE + ')' +
    ')$',
);
const FLORIDAISH = /fla|\bfl/;
const SIGNAL = /^(?:See also|See generally|See|Cf\.|Accord|But see|But cf\.|Compare|Contra|E\.g\.),? /;
const CASE_NAME = /(?: v\.? )|^(?:In re|Ex parte|Matter of|Estate of|State ex rel\.|Application of) /;
const NON_ASCII = /[^\x00-\x7f]/;
const NON_ASCII_G = /[^\x00-\x7f]/g;
const DESIGNATION = /\b(?:et al|et ux|et vir)\b\.?/g;
const TYPO_PUNCT = /[§¶·‐-―‘-‟•…ʼ]/g;

type Parsed = {
  reporter: string;
  volume: number;
  page: number;
  section: string;
  kind: 'southern' | 'weekly' | 'other';
  pins: Array<[number, number | null]>;
  court: string | null;
  prefix: string;
};

type Row = {
  cluster_id: number;
  case_name: string | null;
  first_page: number | null;
  last_page: number | null;
  court_id: string | null;
};

function veto(reason: string, p?: Parsed | null, clusterId: number | null = null): Gate1Result {
  if (!p) return { verdict: 'veto', reason, clusterId: null };
  return { verdict: 'veto', reason, reporter: p.reporter, volume: p.volume, page: p.page, clusterId };
}

function tail(
  s: string,
  end: number,
): { pins: Array<[number, number | null]>; content: string | null; span: [number, number] | null } {
  let rest = s.slice(end);
  const pins: Array<[number, number | null]> = [];
  for (;;) {
    const pm = PIN.exec(rest);
    if (!pm) break;
    pins.push([parseInt(pm[1], 10), pm[2] ? parseInt(pm[2], 10) : null]);
    rest = rest.slice(pm[0].length);
  }
  const tailEnd = s.length - rest.length;
  const cm = PAREN.exec(rest);
  if (!cm) return { pins, content: null, span: null };
  return { pins, content: cm[1], span: [tailEnd, tailEnd + cm[0].length] };
}

function courtName(content: string): string {
  const m = COURT_YEAR.exec(content);
  return (m ? m[1] : content).replace(/[ ,]+$/, '');
}

function courtKnown(content: string | null): boolean {
  if (content === null || NON_ASCII.test(content)) return false;
  const name = courtName(content);
  return FLORIDA_COURT.test(name) || NON_FLORIDA_COURT.test(name);
}

/**
 * All generic reporter-citation matches in s, including overlapping ones. A candidate that
 * starts inside the court parenthetical of an earlier match is skipped, but only when that
 * parenthetical is a recognized court ("La. App. 1 Cir. 2015" must not yield a second
 * citation "1 Cir. 2015"). An unrecognized parenthetical hides nothing.
 */
function scan(s: string): RegExpExecArray[] {
  const out: RegExpExecArray[] = [];
  const spans: Array<[number, number]> = [];
  for (const cand of s.matchAll(CITE_START)) {
    const pos = cand.index ?? 0;
    if (spans.some(([a, b]) => a <= pos && pos < b)) continue;
    const re = new RegExp(GENERIC_SRC, 'y');
    re.lastIndex = pos;
    const m = re.exec(s);
    if (!m) continue;
    out.push(m);
    const t = tail(s, m.index + m[0].length);
    if (t.span !== null && courtKnown(t.content)) spans.push(t.span);
  }
  return out;
}

function classify(
  rawReporter: string,
  pageText: string,
): { kind: 'southern' | 'weekly' | 'other'; canon: string | null; problem: string | null } {
  const letter = /^[A-Za-z]/.test(pageText) ? pageText[0] : null;
  const canon = Object.prototype.hasOwnProperty.call(SOUTHERN_EXACT, rawReporter)
    ? SOUTHERN_EXACT[rawReporter]
    : undefined;
  if (canon !== undefined) return { kind: 'southern', canon, problem: letter ? 'bad_page' : null };
  if (rawReporter === WEEKLY_SUPP) return { kind: 'weekly', canon: WEEKLY_SUPP, problem: letter ? 'bad_page' : null };
  const wm = WEEKLY_PLAIN.exec(rawReporter);
  if (wm) {
    if (wm[1] && letter) return { kind: 'weekly', canon: WEEKLY, problem: 'bad_page' };
    return { kind: 'weekly', canon: WEEKLY, problem: null };
  }
  for (const lk of [loose(rawReporter), loose(rawReporter.replace(/0/g, 'o').replace(/[1I]/g, 'l'))]) {
    if (
      IN_SCOPE_LOOSE.has(lk) ||
      SOUTHERN_LOOSE_SHAPE.test(lk) ||
      (lk.startsWith('fl') && (lk.includes('weekly') || lk.includes('wkly')) && !lk.includes('fed'))
    ) {
      return { kind: 'other', canon: null, problem: 'ambiguous_reporter' };
    }
  }
  return { kind: 'other', canon: rawReporter, problem: null };
}

function parseMatch(s: string, m: RegExpExecArray): { parsed: Parsed | null; problem: string | null } {
  const { kind, canon, problem } = classify(m[2], m[3]);
  if (problem) return { parsed: null, problem };
  const pageText = m[3];
  const letter = /^[A-Za-z]/.test(pageText);
  const page = parseInt(letter ? pageText.slice(1) : pageText, 10);
  let section = '';
  if (kind === 'weekly') {
    const wm = WEEKLY_PLAIN.exec(m[2]);
    section = (wm && wm[1] ? wm[1] : null) ?? (letter ? pageText[0] : '');
  }
  const t = tail(s, m.index + m[0].length);
  return {
    parsed: {
      reporter: canon ?? m[2],
      volume: parseInt(m[1], 10),
      page,
      section,
      kind,
      pins: t.pins,
      court: t.content,
      prefix: s.slice(0, m.index),
    },
    problem: null,
  };
}

function floridaish(name: string): boolean {
  return FLORIDAISH.test(name.toLowerCase().replace(/[1i|]/g, 'l').replace(/0/g, 'o'));
}

/** True if name is a Florida court exactly, or after OCR-folding only its leading 'Fla.' token. */
function ocrFloridaCourt(name: string): boolean {
  if (FLORIDA_COURT.test(name)) return true;
  const k = name.indexOf(' ');
  const tok = k < 0 ? name : name.slice(0, k);
  const rest = k < 0 ? '' : name.slice(k + 1);
  if (tok.toLowerCase().replace(/[1i|]/g, 'l').replace(/0/g, 'o') === 'fla.') {
    return FLORIDA_COURT.test('Fla.' + (rest ? ' ' + rest : ''));
  }
  return false;
}

/**
 * Fall-through requires a positive match against a known non-Florida court. Everything
 * unrecognized vetoes: 'ambiguous_court' when it looks like a (possibly OCR-damaged) Florida
 * court, 'malformed' otherwise.
 */
function courtScope(court: string | null): { decision: 'florida' | 'fall_through' | 'veto'; reason: string } {
  if (court === null) return { decision: 'veto', reason: 'malformed' };
  if (NON_ASCII.test(court)) return { decision: 'veto', reason: 'non_ascii_court' };
  const name = courtName(court);
  if (name === '') return { decision: 'veto', reason: 'malformed' };
  if (FLORIDA_COURT.test(name)) return { decision: 'florida', reason: 'ok' };
  if (NON_FLORIDA_COURT.test(name)) return { decision: 'fall_through', reason: 'non_florida_court' };
  if (floridaish(name) || ocrFloridaCourt(name)) return { decision: 'veto', reason: 'ambiguous_court' };
  return { decision: 'veto', reason: 'malformed' };
}

// ---------------------------------------------------------------------------
// Caption trigrams
// ---------------------------------------------------------------------------

function fold(s: string): string {
  return s.normalize('NFKC').normalize('NFD').replace(/\p{Mn}/gu, '');
}

function captionTokens(folded: string): string {
  let s = folded.toLowerCase().split('&').join(' and ');
  s = s.replace(DESIGNATION, ' ');
  s = s.replace(/[^a-z0-9]+/g, ' ');
  return s.replace(/^ +| +$/g, '');
}

function trigrams(tokens: string): Set<string> {
  const grams = new Set<string>();
  for (const word of tokens.split(' ')) {
    if (word === '') continue;
    const padded = '  ' + word + ' ';
    for (let i = 0; i < padded.length - 2; i++) grams.add(padded.slice(i, i + 3));
  }
  return grams;
}

function captionMatches(given: string, stored: string | null): { ok: boolean; reason: string } {
  if (stored === null || normalize(stored) === '') return { ok: false, reason: 'caption_unverifiable' };
  const g = fold(given).replace(TYPO_PUNCT, ' ');
  if (NON_ASCII.test(g)) return { ok: false, reason: 'caption_non_ascii' };
  const a = trigrams(captionTokens(g));
  const b = trigrams(captionTokens(fold(stored).replace(TYPO_PUNCT, ' ').replace(NON_ASCII_G, ' ')));
  if (a.size === 0 || b.size === 0) return { ok: false, reason: 'caption_mismatch' };
  let inter = 0;
  for (const t of a) if (b.has(t)) inter++;
  const union = a.size + b.size - inter;
  if (inter * JACCARD_DEN >= union * JACCARD_NUM) return { ok: true, reason: 'ok' };
  const small = Math.min(a.size, b.size);
  if (small >= CONTAINMENT_MIN_TRIGRAMS && inter * CONTAINMENT_DEN >= small * CONTAINMENT_NUM) {
    return { ok: true, reason: 'ok' };
  }
  return { ok: false, reason: 'caption_mismatch' };
}

function captionFromPrefix(prefix: string): string | null {
  let p = prefix;
  for (let i = 0; i < 4; i++) {
    const n = p.replace(SIGNAL, '');
    if (n === p) break;
    p = n;
  }
  p = p.replace(/[ ,]+$/, '');
  if (p !== '' && CASE_NAME.test(p)) return p;
  return null;
}

// ---------------------------------------------------------------------------
// Database
// ---------------------------------------------------------------------------

/**
 * 'fla' (Supreme Court) or 'dca' from the citing parenthetical; null if not a Florida court.
 * DCA district numbers are deliberately not compared: CourtListener lumps every DCA into the
 * single court_id 'fladistctapp'.
 */
function courtLevel(court: string | null): 'fla' | 'dca' | null {
  if (court === null || NON_ASCII.test(court)) return null;
  const name = courtName(court);
  if (name === 'Fla.' || name === 'Fla. Sup. Ct.') return 'fla';
  return FLORIDA_COURT.test(name) ? 'dca' : null;
}

function rowProblem(p: Parsed, caption: string | null, row: Row): string | null {
  const level = courtLevel(p.court);
  if ((level === 'dca' && row.court_id === 'fla') || (level === 'fla' && row.court_id === 'fladistctapp')) {
    return 'court_mismatch';
  }
  if (caption !== null) {
    const r = captionMatches(caption, row.case_name);
    if (!r.ok) return r.reason;
  }
  if (p.pins.length > 0) {
    const lo = row.first_page !== null ? row.first_page : p.page;
    if (row.last_page === null) return 'pin_unverifiable';
    if (row.last_page < lo) return 'bad_bounds';
    for (const [a, b] of p.pins) {
      if (b !== null && b < a) return 'pin_out_of_bounds';
      for (const x of [a, b]) {
        if (x !== null && !(lo <= x && x <= row.last_page)) return 'pin_out_of_bounds';
      }
    }
  }
  return null;
}

type SqliteModule = typeof import('node:sqlite');

function loadSqlite(): SqliteModule | null {
  try {
    const mod = process.getBuiltinModule('node:sqlite') as SqliteModule | undefined;
    if (mod && typeof mod.DatabaseSync === 'function') return mod;
  } catch {
    // fall through to the Python child process
  }
  return null;
}

function lookup(sqlite: SqliteModule, dbPath: string, reporter: string, volume: number, page: number, section: string): Row[] {
  const db = new sqlite.DatabaseSync(dbPath, { readOnly: true, timeout: DB_TIMEOUT_MS });
  try {
    const stmt = db.prepare(
      'SELECT cluster_id, case_name, first_page, last_page, court_id FROM citation_index ' +
        'WHERE reporter = ? AND volume = ? AND page = ? AND section = ? ORDER BY cluster_id',
    );
    return stmt.all(reporter, volume, page, section) as unknown as Row[];
  } finally {
    db.close();
  }
}

function checkNormalized(s: string, dbPath: string, sqlite: SqliteModule): Gate1Result {
  if (s.length > MAX_CITATION_CHARS) return veto('too_long');
  const matches = scan(s);
  if (matches.length === 0) return veto('unparseable');
  if (matches.length > 1) return veto('multiple_citations');
  const { parsed: p, problem } = parseMatch(s, matches[0]);
  if (problem || !p) return veto(problem ?? 'unparseable');

  if (p.kind === 'other') {
    if (!KNOWN_REPORTERS.has(p.reporter) && p.court !== null && !NON_ASCII.test(p.court)) {
      const cname = courtName(p.court);
      if (cname !== '' && ocrFloridaCourt(cname)) return veto('florida_court_unknown_reporter', p);
    }
    return { verdict: 'fall_through', reason: 'not_florida_key', reporter: p.reporter, volume: p.volume, page: p.page, clusterId: null };
  }
  if (p.kind === 'southern') {
    const { decision, reason } = courtScope(p.court);
    if (decision === 'veto') return veto(reason, p);
    if (decision === 'fall_through') {
      return { verdict: 'fall_through', reason, reporter: p.reporter, volume: p.volume, page: p.page, clusterId: null };
    }
  }

  try {
    const rows = lookup(sqlite, dbPath, p.reporter, p.volume, p.page, p.section);
    if (rows.length === 0) return veto('not_found', p);
    const caption = captionFromPrefix(p.prefix);
    let first: { reason: string; clusterId: number } | null = null;
    for (const row of rows) {
      const why = rowProblem(p, caption, row);
      if (why === null) {
        return { verdict: 'pass', reason: 'verified', reporter: p.reporter, volume: p.volume, page: p.page, clusterId: row.cluster_id };
      }
      if (first === null) first = { reason: why, clusterId: row.cluster_id };
    }
    return veto(first!.reason, p, first!.clusterId);
  } catch {
    return veto('db_unavailable', p);
  }
}

// ---------------------------------------------------------------------------
// Python child-process fallback
// ---------------------------------------------------------------------------

function repoRoot(): string {
  if (typeof __dirname !== 'undefined') return resolve(__dirname, '..', '..', '..');
  let dir = process.cwd();
  for (let i = 0; i < 8; i++) {
    if (existsSync(join(dir, 'db', 'build_sqlite_index.py'))) return dir;
    const up = resolve(dir, '..');
    if (up === dir) break;
    dir = up;
  }
  return process.cwd();
}

function pythonGate(citation: string, dbPath: string): Gate1Result {
  try {
    const py = join(homedir(), '.venv-cascade', 'bin', 'python');
    const script = join(repoRoot(), 'pipeline', 'gate1.py');
    const out = execFileSync(py, [script, '--db', dbPath, '--citation=' + citation], {
      encoding: 'utf8',
      timeout: PY_TIMEOUT_MS,
      stdio: ['ignore', 'pipe', 'ignore'],
    });
    const j = JSON.parse(out) as Record<string, unknown>;
    if (j.verdict !== 'pass' && j.verdict !== 'veto' && j.verdict !== 'fall_through') return veto('python_bad_output');
    const r: Gate1Result = { verdict: j.verdict, reason: String(j.reason), clusterId: typeof j.cluster_id === 'number' ? j.cluster_id : null };
    if (typeof j.reporter === 'string') r.reporter = j.reporter;
    if (typeof j.volume === 'number') r.volume = j.volume;
    if (typeof j.page === 'number') r.page = j.page;
    return r;
  } catch {
    return veto('python_fallback_failed');
  }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export function localGate1(citation: string, opts?: LocalGate1Options): Gate1Result {
  try {
    const dbPath = opts?.dbPath ?? process.env.KINGSFIELD_FLORIDA_DB ?? join(repoRoot(), 'kingsfield_florida.db');
    if (typeof citation !== 'string') return veto('unparseable');
    const sqlite = opts?.forcePythonFallback ? null : loadSqlite();
    if (sqlite === null) return pythonGate(citation, dbPath);
    return checkNormalized(normalize(citation), dbPath, sqlite);
  } catch {
    return veto('internal_error');
  }
}
