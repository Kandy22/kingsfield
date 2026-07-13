"use client";

import React, { createContext, useContext, useEffect, useMemo, useState, ReactNode } from "react";
import { FEDERAL, findJurisdiction, type Jurisdiction } from "@/app/lib/jurisdictions";

const STORAGE_KEY = "kingsfield_jurisdiction";
const STORAGE_CUSTOM = "kingsfield_jurisdiction_custom_courts";

interface JurisdictionContextType {
    /** Primary jurisdiction — drives statutes + the "preset" case-law court set. */
    jurisdiction: Jurisdiction;
    /** Effective CourtListener court IDs for case search (preset or multi-select). */
    courtIds: string[];
    /** True when the user picked a custom multi-court set via "Select courts…". */
    isCustomCourts: boolean;
    /** Preset Federal/State pick — clears any multi-court override. */
    setJurisdictionKey: (key: string) => void;
    /**
     * Multi-court override for case law. Empty array = clear custom (back to preset).
     * Optional primaryKey updates statute jurisdiction without clearing the custom set.
     */
    setCustomCourtIds: (ids: string[], primaryKey?: string) => void;
    clearCustomCourts: () => void;
}

const JurisdictionContext = createContext<JurisdictionContextType | undefined>(undefined);

export function JurisdictionProvider({ children }: { children: ReactNode }) {
    const [jurisdiction, setJurisdiction] = useState<Jurisdiction>(FEDERAL);
    const [customCourtIds, setCustomCourtIdsState] = useState<string[] | null>(null);

    // Restore last pick on mount.
    useEffect(() => {
        try {
            const saved = localStorage.getItem(STORAGE_KEY);
            if (saved) setJurisdiction(findJurisdiction(saved));
            const custom = localStorage.getItem(STORAGE_CUSTOM);
            if (custom) {
                const parsed = JSON.parse(custom) as string[];
                if (Array.isArray(parsed) && parsed.length > 0) setCustomCourtIdsState(parsed);
            }
        } catch {
            /* ignore */
        }
    }, []);

    const setJurisdictionKey = (key: string) => {
        const next = findJurisdiction(key);
        setJurisdiction(next);
        setCustomCourtIdsState(null);
        try {
            localStorage.setItem(STORAGE_KEY, next.key);
            localStorage.removeItem(STORAGE_CUSTOM);
        } catch {
            /* ignore */
        }
    };

    const setCustomCourtIds = (ids: string[], primaryKey?: string) => {
        if (ids.length === 0) {
            setCustomCourtIdsState(null);
            try {
                localStorage.removeItem(STORAGE_CUSTOM);
            } catch {
                /* ignore */
            }
            return;
        }
        setCustomCourtIdsState(ids);
        if (primaryKey) {
            const next = findJurisdiction(primaryKey);
            setJurisdiction(next);
            try {
                localStorage.setItem(STORAGE_KEY, next.key);
            } catch {
                /* ignore */
            }
        }
        try {
            localStorage.setItem(STORAGE_CUSTOM, JSON.stringify(ids));
        } catch {
            /* ignore */
        }
    };

    const clearCustomCourts = () => setCustomCourtIds([]);

    const courtIds = useMemo(
        () => (customCourtIds && customCourtIds.length > 0 ? customCourtIds : jurisdiction.courtIds),
        [customCourtIds, jurisdiction.courtIds],
    );

    const value: JurisdictionContextType = {
        jurisdiction,
        courtIds,
        isCustomCourts: !!(customCourtIds && customCourtIds.length > 0),
        setJurisdictionKey,
        setCustomCourtIds,
        clearCustomCourts,
    };

    return (
        <JurisdictionContext.Provider value={value}>
            {children}
        </JurisdictionContext.Provider>
    );
}

export function useJurisdiction() {
    const ctx = useContext(JurisdictionContext);
    if (ctx === undefined) {
        throw new Error("useJurisdiction must be used within a JurisdictionProvider");
    }
    return ctx;
}
