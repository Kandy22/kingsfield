"use client";

import { createContext, useContext, useEffect, useState } from "react";

export type Theme = "light" | "beige" | "dark";

interface ThemeContextType {
    theme: Theme;
    setTheme: (t: Theme) => void;
}

const ThemeContext = createContext<ThemeContextType>({
    theme: "light",
    setTheme: () => {},
});

export function ThemeProvider({ children }: { children: React.ReactNode }) {
    const [theme, setThemeState] = useState<Theme>("dark");

    // Read saved preference on mount
    useEffect(() => {
        try {
            const saved = localStorage.getItem("kingsfield-theme") as Theme | null;
            // "dark" is the brand default — only honour saved if explicitly dark or beige
            if (saved === "beige" || saved === "dark") {
                setThemeState(saved);
            } else {
                // clear any stale "light" preference
                localStorage.removeItem("kingsfield-theme");
            }
        } catch {}
    }, []);

    // Apply class to <html> whenever theme changes
    useEffect(() => {
        const root = document.documentElement;
        root.classList.remove("light", "beige", "dark");
        if (theme !== "light") root.classList.add(theme);
        try {
            localStorage.setItem("kingsfield-theme", theme);
        } catch {}
    }, [theme]);

    const setTheme = (t: Theme) => setThemeState(t);

    return (
        <ThemeContext.Provider value={{ theme, setTheme }}>
            {children}
        </ThemeContext.Provider>
    );
}

export function useTheme() {
    return useContext(ThemeContext);
}
