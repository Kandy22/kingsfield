---
name: llm-council
description: "Run any question, idea, or decision through a council of 5 AI advisors who independently analyze it, peer-review each other anonymously, and synthesize a final verdict. Based on Karpathy's LLM Council methodology. MANDATORY TRIGGERS: 'council this', 'run the council', 'war room this', 'pressure-test this', 'stress-test this', 'debate this'. STRONG TRIGGERS (use when combined with a real decision or tradeoff): 'should I X or Y', 'which option', 'what would you do', 'is this the right move', 'validate this', 'get multiple perspectives', 'I can't decide', 'I'm torn between'. Do NOT trigger on simple yes/no questions, factual lookups, or casual 'should I' without a meaningful tradeoff (e.g. 'should I use markdown' is not a council question). DO trigger when the user presents a genuine decision with stakes, multiple options, and context that suggests they want it pressure-tested from multiple angles."
---

# LLM Council

Five advisors, peer-reviewed, chaired. Used when being wrong is expensive.

This skill is the local-first version of the Council that ships in the
Kingsfield product. When you run it via Claude Code, it operates against
the workspace files. When the product runs it, it operates against the
project's matter context. Same five-advisor logic, same peer-review step,
same chairman synthesis.

## The five advisors

| Advisor | Thinking style | Default model |
|---|---|---|
| The Contrarian | Adversarial. Finds the fatal flaw. Plays Devil's Advocate. | Claude Opus |
| First Principles | Strips assumptions. Looks at jurisdictional + procedural roots. | Gemini Pro |
| The Expansionist | Upside, additional defendants, additional theories. | Claude Sonnet |
| The Outsider | Fresh eyes. Common-sense reader. The judge's clerk. | Gemini Flash |
| The Executor | Monday-morning concrete. What's the first filing? | Claude Sonnet |

Five different prompts × different models = real diversity, not five
Claudes wearing hats.

## When to run

**Good council questions:**
- "Should I file MTD or answer?"
- "Settle for $40K or push to summary judgment?"
- "Which of these three positioning angles is strongest?"
- "Is this complaint going to survive Twombly?"

**Bad council questions:**
- "What's res judicata?" (factual lookup — one model answers)
- "Draft a motion to dismiss." (production task — that's the Crew)
- "Hi" (no.)

The Council is for genuine uncertainty with stakes. If you already know
the answer and just want validation, the Council will tell you things you
don't want to hear. That's the point.

## How a session runs

### Step 1 — Frame the question (with context enrichment)

When the user says "council this" (or any trigger phrase), do two things:

**A. Scan the workspace for context.** Quickly read any obviously relevant
files — `CLAUDE.md`, `memory/`, prior council transcripts, the matter's
`Strategy/` folder. Use `Glob` and short `Read` calls. Spend < 30 seconds.
The point is to give advisors enough context for specific, grounded
takes, not generic ones.

**B. Frame the question.** Reframe the user's raw input + the enriched
context as a clear, neutral prompt. Include:
1. Core decision or question
2. Key context from the user
3. Key context from workspace files
4. What's at stake

Don't add opinion. Don't steer. Save the framed question for the transcript.

### Step 2 — Convene the advisors (parallel)

Spawn all 5 advisors simultaneously. Each gets:
1. Their advisor identity and thinking style
2. The framed question
3. The instruction to lean fully into their assigned perspective

150-300 words each. No preamble.

### Step 3 — Peer review (parallel, anonymized)

Anonymize the 5 responses as A-E (random mapping per session). Spawn 5
new sub-agents — same advisor roles, but reading the anonymized set —
and have each answer:
1. Which response is strongest? Why?
2. Which has the biggest blind spot? What is it?
3. What did ALL responses miss?

< 200 words each.

### Step 4 — Chairman synthesis

One agent gets everything: the framed question, all 5 advisor responses
(de-anonymized), all 5 peer reviews. Output structure:

  ## Where the council agrees
  ## Where the council clashes
  ## Blind spots the council caught
  ## The recommendation
  ## The one thing to do first

### Step 5 — Save artifacts

Two files saved to the project:

  council-report-<timestamp>.html       # visual report
  council-transcript-<timestamp>.md     # full transcript

The HTML is what most users will read. The transcript is the audit trail.

## Important notes

- Always spawn advisors in parallel. Sequential lets earlier responses
  bleed into later ones.
- Always anonymize for peer review. Otherwise reviewers defer to the
  thinking style they trust most instead of evaluating on merit.
- The Chairman can disagree with the majority. If 4 advisors say "do it"
  but the dissenter's reasoning is strongest, the Chairman sides with
  the dissenter and says why.
- Don't council trivial questions. If there's one right answer, just
  answer it. The Council is for genuine uncertainty.
- The HTML report matters. Most people scan it; few read the full
  transcript. Keep the report clean and scannable.

## Output reference

The transcript template, the HTML structure, and the exact advisor
prompts live in `backend/src/llm-council/` for the production
implementation. When running this skill directly via Claude Code, use
the prompts in `prompts.ts` — they're the source of truth.
