// Cases for hallucination_guard.ts finalizeHeldOutput / startSseKeepalive / redaction.
// Run by test_chat_guard.py through backend/node_modules/.bin/tsx. Stub verifiers only:
// no Supabase, CourtListener, LLM or Python gate. Prints {caseName: null | "failure text"}.

import assert from 'node:assert/strict';
import {
  GENERIC_ERROR_MESSAGE,
  KEEPALIVE_LINE,
  REDACTION_MARKER,
  WITHHELD_MESSAGE,
  citeKey,
  clientSafeVerification,
  createBufferingSseWriter,
  finalizeHeldOutput,
  redactCitations,
  startSseKeepalive,
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

function assertWithheld(out: FinalizeOutput, forbidden: string[] = []) {
  assert.equal(out.withheld, true);
  assert.deepEqual(
    out.linesToSend.filter((l) => l.includes('content_delta')),
    [delta(WITHHELD_MESSAGE)],
  );
  assert.equal(out.linesToSend[out.linesToSend.length - 1], DONE);
  assert.equal(sentContent(out), WITHHELD_MESSAGE);
  assert.equal(savedContent(out), WITHHELD_MESSAGE);
  assert.deepEqual(out.savedAnnotations, []);
  const blob = JSON.stringify([out.linesToSend, out.savedEvents, out.savedAnnotations]);
  for (const f of forbidden) assert.ok(!blob.includes(f), `leaked: ${f}`);
}

// ---------- cases ----------

const cases: Record<string, () => Promise<void>> = {};

cases.citation_split_across_deltas_is_redacted = async () => {
  const parts = ['As held in Smith v. Jo', 'nes, 123 So. 3d 4', '56 (Fla. 2013), the rule applies. See also ', GOOD, '.'];
  const full = parts.join('');
  const { verify, calls } = stub((t) =>
    t.includes('123 So. 3d') || t.includes('Smith v. Jo') ? result([verdict(SMITH, 'vetoed'), verdict(GOOD, 'verified')]) : result([verdict(GOOD, 'verified')]),
  );
  const held = [...parts.map(delta), DONE];
  const out = await finalizeHeldOutput({ held, events: [{ type: 'content', text: full }], annotations: [], fullText: full, verify });
  assert.equal(out.withheld, false);
  const text = sentContent(out);
  assert.ok(text.includes(REDACTION_MARKER), text);
  assert.ok(!text.includes('456') && !text.includes('Smith v. Jones'), text);
  assert.ok(text.includes(GOOD), text);
  assert.equal(out.linesToSend.filter((l) => l.includes('content_delta')).length, 1, 'ONE content_delta');
  assert.equal(out.linesToSend[out.linesToSend.length - 1], DONE);
  assert.equal(savedContent(out), text, 'saved equals sent');
  assert.equal(calls.length, 2, 'initial verify plus re-verify of the redacted text');
  assert.equal(calls[1], text, 're-verify runs over the exact text that is sent');
  assert.equal(out.verification.hasVetoes, true, 'verification event still reports the veto');
};

cases.redaction_tolerates_whitespace_markdown_and_links = async () => {
  const text =
    'One: **Smith v. Jones**,\n123  So. 3d\n456 (Fla. 2013) here. ' +
    'Two: [Smith v. Jones, 123 So. 3d 456 (Fla. 2013)](us-case-9) there. ' +
    'Three: *Smith* v. _Jones_, 123 So. 3d 456 (Fla. 2013).';
  const out = redactCitations(text, [SMITH]);
  assert.ok(out !== null);
  assert.ok(!out!.includes('456') && !out!.includes('us-case-9'), out!);
  assert.equal(out!.split(REDACTION_MARKER).length - 1, 3, out!);
  assert.ok(out!.startsWith('One: '));
};

cases.link_whose_label_held_a_removed_cite_is_collapsed = async () => {
  const out = redactCitations('Read [see Smith v. Jones, 123 So. 3d 456 (Fla. 2013) and more](us-case-9) now.', [SMITH]);
  assert.equal(out, `Read ${REDACTION_MARKER} now.`);
};

cases.redaction_does_not_match_a_longer_page_number = async () => {
  assert.equal(redactCitations('See Roe v. Doe, 100 So. 3d 555 (Fla. 2012).', ['Roe v. Doe, 100 So. 3d 55 (Fla. 2012)']), null);
  assert.equal(redactCitations('x 100 So. 3d 55 y', ['100 So. 3d 55']), `x ${REDACTION_MARKER} y`);
};

cases.overlapping_vetoed_cites_merge_into_one_marker = async () => {
  const out = redactCitations(`See ${SMITH} ok.`, [SMITH, '123 So. 3d 456 (Fla. 2013)']);
  assert.equal(out, `See ${REDACTION_MARKER} ok.`);
};

cases.vetoed_cite_not_located_withholds = async () => {
  const full = 'A reply with no matching text at all.';
  const { verify } = stub(() => result([verdict(SMITH, 'vetoed')]));
  const out = await finalizeHeldOutput({
    held: [delta(full), DONE], events: [{ type: 'content', text: full }], annotations: [], fullText: full, verify,
  });
  assertWithheld(out, ['A reply with no matching']);
  assert.equal(out.withheldReason, 'veto_not_located');
};

cases.short_cite_after_removed_authority_withholds_via_reverify = async () => {
  const full = `${SMITH}. Later, Smith, 123 So. 3d at 460.`;
  const { verify, calls } = stub((t, n) =>
    n === 0 ? result([verdict(SMITH, 'vetoed')]) : result([verdict('Smith, 123 So. 3d at 460', 'vetoed')]),
  );
  const out = await finalizeHeldOutput({
    held: [delta(full), DONE], events: [{ type: 'content', text: full }], annotations: [caseEntry(1, '123 So. 3d 456')], fullText: full, verify,
  });
  assertWithheld(out, ['Smith', '460']);
  assert.equal(out.withheldReason, 'reverify_failed');
  assert.equal(calls.length, 2);
};

cases.reverify_error_or_throw_withholds = async () => {
  for (const second of [result([], { error: 'Verification failed: boom.', hasVetoes: true }), new Error('kaboom')]) {
    const full = `${SMITH}. Done.`;
    const { verify } = stub((t, n) => (n === 0 ? result([verdict(SMITH, 'vetoed')]) : second));
    const out = await finalizeHeldOutput({
      held: [delta(full), DONE], events: [{ type: 'content', text: full }], annotations: [], fullText: full, verify,
    });
    assertWithheld(out);
    assert.equal(out.withheldReason, 'reverify_failed');
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
  assert.equal(out.verification.error, 'Verification failed: db down. Treating as unverified.');
  // Pure status survives: doc_read events and the scrubbed (counts-only) CourtListener result.
  const types = sentTypes(out);
  assert.deepEqual(types, ['doc_read_start', 'doc_read', 'courtlistener_get_cases', 'content_delta', '[DONE]']);
  const getCases = JSON.parse(out.linesToSend[2].slice(6));
  assert.deepEqual(getCases, { type: 'courtlistener_get_cases', cluster_ids: [5], case_count: 1, opinion_count: 1, cases: [] });
  assert.deepEqual(out.savedEvents.map((e) => e.type), ['doc_read', 'content']);
};

cases.throw_withholds = async () => {
  const secret = 'Model text with Smith v. Jones, 123 So. 3d 456 (Fla. 2013).';
  const { verify } = stub(() => new Error('exploded'));
  const out = await finalizeHeldOutput({ held: [delta(secret), DONE], events: [{ type: 'content', text: secret }], annotations: [], fullText: secret, verify });
  assertWithheld(out, ['Smith']);
  assert.match(out.verification.error ?? '', /exploded/);
  assert.equal(out.verification.hasVetoes, true);
};

cases.draft_placeholder_veto_withholds = async () => {
  const secret = 'Anything the model said.';
  const { verify } = stub(() => result([verdict('[draft]', 'vetoed')]));
  const out = await finalizeHeldOutput({ held: [delta(secret), DONE], events: [{ type: 'content', text: secret }], annotations: [], fullText: secret, verify });
  assertWithheld(out, ['Anything the model']);
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
  assert.equal(out.withheld, false);
  assert.equal(sentContent(out), `Per ${REDACTION_MARKER}, yes.`);
};

cases.conditional_and_verified_replay_unchanged = async () => {
  const parts = ['Per ', SMITH, ' and ', GOOD, '.'];
  const full = parts.join('');
  const held = [
    line({ type: 'doc_read_start', filename: 'a.docx', document_id: 'd1' }),
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
  assert.deepEqual(out.savedAnnotations, annotations);
  assert.equal(calls.length, 1);
  assert.equal(out.verification.hasConditional, true);
};

cases.vetoed_and_unmatched_entries_dropped_from_citations_and_case_citation = async () => {
  const full = `${SMITH} and ${GOOD}.`;
  const entries = [
    caseEntry(1, '123 So. 3d 456'), // vetoed
    caseEntry(2, '1 So. 3d 2'), // verified
    caseEntry(3, '9 U.S. 9'), // matches no verdict at all
    caseEntry(4, null), // no citation at all
    docEntry(), // user's own document: passes
    { type: 'citation_data', ref: 7, cluster_id: 7, citation: '123 So. 3d 456' }, // no kind: treated as case law
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
  const { verify } = stub((t) => (t.includes('456') ? result([verdict(SMITH, 'vetoed'), verdict(GOOD, 'verified')]) : result([verdict(GOOD, 'verified')])));
  const out = await finalizeHeldOutput({ held, events: [{ type: 'content', text: full }], annotations: entries, fullText: full, verify });
  assert.equal(out.withheld, false);
  const parsed = out.linesToSend.filter((l) => l !== DONE).map((l) => JSON.parse(l.slice(6)));
  const citationsEvs = parsed.filter((e) => e.type === 'citations');
  assert.equal(citationsEvs.length, 3, 'started/partial/final all still sent');
  assert.deepEqual(citationsEvs[0].citations, []);
  assert.deepEqual(citationsEvs[1].citations.map((c: any) => c.cluster_id), [2]);
  assert.deepEqual(citationsEvs[2].citations.map((c: any) => c.cluster_id ?? c.doc_id), [2, 'doc-0']);
  assert.deepEqual(parsed.filter((e) => e.type === 'case_citation').map((e) => e.cluster_id), [2]);
  assert.deepEqual(out.savedAnnotations.map((c: any) => c.cluster_id ?? c.doc_id), [2, 'doc-0']);
};

cases.document_entry_quoting_a_removed_cite_is_dropped = async () => {
  const full = `Per ${SMITH}.`;
  const annotations = [docEntry(`as stated, ${SMITH}`), docEntry('clean quote')];
  const { verify } = stub((t) => (t.includes('456') ? result([verdict(SMITH, 'vetoed')]) : CLEAN));
  const out = await finalizeHeldOutput({
    held: [delta(full), line({ type: 'citations', status: 'final', citations: annotations }), DONE],
    events: [{ type: 'content', text: full }], annotations, fullText: full, verify,
  });
  assert.equal(out.savedAnnotations.length, 1);
  assert.equal((out.savedAnnotations[0] as any).quote, 'clean quote');
  assert.ok(!JSON.stringify(out.linesToSend).includes('456'));
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
  const { verify } = stub((t) => (t.includes('456') ? result([verdict(SMITH, 'vetoed')]) : CLEAN));
  const out = await finalizeHeldOutput({ held, events, annotations: [caseEntry(1, '123 So. 3d 456'), docEntry()], fullText: full1 + full2, verify });
  assert.equal(out.withheld, false);
  const sent = sentContent(out);
  assert.equal(sent, `First part. Then ${REDACTION_MARKER} and more.`);
  assert.equal(savedContent(out), sent);
  // ONE content event at the first content position, other content dropped, reasoning and case_opinions gone, order kept.
  assert.deepEqual(out.savedEvents.map((e) => e.type), ['content', 'doc_read']);
  assert.deepEqual(sentTypes(out), ['content_delta', 'doc_read_start', 'doc_read', 'citations', '[DONE]']);
  assert.deepEqual(out.savedAnnotations.map((c: any) => c.doc_id), ['doc-0']);
  const blob = JSON.stringify([out.linesToSend, out.savedEvents]);
  assert.ok(!blob.includes('private thoughts') && !blob.includes('456'));
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
  assert.deepEqual(sentTypes(out), ['workflow_applied', 'doc_read_start', 'courtlistener_verify_citations', 'content_delta', '[DONE]']);
  assert.deepEqual(JSON.parse(out.linesToSend[2].slice(6)), { type: 'courtlistener_verify_citations', citation_count: 2, match_count: 1 });
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
  assert.equal(out.withheld, false);
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

cases.error_event_survives_in_redact_with_generic_message = async () => {
  const full = `Per ${SMITH}.`;
  const held = [delta('Per '), line(ERR_RAW), delta(`${SMITH}.`), DONE];
  const events = [ERR_RAW, { type: 'content', text: full }];
  const { verify } = stub((t) => (t.includes('456') ? result([verdict(SMITH, 'vetoed')]) : CLEAN));
  const out = await finalizeHeldOutput({ held, events, annotations: [], fullText: full, verify });
  assert.equal(out.withheld, false);
  assert.equal(out.redactedCitations, 1);
  assertErrorKept(out, ['content_delta', 'error', '[DONE]'], ['error', 'content']);
};

cases.error_event_survives_in_withhold_with_generic_message = async () => {
  const full = 'Anything the model said.';
  const held = [line({ type: 'doc_read_start', filename: 'a.docx' }), line(ERR_RAW), delta(full), DONE];
  const events = [ERR_RAW, { type: 'content', text: full }];
  const { verify } = stub(() => result([], { hasVetoes: true, error: 'gate down' }));
  const out = await finalizeHeldOutput({ held, events, annotations: [], fullText: full, verify });
  assert.equal(out.withheld, true);
  assertErrorKept(out, ['doc_read_start', 'error', 'content_delta', '[DONE]'], ['error', 'content']);
  assert.equal(sentContent(out), WITHHELD_MESSAGE);
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
