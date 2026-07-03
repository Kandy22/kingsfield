'use client';

import { useState } from 'react';

const SEARCH_TYPES = [
  { value: 'citation', label: 'Citation' },
  { value: 'keyword', label: 'Keyword' },
  { value: 'topic', label: 'Topic' },
];

interface Collection {
  id: string;
  title: string;
  description: string;
  href: string;
}

const FEDERAL: Collection[] = [
  {
    id: 'usc',
    title: 'U.S. Code',
    description: 'Codification of the general and permanent federal laws.',
    href: '/legislation/usc',
  },
  {
    id: 'const',
    title: 'U.S. Constitution',
    description: 'The supreme law of the United States of America.',
    href: '/legislation/constitution',
  },
  {
    id: 'cfr',
    title: 'Code of Federal Regulations',
    description: 'Codification of the rules and regulations of federal agencies.',
    href: '/legislation/cfr',
  },
];

export default function LegislationPage() {
  const [query, setQuery] = useState('');
  const [type, setType] = useState('citation');

  function search(e: React.FormEvent) {
    e.preventDefault();
    const params = new URLSearchParams({ q: query, type });
    window.location.href = `/legislation/results?${params.toString()}`;
  }

  return (
    <div className="mx-auto max-w-3xl px-8 py-24">
      <h1 className="font-serif text-5xl tracking-tight">Legislation</h1>
      <p className="mt-2 text-zinc-600">
        Browse U.S. federal and state statutes and regulations.
      </p>

      <form
        onSubmit={search}
        className="mt-8 rounded-2xl border border-zinc-200 bg-white p-3"
      >
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by citation e.g. 18 USC 1001, 26 CFR 1.61-1, Cal. Penal Code § 187"
            className="flex-1 bg-transparent px-3 py-3 text-base outline-none"
          />
          <button
            type="submit"
            className="flex h-10 w-10 items-center justify-center rounded-full bg-blue-500 text-white transition hover:bg-blue-600"
            aria-label="Search"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M5 12h14M13 5l7 7-7 7" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        </div>
        <div className="mt-1 px-3 pb-1">
          <select
            value={type}
            onChange={(e) => setType(e.target.value)}
            className="bg-transparent text-sm text-zinc-600 outline-none"
          >
            {SEARCH_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </div>
      </form>

      <p className="mt-3 text-xs text-zinc-500">
        Federal sources via Congress.gov, GovInfo.gov, and eCFR.gov. State
        sources via official state legislature sites.
      </p>

      <h2 className="mt-12 font-serif text-2xl">Federal Legislation</h2>
      <div className="mt-4 space-y-3">
        {FEDERAL.map((c) => (
          <a
            key={c.id}
            href={c.href}
            className="block rounded-2xl border border-zinc-200 bg-white p-5 transition hover:border-zinc-300 hover:shadow-sm"
          >
            <div className="font-serif text-lg">{c.title}</div>
            <div className="mt-1 text-sm text-zinc-600">{c.description}</div>
          </a>
        ))}
      </div>

      <h2 className="mt-12 font-serif text-2xl">State Legislation</h2>
      <p className="mt-2 text-sm text-zinc-500">
        Pick a state to browse its codified statutes and regulations.
      </p>
      <div className="mt-4 grid grid-cols-3 gap-3 sm:grid-cols-4">
        {US_STATES.map((s) => (
          <a
            key={s.code}
            href={`/legislation/state/${s.code.toLowerCase()}`}
            className="rounded-lg border border-zinc-200 bg-white px-3 py-2 text-center text-sm transition hover:border-zinc-300"
          >
            {s.name}
          </a>
        ))}
      </div>
    </div>
  );
}

const US_STATES = [
  { code: 'AL', name: 'Alabama' },
  { code: 'AK', name: 'Alaska' },
  { code: 'AZ', name: 'Arizona' },
  { code: 'AR', name: 'Arkansas' },
  { code: 'CA', name: 'California' },
  { code: 'CO', name: 'Colorado' },
  { code: 'CT', name: 'Connecticut' },
  { code: 'DE', name: 'Delaware' },
  { code: 'FL', name: 'Florida' },
  { code: 'GA', name: 'Georgia' },
  { code: 'HI', name: 'Hawaii' },
  { code: 'ID', name: 'Idaho' },
  { code: 'IL', name: 'Illinois' },
  { code: 'IN', name: 'Indiana' },
  { code: 'IA', name: 'Iowa' },
  { code: 'KS', name: 'Kansas' },
  { code: 'KY', name: 'Kentucky' },
  { code: 'LA', name: 'Louisiana' },
  { code: 'ME', name: 'Maine' },
  { code: 'MD', name: 'Maryland' },
  { code: 'MA', name: 'Massachusetts' },
  { code: 'MI', name: 'Michigan' },
  { code: 'MN', name: 'Minnesota' },
  { code: 'MS', name: 'Mississippi' },
  { code: 'MO', name: 'Missouri' },
  { code: 'MT', name: 'Montana' },
  { code: 'NE', name: 'Nebraska' },
  { code: 'NV', name: 'Nevada' },
  { code: 'NH', name: 'New Hampshire' },
  { code: 'NJ', name: 'New Jersey' },
  { code: 'NM', name: 'New Mexico' },
  { code: 'NY', name: 'New York' },
  { code: 'NC', name: 'North Carolina' },
  { code: 'ND', name: 'North Dakota' },
  { code: 'OH', name: 'Ohio' },
  { code: 'OK', name: 'Oklahoma' },
  { code: 'OR', name: 'Oregon' },
  { code: 'PA', name: 'Pennsylvania' },
  { code: 'RI', name: 'Rhode Island' },
  { code: 'SC', name: 'South Carolina' },
  { code: 'SD', name: 'South Dakota' },
  { code: 'TN', name: 'Tennessee' },
  { code: 'TX', name: 'Texas' },
  { code: 'UT', name: 'Utah' },
  { code: 'VT', name: 'Vermont' },
  { code: 'VA', name: 'Virginia' },
  { code: 'WA', name: 'Washington' },
  { code: 'WV', name: 'West Virginia' },
  { code: 'WI', name: 'Wisconsin' },
  { code: 'WY', name: 'Wyoming' },
];
