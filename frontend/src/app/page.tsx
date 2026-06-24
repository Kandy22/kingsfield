"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";

/* ── Gold geometric orbit mark ──────────────────────────────────── */
function GoldMark({ size = 56 }: { size?: number }) {
    return (
        <svg width={size} height={size} viewBox="0 0 80 80" fill="none" xmlns="http://www.w3.org/2000/svg">
            <circle cx="40" cy="40" r="32" stroke="#2B5CE6" strokeWidth="0.7" opacity="0.5" />
            <circle cx="40" cy="40" r="20" stroke="#2B5CE6" strokeWidth="0.7" opacity="0.5" />
            <circle cx="52" cy="40" r="13" stroke="#2B5CE6" strokeWidth="0.5" opacity="0.4" />
            <circle cx="28" cy="40" r="13" stroke="#2B5CE6" strokeWidth="0.5" opacity="0.4" />
            <circle cx="40" cy="52" r="13" stroke="#2B5CE6" strokeWidth="0.5" opacity="0.4" />
            <circle cx="40" cy="28" r="13" stroke="#2B5CE6" strokeWidth="0.5" opacity="0.4" />
            <circle cx="40" cy="40" r="3" fill="#2B5CE6" opacity="0.7" />
        </svg>
    );
}

/* ── Verification Gate chip ─────────────────────────────────────── */
function Gate({ label }: { label: string }) {
    return (
        <span
            className="inline-flex items-center gap-1.5 border border-[#2B5CE6]/30 text-[#2B5CE6]/70 px-2.5 py-1 tracking-widest"
            style={{ fontFamily: "var(--font-jetbrains-mono)", fontSize: "9px" }}
        >
            <span className="w-1 h-1 rounded-full bg-[#2B5CE6]/60 inline-block flex-shrink-0" />
            {label}
        </span>
    );
}

export default function LandingPage() {
    return (
        <div
            className="h-screen flex flex-col overflow-hidden"
            style={{ background: "#0A0A0A" }}
        >
            {/* ── TOP NAV ─────────────────────────────────────────── */}
            <nav className="flex-none flex items-center justify-between px-8 md:px-12 pt-7 pb-3">
                <div className="flex items-center gap-3">
                    <GoldMark size={28} />
                    <span
                        className="text-[#F7F6F2]/50 tracking-[0.22em] uppercase"
                        style={{ fontFamily: "var(--font-jetbrains-mono)", fontSize: "10px" }}
                    >
                        Kingsfield
                    </span>
                </div>
                <div className="flex items-center gap-5">
                    <Link
                        href="/login"
                        className="text-[#F7F6F2]/45 hover:text-[#F7F6F2]/80 transition-colors tracking-[0.15em] uppercase"
                        style={{ fontFamily: "var(--font-jetbrains-mono)", fontSize: "10px" }}
                    >
                        Log in
                    </Link>
                    <Link
                        href="/signup"
                        className="border border-[#2B5CE6]/40 text-[#2B5CE6]/80 hover:border-[#2B5CE6] hover:text-[#2B5CE6] transition-colors px-4 py-1.5 tracking-[0.15em] uppercase"
                        style={{ fontFamily: "var(--font-jetbrains-mono)", fontSize: "10px" }}
                    >
                        Sign up
                    </Link>
                </div>
            </nav>

            {/* ── HERO CENTER ─────────────────────────────────────── */}
            <main className="flex-1 flex flex-col items-center justify-center px-8 text-center min-h-0">

                {/* Gold rule */}
                <div className="w-12 h-px bg-[#2B5CE6]/50 mb-8" />

                {/* Eyebrow label */}
                <p
                    className="text-[#2B5CE6]/60 tracking-[0.35em] uppercase mb-6"
                    style={{ fontFamily: "var(--font-jetbrains-mono)", fontSize: "10px" }}
                >
                    Legal AI · Open Source · AGPL-3.0
                </p>

                {/* Wordmark — Playfair Display 900 */}
                <h1
                    className="text-[#F7F6F2] leading-[0.88] tracking-tight select-none mb-5"
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
                    className="text-[#2B5CE6] mb-5"
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
                    className="text-[#F7F6F2]/35 mb-8 max-w-xs"
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
                        className="block mt-1 not-italic text-[#F7F6F2]/20 tracking-widest"
                        style={{ fontFamily: "var(--font-jetbrains-mono)", fontSize: "9px" }}
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
                        className="flex items-center gap-2 bg-[#2B5CE6] text-[#0A0A0A] hover:bg-[#5A7FF0] transition-colors px-7 py-3 tracking-[0.12em] uppercase font-medium"
                        style={{ fontFamily: "var(--font-jetbrains-mono)", fontSize: "11px" }}
                    >
                        Enter the App <ArrowRight className="h-3 w-3" />
                    </Link>
                    <Link
                        href="/signup"
                        className="border border-[#F7F6F2]/20 text-[#F7F6F2]/55 hover:border-[#F7F6F2]/40 hover:text-[#F7F6F2]/80 transition-colors px-7 py-3 tracking-[0.12em] uppercase"
                        style={{ fontFamily: "var(--font-jetbrains-mono)", fontSize: "11px" }}
                    >
                        Sign up
                    </Link>
                </div>
            </main>

            {/* ── FOOTER STRIP ────────────────────────────────────── */}
            <footer
                className="flex-none flex items-center justify-between px-8 md:px-12 py-4 border-t"
                style={{ borderColor: "#F7F6F2" + "14" }}
            >
                <p
                    className="text-[#F7F6F2]/25 tracking-[0.2em] uppercase"
                    style={{ fontFamily: "var(--font-jetbrains-mono)", fontSize: "9px" }}
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
                            className="text-[#F7F6F2]/25 hover:text-[#F7F6F2]/55 transition-colors tracking-[0.15em] uppercase"
                            style={{ fontFamily: "var(--font-jetbrains-mono)", fontSize: "9px" }}
                        >
                            {label}
                        </Link>
                    ))}
                </nav>
                <p
                    className="text-[#F7F6F2]/20 tracking-wider"
                    style={{ fontFamily: "var(--font-jetbrains-mono)", fontSize: "9px" }}
                >
                    © 2026 · Not legal advice.
                </p>
            </footer>
        </div>
    );
}
