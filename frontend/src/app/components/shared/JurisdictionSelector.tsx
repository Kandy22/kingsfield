"use client";

import { useState, useRef, useEffect } from "react";
import { ChevronDown, Scale, Check } from "lucide-react";
import { useJurisdiction } from "@/contexts/JurisdictionContext";
import { FEDERAL, STATE_JURISDICTIONS } from "@/app/lib/jurisdictions";

/**
 * The single, app-wide jurisdiction picker. Choose once; it scopes Case Law and
 * Legislation together and persists. Replaces the old per-page pickers.
 */
export function JurisdictionSelector({ compact = false }: { compact?: boolean }) {
    const { jurisdiction, setJurisdictionKey } = useJurisdiction();
    const [open, setOpen] = useState(false);
    const [query, setQuery] = useState("");
    const ref = useRef<HTMLDivElement>(null);

    useEffect(() => {
        function onDown(e: MouseEvent) {
            if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
        }
        document.addEventListener("mousedown", onDown);
        return () => document.removeEventListener("mousedown", onDown);
    }, []);

    const q = query.trim().toLowerCase();
    const states = q
        ? STATE_JURISDICTIONS.filter((s) => s.label.toLowerCase().includes(q) || s.abbr!.toLowerCase() === q)
        : STATE_JURISDICTIONS;

    return (
        <div className="relative" ref={ref}>
            <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                className={`flex items-center gap-2 rounded-lg border border-gray-300 bg-white ${compact ? "px-3 py-1.5 text-sm" : "px-4 py-2.5"} text-gray-800 hover:border-gray-400 focus:outline-none focus:ring-2 focus:ring-gray-900 transition-colors`}
            >
                <Scale className="h-4 w-4 text-gray-500 flex-shrink-0" />
                <span className="font-medium">{jurisdiction.label}</span>
                <ChevronDown className={`h-4 w-4 text-gray-400 transition-transform ${open ? "rotate-180" : ""}`} />
            </button>

            {open && (
                <div className="absolute z-30 mt-2 w-72 rounded-lg border border-gray-200 bg-white shadow-lg max-h-96 overflow-hidden flex flex-col">
                    <div className="p-2 border-b border-gray-100">
                        <input
                            autoFocus
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                            placeholder="Search jurisdiction…"
                            className="w-full rounded-md border border-gray-200 px-2.5 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-gray-900"
                        />
                    </div>
                    <div className="overflow-y-auto py-1">
                        {(!q || "federal".includes(q)) && (
                            <Row j={FEDERAL} selected={jurisdiction.key === FEDERAL.key} onPick={pick} />
                        )}
                        {states.length > 0 && (
                            <p className="px-3 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wide text-gray-400">States</p>
                        )}
                        {states.map((s) => (
                            <Row key={s.key} j={s} selected={jurisdiction.key === s.key} onPick={pick} />
                        ))}
                        {q && states.length === 0 && !"federal".includes(q) && (
                            <p className="px-3 py-3 text-sm text-gray-400">No match.</p>
                        )}
                    </div>
                </div>
            )}
        </div>
    );

    function pick(key: string) {
        setJurisdictionKey(key);
        setOpen(false);
        setQuery("");
    }
}

function Row({
    j,
    selected,
    onPick,
}: {
    j: { key: string; label: string };
    selected: boolean;
    onPick: (key: string) => void;
}) {
    return (
        <button
            type="button"
            onClick={() => onPick(j.key)}
            className={`flex w-full items-center justify-between px-3 py-2 text-sm text-left hover:bg-gray-50 ${selected ? "text-gray-900 font-medium" : "text-gray-700"}`}
        >
            <span>{j.label}</span>
            {selected && <Check className="h-4 w-4 text-gray-900" />}
        </button>
    );
}
