"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Check, ChevronDown, Loader2, Scale, Search, X } from "lucide-react";
import { useJurisdiction } from "@/contexts/JurisdictionContext";
import { FEDERAL, STATE_JURISDICTIONS } from "@/app/lib/jurisdictions";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:3001";

/**
 * Google-Scholar-style jurisdiction control (Pass 2).
 *
 * Tier 1 — quick radios: Federal courts | [State] courts | Select courts…
 * Tier 2 — multi-select grid behind "Select courts…" (static + optional CL snapshot).
 *
 * One shared value scopes Case Law courts AND Legislation statutes.
 */

type CourtRow = {
    id: string;
    full_name: string;
    short_name: string;
    jurisdiction: string;
    in_use: boolean;
};

type TabKey = "federal" | "state" | "more";

function buildStaticCourts(): CourtRow[] {
    const rows: CourtRow[] = [];
    for (const id of FEDERAL.courtIds) {
        const label =
            id === "scotus"
                ? "Supreme Court of the United States"
                : id === "cadc"
                  ? "U.S. Court of Appeals for the D.C. Circuit"
                  : id === "cafc"
                    ? "U.S. Court of Appeals for the Federal Circuit"
                    : `U.S. Court of Appeals (${id.toUpperCase()})`;
        rows.push({
            id,
            full_name: label,
            short_name: id,
            jurisdiction: "F",
            in_use: true,
        });
    }
    for (const s of STATE_JURISDICTIONS) {
        s.courtIds.forEach((id, i) => {
            rows.push({
                id,
                full_name: i === 0 ? `${s.label} Supreme Court` : `${s.label} Court of Appeals`,
                short_name: id,
                jurisdiction: i === 0 ? "S" : "SA",
                in_use: true,
            });
        });
    }
    return rows;
}

const STATIC_COURTS = buildStaticCourts();

export function JurisdictionSelector({
    compact = false,
    /** Prominent placement (Assistant front door). */
    prominent = false,
}: {
    compact?: boolean;
    prominent?: boolean;
}) {
    const {
        jurisdiction,
        courtIds,
        isCustomCourts,
        setJurisdictionKey,
        setCustomCourtIds,
        clearCustomCourts,
    } = useJurisdiction();

    const [stateMenuOpen, setStateMenuOpen] = useState(false);
    const [stateQuery, setStateQuery] = useState("");
    const [gridOpen, setGridOpen] = useState(false);
    const [draftCourts, setDraftCourts] = useState<string[]>([]);
    const [allCourts, setAllCourts] = useState<CourtRow[] | null>(null);
    const [loadError, setLoadError] = useState(false);
    const [gridFilter, setGridFilter] = useState("");
    const [gridTab, setGridTab] = useState<TabKey>("federal");

    const stateRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (!stateMenuOpen) return;
        function onDown(e: MouseEvent) {
            if (stateRef.current && !stateRef.current.contains(e.target as Node)) {
                setStateMenuOpen(false);
            }
        }
        document.addEventListener("mousedown", onDown);
        return () => document.removeEventListener("mousedown", onDown);
    }, [stateMenuOpen]);

    useEffect(() => {
        if (!gridOpen) return;
        let cancelled = false;
        (async () => {
            try {
                const res = await fetch(`${API_BASE}/api/research/courts`);
                if (!res.ok) throw new Error(String(res.status));
                const data = (await res.json()) as { courts: CourtRow[] };
                if (!cancelled) {
                    setAllCourts(data.courts?.length ? data.courts : STATIC_COURTS);
                    setLoadError(!data.courts?.length);
                }
            } catch {
                if (!cancelled) {
                    setAllCourts(STATIC_COURTS);
                    setLoadError(true);
                }
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [gridOpen]);

    const q = stateQuery.trim().toLowerCase();
    const filteredStates = q
        ? STATE_JURISDICTIONS.filter(
              (s) => s.label.toLowerCase().includes(q) || s.abbr!.toLowerCase() === q,
          )
        : STATE_JURISDICTIONS;

    const mode: "federal" | "state" | "custom" = isCustomCourts
        ? "custom"
        : jurisdiction.type === "federal"
          ? "federal"
          : "state";

    const stateLabel =
        jurisdiction.type === "state" ? `${jurisdiction.label} courts` : "State courts";

    function openGrid() {
        setDraftCourts(courtIds.length ? [...courtIds] : []);
        setGridFilter("");
        setGridTab("federal");
        setGridOpen(true);
    }

    function applyGrid() {
        if (draftCourts.length === 0) {
            clearCustomCourts();
            setGridOpen(false);
            return;
        }
        // If every selected court belongs to one state, promote that state for statutes.
        const pureState = STATE_JURISDICTIONS.find(
            (s) => s.courtIds.length > 0 && draftCourts.every((id) => s.courtIds.includes(id)),
        );
        const allFederal = draftCourts.every((id) => FEDERAL.courtIds.includes(id));
        const primaryKey = pureState?.key ?? (allFederal ? FEDERAL.key : undefined);
        setCustomCourtIds(draftCourts, primaryKey);
        setGridOpen(false);
    }

    const gridVisible = useMemo(() => {
        if (!allCourts) return [];
        const f = gridFilter.trim().toLowerCase();
        return allCourts.filter((c) => {
            if (f) {
                return (
                    c.full_name?.toLowerCase().includes(f) ||
                    c.short_name?.toLowerCase().includes(f) ||
                    c.id.toLowerCase().includes(f)
                );
            }
            if (gridTab === "federal") {
                return c.jurisdiction === "F" || c.jurisdiction === "FD" || c.jurisdiction === "FB";
            }
            if (gridTab === "state") {
                return c.jurisdiction === "S" || c.jurisdiction === "SA" || c.jurisdiction === "ST";
            }
            return !["F", "FD", "FB", "FBP", "S", "SA", "ST"].includes(c.jurisdiction);
        });
    }, [allCourts, gridFilter, gridTab]);

    function toggleDraft(id: string) {
        setDraftCourts((prev) =>
            prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
        );
    }

    const shell = prominent
        ? "w-full max-w-4xl rounded-xl border border-gray-200 bg-white px-4 py-3 shadow-sm"
        : compact
          ? "inline-flex flex-wrap items-center gap-1"
          : "inline-flex flex-wrap items-center gap-1.5";

    return (
        <>
            <div className={shell}>
                {prominent && (
                    <div className="flex items-center gap-2 mb-2">
                        <Scale className="h-4 w-4 text-gray-500" />
                        <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                            Jurisdiction
                        </span>
                        <span className="text-xs text-gray-400">
                            Scopes case law and statutes together
                        </span>
                    </div>
                )}

                <div className={`flex flex-wrap items-center ${compact ? "gap-1" : "gap-1.5"}`}>
                    <RadioChip
                        active={mode === "federal"}
                        compact={compact}
                        onClick={() => setJurisdictionKey(FEDERAL.key)}
                        label="Federal courts"
                    />

                    <div className="relative" ref={stateRef}>
                        <RadioChip
                            active={mode === "state"}
                            compact={compact}
                            onClick={() => setStateMenuOpen((v) => !v)}
                            label={stateLabel}
                            trailing={
                                <ChevronDown
                                    className={`h-3 w-3 opacity-60 ${stateMenuOpen ? "rotate-180" : ""}`}
                                />
                            }
                        />
                        {stateMenuOpen && (
                            <div className="absolute z-40 mt-1.5 w-64 rounded-lg border border-gray-200 bg-white shadow-lg max-h-80 overflow-hidden flex flex-col left-0">
                                <div className="p-2 border-b border-gray-100">
                                    <input
                                        autoFocus
                                        value={stateQuery}
                                        onChange={(e) => setStateQuery(e.target.value)}
                                        placeholder="Search state…"
                                        className="w-full rounded-md border border-gray-200 px-2.5 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-gray-900"
                                    />
                                </div>
                                <div className="overflow-y-auto py-1">
                                    {filteredStates.map((s) => (
                                        <button
                                            key={s.key}
                                            type="button"
                                            onClick={() => {
                                                setJurisdictionKey(s.key);
                                                setStateMenuOpen(false);
                                                setStateQuery("");
                                            }}
                                            className={`flex w-full items-center justify-between px-3 py-2 text-sm text-left hover:bg-gray-50 ${
                                                jurisdiction.key === s.key && mode === "state"
                                                    ? "font-medium text-gray-900"
                                                    : "text-gray-700"
                                            }`}
                                        >
                                            <span>{s.label}</span>
                                            {jurisdiction.key === s.key && mode === "state" && (
                                                <Check className="h-4 w-4" />
                                            )}
                                        </button>
                                    ))}
                                    {filteredStates.length === 0 && (
                                        <p className="px-3 py-3 text-sm text-gray-400">No match.</p>
                                    )}
                                </div>
                            </div>
                        )}
                    </div>

                    <button
                        type="button"
                        onClick={openGrid}
                        className={`rounded-full border transition-colors ${
                            mode === "custom"
                                ? "border-gray-900 bg-gray-900 text-white"
                                : "border-gray-300 bg-white text-gray-700 hover:border-gray-400"
                        } ${compact ? "px-2.5 py-1 text-xs" : "px-3 py-1.5 text-sm"}`}
                    >
                        {mode === "custom"
                            ? `${courtIds.length} courts selected`
                            : "Select courts…"}
                    </button>
                </div>

                {prominent && (
                    <p className="mt-2 text-xs text-gray-400">
                        Active:{" "}
                        <span className="text-gray-600 font-medium">
                            {mode === "custom"
                                ? `${courtIds.length} courts · statutes follow ${jurisdiction.label}`
                                : jurisdiction.label}
                        </span>
                    </p>
                )}
            </div>

            {gridOpen && (
                <div
                    className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-gray-900/50"
                    onClick={(e) => {
                        if (e.target === e.currentTarget) setGridOpen(false);
                    }}
                >
                    <div className="w-full max-w-2xl max-h-[85vh] rounded-xl border border-gray-200 bg-white shadow-2xl flex flex-col">
                        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
                            <div>
                                <h2 className="text-sm font-semibold text-gray-900">Select courts</h2>
                                <p className="text-xs text-gray-400 mt-0.5">
                                    Multi-select for case search. Statutes stay on {jurisdiction.label}.
                                </p>
                            </div>
                            <button
                                type="button"
                                onClick={() => setGridOpen(false)}
                                className="p-1 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-700"
                            >
                                <X className="h-4 w-4" />
                            </button>
                        </div>

                        <div className="p-3 border-b border-gray-100">
                            <div className="flex items-center gap-2 rounded-lg border border-gray-200 bg-gray-50 px-2.5 py-1.5 mb-2">
                                <Search className="h-3.5 w-3.5 text-gray-400 flex-shrink-0" />
                                <input
                                    value={gridFilter}
                                    onChange={(e) => setGridFilter(e.target.value)}
                                    placeholder="Filter courts…"
                                    className="flex-1 bg-transparent text-xs text-gray-900 placeholder-gray-400 focus:outline-none"
                                />
                            </div>
                            <div className="flex gap-1 flex-wrap">
                                {(
                                    [
                                        ["federal", "Federal"],
                                        ["state", "State"],
                                        ["more", "More"],
                                    ] as const
                                ).map(([key, label]) => (
                                    <button
                                        key={key}
                                        type="button"
                                        onClick={() => {
                                            setGridTab(key);
                                            setGridFilter("");
                                        }}
                                        className={`text-xs px-2.5 py-1 rounded-full transition-colors ${
                                            gridTab === key && !gridFilter
                                                ? "bg-gray-900 text-white"
                                                : "text-gray-500 hover:bg-gray-100"
                                        }`}
                                    >
                                        {label}
                                    </button>
                                ))}
                            </div>
                        </div>

                        <div className="flex-1 overflow-y-auto px-3 py-2 min-h-[200px]">
                            {allCourts === null ? (
                                <div className="flex items-center justify-center gap-2 py-10 text-xs text-gray-400">
                                    <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading courts…
                                </div>
                            ) : gridVisible.length === 0 ? (
                                <p className="py-10 text-center text-xs text-gray-400">No courts match.</p>
                            ) : (
                                <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-3">
                                    {gridVisible.map((c) => (
                                        <label
                                            key={c.id}
                                            className="flex items-start gap-2 px-1 py-1.5 rounded hover:bg-gray-50 cursor-pointer"
                                        >
                                            <input
                                                type="checkbox"
                                                checked={draftCourts.includes(c.id)}
                                                onChange={() => toggleDraft(c.id)}
                                                className="mt-0.5 h-3.5 w-3.5 rounded border-gray-300 accent-gray-900"
                                            />
                                            <span className="text-xs leading-snug text-gray-700">
                                                {c.full_name || c.short_name || c.id}
                                            </span>
                                        </label>
                                    ))}
                                </div>
                            )}
                            {loadError && (
                                <p className="text-[10px] text-amber-600 px-1 py-2">
                                    Full CourtListener list unavailable — showing built-in federal + major state
                                    courts.
                                </p>
                            )}
                        </div>

                        <div className="flex items-center justify-between gap-3 px-4 py-3 border-t border-gray-100 bg-gray-50 rounded-b-xl">
                            <span className="text-[11px] text-gray-400">
                                {draftCourts.length === 0
                                    ? "None selected (uses Federal / State preset)"
                                    : `${draftCourts.length} selected`}
                            </span>
                            <div className="flex items-center gap-2">
                                {draftCourts.length > 0 && (
                                    <button
                                        type="button"
                                        onClick={() => setDraftCourts([])}
                                        className="text-[11px] font-medium text-gray-500 hover:text-gray-900"
                                    >
                                        Clear
                                    </button>
                                )}
                                <button
                                    type="button"
                                    onClick={() => setGridOpen(false)}
                                    className="text-[11px] font-medium text-gray-600 hover:text-gray-900 px-2.5 py-1"
                                >
                                    Cancel
                                </button>
                                <button
                                    type="button"
                                    onClick={applyGrid}
                                    className="text-[11px] font-medium text-white bg-gray-900 hover:bg-gray-700 px-3 py-1.5 rounded transition-colors"
                                >
                                    Done
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </>
    );
}

function RadioChip({
    active,
    compact,
    onClick,
    label,
    trailing,
}: {
    active: boolean;
    compact: boolean;
    onClick: () => void;
    label: string;
    trailing?: ReactNode;
}) {
    return (
        <button
            type="button"
            onClick={onClick}
            className={`inline-flex items-center gap-1.5 rounded-full border transition-colors ${
                active
                    ? "border-gray-900 bg-gray-900 text-white"
                    : "border-gray-300 bg-white text-gray-700 hover:border-gray-400"
            } ${compact ? "px-2.5 py-1 text-xs" : "px-3 py-1.5 text-sm"}`}
        >
            <span
                className={`inline-block rounded-full border ${
                    active ? "border-white bg-white" : "border-gray-400"
                } ${compact ? "h-2 w-2" : "h-2.5 w-2.5"}`}
                aria-hidden
            />
            <span className="whitespace-nowrap">{label}</span>
            {trailing}
        </button>
    );
}
