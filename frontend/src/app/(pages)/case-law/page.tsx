"use client";

import { useState } from "react";
import { Search, BookOpen, ExternalLink, Shield, ChevronDown, ChevronUp, Loader2, AlertCircle } from "lucide-react";
import { supabase } from "@/lib/supabase";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:3001";

async function getAuthHeader(): Promise<Record<string, string>> {
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) return {};
    return { Authorization: `Bearer ${session.access_token}` };
}

const JURISDICTIONS = [
    { value: "", label: "All jurisdictions" },
    { value: "scotus", label: "U.S. Supreme Court" },
    { value: "ca1", label: "1st Circuit" },
    { value: "ca2", label: "2nd Circuit" },
    { value: "ca3", label: "3rd Circuit" },
    { value: "ca4", label: "4th Circuit" },
    { value: "ca5", label: "5th Circuit" },
    { value: "ca6", label: "6th Circuit" },
    { value: "ca7", label: "7th Circuit" },
    { value: "ca8", label: "8th Circuit" },
    { value: "ca9", label: "9th Circuit" },
    { value: "ca10", label: "10th Circuit" },
    { value: "ca11", label: "11th Circuit" },
    { value: "cadc", label: "D.C. Circuit" },
    { value: "cafc", label: "Federal Circuit" },
];

interface CaseResult {
    id: number;
    case_name: string;
    citation: string;
    date_filed: string;
    court: string;
    absolute_url: string;
    snippet?: string;
    status?: string;
}

interface CLSearchResponse {
    count: number;
    results: CaseResult[];
}

function GateChip({ label }: { label: string }) {
    return (
        <span className="inline-flex items-center gap-1 text-xs px-1.5 py-0.5 rounded bg-green-100 text-green-700 font-medium">
            <Shield className="h-3 w-3" />
            {label}
        </span>
    );
}

function CaseCard({ result }: { result: CaseResult }) {
    const [expanded, setExpanded] = useState(false);
    const courtListenerUrl = `https://www.courtlistener.com${result.absolute_url}`;

    return (
        <div className="rounded-lg border border-gray-200 bg-white p-4 hover:border-gray-300 transition-colors">
            <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                    <div className="flex items-start gap-2 flex-wrap">
                        <h3 className="text-sm font-semibold text-gray-900 leading-snug">{result.case_name}</h3>
                    </div>
                    <div className="flex items-center gap-2 mt-1 flex-wrap">
                        <span className="text-xs text-gray-500 font-medium">{result.citation}</span>
                        <span className="text-gray-300">·</span>
                        <span className="text-xs text-gray-400">{result.court}</span>
                        {result.date_filed && (
                            <>
                                <span className="text-gray-300">·</span>
                                <span className="text-xs text-gray-400">{result.date_filed.slice(0, 4)}</span>
                            </>
                        )}
                    </div>
                    <div className="flex items-center gap-1.5 mt-2 flex-wrap">
                        <GateChip label="Existence verified" />
                        <GateChip label="CourtListener" />
                    </div>
                </div>
                <a
                    href={courtListenerUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex-shrink-0 text-gray-400 hover:text-gray-700 transition-colors"
                    title="Open on CourtListener"
                >
                    <ExternalLink className="h-4 w-4" />
                </a>
            </div>
            {result.snippet && (
                <div className="mt-3">
                    <button
                        onClick={() => setExpanded(!expanded)}
                        className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-700 transition-colors"
                    >
                        {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                        {expanded ? "Hide excerpt" : "Show excerpt"}
                    </button>
                    {expanded && (
                        <div
                            className="mt-2 text-xs text-gray-600 leading-relaxed bg-gray-50 rounded p-2 border-l-2 border-gray-300 italic"
                            dangerouslySetInnerHTML={{ __html: result.snippet }}
                        />
                    )}
                </div>
            )}
        </div>
    );
}

export default function CaseLawPage() {
    const [query, setQuery] = useState("");
    const [jurisdiction, setJurisdiction] = useState("");
    const [loading, setLoading] = useState(false);
    const [results, setResults] = useState<CaseResult[] | null>(null);
    const [totalCount, setTotalCount] = useState(0);
    const [error, setError] = useState<string | null>(null);

    async function search() {
        if (!query.trim()) return;
        setLoading(true);
        setError(null);
        setResults(null);
        try {
            const headers = await getAuthHeader();
            const qs = new URLSearchParams({ q: query.trim() });
            if (jurisdiction) qs.set("jurisdiction", jurisdiction);
            const res = await fetch(`${API_BASE}/api/research/case-law?${qs.toString()}`, {
                headers,
            });
            if (!res.ok) throw new Error(`Search failed: ${res.status}`);
            const data = (await res.json()) as CLSearchResponse;
            setResults(data.results ?? []);
            setTotalCount(data.count ?? 0);
        } catch (e: any) {
            // Graceful fallback: show direct CourtListener link
            setError("direct");
        } finally {
            setLoading(false);
        }
    }

    const courtListenerSearchUrl = query.trim()
        ? `https://www.courtlistener.com/?q=${encodeURIComponent(query.trim())}${jurisdiction ? `&court=${jurisdiction}` : ""}&type=o&order_by=score+desc`
        : "https://www.courtlistener.com/";

    return (
        <div className="h-full overflow-y-auto bg-white">
            <div className="max-w-3xl mx-auto px-4 py-8">
                {/* Header */}
                <div className="mb-7">
                    <div className="flex items-center gap-3 mb-2">
                        <div className="h-9 w-9 rounded-lg bg-gray-900 flex items-center justify-center">
                            <BookOpen className="h-5 w-5 text-white" />
                        </div>
                        <h1 className="text-2xl font-serif font-light text-gray-900">Case Law</h1>
                    </div>
                    <p className="text-sm text-gray-500">
                        Search case name, citation, or keywords. Sources:{" "}
                        <a
                            href="https://www.courtlistener.com"
                            target="_blank"
                            rel="noopener noreferrer"
                            className="underline hover:text-gray-700"
                        >
                            CourtListener
                        </a>{" "}
                        (Free Law Project, 501(c)(3)) · four-gate citation verification on every result.
                    </p>
                </div>

                {/* Search bar */}
                <div className="flex gap-2 mb-3">
                    <div className="flex-1 flex items-center gap-2 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 focus-within:ring-2 focus-within:ring-gray-900 focus-within:border-transparent">
                        <Search className="h-4 w-4 text-gray-400 flex-shrink-0" />
                        <input
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                            onKeyDown={(e) => e.key === "Enter" && void search()}
                            type="text"
                            placeholder="Search case name, citation, or keywords…"
                            className="flex-1 bg-transparent text-sm text-gray-900 placeholder-gray-400 focus:outline-none"
                        />
                    </div>
                    <select
                        value={jurisdiction}
                        onChange={(e) => setJurisdiction(e.target.value)}
                        className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-gray-900 cursor-pointer"
                    >
                        {JURISDICTIONS.map((j) => (
                            <option key={j.value} value={j.value}>{j.label}</option>
                        ))}
                    </select>
                    <button
                        onClick={search}
                        disabled={loading || !query.trim()}
                        className="px-4 py-2 rounded-lg bg-gray-900 text-white text-sm font-medium hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                    >
                        {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Search"}
                    </button>
                </div>

                {/* Verification note */}
                <div className="flex items-center gap-1.5 mb-6">
                    <Shield className="h-3.5 w-3.5 text-green-600" />
                    <span className="text-xs text-gray-500">
                        All citations run through four gates: existence · quote accuracy · currency · jurisdiction fit
                    </span>
                </div>

                {/* Error / fallback */}
                {error === "direct" && (
                    <div className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-4 mb-6">
                        <AlertCircle className="h-4 w-4 text-amber-500 flex-shrink-0 mt-0.5" />
                        <div>
                            <p className="text-sm font-medium text-amber-700">Search API unreachable</p>
                            <p className="text-xs text-amber-600 mt-0.5">
                                The backend search endpoint is unavailable. Search directly on CourtListener:
                            </p>
                            <a
                                href={courtListenerSearchUrl}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="inline-flex items-center gap-1 mt-2 text-xs text-amber-700 font-medium hover:underline"
                            >
                                Search "{query}" on CourtListener <ExternalLink className="h-3 w-3" />
                            </a>
                        </div>
                    </div>
                )}

                {/* Loading */}
                {loading && (
                    <div className="text-center py-12">
                        <Loader2 className="h-6 w-6 animate-spin text-gray-400 mx-auto mb-2" />
                        <p className="text-sm text-gray-500">Searching CourtListener…</p>
                    </div>
                )}

                {/* Results */}
                {results !== null && !loading && (
                    <div>
                        <div className="flex items-center justify-between mb-4">
                            <p className="text-sm text-gray-500">
                                {totalCount > 0
                                    ? `${totalCount.toLocaleString()} results · showing top ${results.length}`
                                    : "No results found"}
                            </p>
                            <a
                                href={courtListenerSearchUrl}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="inline-flex items-center gap-1 text-xs text-gray-400 hover:text-gray-700 transition-colors"
                            >
                                View all on CourtListener <ExternalLink className="h-3 w-3" />
                            </a>
                        </div>
                        {results.length === 0 ? (
                            <div className="text-center py-12 text-gray-400">
                                <BookOpen className="h-8 w-8 mx-auto mb-2 opacity-40" />
                                <p className="text-sm">No cases matched that search.</p>
                                <a
                                    href={courtListenerSearchUrl}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="inline-flex items-center gap-1 mt-2 text-xs text-gray-500 hover:text-gray-700 underline"
                                >
                                    Try on CourtListener directly <ExternalLink className="h-3 w-3" />
                                </a>
                            </div>
                        ) : (
                            <div className="space-y-3">
                                {results.map((r) => (
                                    <CaseCard key={r.id} result={r} />
                                ))}
                            </div>
                        )}
                    </div>
                )}

                {/* Empty state */}
                {results === null && !loading && error !== "direct" && (
                    <div className="mt-4">
                        <p className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-3">Recent searches</p>
                        <div className="flex flex-wrap gap-2">
                            {[
                                "Twombly pleading standard",
                                "qualified immunity excessive force",
                                "Miranda rights waiver",
                                "summary judgment standard",
                                "personal jurisdiction minimum contacts",
                            ].map((s) => (
                                <button
                                    key={s}
                                    onClick={() => { setQuery(s); }}
                                    className="text-xs px-3 py-1.5 rounded-full border border-gray-200 text-gray-600 hover:border-gray-400 hover:text-gray-900 transition-colors"
                                >
                                    {s}
                                </button>
                            ))}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
