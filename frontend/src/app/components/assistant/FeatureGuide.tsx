"use client";

import Link from "next/link";
import { FileSearch, Link2, Map, Upload } from "lucide-react";

/**
 * Compact map — dual retrieval and Case Map.
 * Upload is primary via + Documents in the composer (not a faded stub).
 */
export function FeatureGuide() {
    return (
        <div className="w-full mt-6 space-y-3">
            <p className="text-[10px] font-light uppercase tracking-[0.14em] text-gray-400 text-center">
                Where things live
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <GuideCard
                    icon={Upload}
                    title="1. Upload in the box"
                    body="Use + Documents in the message bar (solid control). Case extract runs automatically after attach."
                />
                <GuideCard
                    icon={FileSearch}
                    title="2. Ask these docs"
                    body="After upload, a File Search binder appears under the composer — Index for Q&A, then ask with grounding."
                />
                <Link
                    href="/legislation"
                    className="block rounded-xl border border-blue-500/30 bg-blue-500/5 p-3 hover:bg-blue-500/10 transition-colors text-left"
                >
                    <div className="flex items-center gap-2 mb-1">
                        <Link2 className="h-4 w-4 text-blue-500" />
                        <span className="text-sm font-light text-gray-900 dark:text-paper">
                            3. Statutes · URL packs →
                        </span>
                    </div>
                    <p className="text-[11px] font-light text-gray-500 leading-relaxed">
                        Official multi-URL pack + chat. Uploaded PDFs stay on
                        Assistant.
                    </p>
                </Link>
                <Link
                    href="/analytics"
                    className="block rounded-xl border border-gray-200 dark:border-white/10 bg-white/50 dark:bg-white/[0.03] p-3 hover:border-gray-400 transition-colors text-left"
                >
                    <div className="flex items-center gap-2 mb-1">
                        <Map className="h-4 w-4 text-gray-500" />
                        <span className="text-sm font-light text-gray-900 dark:text-paper">
                            4. Case Map →
                        </span>
                    </div>
                    <p className="text-[11px] font-light text-gray-500 leading-relaxed">
                        Per-document extract map (sidebar: Case Map).
                    </p>
                </Link>
            </div>
        </div>
    );
}

function GuideCard({
    icon: Icon,
    title,
    body,
}: {
    icon: React.ElementType;
    title: string;
    body: string;
}) {
    return (
        <div className="rounded-xl border border-gray-200 dark:border-white/10 bg-white/50 dark:bg-white/[0.03] p-3 text-left">
            <div className="flex items-center gap-2 mb-1">
                <Icon className="h-4 w-4 text-gray-500" />
                <span className="text-sm font-light text-gray-900 dark:text-paper">
                    {title}
                </span>
            </div>
            <p className="text-[11px] font-light text-gray-500 leading-relaxed">
                {body}
            </p>
        </div>
    );
}
