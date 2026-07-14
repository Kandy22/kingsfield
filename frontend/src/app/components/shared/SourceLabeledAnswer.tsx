"use client";

/**
 * Labels dual-retrieval answers: from your documents (File Search) vs
 * from official URLs (urlContext) vs withheld after four-gate.
 */
export function SourceLabeledAnswer({
    engine,
    text,
    withheld,
    urls,
    groundingCount,
}: {
    engine?: string | null;
    text: string | null;
    withheld?: boolean;
    urls?: string[];
    groundingCount?: number;
}) {
    if (withheld) {
        return (
            <div className="mt-3 text-sm font-light text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2 dark:bg-red-500/10 dark:border-red-500/30 dark:text-red-200">
                Answer withheld — one or more citations failed verification
                (existence, quote accuracy, currency, or jurisdiction fit). We
                would rather return nothing than an unverified answer.
            </div>
        );
    }
    if (!text) return null;

    const engineLabel =
        engine === "file_search"
            ? "From your documents (File Search)"
            : engine === "url_context"
              ? "From official URLs (URL Context)"
              : engine === "corpus"
                ? "From local statute corpus"
                : "Answer";

    return (
        <div className="mt-3 space-y-2 border-t border-gray-200 dark:border-white/10 pt-3">
            <div className="flex flex-wrap items-center gap-2">
                <span className="text-[10px] font-light uppercase tracking-wider text-gray-400">
                    {engineLabel}
                </span>
                {typeof groundingCount === "number" && groundingCount > 0 && (
                    <span className="text-[10px] font-light text-blue-600 dark:text-blue-300">
                        {groundingCount} grounding chunk
                        {groundingCount === 1 ? "" : "s"}
                    </span>
                )}
            </div>
            <div className="text-sm font-light text-gray-800 dark:text-paper whitespace-pre-wrap leading-relaxed">
                {text}
            </div>
            {urls && urls.length > 0 && (
                <div className="pt-1">
                    <p className="text-[10px] font-light uppercase tracking-wider text-gray-400 mb-1">
                        Source pack
                    </p>
                    <ul className="space-y-0.5">
                        {urls.map((u) => (
                            <li key={u}>
                                <a
                                    href={u}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="text-[11px] font-light text-blue-600 hover:underline break-all"
                                >
                                    {u}
                                </a>
                            </li>
                        ))}
                    </ul>
                </div>
            )}
            <p className="text-[10px] font-light text-gray-400">
                URL/File Search answers are labeled sources — not four-gate case
                law. Case citations in the answer still run verification when
                present.
            </p>
        </div>
    );
}
