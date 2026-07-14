"use client";

import { useState, useEffect } from "react";
import {
    Search,
    Scroll,
    ExternalLink,
    Landmark,
    MessageSquare,
    Plus,
    X,
    Loader2,
    Link2,
} from "lucide-react";
import {
    proSeAsk,
    proSeChatWithDocs,
    proSeUrlSuggestions,
} from "@/app/lib/mikeApi";
import { JurisdictionSelector } from "@/app/components/shared/JurisdictionSelector";
import { useJurisdiction } from "@/contexts/JurisdictionContext";
import { SourceLabeledAnswer } from "@/app/components/shared/SourceLabeledAnswer";

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
    // Statutes auto-scope to the single app-wide jurisdiction (shared with Case Law).
    const { jurisdiction } = useJurisdiction();
    const [query, setQuery] = useState("");
    const [proSeQuestion, setProSeQuestion] = useState("");
    /** URL pack for urlContext engine (chat-with-docs) — up to 20 allowlisted. */
    const [urlPack, setUrlPack] = useState<string[]>(() =>
        jurisdiction.statuteUrl ? [jurisdiction.statuteUrl] : [],
    );
    const [newUrl, setNewUrl] = useState("");
    const [suggestions, setSuggestions] = useState<string[]>([]);
    const [engine, setEngine] = useState<string | null>(null);

    // Seed pack with jurisdiction default when it changes (keep user-added URLs).
    useEffect(() => {
        if (!jurisdiction.statuteUrl) return;
        setUrlPack((prev) => {
            if (prev.includes(jurisdiction.statuteUrl)) return prev;
            return [jurisdiction.statuteUrl, ...prev].slice(0, 20);
        });
    }, [jurisdiction.statuteUrl]);

    const [proSeAnswer, setProSeAnswer] = useState<string | null>(null);
    const [proSeWithheld, setProSeWithheld] = useState(false);
    const [proSeLoading, setProSeLoading] = useState(false);
    const [proSeError, setProSeError] = useState<string | null>(null);

    function handleSearch(e: React.FormEvent) {
        e.preventDefault();
        if (!query.trim()) return;
        const url = `https://www.congress.gov/search?q=%7B%22source%22%3A%22legislation%22%2C%22search%22%3A%22${encodeURIComponent(query.trim())}%22%7D`;
        window.open(url, "_blank", "noopener,noreferrer");
    }

    function addUrl() {
        const u = newUrl.trim();
        if (!u) return;
        setUrlPack((prev) =>
            prev.includes(u) ? prev : [...prev, u].slice(0, 20),
        );
        setNewUrl("");
    }

    function addFederalPack() {
        const urls = FEDERAL_SOURCES.map((s) => s.url);
        setUrlPack((prev) => {
            const next = [...prev];
            for (const u of urls) {
                if (!next.includes(u) && next.length < 20) next.push(u);
            }
            return next;
        });
    }

    async function handleProSeAsk(e: React.FormEvent) {
        e.preventDefault();
        if (!proSeQuestion.trim()) return;
        setProSeLoading(true);
        setProSeError(null);
        setProSeAnswer(null);
        setProSeWithheld(false);
        setEngine(null);
        try {
            const result = await proSeAsk({
                question: proSeQuestion.trim(),
                jurisdiction: jurisdiction.label,
                sourceUrl: urlPack[0] || undefined,
            });
            setProSeAnswer(result.answer);
            setProSeWithheld(result.withheld);
            setEngine(result.engine ?? "corpus");
        } catch (err: unknown) {
            setProSeError(err instanceof Error ? err.message : "Ask failed");
        } finally {
            setProSeLoading(false);
        }
    }

    async function handleChatWithDocs(prompt?: string) {
        const q = (prompt ?? proSeQuestion).trim();
        if (!q || urlPack.length === 0) return;
        setProSeLoading(true);
        setProSeError(null);
        setProSeAnswer(null);
        setProSeWithheld(false);
        setEngine(null);
        if (prompt) setProSeQuestion(prompt);
        try {
            const result = await proSeChatWithDocs({
                prompt: q,
                urls: urlPack,
            });
            setProSeAnswer(result.text);
            setProSeWithheld(result.withheld);
            setEngine(result.engine ?? "url_context");
        } catch (err: unknown) {
            setProSeError(err instanceof Error ? err.message : "Chat failed");
        } finally {
            setProSeLoading(false);
        }
    }

    async function handleSuggest() {
        if (urlPack.length === 0) return;
        setProSeLoading(true);
        setProSeError(null);
        try {
            const res = await proSeUrlSuggestions(urlPack);
            setSuggestions(res.suggestions ?? []);
        } catch (err: unknown) {
            setProSeError(
                err instanceof Error ? err.message : "Suggestions failed",
            );
        } finally {
            setProSeLoading(false);
        }
    }

    return (
        <div className="h-full overflow-y-auto bg-white">
            <div className="w-full max-w-none mx-auto px-6 py-8">
                {/* Header */}
                <div className="mb-7">
                    <div className="label-caps text-gray-400 mb-2">
                        Kingsfield · Primary sources
                    </div>
                    <div className="flex items-center gap-3 mb-3">
                        <div className="h-9 w-9 rounded-lg bg-gray-900 flex items-center justify-center">
                            <Scroll className="h-5 w-5 text-white" />
                        </div>
                        <h1 className="text-2xl font-serif font-light text-gray-900 dark:text-paper">Statutes</h1>
                    </div>
                    <p className="text-sm font-light text-gray-600 leading-relaxed max-w-none">
                        <span className="font-normal text-gray-900">What statutes are here:</span>{" "}
                        codes and primary legislative sources for the jurisdiction you select
                        (shared with Case Law) — USC, CFR, and official state sources where
                        linked. Primary sources only; no paid digests. Search by citation or
                        keyword, then open the official text. Use this when you need the
                        black-letter rule; use Case Law when you need how courts applied it.
                    </p>
                </div>

                {/* Single jurisdiction — shared with Case Law */}
                <div className="mb-6 flex flex-wrap items-center gap-3">
                    <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Jurisdiction</span>
                    <JurisdictionSelector compact />
                    <span className="text-xs text-gray-400">Statutes below reflect this selection</span>
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

                {/* Dual retrieval is the primary feature on this page — keep above the fold */}
                <div className="mb-8 rounded-lg border-2 border-blue-500/40 bg-blue-500/5 p-4 space-y-4">
                    <div>
                        <div className="flex items-center gap-2 mb-1">
                            <MessageSquare className="h-4 w-4 text-blue-600" />
                            <h2 className="text-base font-light text-gray-900">
                                New · Dual retrieval · URL packs
                            </h2>
                        </div>
                        <p className="text-xs font-light text-gray-500 leading-relaxed max-w-none">
                            <span className="font-normal text-gray-800">URL Context</span>{" "}
                            (chat-with-docs): ask across an allowlisted official source pack.
                            {" "}
                            <span className="font-normal text-gray-800">Corpus ask</span>{" "}
                            uses local statute files when present. Case citations still pass
                            four-gate. For uploaded PDFs, use Assistant → File Search binder.
                        </p>
                    </div>

                    {/* Source pack */}
                    <div>
                        <div className="flex items-center justify-between gap-2 mb-2">
                            <p className="text-[10px] font-light uppercase tracking-wider text-gray-400 flex items-center gap-1">
                                <Link2 className="h-3 w-3" /> Source pack ({urlPack.length}/20)
                            </p>
                            <button
                                type="button"
                                onClick={addFederalPack}
                                className="text-[11px] font-light text-blue-600 hover:underline"
                            >
                                Add federal pack
                            </button>
                        </div>
                        <div className="flex flex-wrap gap-1.5 mb-2">
                            {urlPack.map((u) => (
                                <span
                                    key={u}
                                    className="inline-flex items-center gap-1 max-w-full rounded-full border border-gray-200 bg-white px-2 py-0.5 text-[11px] font-light text-gray-700"
                                >
                                    <span className="truncate max-w-[220px]">{u}</span>
                                    <button
                                        type="button"
                                        onClick={() =>
                                            setUrlPack((p) => p.filter((x) => x !== u))
                                        }
                                        className="text-gray-400 hover:text-gray-700"
                                    >
                                        <X className="h-3 w-3" />
                                    </button>
                                </span>
                            ))}
                        </div>
                        <div className="flex gap-2">
                            <input
                                value={newUrl}
                                onChange={(e) => setNewUrl(e.target.value)}
                                onKeyDown={(e) => {
                                    if (e.key === "Enter") {
                                        e.preventDefault();
                                        addUrl();
                                    }
                                }}
                                className="flex-1 rounded border border-gray-200 px-3 py-2 text-sm font-light"
                                placeholder="Add https:// official statute URL…"
                            />
                            <button
                                type="button"
                                onClick={addUrl}
                                className="rounded border border-gray-300 px-3 py-2 text-sm font-light inline-flex items-center gap-1"
                            >
                                <Plus className="h-3.5 w-3.5" /> Add
                            </button>
                        </div>
                    </div>

                    <form onSubmit={handleProSeAsk} className="flex flex-col gap-2">
                        <textarea
                            value={proSeQuestion}
                            onChange={(e) => setProSeQuestion(e.target.value)}
                            rows={3}
                            className="rounded border border-gray-200 px-3 py-2 text-sm font-light"
                            placeholder="What does the code say about…?"
                        />
                        <div className="flex flex-wrap gap-2">
                            <button
                                type="button"
                                onClick={() => void handleChatWithDocs()}
                                disabled={
                                    proSeLoading ||
                                    !proSeQuestion.trim() ||
                                    urlPack.length === 0
                                }
                                className="px-3 py-2 rounded bg-gray-900 text-white text-sm font-light disabled:opacity-40"
                            >
                                Chat with URL pack
                            </button>
                            <button
                                type="submit"
                                disabled={proSeLoading || !proSeQuestion.trim()}
                                className="px-3 py-2 rounded border border-gray-300 text-sm font-light disabled:opacity-40"
                            >
                                Ask local corpus
                            </button>
                            <button
                                type="button"
                                onClick={() => void handleSuggest()}
                                disabled={proSeLoading || urlPack.length === 0}
                                className="px-3 py-2 rounded border border-gray-300 text-sm font-light disabled:opacity-40"
                            >
                                Suggest questions
                            </button>
                        </div>
                    </form>

                    {suggestions.length > 0 && (
                        <div className="flex flex-wrap gap-1.5">
                            {suggestions.map((s) => (
                                <button
                                    key={s}
                                    type="button"
                                    onClick={() => void handleChatWithDocs(s)}
                                    className="text-[11px] font-light px-2 py-1 rounded-full border border-gray-200 bg-white text-gray-700 hover:bg-gray-50"
                                >
                                    {s}
                                </button>
                            ))}
                        </div>
                    )}

                    {proSeLoading && (
                        <p className="text-xs font-light text-gray-500 inline-flex items-center gap-1.5">
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            Retrieving + four-gate check…
                        </p>
                    )}
                    {proSeError && (
                        <p className="text-xs font-light text-red-600">{proSeError}</p>
                    )}
                    <SourceLabeledAnswer
                        engine={engine}
                        text={proSeAnswer}
                        withheld={proSeWithheld}
                        urls={engine === "url_context" ? urlPack : undefined}
                    />
                </div>

                {/* Statutes & codes for the selected jurisdiction */}
                <div>
                    <div className="flex items-center gap-2 mb-3">
                        <Landmark className="h-4 w-4 text-gray-400" />
                        <h2 className="text-sm font-semibold text-gray-700">{jurisdiction.label} — Statutes &amp; Codes</h2>
                    </div>
                    {jurisdiction.type === "federal" ? (
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                            {FEDERAL_SOURCES.map((src) => (
                                <SourceCard key={src.label} source={src} />
                            ))}
                        </div>
                    ) : (
                        <a
                            href={jurisdiction.statuteUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="group flex items-center justify-between rounded-lg border border-gray-200 bg-white px-4 py-3 hover:border-gray-400 hover:shadow-sm transition-all"
                        >
                            <div>
                                <span className="text-sm font-semibold text-gray-800 group-hover:text-gray-900">{jurisdiction.statuteLabel}</span>
                                <span className="block text-xs text-gray-400">Official code / statutes for {jurisdiction.label}</span>
                            </div>
                            <ExternalLink className="h-4 w-4 text-gray-300 group-hover:text-gray-500 transition-colors" />
                        </a>
                    )}
                    <p className="mt-3 text-xs text-gray-400">
                        Use “Pro Se Ask” above to query {jurisdiction.label} statutes in-app with citation verification.
                    </p>
                </div>
            </div>
        </div>
    );
}
