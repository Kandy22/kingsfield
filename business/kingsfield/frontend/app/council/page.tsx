'use client';

import { useState } from 'react';

interface CouncilSession {
  id: string;
  framedQuestion: string;
  advisors: any[];
  reviewers: any[];
  chairmanVerdict: string;
}

const ADVISORS = [
  { role: 'contrarian', name: 'The Contrarian', model: 'Claude Opus' },
  { role: 'first_principles', name: 'First Principles', model: 'Gemini Pro' },
  { role: 'expansionist', name: 'The Expansionist', model: 'Claude Sonnet' },
  { role: 'outsider', name: 'The Outsider', model: 'Gemini Flash' },
  { role: 'executor', name: 'The Executor', model: 'Claude Sonnet' },
];

export default function CouncilPage() {
  const [question, setQuestion] = useState('');
  const [context, setContext] = useState('');
  const [running, setRunning] = useState(false);
  const [stage, setStage] = useState<'idle' | 'framing' | 'advisors' | 'review' | 'chairman'>('idle');
  const [session, setSession] = useState<CouncilSession | null>(null);

  async function run() {
    if (question.trim().length < 20) return;
    setRunning(true);
    setStage('framing');
    setSession(null);
    try {
      // In practice, the backend streams stage events back over SSE so the
      // user can watch advisors finish. This is the synchronous fallback.
      const res = await fetch('/api/council', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ rawQuestion: question, context }),
      });
      const data = await res.json();
      setSession(data);
      setStage('idle');
    } catch (e) {
      console.error(e);
      setStage('idle');
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl px-8 py-16">
      <h1 className="font-serif text-5xl tracking-tight">Council</h1>
      <p className="mt-2 text-zinc-600">
        Run a decision through five advisors, peer-reviewed and chaired. For
        questions where being wrong is expensive.
      </p>

      <div className="mt-8 grid grid-cols-5 gap-2">
        {ADVISORS.map((a) => (
          <div
            key={a.role}
            className="rounded-lg bg-zinc-50 px-3 py-3 text-center"
          >
            <div className="text-xs font-medium">{a.name}</div>
            <div className="mt-1 font-mono text-[10px] text-zinc-500">
              {a.model}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-10">
        <label className="text-sm text-zinc-600">The question</label>
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Should I file a motion to dismiss or just answer? Cost is roughly the same either way; we have strong 12(b)(6) grounds on count II but it telegraphs the weakness in the contract claim..."
          className="mt-2 h-36 w-full rounded-2xl border border-zinc-200 bg-white p-4 text-base outline-none focus:border-zinc-400"
        />

        <label className="mt-4 block text-sm text-zinc-600">
          Context (optional — paste matter summary, prior filings, or relevant facts)
        </label>
        <textarea
          value={context}
          onChange={(e) => setContext(e.target.value)}
          className="mt-2 h-24 w-full rounded-2xl border border-zinc-200 bg-white p-4 text-sm outline-none focus:border-zinc-400"
        />

        <div className="mt-4 flex items-center justify-between">
          <p className="text-xs text-zinc-500">
            Eleven model calls per session (~30s, ~$0.40 with current pricing).
          </p>
          <button
            onClick={run}
            disabled={running || question.trim().length < 20}
            className="rounded-full bg-zinc-900 px-6 py-2 text-sm font-medium text-white transition hover:bg-zinc-700 disabled:bg-zinc-300"
          >
            {running ? 'Running…' : 'Convene the council'}
          </button>
        </div>
      </div>

      {running && (
        <div className="mt-10 rounded-2xl border border-zinc-200 p-6">
          <p className="text-sm font-medium">Stage: {stage}</p>
          <ul className="mt-3 space-y-1 text-sm text-zinc-600">
            <li className={stage === 'framing' ? 'font-medium text-zinc-900' : ''}>
              1. Framing the question…
            </li>
            <li className={stage === 'advisors' ? 'font-medium text-zinc-900' : ''}>
              2. Advisors writing in parallel…
            </li>
            <li className={stage === 'review' ? 'font-medium text-zinc-900' : ''}>
              3. Anonymized peer review…
            </li>
            <li className={stage === 'chairman' ? 'font-medium text-zinc-900' : ''}>
              4. Chairman synthesizing…
            </li>
          </ul>
        </div>
      )}

      {session && <CouncilVerdict session={session} />}
    </div>
  );
}

function CouncilVerdict({ session }: { session: CouncilSession }) {
  return (
    <div className="mt-10 space-y-8">
      <div>
        <p className="text-xs uppercase tracking-wider text-zinc-500">
          Framed question
        </p>
        <p className="mt-2 rounded-2xl bg-zinc-50 p-5 text-sm">
          {session.framedQuestion}
        </p>
      </div>

      <div>
        <h2 className="font-serif text-2xl">Verdict</h2>
        <div className="mt-3 whitespace-pre-wrap text-sm leading-relaxed">
          {session.chairmanVerdict}
        </div>
      </div>

      <details className="border-t border-zinc-200 pt-4">
        <summary className="cursor-pointer text-sm font-medium">
          Advisor responses
        </summary>
        <div className="mt-4 space-y-6">
          {session.advisors.map((a, i) => (
            <div key={i}>
              <div className="text-sm font-medium">
                {ADVISORS.find((x) => x.role === a.role)?.name ?? a.role}
              </div>
              <div className="mt-1 font-mono text-xs text-zinc-500">
                {a.model.provider} · {a.model.model}
              </div>
              <p className="mt-2 whitespace-pre-wrap text-sm text-zinc-700">{a.text}</p>
            </div>
          ))}
        </div>
      </details>

      <details className="border-t border-zinc-200 pt-4">
        <summary className="cursor-pointer text-sm font-medium">
          Peer reviews
        </summary>
        <div className="mt-4 space-y-6">
          {session.reviewers.map((r: any, i: number) => (
            <div key={i}>
              <div className="text-sm font-medium">Review {i + 1}</div>
              <p className="mt-2 whitespace-pre-wrap text-sm text-zinc-700">{r.text}</p>
            </div>
          ))}
        </div>
      </details>
    </div>
  );
}
