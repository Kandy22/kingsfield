/**
 * <SourceInspector>
 *
 * Drawer that opens when a user clicks any citation chip. Shows the
 * cache record with full provenance: fetch date, SHA-256 hash, fetched-by,
 * each gate's status, subsequent history, and a link to the canonical
 * source URL.
 *
 * Trust comes from being able to inspect every cite in one click.
 */

'use client';

import type { Verdict } from './CitationChip';
import { useEffect, useState } from 'react';

interface SourceRecord {
  id: string;
  citation_bluebook: string;
  short_name: string | null;
  jurisdiction: string;
  year: number | null;
  source_url: string;
  fetched_at: string;
  fetched_by: string | null;
  sha256: string;
  subsequent_history: string | null;
  currency_signal: 'green' | 'yellow' | 'red' | null;
  currency_checked_at: string | null;
}

interface Props {
  verdict: Verdict;
  onClose: () => void;
}

export function SourceInspector({ verdict, onClose }: Props) {
  const [record, setRecord] = useState<SourceRecord | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!verdict.sourceId) {
      setLoading(false);
      return;
    }
    fetch(`/api/sources/${verdict.sourceId}`)
      .then((r) => r.json())
      .then((data) => setRecord(data))
      .finally(() => setLoading(false));
  }, [verdict.sourceId]);

  return (
    <div className="fixed inset-0 z-50 flex" role="dialog">
      <div className="flex-1 bg-black/30" onClick={onClose} />
      <aside className="w-[480px] bg-white shadow-xl overflow-y-auto p-6">
        <header className="flex items-start justify-between gap-3">
          <div>
            <div className="text-xs uppercase tracking-wider text-zinc-500">
              Source Inspector
            </div>
            <h2 className="mt-1 font-serif text-xl">{verdict.citation}</h2>
          </div>
          <button
            onClick={onClose}
            className="rounded p-1 text-zinc-400 hover:text-zinc-700"
            aria-label="Close"
          >
            ✕
          </button>
        </header>

        {loading ? (
          <p className="mt-6 text-sm text-zinc-500">Loading source record…</p>
        ) : !record ? (
          <p className="mt-6 text-sm text-rose-700">
            No source record found. This citation has not been verified
            against a primary source. Treat as unverified.
          </p>
        ) : (
          <>
            <section className="mt-6 space-y-2 text-sm">
              <Field label="Jurisdiction" value={record.jurisdiction} />
              <Field label="Year" value={record.year?.toString() ?? '—'} />
              <Field
                label="Fetched"
                value={new Date(record.fetched_at).toLocaleString()}
              />
              <Field
                label="SHA-256"
                value={
                  <code className="font-mono text-xs break-all">
                    {record.sha256}
                  </code>
                }
              />
              <Field
                label="Source"
                value={
                  <a
                    href={record.source_url}
                    target="_blank"
                    rel="noreferrer"
                    className="underline"
                  >
                    {new URL(record.source_url).hostname}
                  </a>
                }
              />
            </section>

            <section className="mt-6">
              <h3 className="font-semibold text-sm mb-2">Four-Gate Status</h3>
              <Gate label="Existence" pass={verdict.gate1_existence} />
              <Gate
                label="Quote accuracy"
                pass={verdict.gate2_quote_accuracy}
                naLabel="No quote attributed"
              />
              <GateCurrency value={verdict.gate3_currency} />
              <GateJurisdiction value={verdict.gate4_jurisdiction_fit} />
            </section>

            {record.subsequent_history && (
              <section className="mt-6">
                <h3 className="font-semibold text-sm mb-2">Subsequent History</h3>
                <p className="text-sm text-zinc-700 whitespace-pre-line">
                  {record.subsequent_history}
                </p>
              </section>
            )}

            {verdict.notes.length > 0 && (
              <section className="mt-6">
                <h3 className="font-semibold text-sm mb-2">Skeptic Notes</h3>
                <ul className="list-disc pl-5 text-sm text-zinc-700 space-y-1">
                  {verdict.notes.map((n, i) => (
                    <li key={i}>{n}</li>
                  ))}
                </ul>
              </section>
            )}
          </>
        )}

        <footer className="mt-8 border-t pt-4 text-xs text-zinc-500">
          The cache is the truth. If it's not in here, it's not in the brief.
        </footer>
      </aside>
    </div>
  );
}

function Field({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="grid grid-cols-3 gap-2">
      <dt className="text-zinc-500">{label}</dt>
      <dd className="col-span-2">{value}</dd>
    </div>
  );
}

function Gate({
  label,
  pass,
  naLabel,
}: {
  label: string;
  pass: boolean | null;
  naLabel?: string;
}) {
  const text =
    pass === null ? naLabel ?? 'N/A' : pass ? 'Pass' : 'Fail';
  const color =
    pass === null
      ? 'text-zinc-500'
      : pass
        ? 'text-emerald-700'
        : 'text-rose-700';
  return (
    <div className="flex justify-between text-sm py-1 border-b last:border-0">
      <span>{label}</span>
      <span className={`font-medium ${color}`}>{text}</span>
    </div>
  );
}

function GateCurrency({
  value,
}: {
  value: 'green' | 'yellow' | 'red' | null;
}) {
  const map = {
    green: { text: 'Good law', color: 'text-emerald-700' },
    yellow: { text: 'Some negative treatment', color: 'text-amber-700' },
    red: { text: 'Negatively treated — do not rely', color: 'text-rose-700' },
  } as const;
  const v = value ? map[value] : { text: 'Not checked', color: 'text-zinc-500' };
  return (
    <div className="flex justify-between text-sm py-1 border-b">
      <span>Currency</span>
      <span className={`font-medium ${v.color}`}>{v.text}</span>
    </div>
  );
}

function GateJurisdiction({
  value,
}: {
  value: 'mandatory' | 'persuasive' | 'off-point' | null;
}) {
  const map = {
    mandatory: { text: 'Mandatory authority', color: 'text-emerald-700' },
    persuasive: { text: 'Persuasive only', color: 'text-amber-700' },
    'off-point': { text: 'Off-point — should not cite', color: 'text-rose-700' },
  } as const;
  const v = value ? map[value] : { text: 'Not assessed', color: 'text-zinc-500' };
  return (
    <div className="flex justify-between text-sm py-1">
      <span>Jurisdiction fit</span>
      <span className={`font-medium ${v.color}`}>{v.text}</span>
    </div>
  );
}
