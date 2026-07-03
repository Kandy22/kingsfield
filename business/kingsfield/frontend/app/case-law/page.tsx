'use client';

import { useState } from 'react';

const JURISDICTIONS = [
  { value: '', label: 'All jurisdictions' },
  { value: 'scotus', label: 'U.S. Supreme Court' },
  { value: 'ca1', label: '1st Circuit' },
  { value: 'ca2', label: '2nd Circuit' },
  { value: 'ca3', label: '3rd Circuit' },
  { value: 'ca4', label: '4th Circuit' },
  { value: 'ca5', label: '5th Circuit' },
  { value: 'ca6', label: '6th Circuit' },
  { value: 'ca7', label: '7th Circuit' },
  { value: 'ca8', label: '8th Circuit' },
  { value: 'ca9', label: '9th Circuit' },
  { value: 'ca10', label: '10th Circuit' },
  { value: 'ca11', label: '11th Circuit' },
  { value: 'cadc', label: 'D.C. Circuit' },
  { value: 'cafc', label: 'Federal Circuit' },
  // States included via API; this list keeps the UI tidy.
];

export default function CaseLawPage() {
  const [query, setQuery] = useState('');
  const [jurisdiction, setJurisdiction] = useState('');
  const [tab, setTab] = useState<'recent' | 'favorites'>('recent');

  function search(e: React.FormEvent) {
    e.preventDefault();
    const params = new URLSearchParams({ q: query });
    if (jurisdiction) params.set('court', jurisdiction);
    window.location.href = `/case-law/results?${params.toString()}`;
  }

  return (
    <div className="mx-auto max-w-3xl px-8 py-24">
      <h1 className="font-serif text-5xl tracking-tight">Case Law</h1>
      <p className="mt-2 text-zinc-600">
        Browse and search U.S. federal and state case law.
      </p>

      <form
        onSubmit={search}
        className="mt-8 flex items-end gap-2 rounded-2xl border border-zinc-200 bg-white p-3"
      >
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search case name, citation or keywords"
          className="flex-1 bg-transparent px-3 py-3 text-base outline-none"
        />
        <select
          value={jurisdiction}
          onChange={(e) => setJurisdiction(e.target.value)}
          className="bg-transparent px-2 text-sm text-zinc-600 outline-none"
        >
          {JURISDICTIONS.map((j) => (
            <option key={j.value} value={j.value}>
              {j.label}
            </option>
          ))}
        </select>
        <button
          type="submit"
          className="flex h-10 w-10 items-center justify-center rounded-full bg-blue-500 text-white transition hover:bg-blue-600"
          aria-label="Search"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M5 12h14M13 5l7 7-7 7" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </form>

      <p className="mt-3 text-xs text-zinc-500">
        Results pulled from CourtListener (Free Law Project). Every cite that
        ends up in your work is verified against the four-gate protocol.
      </p>

      <div className="mt-12 border-b border-zinc-200">
        <div className="flex gap-6">
          <button
            onClick={() => setTab('recent')}
            className={`pb-3 text-sm transition ${
              tab === 'recent'
                ? 'border-b-2 border-blue-500 text-blue-600'
                : 'text-zinc-600'
            }`}
          >
            Recent Cases
          </button>
          <button
            onClick={() => setTab('favorites')}
            className={`pb-3 text-sm transition ${
              tab === 'favorites'
                ? 'border-b-2 border-blue-500 text-blue-600'
                : 'text-zinc-600'
            }`}
          >
            Favorites
          </button>
        </div>
      </div>

      <RecentOrFavorites tab={tab} />
    </div>
  );
}

function RecentOrFavorites({ tab }: { tab: 'recent' | 'favorites' }) {
  // Real implementation reads from sources table where the user's recent
  // cache hits / starred records live.
  return (
    <div className="mt-8 text-sm text-zinc-500">
      {tab === 'recent'
        ? 'No recent cases yet. Start a search above.'
        : 'No favorites yet. Star a case from the source inspector.'}
    </div>
  );
}
