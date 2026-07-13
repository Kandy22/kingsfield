"use client";

import React, { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { FEDERAL, findJurisdiction, type Jurisdiction } from "@/app/lib/jurisdictions";

const STORAGE_KEY = "kingsfield_jurisdiction";

interface JurisdictionContextType {
    jurisdiction: Jurisdiction;
    setJurisdictionKey: (key: string) => void;
}

const JurisdictionContext = createContext<JurisdictionContextType | undefined>(undefined);

export function JurisdictionProvider({ children }: { children: ReactNode }) {
    const [jurisdiction, setJurisdiction] = useState<Jurisdiction>(FEDERAL);

    // Restore the last-picked jurisdiction on mount (persisted across pages/sessions).
    useEffect(() => {
        try {
            const saved = localStorage.getItem(STORAGE_KEY);
            if (saved) setJurisdiction(findJurisdiction(saved));
        } catch {
            /* ignore */
        }
    }, []);

    const setJurisdictionKey = (key: string) => {
        const next = findJurisdiction(key);
        setJurisdiction(next);
        try {
            localStorage.setItem(STORAGE_KEY, next.key);
        } catch {
            /* ignore */
        }
    };

    return (
        <JurisdictionContext.Provider value={{ jurisdiction, setJurisdictionKey }}>
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
