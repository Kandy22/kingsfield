"use client";

import { Sun, BookOpen, Moon } from "lucide-react";
import { useTheme, type Theme } from "@/app/contexts/ThemeContext";

const OPTIONS: { value: Theme; icon: React.ReactNode; label: string }[] = [
    { value: "light", icon: <Sun className="h-3.5 w-3.5" />, label: "Light" },
    { value: "beige", icon: <BookOpen className="h-3.5 w-3.5" />, label: "Parchment" },
    { value: "dark", icon: <Moon className="h-3.5 w-3.5" />, label: "Dark" },
];

export function ThemeToggle({ collapsed }: { collapsed?: boolean }) {
    const { theme, setTheme } = useTheme();

    return (
        <div
            className={`flex items-center gap-0.5 px-3 py-2 ${collapsed ? "justify-center" : ""}`}
        >
            {!collapsed && (
                <span className="text-xs text-muted-foreground mr-1.5 flex-shrink-0">
                    Theme
                </span>
            )}
            <div className="flex items-center rounded-md border border-border bg-muted p-0.5 gap-0.5">
                {OPTIONS.map((opt) => (
                    <button
                        key={opt.value}
                        onClick={() => setTheme(opt.value)}
                        title={opt.label}
                        className={`flex items-center gap-1 rounded px-1.5 py-1 text-xs transition-colors ${
                            theme === opt.value
                                ? "bg-background text-foreground shadow-sm"
                                : "text-muted-foreground hover:text-foreground"
                        }`}
                    >
                        {opt.icon}
                        {!collapsed && (
                            <span className="hidden sm:inline">{opt.label}</span>
                        )}
                    </button>
                ))}
            </div>
        </div>
    );
}
