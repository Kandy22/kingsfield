"use client";

import { getApiBase } from "@/app/lib/apiBase";

import { useState } from "react";
import { ChevronDown, ChevronUp, Loader2, AlertCircle, Gavel } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { supabase } from "@/lib/supabase";

// Renders council output as formatted Markdown (headings, bold, lists) instead
// of raw ## / ** text. Element styles are set with arbitrary variants so this
// works without the @tailwindcss/typography plugin (which isn't installed).
function Prose({ children }: { children: string }) {
    return (
        <div className="text-sm leading-relaxed text-gray-800
            [&_h1]:text-lg [&_h1]:font-light [&_h1]:mt-4 [&_h1]:mb-2
            [&_h2]:text-base [&_h2]:font-light [&_h2]:mt-4 [&_h2]:mb-1.5
            [&_h3]:text-sm [&_h3]:font-normal [&_h3]:mt-3 [&_h3]:mb-1
            [&_p]:my-2 [&_strong]:font-medium [&_em]:italic
            [&_ul]:list-disc [&_ul]:pl-5 [&_ul]:my-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_ol]:my-2 [&_li]:my-0.5
            [&_hr]:my-3 [&_hr]:border-current [&_hr]:opacity-20
            [&_code]:bg-black/10 [&_code]:px-1 [&_code]:py-0.5 [&_code]:rounded [&_code]:text-[0.85em]
            [&_blockquote]:border-l-2 [&_blockquote]:border-current [&_blockquote]:opacity-90 [&_blockquote]:pl-3 [&_blockquote]:italic">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
        </div>
    );
}

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
        model: "DeepSeek V4 Pro",
        provider: "deepseek",
        description: "Strips away precedent and convention. Rebuilds from the actual rule, the actual statute, the actual text — not what everyone assumes it says.",
        accent: "#2B5CE6", // kf-prim-amber-400 — primary accent/clarity
    },
    {
        role: "expansionist",
        label: "THE EXPANSIONIST",
        model: "Gemini 3.1 Pro",
        provider: "gemini",
        description: "Widens the frame. Finds the angle no one is looking at — adjacent claims, overlooked remedies, jurisdictions where the same facts win.",
        accent: "#16A34A", // kf-prim-green-500 — growth/expansion
    },
    {
        role: "outsider",
        label: "THE OUTSIDER",
        model: "Kimi K2.6",
        provider: "kimi",
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

const PROVIDER_COLORS: Record<string, string> = {
    claude: "#C8642A",
    gemini: "#5B8ECC",
    deepseek: "#7A3FD6",
    kimi: "#1F8A5B",
};

function ProviderBadge({ provider, model }: { provider: string; model: string }) {
    const c = PROVIDER_COLORS[provider] ?? "#8A8A84";
    return (
        <span className="inline-flex items-center gap-1 font-mono font-medium px-2 py-0.5 rounded"
            style={{
                background: `${c}1F`,
                color: c,
                border: `1px solid ${c}4D`,
                fontSize: 10,
            }}>
            <span className="h-1.5 w-1.5 rounded-full" style={{ background: c }} />
            {model}
        </span>
    );
}

function AdvisorCard({ advisor, response }: { advisor: typeof ADVISORS[0]; response?: AdvisorResponse }) {
    const [expanded, setExpanded] = useState(false);
    return (
        <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 transition-all"
            style={{ borderLeft: `3px solid ${advisor.accent}` }}>
            <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap mb-1">
                        <span className="text-[13px] font-light text-gray-900 tracking-tight">
                            {advisor.label.split(" ").map(w => w[0] + w.slice(1).toLowerCase()).join(" ")}
                        </span>
                        <ProviderBadge provider={advisor.provider} model={advisor.model} />
                    </div>
                    <p className="text-xs leading-relaxed text-gray-500">{advisor.description}</p>
                </div>
                {response && (
                    <button onClick={() => setExpanded(!expanded)} className="flex-shrink-0 text-gray-400 hover:text-gray-600 transition-colors">
                        {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                    </button>
                )}
            </div>
            {response && expanded && (
                <div className="mt-3 pt-3 border-t border-gray-200">
                    <Prose>{response.text}</Prose>
                </div>
            )}
            {response && !expanded && (
                <button onClick={() => setExpanded(true)} className="mt-2 text-xs transition-colors hover:underline underline-offset-2" style={{ color: advisor.accent }}>
                    View response →
                </button>
            )}
            {!response && (
                <div className="mt-2 h-1 rounded bg-gray-200 animate-pulse" />
            )}
        </div>
    );
}

function VerdictSection({ verdict }: { verdict: string }) {
    return (
        <div className="rounded-lg bg-gray-50 p-5" style={{ border: "1px solid #2B5CE6" }}>
            <div className="flex items-center gap-2 mb-4">
                <Gavel className="h-4 w-4" style={{ color: "#2B5CE6" }} />
                <span className="label-caps" style={{ color: "#2B5CE6" }}>
                    Chairman&apos;s verdict
                </span>
                <span className="text-xs font-mono text-gray-400">· Claude Opus</span>
            </div>
            <Prose>{verdict}</Prose>
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
            const res = await fetch(`${getApiBase()}/api/council`, {
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
        <div className="h-full overflow-y-auto bg-white">
            <div className="w-full max-w-none mx-auto px-6 py-10">

                {/* ── Header ── */}
                <div className="mb-10">
                    <div className="label-caps text-gray-400 mb-3">
                        Kingsfield · Multi-model deliberation
                    </div>
                    <h1 className="font-serif font-light text-gray-900 dark:text-paper" style={{ fontSize: 48, lineHeight: 1.05, letterSpacing: "-0.03em", fontWeight: 300 }}>
                        The Council
                    </h1>
                    <div style={{ width: 40, height: 1, background: "#2B5CE6", marginTop: 16, marginBottom: 16, opacity: 0.7 }} />
                    <p className="text-sm font-light leading-relaxed max-w-none text-gray-600">
                        <span className="font-normal text-gray-900">What the Council is:</span>{" "}
                        five advisors across multiple model providers, plus a chairman. Each advisor attacks your
                        question from a different angle — then they peer-review each other before the chairman
                        synthesizes the verdict. Use it when a strategy needs adversarial pressure-testing, not for
                        routine cite lookup (use Case Law) or single-doc extract (use Assistant → Case Map).
                    </p>
                </div>

                {/* ── Advisor cards ── */}
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mb-4">
                    {ADVISORS.map(advisor => (
                        <AdvisorCard key={advisor.role} advisor={advisor} response={getAdvisorResponse(advisor.role)} />
                    ))}
                    {/* Chairman */}
                    <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 sm:col-span-2 lg:col-span-3"
                        style={{ borderLeft: "3px solid #2B5CE6" }}>
                        <div className="flex items-center gap-2 flex-wrap">
                            <Gavel className="h-4 w-4" style={{ color: "#2B5CE6" }} />
                            <span className="text-[13px] font-light text-gray-900 tracking-tight">The Chairman</span>
                            <ProviderBadge provider="claude" model="Claude Opus" />
                        </div>
                        <p className="text-xs mt-1 text-gray-500">
                            Synthesizes all five advisors + peer reviews into a single verdict. Has the final word.
                        </p>
                    </div>
                </div>

                {/* ── Input form ── */}
                {!result && (
                    <div className="rounded-lg border border-gray-200 bg-gray-50 p-5 mb-6">
                        <label className="label-caps block text-gray-500 mb-3">
                            What do you need the council to pressure-test?
                        </label>
                        <textarea
                            value={question}
                            onChange={e => setQuestion(e.target.value)}
                            placeholder="e.g. We're about to file a 12(b)(6) motion on preemption grounds. The plaintiff's complaint alleges state-law fraud arising from the same conduct as an SEC enforcement action. Do we have a strong field-preemption argument, or are we better off arguing implied conflict preemption?"
                            rows={5}
                            className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2.5 text-sm text-gray-900 placeholder-gray-400 resize-none focus:outline-none focus:ring-2 focus:ring-gray-900 focus:border-transparent"
                        />
                        <label className="label-caps block text-gray-500 mb-3 mt-5">
                            Context{" "}
                            <span className="normal-case tracking-normal font-light text-gray-400">
                                (optional — matter summary, prior filings, key facts)
                            </span>
                        </label>
                        <textarea
                            value={context}
                            onChange={e => setContext(e.target.value)}
                            placeholder="Add background the council should know — opposing counsel's arguments, the judge's tendencies, prior rulings, key facts you can't ignore..."
                            rows={3}
                            className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2.5 text-sm text-gray-900 placeholder-gray-400 resize-none focus:outline-none focus:ring-2 focus:ring-gray-900 focus:border-transparent"
                        />
                        <div className="mt-5 flex items-center justify-between flex-wrap gap-3">
                            <p className="text-xs font-mono text-gray-400">
                                11 model calls · ~30s · ~$0.40
                            </p>
                            <button
                                onClick={convene}
                                disabled={loading || question.trim().length < 10}
                                className="flex items-center gap-2 px-5 py-2.5 rounded text-[13px] font-light text-white transition-all disabled:opacity-30 disabled:cursor-not-allowed"
                                style={{ background: "#2B5CE6", letterSpacing: "0.06em" }}
                            >
                                {loading ? <><Loader2 className="h-4 w-4 animate-spin" /> Convening…</> : "Convene the council"}
                            </button>
                        </div>
                    </div>
                )}

                {error && (
                    <div className="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 p-4 mb-6">
                        <AlertCircle className="h-4 w-4 flex-shrink-0 mt-0.5 text-red-500" />
                        <div>
                            <p className="text-sm font-light text-red-700">Council failed</p>
                            <p className="text-xs mt-0.5 text-red-600">{error}</p>
                        </div>
                    </div>
                )}

                {loading && (
                    <div className="rounded-lg border border-gray-200 bg-gray-50 p-6 mb-6 text-center">
                        <Loader2 className="h-6 w-6 animate-spin mx-auto mb-3" style={{ color: "#2B5CE6" }} />
                        <p className="text-sm font-light text-gray-700">The council is deliberating…</p>
                        <p className="text-xs mt-1 text-gray-400">Running five advisors + peer review + chairman synthesis</p>
                    </div>
                )}

                {result && (
                    <div className="space-y-5">
                        <div className="rounded-lg border border-gray-200 bg-gray-50 p-4">
                            <p className="label-caps text-gray-400 mb-2">Question as framed by the council</p>
                            <Prose>{result.framedQuestion}</Prose>
                        </div>
                        <div>
                            <p className="label-caps text-gray-400 mb-3">Advisor responses</p>
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
                                className="text-sm text-gray-500 hover:text-gray-700 transition-colors hover:underline underline-offset-4"
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
