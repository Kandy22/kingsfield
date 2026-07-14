"use client";

import { getApiBase } from "@/app/lib/apiBase";

import { useEffect, useState, useCallback } from "react";
import { Loader2, Sparkles, FileText, Network as NetworkIcon, Scale, Gavel, ShieldCheck, Users } from "lucide-react";
import { supabase } from "@/lib/supabase";

async function getAuthHeader(): Promise<Record<string, string>> {
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) return {};
    return { Authorization: `Bearer ${session.access_token}` };
}

// ── Types mirroring backend/src/lib/caseIntelligence.ts ────────────────────
type EntityRole = "judge" | "opposing_counsel" | "da" | "witness" | "party" | "court" | "expert" | "other";
type Novelty = "common" | "uncommon" | "novel";
interface CaseEntity { name: string; role: EntityRole; note?: string; }
interface CaseAllegation { claim: string; authorities: string[]; strength?: string | null; novelty?: Novelty | null; }
interface CaseDefense { defense: string; responds_to?: string | null; authorities: string[]; novelty?: Novelty | null; }
interface CaseAuthority { citation: string; proposition?: string; treatment?: string | null; cite_count?: number | null; }
interface CaseRarity { score: number; label: string; rationale: string; }
interface Extraction {
    id: string;
    document_id: string;
    caption: string | null;
    entities: CaseEntity[];
    allegations: CaseAllegation[];
    defenses: CaseDefense[];
    authorities: CaseAuthority[];
    rarity: CaseRarity | null;
    defense_summary: string | null;
    updated_at: string;
}
interface DocOption { id: string; filename: string; analyzed: boolean; }

const ROLE_COLORS: Record<string, string> = {
    judge: "#2B5CE6",
    opposing_counsel: "#C7341A",
    da: "#C7341A",
    witness: "#E8B121",
    expert: "#7A3FD6",
    party: "#1F8A5B",
    court: "#5B8ECC",
    other: "#8A8A84",
};

const ROLE_LABEL: Record<string, string> = {
    judge: "Judge", opposing_counsel: "Opposing counsel", da: "DA / prosecution",
    witness: "Witness", expert: "Expert", party: "Party", court: "Court", other: "Other",
};

// Column accents — the 3 color-coded categories
const CAT = {
    allegation: "#C7341A",
    authority: "#2B5CE6",
    defense: "#1F8A5B",
};

// ── Common ↔ rare clustering ────────────────────────────────────────────────
// Allegations/defenses: agent-judged novelty. Authorities: CourtListener
// citation frequency (cite_count), enriched at extraction time.
const NOVELTY_TIERS: { key: Novelty; label: string }[] = [
    { key: "common", label: "Common — boilerplate" },
    { key: "uncommon", label: "Less common — fact-specific" },
    { key: "novel", label: "Rare / novel theory" },
];

function authorityTier(a: CaseAuthority): { order: number; label: string } {
    if (a.cite_count == null) return { order: 3, label: "Rules, statutes & unresolved" };
    if (a.cite_count >= 1000) return { order: 0, label: "Landmark — 1,000+ citing opinions" };
    if (a.cite_count >= 100) return { order: 1, label: "Well-established — 100+ citing opinions" };
    return { order: 2, label: "Rarely cited — under 100" };
}

function groupBy<T>(items: T[], keyOf: (t: T) => string): [string, T[]][] {
    const m = new Map<string, T[]>();
    for (const it of items) {
        const k = keyOf(it);
        m.set(k, [...(m.get(k) ?? []), it]);
    }
    return [...m.entries()];
}

// ── The players (entities grouped by role — replaces the force graph) ──────
function PlayersRow({ entities }: { entities: CaseEntity[] }) {
    if (entities.length === 0) return null;
    const groups = groupBy(entities, (e) => e.role);
    return (
        <div>
            <div className="flex items-center gap-1.5 mb-2 label-caps text-gray-500">
                <Users className="h-3.5 w-3.5" /> The players
            </div>
            <div className="flex flex-wrap gap-x-6 gap-y-3 rounded-lg border border-gray-200 bg-gray-50 p-4">
                {groups.map(([role, list]) => (
                    <div key={role}>
                        <p className="text-[10px] font-semibold uppercase tracking-wide mb-1.5" style={{ color: ROLE_COLORS[role] ?? "#8A8A84" }}>
                            {ROLE_LABEL[role] ?? role}
                        </p>
                        <div className="flex flex-wrap gap-1.5">
                            {list.map((e, i) => (
                                <span key={i} title={e.note}
                                    className="text-xs px-2 py-1 rounded-full border bg-white text-gray-700"
                                    style={{ borderColor: `${ROLE_COLORS[e.role] ?? "#8A8A84"}55` }}>
                                    {e.name}
                                </span>
                            ))}
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}

// ── Column building blocks ──────────────────────────────────────────────────
function ColumnHeader({ color, icon: Icon, label, count }: { color: string; icon: any; label: string; count: number }) {
    return (
        <div className="flex items-center gap-1.5 pb-2 mb-3 border-b-2" style={{ borderColor: color }}>
            <Icon className="h-3.5 w-3.5" style={{ color }} />
            <span className="label-caps" style={{ color }}>
                {label} ({count})
            </span>
        </div>
    );
}

function TierLabel({ children }: { children: React.ReactNode }) {
    return (
        <p className="label-caps text-gray-400 mt-3 mb-1.5 first:mt-0" style={{ fontSize: 10 }}>
            {children}
        </p>
    );
}

function AuthorityChips({ citations, hoverAuth, setHoverAuth }: {
    citations: string[]; hoverAuth: string | null; setHoverAuth: (s: string | null) => void;
}) {
    if (citations.length === 0) return null;
    return (
        <div className="flex flex-wrap gap-1 mt-2">
            {citations.map((c, j) => (
                <span key={j} onMouseEnter={() => setHoverAuth(c)} onMouseLeave={() => setHoverAuth(null)}
                    className="text-[10px] px-1.5 py-0.5 rounded font-mono cursor-default"
                    style={{ background: "rgba(43,92,230,0.08)", color: CAT.authority }}>
                    {c.length > 30 ? c.slice(0, 28) + "…" : c}
                </span>
            ))}
        </div>
    );
}

// ── The 3-column clustered layout ───────────────────────────────────────────
function ClusterColumns({ ex }: { ex: Extraction }) {
    const [hoverAuth, setHoverAuth] = useState<string | null>(null);
    const cites = (list: string[]) => hoverAuth !== null && list.includes(hoverAuth);

    // Allegations & defenses clustered by agent-judged novelty
    function noveltyTiers<T extends { novelty?: Novelty | null }>(items: T[]) {
        const tiers = NOVELTY_TIERS
            .map((t) => ({ label: t.label, items: items.filter((i) => i.novelty === t.key) }))
            .filter((t) => t.items.length > 0);
        const unrated = items.filter((i) => !i.novelty);
        if (unrated.length > 0) {
            // Old extractions (pre-novelty) land here; re-analyze to classify.
            tiers.push({ label: tiers.length ? "Unclassified — re-analyze to rank" : "", items: unrated });
        }
        return tiers;
    }

    // Authorities clustered by CourtListener citation frequency
    const authorityTiers = groupBy(ex.authorities, (a) => String(authorityTier(a).order))
        .sort(([a], [b]) => Number(a) - Number(b))
        .map(([, items]) => ({ label: authorityTier(items[0]).label, items }));

    return (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
            {/* Allegations */}
            <div>
                <ColumnHeader color={CAT.allegation} icon={Scale} label="Allegations" count={ex.allegations.length} />
                {noveltyTiers(ex.allegations).map((tier, ti) => (
                    <div key={ti}>
                        {tier.label && <TierLabel>{tier.label}</TierLabel>}
                        <div className="space-y-2">
                            {tier.items.map((a, i) => (
                                <div key={i} className={`rounded-lg border p-3 transition-colors ${cites(a.authorities) ? "border-blue-400 bg-blue-50" : "border-gray-200 bg-gray-50"}`}>
                                    <p className="text-sm text-gray-800">{a.claim}</p>
                                    {a.strength && (
                                        <span className="inline-block mt-1.5 text-[9px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">
                                            {a.strength}
                                        </span>
                                    )}
                                    <AuthorityChips citations={a.authorities} hoverAuth={hoverAuth} setHoverAuth={setHoverAuth} />
                                </div>
                            ))}
                        </div>
                    </div>
                ))}
                {ex.allegations.length === 0 && <p className="text-xs text-gray-400">None extracted.</p>}
            </div>

            {/* Authorities (middle — the connective tissue) */}
            <div>
                <ColumnHeader color={CAT.authority} icon={Gavel} label="Authorities" count={ex.authorities.length} />
                {authorityTiers.map((tier, ti) => (
                    <div key={ti}>
                        <TierLabel>{tier.label}</TierLabel>
                        <div className="space-y-2">
                            {tier.items.map((a, i) => (
                                <div key={i} onMouseEnter={() => setHoverAuth(a.citation)} onMouseLeave={() => setHoverAuth(null)}
                                    className={`rounded-lg border p-2.5 cursor-default transition-colors ${hoverAuth === a.citation ? "border-blue-400 bg-blue-50" : "border-gray-200 bg-white"}`}>
                                    <div className="flex items-baseline justify-between gap-2">
                                        <p className="text-xs font-mono font-medium text-gray-900">{a.citation}</p>
                                        {a.cite_count != null && (
                                            <span className="text-[10px] font-mono text-gray-400 flex-shrink-0" title="Citing opinions on CourtListener">
                                                {a.cite_count.toLocaleString()}×
                                            </span>
                                        )}
                                    </div>
                                    {a.proposition && <p className="text-[11px] text-gray-500 mt-0.5 leading-snug">{a.proposition}</p>}
                                    {a.treatment && <span className="inline-block mt-1 text-[9px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">{a.treatment.replace(/_/g, " ")}</span>}
                                </div>
                            ))}
                        </div>
                    </div>
                ))}
                {ex.authorities.length === 0 && <p className="text-xs text-gray-400">None cited.</p>}
            </div>

            {/* Defenses */}
            <div>
                <ColumnHeader color={CAT.defense} icon={ShieldCheck} label="Defenses" count={ex.defenses.length} />
                {noveltyTiers(ex.defenses).map((tier, ti) => (
                    <div key={ti}>
                        {tier.label && <TierLabel>{tier.label}</TierLabel>}
                        <div className="space-y-2">
                            {tier.items.map((d, i) => (
                                <div key={i} className={`rounded-lg border p-3 transition-colors ${cites(d.authorities) ? "border-blue-400 bg-blue-50" : "border-gray-200 bg-gray-50"}`}>
                                    <p className="text-sm text-gray-800">{d.defense}</p>
                                    {d.responds_to && <p className="text-[11px] text-gray-400 mt-1 italic">↳ responds to: {d.responds_to}</p>}
                                    <AuthorityChips citations={d.authorities} hoverAuth={hoverAuth} setHoverAuth={setHoverAuth} />
                                </div>
                            ))}
                        </div>
                    </div>
                ))}
                {ex.defenses.length === 0 && <p className="text-xs text-gray-400">None extracted.</p>}
            </div>
        </div>
    );
}

export default function AnalyticsPage() {
    const [extractions, setExtractions] = useState<Extraction[]>([]);
    const [selectedId, setSelectedId] = useState<string | null>(null);
    const [docs, setDocs] = useState<DocOption[]>([]);
    const [pickDoc, setPickDoc] = useState<string>("");
    const [analyzing, setAnalyzing] = useState(false);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [focusDocumentId, setFocusDocumentId] = useState<string | null>(null);

    useEffect(() => {
        if (typeof window === "undefined") return;
        const q = new URLSearchParams(window.location.search).get("documentId");
        if (q) setFocusDocumentId(q);
    }, []);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const headers = await getAuthHeader();
            const [exRes, docRes] = await Promise.all([
                fetch(`${getApiBase()}/api/analytics`, { headers }),
                fetch(`${getApiBase()}/api/analytics/documents`, { headers }),
            ]);
            const exData = await exRes.json();
            const docData = await docRes.json();
            const list: Extraction[] = exData.extractions ?? [];
            setExtractions(list);
            setDocs(docData.documents ?? []);
            if (focusDocumentId) {
                const match = list.find((e) => e.document_id === focusDocumentId);
                if (match) setSelectedId(match.id);
                else if (list.length && !selectedId) setSelectedId(list[0].id);
            } else if (list.length && !selectedId) {
                setSelectedId(list[0].id);
            }
        } catch (e: any) {
            setError(e.message ?? "Failed to load case map");
        } finally {
            setLoading(false);
        }
    }, [selectedId, focusDocumentId]);

    useEffect(() => { void load(); }, [focusDocumentId]); // eslint-disable-line react-hooks/exhaustive-deps

    async function analyze() {
        if (!pickDoc) return;
        setAnalyzing(true);
        setError(null);
        try {
            const headers = await getAuthHeader();
            const res = await fetch(`${getApiBase()}/api/analytics/extract`, {
                method: "POST",
                headers: { "Content-Type": "application/json", ...headers },
                body: JSON.stringify({ documentId: pickDoc }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail ?? "Extraction failed");
            await load();
            setSelectedId(data.extraction.id);
            setPickDoc("");
        } catch (e: any) {
            setError(e.message ?? "Extraction failed");
        } finally {
            setAnalyzing(false);
        }
    }

    const selected = extractions.find(e => e.id === selectedId) ?? null;

    return (
        <div className="h-full overflow-y-auto bg-white">
            <div className="w-full max-w-none mx-auto px-6 py-8">
                {/* Header */}
                <div className="mb-6">
                    <div className="label-caps text-gray-400 mb-2">
                        Kingsfield · Case intelligence
                    </div>
                    <h1 className="font-serif font-light text-gray-900 dark:text-paper" style={{ fontSize: 40, lineHeight: 1.05, fontWeight: 300 }}>Case Map</h1>
                    <p className="text-sm font-light text-gray-600 mt-2 leading-relaxed max-w-none">
                        <span className="font-normal text-gray-900">What Case Map is:</span>{" "}
                        per-document extract of the matter — who&apos;s involved (judge, opposing counsel, witnesses),
                        what&apos;s alleged, what the defense is, which authorities are cited — clustered from boilerplate to novel.
                        Upload on Assistant to extract automatically; this page is the deep map, not the front door.
                        Judicial Analytics (cross-matter patterns) is Coming Soon in the left bar.
                    </p>
                </div>

                {/* Analyze toolbar */}
                <div className="flex flex-wrap items-center gap-3 mb-6 p-4 rounded-lg border border-gray-200 bg-gray-50">
                    <FileText className="h-4 w-4 text-gray-400" />
                    <select value={pickDoc} onChange={e => setPickDoc(e.target.value)}
                        className="flex-1 min-w-[200px] rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-gray-900">
                        <option value="">Select a document to analyze…</option>
                        {docs.map(d => (
                            <option key={d.id} value={d.id}>{d.filename}{d.analyzed ? "  ✓ analyzed" : ""}</option>
                        ))}
                    </select>
                    <button onClick={analyze} disabled={!pickDoc || analyzing}
                        className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-gray-900 text-white text-sm font-medium hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
                        {analyzing ? <><Loader2 className="h-4 w-4 animate-spin" /> Extracting…</> : <><Sparkles className="h-4 w-4" /> Analyze document</>}
                    </button>
                </div>

                {error && <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-700">{error}</div>}

                {loading ? (
                    <div className="flex items-center justify-center gap-2 text-sm text-gray-500 py-24">
                        <Loader2 className="h-4 w-4 animate-spin" /> Loading case intelligence…
                    </div>
                ) : extractions.length === 0 ? (
                    <div className="text-center py-20 border border-dashed border-gray-200 rounded-lg">
                        <NetworkIcon className="h-8 w-8 text-gray-300 mx-auto mb-3" />
                        <p className="text-sm font-medium text-gray-700">No case intelligence yet</p>
                        <p className="text-xs text-gray-400 mt-1 max-w-sm mx-auto">
                            Pick a document above and hit Analyze. The agent will map its entities, allegations, defenses, and authorities here.
                        </p>
                    </div>
                ) : (
                    <>
                        {/* Case selector tabs */}
                        {extractions.length > 1 && (
                            <div className="flex flex-wrap gap-2 mb-5">
                                {extractions.map(e => (
                                    <button key={e.id} onClick={() => setSelectedId(e.id)}
                                        className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${selectedId === e.id ? "border-gray-900 bg-gray-900 text-white" : "border-gray-200 text-gray-600 hover:border-gray-400"}`}>
                                        {e.caption ?? "Untitled case"}
                                    </button>
                                ))}
                            </div>
                        )}

                        {selected && (
                            <div className="space-y-6">
                                {/* Caption + rarity */}
                                <div className="flex flex-wrap items-start justify-between gap-4">
                                    <div>
                                        <h2 className="text-lg font-light text-gray-900">{selected.caption}</h2>
                                        {selected.defense_summary && <p className="text-sm text-gray-500 mt-1 max-w-2xl">{selected.defense_summary}</p>}
                                    </div>
                                    {selected.rarity && (
                                        <div className="flex-shrink-0 text-right">
                                            <div className="text-[10px] uppercase tracking-wider text-gray-400">Fact-pattern rarity</div>
                                            <div className="flex items-center gap-2 mt-1">
                                                <div className="w-28 h-1.5 rounded-full bg-gray-200 overflow-hidden">
                                                    <div className="h-full rounded-full" style={{ width: `${selected.rarity.score}%`, background: selected.rarity.score > 66 ? "#C7341A" : selected.rarity.score > 33 ? "#E8B121" : "#1F8A5B" }} />
                                                </div>
                                                <span className="text-xs font-medium text-gray-700">{selected.rarity.label}</span>
                                            </div>
                                            {selected.rarity.rationale && <p className="text-[11px] text-gray-400 mt-1 max-w-[220px]">{selected.rarity.rationale}</p>}
                                        </div>
                                    )}
                                </div>

                                {/* The players */}
                                <PlayersRow entities={selected.entities} />

                                {/* Columnar cluster — the core view */}
                                <div>
                                    <div className="flex items-center gap-1.5 mb-3 label-caps text-gray-500">
                                        <Scale className="h-3.5 w-3.5" /> Allegations · Authorities · Defenses
                                        <span className="normal-case tracking-normal font-light text-gray-400 ml-1">— clustered common → rare · hover an authority to see what it supports</span>
                                    </div>
                                    <ClusterColumns ex={selected} />
                                </div>
                            </div>
                        )}
                    </>
                )}

                {/* Coming soon / differentiators */}
                <section id="coming-soon" className="mt-12 pt-8 border-t border-gray-200 scroll-mt-8">
                    <div className="label-caps text-gray-400 mb-3">
                        Coming soon · Other options
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <ComingSoonCard
                            title="Word / WordPerfect plugin"
                            body="Research, cite, and run the Council without leaving Microsoft Word — plus WordPerfect legal tools interop (pleadings, TOA, redline/compare). Web editor ships first; desktop is export/interop."
                            ctaHref="mailto:aray.aaron@gmail.com?subject=Kingsfield%20Word%20%2F%20WordPerfect%20Plugin%20—%20Early%20Access&body=I%27d%20like%20early%20access%20to%20the%20Kingsfield%20Word%20%2F%20WordPerfect%20plugin."
                            ctaLabel="Request early access"
                        />
                        <ComingSoonCard
                            title="Judicial Analytics"
                            body="Cross-matter patterns: judges, opposing counsel, venues, and citation graphs across your portfolio — not the per-document Case Map above."
                        />
                        <ComingSoonCard
                            title="Verifier"
                            body="Hearing and video citation verification pipeline — primary-source integrity for oral proceedings."
                        />
                        <ComingSoonCard
                            title="Wingman"
                            body="Live courtroom / deposition earpiece advisor. Separate runtime; teaser until the PWA path is productized here."
                        />
                    </div>
                </section>
            </div>
        </div>
    );
}

function ComingSoonCard({
    title,
    body,
    ctaHref,
    ctaLabel,
}: {
    title: string;
    body: string;
    ctaHref?: string;
    ctaLabel?: string;
}) {
    return (
        <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50/80 p-4">
            <div className="flex items-center justify-between gap-2 mb-1.5">
                <h3 className="text-sm font-light text-gray-900">{title}</h3>
                <span className="label-caps text-gray-400 shrink-0" style={{ fontSize: 10 }}>
                    Coming soon
                </span>
            </div>
            <p className="text-xs text-gray-500 leading-relaxed">{body}</p>
            {ctaHref && ctaLabel && (
                <a
                    href={ctaHref}
                    className="inline-block mt-3 text-xs font-light text-blue-600 hover:text-blue-800"
                >
                    {ctaLabel} →
                </a>
            )}
        </div>
    );
}
