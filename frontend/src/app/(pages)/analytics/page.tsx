"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import * as d3 from "d3";

type NodeType = "judge" | "case" | "party" | "court";

interface GraphNode {
    id: string;
    label: string;
    type: NodeType;
    subtitle?: string;
    x?: number;
    y?: number;
    fx?: number | null;
    fy?: number | null;
}

interface GraphLink {
    source: string | GraphNode;
    target: string | GraphNode;
    relation: string;
}

const NODE_COLORS: Record<NodeType, string> = {
    judge:  "#2B5CE6",
    case:   "#ECECEC",
    party:  "#5B8ECC",
    court:  "#9B6FD8",
};

const NODE_RADIUS: Record<NodeType, number> = {
    judge: 14,
    case:  11,
    party:  8,
    court: 12,
};

const MOCK_NODES: GraphNode[] = [
    { id: "j1",  label: "Kavanaugh, B.",     type: "judge",  subtitle: "Associate Justice" },
    { id: "j2",  label: "Roberts, J.",       type: "judge",  subtitle: "Chief Justice" },
    { id: "j3",  label: "Jackson, K.",       type: "judge",  subtitle: "Associate Justice" },
    { id: "j4",  label: "Thomas, C.",        type: "judge",  subtitle: "Associate Justice" },
    { id: "j5",  label: "Sotomayor, S.",     type: "judge",  subtitle: "Associate Justice" },
    { id: "c1",  label: "Dobbs v. Jackson",  type: "case",   subtitle: "597 U.S. 215 (2022)" },
    { id: "c2",  label: "Bruen",             type: "case",   subtitle: "597 U.S. 1 (2022)" },
    { id: "c3",  label: "West Virginia v. EPA", type: "case", subtitle: "597 U.S. 697 (2022)" },
    { id: "c4",  label: "Moore v. Harper",   type: "case",   subtitle: "600 U.S. 1 (2023)" },
    { id: "c5",  label: "303 Creative",      type: "case",   subtitle: "600 U.S. 570 (2023)" },
    { id: "c6",  label: "Loper Bright",      type: "case",   subtitle: "603 U.S. (2024)" },
    { id: "c7",  label: "Trump v. US",       type: "case",   subtitle: "603 U.S. (2024)" },
    { id: "p1",  label: "State of MS",       type: "party" },
    { id: "p2",  label: "Jackson Women's Health", type: "party" },
    { id: "p3",  label: "EPA",               type: "party" },
    { id: "p4",  label: "NYSRPA",            type: "party" },
    { id: "p5",  label: "303 Creative LLC",  type: "party" },
    { id: "p6",  label: "Loper Bright Enter.", type: "party" },
    { id: "ct1", label: "SCOTUS",            type: "court" },
    { id: "ct2", label: "5th Circuit",       type: "court" },
    { id: "ct3", label: "2nd Circuit",       type: "court" },
];

const MOCK_LINKS: GraphLink[] = [
    { source: "j2", target: "c1", relation: "authored majority" },
    { source: "j1", target: "c2", relation: "authored majority" },
    { source: "j2", target: "c3", relation: "authored majority" },
    { source: "j2", target: "c4", relation: "authored majority" },
    { source: "j1", target: "c5", relation: "authored majority" },
    { source: "j2", target: "c6", relation: "authored majority" },
    { source: "j2", target: "c7", relation: "authored majority" },
    { source: "j4", target: "c1", relation: "concurrence" },
    { source: "j4", target: "c2", relation: "concurrence" },
    { source: "j3", target: "c6", relation: "dissent" },
    { source: "j3", target: "c7", relation: "dissent" },
    { source: "j5", target: "c1", relation: "dissent" },
    { source: "j5", target: "c3", relation: "dissent" },
    { source: "p1", target: "c1", relation: "petitioner" },
    { source: "p2", target: "c1", relation: "respondent" },
    { source: "p3", target: "c3", relation: "respondent" },
    { source: "p4", target: "c2", relation: "petitioner" },
    { source: "p5", target: "c5", relation: "petitioner" },
    { source: "p6", target: "c6", relation: "petitioner" },
    { source: "c1", target: "ct1", relation: "decided by" },
    { source: "c2", target: "ct1", relation: "decided by" },
    { source: "c3", target: "ct1", relation: "decided by" },
    { source: "c4", target: "ct1", relation: "decided by" },
    { source: "c5", target: "ct1", relation: "decided by" },
    { source: "c6", target: "ct1", relation: "decided by" },
    { source: "c7", target: "ct1", relation: "decided by" },
    { source: "c1", target: "ct2", relation: "appealed from" },
    { source: "c2", target: "ct3", relation: "appealed from" },
    { source: "c6", target: "ct2", relation: "appealed from" },
    { source: "c3", target: "c6",  relation: "overruled by" },
    { source: "c1", target: "c5",  relation: "cited in" },
    { source: "c2", target: "c5",  relation: "cited in" },
];

const FILTERS: { key: NodeType | "all"; label: string }[] = [
    { key: "all",   label: "ALL" },
    { key: "judge", label: "JUDGES" },
    { key: "case",  label: "CASES" },
    { key: "party", label: "PARTIES" },
    { key: "court", label: "COURTS" },
];

export default function AnalyticsPage() {
    const svgRef = useRef<SVGSVGElement>(null);
    const [filter, setFilter] = useState<NodeType | "all">("all");
    const [selected, setSelected] = useState<GraphNode | null>(null);
    const [connectedLinks, setConnectedLinks] = useState<GraphLink[]>([]);

    const selectNode = useCallback((node: GraphNode) => {
        setSelected(node);
        const links = MOCK_LINKS.filter(l => {
            const srcId = typeof l.source === "string" ? l.source : l.source.id;
            const tgtId = typeof l.target === "string" ? l.target : l.target.id;
            return srcId === node.id || tgtId === node.id;
        });
        setConnectedLinks(links);
    }, []);

    useEffect(() => {
        if (!svgRef.current) return;
        const svg = d3.select(svgRef.current);
        svg.selectAll("*").remove();

        const el = svgRef.current;
        const W = el.clientWidth || 800;
        const H = el.clientHeight || 600;

        const visibleTypes = filter === "all"
            ? (["judge","case","party","court"] as NodeType[])
            : [filter];

        const nodes: GraphNode[] = MOCK_NODES
            .filter(n => visibleTypes.includes(n.type))
            .map(n => ({ ...n }));

        const nodeIds = new Set(nodes.map(n => n.id));
        const links: GraphLink[] = MOCK_LINKS.filter(l => {
            const srcId = typeof l.source === "string" ? l.source : (l.source as GraphNode).id;
            const tgtId = typeof l.target === "string" ? l.target : (l.target as GraphNode).id;
            return nodeIds.has(srcId) && nodeIds.has(tgtId);
        }).map(l => ({ ...l }));

        const g = svg.append("g");

        // Zoom
        svg.call(d3.zoom<SVGSVGElement, unknown>()
            .scaleExtent([0.3, 3])
            .on("zoom", (e) => g.attr("transform", e.transform)) as any);

        const sim = d3.forceSimulation<GraphNode>(nodes)
            .force("link", d3.forceLink<GraphNode, GraphLink>(links)
                .id(d => d.id)
                .distance(d => {
                    const s = d.source as GraphNode;
                    const t = d.target as GraphNode;
                    if (s.type === "judge" && t.type === "case") return 90;
                    if (s.type === "case"  && t.type === "court") return 80;
                    return 110;
                })
                .strength(0.4))
            .force("charge", d3.forceManyBody().strength(-280))
            .force("center", d3.forceCenter(W / 2, H / 2))
            .force("collision", d3.forceCollide<GraphNode>(d => NODE_RADIUS[d.type] + 18));

        // Links
        const linkGroup = g.append("g").attr("class", "links");
        const linkEl = linkGroup.selectAll("line")
            .data(links)
            .join("line")
            .attr("stroke", "#2A2A28")
            .attr("stroke-width", 1)
            .attr("stroke-opacity", 0.7);

        // Nodes
        const nodeGroup = g.append("g").attr("class", "nodes");
        const nodeEl = nodeGroup.selectAll("g")
            .data(nodes)
            .join("g")
            .attr("cursor", "pointer")
            .call(d3.drag<SVGGElement, GraphNode>()
                .on("start", (e, d) => {
                    if (!e.active) sim.alphaTarget(0.3).restart();
                    d.fx = d.x; d.fy = d.y;
                })
                .on("drag", (e, d) => { d.fx = e.x; d.fy = e.y; })
                .on("end", (e, d) => {
                    if (!e.active) sim.alphaTarget(0);
                    d.fx = null; d.fy = null;
                }) as any)
            .on("click", (_, d) => selectNode(d));

        nodeEl.append("circle")
            .attr("r", d => NODE_RADIUS[d.type])
            .attr("fill", d => `${NODE_COLORS[d.type]}22`)
            .attr("stroke", d => NODE_COLORS[d.type])
            .attr("stroke-width", 1.5);

        nodeEl.append("text")
            .text(d => d.label.split(" ")[0])
            .attr("text-anchor", "middle")
            .attr("dy", "0.35em")
            .attr("fill", d => NODE_COLORS[d.type])
            .attr("font-size", d => d.type === "judge" ? 7 : 6)
            .attr("font-family", "IBM Plex Mono, monospace")
            .attr("pointer-events", "none");

        nodeEl.append("title").text(d => d.label);

        sim.on("tick", () => {
            linkEl
                .attr("x1", d => (d.source as GraphNode).x ?? 0)
                .attr("y1", d => (d.source as GraphNode).y ?? 0)
                .attr("x2", d => (d.target as GraphNode).x ?? 0)
                .attr("y2", d => (d.target as GraphNode).y ?? 0);

            nodeEl.attr("transform", d => `translate(${d.x ?? 0},${d.y ?? 0})`);
        });

        return () => { sim.stop(); };
    }, [filter, selectNode]);

    const getConnectedNodes = () => {
        if (!selected) return [];
        return connectedLinks.map(l => {
            const srcId = typeof l.source === "string" ? l.source : (l.source as GraphNode).id;
            const tgtId = typeof l.target === "string" ? l.target : (l.target as GraphNode).id;
            const otherId = srcId === selected.id ? tgtId : srcId;
            return { node: MOCK_NODES.find(n => n.id === otherId), relation: l.relation, direction: srcId === selected.id ? "→" : "←" };
        }).filter(x => x.node);
    };

    return (
        <div className="h-full flex flex-col" style={{ background: "#0A0A0A" }}>
            {/* Header */}
            <div className="px-6 pt-6 pb-4 flex-shrink-0" style={{ borderBottom: "1px solid #2A2A28" }}>
                <div className="text-xs font-semibold tracking-widest mb-1" style={{ color: "#717171", letterSpacing: "0.15em" }}>
                    KINGSFIELD · JUDICIAL INTELLIGENCE
                </div>
                <h1 style={{
                    fontFamily: "var(--font-bebas), 'Bebas Neue', sans-serif",
                    fontSize: 40,
                    lineHeight: 1,
                    color: "#ECECEC",
                    letterSpacing: "0.02em",
                }}>JUDICIAL CONNECTION GRAPH</h1>
                <p className="text-xs mt-1" style={{ color: "#717171" }}>
                    Map how judges, cases, parties, and courts relate. Click any node to explore its connections.
                </p>

                {/* Filter tabs */}
                <div className="flex gap-2 mt-4">
                    {FILTERS.map(f => (
                        <button
                            key={f.key}
                            onClick={() => { setFilter(f.key); setSelected(null); }}
                            className="px-3 py-1.5 rounded text-xs font-bold tracking-widest transition-all"
                            style={{
                                fontFamily: "var(--font-bebas), 'Bebas Neue', sans-serif",
                                fontSize: 12,
                                letterSpacing: "0.10em",
                                background: filter === f.key ? "#2B5CE6" : "#161615",
                                color: filter === f.key ? "#0B0B0B" : "#717171",
                                border: `1px solid ${filter === f.key ? "#2B5CE6" : "#2A2A28"}`,
                            }}
                        >
                            {f.label}
                        </button>
                    ))}

                    {/* Legend */}
                    <div className="ml-auto flex items-center gap-4">
                        {(["judge","case","party","court"] as NodeType[]).map(t => (
                            <div key={t} className="flex items-center gap-1.5">
                                <div className="w-2.5 h-2.5 rounded-full" style={{ background: NODE_COLORS[t] }} />
                                <span className="text-xs capitalize" style={{ color: "#717171" }}>{t}</span>
                            </div>
                        ))}
                    </div>
                </div>
            </div>

            {/* Graph + Side panel */}
            <div className="flex-1 flex min-h-0">
                <svg
                    ref={svgRef}
                    className="flex-1"
                    style={{ background: "#0A0A0A", cursor: "grab" }}
                />

                {selected && (
                    <div className="flex-shrink-0 flex flex-col overflow-y-auto"
                        style={{ width: 280, background: "#161615", borderLeft: "1px solid #2A2A28" }}>
                        <div className="p-5" style={{ borderBottom: "1px solid #2A2A28" }}>
                            <div className="text-xs font-semibold tracking-widest mb-2"
                                style={{ color: NODE_COLORS[selected.type], letterSpacing: "0.10em", fontFamily: "var(--font-bebas), sans-serif", fontSize: 11 }}>
                                {selected.type.toUpperCase()}
                            </div>
                            <div className="text-base font-semibold" style={{ color: "#ECECEC" }}>{selected.label}</div>
                            {selected.subtitle && (
                                <div className="text-xs mt-1" style={{ color: "#717171", fontFamily: "var(--font-ibm-plex-mono), monospace" }}>
                                    {selected.subtitle}
                                </div>
                            )}
                        </div>

                        <div className="p-5">
                            <div className="text-xs font-semibold tracking-widest mb-3"
                                style={{ color: "#717171", letterSpacing: "0.10em" }}>
                                CONNECTIONS ({connectedLinks.length})
                            </div>
                            <div className="space-y-2">
                                {getConnectedNodes().map((item, i) => item.node && (
                                    <button
                                        key={i}
                                        onClick={() => selectNode(item.node!)}
                                        className="w-full text-left rounded p-2.5 transition-all hover:bg-white/5"
                                        style={{ border: "1px solid #2A2A28" }}
                                    >
                                        <div className="flex items-center justify-between gap-2">
                                            <span className="text-xs font-medium" style={{ color: NODE_COLORS[item.node.type] }}>
                                                {item.node.label}
                                            </span>
                                            <span className="text-xs" style={{ color: "#4A4A46" }}>{item.direction}</span>
                                        </div>
                                        <div className="text-xs mt-0.5" style={{ color: "#4A4A46", fontFamily: "var(--font-ibm-plex-mono), monospace" }}>
                                            {item.relation}
                                        </div>
                                    </button>
                                ))}
                            </div>
                        </div>

                        <button
                            onClick={() => setSelected(null)}
                            className="mx-5 mb-5 mt-auto px-3 py-2 rounded text-xs transition-all"
                            style={{ border: "1px solid #2A2A28", color: "#717171" }}
                        >
                            Clear selection
                        </button>
                    </div>
                )}
            </div>
        </div>
    );
}
