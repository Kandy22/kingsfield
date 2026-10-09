// Cases for hallucination_guard.ts finalizeCrewReply (POST /crew/chat) and gateCouncilOutput (POST /council,
// GET /council/:id[/html|/markdown]). Run by test_route_gate.py through backend/node_modules/.bin/tsx.
// Stub verifiers only: no Supabase, CourtListener, LLM or Python gate. Prints {caseName: null | "failure text"}.

import assert from 'node:assert/strict';
import {
  CREW_CHUNK_SIZE,
  VETO_WITHHELD_MESSAGE,
  WITHHELD_MESSAGE,
  finalizeCrewReply,
  gateCouncilOutput,
  withheldCouncilOutput,
  type FinalizeOutput,
  type SseVerificationResult,
} from '../../backend/src/middleware/hallucination_guard';

// ---------- helpers ----------

const DONE = 'data: [DONE]\n\n';
const parse = (l: string) => JSON.parse(l.slice(6));

type Status = 'verified' | 'conditional' | 'vetoed' | 'pending';
const verdict = (citation: string, status: Status) => ({
  citation,
  status,
  gate1_existence: status !== 'vetoed',
  gate2_quote_accuracy: null,
  gate3_currency: null,
  gate4_jurisdiction_fit: null,
  notes: [] as string[],
});
const result = (verdicts: ReturnType<typeof verdict>[], extra: Partial<SseVerificationResult> = {}): SseVerificationResult => ({
  verdicts: verdicts as any,
  hasVetoes: verdicts.some((v) => v.status === 'vetoed' || v.status === 'pending'),
  hasConditional: verdicts.some((v) => v.status === 'conditional'),
  ...extra,
});
const CLEAN = result([]);

function stub(rule: (text: string, n: number) => SseVerificationResult | Error) {
  const calls: string[] = [];
  const verify = async (text: string) => {
    calls.push(text);
    const r = rule(text, calls.length - 1);
    if (r instanceof Error) throw r;
    return r;
  };
  return { verify, calls };
}

const GOOD = 'Good v. Case, 1 So. 3d 2 (Fla. 2010)';
const FAB = 'Doe v. Roe, 999 So. 3d 999 (Fla. 2015)';
const OTHER = 'Other v. Thing, 5 So. 3d 6 (Fla. 2011)';
const URL_GOOD = 'https://www.courtlistener.com/opinion/1/good-v-case/';

/** Vetoes any text containing FAB's reporter cite, verifies GOOD wherever it appears. */
const fabVetoer = () =>
  stub((t) => {
    const vs = [];
    if (t.includes('999 So. 3d 999')) vs.push(verdict(FAB, 'vetoed'));
    if (t.includes('1 So. 3d 2')) vs.push(verdict(GOOD, 'verified'));
    return result(vs);
  });

const authority = (citation = GOOD, relevanceNote = 'Controls the standard of review here.', sourceUrl = URL_GOOD) => ({
  citation, sourceUrl, relevanceNote,
});

const types = (out: FinalizeOutput) => out.linesToSend.map((l) => (l === DONE ? '[DONE]' : parse(l).type));
const sentText = (out: FinalizeOutput) =>
  out.linesToSend.filter((l) => l !== DONE).map(parse).filter((e) => e.type === 'content_delta').map((e) => e.text).join('');
const eventOf = (out: FinalizeOutput, type: string) => out.linesToSend.filter((l) => l !== DONE).map(parse).find((e) => e.type === type);

function assertCrewWithheld(out: FinalizeOutput, message: string, forbidden: string[] = []) {
  assert.equal(out.withheld, true);
  assert.equal(sentText(out), message);
  assert.deepEqual(types(out), ['content_delta', 'verification', '[DONE]']);
  assert.ok(!types(out).includes('citations'), 'no citations event when withheld');
  const blob = JSON.stringify(out);
  for (const f of forbidden) assert.ok(!blob.includes(f), `leaked: ${f}`);
}

// ---------- cases ----------

const cases: Record<string, () => Promise<void>> = {};

// ===== /crew/chat =====

cases.crew_clean_reply_passes_unchanged_with_citations = async () => {
  const reply = `The rule is settled. See ${GOOD}.`;
  const rel = 'Controls the standard of review here.';
  const { verify, calls } = fabVetoer();
  const out = await finalizeCrewReply({ reply, authorities: [authority(GOOD, rel)], verify });
  assert.equal(out.withheld, false);
  assert.equal(out.withheldReason, null);
  assert.equal(sentText(out), reply, 'reply sent unchanged');
  const cites = eventOf(out, 'citations');
  assert.deepEqual(cites.citations, [{ type: 'legal_authority', citation: GOOD, url: URL_GOOD, relevance: rel }]);
  // Gate 1 saw the reply AND the citation, url and relevance text, and the reply on its own.
  assert.ok(calls[0].startsWith(reply) && calls[0].includes(rel) && calls[0].includes(GOOD) && calls[0].includes(URL_GOOD));
  assert.ok(calls.includes(reply), 'the sent reply was checked on its own');
  // Order: deltas, citations, verification, [DONE].
  const t = types(out);
  assert.deepEqual(t.slice(-3), ['citations', 'verification', '[DONE]']);
  assert.ok(t.slice(0, -3).every((x) => x === 'content_delta'));
  const v = eventOf(out, 'verification');
  assert.equal(v.hasVetoes, false);
  assert.equal(v.verdicts.length, 1);
};

cases.crew_streams_in_80_char_chunks_and_a_citations_event_is_always_sent = async () => {
  assert.equal(CREW_CHUNK_SIZE, 80);
  const reply = 'x'.repeat(200);
  const { verify, calls } = stub(() => CLEAN);
  const out = await finalizeCrewReply({ reply, authorities: [], verify });
  assert.equal(out.withheld, false);
  const deltas = out.linesToSend.filter((l) => l !== DONE).map(parse).filter((e) => e.type === 'content_delta');
  assert.deepEqual(deltas.map((d) => d.text.length), [80, 80, 40]);
  assert.deepEqual(eventOf(out, 'citations').citations, []);
  assert.equal(calls.length, 1, 'no authorities: the reply is the full text, one gate call');
};

cases.crew_veto_in_the_reply_withholds_with_the_veto_message_and_no_citations = async () => {
  const reply = `As held in ${FAB}, the rule applies. See also ${GOOD}.`;
  const { verify } = fabVetoer();
  const out = await finalizeCrewReply({ reply, authorities: [authority()], verify });
  // (A verified verdict keeps its citation in the client-safe record, as in chat; only the reply text and chips are gone.)
  assertCrewWithheld(out, VETO_WITHHELD_MESSAGE, ['Doe', 'Roe', '999', 'the rule applies', 'See also', URL_GOOD, 'Controls the standard']);
  assert.equal(out.withheldReason, 'veto');
  assert.equal(eventOf(out, 'verification').hasVetoes, true);
};

cases.crew_veto_only_in_a_relevance_note_withholds = async () => {
  const reply = 'A clean reply with no citations at all.';
  const rel = `Follows ${FAB} on this point.`;
  const { verify } = fabVetoer();
  const out = await finalizeCrewReply({ reply, authorities: [authority(GOOD, rel)], verify });
  assertCrewWithheld(out, VETO_WITHHELD_MESSAGE, ['clean reply', '999', 'Roe', 'Follows', URL_GOOD]);
  assert.equal(out.withheldReason, 'veto');
};

cases.crew_veto_only_in_an_authority_citation_withholds = async () => {
  const { verify } = fabVetoer();
  const out = await finalizeCrewReply({ reply: 'Clean.', authorities: [authority(FAB, 'Fine.')], verify });
  assertCrewWithheld(out, VETO_WITHHELD_MESSAGE, ['Roe', '999']);
};

cases.crew_pending_verdict_counts_as_a_veto = async () => {
  const { verify } = stub(() => result([verdict(GOOD, 'pending')], { hasVetoes: false }));
  const out = await finalizeCrewReply({ reply: `See ${GOOD}.`, authorities: [], verify });
  assertCrewWithheld(out, VETO_WITHHELD_MESSAGE, ['Good v. Case']);
  assert.equal(eventOf(out, 'verification').hasVetoes, true);
};

cases.crew_short_form_in_a_relevance_note_is_checked_alone = async () => {
  // "Id. at 5" borrows its antecedent from the reply when the texts are joined; alone it has none.
  const rel = 'See id. at 5 for the standard.';
  const { verify, calls } = stub((t) => (t === rel ? result([verdict(GOOD, 'vetoed')]) : result([verdict(GOOD, 'verified')])));
  const out = await finalizeCrewReply({ reply: `See ${GOOD}.`, authorities: [authority(GOOD, rel)], verify });
  assertCrewWithheld(out, VETO_WITHHELD_MESSAGE);
  assert.ok(calls.includes(rel), 'the short-form string was sent to the gate on its own');
};

cases.crew_gate_error_withholds_with_the_generic_message = async () => {
  for (const rule of [
    () => new Error('sqlite: no such table caselaw_opinion at /secret/path'),
    () => result([], { error: 'CourtListener 500: token abc123secret' }),
    () => ({ nonsense: true }) as any,
  ]) {
    const { verify } = stub(rule);
    const out = await finalizeCrewReply({ reply: `See ${GOOD}.`, authorities: [authority()], verify });
    assertCrewWithheld(out, WITHHELD_MESSAGE, ['sqlite', 'secret', 'abc123', 'CourtListener', 'Good v. Case']);
    assert.equal(eventOf(out, 'verification').error, 'Verification failed.');
  }
};

cases.crew_raw_gate_error_goes_to_the_logger_not_the_client = async () => {
  const logged: unknown[] = [];
  const { verify } = stub(() => new Error('boom-secret'));
  const out = await finalizeCrewReply({
    reply: 'x', authorities: [], verify, logError: (ctx, e) => logged.push([ctx, e]),
  });
  assert.ok(logged.length >= 1);
  assert.ok(JSON.stringify(logged).includes('boom-secret'));
  assert.ok(!JSON.stringify(out).includes('boom-secret'));
};

cases.crew_verification_record_is_client_safe = async () => {
  const noted = { ...verdict(FAB, 'vetoed'), notes: [`No match for ${FAB}`] };
  const { verify } = stub(() => result([noted as any, verdict(GOOD, 'verified')]));
  const out = await finalizeCrewReply({ reply: `${FAB} and ${GOOD}`, authorities: [], verify });
  assertCrewWithheld(out, VETO_WITHHELD_MESSAGE, ['Doe v. Roe', '999 So. 3d 999']);
  const v = eventOf(out, 'verification');
  assert.equal(v.verdicts[0].status, 'vetoed');
  assert.equal(v.verdicts[0].citation, '', 'vetoed verdict carries no citation text');
  assert.equal(v.verdicts[1].citation, GOOD, 'verified verdict is unchanged');
  assert.deepEqual(v, { type: 'verification', verdicts: out.verification.verdicts, hasVetoes: true, hasConditional: false });
  assert.deepEqual(out.savedAnnotations.length, 1);
};

cases.crew_chip_without_a_matching_verdict_is_dropped_from_a_clean_reply = async () => {
  const { verify } = fabVetoer(); // verifies GOOD only; OTHER gets no verdict
  const out = await finalizeCrewReply({
    reply: `See ${GOOD}.`, authorities: [authority(GOOD), authority(OTHER, 'Also relevant.')], verify,
  });
  assert.equal(out.withheld, false);
  assert.deepEqual(eventOf(out, 'citations').citations.map((c: any) => c.citation), [GOOD]);
};

cases.crew_malformed_input_withholds = async () => {
  const bad: any[] = [
    { reply: 42, authorities: [] },
    { reply: 'reply-secret-text', authorities: 'nope' },
    { reply: 'reply-secret-text', authorities: [{ sourceUrl: 'u', relevanceNote: 'r' }] },
    { reply: 'reply-secret-text', authorities: [{ citation: GOOD, sourceUrl: 5, relevanceNote: 'r' }] },
    { reply: 'reply-secret-text', authorities: [{ citation: GOOD, sourceUrl: 'u', relevanceNote: { x: 1 } }] },
    { reply: 'reply-secret-text', authorities: [null] },
  ];
  for (const input of bad) {
    const { verify, calls } = stub(() => CLEAN);
    const out = await finalizeCrewReply({ ...input, verify, logError: () => {} });
    assertCrewWithheld(out, WITHHELD_MESSAGE, ['reply-secret-text', GOOD]);
    assert.equal(calls.length, 0, 'nothing malformed reaches the gate or the client');
  }
};

// ===== /council =====

const ROLES = ['contrarian', 'first_principles', 'expansionist', 'outsider', 'executor'] as const;
const LETTERS = ['A', 'B', 'C', 'D', 'E'] as const;

const councilOut = (over: { framed?: string; advisor?: [number, string]; reviewer?: [number, string]; verdict?: string } = {}) => ({
  framedQuestion: over.framed ?? 'Framed: may the claim be dismissed?',
  advisors: ROLES.map((role, i) => ({
    role,
    model: { provider: 'claude', model: 'claude-opus-4-8' },
    text: over.advisor && over.advisor[0] === i ? over.advisor[1] : `Advisor ${role} says something clean.`,
    letter: LETTERS[i],
  })),
  reviewers: ROLES.map((reviewerRole, i) => ({
    reviewerRole,
    text: over.reviewer && over.reviewer[0] === i ? over.reviewer[1] : `Reviewer ${reviewerRole} says something clean.`,
  })),
  chairmanVerdict: over.verdict ?? '## Verdict\nProceed carefully.',
});

/** The fields council/page.tsx reads: framedQuestion, advisors[].role/.text, chairmanVerdict (+ model, letter, reviewers). */
function assertFrontendShape(o: any) {
  assert.equal(typeof o.framedQuestion, 'string');
  assert.equal(typeof o.chairmanVerdict, 'string');
  assert.ok(Array.isArray(o.advisors) && Array.isArray(o.reviewers));
  for (const role of ROLES) {
    const a = o.advisors.find((x: any) => x.role === role);
    assert.ok(a, `advisor ${role} present (page.tsx getAdvisorResponse(role))`);
    assert.equal(typeof a.text, 'string');
    assert.equal(typeof a.model.provider, 'string');
    assert.equal(typeof a.model.model, 'string');
    assert.ok((LETTERS as readonly string[]).includes(a.letter));
  }
  for (const r of o.reviewers) assert.equal(typeof r.text, 'string');
  assert.deepEqual(Object.keys(o).sort(), ['advisors', 'chairmanVerdict', 'framedQuestion', 'reviewers']);
}

cases.council_clean_output_passes_unchanged_and_in_the_frontend_shape = async () => {
  const input = councilOut();
  const { verify, calls } = stub(() => result([verdict(GOOD, 'verified')]));
  const g = await gateCouncilOutput(input, { verify });
  assert.equal(g.withheld, false);
  assert.equal(g.withheldReason, null);
  assert.deepEqual(g.output, input);
  assertFrontendShape(g.output);
  assert.equal(g.verification.hasVetoes, false);
  assert.equal(g.verification.verdicts.length, 1);
  // Every model-written field went to the gate.
  const all = calls.join('\n');
  for (const s of [input.framedQuestion, input.chairmanVerdict, ...input.advisors.map((a) => a.text), ...input.reviewers.map((r) => r.text)]) {
    assert.ok(all.includes(s), `not checked: ${s}`);
  }
};

cases.council_a_veto_in_any_one_field_withholds_the_whole_output = async () => {
  const fieldCases: Record<string, ReturnType<typeof councilOut>> = {
    framedQuestion: councilOut({ framed: `Framed on ${FAB}.` }),
    advisor_0: councilOut({ advisor: [0, `Per ${FAB}.`] }),
    advisor_4: councilOut({ advisor: [4, `Per ${FAB}.`] }),
    reviewer_0: councilOut({ reviewer: [0, `Per ${FAB}.`] }),
    reviewer_3: councilOut({ reviewer: [3, `Per ${FAB}.`] }),
    chairmanVerdict: councilOut({ verdict: `Verdict: ${FAB} controls.` }),
  };
  for (const [name, input] of Object.entries(fieldCases)) {
    const { verify } = fabVetoer();
    const g = await gateCouncilOutput(input, { verify });
    assert.equal(g.withheld, true, name);
    assert.equal(g.withheldReason, 'veto', name);
    assert.deepEqual(g.output, withheldCouncilOutput(VETO_WITHHELD_MESSAGE), name);
    assertFrontendShape(g.output);
    const blob = JSON.stringify(g);
    for (const leak of ['Doe', 'Roe', '999', 'Framed:', 'says something clean', 'Proceed carefully']) {
      assert.ok(!blob.includes(leak), `${name} leaked ${leak}`);
    }
    assert.equal(g.verification.hasVetoes, true, name);
    assert.equal(g.verification.verdicts.find((v: any) => v.status === 'vetoed')?.citation, '', name);
  }
};

cases.council_a_short_form_field_is_checked_alone = async () => {
  const idText = 'The court said as much. Id. at 7.';
  const input = councilOut({ advisor: [2, idText] });
  const { verify, calls } = stub((t) => (t === idText ? result([verdict(GOOD, 'vetoed')]) : CLEAN));
  const g = await gateCouncilOutput(input, { verify });
  assert.equal(g.withheld, true);
  assert.equal(g.withheldReason, 'veto');
  assert.ok(calls.includes(idText));
};

cases.council_pending_verdict_withholds = async () => {
  const { verify } = stub(() => result([verdict(GOOD, 'pending')], { hasVetoes: false }));
  const g = await gateCouncilOutput(councilOut(), { verify });
  assert.equal(g.withheld, true);
  assert.deepEqual(g.output, withheldCouncilOutput(VETO_WITHHELD_MESSAGE));
  assert.equal(g.verification.hasVetoes, true);
};

cases.council_gate_error_withholds_with_the_generic_message_and_leaks_nothing = async () => {
  for (const rule of [
    () => new Error('sqlite: unable to open /private/db secret-xyz'),
    () => result([], { error: 'CourtListener 502 token=secret-xyz' }),
    () => ({ bogus: 1 }) as any,
  ]) {
    const logged: unknown[] = [];
    const { verify } = stub(rule);
    const g = await gateCouncilOutput(councilOut(), { verify, logError: (c, e) => logged.push([c, e]) });
    assert.equal(g.withheld, true);
    assert.equal(g.withheldReason, 'verification_error');
    assert.deepEqual(g.output, withheldCouncilOutput(WITHHELD_MESSAGE));
    assertFrontendShape(g.output);
    assert.ok(!JSON.stringify(g).includes('secret-xyz'));
    assert.equal(g.verification.error, 'Verification failed.');
    assert.ok(logged.length >= 1, 'raw error goes to the logger');
  }
};

cases.council_withheld_shape_is_five_advisors_five_reviewers_and_one_fixed_message = async () => {
  for (const msg of [WITHHELD_MESSAGE, VETO_WITHHELD_MESSAGE]) {
    const w = withheldCouncilOutput(msg);
    assertFrontendShape(w);
    assert.deepEqual(w.advisors.map((a) => a.role), [...ROLES]);
    assert.deepEqual(w.advisors.map((a) => a.letter), [...LETTERS]);
    assert.equal(w.advisors.length, 5);
    assert.equal(w.reviewers.length, 5);
    const texts = [w.framedQuestion, w.chairmanVerdict, ...w.advisors.map((a) => a.text), ...w.reviewers.map((r) => r.text)];
    assert.ok(texts.every((t) => t === msg));
  }
  assert.deepEqual(withheldCouncilOutput(), withheldCouncilOutput(WITHHELD_MESSAGE));
};

cases.council_malformed_output_withholds_without_calling_the_gate = async () => {
  const good = councilOut();
  const bad: any[] = [
    null,
    'text',
    { ...good, advisors: undefined },
    { ...good, reviewers: 'x' },
    { ...good, framedQuestion: 5 },
    { ...good, chairmanVerdict: undefined },
    { ...good, advisors: [{ ...good.advisors[0], role: 'judge' }] },
    { ...good, advisors: [{ ...good.advisors[0], text: 7 }] },
    { ...good, advisors: [{ ...good.advisors[0], letter: 'Z' }] },
    { ...good, advisors: [{ ...good.advisors[0], model: { provider: '<script>', model: 'm' } }] },
    { ...good, advisors: [{ ...good.advisors[0], model: null }] },
    { ...good, reviewers: [{ reviewerRole: 'nobody', text: 'x' }] },
  ];
  for (const input of bad) {
    const { verify, calls } = stub(() => CLEAN);
    const g = await gateCouncilOutput(input, { verify, logError: () => {} });
    assert.equal(g.withheld, true, JSON.stringify(input)?.slice(0, 80));
    assert.equal(g.withheldReason, 'malformed_output');
    assert.deepEqual(g.output, withheldCouncilOutput(WITHHELD_MESSAGE));
    assert.equal(calls.length, 0);
  }
};

cases.council_passed_output_has_only_the_known_keys = async () => {
  const input: any = councilOut();
  input.leak = 'unchecked text';
  input.advisors[0].extra = 'unchecked advisor text';
  input.reviewers[0].extra = 'unchecked reviewer text';
  const { verify } = stub(() => CLEAN);
  const g = await gateCouncilOutput(input, { verify });
  assert.equal(g.withheld, false);
  assertFrontendShape(g.output);
  assert.ok(!JSON.stringify(g.output).includes('unchecked'));
};

cases.council_empty_strings_do_not_throw = async () => {
  // Empty text fields: still a clean pass, never an exception.
  const input = councilOut({ framed: '', verdict: '' });
  const { verify } = stub(() => CLEAN);
  const g = await gateCouncilOutput(input, { verify });
  assert.equal(g.withheld, false);
};

// ---------- run ----------

(async () => {
  const report: Record<string, string | null> = {};
  for (const [name, fn] of Object.entries(cases)) {
    try {
      await fn();
      report[name] = null;
    } catch (err: any) {
      report[name] = String(err?.stack ?? err).slice(0, 2000);
    }
  }
  process.stdout.write(JSON.stringify(report));
})();
