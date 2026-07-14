"use client";

import { useState } from "react";
import { Loader2, Library, Send } from "lucide-react";
import {
    proSeAskManual,
    proSeCreateManualStore,
    proSeManualSuggestions,
    proSeUploadToManualStore,
} from "@/app/lib/mikeApi";
import { SourceLabeledAnswer } from "../shared/SourceLabeledAnswer";
import type { Document } from "../shared/types";

/**
 * Always-visible File Search binder (Google ask-the-manual pattern).
 * Empty state when no docs; full index + ask when files are attached.
 * Complements Case Map extract (structure) with RAG Q&A (retrieve).
 */
export function DocBinderPanel({ docs }: { docs: Document[] }) {
    const [ragStoreName, setRagStoreName] = useState<string | null>(null);
    const [indexing, setIndexing] = useState(false);
    const [asking, setAsking] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [question, setQuestion] = useState("");
    const [suggestions, setSuggestions] = useState<string[]>([]);
    const [answer, setAnswer] = useState<string | null>(null);
    const [withheld, setWithheld] = useState(false);
    const [groundingCount, setGroundingCount] = useState(0);
    const [indexedNames, setIndexedNames] = useState<string[]>([]);

    const hasDocs = docs.length > 0;
    const ready = !!ragStoreName;

    async function indexDocs() {
        if (docs.length === 0) return;
        setIndexing(true);
        setError(null);
        setAnswer(null);
        try {
            const { ragStoreName: store } = await proSeCreateManualStore(
                `assistant-binder-${Date.now()}`,
            );
            const names: string[] = [];
            for (const d of docs) {
                const up = await proSeUploadToManualStore({
                    ragStoreName: store,
                    documentId: d.id,
                });
                names.push(up.filename);
            }
            setRagStoreName(store);
            setIndexedNames(names);
            const sug = await proSeManualSuggestions(store).catch(() => ({
                suggestions: [] as string[],
            }));
            setSuggestions(sug.suggestions ?? []);
        } catch (e: unknown) {
            setError(e instanceof Error ? e.message : "Indexing failed");
        } finally {
            setIndexing(false);
        }
    }

    async function ask(q?: string) {
        const text = (q ?? question).trim();
        if (!text || !ragStoreName) return;
        setAsking(true);
        setError(null);
        setAnswer(null);
        setWithheld(false);
        try {
            const res = await proSeAskManual({
                question: text,
                ragStoreName,
            });
            setAnswer(res.text);
            setWithheld(res.withheld);
            setGroundingCount(
                Array.isArray(res.groundingChunks)
                    ? res.groundingChunks.length
                    : 0,
            );
            if (q) setQuestion(q);
        } catch (e: unknown) {
            setError(e instanceof Error ? e.message : "Ask failed");
        } finally {
            setAsking(false);
        }
    }

    // No empty stub — attach via + Documents first (natural chat UX).
    if (!hasDocs) return null;

    return (
        <div className="w-full rounded-xl border border-blue-500/40 bg-blue-500/5 dark:bg-blue-500/10 p-4 space-y-3">
            <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                    <p className="text-[10px] font-light uppercase tracking-[0.14em] text-blue-600 dark:text-blue-300">
                        Ask these docs · File Search
                    </p>
                    <p className="text-sm font-light text-gray-800 dark:text-paper mt-0.5">
                        {ready
                            ? "Indexed binder ready — ask with grounding (separate from Case Map extract)."
                            : `${docs.length} file${docs.length === 1 ? "" : "s"} attached. Index to enable grounded Q&A.`}
                    </p>
                </div>
                <button
                    type="button"
                    onClick={() => void indexDocs()}
                    disabled={indexing}
                    className="shrink-0 inline-flex items-center gap-1.5 rounded-lg border border-gray-900 bg-gray-900 px-2.5 py-1.5 text-xs font-light text-white hover:bg-gray-800 disabled:opacity-40"
                >
                    {indexing ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                        <Library className="h-3.5 w-3.5" />
                    )}
                    {ready ? "Re-index" : "Index for Q&A"}
                </button>
            </div>

            {indexedNames.length > 0 && (
                <p className="text-[11px] font-light text-gray-500">
                    Indexed: {indexedNames.join(", ")}
                </p>
            )}

            {suggestions.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                    {suggestions.map((s) => (
                        <button
                            key={s}
                            type="button"
                            onClick={() => void ask(s)}
                            className="text-[11px] font-light px-2 py-1 rounded-full border border-gray-200 text-gray-700 hover:bg-gray-50 dark:border-white/10 dark:text-paper dark:hover:bg-white/5"
                        >
                            {s}
                        </button>
                    ))}
                </div>
            )}

            <div className="flex gap-2">
                <input
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                    onKeyDown={(e) => {
                        if (e.key === "Enter") {
                            e.preventDefault();
                            void ask();
                        }
                    }}
                    disabled={!ready || asking}
                    placeholder={
                        ready
                            ? "Ask anything about these documents…"
                            : "Click “Index for Q&A” first"
                    }
                    className="flex-1 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-light text-gray-900 placeholder:text-gray-400 dark:border-white/10 dark:bg-white/5 dark:text-paper disabled:opacity-50"
                />
                <button
                    type="button"
                    onClick={() => void ask()}
                    disabled={!ready || asking || !question.trim()}
                    className="rounded-lg bg-gray-900 text-white px-3 py-2 hover:bg-gray-800 disabled:opacity-40"
                    title="Ask binder"
                >
                    {asking ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                        <Send className="h-4 w-4" />
                    )}
                </button>
            </div>

            {error && (
                <p className="text-xs font-light text-red-600">{error}</p>
            )}

            <SourceLabeledAnswer
                engine="file_search"
                text={answer}
                withheld={withheld}
                groundingCount={groundingCount}
            />
        </div>
    );
}
