// Single source of truth for jurisdiction — picked once, scopes Case Law
// (CourtListener court filter) AND Legislation (statute source) together.
//
// courtIds: CourtListener court IDs used to scope opinion search. Empty = no
//   court filter (search everything in that scope).
// statuteUrl / statuteLabel: the authoritative statute/code source for the
//   jurisdiction (used by the in-app Legislation reader).

export type JurisdictionType = "federal" | "state";

export interface Jurisdiction {
    key: string;            // stable id, e.g. "federal" | "CA"
    label: string;          // display name
    type: JurisdictionType;
    abbr?: string;          // state abbreviation
    courtIds: string[];     // CourtListener court ids for case-law scoping
    statuteUrl: string;     // authoritative code/statute source
    statuteLabel: string;   // e.g. "United States Code" / "California Codes"
}

export const FEDERAL: Jurisdiction = {
    key: "federal",
    label: "Federal",
    type: "federal",
    // SCOTUS + the 13 circuit courts of appeals
    courtIds: ["scotus", "ca1", "ca2", "ca3", "ca4", "ca5", "ca6", "ca7", "ca8", "ca9", "ca10", "ca11", "cadc", "cafc"],
    statuteUrl: "https://uscode.house.gov/",
    statuteLabel: "United States Code",
};

// State statute/code sources (authoritative official or Justia fallback).
const STATE_STATUTE_URLS: Record<string, string> = {
    AL: "https://law.justia.com/codes/alabama/", AK: "https://law.alaska.gov/",
    AZ: "https://www.azleg.gov/arstitle/", AR: "https://law.justia.com/codes/arkansas/",
    CA: "https://leginfo.legislature.ca.gov/faces/codes.xhtml", CO: "https://leg.colorado.gov/colorado-revised-statutes",
    CT: "https://www.cga.ct.gov/current/pub/titles.htm", DE: "https://delcode.delaware.gov/",
    FL: "https://www.flsenate.gov/Laws/Statutes", GA: "https://law.georgia.gov/georgia-code",
    HI: "https://www.capitol.hawaii.gov/hrscurrent/", ID: "https://legislature.idaho.gov/statutesrules/idstat/",
    IL: "https://www.ilga.gov/legislation/ilcs/ilcs.asp", IN: "https://iga.in.gov/laws/",
    IA: "https://www.legis.iowa.gov/law/iowaCode", KS: "https://kslegislature.org/li/b2023_24/statute/",
    KY: "https://legislature.ky.gov/Law/Statutes/Pages/default.aspx", LA: "https://www.legis.la.gov/legis/LawSearch.aspx",
    ME: "https://legislature.maine.gov/statutes/", MD: "https://mgaleg.maryland.gov/mgawebsite/Laws/StatuteText",
    MA: "https://malegislature.gov/Laws/GeneralLaws", MI: "https://www.legislature.mi.gov/Laws",
    MN: "https://www.revisor.mn.gov/statutes/", MS: "https://law.justia.com/codes/mississippi/",
    MO: "https://revisor.mo.gov/main/PageSelect.aspx", MT: "https://leg.mt.gov/bills/mca/",
    NE: "https://nebraskalegislature.gov/laws/statutes.php", NV: "https://www.leg.state.nv.us/nrs/",
    NH: "https://www.gencourt.state.nh.us/rsa/html/indexes/", NJ: "https://www.njleg.state.nj.us/",
    NM: "https://www.nmlegis.gov/Legislation/Statutes", NY: "https://www.nysenate.gov/legislation/laws/",
    NC: "https://www.ncleg.gov/Laws/GeneralStatutesSections/Chapter0", ND: "https://ndlegis.gov/information/statutes/cent-code.html",
    OH: "https://codes.ohio.gov/ohio-revised-code", OK: "https://www.oscn.net/applications/oscn/Index.asp?level=1",
    OR: "https://www.oregonlegislature.gov/bills_laws/pages/ors.aspx", PA: "https://www.legis.state.pa.us/cfdocs/legis/LI/Public/cons_index.cfm",
    RI: "https://webserver.rilegislature.gov/Statutes/", SC: "https://www.scstatehouse.gov/code/title1.php",
    SD: "https://law.sd.gov/", TN: "https://www.tn.gov/sos/acts/",
    TX: "https://statutes.capitol.texas.gov/", UT: "https://le.utah.gov/xcode/code.html",
    VT: "https://legislature.vermont.gov/statutes/", VA: "https://law.lis.virginia.gov/vacode/",
    WA: "https://apps.leg.wa.gov/rcw/", WV: "https://code.wvlegislature.gov/",
    WI: "https://docs.legis.wisconsin.gov/statutes/statutes", WY: "https://wyoleg.gov/StateStatutes/StatutesConstitution",
    DC: "https://code.dccouncil.gov/us/dc/council/code", PR: "https://law.justia.com/codes/puerto-rico/",
};

const STATE_NAMES: Record<string, string> = {
    AL: "Alabama", AK: "Alaska", AZ: "Arizona", AR: "Arkansas", CA: "California", CO: "Colorado",
    CT: "Connecticut", DE: "Delaware", FL: "Florida", GA: "Georgia", HI: "Hawaii", ID: "Idaho",
    IL: "Illinois", IN: "Indiana", IA: "Iowa", KS: "Kansas", KY: "Kentucky", LA: "Louisiana",
    ME: "Maine", MD: "Maryland", MA: "Massachusetts", MI: "Michigan", MN: "Minnesota", MS: "Mississippi",
    MO: "Missouri", MT: "Montana", NE: "Nebraska", NV: "Nevada", NH: "New Hampshire", NJ: "New Jersey",
    NM: "New Mexico", NY: "New York", NC: "North Carolina", ND: "North Dakota", OH: "Ohio", OK: "Oklahoma",
    OR: "Oregon", PA: "Pennsylvania", RI: "Rhode Island", SC: "South Carolina", SD: "South Dakota",
    TN: "Tennessee", TX: "Texas", UT: "Utah", VT: "Vermont", VA: "Virginia", WA: "Washington",
    WV: "West Virginia", WI: "Wisconsin", WY: "Wyoming", DC: "D.C.", PR: "Puerto Rico",
};

// CourtListener court ids for each state's high courts, where the id is stable
// and known. States not listed here fall back to no court filter (search all)
// until the full court snapshot is available.
const STATE_COURT_IDS: Record<string, string[]> = {
    CA: ["cal", "calctapp"], NY: ["ny", "nyappdiv", "nyappterm"], TX: ["tex", "texapp", "texcrimapp"],
    FL: ["fla", "fladistctapp"], IL: ["ill", "illappct"], PA: ["pa", "pasuperct", "pacommwct"],
    OH: ["ohio", "ohioctapp"], MI: ["mich", "michctapp"], NJ: ["nj", "njsuperctappdiv"],
    GA: ["ga", "gactapp"], NC: ["nc", "ncctapp"], VA: ["va", "vactapp"], WA: ["wash", "washctapp"],
    MA: ["mass", "massappct"], CO: ["colo", "coloctapp"],
};

export const STATE_JURISDICTIONS: Jurisdiction[] = Object.keys(STATE_NAMES)
    .sort((a, b) => STATE_NAMES[a].localeCompare(STATE_NAMES[b]))
    .map((abbr) => ({
        key: abbr,
        label: STATE_NAMES[abbr],
        type: "state" as const,
        abbr,
        courtIds: STATE_COURT_IDS[abbr] ?? [],
        statuteUrl: STATE_STATUTE_URLS[abbr] ?? `https://law.justia.com/codes/${STATE_NAMES[abbr].toLowerCase().replace(/\s/g, "-")}/`,
        statuteLabel: `${STATE_NAMES[abbr]} Statutes`,
    }));

export const ALL_JURISDICTIONS: Jurisdiction[] = [FEDERAL, ...STATE_JURISDICTIONS];

export function findJurisdiction(key: string): Jurisdiction {
    return ALL_JURISDICTIONS.find((j) => j.key === key) ?? FEDERAL;
}
