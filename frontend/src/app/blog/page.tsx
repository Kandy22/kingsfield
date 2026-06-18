import Link from "next/link";
import { ArrowLeft, ArrowRight } from "lucide-react";

const REPORTS = [
    {
        issue: "Vol. I",
        season: "Summer 2026",
        title: "The Hallucination Tax",
        subtitle: "What legal AI hallucinations actually cost — in sanctions, dismissals, and broken trust. And why the open-source stack is the only durable fix.",
        tags: ["Citation Verification", "Legal AI", "Pro Se"],
        status: "upcoming" as const,
    },
];

export default function BlogPage() {
    return (
        <div className="min-h-screen" style={{ background: "var(--kg-parchment)", fontFamily: "var(--font-body)" }}>

            {/* Header */}
            <header className="px-8 md:px-14 pt-10 pb-0 flex items-center justify-between border-b border-[#0A0A0A]/10">
                <Link
                    href="/"
                    className="flex items-center gap-2 text-[11px] tracking-[0.2em] uppercase text-[#0A0A0A]/40 hover:text-[#0A0A0A] transition-colors pb-4"
                >
                    <ArrowLeft className="h-3 w-3" /> Kingsfield
                </Link>
                <p className="text-[10px] tracking-[0.3em] uppercase text-[#0A0A0A]/30 pb-4">
                    Bi-Annual Report
                </p>
            </header>

            {/* Hero */}
            <div className="px-8 md:px-14 py-16 md:py-24 border-b border-[#0A0A0A]/10">
                <p className="text-[10px] tracking-[0.3em] uppercase text-[#C8A96E] mb-4">
                    Smart. Not Stupid.
                </p>
                <h1
                    className="text-6xl md:text-8xl lg:text-[120px] text-[#0A0A0A] leading-[0.85] mb-6"
                    style={{
                        fontFamily: "var(--font-display)",
                        letterSpacing: "-0.02em",
                    }}
                >
                    THE<br />REPORT
                </h1>
                <p
                    className="text-lg md:text-xl text-[#0A0A0A]/55 max-w-xl leading-relaxed"
                    style={{ fontFamily: "var(--font-editorial)", fontStyle: "italic" }}
                >
                    Plain-English analysis of the legal system — who it serves,
                    who it doesn't, and what you can actually do about it.
                    Published twice a year. No jargon. No softening. No sponsors.
                </p>
            </div>

            {/* Issues */}
            <div className="px-8 md:px-14 py-16">
                <div className="max-w-5xl">
                    {REPORTS.map((report) => (
                        <article
                            key={report.issue}
                            className="flex flex-col md:flex-row md:items-start gap-8 py-12 border-b border-[#0A0A0A]/10 last:border-0"
                        >
                            <div className="flex-shrink-0 w-32">
                                <p className="text-[10px] tracking-[0.2em] uppercase text-[#0A0A0A]/30 mb-1">{report.issue}</p>
                                <p className="text-xs text-[#0A0A0A]/40">{report.season}</p>
                                {report.status === "upcoming" && (
                                    <span className="inline-flex items-center gap-1 mt-2 text-[9px] tracking-[0.2em] uppercase px-2 py-0.5 border border-[#C8A96E]/40 text-[#C8A96E]">
                                        Coming Soon
                                    </span>
                                )}
                            </div>
                            <div className="flex-1">
                                <h2
                                    className="text-3xl md:text-4xl text-[#0A0A0A] mb-3 leading-tight"
                                    style={{
                                        fontFamily: "var(--font-editorial)",
                                        letterSpacing: "-0.02em"
                                    }}
                                >
                                    {report.title}
                                </h2>
                                <p
                                    className="text-base text-[#0A0A0A]/55 leading-relaxed mb-4 max-w-lg"
                                    style={{ fontFamily: "var(--font-editorial)", fontStyle: "italic" }}
                                >
                                    {report.subtitle}
                                </p>
                                <div className="flex flex-wrap gap-2">
                                    {report.tags.map((tag) => (
                                        <span
                                            key={tag}
                                            className="text-[10px] tracking-[0.15em] uppercase px-2 py-1 border border-[#0A0A0A]/15 text-[#0A0A0A]/40"
                                        >
                                            {tag}
                                        </span>
                                    ))}
                                </div>
                            </div>
                            {report.status !== "upcoming" && (
                                <div className="flex-shrink-0">
                                    <Link
                                        href={`/blog/${report.issue.toLowerCase().replace(" ", "-")}`}
                                        className="flex items-center gap-2 text-sm tracking-[0.1em] uppercase text-[#0A0A0A] border-b border-[#0A0A0A]/30 pb-0.5 hover:border-[#0A0A0A] transition-colors"
                                    >
                                        Read <ArrowRight className="h-3.5 w-3.5" />
                                    </Link>
                                </div>
                            )}
                        </article>
                    ))}

                    {/* Placeholder for future issues */}
                    <div className="py-12 border-b border-[#0A0A0A]/10">
                        <p className="text-[10px] tracking-[0.3em] uppercase text-[#0A0A0A]/20">
                            Vol. II · Winter 2027 · Title TBD
                        </p>
                    </div>
                </div>
            </div>

            {/* CTA */}
            <div className="bg-[#0A0A0A] px-8 md:px-14 py-16">
                <div className="max-w-5xl flex flex-col md:flex-row md:items-center justify-between gap-6">
                    <p
                        className="text-[#FFFFF7]/70 text-xl md:text-2xl max-w-lg leading-snug"
                        style={{ fontFamily: "var(--font-editorial)", fontStyle: "italic" }}
                    >
                        "Real help. Zero bullshit."<br />
                        <span className="text-[#FFFFF7]/30 text-base not-italic tracking-wide">
                            — Kingsfield
                        </span>
                    </p>
                    <Link
                        href="/assistant"
                        className="flex items-center gap-2 px-6 py-3 bg-[#F5F0E6] text-[#0A0A0A] text-sm tracking-[0.08em] uppercase hover:bg-[#FFFFF7] transition-colors flex-shrink-0"
                    >
                        Enter the App <ArrowRight className="h-3.5 w-3.5" />
                    </Link>
                </div>
            </div>

        </div>
    );
}
