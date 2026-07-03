# The Council of Experts

> Most people don't need a lawyer. They need clarity, leverage, and someone who knows how to think.
> The Council is the room where we do the thinking.

The Council is a structured adversarial review system. Before any significant move — a filing, a settlement decision, a deposition outline, a major strategic call — the work goes to the Council. Each role challenges it from a different angle. The point isn't consensus. The point is to find what's wrong **before** opposing counsel does.

---

## The roles

| Role | What they do | When they speak |
|---|---|---|
| **The Skeptic** | Hallucination cop. Verifies every cite against the four gates. **Hard veto power.** | Always. First. |
| **The Judge** | Applies law to facts cold. No advocacy. Tells you how a neutral on the bench would actually rule. | Every brief, every motion, every dispositive decision. |
| **Opposing Counsel** | Argues the other side as hard as possible. Finds every weakness, every counterargument, every distinguishable case. | Every filing before it goes out. |
| **The Strategist** | Asks "what's the actual goal?" and "what's the cost?" Optimizes for outcome, not for being right. | Every settlement decision, every venue choice, every discovery dispute. |
| **The Procedural Clerk** | Knows the local rules, deadlines, page limits, formatting, service requirements. Boring on purpose. | Every filing. |
| **The Evidence Master** | Tracks what's admissible, what's hearsay, what's privileged, what's authenticated. Owns the chain of custody. | Every motion that turns on facts. |
| **The Witness Coach** | Prep, cross-prep, credibility analysis. Reads transcripts for impeachment material. | Depositions and trial. |
| **The Translator** | Takes legalese out. Explains in plain English what's actually happening. | When a human needs to make a decision. |
| **The Historian** | Knows what's happened in this matter and across matters. Catches inconsistencies and patterns. | When a position is being taken; when opposing counsel reappears. |

Each role's full prompt and refusal template is in `backend/src/council/<role>.ts`.

---

## Three protocols

### Standard Session

The full review. Use for any filing, any settlement decision, any dispositive call.

1. **Charter.** Convener writes a one-paragraph charter.
2. **Materials.** All cited sources are pre-cached. Skeptic stops the session if not.
3. **Stage 1 — Skeptic pre-flight.** Every cite gets verified, conditional, or vetoed. **Vetoes pause the session until resolved.**
4. **Stage 2 — Independent passes.** Each convened role reviews silently. No cross-talk yet.
5. **Stage 3 — Cross-examination.** Strategist consolidates. Opposing Counsel and the Judge get the floor. Skeptic interrupts if a new unverified cite appears.
6. **Stage 4 — Decision memo.** Convener (the human) writes the decision. Roles' positions are recorded even when overridden.
7. **Stage 5 — Log.** Everything saved to `council_sessions` + `council_role_outputs`.

### Citation-Only Review

The lightweight version. Skeptic only. Use when a document is going outside the system but a full session is overkill (a short letter to opposing counsel, a single-cite email).

### Strategy Sanity Check

The pre-drafting protocol. Strategist + Translator + Judge. Use *before* you've written anything, while you're deciding what to do.

---

## The veto

The Skeptic has **hard veto power** on any unverified cite. No exceptions, no overrides, no "we'll fix it later." If the Skeptic says a citation hasn't passed all four gates, it comes out of the document until it has.

Every other role gets a **dissent**, not a veto. Dissents are recorded in `council_dissents` and the human convener decides.

---

## A note on what this is

The Council is not a "panel of wise AI assistants." It's a structured way of forcing yourself to look at your own work from multiple perspectives — the bench, the other side, the procedural clerk's desk — before clicking send. The roles are guardrails. The judgment is still yours.

That's how good lawyers think on their own. We're just making the steps explicit so the rest of us can think the same way.
