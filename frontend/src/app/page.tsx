"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";

/* ── Gold geometric orbit mark ──────────────────────────────────── */
function GoldMark({ size = 56 }: { size?: number }) {
    return (
        <svg width={size} height={size} viewBox="0 0 80 80" fill="none" xmlns="http://www.w3.org/2000/svg">
            <circle cx="40" cy="40" r="32" stroke="#C8A96E" strokeWidth="0.7" opacity="0.5" />
            <circle cx="40" cy="40" r="20" stroke="#C8A96E" strokeWidth="0.7" opacity="0.5" />
            <circle cx="52" cy="40" r="13" stroke="#C8A96E" strokeWidth="0.5" opacity="0.4" />
            <circle cx="28" cy="40" r="13" stroke="#C8A96E" strokeWidth="0.5" opacity="0.4" />
            <circle cx="40" cy="52" r="13" stroke="#C8A96E" strokeWidth="0.5" opacity="0.4" />
            <circle cx="40" cy="28" r="13" stroke="#C8A96E" strokeWidth="0.5" opacity="0.4" />
            <circle cx="40" cy="40" r="3" fill="#C8A96E" opacity="0.7" />
        </svg>
    );
}

/* ── Verification Gate chip ─────────────────────────────────────── */
function Gate({ label }: { label: string }) {
    return (
        <span
            className="inline-flex items-center gap-1.5 border border-[#C8A96E]/30 text-[#C8A96E]/70 px-2.5 py-1 tracking-widest"
            style={{ fontFamily: "var(--font-mono)", fontSize: "9px" }}
        >
            <span className="w-1 h-1 rounded-full bg-[#C8A96E]/60 inline-block flex-shrink-0" />
            {label}
        </span>
    );
}

export default function LandingPage() {
    return (
        <div
            className="h-screen flex flex-col overflow-hidden"
            style={{ background: "#1A1E2E" }}
        >
            {/* ── TOP NAV ─────────────────────────────────────────── */}
            <nav className="flex-none flex items-center justify-between px-8 md:px-12 pt-7 pb-3">
                <div className="flex items-center gap-3">
                    <GoldMark size={28} />
                    <span
                        className="text-[#EDE8D8]/50 tracking-[0.22em] uppercase"
                        style={{ fontFamily: "var(--font-mono)", fontSize: "10px" }}
                    >
                        Kingsfield
                    </span>
                </div>
                <div className="flex items-center gap-5">
                    <Link
                        href="/login"
                        className="text-[#EDE8D8]/45 hover:text-[#EDE8D8]/80 transition-colors tracking-[0.15em] uppercase"
                        style={{ fontFamily: "var(--font-mono)", fontSize: "10px" }}
                    >
                        Log in
                    </Link>
                    <Link
                        href="/signup"
                        className="border border-[#C8A96E]/40 text-[#C8A96E]/80 hover:border-[#C8A96E] hover:text-[#C8A96E] transition-colors px-4 py-1.5 tracking-[0.15em] uppercase"
                        style={{ fontFamily: "var(--font-mono)", fontSize: "10px" }}
                    >
                        Sign up
                    </Link>
                </div>
            </nav>

            {/* ── HERO CENTER ─────────────────────────────────────── */}
            <main className="flex-1 flex flex-col items-center justify-center px-8 text-center min-h-0">

                {/* Gold rule */}
                <div className="w-12 h-px bg-[#C8A96E]/50 mb-8" />

                {/* Eyebrow label */}
                <p
                    className="text-[#C8A96E]/60 tracking-[0.35em] uppercase mb-6"
                    style={{ fontFamily: "var(--font-mono)", fontSize: "10px" }}
                >
                    Legal AI · Open Source · AGPL-3.0
                </p>

                {/* Wordmark — Playfair Display 900 */}
                <h1
                    className="text-[#EDE8D8] leading-[0.88] tracking-tight select-none mb-5"
                    style={{
                        fontFamily: "var(--font-display)",
                        fontWeight: 900,
                        fontSize: "clamp(52px, 11vw, 148px)",
                        letterSpacing: "-0.025em",
                    }}
                >
                    Kingsfield Lawfare
                </h1>

                {/* Gold tagline */}
                <p
                    className="text-[#C8A96E] mb-5"
                    style={{
                        fontFamily: "var(--font-display)",
                        fontStyle: "italic",
                        fontWeight: 400,
                        fontSize: "clamp(16px, 2.2vw, 26px)",
                        letterSpacing: "0.01em",
                    }}
                >
                    Know the Rules. Use Them.
                </p>

                {/* Shakespeare quote */}
                <blockquote
                    className="text-[#EDE8D8]/35 mb-8 max-w-xs"
                    style={{
                        fontFamily: "var(--font-editorial)",
                        fontStyle: "italic",
                        fontSize: "clamp(12px, 1.3vw, 15px)",
                        lineHeight: "1.6",
                        letterSpacing: "0.01em",
                    }}
                >
                    "First, kill all the lawyers."
                    <span
                        className="block mt-1 not-italic text-[#EDE8D8]/20 tracking-widest"
                        style={{ fontFamily: "var(--font-mono)", fontSize: "9px" }}
                    >
                        — Shakespeare
                    </span>
                </blockquote>

                {/* Four gate chips */}
                <div className="flex flex-wrap items-center justify-center gap-2 mb-8">
                    <Gate label="EXISTENCE" />
                    <Gate label="QUOTE ACCURACY" />
                    <Gate label="CURRENCY" />
                    <Gate label="JURISDICTION FIT" />
                </div>

                {/* CTA buttons */}
                <div className="flex items-center gap-4">
                    <Link
                        href="/assistant"
                        className="flex items-center gap-2 bg-[#C8A96E] text-[#1A1E2E] hover:bg-[#E2BE82] transition-colors px-7 py-3 tracking-[0.12em] uppercase font-medium"
                        style={{ fontFamily: "var(--font-mono)", fontSize: "11px" }}
                    >
                        Enter the App <ArrowRight className="h-3 w-3" />
                    </Link>
                    <Link
                        href="/signup"
                        className="border border-[#EDE8D8]/20 text-[#EDE8D8]/55 hover:border-[#EDE8D8]/40 hover:text-[#EDE8D8]/80 transition-colors px-7 py-3 tracking-[0.12em] uppercase"
                        style={{ fontFamily: "var(--font-mono)", fontSize: "11px" }}
                    >
                        Sign up
                    </Link>
                </div>
            </main>

            {/* ── FOOTER STRIP ────────────────────────────────────── */}
            <footer
                className="flex-none flex items-center justify-between px-8 md:px-12 py-4 border-t"
                style={{ borderColor: "#EDE8D8" + "14" }}
            >
                <p
                    className="text-[#EDE8D8]/25 tracking-[0.2em] uppercase"
                    style={{ fontFamily: "var(--font-mono)", fontSize: "9px" }}
                >
                    Smart. Not Stupid.
                </p>
                <nav className="flex items-center gap-5">
                    {[
                        ["Council", "/council"],
                        ["Case Law", "/case-law"],
                        ["Legislation", "/legislation"],
                        ["GitHub", "https://github.com"],
                    ].map(([label, href]) => (
                        <Link
                            key={label}
                            href={href}
                            className="text-[#EDE8D8]/25 hover:text-[#EDE8D8]/55 transition-colors tracking-[0.15em] uppercase"
                            style={{ fontFamily: "var(--font-mono)", fontSize: "9px" }}
                        >
                            {label}
                        </Link>
                    ))}
                </nav>
                <p
                    className="text-[#EDE8D8]/20 tracking-wider"
                    style={{ fontFamily: "var(--font-mono)", fontSize: "9px" }}
                >
                    © 2026 · Not legal advice.
                </p>
            </footer>
        </div>
    );
}
