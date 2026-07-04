"use client";

import { useState, useEffect } from "react";
import { Search, BookOpen, ExternalLink, Shield, ChevronDown, ChevronUp, Loader2, AlertCircle, X, FileText } from "lucide-react";
import { supabase } from "@/lib/supabase";
import { CourtPicker } from "@/app/components/case-law/CourtPicker";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:3001";

async function getAuthHeader(): Promise<Record<string, string>> {
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) return {};
    return { Authorization: `Bearer ${session.access_token}` };
}

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

interface CaseOpinion {
    opinionId: number | null;
    type: string | null;
    author: string | null;
    url: string | null;
    text?: string | null;
    html?: string | null;
}

const OPINION_TYPE_LABELS: Record<string, string> = {
    "020lead": "Lead opinion",
    "010combined": "Opinion",
    "030concurrence": "Concurrence",
    "040dissent": "Dissent",
    "050addendum": "Addendum",
    "060remittitur": "Remittitur",
    "070rehearing": "Rehearing",
    "080on-the-merits": "On the merits",
};

function opinionTypeLabel(type: string | null): string {
    if (!type) return "Opinion";
    return OPINION_TYPE_LABELS[type] ?? "Opinion";
}

// In-app opinion reader — pulls the full opinion text from CourtListener via
// the backend (four-gate verified) and renders it here. CourtListener is cited
// as the source, not the destination: primary sources live in the product.
function OpinionReader({ result, onClose }: { result: CaseResult; onClose: () => void }) {
    const [loading, setLoading] = useState(true);
    const [opinions, setOpinions] = useState<CaseOpinion[]>([]);
    const [error, setError] = useState<string | null>(null);
    const courtListenerUrl = `https://www.courtlistener.com${result.absolute_url}`;

    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const headers = await getAuthHeader();
                const res = await fetch(`${API_BASE}/case-law/case-opinions`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json", ...headers },
                    body: JSON.stringify({ clusterId: result.id }),
                });
                if (!res.ok) throw new Error(`Failed to load opinion (${res.status})`);
                const data = (await res.json()) as { opinions: CaseOpinion[] };
                if (!cancelled) setOpinions(data.opinions ?? []);
            } catch (e: any) {
                if (!cancelled) setError(e.message ?? "Could not load opinion text");
            } finally {
                if (!cancelled) setLoading(false);
            }
        })();
        return () => { cancelled = true; };
    }, [result.id]);

    return (
        <div className="fixed inset-0 z-50 flex justify-end">
            <div className="absolute inset-0 bg-black/30" onClick={onClose} />
            <div className="relative w-full max-w-3xl h-full bg-white shadow-2xl flex flex-col animate-in slide-in-from-right">
                {/* Header */}
                <div className="flex items-start justify-between gap-4 px-6 py-4 border-b border-gray-200 flex-shrink-0">
                    <div className="min-w-0">
                        <h2 className="text-base font-semibold text-gray-900 leading-snug">{result.case_name}</h2>
                        <div className="flex items-center gap-2 mt-1 flex-wrap text-xs text-gray-500">
                            <span className="font-medium">{result.citation}</span>
                            {result.court && <><span className="text-gray-300">·</span><span>{result.court}</span></>}
                            {result.date_filed && <><span className="text-gray-300">·</span><span>{result.date_filed.slice(0, 4)}</span></>}
                        </div>
                    </div>
                    <button onClick={onClose} className="flex-shrink-0 text-gray-400 hover:text-gray-700 transition-colors" title="Close">
                        <X className="h-5 w-5" />
                    </button>
                </div>

                {/* Body */}
                <div className="flex-1 overflow-y-auto px-6 py-5">
                    {loading && (
                        <div className="flex items-center justify-center gap-2 text-sm text-gray-500 py-16">
                            <Loader2 className="h-4 w-4 animate-spin" /> Loading opinion text…
                        </div>
                    )}
                    {error && (
                        <div className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-4">
                            <AlertCircle className="h-4 w-4 text-amber-500 flex-shrink-0 mt-0.5" />
                            <div>
                                <p className="text-sm font-medium text-amber-700">Couldn&apos;t load the opinion text</p>
                                <p className="text-xs text-amber-600 mt-0.5">{error}</p>
                                <a href={courtListenerUrl} target="_blank" rel="noopener noreferrer"
                                    className="inline-flex items-center gap-1 mt-2 text-xs text-amber-700 font-medium hover:underline">
                                    Read on CourtListener <ExternalLink className="h-3 w-3" />
                                </a>
                            </div>
                        </div>
                    )}
                    {!loading && !error && opinions.length === 0 && (
                        <p className="text-sm text-gray-500 py-16 text-center">No opinion text available for this case.</p>
                    )}
                    {!loading && !error && opinions.map((op, i) => (
                        <div key={op.opinionId ?? i} className="mb-8">
                            <div className="flex items-center gap-2 mb-3 pb-2 border-b border-gray-100">
                                <FileText className="h-3.5 w-3.5 text-gray-400" />
                                <span className="text-xs font-semibold tracking-wide text-gray-500 uppercase">
                                    {opinionTypeLabel(op.type)}{op.author ? ` · ${op.author}` : ""}
                                </span>
                            </div>
                            {op.html ? (
                                <div className="prose prose-sm max-w-none text-gray-800 leading-relaxed [&_p]:mb-3"
                                    dangerouslySetInnerHTML={{ __html: op.html }} />
                            ) : (
                                <div className="text-sm text-gray-800 leading-relaxed whitespace-pre-wrap font-serif">
                                    {op.text}
                                </div>
                            )}
                        </div>
                    ))}
                </div>

                {/* Footer — source provenance */}
                <div className="flex items-center justify-between gap-3 px-6 py-3 border-t border-gray-200 flex-shrink-0 bg-gray-50">
                    <span className="text-xs text-gray-400">
                        Source: <a href={courtListenerUrl} target="_blank" rel="noopener noreferrer" className="underline hover:text-gray-600">CourtListener</a> · Free Law Project
                    </span>
                    <span className="inline-flex items-center gap-1 text-xs text-green-700 font-medium">
                        <Shield className="h-3 w-3" /> Primary source · verified
                    </span>
                </div>
            </div>
        </div>
    );
}

function GateChip({ label, variant = "verify" }: { label: string; variant?: "verify" | "source" }) {
    const styles = variant === "source"
        ? "bg-blue-50 text-blue-700"
        : "bg-green-100 text-green-700";
    const Icon = variant === "source" ? BookOpen : Shield;
    return (
        <span className={`inline-flex items-center gap-1 text-xs px-1.5 py-0.5 rounded font-medium ${styles}`}>
            <Icon className="h-3 w-3" />
            {label}
        </span>
    );
}

function CaseCard({ result, onRead }: { result: CaseResult; onRead: () => void }) {
    const [expanded, setExpanded] = useState(false);
    const courtListenerUrl = `https://www.courtlistener.com${result.absolute_url}`;

    return (
        <div className="rounded-lg border border-gray-200 bg-white p-4 hover:border-gray-300 transition-colors">
            <div className="flex items-start justify-between gap-3">
                <button onClick={onRead} className="flex-1 min-w-0 text-left group">
                    <div className="flex items-start gap-2 flex-wrap">
                        <h3 className="text-sm font-semibold text-gray-900 leading-snug group-hover:text-blue-700 transition-colors">{result.case_name}</h3>
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
                        <GateChip label="Existence verified" variant="verify" />
                        <GateChip label="CourtListener" variant="source" />
                    </div>
                </button>
                <a
                    href={courtListenerUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex-shrink-0 text-gray-300 hover:text-gray-600 transition-colors"
                    title="Open source on CourtListener"
                >
                    <ExternalLink className="h-4 w-4" />
                </a>
            </div>
            <div className="flex items-center gap-3 mt-3">
                <button
                    onClick={onRead}
                    className="inline-flex items-center gap-1.5 text-xs font-medium text-white bg-blue-600 hover:bg-blue-700 px-3 py-1.5 rounded transition-colors"
                >
                    <BookOpen className="h-3.5 w-3.5" /> Read opinion
                </button>
                {result.snippet && (
                    <button
                        onClick={() => setExpanded(!expanded)}
                        className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-700 transition-colors"
                    >
                        {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                        {expanded ? "Hide excerpt" : "Show excerpt"}
                    </button>
                )}
            </div>
            {result.snippet && expanded && (
                <div
                    className="mt-2 text-xs text-gray-600 leading-relaxed bg-gray-50 rounded p-2 border-l-2 border-gray-300 italic"
                    dangerouslySetInnerHTML={{ __html: result.snippet }}
                />
            )}
        </div>
    );
}

export default function CaseLawPage() {
    const [query, setQuery] = useState("");
    // CourtListener court IDs; empty = all jurisdictions. Multi-select — the
    // search API takes a space-separated list in its `court` param.
    const [courts, setCourts] = useState<string[]>([]);
    const [loading, setLoading] = useState(false);
    const [results, setResults] = useState<CaseResult[] | null>(null);
    const [totalCount, setTotalCount] = useState(0);
    const [error, setError] = useState<string | null>(null);
    const [reading, setReading] = useState<CaseResult | null>(null);

    async function search() {
        if (!query.trim()) return;
        setLoading(true);
        setError(null);
        setResults(null);
        try {
            const headers = await getAuthHeader();
            const qs = new URLSearchParams({ q: query.trim() });
            if (courts.length) qs.set("jurisdiction", courts.join(" "));
            const res = await fetch(`${API_BASE}/api/research/case-law?${qs.toString()}`, {
                headers,
            });
            if (res.status === 429) {
                const body = await res.json().catch(() => ({}));
                setError(`throttled:${body.retry_in ?? 30}`);
                return;
            }
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
        ? `https://www.courtlistener.com/?q=${encodeURIComponent(query.trim())}${courts.length ? `&court=${encodeURIComponent(courts.join(" "))}` : ""}&type=o&order_by=score+desc`
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
                    <CourtPicker selected={courts} onChange={setCourts} />
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

                {/* Rate-limited by CourtListener — honest, retryable */}
                {error?.startsWith("throttled:") && (
                    <div className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-4 mb-6">
                        <AlertCircle className="h-4 w-4 text-amber-500 flex-shrink-0 mt-0.5" />
                        <div>
                            <p className="text-sm font-medium text-amber-700">CourtListener is rate-limiting requests</p>
                            <p className="text-xs text-amber-600 mt-0.5">
                                Too many API calls in the last minute. Retry in ~{error.split(":")[1]}s.
                            </p>
                            <button onClick={() => void search()}
                                className="inline-flex items-center gap-1 mt-2 text-xs text-amber-700 font-medium hover:underline">
                                Retry search
                            </button>
                        </div>
                    </div>
                )}

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
                                    <CaseCard key={r.id} result={r} onRead={() => setReading(r)} />
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
            {reading && <OpinionReader result={reading} onClose={() => setReading(null)} />}
        </div>
    );
}
