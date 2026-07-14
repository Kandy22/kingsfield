"use client";

import { useEffect, useState } from "react";
import {
    FileText,
    Loader2,
    Map,
    PencilLine,
    Scale,
    Gavel,
    ShieldCheck,
    Users,
    AlertCircle,
} from "lucide-react";
import { useRouter } from "next/navigation";
import {
    waitForExtraction,
    type CaseExtraction,
} from "@/app/lib/caseIntelligenceApi";
import type { Document } from "../shared/types";

interface Props {
    doc: Document;
    onOpenEditor?: (doc: Document, extraction: CaseExtraction | null) => void;
}

type Status = "loading" | "ready" | "error";

export function CaseExtractionCard({ doc, onOpenEditor }: Props) {
    const router = useRouter();
    const [status, setStatus] = useState<Status>("loading");
    const [extraction, setExtraction] = useState<CaseExtraction | null>(null);
    const [errorMsg, setErrorMsg] = useState<string | null>(null);

    useEffect(() => {
        const ac = new AbortController();
        setStatus("loading");
        setExtraction(null);
        setErrorMsg(null);
        void (async () => {
            try {
                const result = await waitForExtraction(doc.id, {
                    projectId: doc.project_id,
                    signal: ac.signal,
                });
                if (ac.signal.aborted) return;
                if (result.ok) {
                    setExtraction(result.extraction);
                    setStatus("ready");
                } else {
                    setErrorMsg(result.error);
                    setStatus("error");
                }
            } catch {
                if (!ac.signal.aborted) {
                    setErrorMsg("Extraction failed unexpectedly.");
                    setStatus("error");
                }
            }
        })();
        return () => ac.abort();
    }, [doc.id, doc.project_id]);

    const parties = (extraction?.entities ?? [])
        .filter((e) => e.role === "party" || e.role === "judge")
        .slice(0, 6);
    const topAuths = (extraction?.authorities ?? []).slice(0, 4);
    const topClaims = (extraction?.allegations ?? []).slice(0, 3);

    return (
        <div className="w-full rounded-xl border border-gray-200/90 bg-white/80 shadow-sm backdrop-blur-sm dark:border-white/10 dark:bg-white/[0.04] dark:shadow-none">
            <div className="flex items-start justify-between gap-3 px-4 pt-3 pb-2">
                <div className="min-w-0 flex items-start gap-2">
                    <FileText className="h-4 w-4 mt-0.5 shrink-0 text-gray-400" />
                    <div className="min-w-0">
                        <p className="text-xs font-light uppercase tracking-wider text-gray-400">
                            Case extract
                        </p>
                        <p className="text-sm font-light text-gray-900 truncate dark:text-paper">
                            {extraction?.caption || doc.filename}
                        </p>
                    </div>
                </div>
                {status === "loading" && (
                    <span className="inline-flex items-center gap-1.5 text-xs text-gray-500 shrink-0">
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        Extracting…
                    </span>
                )}
                {status === "error" && (
                    <span className="inline-flex items-center gap-1.5 text-xs text-amber-600 shrink-0">
                        <AlertCircle className="h-3.5 w-3.5" />
                        No body text
                    </span>
                )}
            </div>

            {status === "error" && (
                <div className="px-4 pb-3">
                    <div className="rounded-lg border border-amber-200/80 bg-amber-50/90 dark:border-amber-500/20 dark:bg-amber-500/10 p-3">
                        <p className="text-xs font-light text-amber-900 dark:text-amber-100/90 leading-relaxed">
                            {errorMsg ??
                                "Could not extract case facts from this file."}
                        </p>
                        <p className="text-[11px] font-light text-amber-800/80 dark:text-amber-100/60 mt-2 leading-relaxed">
                            Your Heppner PDF is a RICOH scan (image pages). PACER
                            stamps like “1:25-cr-00503-JSR” are the only text
                            layer — not the opinion body. Get a text PDF from
                            CourtListener/WL, run OCR, or paste the opinion text
                            into chat.
                        </p>
                    </div>
                    <div className="flex flex-wrap gap-2 pt-3">
                        <button
                            type="button"
                            onClick={() => onOpenEditor?.(doc, null)}
                            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-light text-gray-700 hover:bg-gray-50 dark:border-white/10 dark:bg-white/5 dark:text-paper"
                        >
                            <PencilLine className="h-3.5 w-3.5" />
                            Open PDF in editor
                        </button>
                    </div>
                </div>
            )}

            {status === "ready" && extraction && (
                <div className="px-4 pb-3 space-y-3">
                    {extraction.defense_summary && (
                        <p className="text-xs text-gray-600 dark:text-gray-400 leading-relaxed font-light">
                            {extraction.defense_summary}
                        </p>
                    )}

                    {parties.length > 0 && (
                        <div>
                            <div className="flex items-center gap-1 text-[10px] font-light uppercase tracking-wide text-gray-400 mb-1">
                                <Users className="h-3 w-3" /> Players
                            </div>
                            <div className="flex flex-wrap gap-1">
                                {parties.map((p, i) => (
                                    <span
                                        key={i}
                                        className="text-[11px] px-2 py-0.5 rounded-full border border-gray-200 bg-gray-50 text-gray-700 dark:border-white/10 dark:bg-white/5 dark:text-paper"
                                    >
                                        <span className="text-gray-400 mr-1">
                                            {p.role}
                                        </span>
                                        {p.name}
                                    </span>
                                ))}
                            </div>
                        </div>
                    )}

                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                        <MiniCol
                            icon={Scale}
                            color="#C7341A"
                            label="Allegations"
                            items={topClaims.map((c) => c.claim)}
                            empty="None"
                        />
                        <MiniCol
                            icon={Gavel}
                            color="#2B5CE6"
                            label="Authorities"
                            items={topAuths.map((a) => a.citation)}
                            empty="None"
                            mono
                        />
                        <MiniCol
                            icon={ShieldCheck}
                            color="#1F8A5B"
                            label="Defenses"
                            items={(extraction.defenses ?? [])
                                .slice(0, 3)
                                .map((d) => d.defense)}
                            empty="None"
                        />
                    </div>

                    <div className="flex flex-wrap gap-2 pt-1">
                        <button
                            type="button"
                            onClick={() =>
                                router.push(
                                    `/analytics?documentId=${encodeURIComponent(doc.id)}`,
                                )
                            }
                            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-light text-gray-700 hover:bg-gray-50 dark:border-white/10 dark:bg-white/5 dark:text-paper dark:hover:bg-white/10"
                        >
                            <Map className="h-3.5 w-3.5" />
                            Open Case Map
                        </button>
                        <button
                            type="button"
                            onClick={() => onOpenEditor?.(doc, extraction)}
                            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-900 bg-gray-900 px-2.5 py-1.5 text-xs font-light text-white hover:bg-gray-700 dark:border-white/20"
                        >
                            <PencilLine className="h-3.5 w-3.5" />
                            Open in editor
                        </button>
                    </div>
                </div>
            )}

            {status === "loading" && (
                <div className="px-4 pb-3">
                    <p className="text-xs text-gray-500 font-light">
                        Mapping parties, claims, defenses, and authorities…
                    </p>
                </div>
            )}
        </div>
    );
}

function MiniCol({
    icon: Icon,
    color,
    label,
    items,
    empty,
    mono,
}: {
    icon: React.ElementType;
    color: string;
    label: string;
    items: string[];
    empty: string;
    mono?: boolean;
}) {
    return (
        <div className="rounded-lg border border-gray-100 bg-gray-50/80 p-2 dark:border-white/10 dark:bg-white/[0.03]">
            <div
                className="flex items-center gap-1 text-[10px] font-light uppercase tracking-wide mb-1"
                style={{ color }}
            >
                <Icon className="h-3 w-3" />
                {label}
            </div>
            {items.length === 0 ? (
                <p className="text-[11px] text-gray-400 font-light">{empty}</p>
            ) : (
                <ul className="space-y-1">
                    {items.map((t, i) => (
                        <li
                            key={i}
                            className={`text-[11px] text-gray-700 line-clamp-2 dark:text-gray-300 font-light ${mono ? "font-mono" : ""}`}
                        >
                            {t}
                        </li>
                    ))}
                </ul>
            )}
        </div>
    );
}
