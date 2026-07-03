# HALLUCINATION PROTOCOL

> Real help. Zero bullshit.

This is the ground rule. If you only read one file in this repo, read this one.

---

## Why this exists

LLMs hallucinate citations. They invent cases, misquote opinions, and confidently cite statutes that don't say what they claim. Lawyers have been **sanctioned** for filing AI-generated briefs full of fake authority. *Mata v. Avianca* (S.D.N.Y. 2023) is the cautionary tale every operator should know — two attorneys filed a brief citing six fictional cases that ChatGPT invented, and the judge sanctioned them.

A pro se litigant who does the same thing doesn't get sanctioned. They get **dismissed with prejudice**, lose the case, and possibly owe fees. The cost of a hallucination here is your entire matter.

So: this vault treats every legal proposition as **unverified by default** and forces it through a verification chain before it can be used.

---

## The Four Gates

Nothing produced by an AI — Claude, GPT, Gemini, Llama, anything — gets into a filing, a letter, a deposition outline, or a strategy memo until it has passed all four gates.

### Gate 1 — Existence

Does this case / statute / rule actually exist?

- **Tool:** [CourtListener Citation Lookup API](https://www.courtlistener.com/help/api/rest/citation-lookup/) — explicitly built as a guardrail against hallucinated citations.
- **Backup:** Caselaw Access Project (case.law), Google Scholar, the official reporter.
- **Statutes:** the official state code site or Congress.gov / GovInfo.gov.
- **Rules:** the actual rule on the court's own website.

If the citation doesn't resolve to a real document on a primary source, **it does not exist**, no matter how confident the model sounded.

### Gate 2 — Accuracy of the Quote

Does the case / statute actually *say* what we're claiming it says?

- Pull the full text. Read the cited paragraphs.
- The quoted language must appear verbatim, in context, on the page cited.
- Paraphrases must be defensible against the actual holding, not a headnote summary.

If the quote isn't on the page, **the proposition is unsupported**.

### Gate 3 — Currency (KeyCite-equivalent)

Is this case still good law? Has the statute been amended or repealed?

- Cases: check subsequent history. CourtListener's "Cited By" view + the negative-treatment field. For high-stakes cites, cross-check on Google Scholar's "How cited."
- Statutes: confirm the version date and check the latest session laws / public laws.
- Rules: confirm the version on the court's site is current.

If a case has been overruled, vacated, or limited on the point you're citing, **note it explicitly or pick a different case**.

### Gate 4 — Jurisdiction Fit

Is this authority actually binding (or persuasive) in *our* forum?

- Mandatory authority: same jurisdiction, same or higher court, on point.
- Persuasive authority: clearly labeled as such, and chosen for a reason.
- Non-precedential / unpublished: flagged, and only used where local rules permit.

If a Ninth Circuit case is being cited in a Florida state trial court matter, **say so out loud** and explain why it's still useful.

---

## The audit trail

Every cited authority must, before it's used, be logged in [`/Sources/Cache/`](../Sources/Cache/) with:

- The full citation (Bluebook).
- Source URL.
- SHA-256 hash of the fetched document.
- Date fetched.
- Which gate(s) passed and the verifier (human name or council role).

Sample entry: [`/_System/schemas/source-record.schema.md`](./schemas/source-record.schema.md).

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
- "Bluebook" a citation it invented.
- Tell you something is "settled law" without showing the settlement.

If the model doesn't have a verified source, the correct output is: **"I can't support that. Want me to search for one?"** Not a polished paragraph with a fake cite.

---

## The one-line test

Before any AI output leaves this vault, ask:

> Could I hand this to a federal judge tomorrow and survive a Rule 11 inquiry?

If the answer is anything other than "yes, every cite is in `Sources/Cache/`," it doesn't ship.
