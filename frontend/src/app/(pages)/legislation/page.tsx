"use client";

import { useState } from "react";
import { Search, Scroll, ExternalLink, ChevronDown, Globe, Landmark, MessageSquare } from "lucide-react";
import { proSeAsk, proSeChatWithDocs } from "@/app/lib/mikeApi";

interface LegislationSource {
    label: string;
    description: string;
    url: string;
    type: "federal" | "state" | "regulatory";
}

const FEDERAL_SOURCES: LegislationSource[] = [
    {
        label: "U.S. Code",
        description: "All federal statutes, codified by title and section (e.g. 18 U.S.C. § 1001)",
        url: "https://uscode.house.gov/",
        type: "federal",
    },
    {
        label: "U.S. Constitution",
        description: "The founding document, all amendments, annotation links to major case law",
        url: "https://constitution.congress.gov/",
        type: "federal",
    },
    {
        label: "Code of Federal Regulations",
        description: "All agency regulations — eCFR.gov provides the current in-force text (e.g. 26 CFR 1.61-1)",
        url: "https://www.ecfr.gov/",
        type: "regulatory",
    },
    {
        label: "Federal Register",
        description: "Proposed and final rules, presidential documents, regulatory notices",
        url: "https://www.federalregister.gov/",
        type: "regulatory",
    },
    {
        label: "Congress.gov",
        description: "Pending and enacted legislation, bill text, congressional record, sponsor info",
        url: "https://www.congress.gov/",
        type: "federal",
    },
    {
        label: "GovInfo.gov",
        description: "Authenticated copies of the Congressional Record, Statutes at Large, public laws",
        url: "https://www.govinfo.gov/",
        type: "federal",
    },
];

const STATES = [
    { abbr: "AL", name: "Alabama" }, { abbr: "AK", name: "Alaska" }, { abbr: "AZ", name: "Arizona" },
    { abbr: "AR", name: "Arkansas" }, { abbr: "CA", name: "California" }, { abbr: "CO", name: "Colorado" },
    { abbr: "CT", name: "Connecticut" }, { abbr: "DE", name: "Delaware" }, { abbr: "FL", name: "Florida" },
    { abbr: "GA", name: "Georgia" }, { abbr: "HI", name: "Hawaii" }, { abbr: "ID", name: "Idaho" },
    { abbr: "IL", name: "Illinois" }, { abbr: "IN", name: "Indiana" }, { abbr: "IA", name: "Iowa" },
    { abbr: "KS", name: "Kansas" }, { abbr: "KY", name: "Kentucky" }, { abbr: "LA", name: "Louisiana" },
    { abbr: "ME", name: "Maine" }, { abbr: "MD", name: "Maryland" }, { abbr: "MA", name: "Massachusetts" },
    { abbr: "MI", name: "Michigan" }, { abbr: "MN", name: "Minnesota" }, { abbr: "MS", name: "Mississippi" },
    { abbr: "MO", name: "Missouri" }, { abbr: "MT", name: "Montana" }, { abbr: "NE", name: "Nebraska" },
    { abbr: "NV", name: "Nevada" }, { abbr: "NH", name: "New Hampshire" }, { abbr: "NJ", name: "New Jersey" },
    { abbr: "NM", name: "New Mexico" }, { abbr: "NY", name: "New York" }, { abbr: "NC", name: "North Carolina" },
    { abbr: "ND", name: "North Dakota" }, { abbr: "OH", name: "Ohio" }, { abbr: "OK", name: "Oklahoma" },
    { abbr: "OR", name: "Oregon" }, { abbr: "PA", name: "Pennsylvania" }, { abbr: "RI", name: "Rhode Island" },
    { abbr: "SC", name: "South Carolina" }, { abbr: "SD", name: "South Dakota" }, { abbr: "TN", name: "Tennessee" },
    { abbr: "TX", name: "Texas" }, { abbr: "UT", name: "Utah" }, { abbr: "VT", name: "Vermont" },
    { abbr: "VA", name: "Virginia" }, { abbr: "WA", name: "Washington" }, { abbr: "WV", name: "West Virginia" },
    { abbr: "WI", name: "Wisconsin" }, { abbr: "WY", name: "Wyoming" },
    { abbr: "DC", name: "D.C." }, { abbr: "PR", name: "Puerto Rico" },
];

// Best official statute/code site per state
const STATE_LAW_URLS: Record<string, string> = {
    AL: "https://law.justia.com/codes/alabama/",
    AK: "https://law.alaska.gov/",
    AZ: "https://www.azleg.gov/arstitle/",
    AR: "https://advance.lexis.com/container?config=014CJAA5ZGVhZjA3LWI5ZmQtNDljNy1hNzUwLWIwYjYxMzAyZWRhMw==",
    CA: "https://leginfo.legislature.ca.gov/faces/codes.xhtml",
    CO: "https://leg.colorado.gov/colorado-revised-statutes",
    CT: "https://www.cga.ct.gov/current/pub/titles.htm",
    DE: "https://delcode.delaware.gov/",
    FL: "https://www.flsenate.gov/Laws/Statutes",
    GA: "https://law.georgia.gov/georgia-code",
    HI: "https://www.capitol.hawaii.gov/hrscurrent/",
    ID: "https://legislature.idaho.gov/statutesrules/idstat/",
    IL: "https://www.ilga.gov/legislation/ilcs/ilcs.asp",
    IN: "https://iga.in.gov/laws/",
    IA: "https://www.legis.iowa.gov/law/iowaCode",
    KS: "https://kslegislature.org/li/b2023_24/statute/",
    KY: "https://legislature.ky.gov/Law/Statutes/Pages/default.aspx",
    LA: "https://www.legis.la.gov/legis/LawSearch.aspx",
    ME: "https://legislature.maine.gov/statutes/",
    MD: "https://mgaleg.maryland.gov/mgawebsite/Laws/StatuteText",
    MA: "https://malegislature.gov/Laws/GeneralLaws",
    MI: "https://www.legislature.mi.gov/Laws",
    MN: "https://www.revisor.mn.gov/statutes/",
    MS: "https://law.justia.com/codes/mississippi/",
    MO: "https://revisor.mo.gov/main/PageSelect.aspx",
    MT: "https://leg.mt.gov/bills/mca/",
    NE: "https://nebraskalegislature.gov/laws/statutes.php",
    NV: "https://www.leg.state.nv.us/nrs/",
    NH: "https://www.gencourt.state.nh.us/rsa/html/indexes/",
    NJ: "https://www.njleg.state.nj.us/",
    NM: "https://www.nmlegis.gov/Legislation/Statutes",
    NY: "https://www.nysenate.gov/legislation/laws/",
    NC: "https://www.ncleg.gov/Laws/GeneralStatutesSections/Chapter0",
    ND: "https://ndlegis.gov/information/statutes/cent-code.html",
    OH: "https://codes.ohio.gov/ohio-revised-code",
    OK: "https://www.oscn.net/applications/oscn/Index.asp?level=1",
    OR: "https://www.oregonlegislature.gov/bills_laws/pages/ors.aspx",
    PA: "https://www.legis.state.pa.us/cfdocs/legis/LI/Public/cons_index.cfm",
    RI: "https://webserver.rilegislature.gov/Statutes/",
    SC: "https://www.scstatehouse.gov/code/title1.php",
    SD: "https://law.sd.gov/",
    TN: "https://www.tn.gov/sos/acts/",
    TX: "https://statutes.capitol.texas.gov/",
    UT: "https://le.utah.gov/xcode/code.html",
    VT: "https://legislature.vermont.gov/statutes/",
    VA: "https://law.lis.virginia.gov/vacode/",
    WA: "https://apps.leg.wa.gov/rcw/",
    WV: "https://code.wvlegislature.gov/",
    WI: "https://docs.legis.wisconsin.gov/statutes/statutes",
    WY: "https://wyoleg.gov/NXT/gateway.dll?f=templates&fn=default.htm",
    DC: "https://code.dccouncil.gov/",
    PR: "https://bvirtualogp.pr.gov/ogp/Bvirtual/leyesreferencia/PDF/",
};

function SourceCard({ source }: { source: LegislationSource }) {
    const typeColor =
        source.type === "federal"
            ? "bg-blue-100 text-blue-700"
            : source.type === "regulatory"
            ? "bg-purple-100 text-purple-700"
            : "bg-green-100 text-green-700";
    const typeLabel =
        source.type === "federal" ? "Federal" : source.type === "regulatory" ? "Regulatory" : "State";

    return (
        <a
            href={source.url}
            target="_blank"
            rel="noopener noreferrer"
            className="group flex items-start gap-3 rounded-lg border border-gray-200 bg-white p-3.5 hover:border-gray-400 hover:shadow-sm transition-all"
        >
            <Landmark className="h-4 w-4 text-gray-400 flex-shrink-0 mt-0.5 group-hover:text-gray-700 transition-colors" />
            <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-medium text-gray-900 group-hover:text-gray-700">{source.label}</span>
                    <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${typeColor}`}>{typeLabel}</span>
                </div>
                <p className="text-xs text-gray-500 mt-0.5 leading-snug">{source.description}</p>
            </div>
            <ExternalLink className="h-3.5 w-3.5 text-gray-300 flex-shrink-0 group-hover:text-gray-500 transition-colors" />
        </a>
    );
}

export default function LegislationPage() {
    const [query, setQuery] = useState("");
    const [showAllStates, setShowAllStates] = useState(false);
    const [proSeQuestion, setProSeQuestion] = useState("");
    const [proSeUrl, setProSeUrl] = useState("https://leg.colorado.gov/colorado-revised-statutes");
    const [proSeAnswer, setProSeAnswer] = useState<string | null>(null);
    const [proSeWithheld, setProSeWithheld] = useState(false);
    const [proSeLoading, setProSeLoading] = useState(false);
    const [proSeError, setProSeError] = useState<string | null>(null);

    const displayedStates = showAllStates ? STATES : STATES.slice(0, 20);

    function handleSearch(e: React.FormEvent) {
        e.preventDefault();
        if (!query.trim()) return;
        const url = `https://www.congress.gov/search?q=%7B%22source%22%3A%22legislation%22%2C%22search%22%3A%22${encodeURIComponent(query.trim())}%22%7D`;
        window.open(url, "_blank", "noopener,noreferrer");
    }

    async function handleProSeAsk(e: React.FormEvent) {
        e.preventDefault();
        if (!proSeQuestion.trim()) return;
        setProSeLoading(true);
        setProSeError(null);
        setProSeAnswer(null);
        setProSeWithheld(false);
        try {
            const result = await proSeAsk({
                question: proSeQuestion.trim(),
                jurisdiction: "colorado",
                sourceUrl: proSeUrl.trim() || undefined,
            });
            setProSeAnswer(result.answer);
            setProSeWithheld(result.withheld);
        } catch (err: unknown) {
            setProSeError(err instanceof Error ? err.message : "Ask failed");
        } finally {
            setProSeLoading(false);
        }
    }

    async function handleChatWithDocs(e: React.FormEvent) {
        e.preventDefault();
        if (!proSeQuestion.trim() || !proSeUrl.trim()) return;
        setProSeLoading(true);
        setProSeError(null);
        setProSeAnswer(null);
        setProSeWithheld(false);
        try {
            const result = await proSeChatWithDocs({
                prompt: proSeQuestion.trim(),
                urls: [proSeUrl.trim()],
            });
            setProSeAnswer(result.text);
            setProSeWithheld(result.withheld);
        } catch (err: unknown) {
            setProSeError(err instanceof Error ? err.message : "Chat failed");
        } finally {
            setProSeLoading(false);
        }
    }

    return (
        <div className="h-full overflow-y-auto bg-white">
            <div className="max-w-3xl mx-auto px-4 py-8">
                {/* Header */}
                <div className="mb-7">
                    <div className="flex items-center gap-3 mb-2">
                        <div className="h-9 w-9 rounded-lg bg-gray-900 flex items-center justify-center">
                            <Scroll className="h-5 w-5 text-white" />
                        </div>
                        <h1 className="text-2xl font-serif font-light text-gray-900">Legislation</h1>
                    </div>
                    <p className="text-sm text-gray-500">
                        Search by citation (18 USC 1001, 26 CFR 1.61-1, Cal. Penal Code §187) or keyword.
                        Sources: Congress.gov, GovInfo.gov, eCFR.gov (federal); official state legislature sites.
                    </p>
                </div>

                {/* Search bar */}
                <form onSubmit={handleSearch} className="flex gap-2 mb-8">
                    <div className="flex-1 flex items-center gap-2 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 focus-within:ring-2 focus-within:ring-gray-900 focus-within:border-transparent">
                        <Search className="h-4 w-4 text-gray-400 flex-shrink-0" />
                        <input
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                            type="text"
                            placeholder="18 USC § 1001 · 26 CFR 1.61-1 · Cal. Penal Code § 187 · RICO"
                            className="flex-1 bg-transparent text-sm text-gray-900 placeholder-gray-400 focus:outline-none"
                        />
                    </div>
                    <button
                        type="submit"
                        disabled={!query.trim()}
                        className="px-4 py-2 rounded-lg bg-gray-900 text-white text-sm font-medium hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                    >
                        Search
                    </button>
                </form>

                <div className="mb-8 rounded-lg border border-gray-200 bg-gray-50 p-4">
                    <div className="flex items-center gap-2 mb-2">
                        <MessageSquare className="h-4 w-4 text-gray-500" />
                        <h2 className="text-sm font-semibold text-gray-800">Pro Se Ask (verified)</h2>
                    </div>
                    <p className="text-xs text-gray-500 mb-3">
                        Ask-the-manual + chat-with-docs wired to Kingsfield verifier.
                    </p>
                    <form onSubmit={handleProSeAsk} className="flex flex-col gap-2">
                        <input
                            value={proSeUrl}
                            onChange={(e) => setProSeUrl(e.target.value)}
                            className="rounded border border-gray-200 px-3 py-2 text-sm"
                            placeholder="Allowlisted statute URL"
                        />
                        <textarea
                            value={proSeQuestion}
                            onChange={(e) => setProSeQuestion(e.target.value)}
                            rows={3}
                            className="rounded border border-gray-200 px-3 py-2 text-sm"
                            placeholder="What does Colorado law say about…?"
                        />
                        <div className="flex gap-2">
                            <button type="submit" disabled={proSeLoading || !proSeQuestion.trim()} className="px-3 py-2 rounded bg-gray-900 text-white text-sm disabled:opacity-40">
                                Ask corpus
                            </button>
                            <button type="button" onClick={handleChatWithDocs} disabled={proSeLoading || !proSeQuestion.trim()} className="px-3 py-2 rounded border border-gray-300 text-sm disabled:opacity-40">
                                Chat with URL
                            </button>
                        </div>
                    </form>
                    {proSeLoading && <p className="text-xs text-gray-500 mt-2">Running four-gate verification…</p>}
                    {proSeError && <p className="text-xs text-red-600 mt-2">{proSeError}</p>}
                    {proSeWithheld && (
                        <div className="mt-3 text-sm text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2">
                            Answer withheld — one or more citations failed verification (existence, quote accuracy, currency, or jurisdiction fit). We would rather return nothing than an unverified answer.
                        </div>
                    )}
                    {proSeAnswer && !proSeWithheld && (
                        <div className="mt-3 text-sm text-gray-800 whitespace-pre-wrap border-t border-gray-200 pt-3">
                            {proSeAnswer}
                        </div>
                    )}
                </div>

                {/* Federal sources */}
                <div className="mb-8">
                    <div className="flex items-center gap-2 mb-3">
                        <Globe className="h-4 w-4 text-gray-400" />
                        <h2 className="text-sm font-semibold text-gray-700">Federal</h2>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        {FEDERAL_SOURCES.map((src) => (
                            <SourceCard key={src.label} source={src} />
                        ))}
                    </div>
                </div>

                {/* State codes */}
                <div>
                    <div className="flex items-center gap-2 mb-3">
                        <Landmark className="h-4 w-4 text-gray-400" />
                        <h2 className="text-sm font-semibold text-gray-700">State Codes</h2>
                    </div>
                    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
                        {displayedStates.map((state) => (
                            <a
                                key={state.abbr}
                                href={STATE_LAW_URLS[state.abbr] ?? `https://law.justia.com/codes/${state.name.toLowerCase().replace(/\s/g, "-")}/`}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="group flex items-center justify-between rounded-lg border border-gray-200 bg-white px-3 py-2 hover:border-gray-400 hover:shadow-sm transition-all"
                            >
                                <div>
                                    <span className="text-xs font-semibold text-gray-700 group-hover:text-gray-900">{state.abbr}</span>
                                    <span className="block text-xs text-gray-400 group-hover:text-gray-600">{state.name}</span>
                                </div>
                                <ExternalLink className="h-3 w-3 text-gray-300 group-hover:text-gray-500 transition-colors" />
                            </a>
                        ))}
                    </div>
                    {!showAllStates && (
                        <button
                            onClick={() => setShowAllStates(true)}
                            className="mt-3 flex items-center gap-1 text-xs text-gray-400 hover:text-gray-700 transition-colors"
                        >
                            <ChevronDown className="h-3.5 w-3.5" />
                            Show all {STATES.length} states + territories
                        </button>
                    )}
                </div>
            </div>
        </div>
    );
}
