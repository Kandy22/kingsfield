"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, Loader2, Search, X } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:3001";

export interface Court {
    id: string;
    full_name: string;
    short_name: string;
    citation_string: string;
    jurisdiction: string; // CL jurisdiction code: F, FD, FB, S, SA, ST, FS, …
    in_use: boolean;
}

type TabKey = "federal-appellate" | "federal-district" | "bankruptcy" | "state" | "more";

const TABS: { key: TabKey; label: string }[] = [
    { key: "federal-appellate", label: "Federal Appellate" },
    { key: "federal-district", label: "Federal District" },
    { key: "bankruptcy", label: "Bankruptcy" },
    { key: "state", label: "State" },
    { key: "more", label: "More" },
];

function tabFor(court: Court): TabKey {
    switch (court.jurisdiction) {
        case "F":
            return "federal-appellate";
        case "FD":
            return "federal-district";
        case "FB":
        case "FBP":
            return "bankruptcy";
        case "S":
        case "SA":
        case "ST":
            return "state";
        default:
            return "more"; // special federal, military, tribal, territorial, committees…
    }
}

/** Section headers within a tab, keyed by CL jurisdiction code. */
const SECTION_LABELS: Record<string, string> = {
    S: "Supreme courts",
    SA: "Appellate courts",
    ST: "Trial courts",
    FS: "Special federal",
    FBP: "Bankruptcy panels",
};

// Minimal offline fallback if /api/research/courts is unreachable — SCOTUS,
// the 13 circuits, and state supreme courts were the old hand-maintained list.
const FALLBACK_COURTS: Court[] = [
    { id: "scotus", full_name: "Supreme Court of the United States", short_name: "SCOTUS", citation_string: "U.S.", jurisdiction: "F", in_use: true },
    ...["ca1", "ca2", "ca3", "ca4", "ca5", "ca6", "ca7", "ca8", "ca9", "ca10", "ca11", "cadc", "cafc"].map((id, i) => {
        const n = i + 1;
        const ord = n === 1 ? "1st" : n === 2 ? "2nd" : n === 3 ? "3rd" : `${n}th`;
        return {
            id,
            full_name: id === "cadc" ? "D.C. Circuit" : id === "cafc" ? "Federal Circuit" : `${ord} Circuit`,
            short_name: id,
            citation_string: "",
            jurisdiction: "F",
            in_use: true,
        };
    }),
];

export function CourtPicker({
    selected,
    onChange,
}: {
    selected: string[];
    onChange: (ids: string[]) => void;
}) {
    const [open, setOpen] = useState(false);
    const [tab, setTab] = useState<TabKey>("federal-appellate");
    const [courts, setCourts] = useState<Court[] | null>(null);
    const [loadError, setLoadError] = useState(false);
    const [filter, setFilter] = useState("");
    const [showHistorical, setShowHistorical] = useState(false);
    const panelRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const res = await fetch(`${API_BASE}/api/research/courts`);
                if (!res.ok) throw new Error(String(res.status));
                const data = (await res.json()) as { courts: Court[] };
                if (!cancelled) setCourts(data.courts ?? []);
            } catch {
                if (!cancelled) {
                    setCourts(FALLBACK_COURTS);
                    setLoadError(true);
                }
            }
        })();
        return () => {
            cancelled = true;
        };
    }, []);

    // Close on outside click
    useEffect(() => {
        if (!open) return;
        function onDocClick(e: MouseEvent) {
            if (panelRef.current && !panelRef.current.contains(e.target as Node)) setOpen(false);
        }
        document.addEventListener("mousedown", onDocClick);
        return () => document.removeEventListener("mousedown", onDocClick);
    }, [open]);

    const byId = useMemo(() => new Map((courts ?? []).map((c) => [c.id, c])), [courts]);

    const visible = useMemo(() => {
        if (!courts) return [];
        const f = filter.trim().toLowerCase();
        return courts.filter((c) => {
            if (!showHistorical && !c.in_use) return false;
            if (f) {
                // A search matches across ALL tabs so users don't hunt tab-by-tab
                return (
                    c.full_name.toLowerCase().includes(f) ||
                    c.short_name.toLowerCase().includes(f) ||
                    c.id.toLowerCase().includes(f) ||
                    c.citation_string.toLowerCase().includes(f)
                );
            }
            return tabFor(c) === tab;
        });
    }, [courts, tab, filter, showHistorical]);

    // Group the visible list into labelled sections (state supreme vs appellate, etc.)
    const sections = useMemo(() => {
        const groups = new Map<string, Court[]>();
        for (const c of visible) {
            const label = filter.trim()
                ? TABS.find((t) => t.key === tabFor(c))?.label ?? "Other"
                : SECTION_LABELS[c.jurisdiction] ?? "";
            const list = groups.get(label) ?? [];
            list.push(c);
            groups.set(label, list);
        }
        for (const list of groups.values()) {
            list.sort((a, b) => a.full_name.localeCompare(b.full_name));
        }
        return [...groups.entries()];
    }, [visible, filter]);

    function toggle(id: string) {
        onChange(selected.includes(id) ? selected.filter((s) => s !== id) : [...selected, id]);
    }

    const buttonLabel =
        selected.length === 0
            ? "All jurisdictions"
            : selected.length === 1
              ? (byId.get(selected[0])?.short_name || byId.get(selected[0])?.full_name || selected[0])
              : `${selected.length} courts`;

    return (
        <div className="relative" ref={panelRef}>
            <button
                type="button"
                onClick={() => setOpen(!open)}
                className="flex items-center gap-2 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-gray-900 cursor-pointer whitespace-nowrap max-w-[220px]"
                title={selected.length ? selected.join(", ") : "Choose courts"}
            >
                <span className="truncate">{buttonLabel}</span>
                <ChevronDown className="h-3.5 w-3.5 text-gray-400 flex-shrink-0" />
            </button>

            {open && (
                <div className="absolute right-0 z-40 mt-2 w-[560px] max-w-[90vw] rounded-xl border border-gray-200 bg-white shadow-xl">
                    {/* Search + tabs */}
                    <div className="p-3 border-b border-gray-100">
                        <div className="flex items-center gap-2 rounded-lg border border-gray-200 bg-gray-50 px-2.5 py-1.5 mb-2">
                            <Search className="h-3.5 w-3.5 text-gray-400 flex-shrink-0" />
                            <input
                                value={filter}
                                onChange={(e) => setFilter(e.target.value)}
                                placeholder="Filter courts — name, ID, or reporter…"
                                className="flex-1 bg-transparent text-xs text-gray-900 placeholder-gray-400 focus:outline-none"
                            />
                            {filter && (
                                <button onClick={() => setFilter("")} className="text-gray-300 hover:text-gray-600">
                                    <X className="h-3.5 w-3.5" />
                                </button>
                            )}
                        </div>
                        <div className="flex gap-1 flex-wrap">
                            {TABS.map((t) => (
                                <button
                                    key={t.key}
                                    onClick={() => { setTab(t.key); setFilter(""); }}
                                    className={`text-xs px-2.5 py-1 rounded-full transition-colors ${
                                        tab === t.key && !filter
                                            ? "bg-gray-900 text-white"
                                            : "text-gray-500 hover:bg-gray-100"
                                    }`}
                                >
                                    {t.label}
                                </button>
                            ))}
                        </div>
                    </div>

                    {/* Court list */}
                    <div className="max-h-72 overflow-y-auto px-3 py-2">
                        {courts === null ? (
                            <div className="flex items-center justify-center gap-2 py-8 text-xs text-gray-400">
                                <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading court list…
                            </div>
                        ) : visible.length === 0 ? (
                            <p className="py-8 text-center text-xs text-gray-400">No courts match.</p>
                        ) : (
                            sections.map(([label, list]) => (
                                <div key={label || "default"} className="mb-2">
                                    {label && (
                                        <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-400 px-1 pt-2 pb-1">
                                            {label}
                                        </p>
                                    )}
                                    <div className="grid grid-cols-2 gap-x-3">
                                        {list.map((c) => (
                                            <label
                                                key={c.id}
                                                className="flex items-start gap-2 px-1 py-1 rounded hover:bg-gray-50 cursor-pointer"
                                            >
                                                <input
                                                    type="checkbox"
                                                    checked={selected.includes(c.id)}
                                                    onChange={() => toggle(c.id)}
                                                    className="mt-0.5 h-3.5 w-3.5 rounded border-gray-300 accent-gray-900"
                                                />
                                                <span className={`text-xs leading-snug ${c.in_use ? "text-gray-700" : "text-gray-400"}`}>
                                                    {c.full_name || c.short_name || c.id}
                                                    {!c.in_use && " (historical)"}
                                                </span>
                                            </label>
                                        ))}
                                    </div>
                                </div>
                            ))
                        )}
                        {loadError && (
                            <p className="text-[10px] text-amber-600 px-1 py-1">
                                Full court list unavailable — showing federal courts only.
                            </p>
                        )}
                    </div>

                    {/* Footer */}
                    <div className="flex items-center justify-between gap-3 px-3 py-2 border-t border-gray-100 bg-gray-50 rounded-b-xl">
                        <label className="flex items-center gap-1.5 text-[11px] text-gray-500 cursor-pointer">
                            <input
                                type="checkbox"
                                checked={showHistorical}
                                onChange={(e) => setShowHistorical(e.target.checked)}
                                className="h-3 w-3 accent-gray-900"
                            />
                            Include historical courts
                        </label>
                        <div className="flex items-center gap-2">
                            <span className="text-[11px] text-gray-400">
                                {selected.length === 0 ? "All jurisdictions" : `${selected.length} selected`}
                            </span>
                            {selected.length > 0 && (
                                <button
                                    onClick={() => onChange([])}
                                    className="text-[11px] font-medium text-gray-500 hover:text-gray-900"
                                >
                                    Clear
                                </button>
                            )}
                            <button
                                onClick={() => setOpen(false)}
                                className="text-[11px] font-medium text-white bg-gray-900 hover:bg-gray-700 px-2.5 py-1 rounded transition-colors"
                            >
                                Done
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
