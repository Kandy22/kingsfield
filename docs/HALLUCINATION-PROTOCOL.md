# The Hallucination Protocol

> Real help. Zero bullshit.

This is the doctrinal root of the entire system. The architecture, the
verification pipeline, the Council, the UI chips — all of it serves this
one document.

If you only read one thing, read this.

---

## Why this exists

LLMs hallucinate citations. They invent cases, misquote opinions, and confidently cite statutes that don't say what they claim.

The cautionary tale is *Mata v. Avianca, Inc.* (S.D.N.Y. 2023): two attorneys filed a brief citing six fictional cases that ChatGPT had invented. The judge sanctioned them. That's the BigLaw version. The pro se version is worse — a self-represented litigant who files a hallucinated cite gets dismissed with prejudice and may owe fees.

So Kingsfield treats every legal proposition as **unverified by default** and forces it through a verification chain before it can ship.

---

## The Four Gates

Nothing produced by an AI gets into a filing, a letter, a deposition outline, or a strategy memo until it has passed all four gates.

### Gate 1 — Existence

Does this case / statute / rule actually exist?

- **Primary tool:** [CourtListener Citation Lookup API](https://www.courtlistener.com/help/api/rest/) — explicitly built by Free Law Project as a guardrail against hallucinated citations.
- **Backup:** Caselaw Access Project (case.law) for older cases; Google Scholar as a cross-check; the official reporter for stubborn cases.
- **Statutes:** Congress.gov, GovInfo.gov, eCFR.gov, or the official state legislature site.
- **Rules:** the actual rule on the court's own website.

If a citation does not resolve to a real document on a primary source, **it does not exist**.

### Gate 2 — Quote Accuracy

Does the case / statute actually *say* what we're claiming it says?

- Pull the full text. Find the cited page.
- The quoted language must appear verbatim, in context, on the page cited.
- Paraphrases must be defensible against the actual holding, not a headnote.

If the quote isn't on the page, **the proposition is unsupported**.

### Gate 3 — Currency

Is this case still good law? Has the statute been amended or repealed?

- Cases: scan CourtListener's cited-by graph for negative-treatment markers (overruled, abrogated, called into doubt). Cross-check with Google Scholar's "How cited."
- Statutes: confirm the version date and check session laws / public laws.
- Rules: confirm the version on the court's site is current.

If a case has been overruled, vacated, or limited on the point you're citing, **note it explicitly or pick a different case**.

For high-stakes filings, supplement with paid Shepard's / KeyCite. The free-tier currency check is best-effort, not professional-grade.

### Gate 4 — Jurisdiction Fit

Is this authority actually binding (or persuasive) in our forum?

- Mandatory: same jurisdiction, same or higher court, on point.
- Persuasive: clearly labeled as such, with a reason it's being used.
- Non-precedential / unpublished: flagged, used only where local rules permit.

If a Ninth Circuit case is being cited in a Florida state trial court, **say so out loud** and explain why it's still useful.

---

## The audit trail

Every cited authority must be persisted in the `sources` table with:

- The full Bluebook citation.
- Source URL.
- SHA-256 hash of the fetched document.
- Date fetched + fetcher.
- Gate status per gate.
- Notes on subsequent history.

If it's not in the cache, **it's not in the brief**.

---

## What the AI is allowed to do

- Suggest authorities to look up.
- Summarize verified materials *that are already in the cache*.
- Draft language that cites *only* sources that have passed all four gates.
- Flag weak spots in our own arguments.
- Run the council protocol.

## What the AI is forbidden to do

- Cite a case from memory.
- Quote a case it has not been shown.
- Assert a rule of law without a pinpoint cite from the cache.
- Bluebook a citation it invented.
- Tell you something is "settled law" without showing the settlement.

If the model doesn't have a verified source, the correct output is:

> "I can't support that. Want me to search for one?"

Not a polished paragraph with a fake cite.

---

## The one-line test

Before any AI output leaves Kingsfield, ask:

> Could I hand this to a federal judge tomorrow and survive a Rule 11 inquiry?

If the answer is anything other than "yes, every cite is in `sources`," it doesn't ship.
