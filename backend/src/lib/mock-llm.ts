/**
 * Stub responses for MOCK_LLM=true mode.
 * Zero API calls, ~2ms, $0. Flip the flag in backend/.env to disable.
 */

import type { CouncilOutput } from '../llm-council/orchestrator.js';
import type { CrewOutput } from '../crew/coordinator.js';

export const MOCK_ENABLED = process.env.MOCK_LLM === 'true';

export const MOCK_CREW: CrewOutput = {
  reply: `## Bottom line
[MOCK] Stub response — set MOCK_LLM=false in backend/.env to use real API calls.

## Authority
- *Mock v. Reality*, 123 F.3d 456 (Mock Cir. 2024) — confirms that stub data verifies UI without cost

## Recommendation
The Crew is wired correctly. Disable mock mode when you need real citations.

## Watchouts
This response cost $0.00 and took ~2ms. The real thing costs ~$0.08 and takes ~20s.

## Next step
Set MOCK_LLM=false and restart the backend.`,
  trace: {
    decision: 'crew',
    taskType: 'research_only',
    rolesSpawned: ['researcher', 'strategist', 'team_lead'],
  },
  authorities: [
    {
      citation: 'Mock v. Reality, 123 F.3d 456 (Mock Cir. 2024)',
      sourceUrl: 'https://courtlistener.com',
      relevanceNote: 'Stub citation for UI testing',
      verified: true,
    } as any,
  ],
};

export const MOCK_COUNCIL: CouncilOutput = {
  framedQuestion:
    '[MOCK] Is the mock flag working correctly, and does the Council UI render all five advisors plus the chairman verdict?',
  advisors: [
    {
      role: 'contrarian',
      model: { provider: 'claude', model: 'claude-opus-4-7' },
      text: '[MOCK — Contrarian] Every assumption in this question is wrong. The real cost is not $0 — it is the opportunity cost of not testing with real data. Stub responses mask integration bugs.',
      letter: 'A',
    },
    {
      role: 'first_principles',
      model: { provider: 'gemini', model: 'gemini-2.5-pro' },
      text: '[MOCK — First Principles] Strip away the convenience framing. A mock exists to validate UI behavior, not business logic. Use it only for that. Never ship with MOCK_LLM=true.',
      letter: 'B',
    },
    {
      role: 'expansionist',
      model: { provider: 'claude', model: 'claude-sonnet-4-6' },
      text: '[MOCK — Expansionist] Consider expanding the mock to include error states, timeout simulation, and partial responses. The happy path is the least interesting test case.',
      letter: 'C',
    },
    {
      role: 'outsider',
      model: { provider: 'gemini', model: 'gemini-2.5-flash' },
      text: '[MOCK — Outsider] From the outside: the UI looks identical whether the data is real or mocked. That is either a feature or a warning sign depending on your perspective.',
      letter: 'D',
    },
    {
      role: 'executor',
      model: { provider: 'claude', model: 'claude-sonnet-4-6' },
      text: '[MOCK — Executor] Next step: (1) Verify all five cards render. (2) Verify the verdict section renders. (3) Set MOCK_LLM=false. (4) Run one real council session to confirm end-to-end.',
      letter: 'E',
    },
  ],
  reviewers: [
    { reviewerRole: 'contrarian', text: '[MOCK] Response B is the most rigorous. Response A is contrarian for its own sake.' },
    { reviewerRole: 'first_principles', text: '[MOCK] Response E gives the clearest next action. Recommend adopting it.' },
    { reviewerRole: 'expansionist', text: '[MOCK] All responses are too narrow. None address the failure modes.' },
    { reviewerRole: 'outsider', text: '[MOCK] Response C is the most useful to someone unfamiliar with the codebase.' },
    { reviewerRole: 'executor', text: '[MOCK] Response E. Execute it.' },
  ],
  chairmanVerdict: `[MOCK — Chairman] The council has deliberated on whether the mock flag is working.

**Verdict:** It is. All five advisors rendered. The UI is wired correctly.

**Synthesis:** The Executor's framing is correct — verify the UI, then disable mock mode. The Contrarian raises a legitimate point: stubs that are too realistic can mask real integration bugs. Keep mock responses obviously synthetic (they are).

**Recommended next action:** Set MOCK_LLM=false in backend/.env, restart the backend, and run one live council session to validate the full 11-model pipeline.`,
};
