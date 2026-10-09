// Cases for hallucination_guard.ts finalizeHeldOutput / startSseKeepalive / visibleMatchesFullText.
// Run by test_chat_guard.py through backend/node_modules/.bin/tsx. Stub verifiers only:
// no Supabase, CourtListener, LLM or Python gate. Prints {caseName: null | "failure text"}.

import assert from 'node:assert/strict';
import {
  ABORTED_MESSAGE,
  ALIGN_WORK_BUDGET,
  failedReplyRecord,
  alignVisibleToFullText,
  GENERIC_ERROR_MESSAGE,
  KEEPALIVE_LINE,
  REDACTION_MARKER,
  VETO_WITHHELD_MESSAGE,
  WITHHELD_MESSAGE,
  citeKey,
  clientSafeVerification,
  createBufferingSseWriter,
  finalizeHeldOutput,
  startSseKeepalive,
  visibleMatchesFullText,
  type FinalizeOutput,
  type SseVerificationResult,
} from '../../backend/src/middleware/hallucination_guard';

// ---------- helpers ----------

const line = (ev: unknown) => `data: ${JSON.stringify(ev)}\n\n`;
const DONE = 'data: [DONE]\n\n';
const delta = (text: string) => line({ type: 'content_delta', text });

type Status = 'verified' | 'conditional' | 'vetoed' | 'pending';
const verdict = (citation: string, status: Status) => ({
  citation,
  status,
  gate1_existence: status !== 'vetoed',
  gate2_quote_accuracy: null,
  gate3_currency: null,
  gate4_jurisdiction_fit: null,
  notes: [],
});
const result = (verdicts: ReturnType<typeof verdict>[], extra: Partial<SseVerificationResult> = {}): SseVerificationResult => ({
  verdicts: verdicts as any,
  hasVetoes: verdicts.some((v) => v.status === 'vetoed' || v.status === 'pending'),
  hasConditional: verdicts.some((v) => v.status === 'conditional'),
  ...extra,
});
const CLEAN = result([]);

/** Stub verifier: `rule(text, callIndex)` returns the result; every call is recorded. */
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

const SMITH = 'Smith v. Jones, 123 So. 3d 456 (Fla. 2013)';
const GOOD = 'Good v. Case, 1 So. 3d 2 (Fla. 2010)';

const caseEntry = (cluster_id: number, citation: string | null) => ({
  type: 'citation_data', kind: 'case', ref: cluster_id, cluster_id, case_name: `Case ${cluster_id}`, citation,
  url: `https://example.test/${cluster_id}`, quotes: [],
});
const docEntry = (quote = 'verbatim text') => ({
  type: 'citation_data', kind: 'document', ref: 1, doc_id: 'doc-0', document_id: 'd1', filename: 'brief.docx', page: 1, quote, quotes: [],
});
const caseCitationEv = (cluster_id: number, citation: string | null) => ({
  type: 'case_citation', cluster_id, case_name: `Case ${cluster_id}`, citation, url: `https://example.test/${cluster_id}`,
});

function sentContent(out: FinalizeOutput): string {
  return out.linesToSend
    .filter((l) => l !== DONE)
    .map((l) => JSON.parse(l.slice(6)))
    .filter((e) => e && e.type === 'content_delta')
    .map((e) => e.text)
    .join('');
}
const savedContent = (out: FinalizeOutput) =>
  out.savedEvents.filter((e) => e.type === 'content').map((e) => e.text).join('');
const sentTypes = (out: FinalizeOutput) =>
  out.linesToSend.map((l) => (l === DONE ? '[DONE]' : JSON.parse(l.slice(6)).type));

/** The record Step 2 saves: type + the same four fields as the client-safe verification. */
const recordOf = (v: SseVerificationResult) => ({
  type: 'verification',
  verdicts: v.verdicts,
  hasVetoes: v.hasVetoes,
  hasConditional: v.hasConditional,
  ...(v.error ? { error: v.error } : {}),
});
const isVerificationRecord = (a: any) => !!a && a.type === 'verification';
/** savedAnnotations without the verification record: the sent citation entries only. */
const citationEntries = (out: FinalizeOutput) => out.savedAnnotations.filter((a) => !isVerificationRecord(a));

function assertWithheld(out: FinalizeOutput, forbidden: string[] = [], message: string = WITHHELD_MESSAGE) {
  assert.equal(out.withheld, true);
  assert.deepEqual(
    out.linesToSend.filter((l) => l.includes('content_delta')),
    [delta(message)],
  );
  assert.equal(out.linesToSend[out.linesToSend.length - 1], DONE);
  assert.equal(sentContent(out), message);
  assert.equal(savedContent(out), message);
  assert.equal(out.savedEvents.filter((e) => e.type === 'content').length, 1, 'exactly one saved content event');
  // No case-citation entries, case_citation events or model text can ride along with a withheld reply.
  const types = sentTypes(out);
  assert.ok(!types.includes('citations') && !types.includes('case_citation'), types.join());
  assert.deepEqual(out.savedAnnotations, [recordOf(out.verification)], 'only the verification record is saved');
  const blob = JSON.stringify([out.linesToSend, out.savedEvents, out.savedAnnotations]);
  for (const f of forbidden) assert.ok(!blob.includes(f), `leaked: ${f}`);
}

// ---------- cases ----------

const cases: Record<string, () => Promise<void>> = {};

// ----- any veto withholds the whole reply -----

cases.veto_withholds_whole_reply_with_the_veto_message_sent_and_saved = async () => {
  // The cite is split across deltas, so no single delta holds it; the reply also names the case.
  const parts = ['As held in Smith v. Jo', 'nes, 123 So. 3d 4', '56 (Fla. 2013), the rule applies. See also ', GOOD, '.'];
  const full = parts.join('');
  const { verify, calls } = stub(() => result([verdict(SMITH, 'vetoed'), verdict(GOOD, 'verified')]));
  const held = [
    ...parts.map(delta),
    line({ type: 'citations', status: 'final', citations: [caseEntry(1, '123 So. 3d 456'), caseEntry(2, '1 So. 3d 2'), docEntry()] }),
    line(caseCitationEv(1, '123 So. 3d 456')),
    line(caseCitationEv(2, '1 So. 3d 2')),
    DONE,
  ];
  const events = [
    { type: 'content', text: parts.slice(0, 2).join('') },
    { type: 'doc_read', filename: 'a.docx' },
    { type: 'content', text: parts.slice(2).join('') },
  ];
  const out = await finalizeHeldOutput({
    held, events, annotations: [caseEntry(1, '123 So. 3d 456'), caseEntry(2, '1 So. 3d 2'), docEntry()], fullText: full, verify,
  });
  assertWithheld(out, ['Smith', 'Jones', '456', 'the rule applies', 'Case 1', 'Case 2'], VETO_WITHHELD_MESSAGE);
  assert.equal(out.withheldReason, 'veto');
  assert.ok(!sentContent(out).includes(REDACTION_MARKER), 'no partial redaction text');
  assert.equal(calls.length, 1, 'visible equals fullText: one gate call, no re-verify');
  // The verification event and the saved record are still there, with citation text stripped from the non-OK verdict.
  assert.equal(out.verification.hasVetoes, true);
  const vs = out.verification.verdicts as any[];
  assert.equal(vs[0].status, 'vetoed');
  assert.equal(vs[0].citation, '');
  assert.equal(vs[1].citation, GOOD, 'verified verdict keeps its citation');
  const rec = out.savedAnnotations.find(isVerificationRecord) as any;
  assert.deepEqual(rec, recordOf(out.verification));
  assert.equal(rec.verdicts[0].citation, '');
  // doc_read is a checked family now: dropped whole in the withheld path.
  assert.deepEqual(out.savedEvents.map((e) => e.type), ['content']);
};

cases.veto_message_is_distinct_from_the_generic_withheld_message = async () => {
  assert.equal(VETO_WITHHELD_MESSAGE, 'This answer was withheld because it cited a case that could not be verified.');
  assert.equal(WITHHELD_MESSAGE, 'This answer could not be verified and was withheld.');
  assert.notEqual(VETO_WITHHELD_MESSAGE, WITHHELD_MESSAGE);
};

cases.veto_in_the_hidden_citations_block_withholds = async () => {
  const visible = 'Hello there.';
  const full = `${visible}<CITATIONS>[{"citation":"123 So. 3d 456"}]</CITATIONS>`;
  const { verify, calls } = stub((t) => (t.includes('456') ? result([verdict(SMITH, 'vetoed')]) : CLEAN));
  const out = await finalizeHeldOutput({
    held: [delta(visible), line(caseCitationEv(1, '123 So. 3d 456')), DONE],
    events: [{ type: 'content', text: visible }], annotations: [caseEntry(1, '123 So. 3d 456')], fullText: full, verify,
  });
  assertWithheld(out, ['Hello there', '456'], VETO_WITHHELD_MESSAGE);
  assert.equal(out.withheldReason, 'veto');
  assert.equal(calls.length, 1, 'stops at the first veto');
};

cases.veto_withholds_however_the_cite_is_formatted = async () => {
  const full =
    'One: **Smith v. Jones**,\n123  So. 3d\n456 (Fla. 2013) here. ' +
    'Two: [Smith v. Jones, 123 So. 3d 456 (Fla. 2013)](us-case-9) there. ' +
    'Three: *Smith* v. _Jones_, 123 So. 3d 456 (Fla. 2013).';
  // Markdown, line breaks and links around the cite make no difference: there is no text surgery, the reply is withheld whole.
  const { verify } = stub(() => result([verdict(SMITH, 'vetoed')]));
  const out = await finalizeHeldOutput({
    held: [delta(full), DONE], events: [{ type: 'content', text: full }], annotations: [], fullText: full, verify,
  });
  assertWithheld(out, ['Smith', '456', 'us-case-9', 'One:'], VETO_WITHHELD_MESSAGE);
  assert.equal(out.withheldReason, 'veto');
  // (end of case)
};

cases.veto_withholds_even_when_the_cite_is_nowhere_in_the_reply_text = async () => {
  const full = 'A reply with no matching text at all.';
  const { verify } = stub(() => result([verdict(SMITH, 'vetoed')]));
  const out = await finalizeHeldOutput({
    held: [delta(full), DONE], events: [{ type: 'content', text: full }], annotations: [], fullText: full, verify,
  });
  assertWithheld(out, ['A reply with no matching'], VETO_WITHHELD_MESSAGE);
  assert.equal(out.withheldReason, 'veto');
};

cases.veto_withholds_the_whole_reply_including_short_forms = async () => {
  const full = `${SMITH}. Later, Smith, 123 So. 3d at 460.`;
  const { verify, calls } = stub(() => result([verdict(SMITH, 'vetoed'), verdict('Smith, 123 So. 3d at 460', 'vetoed')]));
  const out = await finalizeHeldOutput({
    held: [delta(full), DONE], events: [{ type: 'content', text: full }], annotations: [caseEntry(1, '123 So. 3d 456')], fullText: full, verify,
  });
  assertWithheld(out, ['Smith', '460'], VETO_WITHHELD_MESSAGE);
  assert.equal(out.withheldReason, 'veto');
  assert.equal(calls.length, 1);
};

cases.visible_verify_error_or_throw_withholds_with_the_generic_message = async () => {
  // The reply has a hidden <CITATIONS> block, so the sent text differs from fullText and is verified on its own.
  const visible = 'Plain answer.';
  const full = `${visible}<CITATIONS>[]</CITATIONS>`;
  for (const second of [result([], { error: 'Verification failed: boom.', hasVetoes: true }), new Error('kaboom')]) {
    const { verify, calls } = stub((t, n) => (n === 0 ? CLEAN : second));
    const out = await finalizeHeldOutput({
      held: [delta(visible), DONE], events: [{ type: 'content', text: visible }], annotations: [], fullText: full, verify, logError: () => {},
    });
    assertWithheld(out, ['Plain answer']);
    assert.equal(out.withheldReason, 'verification_error');
    assert.equal(out.verification.error, 'Verification failed.');
    assert.deepEqual(calls, [full, visible], 'fullText first, then the exact sent text');
  }
};

cases.error_result_withholds_and_leaks_no_model_text = async () => {
  const secret = 'SECRET MODEL ANSWER about 123 So. 3d 456';
  const { verify, calls } = stub(() => result([], { hasVetoes: true, error: 'Verification failed: db down. Treating as unverified.' }));
  const held = [
    line({ type: 'reasoning_delta', text: 'SECRET REASONING' }),
    line({ type: 'doc_read_start', filename: 'brief.docx', document_id: 'd1' }),
    line({ type: 'doc_read', filename: 'brief.docx', document_id: 'd1' }),
    line({ type: 'courtlistener_get_cases', cluster_ids: [5], case_count: 1, opinion_count: 1, cases: [{ cluster_id: 5, case_name: 'LEAKY NAME', citation: '1 So. 3d 2', url: 'u' }], error: 'LEAKY ERR' }),
    line({ type: 'case_opinions', cluster_id: 5, case: { text: 'LEAKY OPINION' } }),
    line({ type: 'citations', status: 'final', citations: [caseEntry(5, '1 So. 3d 2'), docEntry('LEAKY QUOTE')] }),
    line(caseCitationEv(5, '1 So. 3d 2')),
    line({ type: 'doc_find', filename: 'brief.docx', query: 'LEAKY QUERY 1', total_matches: 1 }),
    delta(secret),
    DONE,
  ];
  const events = [
    { type: 'reasoning', text: 'SECRET REASONING' },
    { type: 'doc_read', filename: 'brief.docx', document_id: 'd1' },
    { type: 'content', text: secret },
  ];
  const out = await finalizeHeldOutput({ held, events, annotations: [caseEntry(5, '1 So. 3d 2'), docEntry()], fullText: secret, verify });
  assertWithheld(out, ['SECRET', 'LEAKY', '123 So. 3d']);
  assert.equal(calls.length, 1, 'no further verification once the gate failed');
  assert.equal(out.verification.error, 'Verification failed.');
  // Only the scrubbed (counts-only) CourtListener result survives; doc_read / doc_read_start are checked families, dropped when withholding.
  const types = sentTypes(out);
  assert.deepEqual(types, ['courtlistener_get_cases', 'content_delta', '[DONE]']);
  const getCases = JSON.parse(out.linesToSend[0].slice(6));
  assert.deepEqual(getCases, { type: 'courtlistener_get_cases', cluster_ids: [5], case_count: 1, opinion_count: 1, cases: [] });
  assert.deepEqual(out.savedEvents.map((e) => e.type), ['content']);
};

cases.throw_withholds = async () => {
  const secret = 'Model text with Smith v. Jones, 123 So. 3d 456 (Fla. 2013).';
  const { verify } = stub(() => new Error('exploded'));
  const out = await finalizeHeldOutput({ held: [delta(secret), DONE], events: [{ type: 'content', text: secret }], annotations: [], fullText: secret, verify });
  assertWithheld(out, ['Smith']);
  assert.equal(out.verification.error, 'Verification failed.');
  assert.ok(!JSON.stringify(out).includes('exploded'), 'exception text stays on the server');
  assert.equal(out.verification.hasVetoes, true);
};

cases.draft_placeholder_veto_withholds = async () => {
  const secret = 'Anything the model said.';
  const { verify } = stub(() => result([verdict('[draft]', 'vetoed')]));
  const out = await finalizeHeldOutput({ held: [delta(secret), DONE], events: [{ type: 'content', text: secret }], annotations: [], fullText: secret, verify });
  assertWithheld(out, ['Anything the model'], VETO_WITHHELD_MESSAGE);
  assert.equal(out.withheldReason, 'whole_draft_veto');
};

cases.veto_flag_without_any_vetoed_verdict_withholds = async () => {
  const { verify } = stub(() => ({ verdicts: [], hasVetoes: true, hasConditional: false }));
  const out = await finalizeHeldOutput({ held: [delta('x'), DONE], events: [{ type: 'content', text: 'x' }], annotations: [], fullText: 'x', verify });
  assertWithheld(out);
};

cases.pending_status_counts_as_vetoed = async () => {
  const full = `Per ${SMITH}, yes.`;
  const { verify } = stub((t) => (t.includes('456') ? result([verdict(SMITH, 'pending')]) : CLEAN));
  const out = await finalizeHeldOutput({ held: [delta(full), DONE], events: [{ type: 'content', text: full }], annotations: [], fullText: full, verify });
  assertWithheld(out, ['Smith', '456', 'yes'], VETO_WITHHELD_MESSAGE);
  assert.equal(out.withheldReason, 'veto');
  assert.equal((out.verification.verdicts as any[])[0].status, 'pending');
  assert.equal((out.verification.verdicts as any[])[0].citation, '');
};

cases.unknown_status_counts_as_vetoed = async () => {
  const full = `Per ${SMITH}, yes.`;
  const odd = { ...verdict(SMITH, 'vetoed'), status: 'weird' as any };
  const out = await finalizeHeldOutput({
    held: [delta(full), DONE], events: [{ type: 'content', text: full }], annotations: [], fullText: full,
    verify: stub(() => ({ verdicts: [odd], hasVetoes: false, hasConditional: false })).verify,
  });
  assertWithheld(out, ['Smith', 'yes'], VETO_WITHHELD_MESSAGE);
};

cases.conditional_and_verified_replay_unchanged = async () => {
  const parts = ['Per ', SMITH, ' and ', GOOD, '.'];
  const full = parts.join('');
  const held = [
    // Real document ids are UUIDs, which are not citable strings; a filename without digits sends nothing to the gate.
    line({ type: 'doc_read_start', filename: 'a.docx', document_id: '123e4567-e89b-12d3-a456-426614174000' }),
    ...parts.map(delta),
    line({ type: 'citations', status: 'started', citations: [] }),
    line({ type: 'citations', status: 'final', citations: [caseEntry(1, '123 So. 3d 456'), caseEntry(2, '1 So. 3d 2'), docEntry()] }),
    line(caseCitationEv(1, '123 So. 3d 456')),
    line(caseCitationEv(2, '1 So. 3d 2')),
    DONE,
  ];
  const events = [{ type: 'doc_read', filename: 'a.docx' }, { type: 'content', text: full }];
  const annotations = [caseEntry(1, '123 So. 3d 456'), caseEntry(2, '1 So. 3d 2'), docEntry()];
  const { verify, calls } = stub(() => result([verdict(SMITH, 'conditional'), verdict(GOOD, 'verified')]));
  const out = await finalizeHeldOutput({ held, events, annotations, fullText: full, verify });
  assert.equal(out.withheld, false);
  assert.deepEqual(out.linesToSend, held, 'every held line replayed byte for byte');
  assert.deepEqual(out.savedEvents, events);
  assert.deepEqual(out.savedAnnotations, [...annotations, recordOf(out.verification)]);
  assert.equal(calls.length, 1);
  assert.equal(out.verification.hasConditional, true);
};

cases.unmatched_entries_dropped_from_citations_and_case_citation = async () => {
  const full = `${SMITH} and ${GOOD}.`;
  const entries = [
    caseEntry(1, '123 So. 3d 456'), // conditional: kept
    caseEntry(2, '1 So. 3d 2'), // verified: kept
    caseEntry(3, '9 U.S. 9'), // matches no verdict at all
    caseEntry(4, null), // no citation at all
    docEntry(), // user's own document: passes
    { type: 'citation_data', ref: 7, cluster_id: 7, citation: '9 U.S. 9' }, // no kind: treated as case law, no verdict
    { ...docEntry(), cluster_id: 8 }, // claims to be a document but carries a cluster_id: treated as case law
  ];
  const held = [
    delta(full),
    line({ type: 'citations', status: 'started', citations: [] }),
    line({ type: 'citations', status: 'partial', citations: entries.slice(0, 2) }),
    line({ type: 'citations', status: 'final', citations: entries }),
    line(caseCitationEv(1, '123 So. 3d 456')),
    line(caseCitationEv(2, '1 So. 3d 2')),
    line(caseCitationEv(3, '9 U.S. 9')),
    line(caseCitationEv(4, null)),
    DONE,
  ];
  const { verify } = stub(() => result([verdict(SMITH, 'conditional'), verdict(GOOD, 'verified')]));
  const out = await finalizeHeldOutput({ held, events: [{ type: 'content', text: full }], annotations: entries, fullText: full, verify });
  assert.equal(out.withheld, false);
  const parsed = out.linesToSend.filter((l) => l !== DONE).map((l) => JSON.parse(l.slice(6)));
  const citationsEvs = parsed.filter((e) => e.type === 'citations');
  assert.equal(citationsEvs.length, 3, 'started/partial/final all still sent');
  assert.deepEqual(citationsEvs[0].citations, []);
  assert.deepEqual(citationsEvs[1].citations.map((c: any) => c.cluster_id), [1, 2]);
  assert.deepEqual(citationsEvs[2].citations.map((c: any) => c.cluster_id ?? c.doc_id), [1, 2, 'doc-0']);
  assert.deepEqual(parsed.filter((e) => e.type === 'case_citation').map((e) => e.cluster_id), [1, 2]);
  assert.deepEqual(citationEntries(out).map((c: any) => c.cluster_id ?? c.doc_id), [1, 2, 'doc-0']);
};

cases.saved_events_equal_what_was_sent = async () => {
  const full1 = 'First part. ';
  const full2 = `Then ${SMITH} and more.`;
  const held = [
    line({ type: 'reasoning_delta', text: 'private thoughts' }),
    line({ type: 'reasoning_block_end' }),
    delta(full1),
    line({ type: 'doc_read_start', filename: 'a.docx' }),
    line({ type: 'doc_read', filename: 'a.docx' }),
    line({ type: 'case_opinions', cluster_id: 1, case: { x: 1 } }),
    delta(full2),
    line({ type: 'citations', status: 'final', citations: [caseEntry(1, '123 So. 3d 456'), docEntry()] }),
    DONE,
  ];
  const events = [
    { type: 'reasoning', text: 'private thoughts' },
    { type: 'content', text: full1 },
    { type: 'doc_read', filename: 'a.docx' },
    { type: 'content', text: full2 },
  ];
  const { verify } = stub(() => result([verdict(SMITH, 'conditional')], { hasConditional: true }));
  const out = await finalizeHeldOutput({ held, events, annotations: [caseEntry(1, '123 So. 3d 456'), docEntry()], fullText: full1 + full2, verify });
  assert.equal(out.withheld, false);
  const sent = sentContent(out);
  assert.equal(sent, full1 + full2, 'model text goes out unchanged');
  assert.equal(savedContent(out), sent);
  // Content events keep their positions, reasoning and case_opinions are gone, order kept.
  assert.deepEqual(out.savedEvents.map((e) => e.type), ['content', 'doc_read', 'content']);
  assert.deepEqual(sentTypes(out), ['content_delta', 'doc_read_start', 'doc_read', 'content_delta', 'citations', '[DONE]']);
  assert.deepEqual(citationEntries(out).map((c: any) => c.cluster_id ?? c.doc_id), [1, 'doc-0']);
  const blob = JSON.stringify([out.linesToSend, out.savedEvents]);
  assert.ok(!blob.includes('private thoughts'));
};

cases.streamed_and_saved_text_mismatch_withholds = async () => {
  const { verify } = stub(() => CLEAN);
  const out = await finalizeHeldOutput({ held: [delta('streamed'), DONE], events: [{ type: 'content', text: 'something else' }], annotations: [], fullText: 'streamed', verify });
  assertWithheld(out, ['streamed', 'something else']);
  assert.equal(out.withheldReason, 'content_mismatch');
};

cases.unknown_and_unparseable_held_lines_are_dropped = async () => {
  const held = [delta('ok text'), line({ type: 'brand_new_event', text: 'MYSTERY' }), 'data: {not json\n\n', ': stray comment\n\n', DONE];
  const { verify } = stub(() => CLEAN);
  const out = await finalizeHeldOutput({ held, events: [{ type: 'content', text: 'ok text' }], annotations: [], fullText: 'ok text', verify });
  assert.equal(out.withheld, false);
  assert.deepEqual(out.linesToSend, [delta('ok text'), DONE]);
};

cases.rule4_clean_model_text_passes_and_flagged_text_is_dropped = async () => {
  const BAD = 'Fake v. Case, 999 So. 3d 5 (Fla. 2012)';
  const full = 'Plain answer.';
  const held = [
    delta(full),
    line({ type: 'doc_find_start', filename: 'a.docx', query: 'indemnification' }),
    line({ type: 'doc_find', filename: 'a.docx', query: 'indemnification', total_matches: 2 }),
    line({ type: 'doc_find_start', filename: 'a.docx', query: BAD }),
    line({ type: 'doc_find', filename: 'a.docx', query: BAD, total_matches: 0 }),
    line({ type: 'doc_created', filename: 'Memo 2024.docx', download_url: 'https://x.test/dl', document_id: 'd9' }),
    line({ type: 'courtlistener_search_case_law_start', query: BAD }),
    line({ type: 'courtlistener_search_case_law', query: BAD, result_count: 0 }),
    line({ type: 'courtlistener_find_in_case_start', cluster_id: 5, query: 'anything' }),
    line({ type: 'courtlistener_find_in_case', cluster_id: 5, query: 'anything', total_matches: 1, case_name: 'N', citation: '1 So. 3d 2' }),
    line({ type: 'mcp_tool_result', name: 'mcp_x_tool', connector_name: 'My Server', tool_name: 'tool', status: 'error', error: `failed on ${BAD}` }),
    line({ type: 'doc_edited', filename: 'a.docx', document_id: 'd1', version_id: 'v1', download_url: 'https://x.test/e', annotations: [{ inserted_text: 'new clause', reason: 'cleanup' }] }),
    DONE,
  ];
  const events = [
    { type: 'doc_find', filename: 'a.docx', query: 'indemnification', total_matches: 2 },
    { type: 'doc_find', filename: 'a.docx', query: BAD, total_matches: 0 },
    { type: 'doc_created', filename: 'Memo 2024.docx', download_url: 'https://x.test/dl', document_id: 'd9' },
    { type: 'courtlistener_search_case_law', query: BAD, result_count: 0 },
    { type: 'courtlistener_find_in_case', cluster_id: 5, query: 'anything', total_matches: 1 },
    { type: 'mcp_tool_call', connector_id: 'c1', connector_name: 'My Server', tool_name: 'tool', openai_tool_name: 'mcp_x_tool', status: 'error', error: `failed on ${BAD}` },
    { type: 'doc_edited', filename: 'a.docx', document_id: 'd1', version_id: 'v1', version_number: 2, download_url: 'https://x.test/e', annotations: [{ inserted_text: 'new clause', reason: 'cleanup' }] },
    { type: 'content', text: full },
  ];
  // The gate flags any text containing the fabricated cite (alone or in a batch) and nothing else.
  const { verify } = stub((t) => (t.includes('999 So. 3d 5') ? result([verdict(BAD, 'vetoed')]) : CLEAN));
  const out = await finalizeHeldOutput({ held, events, annotations: [], fullText: full, verify });
  assert.equal(out.withheld, false, 'a flagged tool string must not withhold the reply');
  const sent = out.linesToSend.filter((l) => l !== DONE).map((l) => JSON.parse(l.slice(6)));
  const types = sent.map((e) => e.type);
  // doc_find family dropped as a whole (start and result stay paired), CL search dropped, find_in_case always dropped.
  assert.ok(!types.some((t) => t.startsWith('doc_find')), types.join());
  assert.ok(!types.some((t) => t.startsWith('courtlistener_')), types.join());
  // Unflagged families pass unchanged.
  assert.ok(types.includes('doc_created') && types.includes('doc_edited'));
  // mcp result had a flagged error string: scrubbed, not dropped (the live mcp_tool_start is waiting for it).
  const mcp = sent.find((e) => e.type === 'mcp_tool_result');
  assert.deepEqual(mcp, { type: 'mcp_tool_result', name: 'mcp_x_tool', tool_name: 'tool', status: 'error' });
  assert.deepEqual(
    out.savedEvents.map((e) => e.type),
    ['doc_created', 'mcp_tool_call', 'doc_edited', 'content'],
  );
  const savedMcp = out.savedEvents.find((e) => e.type === 'mcp_tool_call') as any;
  assert.equal(savedMcp.error, undefined);
  assert.ok(!JSON.stringify([out.linesToSend, out.savedEvents]).includes('999 So. 3d'));
};

cases.rule4_clean_batch_makes_no_extra_calls_when_nothing_to_check = async () => {
  const held = [delta('hi'), line({ type: 'doc_read', filename: 'a.docx' }), line({ type: 'doc_find', filename: 'a.docx', query: 'indemnification', total_matches: 1 }), DONE];
  const { verify, calls } = stub(() => CLEAN);
  const out = await finalizeHeldOutput({ held, events: [{ type: 'content', text: 'hi' }], annotations: [], fullText: 'hi', verify });
  assert.deepEqual(out.linesToSend, held);
  assert.equal(calls.length, 1, 'strings without digits cannot hold a citation and are not sent to the gate');
};

cases.rule4_gate_error_on_tool_text_drops_it = async () => {
  const held = [delta('hi'), line({ type: 'doc_created', filename: 'Memo 2024.docx', download_url: 'https://x.test/d', document_id: 'd9' }), DONE];
  const { verify } = stub((t) => (t === 'hi' ? CLEAN : result([], { hasVetoes: true, error: 'gate down' })));
  const out = await finalizeHeldOutput({ held, events: [{ type: 'content', text: 'hi' }], annotations: [], fullText: 'hi', verify });
  assert.equal(out.withheld, false);
  assert.deepEqual(sentTypes(out), ['content_delta', '[DONE]']);
};

cases.rule4_short_form_strings_are_checked_alone = async () => {
  // "Id. at 5" would resolve against a neighbouring string in a batch; it must be checked on its own.
  const held = [
    delta('hi'),
    line({ type: 'doc_find_start', filename: 'a.docx', query: 'Id. at 5' }),
    line({ type: 'doc_find_start', filename: 'a.docx', query: 'Good v. Case, 1 So. 3d 2 (Fla. 2010)' }),
    DONE,
  ];
  const { verify, calls } = stub((t) => (t === 'Id. at 5' ? result([verdict('Id. at 5', 'vetoed')]) : CLEAN));
  const out = await finalizeHeldOutput({ held, events: [{ type: 'content', text: 'hi' }], annotations: [], fullText: 'hi', verify });
  assert.ok(calls.includes('Id. at 5'), 'checked alone');
  assert.deepEqual(sentTypes(out), ['content_delta', '[DONE]'], 'family dropped');
};

cases.withheld_output_order_and_status_only = async () => {
  const { verify } = stub(() => result([], { hasVetoes: true, error: 'x' }));
  const held = [
    line({ type: 'workflow_applied', workflow_id: 'w'.repeat(301), title: 't' }), // held (too long to be live), server-state
    line({ type: 'doc_read_start', filename: 'a.docx' }),
    delta('model words'),
    line({ type: 'courtlistener_verify_citations', citation_count: 2, match_count: 1, error: 'ERR TEXT' }),
    line({ type: 'doc_created', filename: 'Leaky.docx', download_url: 'u' }),
    DONE,
  ];
  const out = await finalizeHeldOutput({ held, events: [{ type: 'content', text: 'model words' }, { type: 'doc_created', filename: 'Leaky.docx', download_url: 'u' }], annotations: [], fullText: 'model words', verify });
  assertWithheld(out, ['model words', 'Leaky', 'ERR TEXT']);
  // doc_read_start is a checked family: dropped in the withheld path.
  assert.deepEqual(sentTypes(out), ['workflow_applied', 'courtlistener_verify_citations', 'content_delta', '[DONE]']);
  assert.deepEqual(JSON.parse(out.linesToSend[1].slice(6)), { type: 'courtlistener_verify_citations', citation_count: 2, match_count: 1 });
};

cases.empty_reply_replays_without_calls_beyond_the_first = async () => {
  const { verify, calls } = stub(() => CLEAN);
  const out = await finalizeHeldOutput({ held: [DONE], events: [], annotations: [], fullText: '', verify });
  assert.equal(out.withheld, false);
  assert.deepEqual(out.linesToSend, [DONE]);
  assert.equal(calls.length, 1);
};

cases.citekey_matches_bare_and_full_forms = async () => {
  assert.equal(citeKey('123 So. 3d 456'), citeKey('Smith v. Jones, 123 So. 3d 456, 460 (Fla. 2013)'));
  assert.equal(citeKey('123 So.3d 456'), citeKey('123 So. 3d 456'));
  assert.equal(citeKey('410 U.S. 113'), citeKey('Roe v. Wade, 410 U.S. 113 (1973)'));
  assert.equal(citeKey('45 Fla. L. Weekly D123'), citeKey('X v. Y, 45 Fla. L. Weekly D123 (Fla. 2d DCA 2020)'));
  assert.notEqual(citeKey('123 So. 3d 456'), citeKey('123 So. 2d 456'));
  assert.notEqual(citeKey('123 So. 3d 456'), citeKey('123 So. 3d 4560'));
  assert.equal(citeKey(null), null);
  assert.equal(citeKey('no cite here'), null);
};

cases.buffering_writer_take_held_releases_nothing = async () => {
  const raw: string[] = [];
  const w = createBufferingSseWriter((l) => raw.push(l));
  w.write(line({ type: 'tool_call_start', name: 'read_document' }));
  w.write(delta('held text'));
  w.write(DONE);
  assert.equal(raw.length, 1, 'only the live status line went out');
  assert.deepEqual(w.takeHeld(), [delta('held text'), DONE]);
  w.flush();
  assert.equal(raw.length, 1, 'takeHeld emptied the buffer; flush has nothing to send');
};

// ---------- B1: doc_read filenames are checked ----------

const BAD_NAME = 'Fake v. Case, 999 So. 3d 5 (Fla. 2012).docx';
const flagsBadCite = (t: string) => (t.includes('999 So. 3d 5') ? result([verdict('Fake v. Case, 999 So. 3d 5 (Fla. 2012)', 'vetoed')]) : CLEAN);

cases.doc_read_with_a_flagged_filename_is_dropped_sent_and_saved = async () => {
  const full = 'Plain answer.';
  const held = [
    delta(full),
    line({ type: 'doc_read_start', filename: BAD_NAME, document_id: 'd1' }),
    line({ type: 'doc_read', filename: BAD_NAME, document_id: 'd1' }),
    line({ type: 'doc_read_start', filename: 'Brief 2024.docx', document_id: 'd2' }),
    line({ type: 'doc_read', filename: 'Brief 2024.docx', document_id: 'd2' }),
    DONE,
  ];
  const events = [
    { type: 'doc_read', filename: BAD_NAME, document_id: 'd1' },
    { type: 'doc_read', filename: 'Brief 2024.docx', document_id: 'd2' },
    { type: 'content', text: full },
  ];
  const out = await finalizeHeldOutput({ held, events, annotations: [], fullText: full, verify: stub(flagsBadCite).verify });
  assert.equal(out.withheld, false, 'a flagged tool string does not withhold the reply');
  // The family is dropped whole (start and result stay paired), like the other checked families.
  assert.deepEqual(sentTypes(out), ['content_delta', '[DONE]']);
  assert.deepEqual(out.savedEvents.map((e) => e.type), ['content']);
  assert.ok(!JSON.stringify([out.linesToSend, out.savedEvents]).includes('999 So. 3d'));
  assert.ok(!JSON.stringify([out.linesToSend, out.savedEvents]).includes('Brief 2024'));
};

cases.doc_read_with_a_clean_filename_passes_unchanged = async () => {
  const full = 'Plain answer.';
  const held = [
    line({ type: 'doc_read_start', filename: 'Brief 2024.docx', document_id: 'd2' }),
    line({ type: 'doc_read', filename: 'Brief 2024.docx', document_id: 'd2' }),
    delta(full),
    DONE,
  ];
  const events = [{ type: 'doc_read', filename: 'Brief 2024.docx', document_id: 'd2' }, { type: 'content', text: full }];
  const { verify, calls } = stub(flagsBadCite);
  const out = await finalizeHeldOutput({ held, events, annotations: [], fullText: full, verify });
  assert.equal(out.withheld, false);
  assert.deepEqual(out.linesToSend, held);
  assert.deepEqual(out.savedEvents, events);
  assert.ok(calls.some((c) => c.includes('Brief 2024.docx')), 'the filename went through Gate 1');
};

cases.doc_read_is_dropped_when_withholding = async () => {
  for (const [verify, message] of [
    [stub(() => result([], { hasVetoes: true, error: 'gate down' })).verify, WITHHELD_MESSAGE],
    [stub(() => result([verdict(SMITH, 'vetoed')])).verify, VETO_WITHHELD_MESSAGE],
  ] as const) {
    const held = [
      line({ type: 'doc_read_start', filename: 'a.docx', document_id: 'd1' }),
      line({ type: 'doc_read', filename: 'a.docx', document_id: 'd1' }),
      delta('x'),
      DONE,
    ];
    const events = [{ type: 'doc_read', filename: 'a.docx', document_id: 'd1' }, { type: 'content', text: 'x' }];
    const out = await finalizeHeldOutput({ held, events, annotations: [], fullText: 'x', verify, logError: () => {} });
    assertWithheld(out, ['a.docx'], message);
    assert.deepEqual(sentTypes(out), ['content_delta', '[DONE]']);
    assert.deepEqual(out.savedEvents.map((e) => e.type), ['content']);
  }
};

// ---------- B7: Gate 1 runs over exactly the text that is sent ----------

const CIT_BLOCK = '<CITATIONS>[{"ref":1}]</CITATIONS>';

cases.cite_only_in_the_sent_text_withholds = async () => {
  // fullText verifies clean; the text actually sent carries a cite the gate vetoes.
  const full = `Clean text.${CIT_BLOCK}`;
  const sent = `Clean text. Per ${SMITH}.`;
  const { verify, calls } = stub((t) => (t.includes('456') ? result([verdict(SMITH, 'vetoed')]) : CLEAN));
  const out = await finalizeHeldOutput({
    held: [delta(sent), DONE], events: [{ type: 'content', text: sent }], annotations: [], fullText: full, verify,
  });
  assertWithheld(out, ['Smith', '456', 'Clean text'], VETO_WITHHELD_MESSAGE);
  assert.equal(out.withheldReason, 'veto');
  assert.deepEqual(calls, [full, sent], 'fullText first, then exactly the sent text');
};

cases.blank_full_text_with_non_blank_sent_text_withholds = async () => {
  const sent = 'Some model words.';
  const { verify } = stub(() => CLEAN);
  const out = await finalizeHeldOutput({
    held: [delta(sent), DONE], events: [{ type: 'content', text: sent }], annotations: [], fullText: '', verify, logError: () => {},
  });
  assertWithheld(out, ['Some model words']);
  assert.equal(out.withheldReason, 'fulltext_mismatch');
  assert.equal(out.verification.error, 'Verification failed.');
  // Whitespace-only fullText is no better.
  const ws = await finalizeHeldOutput({
    held: [delta(sent), DONE], events: [{ type: 'content', text: sent }], annotations: [], fullText: '  \n ', verify, logError: () => {},
  });
  assertWithheld(ws, ['Some model words']);
  assert.equal(ws.withheldReason, 'fulltext_mismatch');
  // A cite in the sent text is caught by the gate run over it, with the veto message.
  const bad = `Per ${SMITH}.`;
  const v = await finalizeHeldOutput({
    held: [delta(bad), DONE], events: [{ type: 'content', text: bad }], annotations: [], fullText: '',
    verify: stub((t) => (t.includes('456') ? result([verdict(SMITH, 'vetoed')]) : CLEAN)).verify,
  });
  assertWithheld(v, ['Smith', '456'], VETO_WITHHELD_MESSAGE);
};

cases.sent_text_that_is_not_the_full_text_withholds_even_when_every_check_is_clean = async () => {
  const stubs = () => stub(() => CLEAN).verify;
  const scenarios: Record<string, { full: string; sent: string }> = {
    extra_text_added: { full: `abc${CIT_BLOCK}`, sent: 'abc EXTRA' },
    text_truncated_no_tag: { full: 'abc def', sent: 'abc' },
    text_dropped_in_the_middle_no_tag: { full: 'abc def ghi', sent: 'abc ghi' },
    text_reordered: { full: 'one two', sent: 'two one' },
    leading_text_missing: { full: `abc${CIT_BLOCK}`, sent: 'bc' },
    sent_blank_but_full_not: { full: 'abc', sent: '' },
  };
  for (const [name, { full, sent }] of Object.entries(scenarios)) {
    const events = sent ? [{ type: 'content', text: sent }] : [];
    const out = await finalizeHeldOutput({
      held: sent ? [delta(sent), DONE] : [DONE], events, annotations: [], fullText: full, verify: stubs(), logError: () => {},
    });
    assert.equal(out.withheld, true, name);
    assert.equal(out.withheldReason, 'fulltext_mismatch', name);
    assert.equal(sentContent(out), WITHHELD_MESSAGE, name);
  }
};

cases.normal_stream_with_a_trailing_citations_block_passes = async () => {
  const parts = ['Per ', GOOD, '.'];
  const visible = parts.join('');
  const full = `${visible}${CIT_BLOCK}`;
  const held = [
    ...parts.map(delta),
    line({ type: 'citations', status: 'final', citations: [caseEntry(2, '1 So. 3d 2'), docEntry()] }),
    line(caseCitationEv(2, '1 So. 3d 2')),
    DONE,
  ];
  const events = [{ type: 'content', text: visible }];
  const { verify, calls } = stub(() => result([verdict(GOOD, 'verified')]));
  const out = await finalizeHeldOutput({ held, events, annotations: [caseEntry(2, '1 So. 3d 2'), docEntry()], fullText: full, verify });
  assert.equal(out.withheld, false);
  assert.deepEqual(out.linesToSend, held, 'replayed byte for byte');
  assert.deepEqual(out.savedEvents, events);
  assert.deepEqual(calls, [full, visible]);
  assert.deepEqual(citationEntries(out).map((c: any) => c.cluster_id ?? c.doc_id), [2, 'doc-0']);
};

cases.multi_iteration_stream_with_hidden_blocks_passes = async () => {
  // Iteration 1 ends in a hidden block; iteration 2 is plain; iteration 3 ends in an unclosed block.
  const full = `One.${CIT_BLOCK}Two. Three.<CITATIONS>[{"ref"`;
  const events = [{ type: 'content', text: 'One.' }, { type: 'content', text: 'Two. Three.' }];
  const out = await finalizeHeldOutput({
    held: [delta('One.'), delta('Two. '), delta('Three.'), DONE], events, annotations: [], fullText: full, verify: stub(() => CLEAN).verify,
  });
  assert.equal(out.withheld, false);
};

cases.partial_tag_text_without_a_complete_tag_is_plain_text = async () => {
  // Only a complete <CITATIONS> tag hides anything; a reply ending in a partial one is plain text sent whole.
  const out = await finalizeHeldOutput({
    held: [delta('Text <CITA'), delta('TIONS'), DONE], events: [{ type: 'content', text: 'Text <CITATIONS' }], annotations: [],
    fullText: 'Text <CITATIONS', verify: stub(() => CLEAN).verify,
  });
  assert.equal(out.withheld, false, 'visible equals fullText exactly (no complete tag)');
};

cases.visible_matches_full_text_alignment = async () => {
  const T = '<CITATIONS>';
  const yes: Array<[string, string]> = [
    ['', ''],
    ['abc', 'abc'],
    ['abc', `abc${T}x</CITATIONS>`],
    ['abc', `abc${T}`],
    ['', `${T}x`],
    ['one two. three', `one ${T}[]</CITATIONS>two. three${T}[]`],
    ['ab', `a${T}x${T}b`],
  ];
  for (const [v, f] of yes) assert.equal(visibleMatchesFullText(v, f), true, JSON.stringify([v, f]));
  const no: Array<[string, string]> = [
    ['', 'abc'],
    ['abc', ''],
    ['abc', 'abd'],
    ['xabc', `abc${T}`],
    ['abcX', `abc${T}zz`],
    ['', `x${T}y`],
    ['b a', 'a b'],
    ['abc', 'abc def'],
    ['abc def', 'abc'],
    ['  ', ''],
  ];
  for (const [v, f] of no) assert.equal(visibleMatchesFullText(v, f), false, JSON.stringify([v, f]));
  // Pathological input gives up (false) instead of running long.
  const many = `${'a'.repeat(300)}${T}`.repeat(400);
  const started = Date.now();
  visibleMatchesFullText('a'.repeat(300) + 'b', many);
  assert.ok(Date.now() - started < 5000, 'bounded work');
};

// ----- Fix 1: every character comparison counts toward one work budget -----

/** Deterministic, realistic prose: sentences of ordinary words. */
function proseOf(chars: number, seed = 0): string {
  const words = ['the', 'court', 'held', 'that', 'a', 'party', 'may', 'not', 'recover', 'under', 'this', 'statute',
    'unless', 'notice', 'was', 'given', 'to', 'the', 'opposing', 'party', 'within', 'the', 'time', 'allowed'];
  const parts: string[] = [];
  let len = 0;
  for (let i = seed; len < chars; i++) {
    const w = words[(i * 7 + (i % 5)) % words.length] + (i % 11 === 10 ? '. ' : ' ');
    parts.push(w);
    len += w.length;
  }
  return parts.join('').slice(0, chars);
}
/** A hidden citations block as the model writes it: JSON with quoted prose, closed by the end tag. */
const hiddenBlock = (quote: string) =>
  `<CITATIONS>[{"ref":1,"cluster_id":123,"quote":"${quote}","reason":"the court held that a party may not recover"}]</CITATIONS>`;

cases.alignment_work_budget_is_bounded_and_exhaustion_is_never_a_match = async () => {
  // The budget is a real, finite number.
  assert.ok(Number.isFinite(ALIGN_WORK_BUDGET) && ALIGN_WORK_BUDGET > 0 && ALIGN_WORK_BUDGET <= 50_000_000, String(ALIGN_WORK_BUDGET));

  // Adversarial: a tag, a long run of one repeated character, and a mismatch only at the very end.
  // From each start q inside the run the old search compared the run to the end of the run, so its
  // total was M + (M-1) + ... + 1 comparisons, in fewer than 200_000 walk calls (the old step cap).
  const M = 60_000;
  const T = '<CITATIONS>';
  const full = `${T}${'a'.repeat(M)}${T}`;
  const visible = `${'a'.repeat(M)}b`;
  const oldComparisons = (M * (M + 1)) / 2;
  assert.ok(oldComparisons > 100 * ALIGN_WORK_BUDGET, `the old code would do ${oldComparisons} comparisons`);
  assert.ok(M < 200_000, 'well under the old step cap, so the old cap never stopped it');
  const started = Date.now();
  const r = alignVisibleToFullText(visible, full);
  const elapsed = Date.now() - started;
  assert.equal(r.matched, false);
  assert.equal(r.exhausted, true, 'the budget ran out');
  assert.ok(r.work <= ALIGN_WORK_BUDGET + 64, `work ${r.work}`);
  assert.equal(visibleMatchesFullText(visible, full), false);
  assert.ok(elapsed < 1000, `bounded wall clock, took ${elapsed} ms`);

  // Through the finalizer: withheld as a mismatch, with the generic message.
  const t2 = Date.now();
  const out = await finalizeHeldOutput({
    held: [delta(visible), DONE], events: [{ type: 'content', text: visible }], annotations: [], fullText: full,
    verify: stub(() => CLEAN).verify, logError: () => {},
  });
  assert.ok(Date.now() - t2 < 2000, 'finalizeHeldOutput stays quick on the adversarial input');
  assertWithheld(out);
  assert.equal(out.withheldReason, 'fulltext_mismatch');

  // Exhaustion is never a match, even when a real alignment exists. Case 1: the one-time scan alone is over budget.
  const big = 'a'.repeat(ALIGN_WORK_BUDGET + 500_000);
  const r1 = alignVisibleToFullText(big, `${big}${hiddenBlock('x')}`);
  assert.deepEqual([r1.matched, r1.exhausted], [false, true]);
  // Case 2: the budget runs out in the middle of the comparison run.
  const mid = 'a'.repeat(Math.floor(ALIGN_WORK_BUDGET * 0.6));
  const r2 = alignVisibleToFullText(mid, `${mid}${hiddenBlock('x')}`);
  assert.deepEqual([r2.matched, r2.exhausted], [false, true]);
  assert.ok(r2.work <= ALIGN_WORK_BUDGET + 64, `work ${r2.work}`);
  assert.equal(visibleMatchesFullText(mid, `${mid}${hiddenBlock('x')}`), false);
  // The same shape just under the budget does match: the budget, not the shape, decides.
  const ok = 'a'.repeat(Math.floor(ALIGN_WORK_BUDGET * 0.4));
  const r3 = alignVisibleToFullText(ok, `${ok}${hiddenBlock('x')}`);
  assert.deepEqual([r3.matched, r3.exhausted], [true, false]);
};

cases.honest_long_replies_stay_far_under_the_work_budget = async () => {
  // (a) 100 KB of prose with one trailing hidden block.
  const prose = proseOf(100_000);
  const fullA = `${prose}${hiddenBlock(prose.slice(0, 300))}`;
  const a = alignVisibleToFullText(prose, fullA);
  assert.deepEqual([a.matched, a.exhausted], [true, false]);
  assert.ok(a.work * 20 <= ALIGN_WORK_BUDGET, `100 KB reply used ${a.work} of ${ALIGN_WORK_BUDGET}`);
  assert.equal(visibleMatchesFullText(prose, fullA), true);

  // (b) Multi-iteration: hidden blocks after iterations 1-3 (the third quotes the start of the next
  // iteration, the case that makes the search try misleading starts), a plain iteration, an iteration that
  // starts with a bare tag, and an unclosed block at the end. About 100 KB shown, 1.5 KB hidden.
  const it = [proseOf(20_000, 1), proseOf(20_000, 2), proseOf(20_000, 3), proseOf(20_000, 4), proseOf(20_000, 5)];
  const fullB =
    `${it[0]}${hiddenBlock(it[0].slice(-200))}` +
    `${it[1]}${hiddenBlock(it[2].slice(0, 400))}` +
    `${it[2]}${hiddenBlock(it[3].slice(0, 400))}` +
    `${it[3]}` +
    `<CITATIONS>[{"ref"` + // an iteration that is only a hidden, unclosed block
    `${it[4]}<CITATIONS>[{"ref":2,"quote":"${it[4].slice(0, 120)}`;
  const visibleB = it.join('');
  const b = alignVisibleToFullText(visibleB, fullB);
  assert.deepEqual([b.matched, b.exhausted], [true, false]);
  assert.ok(b.work * 20 <= ALIGN_WORK_BUDGET, `multi-iteration reply used ${b.work} of ${ALIGN_WORK_BUDGET}`);

  // Both pass the finalizer, quickly, and are not withheld.
  for (const [vis, fullText] of [[prose, fullA], [visibleB, fullB]] as const) {
    const t0 = Date.now();
    const out = await finalizeHeldOutput({
      held: [delta(vis), DONE], events: [{ type: 'content', text: vis }], annotations: [], fullText, verify: stub(() => CLEAN).verify,
    });
    assert.equal(out.withheld, false);
    assert.ok(Date.now() - t0 < 1000);
  }
};

// ----- Fix 2: a veto-withheld reply always carries hasVetoes: true -----

cases.veto_withhold_always_sends_and_saves_hasvetoes_true = async () => {
  const full = `Per ${SMITH}, yes.`;
  const odd = { ...verdict(SMITH, 'vetoed'), status: 'weird' as any };
  const pendingFalse: SseVerificationResult = { verdicts: [verdict(SMITH, 'pending')] as any, hasVetoes: false, hasConditional: false };
  const unknownFalse: SseVerificationResult = { verdicts: [odd] as any, hasVetoes: false, hasConditional: false };
  const draftFalse: SseVerificationResult = { verdicts: [verdict('[draft]', 'vetoed')] as any, hasVetoes: false, hasConditional: false };
  const scenarios: Array<[string, SseVerificationResult, string]> = [
    ['pending, hasVetoes false', pendingFalse, 'veto'],
    ['unknown status, hasVetoes false', unknownFalse, 'veto'],
    ['whole-draft placeholder, hasVetoes false', draftFalse, 'whole_draft_veto'],
  ];
  for (const [name, gate, reason] of scenarios) {
    assert.equal(gate.hasVetoes, false, `${name}: the stub really says false`);
    const before = JSON.stringify(gate);
    const out = await finalizeHeldOutput({
      held: [delta(full), DONE], events: [{ type: 'content', text: full }], annotations: [], fullText: full, verify: stub(() => gate).verify,
    });
    assert.equal(JSON.stringify(gate), before, `${name}: the gate result is not mutated`);
    assertWithheld(out, ['Smith', '456'], VETO_WITHHELD_MESSAGE);
    assert.equal(out.withheldReason, reason, name);
    assert.equal(out.verification.hasVetoes, true, `${name}: sent verification`);
    const saved = out.savedAnnotations.filter(isVerificationRecord);
    assert.equal(saved.length, 1, name);
    assert.equal((saved[0] as any).hasVetoes, true, `${name}: saved record`);
    assert.deepEqual(saved[0], recordOf(out.verification), `${name}: sent and saved are identical`);
    // No other field changed: hasConditional and the verdict count stay as the gate said, citations still scrubbed.
    assert.equal(out.verification.hasConditional, false, name);
    assert.equal(out.verification.verdicts.length, 1, name);
    assert.equal((out.verification.verdicts[0] as any).citation, '', name);
    assert.ok(!('error' in out.verification), name);
  }
  // A veto found only in the text actually sent (second verify) gets the same treatment.
  const sent = `Clean text. Per ${SMITH}.`;
  const out2 = await finalizeHeldOutput({
    held: [delta(sent), DONE], events: [{ type: 'content', text: sent }], annotations: [], fullText: `Clean text.${CIT_BLOCK}`,
    verify: stub((t) => (t.includes('456') ? pendingFalse : CLEAN)).verify,
  });
  assert.equal(out2.withheldReason, 'veto');
  assert.equal(out2.verification.hasVetoes, true);
  assert.deepEqual(out2.savedAnnotations, [recordOf(out2.verification)]);
  // Non-veto withholds are unchanged: a gate error keeps whatever flag the gate set.
  const err = await finalizeHeldOutput({
    held: [delta('x'), DONE], events: [{ type: 'content', text: 'x' }], annotations: [], fullText: 'x', logError: () => {},
    verify: stub(() => result([], { hasVetoes: false, error: 'gate down' })).verify,
  });
  assert.equal(err.withheldReason, 'verification_error');
  assert.equal(err.verification.hasVetoes, false);
  assert.deepEqual(err.savedAnnotations, [recordOf(err.verification)]);
};

// ---------- client-facing verification ----------

const noteVerdict = (citation: string, status: Status, notes: string[]) => ({ ...verdict(citation, status), notes });

cases.vetoed_and_pending_verdicts_have_no_citation_in_client_event = async () => {
  const full = `Per ${SMITH}, yes. Also ${GOOD}. And Pending v. Case, 77 So. 3d 88 (Fla. 2011).`;
  const PENDING = 'Pending v. Case, 77 So. 3d 88 (Fla. 2011)';
  const { verify } = stub((t) =>
    t.includes('456') || t.includes('77 So. 3d')
      ? result([verdict(SMITH, 'vetoed'), verdict(GOOD, 'verified'), verdict(PENDING, 'pending')])
      : result([verdict(GOOD, 'verified')]),
  );
  const out = await finalizeHeldOutput({ held: [delta(full), DONE], events: [{ type: 'content', text: full }], annotations: [], fullText: full, verify });
  assertWithheld(out, ['Smith', '456', 'Pending v.', '77 So.'], VETO_WITHHELD_MESSAGE);
  const vs = out.verification.verdicts as any[];
  assert.equal(vs.length, 3, 'same number of verdicts, same order');
  assert.equal(vs[0].status, 'vetoed');
  assert.equal(vs[0].citation, '');
  assert.equal(vs[1].citation, GOOD, 'verified verdict keeps its citation');
  assert.equal(vs[2].status, 'pending');
  assert.equal(vs[2].citation, '');
  for (const v of [vs[0], vs[2]]) {
    assert.equal(v.gate1_existence, v.status !== 'vetoed', 'gate fields kept');
    assert.equal(v.gate2_quote_accuracy, null);
    assert.deepEqual(Object.keys(v).sort(), Object.keys(verdict(SMITH, 'vetoed')).sort(), 'same shape');
  }
  const blob = JSON.stringify(out.verification);
  assert.ok(!blob.includes('Smith') && !blob.includes('456') && !blob.includes('Pending v.') && !blob.includes('77 So.'), blob);
  assert.equal(out.verification.hasVetoes, true);
  // Same for a withheld outcome.
  const w = await finalizeHeldOutput({
    held: [delta('x'), DONE], events: [{ type: 'content', text: 'x' }], annotations: [], fullText: 'x',
    verify: stub(() => result([verdict('[draft]', 'vetoed'), verdict(SMITH, 'vetoed')])).verify,
  });
  assert.equal(w.withheld, true);
  assert.deepEqual((w.verification.verdicts as any[]).map((v) => v.citation), ['', '']);
};

cases.note_containing_the_cite_is_scrubbed = async () => {
  const notes = [
    `${SMITH} was not found in the Florida index`,
    'No record for 123 So. 3d 456',
    'Caption "Smith v. Jones" does not match',
    'pin cite 123 So. 3d at 460 is outside the opinion',
    'related: Other v. Thing, 9 U.S. 9 (1801) and 45 Fla. L. Weekly D123',
    'Gate 1 failed closed: no match in kingsfield_florida.db',
  ];
  const r = result([noteVerdict(SMITH, 'vetoed', notes), noteVerdict(SMITH, 'pending', [`still ${SMITH}`])]);
  const before = JSON.stringify(r);
  const safe = clientSafeVerification(r);
  assert.equal(JSON.stringify(r), before, 'input is not mutated');
  const v0 = safe.verdicts[0] as any;
  assert.equal(v0.notes.length, notes.length, 'one note out per note in');
  const blob = JSON.stringify(safe);
  for (const leak of ['Smith', 'Jones', '123 So.', '456', '460', '9 U.S.', 'Fla. L. Weekly', 'D123']) {
    assert.ok(!blob.includes(leak), `leaked ${leak}: ${blob}`);
  }
  assert.ok(v0.notes[0].includes(REDACTION_MARKER));
  assert.ok(v0.notes[0].includes('was not found in the Florida index'), 'the reason survives');
  assert.equal(v0.notes[5], notes[5], 'a note with no citation text is untouched');
  assert.ok((safe.verdicts[1] as any).notes[0].startsWith('still '));
  // The whole-draft placeholder is not citation text; "draft" in its notes stays readable.
  const d = clientSafeVerification(result([noteVerdict('[draft]', 'vetoed', ['whole draft vetoed: no verifiable citation'])]));
  assert.equal((d.verdicts[0] as any).citation, '');
  assert.deepEqual((d.verdicts[0] as any).notes, ['whole draft vetoed: no verifiable citation']);
  // Through the finalizer as well.
  const full = `Per ${SMITH}.`;
  const out = await finalizeHeldOutput({
    held: [delta(full), DONE], events: [{ type: 'content', text: full }], annotations: [], fullText: full,
    verify: stub((t) => (t.includes('456') ? result([noteVerdict(SMITH, 'vetoed', [`${SMITH} not found`])]) : CLEAN)).verify,
  });
  assert.ok(!JSON.stringify(out.verification).includes('456'));
};

cases.verified_and_conditional_verdicts_are_unchanged_by_client_safe = async () => {
  const r = result([
    noteVerdict(GOOD, 'verified', [`${GOOD} found`, 'pin 1 So. 3d at 3 ok']),
    noteVerdict(SMITH, 'conditional', [`${SMITH} treated negatively`]),
  ], { hasConditional: true });
  const safe = clientSafeVerification(r);
  assert.deepEqual(safe, r);
  assert.equal(safe.verdicts[0], r.verdicts[0], 'same objects, not copies');
  const empty = clientSafeVerification(CLEAN);
  assert.deepEqual(empty, CLEAN);
  // An unknown status counts as not ok.
  const odd = clientSafeVerification({ verdicts: [{ ...verdict(SMITH, 'vetoed'), status: 'weird' as any }], hasVetoes: true, hasConditional: false });
  assert.equal((odd.verdicts[0] as any).citation, '');
  // And through the finalizer: clean replay returns verified/conditional untouched.
  const full = `Per ${SMITH} and ${GOOD}.`;
  const out = await finalizeHeldOutput({
    held: [delta(full), DONE], events: [{ type: 'content', text: full }], annotations: [], fullText: full,
    verify: stub(() => result([verdict(SMITH, 'conditional'), verdict(GOOD, 'verified')], { hasConditional: true })).verify,
  });
  assert.deepEqual((out.verification.verdicts as any[]).map((v) => v.citation), [SMITH, GOOD]);
};

// ---------- error events ----------

const ERR_RAW = { type: 'error', message: 'OpenAI 429 on gpt-4o: rate limit, key sk-abc123456789012345', provider: 'openai', stack: 'at x' };

function assertErrorKept(out: FinalizeOutput, expectedTypesSent: string[], expectedTypesSaved: string[]) {
  assert.deepEqual(sentTypes(out), expectedTypesSent);
  assert.deepEqual(out.savedEvents.map((e) => e.type), expectedTypesSaved);
  const sentErr = out.linesToSend.filter((l) => l !== DONE).map((l) => JSON.parse(l.slice(6))).filter((e) => e.type === 'error');
  assert.deepEqual(sentErr, [{ type: 'error', message: GENERIC_ERROR_MESSAGE }]);
  assert.deepEqual(out.savedEvents.filter((e) => e.type === 'error'), [{ type: 'error', message: GENERIC_ERROR_MESSAGE }]);
  const blob = JSON.stringify([out.linesToSend, out.savedEvents]);
  for (const f of ['OpenAI', 'gpt-4o', 'sk-abc', 'rate limit', 'provider', 'stack']) assert.ok(!blob.includes(f), `leaked ${f}`);
}

cases.error_event_survives_in_replay_with_generic_message = async () => {
  const full = 'Short reply.';
  const held = [line({ type: 'doc_read_start', filename: 'a.docx' }), line(ERR_RAW), delta(full), DONE];
  const events = [{ type: 'doc_read', filename: 'a.docx' }, ERR_RAW, { type: 'content', text: full }];
  const out = await finalizeHeldOutput({ held, events, annotations: [], fullText: full, verify: stub(() => CLEAN).verify });
  assert.equal(out.withheld, false);
  assertErrorKept(out, ['doc_read_start', 'error', 'content_delta', '[DONE]'], ['doc_read', 'error', 'content']);
  assert.equal(out.linesToSend[1], line({ type: 'error', message: GENERIC_ERROR_MESSAGE }));
};

cases.error_event_survives_in_veto_withhold_with_generic_message = async () => {
  const full = `Per ${SMITH}.`;
  const held = [delta('Per '), line(ERR_RAW), delta(`${SMITH}.`), DONE];
  const events = [ERR_RAW, { type: 'content', text: full }];
  const { verify } = stub((t) => (t.includes('456') ? result([verdict(SMITH, 'vetoed')]) : CLEAN));
  const out = await finalizeHeldOutput({ held, events, annotations: [], fullText: full, verify });
  assert.equal(out.withheld, true);
  assert.equal(sentContent(out), VETO_WITHHELD_MESSAGE);
  assertErrorKept(out, ['error', 'content_delta', '[DONE]'], ['error', 'content']);
};

cases.error_event_survives_in_withhold_with_generic_message = async () => {
  const full = 'Anything the model said.';
  const held = [line({ type: 'doc_read_start', filename: 'a.docx' }), line(ERR_RAW), delta(full), DONE];
  const events = [ERR_RAW, { type: 'content', text: full }];
  const { verify } = stub(() => result([], { hasVetoes: true, error: 'gate down' }));
  const out = await finalizeHeldOutput({ held, events, annotations: [], fullText: full, verify });
  assert.equal(out.withheld, true);
  // doc_read_start is a checked family: dropped when withholding.
  assertErrorKept(out, ['error', 'content_delta', '[DONE]'], ['error', 'content']);
  assert.equal(sentContent(out), WITHHELD_MESSAGE);
};

// ---------- Step 2: generic error, persisted verification record ----------

const RAW_ERR = 'SQLITE_CANTOPEN: unable to open /Users/x/kingsfield_florida.db; CourtListener 503 at https://www.courtlistener.com/api/rest/v4/citation-lookup/ token=abc';
const RAW_PARTS = ['SQLITE_CANTOPEN', 'kingsfield_florida', 'CourtListener', 'courtlistener.com', 'token=abc', '503'];
const noRaw = (value: unknown) => {
  const blob = JSON.stringify(value);
  for (const p of RAW_PARTS) assert.ok(!blob.includes(p), `raw error text leaked (${p}): ${blob.slice(0, 300)}`);
};
const SENT_KEYS_BANNED = ['ref', 'kind', 'filename', 'document_id'];

type LogEntry = { context: string; message: string; name: string | null };
function logSink() {
  const entries: LogEntry[] = [];
  return {
    entries,
    logError: (context: string, error: { name: string | null; message: string }) =>
      void entries.push({ context, message: error.message, name: error.name }),
  };
}

cases.client_safe_replaces_any_error_with_generic_text = async () => {
  const r = result([], { hasVetoes: true, error: RAW_ERR });
  const safe = clientSafeVerification(r);
  assert.equal(safe.error, 'Verification failed.');
  noRaw(safe);
  assert.equal(r.error, RAW_ERR, 'input is not mutated');
  // Whatever the shape of the error text, it is replaced.
  for (const e of ['Verification failed: boom. Treating as unverified.', 'x', 'Reply withheld: streamed and saved text differ']) {
    assert.equal(clientSafeVerification(result([], { hasVetoes: true, error: e })).error, 'Verification failed.');
  }
  // No error stays no error (no key at all), and unknown extra fields are not copied through.
  assert.ok(!('error' in clientSafeVerification(CLEAN)));
  const extra = clientSafeVerification({ ...CLEAN, leak: RAW_ERR } as any);
  assert.ok(!('leak' in extra));
  assert.deepEqual(Object.keys(extra).sort(), ['hasConditional', 'hasVetoes', 'verdicts']);
};

cases.every_verification_failure_path_sends_and_saves_only_the_generic_error = async () => {
  const full = 'Plain answer.';
  const events = [{ type: 'content', text: full }];
  const fail = result([], { hasVetoes: true, error: RAW_ERR });
  const scenarios: Record<string, ReturnType<typeof stub>> = {
    first_verify_error: stub(() => fail),
    first_verify_throw: stub(() => new Error(RAW_ERR)),
    visible_verify_error: stub((t, n) => (n === 0 ? CLEAN : fail)),
    visible_verify_throw: stub((t, n) => (n === 0 ? CLEAN : new Error(RAW_ERR))),
  };
  for (const [name, s] of Object.entries(scenarios)) {
    // The visible_* scenarios carry a hidden <CITATIONS> block, so the sent text is verified on its own.
    const fullText = name.startsWith('visible') ? `${full}<CITATIONS>[]</CITATIONS>` : full;
    const out = await finalizeHeldOutput({
      held: [delta(full), DONE], events: [{ type: 'content', text: full }], annotations: [], fullText, verify: s.verify, logError: () => {},
    });
    assert.equal(out.withheld, true, name);
    assert.equal(out.verification.error, 'Verification failed.', name);
    noRaw([out.linesToSend, out.savedEvents, out.savedAnnotations, out.verification]);
  }
  // Tool-text check that fails: the family is dropped, and the error text goes nowhere.
  const toolHeld = [delta(full), line({ type: 'doc_created', filename: 'Memo 2024.docx', download_url: 'https://x.test/d', document_id: 'd9' }), DONE];
  const out = await finalizeHeldOutput({
    held: toolHeld, events, annotations: [], fullText: full, logError: () => {},
    verify: stub((t) => (t === full ? CLEAN : fail)).verify,
  });
  assert.equal(out.withheld, false);
  assert.deepEqual(sentTypes(out), ['content_delta', '[DONE]']);
  noRaw([out.linesToSend, out.savedEvents, out.savedAnnotations, out.verification]);
};

cases.saved_annotations_hold_exactly_one_verification_record_in_replay_veto_withhold = async () => {
  const full = `Per ${SMITH} and ${GOOD}.`;
  const events = [{ type: 'content', text: full }];
  const cited = [caseEntry(2, '1 So. 3d 2'), docEntry()];
  const outcomes: Record<string, FinalizeOutput> = {
    replay: await finalizeHeldOutput({
      held: [delta(full), DONE], events, annotations: cited, fullText: full,
      verify: stub(() => result([verdict(SMITH, 'conditional'), verdict(GOOD, 'verified')], { hasConditional: true })).verify,
    }),
    veto: await finalizeHeldOutput({
      held: [delta(full), DONE], events, annotations: cited, fullText: full,
      verify: stub(() => result([verdict(SMITH, 'vetoed'), verdict(GOOD, 'verified')])).verify,
    }),
    withhold: await finalizeHeldOutput({
      held: [delta(full), DONE], events, annotations: cited, fullText: full, logError: () => {},
      verify: stub(() => result([], { hasVetoes: true, error: RAW_ERR })).verify,
    }),
    empty_reply: await finalizeHeldOutput({ held: [DONE], events: [], annotations: [], fullText: '', verify: stub(() => CLEAN).verify }),
  };
  assert.equal(outcomes.replay.withheld, false);
  assert.equal(outcomes.veto.withheld, true);
  assert.equal(sentContent(outcomes.veto), VETO_WITHHELD_MESSAGE);
  assert.equal(outcomes.withhold.withheld, true);
  assert.equal(sentContent(outcomes.withhold), WITHHELD_MESSAGE);
  for (const [name, out] of Object.entries(outcomes)) {
    const records = out.savedAnnotations.filter(isVerificationRecord);
    assert.equal(records.length, 1, `${name}: exactly one record`);
    assert.equal(out.savedAnnotations[out.savedAnnotations.length - 1], records[0], `${name}: record is the last element`);
    // Deep-equal to the verification that was sent, plus the type tag.
    assert.deepEqual(records[0], recordOf(out.verification), name);
    assert.deepEqual({ ...(records[0] as any), type: undefined }, { ...out.verification, type: undefined }, `${name}: same fields as finalized.verification`);
    // Invisible to the frontend matchers (a.ref === ref; a.kind !== "case" && a.filename === ...).
    for (const k of SENT_KEYS_BANNED) assert.ok(!(k in (records[0] as object)), `${name}: record has ${k}`);
    assert.deepEqual(
      Object.keys(records[0] as object).sort(),
      ['hasConditional', 'hasVetoes', 'type', 'verdicts', ...(out.verification.error ? ['error'] : [])].sort(),
      name,
    );
    assert.equal((records[0] as any).type, 'verification');
  }
  assert.equal(citationEntries(outcomes.replay).length, 2, 'cited entries still saved ahead of the record');
  assert.equal(citationEntries(outcomes.withhold).length, 0);
  assert.equal(citationEntries(outcomes.veto).length, 0);
  assert.deepEqual(outcomes.empty_reply.savedAnnotations, [{ type: 'verification', verdicts: [], hasVetoes: false, hasConditional: false }]);
  assert.equal((outcomes.withhold.savedAnnotations[0] as any).error, 'Verification failed.');
  noRaw(outcomes.withhold.savedAnnotations);
};

cases.vetoed_verdict_in_the_saved_record_has_empty_citation_and_scrubbed_notes = async () => {
  const PENDING = 'Pending v. Case, 77 So. 3d 88 (Fla. 2011)';
  const full = `Per ${SMITH} and ${GOOD}. Also ${PENDING}.`;
  const rec = result([
    noteVerdict(SMITH, 'vetoed', [`${SMITH} not found in the Florida index`, 'pin cite 123 So. 3d at 460 is outside the opinion']),
    noteVerdict(GOOD, 'verified', [`${GOOD} found`]),
    noteVerdict(PENDING, 'pending', [`still checking ${PENDING}`]),
  ]);
  const out = await finalizeHeldOutput({
    held: [delta(full), DONE], events: [{ type: 'content', text: full }], annotations: [], fullText: full,
    verify: stub((t) => (t.includes('456') || t.includes('77 So.') ? rec : result([verdict(GOOD, 'verified')]))).verify,
  });
  assert.equal(out.withheld, true);
  assert.equal(sentContent(out), VETO_WITHHELD_MESSAGE);
  assert.equal(savedContent(out), VETO_WITHHELD_MESSAGE);
  const saved = out.savedAnnotations.find(isVerificationRecord) as any;
  assert.ok(saved);
  assert.equal(saved.verdicts[0].status, 'vetoed');
  assert.equal(saved.verdicts[0].citation, '');
  assert.equal(saved.verdicts[2].citation, '');
  assert.equal(saved.verdicts[1].citation, GOOD, 'verified verdict keeps its citation');
  assert.ok(saved.verdicts[0].notes[0].includes(REDACTION_MARKER));
  assert.ok(saved.verdicts[0].notes[0].includes('not found in the Florida index'), 'the reason survives');
  const vetoedBlob = JSON.stringify([saved.verdicts[0], saved.verdicts[2]]);
  for (const leak of ['Smith', 'Jones', '123 So.', '456', '460', 'Pending v.', '77 So.', '88']) {
    assert.ok(!vetoedBlob.includes(leak), `leaked ${leak}: ${vetoedBlob}`);
  }
  assert.deepEqual(saved, recordOf(out.verification), 'same object content as the SSE verification');
};

cases.raw_verification_error_goes_to_the_logger_once_per_failure = async () => {
  // First verify returns an error result.
  {
    const log = logSink();
    const out = await finalizeHeldOutput({
      held: [delta('x'), DONE], events: [{ type: 'content', text: 'x' }], annotations: [], fullText: 'x', logError: log.logError,
      verify: stub(() => result([], { hasVetoes: true, error: RAW_ERR })).verify,
    });
    assert.equal(out.verification.error, 'Verification failed.');
    assert.equal(log.entries.length, 1);
    assert.equal(log.entries[0].context, 'first_verify');
    assert.equal(log.entries[0].message, RAW_ERR, 'raw text reaches the server log');
  }
  // First verify throws.
  {
    const log = logSink();
    await finalizeHeldOutput({
      held: [delta('x'), DONE], events: [{ type: 'content', text: 'x' }], annotations: [], fullText: 'x', logError: log.logError,
      verify: stub(() => new Error('kaboom in sqlite')).verify,
    });
    assert.equal(log.entries.length, 1);
    assert.ok(log.entries[0].message.includes('kaboom in sqlite'), log.entries[0].message);
  }
  // The check over the sent text fails: logged as visible_verify; the clean first verify logs nothing.
  {
    const log = logSink();
    const visible = 'Plain answer.';
    const out = await finalizeHeldOutput({
      held: [delta(visible), DONE], events: [{ type: 'content', text: visible }], annotations: [], fullText: `${visible}<CITATIONS>[]</CITATIONS>`, logError: log.logError,
      verify: stub((t, n) => (n === 0 ? CLEAN : result([], { hasVetoes: true, error: RAW_ERR }))).verify,
    });
    assert.equal(out.withheld, true);
    assert.deepEqual(log.entries.map((e) => e.context), ['visible_verify']);
    assert.ok(log.entries[0].message.includes('SQLITE_CANTOPEN'));
    noRaw(out);
  }
  // Tool text check fails: logged as tool_text.
  {
    const log = logSink();
    const s = stub((t) => (t === 'hi' ? CLEAN : result([], { hasVetoes: true, error: RAW_ERR })));
    const out = await finalizeHeldOutput({
      held: [delta('hi'), line({ type: 'doc_created', filename: 'Memo 2024.docx', download_url: 'https://x.test/d', document_id: 'd9' }), DONE],
      events: [{ type: 'content', text: 'hi' }], annotations: [], fullText: 'hi', logError: log.logError, verify: s.verify,
    });
    assert.equal(out.withheld, false);
    // One log per failed verify call (the batch, then each string alone); the clean first call logs nothing.
    assert.equal(log.entries.length, s.calls.length - 1);
    assert.ok(log.entries.length >= 1);
    assert.ok(log.entries.every((e) => e.context === 'tool_text' && e.message.includes('SQLITE_CANTOPEN')));
  }
  // A malformed result is a failure too.
  {
    const log = logSink();
    await finalizeHeldOutput({
      held: [delta('x'), DONE], events: [{ type: 'content', text: 'x' }], annotations: [], fullText: 'x', logError: log.logError,
      verify: (async () => ({ nope: true })) as any,
    });
    assert.equal(log.entries.length, 1);
  }
  // Streamed/saved mismatch is the server's own withhold: logged once.
  {
    const log = logSink();
    const out = await finalizeHeldOutput({
      held: [delta('streamed'), DONE], events: [{ type: 'content', text: 'other' }], annotations: [], fullText: 'streamed', logError: log.logError,
      verify: stub(() => CLEAN).verify,
    });
    assert.equal(out.withheldReason, 'content_mismatch');
    assert.deepEqual(log.entries.map((e) => e.context), ['withheld']);
    assert.equal(out.verification.error, 'Verification failed.');
  }
  // No failure, no log: clean replay, and a plain veto that withholds the reply.
  {
    const log = logSink();
    const full = `Per ${SMITH}.`;
    await finalizeHeldOutput({
      held: [delta('ok'), DONE], events: [{ type: 'content', text: 'ok' }], annotations: [], fullText: 'ok', logError: log.logError, verify: stub(() => CLEAN).verify,
    });
    const vetoed = await finalizeHeldOutput({
      held: [delta(full), DONE], events: [{ type: 'content', text: full }], annotations: [], fullText: full, logError: log.logError,
      verify: stub((t) => (t.includes('456') ? result([verdict(SMITH, 'vetoed')]) : CLEAN)).verify,
    });
    assert.equal(vetoed.withheld, true);
    assert.equal(log.entries.length, 0);
  }
  // A logger that throws never changes the outcome.
  {
    const out = await finalizeHeldOutput({
      held: [delta('x'), DONE], events: [{ type: 'content', text: 'x' }], annotations: [], fullText: 'x',
      logError: () => { throw new Error('log sink down'); },
      verify: stub(() => result([], { hasVetoes: true, error: RAW_ERR })).verify,
    });
    assert.equal(out.withheld, true);
    assert.equal(out.verification.error, 'Verification failed.');
  }
};

// ---------- keepalive ----------

function fakeTimers() {
  const state = { handles: new Map<number, { fn: () => void; ms: number }>(), next: 1, cleared: 0 };
  return {
    state,
    timers: {
      setInterval: (fn: () => void, ms: number) => {
        const id = state.next++;
        state.handles.set(id, { fn, ms });
        return id;
      },
      clearInterval: (h: unknown) => {
        state.cleared++;
        state.handles.delete(h as number);
      },
    },
    tick: () => [...state.handles.values()].forEach((h) => h.fn()),
  };
}

cases.keepalive_pings_each_interval_and_stops_on_flush = async () => {
  const f = fakeTimers();
  const raw: string[] = [];
  const ka = startSseKeepalive((l) => raw.push(l), { timers: f.timers });
  assert.equal([...f.state.handles.values()][0].ms, 15000, 'default interval is 15 s');
  f.tick();
  f.tick();
  assert.deepEqual(raw, [KEEPALIVE_LINE, KEEPALIVE_LINE]);
  assert.equal(KEEPALIVE_LINE, ': ping\n\n');
  ka.stop(); // the route calls this right before releasing the held lines
  f.tick();
  assert.equal(raw.length, 2, 'no ping after stop');
  assert.equal(f.state.handles.size, 0, 'no timer left running');
  assert.equal(ka.active, false);
  ka.stop();
  assert.equal(f.state.cleared, 1, 'stop is idempotent');
};

cases.keepalive_stops_on_abort_error_and_close_paths = async () => {
  // The routes call keepalive.stop() from res "close", the catch block and finally; model each as a stop with no flush.
  for (const path of ['abort', 'error', 'close', 'finally']) {
    const f = fakeTimers();
    const raw: string[] = [];
    const ka = startSseKeepalive((l) => raw.push(l), { timers: f.timers });
    f.tick();
    ka.stop();
    ka.stop();
    f.tick();
    assert.equal(raw.length, 1, path);
    assert.equal(f.state.handles.size, 0, `${path}: timer leaked`);
  }
};

cases.keepalive_writer_failure_stops_the_timer_instead_of_throwing = async () => {
  const f = fakeTimers();
  startSseKeepalive(() => { throw new Error('socket gone'); }, { timers: f.timers });
  f.tick();
  assert.equal(f.state.handles.size, 0);
};

cases.keepalive_real_timers_fire_then_stop_cleanly = async () => {
  const raw: string[] = [];
  const ka = startSseKeepalive((l) => raw.push(l), { intervalMs: 15 });
  await new Promise((r) => setTimeout(r, 80));
  assert.ok(raw.length >= 2, `expected >= 2 pings, got ${raw.length}`);
  ka.stop();
  const n = raw.length;
  await new Promise((r) => setTimeout(r, 60));
  assert.equal(raw.length, n, 'no ping after stop');
};

// ---------- failed / aborted reply marker ----------

cases.failed_reply_record_aborted_is_one_fixed_content_event_and_sends_nothing = async () => {
  const r = failedReplyRecord('aborted');
  assert.deepEqual(r.events, [{ type: 'content', text: ABORTED_MESSAGE }]);
  assert.equal(r.annotations, null);
  assert.deepEqual(r.sseLines, []);
  assert.equal(ABORTED_MESSAGE, 'This reply was stopped before it was completed.');
  assert.notEqual(ABORTED_MESSAGE, GENERIC_ERROR_MESSAGE);
};

cases.failed_reply_record_failed_saves_fixed_strings_and_sends_generic_error_then_done = async () => {
  const r = failedReplyRecord('failed');
  assert.deepEqual(r.events, [
    { type: 'content', text: GENERIC_ERROR_MESSAGE },
    { type: 'error', message: GENERIC_ERROR_MESSAGE },
  ]);
  assert.equal(r.annotations, null);
  assert.deepEqual(r.sseLines, [line({ type: 'error', message: GENERIC_ERROR_MESSAGE }), DONE]);
  assert.equal(GENERIC_ERROR_MESSAGE, 'The reply failed before it could be completed.');
};

cases.failed_reply_record_takes_no_input_and_carries_only_the_fixed_strings = async () => {
  assert.equal(failedReplyRecord.length, 1, 'only the kind parameter');
  const allowed = new Set([ABORTED_MESSAGE, GENERIC_ERROR_MESSAGE, 'content', 'error']);
  const strings = (v: unknown, out: string[] = []): string[] => {
    if (typeof v === 'string') out.push(v);
    else if (Array.isArray(v)) v.forEach((x) => strings(x, out));
    else if (v && typeof v === 'object') Object.values(v).forEach((x) => strings(x, out));
    return out;
  };
  for (const kind of ['aborted', 'failed'] as const) {
    const r = failedReplyRecord(kind);
    // Every string in the saved record is one of the fixed strings or an event type.
    for (const s of strings([r.events, r.annotations])) assert.ok(allowed.has(s), `${kind}: unexpected string ${s}`);
    // Every sent line is the generic error event or [DONE].
    for (const l of r.sseLines) {
      assert.ok(l === DONE || l === line({ type: 'error', message: GENERIC_ERROR_MESSAGE }), `${kind}: unexpected line ${l}`);
    }
  }
  // Extra arguments (a model error, partial text) are ignored; an unknown kind fails closed to 'failed'.
  const sneaky = (failedReplyRecord as any)('aborted', new Error('provider said: secret'), 'partial model text');
  assert.ok(!JSON.stringify(sneaky).includes('secret') && !JSON.stringify(sneaky).includes('partial'));
  assert.deepEqual((failedReplyRecord as any)('weird'), failedReplyRecord('failed'));
};

cases.failed_reply_record_returns_fresh_objects = async () => {
  const a = failedReplyRecord('failed');
  a.events.push({ type: 'content', text: 'tampered' });
  a.sseLines.push('x');
  const b = failedReplyRecord('failed');
  assert.equal(b.events.length, 2);
  assert.equal(b.sseLines.length, 2);
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
