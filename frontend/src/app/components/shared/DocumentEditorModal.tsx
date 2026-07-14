"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Download, X } from "lucide-react";
import { DocView } from "./DocView";
import { getDocumentUrl } from "@/app/lib/mikeApi";
import {
    applyLegalReviewHighlights,
    LEGAL_REVIEW_HIGHLIGHT_CSS,
} from "@/app/lib/legalReviewHighlight";
import type { Document } from "./types";

interface Props {
    doc: Document | null;
    authorities?: string[];
    onClose: () => void;
}

/**
 * Full-screen document editor surface (viewer + Review highlights).
 * Not a free-form Word clone — DOCX track-changes still come from Assistant;
 * this is the place to read with authority (blue) and prior-filing (green) paint.
 */
export function DocumentEditorModal({ doc, authorities = [], onClose }: Props) {
    const [mounted, setMounted] = useState(false);
    const paintRootRef = useRef<HTMLDivElement>(null);
    const authoritiesRef = useRef(authorities);
    authoritiesRef.current = authorities;

    useEffect(() => setMounted(true), []);

    useEffect(() => {
        if (!mounted) return;
        const id = "kf-legal-review-highlight-css";
        if (!document.getElementById(id)) {
            const style = document.createElement("style");
            style.id = id;
            style.textContent = LEGAL_REVIEW_HIGHLIGHT_CSS;
            document.head.appendChild(style);
        }
    }, [mounted]);

    // Timed re-paints as PDF text layer / docx-preview finish (avoid MutationObserver
    // feedback loops from wrap/unwrap of highlight spans).
    useEffect(() => {
        if (!doc || !mounted) return;
        const root = paintRootRef.current;
        if (!root) return;

        const paint = () => {
            applyLegalReviewHighlights(root, authoritiesRef.current);
        };

        const timers = [600, 1500, 3000, 5000].map((ms) =>
            window.setTimeout(paint, ms),
        );

        return () => {
            timers.forEach(clearTimeout);
        };
    }, [doc?.id, mounted, authorities]);

    if (!doc || !mounted) return null;

    async function handleDownload() {
        if (!doc) return;
        const { url, filename } = await getDocumentUrl(doc.id, null);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        a.click();
    }

    return createPortal(
        <div
            className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50"
            onClick={onClose}
        >
            <div
                className="relative flex flex-col w-[min(1100px,96vw)] h-[92vh] rounded-xl shadow-2xl overflow-hidden border border-white/10"
                style={{ background: "#0E0C09" }}
                onClick={(e) => e.stopPropagation()}
            >
                <div
                    className="flex items-center justify-between px-5 py-3 shrink-0 border-b"
                    style={{
                        borderColor: "rgba(255,255,255,0.08)",
                        background: "#141109",
                    }}
                >
                    <div className="min-w-0">
                        <p
                            className="text-[10px] font-semibold uppercase tracking-[0.14em]"
                            style={{ color: "#A09485" }}
                        >
                            Document editor · Review
                        </p>
                        <p
                            className="text-sm font-medium truncate"
                            style={{ color: "#F5F1EA" }}
                        >
                            {doc.filename}
                        </p>
                        <p
                            className="text-[11px] mt-0.5"
                            style={{ color: "#7A7060" }}
                        >
                            <span style={{ color: "#5B9BD5" }}>■</span>{" "}
                            Authorities
                            <span className="mx-2">·</span>
                            <span style={{ color: "#6FBF73" }}>■</span> Prior
                            filings
                        </p>
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                        <button
                            type="button"
                            onClick={handleDownload}
                            className="flex items-center justify-center w-8 h-8 rounded-lg transition-colors"
                            style={{ color: "#A09485" }}
                            title="Download"
                        >
                            <Download className="h-4 w-4" />
                        </button>
                        <button
                            type="button"
                            onClick={onClose}
                            className="flex items-center justify-center w-8 h-8 rounded-lg transition-colors"
                            style={{ color: "#A09485" }}
                            title="Close"
                        >
                            <X className="h-4 w-4" />
                        </button>
                    </div>
                </div>

                <div
                    ref={paintRootRef}
                    className="flex flex-col flex-1 min-h-0 overflow-hidden px-3 pb-3 bg-white"
                >
                    <DocView
                        key={doc.id}
                        doc={{ document_id: doc.id, version_id: null }}
                        rounded={false}
                        bordered={false}
                    />
                </div>
            </div>
        </div>,
        document.body,
    );
}
