# Legal Books → Kingsfield Skills

**book-to-skill** converts PDFs and EPUBs into Claude Code skills that load on demand —
no hallucinated summaries, no context bloat. Each book becomes a `SKILL.md` index with
per-chapter files that the model fetches only when needed.

For Kingsfield, this means the **Crew reasons from practice guides**, not just searches
case law. The Researcher pulls statutes and opinions. The Strategist reasons from FRCP,
CACI, and the ABA Model Rules. That pairing is what BigLaw charges $800/hour to simulate.
We wire it in for free.

---

## Install book-to-skill

In any Claude Code session, run once:

```bash
/book-to-skill ~/path/to/book.pdf
```

GitHub: https://github.com/virgiliojr94/book-to-skill

The tool generates:
- `SKILL.md` — the index Claude reads first (lightweight, always loaded)
- `chapters/ch-01.md`, `ch-02.md`, … — loaded on demand when the index says so

Install generated skill directories under `backend/skills/`:

```
backend/skills/
  frcp/
    SKILL.md
    chapters/
  caci/
    SKILL.md
    chapters/
  aba-model-rules/
    SKILL.md
    chapters/
  fre/
    SKILL.md
    chapters/
  copyright/
    SKILL.md
    chapters/
```

---

## Priority Books — Free Government Sources First

These are all free. No Westlaw. No LexisNexis. Primary sources only.

### Tier 1 — Wire immediately (Crew uses these on every session)

| Book | Source | Why it matters |
|------|--------|----------------|
| **Federal Rules of Civil Procedure (FRCP)** | uscourts.gov/rules | Every federal case. Deadlines, pleading standards, discovery. The Strategist needs this on every federal matter. |
| **Federal Rules of Evidence (FRE)** | uscourts.gov/rules | Admissibility. What survives a motion in limine. The Analyst flags evidentiary problems. |
| **ABA Model Rules of Professional Conduct** | americanbar.org (free PDF) | Duty of competence re: AI (Rule 1.1). Confidentiality. Conflicts. ABA Opinion 512 hooks directly to this. |
| **Federal Rules of Appellate Procedure (FRAP)** | uscourts.gov/rules | Deadlines. Preservation. What gets reviewed de novo vs. abuse of discretion. |

### Tier 2 — Add for California / high-volume jurisdictions

| Book | Source | Why it matters |
|------|--------|----------------|
| **CACI Jury Instructions (2025 ed.)** | courts.ca.gov/caci.htm (free) | California civil jury instructions. Essential for damages analysis, tort elements, employment claims. |
| **California Rules of Court** | courts.ca.gov/rules.htm (free) | Local filing rules, formatting, deadlines. |

### Tier 3 — Creator economy / IP focus (Kingsfield's lane)

| Book | Source | Why it matters |
|------|--------|----------------|
| **Copyright in Music: A Practical Guide** | public domain + copyright.gov resources | Master vs. sync licensing, sampling, DMCA safe harbor, fair use. Core to the music/creator work. |
| **USPTO Patent Pro Se Guide** | uspto.gov (free) | Self-represented patent filers. Expands the TAM considerably. |
| **Copyright Office Circular 92 (Copyright Act)** | copyright.gov/title17 (free) | The statute itself. Researcher should pull from here for §106, §107 fair use analysis. |

---

## How It Wires Into the Crew

The Crew in `backend/src/crew/` has four roles. Skills slot in at the Researcher and
Strategist layers.

### Researcher (`backend/src/crew/researcher.ts`)

When the query involves federal court, add a skill call after the CourtListener lookup:

```typescript
// After pulling cases from CourtListener / CiteLaw:
if (query.involves('pleading') || query.involves('discovery')) {
  const frcpSkill = await loadSkill('frcp');
  context.push(await frcpSkill.lookup(query.procedural_issue));
}
```

The FRCP skill can answer: "What's the Rule 12(b)(6) standard?" without a web call.
The answer is already in `chapters/ch-12.md` — fetched in one local read.

### Strategist (`backend/src/crew/strategist.ts`)

The Strategist builds litigation strategy. Book skills give it the rules it reasons from:

```typescript
// Before drafting motion strategy:
const rules = await Promise.all([
  loadSkill('frcp').lookup('summary judgment standard'),
  loadSkill('fre').lookup('hearsay exceptions'),
]);
strategy.groundIn(rules);
```

### The Skeptic (`backend/src/council/skeptic.ts`)

The Skeptic should cross-check any procedural claim against the relevant rule skill
before clearing it through Gate 4 (jurisdiction fit). If the Strategist recommends a
motion deadline, the Skeptic pulls the FRCP chapter and verifies. This is cheap, local,
and makes the four-gate system bulletproof on procedural questions.

---

## The Differentiator Argument

Harvey: OpenAI embeddings over uploaded documents. No practice guide layer. No
procedural rule verification. The associate knows what they uploaded; they do not
inherently know FRCP.

Kingsfield Crew + book-to-skill: The Researcher searches case law. The Strategist reads
from the same FRCP, CACI, and ABA rules that BigLaw associates have on their shelves.
The Skeptic checks the rules before it signs off. Eleven model calls, two providers,
free government sources, no retainer.

The claim: "BigLaw analysis without a retainer" is only credible if the system actually
reasons from the rules, not just the cases. Book-to-skill makes that claim true.

---

## Adding New Books

1. Download the free PDF (always prefer official government / court sources)
2. Run `book-to-skill ~/Downloads/book.pdf` in a Claude Code session
3. Move generated skill directory to `backend/skills/<slug>/`
4. Register the skill slug in `backend/src/crew/skills-registry.ts` (create if absent)
5. Add a row to this table

**Never pay for a secondary source that has a free government equivalent.** If it is
a rule of court, a statute, or a regulation — the primary source is public and free.
Paying Westlaw for a formatted copy of the USC is funding the toll road.

---

## Status

| Skill | Status | Priority |
|-------|--------|----------|
| `frcp` | ⬜ Not built | P0 |
| `fre` | ⬜ Not built | P0 |
| `aba-model-rules` | ⬜ Not built | P0 |
| `frap` | ⬜ Not built | P1 |
| `caci` | ⬜ Not built | P1 |
| `ca-rules-of-court` | ⬜ Not built | P2 |
| `copyright` | ⬜ Not built | P2 |
| `uspto-pro-se` | ⬜ Not built | P3 |
