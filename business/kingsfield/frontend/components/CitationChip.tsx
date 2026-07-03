/**
 * <CitationChip>
 *
 * Inline component that wraps every citation rendered in chat / drafting UI.
 * Visual states:
 *   ✅ green   — verified (all four gates passed)
 *   ⚠️ yellow  — conditional (e.g., persuasive only, or yellow currency)
 *   ❌ red     — vetoed (failed Gate 1, 2, or 3 — must NOT be sent)
 *   ⏳ gray    — pending verification
 *
 * Clicking a chip opens the <SourceInspector> drawer with the cached
 * source, hash, fetch date, and full gate breakdown.
 */

'use client';

import { useState } from 'react';
import { SourceInspector } from './SourceInspector';

export type VerificationStatus = 'verified' | 'conditional' | 'vetoed' | 'pending';

export interface Verdict {
  citation: string;
  status: VerificationStatus;
  gate1_existence: boolean;
  gate2_quote_accuracy: boolean | null;
  gate3_currency: 'green' | 'yellow' | 'red' | null;
  gate4_jurisdiction_fit: 'mandatory' | 'persuasive' | 'off-point' | null;
  sourceId?: string;
  sha256?: string;
  notes: string[];
}

interface Props {
  verdict: Verdict;
}

const STYLE: Record<VerificationStatus, { bg: string; fg: string; icon: string; label: string }> = {
  verified: {
    bg: 'bg-emerald-50 hover:bg-emerald-100',
    fg: 'text-emerald-900 border-emerald-300',
    icon: '✓',
    label: 'Verified',
  },
  conditional: {
    bg: 'bg-amber-50 hover:bg-amber-100',
    fg: 'text-amber-900 border-amber-300',
    icon: '!',
    label: 'Conditional',
  },
  vetoed: {
    bg: 'bg-rose-50 hover:bg-rose-100',
    fg: 'text-rose-900 border-rose-400',
    icon: '✕',
    label: 'Vetoed',
  },
  pending: {
    bg: 'bg-zinc-50 hover:bg-zinc-100',
    fg: 'text-zinc-700 border-zinc-300',
    icon: '…',
    label: 'Pending',
  },
};

export function CitationChip({ verdict }: Props) {
  const [open, setOpen] = useState(false);
  const s = STYLE[verdict.status];

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        title={`${s.label}: ${verdict.citation}`}
        className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 font-mono text-xs ${s.bg} ${s.fg} cursor-pointer transition`}
      >
        <span aria-hidden>{s.icon}</span>
        <span>{verdict.citation}</span>
      </button>
      {open && (
        <SourceInspector verdict={verdict} onClose={() => setOpen(false)} />
      )}
    </>
  );
}

/**
 * Hallucination Banner — sits above any draft that contains vetoed cites.
 * Disables the "send" / "export" actions until resolved.
 */
export function HallucinationBanner({ verdicts }: { verdicts: Verdict[] }) {
  const vetoed = verdicts.filter((v) => v.status === 'vetoed');
  if (vetoed.length === 0) return null;

  return (
    <div className="rounded-lg border border-rose-400 bg-rose-50 p-4 text-sm text-rose-950">
      <div className="font-semibold">Skeptic veto — this draft cannot be sent.</div>
      <p className="mt-1">
        {vetoed.length} citation{vetoed.length > 1 ? 's' : ''} failed verification.
        Verify against a primary source or remove the citation. The four-gate
        protocol is non-negotiable.
      </p>
      <ul className="mt-2 list-disc pl-5">
        {vetoed.map((v) => (
          <li key={v.citation}>
            <span className="font-mono">{v.citation}</span>
            {v.notes.length > 0 && (
              <span className="text-rose-700"> — {v.notes[0]}</span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
