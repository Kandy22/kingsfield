"use client";

import { useState, useEffect } from "react";
import {
    MessageSquare, FolderOpen, Table2, Library,
    User, ChevronsUpDown, ChevronDown,
    BookOpen, Scroll, Scale, Plus, Network,
} from "lucide-react";
import Image from "next/image";
import { useAuth } from "@/contexts/AuthContext";
import { useUserProfile } from "@/contexts/UserProfileContext";
import { ThemeToggle } from "./ThemeToggle";
import { useChatHistoryContext } from "@/app/contexts/ChatHistoryContext";
import { useRouter, usePathname } from "next/navigation";
import Link from "next/link";
import { SidebarChatItem } from "@/app/components/shared/SidebarChatItem";
import { listProjects } from "@/app/lib/mikeApi";

interface SectionConfig {
    href: string;
    label: string;
    sublabel: string;
    icon: React.ElementType;
    /** Bold, distinct panel background — each section must be unmistakably different */
    bg: string;
}

// Uniform ink panel — instrument layer aesthetic per brand guide.
// #161615 = ink-2. Section identity via blue accent, not bg color.
const SECTIONS: SectionConfig[] = [
    { href: "/assistant",       label: "Assistant",       sublabel: "AI research & drafting",   icon: MessageSquare, bg: "#161615" },
    { href: "/case-law",        label: "Case Law",        sublabel: "Search opinions",           icon: BookOpen,      bg: "#161615" },
    { href: "/council",         label: "Council",         sublabel: "Multi-model deliberation",  icon: Scale,         bg: "#161615" },
    { href: "/projects",        label: "Projects",        sublabel: "Case workspaces",           icon: FolderOpen,    bg: "#161615" },
    { href: "/legislation",     label: "Legislation",     sublabel: "Statutes & codes",          icon: Scroll,        bg: "#161615" },
    { href: "/tabular-reviews", label: "Tabular Review",  sublabel: "Structured extraction",     icon: Table2,        bg: "#161615" },
    { href: "/workflows",       label: "Workflows",       sublabel: "Automated pipelines",       icon: Library,       bg: "#161615" },
    { href: "/analytics",       label: "Analytics",       sublabel: "Judicial connections",      icon: Network,       bg: "#161615" },
];

interface AppSidebarProps {
    isOpen: boolean;
    onToggle: () => void;
}

export function AppSidebar({ isOpen, onToggle }: AppSidebarProps) {
    const { user } = useAuth();
    const { profile } = useUserProfile();
    const { chats, currentChatId, setCurrentChatId } = useChatHistoryContext();
    const router = useRouter();
    const pathname = usePathname();
    const [dropdownOpen, setDropdownOpen] = useState(false);
    const [historyCollapsed, setHistoryCollapsed] = useState(false);
    const [projectNames, setProjectNames] = useState<Record<string, string>>({});

    const active = SECTIONS.find(s => pathname === s.href || pathname.startsWith(s.href + "/"));
    const panelBg = active?.bg ?? "#161615";

    useEffect(() => {
        if (!user) return;
        listProjects().then(projects => {
            const map: Record<string, string> = {};
            projects.forEach(p => { map[p.id] = p.name; });
            setProjectNames(map);
        }).catch(() => {});
    }, [user]);

    useEffect(() => {
        const close = () => setDropdownOpen(false);
        if (dropdownOpen) { document.addEventListener("click", close); return () => document.removeEventListener("click", close); }
    }, [dropdownOpen]);

    useEffect(() => {
        if (pathname.startsWith("/assistant/chat/")) {
            setCurrentChatId(pathname.split("/").pop() ?? null); return;
        }
        const m = pathname.match(/^\/projects\/[^/]+\/assistant\/chat\/([^/]+)/);
        if (m) { setCurrentChatId(m[1]); return; }
        if (pathname === "/assistant") setCurrentChatId(null);
    }, [pathname, setCurrentChatId]);

    const initials = () => profile?.displayName?.[0]?.toUpperCase() ?? user?.email?.[0]?.toUpperCase() ?? "?";
    const displayName = () => profile?.displayName ?? user?.email?.split("@")[0] ?? "";
    const tier = () => profile?.tier ?? "Free";

    if (!user) return null;

    return (
        <div className="flex h-dvh flex-shrink-0">

            {/* ── STRIP: ink (#0A0A0A), always 52px ── */}
            <div className="flex flex-col items-center py-3 flex-shrink-0"
                style={{ width: 52, background: "#0A0A0A", borderRight: "1px solid #2A2A28" }}>

                {/* Skull logo mark */}
                <Link href="/assistant" className="mb-2 block" title="Kingsfield">
                    <div style={{ width: 36, height: 36, borderRadius: "50%", overflow: "hidden", border: "1px solid #2A2A28" }}>
                        <Image src="/skull.jpg" alt="Kingsfield" width={36} height={36}
                            style={{ objectFit: "cover", objectPosition: "center" }} />
                    </div>
                </Link>

                {/* Nav icons */}
                <div className="flex flex-col gap-0.5 flex-1 mt-1">
                    {SECTIONS.map(({ href, label, icon: Icon, bg }) => {
                        const isActive = pathname === href || pathname.startsWith(href + "/");
                        return (
                            <button key={href}
                                onClick={() => { router.push(href); if (!isOpen) onToggle(); }}
                                title={label}
                                style={{
                                    width: 36, height: 36,
                                    display: "flex", alignItems: "center", justifyContent: "center",
                                    borderRadius: 0,
                                    background: isActive ? "rgba(43,92,230,0.12)" : "transparent",
                                    color: isActive ? "#2B5CE6" : "#5A5A56",
                                    borderLeft: isActive ? "2px solid #2B5CE6" : "2px solid transparent",
                                    cursor: "pointer",
                                    transition: "all 0.15s",
                                }}
                                onMouseEnter={e => { if (!isActive) (e.currentTarget as HTMLElement).style.color = "#C4C3BD"; }}
                                onMouseLeave={e => { if (!isActive) (e.currentTarget as HTMLElement).style.color = "#5A5A56"; }}
                            >
                                <Icon style={{ width: 15, height: 15 }} />
                            </button>
                        );
                    })}
                </div>

                {/* Bottom: theme + avatar */}
                <div className="mt-auto flex flex-col items-center gap-2">
                    <ThemeToggle collapsed={true} />
                    <button onClick={() => router.push("/account")} title={user.email}
                        style={{
                            width: 28, height: 28, borderRadius: "50%",
                            background: "#161615", color: "#C4C3BD",
                            fontSize: 11, fontWeight: 600,
                            display: "flex", alignItems: "center", justifyContent: "center",
                            border: "1px solid #2A2A28", cursor: "pointer",
                        }}>
                        {initials()}
                    </button>
                </div>
            </div>

            {/* ── PANEL: bold section color, white text throughout ── */}
            {isOpen && (
                <div className="flex flex-col h-dvh flex-shrink-0 overflow-hidden"
                    style={{
                        width: 216,
                        background: panelBg,
                        borderRight: "1px solid rgba(255,255,255,0.08)",
                        transition: "background 0.2s ease",
                    }}>

                    {/* Header — click to collapse */}
                    <button onClick={onToggle} className="text-left px-5 pt-5 pb-4 flex-shrink-0 w-full">
                        <div style={{ fontSize: 10, letterSpacing: "0.18em", color: "rgba(255,255,255,0.40)", fontFamily: "var(--font-dm-sans)", fontWeight: 600, textTransform: "uppercase", marginBottom: 6 }}>
                            Kingsfield
                        </div>
                        <div style={{
                            fontFamily: "var(--font-playfair), 'Playfair Display', Georgia, serif",
                            fontSize: 22,
                            fontWeight: 900,
                            color: "#FFFFFF",
                            letterSpacing: "-0.02em",
                            lineHeight: 1.1,
                        }}>
                            {active?.label ?? "Kingsfield"}
                        </div>
                        {active?.sublabel && (
                            <div style={{ fontSize: 11, color: "rgba(255,255,255,0.45)", marginTop: 3, fontFamily: "var(--font-dm-sans)" }}>
                                {active.sublabel}
                            </div>
                        )}
                        <div style={{ marginTop: 14, height: 1, background: "rgba(255,255,255,0.15)" }} />
                    </button>

                    {/* Nav links */}
                    <div style={{ padding: "0 10px", flexShrink: 0 }}>
                        {SECTIONS.map(({ href, label, icon: Icon }) => {
                            const isActive = pathname === href || pathname.startsWith(href + "/");
                            return (
                                <button key={href} onClick={() => router.push(href)}
                                    style={{
                                        width: "100%", display: "flex", alignItems: "center", gap: 9,
                                        padding: "7px 10px", borderRadius: 4, marginBottom: 2,
                                        background: isActive ? "rgba(255,255,255,0.18)" : "transparent",
                                        color: isActive ? "#FFFFFF" : "rgba(255,255,255,0.50)",
                                        fontWeight: isActive ? 600 : 400,
                                        fontSize: 13, fontFamily: "var(--font-dm-sans)",
                                        border: "none", cursor: "pointer", textAlign: "left",
                                        transition: "background 0.1s",
                                    }}
                                    onMouseEnter={e => { if (!isActive) (e.currentTarget as HTMLElement).style.background = "rgba(255,255,255,0.08)"; }}
                                    onMouseLeave={e => { if (!isActive) (e.currentTarget as HTMLElement).style.background = "transparent"; }}
                                >
                                    <Icon style={{ width: 13, height: 13, flexShrink: 0 }} />
                                    {label}
                                </button>
                            );
                        })}
                    </div>

                    <div style={{ margin: "10px 16px", height: 1, background: "rgba(255,255,255,0.12)", flexShrink: 0 }} />

                    {/* Section-specific content */}
                    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", padding: "0 10px" }}>

                        {active?.href === "/assistant" && (
                            <>
                                <button onClick={() => router.push("/assistant")}
                                    style={{
                                        display: "flex", alignItems: "center", gap: 7,
                                        padding: "7px 10px", borderRadius: 4, marginBottom: 8,
                                        background: "rgba(255,255,255,0.18)", color: "#FFFFFF",
                                        fontWeight: 600, fontSize: 13, fontFamily: "var(--font-dm-sans)",
                                        border: "none", cursor: "pointer", width: "100%",
                                    }}>
                                    <Plus style={{ width: 13, height: 13 }} /> New Chat
                                </button>
                                <button onClick={() => setHistoryCollapsed(v => !v)}
                                    style={{
                                        display: "flex", alignItems: "center", justifyContent: "space-between",
                                        padding: "0 10px", marginBottom: 4,
                                        background: "transparent", border: "none", cursor: "pointer",
                                        color: "rgba(255,255,255,0.35)", fontSize: 11, fontWeight: 600,
                                        fontFamily: "var(--font-dm-sans)", letterSpacing: "0.08em",
                                        textTransform: "uppercase", width: "100%",
                                    }}>
                                    <span>Recent</span>
                                    <ChevronDown style={{ width: 12, height: 12, transform: historyCollapsed ? "rotate(-90deg)" : "none", transition: "transform 0.2s" }} />
                                </button>
                                {!historyCollapsed && (
                                    <div style={{ overflowY: "auto", flex: 1 }}>
                                        {!chats ? (
                                            [40,60,50,70,45].map((w, i) => (
                                                <div key={i} style={{ height: 30, display: "flex", alignItems: "center", padding: "0 8px", borderRadius: 4, marginBottom: 2 }}>
                                                    <div style={{ height: 8, width: `${w}%`, background: "rgba(255,255,255,0.12)", borderRadius: 2 }} className="animate-pulse" />
                                                </div>
                                            ))
                                        ) : chats.length === 0 ? (
                                            <div style={{ fontSize: 12, color: "rgba(255,255,255,0.30)", padding: "6px 10px" }}>No chats yet</div>
                                        ) : (
                                            chats.map(chat => (
                                                <SidebarChatItem key={chat.id} chat={chat} isActive={currentChatId === chat.id}
                                                    projectName={chat.project_id ? projectNames[chat.project_id] : undefined}
                                                    onSelect={() => {
                                                        setCurrentChatId(chat.id);
                                                        router.push(chat.project_id ? `/projects/${chat.project_id}/assistant/chat/${chat.id}` : `/assistant/chat/${chat.id}`);
                                                    }} />
                                            ))
                                        )}
                                    </div>
                                )}
                            </>
                        )}

                        {active?.href === "/projects" && (
                            <button onClick={() => router.push("/projects")} style={{ display: "flex", alignItems: "center", gap: 7, padding: "7px 10px", borderRadius: 4, background: "rgba(255,255,255,0.18)", color: "#FFFFFF", fontWeight: 600, fontSize: 13, fontFamily: "var(--font-dm-sans)", border: "none", cursor: "pointer", width: "100%" }}>
                                <Plus style={{ width: 13, height: 13 }} /> New Project
                            </button>
                        )}
                        {active?.href === "/workflows" && (
                            <button onClick={() => router.push("/workflows")} style={{ display: "flex", alignItems: "center", gap: 7, padding: "7px 10px", borderRadius: 4, background: "rgba(255,255,255,0.18)", color: "#FFFFFF", fontWeight: 600, fontSize: 13, fontFamily: "var(--font-dm-sans)", border: "none", cursor: "pointer", width: "100%" }}>
                                <Plus style={{ width: 13, height: 13 }} /> New Workflow
                            </button>
                        )}
                        {active?.href === "/tabular-reviews" && (
                            <button onClick={() => router.push("/tabular-reviews")} style={{ display: "flex", alignItems: "center", gap: 7, padding: "7px 10px", borderRadius: 4, background: "rgba(255,255,255,0.18)", color: "#FFFFFF", fontWeight: 600, fontSize: 13, fontFamily: "var(--font-dm-sans)", border: "none", cursor: "pointer", width: "100%" }}>
                                <Plus style={{ width: 13, height: 13 }} /> New Review
                            </button>
                        )}
                    </div>

                    {/* User footer */}
                    <div style={{ borderTop: "1px solid rgba(255,255,255,0.12)", marginTop: "auto", flexShrink: 0, position: "relative" }}>
                        <button onClick={() => setDropdownOpen(!dropdownOpen)}
                            style={{
                                display: "flex", alignItems: "center", gap: 10, width: "100%",
                                padding: "12px 16px", background: dropdownOpen ? "rgba(255,255,255,0.10)" : "transparent",
                                border: "none", cursor: "pointer", transition: "background 0.1s",
                            }}>
                            <div style={{
                                width: 28, height: 28, borderRadius: "50%", flexShrink: 0,
                                background: "rgba(255,255,255,0.18)", color: "#FFFFFF",
                                fontSize: 12, fontWeight: 700, fontFamily: "var(--font-dm-sans)",
                                display: "flex", alignItems: "center", justifyContent: "center",
                                border: "1px solid rgba(255,255,255,0.25)",
                            }}>{initials()}</div>
                            <div style={{ flex: 1, minWidth: 0, textAlign: "left" }}>
                                <div style={{ fontSize: 13, fontWeight: 600, color: "rgba(255,255,255,0.85)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontFamily: "var(--font-dm-sans)" }}>{displayName()}</div>
                                <div style={{ fontSize: 11, color: "rgba(255,255,255,0.40)", fontFamily: "var(--font-dm-sans)" }}>{tier()}</div>
                            </div>
                            <ChevronsUpDown style={{ width: 14, height: 14, color: "rgba(255,255,255,0.30)", flexShrink: 0 }} />
                        </button>
                        {dropdownOpen && (
                            <div style={{ position: "absolute", bottom: "100%", left: 0, margin: 4, background: "#161615", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 6, padding: 4, zIndex: 50, width: "calc(100% - 8px)" }}>
                                <button onClick={() => { router.push("/account"); setDropdownOpen(false); }}
                                    style={{ display: "flex", alignItems: "center", gap: 8, width: "100%", padding: "8px 12px", background: "transparent", border: "none", cursor: "pointer", color: "rgba(255,255,255,0.70)", fontSize: 13, borderRadius: 4, fontFamily: "var(--font-dm-sans)" }}
                                    onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = "rgba(255,255,255,0.08)"}
                                    onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = "transparent"}>
                                    <User style={{ width: 14, height: 14 }} /> Account Settings
                                </button>
                            </div>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}
