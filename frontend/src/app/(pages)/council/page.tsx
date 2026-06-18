"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp, Loader2, AlertCircle, Gavel, FileText } from "lucide-react";
import { supabase } from "@/lib/supabase";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:3001";

async function getAuthHeader(): Promise<Record<string, string>> {
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) return {};
    return { Authorization: `Bearer ${session.access_token}` };
}

interface AdvisorResponse {
    role: string;
    model: { provider: string; model: string };
    text: string;
    letter: "A" | "B" | "C" | "D" | "E";
}

interface CouncilOutput {
    framedQuestion: string;
    advisors: AdvisorResponse[];
    reviewers: { reviewerRole: string; text: string }[];
    chairmanVerdict: string;
}

// Advisor accent colors from kingsfield-tokens.css semantic palette
const ADVISORS = [
    {
        role: "contrarian",
        label: "THE CONTRARIAN",
        model: "Claude Opus",
        provider: "claude",
        description: "Finds the holes before opposing counsel does. Argues the other side without mercy. If this advisor can't break your position, you have one.",
        accent: "#DC2626", // kf-prim-red-500 — challenge/danger
    },
    {
        role: "first_principles",
        label: "FIRST PRINCIPLES",
        model: "Gemini Pro",
        provider: "gemini",
        description: "Strips away precedent and convention. Rebuilds from the actual rule, the actual statute, the actual text — not what everyone assumes it says.",
        accent: "#E09B30", // kf-prim-amber-400 — primary accent/clarity
    },
    {
        role: "expansionist",
        label: "THE EXPANSIONIST",
        model: "Claude Sonnet",
        provider: "claude",
        description: "Widens the frame. Finds the angle no one is looking at — adjacent claims, overlooked remedies, jurisdictions where the same facts win.",
        accent: "#16A34A", // kf-prim-green-500 — growth/expansion
    },
    {
        role: "outsider",
        label: "THE OUTSIDER",
        model: "Gemini Flash",
        provider: "gemini",
        description: "No priors. No institutional loyalty. No assumption that the way things are done is the way they must be done. Reads the situation cold.",
        accent: "#A09485", // kf-prim-warm-200 — neutral/cold read
    },
    {
        role: "executor",
        label: "THE EXECUTOR",
        model: "Claude Sonnet",
        provider: "claude",
        description: "Skips the theory. What to file, when to file it, in what order, with what evidence. Strategy is only real when it has a next step.",
        accent: "#A86500", // kf-prim-amber-700 — action/execute
    },
];

function ProviderBadge({ provider, model }: { provider: string; model: string }) {
    const isGemini = provider === "gemini";
    return (
        <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded"
            style={{
                background: isGemini ? "rgba(64,128,200,0.15)" : "rgba(200,100,40,0.15)",
                color: isGemini ? "#5B8ECC" : "#C8642A",
                border: `1px solid ${isGemini ? "rgba(64,128,200,0.30)" : "rgba(200,100,40,0.30)"}`,
                fontFamily: "var(--font-ibm-plex-mono), 'IBM Plex Mono', monospace",
                fontSize: 10,
            }}>
            <span className="h-1.5 w-1.5 rounded-full" style={{ background: isGemini ? "#5B8ECC" : "#C8642A" }} />
            {model}
        </span>
    );
}

function AdvisorCard({ advisor, response }: { advisor: typeof ADVISORS[0]; response?: AdvisorResponse }) {
    const [expanded, setExpanded] = useState(false);
    return (
        <div className="rounded p-4 transition-all"
            style={{
                background: "#1C190F",
                border: `1px solid #2E2A1E`,
                borderLeft: `3px solid ${advisor.accent}`,
            }}>
            <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap mb-1">
                        <span style={{
                            fontFamily: "var(--font-playfair), 'Playfair Display', Georgia, serif",
                            fontSize: 13,
                            fontWeight: 700,
                            color: "#F5F1EA",
                        }}>{advisor.label.split(" ").map(w => w[0] + w.slice(1).toLowerCase()).join(" ")}</span>
                        <ProviderBadge provider={advisor.provider} model={advisor.model} />
                    </div>
                    <p className="text-xs leading-relaxed" style={{ color: "#A09485" }}>{advisor.description}</p>
                </div>
                {response && (
                    <button onClick={() => setExpanded(!expanded)} className="flex-shrink-0 transition-colors" style={{ color: "#717171" }}>
                        {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                    </button>
                )}
            </div>
            {response && expanded && (
                <div className="mt-3 pt-3" style={{ borderTop: "1px solid #2A2A26" }}>
                    <p className="text-sm whitespace-pre-wrap leading-relaxed" style={{ color: "#ABABAB" }}>{response.text}</p>
                </div>
            )}
            {response && !expanded && (
                <button onClick={() => setExpanded(true)} className="mt-2 text-xs transition-colors hover:underline underline-offset-2" style={{ color: advisor.accent }}>
                    View response →
                </button>
            )}
            {!response && (
                <div className="mt-2 h-1 rounded animate-pulse" style={{ background: "#2A2A26" }} />
            )}
        </div>
    );
}

function VerdictSection({ verdict }: { verdict: string }) {
    return (
        <div className="rounded p-5" style={{ background: "#1C190F", border: "1px solid #E09B30" }}>
            <div className="flex items-center gap-2 mb-4">
                <Gavel className="h-4 w-4" style={{ color: "#E09B30" }} />
                <span className="font-bold tracking-widest" style={{
                    fontFamily: "var(--font-inter), Inter, sans-serif",
                    fontSize: 11,
                    fontWeight: 600,
                    color: "#E09B30",
                    letterSpacing: "0.12em",
                    textTransform: "uppercase" as const,
                }}>CHAIRMAN'S VERDICT</span>
                <span className="text-xs" style={{ color: "#717171", fontFamily: "var(--font-ibm-plex-mono), monospace" }}>· Claude Opus</span>
            </div>
            <div className="text-sm whitespace-pre-wrap leading-relaxed" style={{ color: "#ECECEC" }}>{verdict}</div>
        </div>
    );
}

export default function CouncilPage() {
    const [question, setQuestion] = useState("");
    const [context, setContext] = useState("");
    const [loading, setLoading] = useState(false);
    const [result, setResult] = useState<CouncilOutput | null>(null);
    const [error, setError] = useState<string | null>(null);

    async function convene() {
        if (!question.trim() || question.trim().length < 10) return;
        setLoading(true);
        setError(null);
        setResult(null);
        try {
            const headers = await getAuthHeader();
            const res = await fetch(`${API_BASE}/api/council`, {
                method: "POST",
                headers: { "Content-Type": "application/json", ...headers },
                body: JSON.stringify({ rawQuestion: question.trim(), context: context.trim() || undefined }),
            });
            if (!res.ok) throw new Error((await res.text()) || `Error ${res.status}`);
            setResult(await res.json() as CouncilOutput);
        } catch (e: any) {
            setError(e.message ?? "Unknown error");
        } finally {
            setLoading(false);
        }
    }

    const getAdvisorResponse = (role: string) => result?.advisors.find(a => a.role === role);

    return (
        <div className="h-full overflow-y-auto" style={{ background: "#0E0C09" }}>
            <div className="max-w-4xl mx-auto px-6 py-10">

                {/* ── Header ── */}
                <div className="mb-10">
                    <div className="text-xs font-semibold tracking-widest mb-2" style={{ color: "#717171", letterSpacing: "0.15em" }}>
                        KINGSFIELD · MULTI-MODEL DELIBERATION
                    </div>
                    <h1 style={{
                        fontFamily: "var(--font-playfair), 'Playfair Display', Georgia, serif",
                        fontSize: 56,
                        fontWeight: 900,
                        lineHeight: 1.0,
                        color: "#F5F1EA",
                        letterSpacing: "-0.03em",
                    }}>
                        The Council
                    </h1>
                    <div style={{ width: 48, height: 2, background: "#E09B30", marginTop: 16, marginBottom: 16 }} />
                    <p className="text-sm leading-relaxed max-w-2xl" style={{ color: "#ABABAB" }}>
                        Five advisors. Two model providers. One chairman. Each advisor attacks your question from a
                        different angle — then they peer-review each other before the chairman synthesizes the verdict.
                    </p>
                </div>

                {/* ── Advisor cards ── */}
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mb-4">
                    {ADVISORS.map(advisor => (
                        <AdvisorCard key={advisor.role} advisor={advisor} response={getAdvisorResponse(advisor.role)} />
                    ))}
                    {/* Chairman */}
                    <div className="rounded p-4 sm:col-span-2 lg:col-span-3"
                        style={{ background: "#1C1C1A", border: "1px solid #2A2A26", borderLeft: "3px solid #C8A96E" }}>
                        <div className="flex items-center gap-2 flex-wrap">
                            <Gavel className="h-4 w-4" style={{ color: "#E09B30" }} />
                            <span style={{
                                fontFamily: "var(--font-playfair), 'Playfair Display', Georgia, serif",
                                fontSize: 13,
                                fontWeight: 700,
                                color: "#F5F1EA",
                            }}>The Chairman</span>
                            <ProviderBadge provider="claude" model="Claude Opus" />
                        </div>
                        <p className="text-xs mt-1" style={{ color: "#717171" }}>
                            Synthesizes all five advisors + peer reviews into a single verdict. Has the final word.
                        </p>
                    </div>
                </div>

                {/* ── Word Plugin Banner ── */}
                <div className="rounded mb-8 flex items-center justify-between gap-4 px-5 py-4"
                    style={{ background: "#1C190F", border: "1px solid #2E2A1E", borderLeft: "3px solid #E09B30" }}>
                    <div className="flex items-center gap-3 min-w-0">
                        <div className="flex-shrink-0 flex items-center justify-center w-9 h-9 rounded"
                            style={{ background: "rgba(224,155,48,0.12)" }}>
                            <FileText className="h-5 w-5" style={{ color: "#E09B30" }} />
                        </div>
                        <div>
                            <div style={{
                                fontFamily: "var(--font-inter), Inter, sans-serif",
                                fontSize: 11,
                                fontWeight: 700,
                                color: "#E09B30",
                                letterSpacing: "0.12em",
                                textTransform: "uppercase",
                            }}>
                                Word Plugin — Early Access
                            </div>
                            <div className="text-xs mt-0.5" style={{ color: "#ABABAB" }}>
                                Research, cite, and run the council without leaving Microsoft Word. The gap BigLaw doesn't want you to close.
                            </div>
                        </div>
                    </div>
                    <a
                        href="#word-plugin"
                        className="flex-shrink-0 px-4 py-2 rounded text-xs font-semibold transition-all hover:opacity-80"
                        style={{ background: "#E09B30", color: "#0E0C09", whiteSpace: "nowrap", fontWeight: 600 }}
                    >
                        Get the Plugin →
                    </a>
                </div>

                {/* ── Input form ── */}
                {!result && (
                    <div className="rounded p-5 mb-6" style={{ background: "#1C1C1A", border: "1px solid #2A2A26" }}>
                        <label className="block text-xs font-semibold tracking-widest mb-3" style={{ color: "#ABABAB", letterSpacing: "0.10em" }}>
                            WHAT DO YOU NEED THE COUNCIL TO PRESSURE-TEST?
                        </label>
                        <textarea
                            value={question}
                            onChange={e => setQuestion(e.target.value)}
                            placeholder="e.g. We're about to file a 12(b)(6) motion on preemption grounds. The plaintiff's complaint alleges state-law fraud arising from the same conduct as an SEC enforcement action. Do we have a strong field-preemption argument, or are we better off arguing implied conflict preemption?"
                            rows={5}
                            className="w-full rounded px-3 py-2.5 text-sm resize-none focus:outline-none"
                            style={{ background: "#0E0C09", color: "#ECECEC", border: "1px solid #2A2A26", fontFamily: "var(--font-inter), Inter, sans-serif" }}
                        />
                        <label className="block text-xs font-semibold tracking-widest mb-3 mt-5" style={{ color: "#ABABAB", letterSpacing: "0.10em" }}>
                            CONTEXT <span className="font-normal normal-case" style={{ color: "#717171", letterSpacing: 0 }}>(optional — matter summary, prior filings, key facts)</span>
                        </label>
                        <textarea
                            value={context}
                            onChange={e => setContext(e.target.value)}
                            placeholder="Add background the council should know — opposing counsel's arguments, the judge's tendencies, prior rulings, key facts you can't ignore..."
                            rows={3}
                            className="w-full rounded px-3 py-2.5 text-sm resize-none focus:outline-none"
                            style={{ background: "#0E0C09", color: "#ECECEC", border: "1px solid #2A2A26", fontFamily: "var(--font-inter), Inter, sans-serif" }}
                        />
                        <div className="mt-5 flex items-center justify-between flex-wrap gap-3">
                            <p className="text-xs" style={{ color: "#717171", fontFamily: "var(--font-ibm-plex-mono), monospace" }}>
                                11 model calls · ~30s · ~$0.40
                            </p>
                            <button
                                onClick={convene}
                                disabled={loading || question.trim().length < 10}
                                className="flex items-center gap-2 px-5 py-2.5 rounded text-sm font-bold tracking-widest transition-all disabled:opacity-30 disabled:cursor-not-allowed"
                                style={{
                                    background: "#E09B30",
                                    color: "#0E0C09",
                                    fontFamily: "var(--font-inter), Inter, sans-serif",
                                    fontSize: 13,
                                    fontWeight: 600,
                                    letterSpacing: "0.04em",
                                }}
                            >
                                {loading ? <><Loader2 className="h-4 w-4 animate-spin" /> CONVENING…</> : "CONVENE THE COUNCIL"}
                            </button>
                        </div>
                    </div>
                )}

                {error && (
                    <div className="flex items-start gap-3 rounded p-4 mb-6" style={{ background: "#2A1515", border: "1px solid #C84040" }}>
                        <AlertCircle className="h-4 w-4 flex-shrink-0 mt-0.5" style={{ color: "#C84040" }} />
                        <div>
                            <p className="text-sm font-semibold" style={{ color: "#C84040" }}>Council failed</p>
                            <p className="text-xs mt-0.5" style={{ color: "#ABABAB" }}>{error}</p>
                        </div>
                    </div>
                )}

                {loading && (
                    <div className="rounded p-6 mb-6 text-center" style={{ background: "#1C1C1A", border: "1px solid #2A2A26" }}>
                        <Loader2 className="h-6 w-6 animate-spin mx-auto mb-3" style={{ color: "#E09B30" }} />
                        <p className="text-sm font-semibold" style={{ color: "#ABABAB" }}>The council is deliberating…</p>
                        <p className="text-xs mt-1" style={{ color: "#717171" }}>Running five advisors + peer review + chairman synthesis</p>
                    </div>
                )}

                {result && (
                    <div className="space-y-5">
                        <div className="rounded p-4" style={{ background: "#1C1C1A", border: "1px solid #2A2A26" }}>
                            <p className="text-xs font-semibold tracking-widest mb-2" style={{ color: "#717171", letterSpacing: "0.10em" }}>QUESTION AS FRAMED BY THE COUNCIL</p>
                            <p className="text-sm leading-relaxed" style={{ color: "#ABABAB" }}>{result.framedQuestion}</p>
                        </div>
                        <div>
                            <p className="text-xs font-semibold tracking-widest mb-3" style={{ color: "#717171", letterSpacing: "0.10em" }}>ADVISOR RESPONSES</p>
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                                {ADVISORS.map(advisor => (
                                    <AdvisorCard key={advisor.role} advisor={advisor} response={getAdvisorResponse(advisor.role)} />
                                ))}
                            </div>
                        </div>
                        <VerdictSection verdict={result.chairmanVerdict} />
                        <div className="text-center pt-2">
                            <button
                                onClick={() => { setResult(null); setQuestion(""); setContext(""); setError(null); }}
                                className="text-sm transition-colors hover:underline underline-offset-4"
                                style={{ color: "#717171" }}
                            >
                                Convene a new session
                            </button>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
