# Agents

> Three systems. Three jobs. Don't blur them.

Kingsfield has three distinct agent systems. Each answers a different question. If you're not sure which one to reach for, ask: *what is the user trying to do right now?*

---

## Layer 1 — The Crew (`backend/src/crew/`)

**Question it answers:** *Help me do the work.*

Four legal specialists that produce the deliverable. Run silently behind the chat assistant when a request needs more than a one-shot answer.

| Role | What they do |
|---|---|
| Researcher | Pulls authority from CourtListener, eCFR, Congress.gov. Every cite is run through the four-gate pipeline before it's offered to the next role. |
| Contract Analyst | Reads documents in the project. Flags risks, ambiguities, missing terms, compliance issues. |
| Strategist | Looks at risks, leverage, procedural posture. Suggests next steps. |
| Team Lead | Synthesizes the three above into a single coherent output. Flags where the inputs disagreed. |

**When the Crew fires:** any chat message in a project that involves drafting, analysis, or research that benefits from specialization. The user does not see "5 agents are running" — they see one assistant response, but it's been built by the crew.

**When the Crew does *not* fire:** simple lookups, factual questions, casual chat. One model can answer "what is res judicata"; you don't need a crew for that.

---

## Layer 2 — The Verification Council (`backend/src/council/`)

**Question it answers:** *Is this work safe to ship?*

Nine adversarial reviewers. The Skeptic always runs (and has hard veto). The other eight convene only when the user is about to file something or hits "Review."

| Role | When |
|---|---|
| **Skeptic** | Always. Every output. Hard veto on any cite that fails the four gates. |
| Judge, Opposing Counsel, Strategist, Procedural Clerk, Evidence Master, Witness Coach, Translator, Historian | On-demand, per the protocols in `docs/COUNCIL.md`. |

**When the Verification Council fires:** the user clicks "Review" on a draft, attempts to export a filing, or hits an explicit checkpoint in a Workflow.

**When it does *not* fire:** mid-draft. The user is still thinking. Don't interrupt with eight reviewers.

---

## Layer 3 — The LLM Council (`backend/src/llm-council/`)

**Question it answers:** *Am I working on the right thing?*

Karpathy-style 5-advisor council with peer review and a chairman. Mixed model providers (Claude + Gemini) so the diversity is real, not cosmetic.

| Advisor | Model |
|---|---|
| Contrarian | Claude (Opus) |
| First Principles | Gemini (Pro) |
| Expansionist | Claude (Sonnet) |
| Outsider | Gemini (Flash) |
| Executor | Claude (Sonnet) |

The Chairman is Claude Opus.

**When the LLM Council fires:** the user explicitly triggers it. From the sidebar's "Council" tab, or by typing one of: *"council this," "war room this," "pressure-test this," "stress-test this," "debate this,"* or a genuine "should I X or Y" question with stakes.

**When it does *not* fire:** factual questions, drafting tasks, simple yes/no. The Council is expensive — eleven model calls per session. Don't burn it on lookups.

---

## How they relate

```
Chat message
   │
   ├─ Simple question? → one model, one answer.
   │
   ├─ Production task (draft, research, analyze)? → Crew runs silently.
   │     └─ Crew output → Skeptic always runs on cites.
   │
   ├─ User clicks "Review" on a draft → Verification Council convenes.
   │
   └─ User triggers "Council this" → LLM Council convenes (separate UI).
```

The three layers don't talk to each other. The Crew doesn't summon the Verification Council; that's a separate user action. The Verification Council doesn't summon the LLM Council; the LLM Council is for human strategic decisions, not machine-to-machine review.

---

## Why this separation matters

If you collapse these into one mega-agent system, three things go wrong:

1. **Cost.** Running eleven LLM calls on every chat message is unaffordable. You need each layer to fire only when its job is actually being asked for.
2. **Latency.** Users notice. A chat that takes 30 seconds because the LLM Council is running on a "what time is it" question is a broken product.
3. **Confusion.** When everything reviews everything, no role has clear ownership. The Skeptic that vetoes citations is *the* Skeptic — not a member of three different councils with three different remits.

Keep them separate. Keep them named. Keep their triggers explicit.
