/**
 * Council report renderer.
 *
 * Produces a single-file HTML report after a council session. Saved to
 * the project so the user can scan, share, and revisit. The full
 * transcript is also saved as markdown alongside.
 */

import type { CouncilOutput, AdvisorResponse } from './orchestrator.js';

const ROLE_LABEL = {
  contrarian: 'Contrarian',
  first_principles: 'First principles thinker',
  expansionist: 'Expansionist',
  outsider: 'Outsider',
  executor: 'Executor',
} as const;

export function renderCouncilHTML(out: CouncilOutput, opts?: { question?: string }): string {
  const advisorsByRole = Object.fromEntries(out.advisors.map((a) => [a.role, a])) as Record<
    AdvisorResponse['role'],
    AdvisorResponse
  >;
  const ts = new Date().toISOString().replace('T', ' ').slice(0, 16);

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Council verdict — Kingsfield</title>
<style>
  :root {
    --bg: #ffffff;
    --ink: #0a0a14;
    --muted: #5f5e5a;
    --line: rgba(10,10,20,0.1);
    --accent: #0a0a14;
    --serif: ui-serif, Georgia, "Times New Roman", serif;
    --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, sans-serif;
  }
  body { background: var(--bg); color: var(--ink); font-family: var(--sans); margin: 0; line-height: 1.55; }
  main { max-width: 760px; margin: 0 auto; padding: 56px 32px; }
  .brand { font-family: var(--serif); font-size: 28px; letter-spacing: -0.02em; margin: 0 0 4px; }
  .tagline { color: var(--muted); font-size: 13px; margin: 0 0 40px; }
  .question { background: #f5f4f0; padding: 20px 24px; border-radius: 10px; margin: 0 0 40px; }
  .question .label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; margin: 0 0 8px; }
  .question p { margin: 0; font-size: 15px; }
  h1 { font-family: var(--serif); font-size: 32px; line-height: 1.2; margin: 0 0 28px; letter-spacing: -0.01em; }
  h2 { font-family: var(--serif); font-size: 22px; margin: 40px 0 16px; letter-spacing: -0.005em; }
  .verdict { font-size: 16px; }
  .verdict h2:first-child { margin-top: 0; }
  details { border-top: 0.5px solid var(--line); margin: 0; padding: 16px 0; }
  details:last-child { border-bottom: 0.5px solid var(--line); }
  summary { cursor: pointer; font-weight: 500; font-size: 14px; }
  summary::-webkit-details-marker { color: var(--muted); }
  details[open] summary { margin-bottom: 12px; }
  .advisor-meta { color: var(--muted); font-size: 12px; margin: 0 0 12px; }
  .advisor-text, .review-text { font-size: 14px; white-space: pre-wrap; }
  footer { color: var(--muted); font-size: 12px; margin: 56px 0 0; padding-top: 20px; border-top: 0.5px solid var(--line); }
  .grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; margin: 24px 0 0; }
  .pill { background: #f5f4f0; padding: 10px 8px; border-radius: 8px; text-align: center; font-size: 11px; }
  .pill .name { font-weight: 500; color: var(--ink); }
  .pill .model { color: var(--muted); margin-top: 4px; font-family: ui-monospace, monospace; }
</style>
</head>
<body>
<main>
  <p class="brand">Kingsfield</p>
  <p class="tagline">Smart. Not stupid. — LLM Council verdict</p>

  <div class="question">
    <p class="label">Framed question</p>
    <p>${escape(out.framedQuestion)}</p>
  </div>

  <div class="grid">
    ${out.advisors
      .map(
        (a) => `
      <div class="pill">
        <div class="name">${ROLE_LABEL[a.role]}</div>
        <div class="model">${a.model.provider}</div>
      </div>`,
      )
      .join('')}
  </div>

  <h1 style="margin-top: 48px;">Verdict</h1>
  <div class="verdict">${markdownLite(out.chairmanVerdict)}</div>

  <h2>Advisor responses</h2>
  ${out.advisors
    .map(
      (a) => `
    <details>
      <summary>${ROLE_LABEL[a.role]}</summary>
      <p class="advisor-meta">${a.model.provider} · ${escape(a.model.model)} · letter ${a.letter}</p>
      <div class="advisor-text">${escape(a.text)}</div>
    </details>`,
    )
    .join('')}

  <h2>Peer reviews</h2>
  ${out.reviewers
    .map(
      (r, i) => `
    <details>
      <summary>Review ${i + 1} (from ${ROLE_LABEL[r.reviewerRole]})</summary>
      <div class="review-text">${escape(r.text)}</div>
    </details>`,
    )
    .join('')}

  <footer>
    Generated ${escape(ts)} · Five advisors, peer-reviewed, chaired ·
    <a href="https://github.com/" style="color: inherit;">github</a>
  </footer>
</main>
</body>
</html>`;
}

export function renderCouncilMarkdown(out: CouncilOutput): string {
  const advisor = (a: AdvisorResponse) =>
    `### The ${ROLE_LABEL[a.role]} (${a.model.provider} · ${a.model.model})\n\n${a.text}\n`;
  return `# Council verdict

## Framed question

${out.framedQuestion}

## Verdict

${out.chairmanVerdict}

## Advisor responses

${out.advisors.map(advisor).join('\n')}

## Peer reviews

${out.reviewers
  .map(
    (r, i) => `### Review ${i + 1} — ${ROLE_LABEL[r.reviewerRole]}\n\n${r.text}\n`,
  )
  .join('\n')}
`;
}

function escape(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function markdownLite(s: string): string {
  // Very narrow renderer — handles ## headings and paragraphs. The
  // chairman output is structured and predictable.
  return escape(s)
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/\n\n+/g, '</p><p>')
    .replace(/^/, '<p>')
    .concat('</p>')
    .replace(/<p><h2>/g, '<h2>')
    .replace(/<\/h2><\/p>/g, '</h2>');
}
