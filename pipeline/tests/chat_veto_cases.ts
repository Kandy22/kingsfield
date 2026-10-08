// Adversary cases for the chat route: what a reload shows after a veto, and what can still reach the client
// or the saved row on the SUCCESS path.
//
// Run once by test_chat_veto_persistence.py under backend's tsx. Stub verifiers, except the "real_gate_*" cases,
// which run the production verify closure (verifyDraftForSse -> verifyDraft -> localGate1Text -> pipeline/gate1.py)
// against the fixture database named by KINGSFIELD_FLORIDA_DB. Supabase and CourtListener are unreachable by
// construction (a Proxy that throws), and every draft used with the real gate holds only fabricated Florida cites,
// which the local gate vetoes before any network call. No LLM, no network.
//
// Prints one JSON line: { results: { caseName: null | "failure text" }, info: { ... } }.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import {
  REDACTION_MARKER,
  VETO_WITHHELD_MESSAGE,
  WITHHELD_MESSAGE,
  finalizeHeldOutput,
  verifyDraftForSse,
  visibleMatchesFullText,
} from '../../backend/src/middleware/hallucination_guard';

// ---------- helpers ----------

const line = (ev: unknown) => `data: ${JSON.stringify(ev)}\n\n`;
const DONE = 'data: [DONE]\n\n';
const delta = (text: string) => line({ type: 'content_delta', text });
const silent = () => {};

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
const result = (verdicts: any[], extra: Record<string, unknown> = {}) => ({
  verdicts,
  hasVetoes: verdicts.some((v) => v.status === 'vetoed' || v.status === 'pending'),
  hasConditional: verdicts.some((v) => v.status === 'conditional'),
  ...extra,
});
const CLEAN = result([]);

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

const sentContent = (out: any): string =>
  out.linesToSend
    .filter((l: string) => l !== DONE)
    .map((l: string) => JSON.parse(l.slice(6)))
    .filter((e: any) => e && e.type === 'content_delta')
    .map((e: any) => e.text)
    .join('');
const savedContent = (out: any): string =>
  out.savedEvents.filter((e: any) => e.type === 'content').map((e: any) => e.text).join('');
const everything = (out: any) => JSON.stringify([out.linesToSend, out.savedEvents, out.savedAnnotations, out.verification]);

/** What chat.ts / projectChat.ts send over SSE after linesToSend (kept in step with the route by the static test). */
const routeVerificationEvent = (out: any) =>
  JSON.parse(JSON.stringify({
    type: 'verification',
    verdicts: out.verification.verdicts,
    hasVetoes: out.verification.hasVetoes,
    hasConditional: out.verification.hasConditional,
    error: out.verification.error,
  }));

/** What chat.ts / projectChat.ts insert on the success path, as the database would hand it back. */
const storedRow = (out: any) =>
  JSON.parse(JSON.stringify({
    chat_id: 'c1',
    role: 'assistant',
    content: out.savedEvents.length ? out.savedEvents : null,
    annotations: out.savedAnnotations,
  }));

// A stand-in gate with the real gate's habit: a vetoed verdict names the cite CORE ("123 So. 3d 456"), not the caption.
const FAKE_VOLUMES = new Set(['123', '999']);
function coreGate(text: string) {
  const seen = new Map<string, any>();
  for (const m of text.matchAll(/(\d{1,4}) So\. 3d (\d{1,5})/g)) {
    if (!seen.has(m[0])) seen.set(m[0], verdict(m[0], FAKE_VOLUMES.has(m[1]) ? 'vetoed' : 'verified'));
  }
  return result([...seen.values()]);
}
const coreVerify = async (t: string) => coreGate(t);

// ---------- the reload path: the real hydrateEditStatuses from chat.ts, run against a stub db ----------

function loadHydrate(): (messages: any[], db: any) => Promise<any[]> {
  const root = process.cwd();
  const src = readFileSync(path.join(root, 'backend', 'src', 'routes', 'chat.ts'), 'utf8');
  const start = src.indexOf('async function hydrateEditStatuses(');
  assert.ok(start >= 0, 'hydrateEditStatuses not found in chat.ts');
  const end = src.indexOf('\n}\n', start);
  assert.ok(end > start, 'end of hydrateEditStatuses not found in chat.ts');
  const ts = src.slice(start, end + 2);
  const req = createRequire(path.join(root, 'backend', 'package.json'));
  let js: string;
  try {
    js = req('esbuild').transformSync(ts, { loader: 'ts' }).code;
  } catch (e1) {
    try {
      js = req('typescript').transpileModule(ts, { compilerOptions: { target: 99 } }).outputText;
    } catch (e2) {
      throw new Error(`no TypeScript transpiler reachable from backend/node_modules (esbuild, typescript): ${String(e1)} / ${String(e2)}`);
    }
  }
  return new Function(`${js}\nreturn hydrateEditStatuses;`)();
}

function stubDb(rows: Record<string, any[]>) {
  const tables: string[] = [];
  return {
    tables,
    from: (table: string) => {
      tables.push(table);
      const q: any = { select: () => q, in: () => Promise.resolve({ data: rows[table] ?? [] }) };
      return q;
    },
  };
}

// ---------- cases ----------

const cases: Record<string, () => Promise<void>> = {};
const info: Record<string, unknown> = {};

/** A withheld reply: the fixed message only, sent and saved; nothing else the model wrote or fetched. */
function assertWholeReplyWithheld(out: any, message: string, label: string) {
  assert.equal(out.withheld, true, `${label}: the reply was not withheld`);
  assert.equal(sentContent(out), message, `${label}: sent text is not the fixed withheld message`);
  assert.equal(savedContent(out), message, `${label}: saved text is not the fixed withheld message`);
  assert.equal(sentContent(out), savedContent(out), `${label}: saved differs from sent`);
  assert.ok(!sentContent(out).includes(REDACTION_MARKER), `${label}: redaction marker in reply text (redaction is gone)`);
  const sentTypes = out.linesToSend.filter((l: string) => l !== DONE).map((l: string) => JSON.parse(l.slice(6)).type);
  for (const t of ['citations', 'case_citation', 'doc_read', 'doc_read_start', 'case_opinions']) {
    assert.ok(!sentTypes.includes(t), `${label}: a ${t} event was sent in a withheld reply (sent: ${sentTypes.join(',')})`);
    assert.ok(!out.savedEvents.some((e: any) => e.type === t), `${label}: a ${t} event was saved in a withheld reply`);
  }
  assert.equal(out.savedEvents.filter((e: any) => e.type === 'content').length, 1, `${label}: more than one content event saved`);
  const nonRecord = out.savedAnnotations.filter((a: any) => !a || a.type !== 'verification');
  assert.deepEqual(nonRecord, [], `${label}: citation/document entries saved in a withheld reply`);
  assert.equal(out.savedAnnotations.length, 1, `${label}: the verification record must be the only annotation`);
}

cases.vetoed_reply_saved_with_veto_and_reload_shows_it = async () => {
  const FAB = 'Smith v. Jones, 123 So. 3d 456 (Fla. 2013)';
  const GOOD = 'Good v. Case, 1 So. 3d 2 (Fla. 2010)';
  const parts = ['As held in Smith v. Jo', 'nes, 123 So. 3d 4', '56 (Fla. 2013), the rule applies. See also ', GOOD, '.'];
  const full = parts.join('');
  assert.ok(full.includes(FAB));
  const entries = [caseEntry(1, '123 So. 3d 456'), caseEntry(2, '1 So. 3d 2'), docEntry()];
  const held = [
    ...parts.map(delta),
    line({ type: 'citations', status: 'final', citations: entries }),
    line(caseCitationEv(1, '123 So. 3d 456')),
    line(caseCitationEv(2, '1 So. 3d 2')),
    line({ type: 'doc_read_start', filename: 'brief.docx', document_id: 'd1' }),
    line({ type: 'doc_read', filename: 'brief.docx', document_id: 'd1' }),
    DONE,
  ];
  const out = await finalizeHeldOutput({
    held,
    events: [
      { type: 'doc_read', filename: 'brief.docx', document_id: 'd1' },
      { type: 'content', text: full },
    ],
    annotations: entries, fullText: full, verify: coreVerify, logError: silent,
  });
  // One vetoed cite withholds the WHOLE reply: no redaction, no surviving case name, holding or sibling cite.
  assertWholeReplyWithheld(out, VETO_WITHHELD_MESSAGE, 'vetoed reply');
  assert.equal(out.withheldReason, 'veto');
  for (const name of ['Smith', 'Jones', 'the rule applies', 'Good v. Case', 'See also', 'As held in']) {
    assert.ok(!everything(out).includes(name), `"${name}" (case name or holding) survived a vetoed reply`);
  }

  // 1. exactly one verification record, last, carrying the veto
  const records = out.savedAnnotations.filter((a: any) => a && a.type === 'verification');
  assert.equal(records.length, 1, 'exactly one verification record is saved');
  const record: any = records[0];
  assert.equal(out.savedAnnotations[out.savedAnnotations.length - 1], record, 'the record is the last annotation');
  assert.equal(record.hasVetoes, true, 'the saved record says the reply had a veto');
  const vetoed = record.verdicts.filter((v: any) => v.status === 'vetoed');
  assert.equal(vetoed.length, 1, `one vetoed verdict in the saved record: ${JSON.stringify(record.verdicts)}`);
  assert.equal(vetoed[0].citation, '', 'a vetoed verdict carries no citation text');
  assert.ok(record.verdicts.some((v: any) => v.status === 'verified' && v.citation === '1 So. 3d 2'), 'the verified cite keeps its verdict');

  // 2. the saved record is the SSE verification event, field for field
  const sse = routeVerificationEvent(out);
  assert.deepEqual(JSON.parse(JSON.stringify(record)), sse, 'saved record differs from the verification event that was sent');

  // 3. the vetoed cite is nowhere: not sent, not saved, not in the verdicts
  const blob = everything(out) + JSON.stringify(sse);
  for (const leak of ['123 So. 3d 456', 'So. 3d 456', '456']) assert.ok(!blob.includes(leak), `vetoed cite text "${leak}" leaked: ${blob.slice(0, 300)}`);
  assert.equal(savedContent(out), sentContent(out), 'saved text equals sent text');
  assert.deepEqual(out.savedAnnotations.filter((a: any) => a.type !== 'verification'), [], 'no case or document entry survives a withheld reply');

  // 4. a reload (the real hydrateEditStatuses, then the client) still shows the veto
  const hydrate = loadHydrate();
  const [m] = await hydrate([storedRow(out)], stubDb({}));
  const shown = (m.annotations as any[]).find((a) => a && a.type === 'verification');
  assert.ok(shown, 'the reloaded message has no verification record');
  assert.equal(shown.hasVetoes, true);
  assert.ok(shown.verdicts.some((v: any) => v.status === 'vetoed'));
  assert.deepEqual(shown, record, 'the reloaded record differs from the one that was saved');
  const reloaded = JSON.stringify(m);
  for (const leak of ['123 So. 3d 456', 'So. 3d 456', '456']) assert.ok(!reloaded.includes(leak), `reloaded message leaks "${leak}"`);
};

cases.withheld_reply_saved_flagged_and_reload_shows_it = async () => {
  const full = 'As held in Smith v. Jones, 123 So. 3d 456 (Fla. 2013), the rule applies.';
  const raw = 'SQLITE_CANTOPEN: unable to open /Users/x/kingsfield_florida.db while checking 123 So. 3d 456; CourtListener 503 token=abc123';
  const out = await finalizeHeldOutput({
    held: [delta(full), DONE], events: [{ type: 'content', text: full }], annotations: [caseEntry(1, '123 So. 3d 456')], fullText: full,
    verify: async () => { throw new Error(raw); }, logError: silent,
  });
  assert.equal(out.withheld, true);
  assert.equal(savedContent(out), WITHHELD_MESSAGE);
  assert.equal(sentContent(out), WITHHELD_MESSAGE);
  const records = out.savedAnnotations.filter((a: any) => a && a.type === 'verification');
  assert.equal(out.savedAnnotations.length, 1, 'only the verification record is saved when the reply is withheld');
  const record: any = records[0];
  assert.equal(record.hasVetoes, true, 'a withheld reply must be saved as unverified');
  assert.equal(record.error, 'Verification failed.');
  assert.deepEqual(JSON.parse(JSON.stringify(record)), routeVerificationEvent(out));
  const hydrate = loadHydrate();
  const [m] = await hydrate([storedRow(out)], stubDb({}));
  assert.deepEqual((m.annotations as any[]).find((a) => a.type === 'verification'), record);
  const blob = everything(out) + JSON.stringify(m);
  for (const leak of ['SQLITE', 'kingsfield_florida', 'CourtListener', 'token=abc', '123 So. 3d', 'Smith', 'rule applies']) {
    assert.ok(!blob.includes(leak), `withheld reply leaks "${leak}"`);
  }
};

cases.clean_reply_saved_with_a_clean_record = async () => {
  const full = 'Per Good v. Case, 1 So. 3d 2 (Fla. 2010), yes.';
  const out = await finalizeHeldOutput({
    held: [delta(full), DONE], events: [{ type: 'content', text: full }], annotations: [], fullText: full, verify: coreVerify, logError: silent,
  });
  assert.equal(out.withheld, false);
  const records = out.savedAnnotations.filter((a: any) => a && a.type === 'verification');
  assert.equal(records.length, 1);
  assert.equal((records[0] as any).hasVetoes, false);
  assert.deepEqual(out.linesToSend, [delta(full), DONE]);
};

cases.reload_patches_edits_and_keeps_the_record = async () => {
  const full = 'Per Smith v. Jones, 123 So. 3d 456 (Fla. 2013), yes.';
  const out = await finalizeHeldOutput({
    held: [delta(full), DONE], events: [{ type: 'content', text: full }], annotations: [], fullText: full, verify: coreVerify, logError: silent,
  });
  const record: any = out.savedAnnotations[out.savedAnnotations.length - 1];
  assert.equal(record.type, 'verification');
  const edit = { kind: 'edit', edit_id: 'e1', document_id: 'd1', version_id: 'v1', status: 'pending', deleted_text: 'a', inserted_text: 'b' };
  const msg = {
    id: 'm1', role: 'assistant',
    content: [{ type: 'doc_edited', filename: 'a.docx', document_id: 'd1', version_id: 'v1', annotations: [edit] }],
    annotations: [edit, record],
  };
  const db = stubDb({ document_edits: [{ id: 'e1', status: 'accepted' }], document_versions: [{ id: 'v1', version_number: 3 }] });
  const [h] = await loadHydrate()([JSON.parse(JSON.stringify(msg))], db);
  assert.equal(h.annotations[0].status, 'accepted', 'the edit status was patched');
  assert.equal(h.annotations[0].version_number, 3);
  assert.equal(h.annotations.length, 2, 'hydration dropped an annotation');
  assert.deepEqual(h.annotations[1], record, 'hydration altered the verification record');
  assert.equal(h.annotations[1].hasVetoes, true);
};

// A tool-created document takes its name from a model-chosen title (generateDocx keeps [A-Za-z0-9 -], 64 chars), and
// the standard follow-up read_document emits doc_read_start / doc_read with that name. doc_created and doc_read are one
// Gate-1-checked family (a flagged string drops the whole family, sent and saved).
cases.generated_doc_filename_is_not_a_gate1_free_channel = async () => {
  const F = 'Doe v Roe 999 So 3d 999 Fla 2015 Memo.docx';
  const full = 'I drafted the memo for you.';
  const held = [
    line({ type: 'doc_created_start', filename: F }),
    line({ type: 'doc_created', filename: F, download_url: 'https://x.test/dl/abc', document_id: 'd9', version_id: 'v1', version_number: 1 }),
    line({ type: 'doc_read_start', filename: F, document_id: 'd9' }),
    line({ type: 'doc_read', filename: F, document_id: 'd9' }),
    delta(full),
    DONE,
  ];
  const events = [
    { type: 'doc_created', filename: F, download_url: 'https://x.test/dl/abc', document_id: 'd9', version_id: 'v1', version_number: 1 },
    { type: 'doc_read', filename: F, document_id: 'd9' },
    { type: 'content', text: full },
  ];
  const flagsCite = (t: string) => /999\s+So\.?\s+3d\s+999/.test(t);
  const out = await finalizeHeldOutput({
    held, events, annotations: [], fullText: full, logError: silent,
    verify: async (t: string) => (flagsCite(t) ? result([verdict('999 So 3d 999', 'vetoed')]) : CLEAN),
  });
  assert.equal(out.withheld, false);
  const types = out.linesToSend.map((l: string) => (l === DONE ? '[DONE]' : JSON.parse(l.slice(6)).type));
  const blob = everything(out);
  assert.ok(
    !flagsCite(blob),
    `a model-chosen filename carrying a Gate-1-flagged cite reached the client and/or the saved row; sent types: ${types.join(',')}; ` +
      `saved types: ${out.savedEvents.map((e: any) => e.type).join(',')}`,
  );
};

// doc_read / doc_read_start alone (no doc_created) with a flagged model-chosen name: the family is dropped whole, sent and saved.
cases.doc_read_alone_with_flagged_filename_is_dropped = async () => {
  const F = 'Doe v Roe 999 So 3d 999 Fla 2015 Memo.docx';
  const full = 'Here is what the file says.';
  const flagsCite = (t: string) => /999\s+So\.?\s+3d\s+999/.test(t);
  const out = await finalizeHeldOutput({
    held: [
      line({ type: 'doc_read_start', filename: F, document_id: 'd9' }),
      line({ type: 'doc_read', filename: F, document_id: 'd9' }),
      delta(full), DONE,
    ],
    events: [{ type: 'doc_read', filename: F, document_id: 'd9' }, { type: 'content', text: full }],
    annotations: [], fullText: full, logError: silent,
    verify: async (t: string) => (flagsCite(t) ? result([verdict('999 So 3d 999', 'vetoed')]) : CLEAN),
  });
  assert.equal(out.withheld, false, 'a flagged tool string drops its family; it does not touch the clean reply');
  assert.ok(!flagsCite(everything(out)), 'the flagged doc_read filename reached the client or the saved row');
  const sentTypes = out.linesToSend.filter((l: string) => l !== DONE).map((l: string) => JSON.parse(l.slice(6)).type);
  assert.ok(!sentTypes.includes('doc_read') && !sentTypes.includes('doc_read_start'), `doc_read family sent: ${sentTypes.join(',')}`);
  assert.ok(!out.savedEvents.some((e: any) => e.type === 'doc_read'), 'doc_read saved');
  assert.equal(sentContent(out), full, 'the clean reply text still goes out unchanged');
};

// Every non-ok verdict kind withholds the whole reply with the veto message, never a redacted remainder.
cases.pending_unknown_and_draft_verdicts_withhold_whole_reply = async () => {
  const full = 'Per Roe v. Wade Fake, 1 So. 3d 2 (Fla. 2010), the rule applies.';
  const entries = [caseEntry(1, '1 So. 3d 2'), docEntry()];
  const mk = (verdicts: any[], hasVetoes: boolean) => ({ verdicts, hasVetoes, hasConditional: false });
  const variants: Record<string, any> = {
    pending: result([verdict('1 So. 3d 2', 'pending')]),
    unknown_status: mk([{ ...verdict('1 So. 3d 2', 'verified'), status: 'who_knows' }], false),
    missing_status: mk([{ ...verdict('1 So. 3d 2', 'verified'), status: undefined }], false),
    whole_draft_placeholder: mk([verdict('[draft]', 'vetoed')], true),
    veto_plus_verified: result([verdict('1 So. 3d 2', 'verified'), verdict('9 So. 3d 9', 'vetoed')]),
  };
  for (const [name, r] of Object.entries(variants)) {
    const out = await finalizeHeldOutput({
      held: [delta(full), line({ type: 'citations', status: 'final', citations: entries }), line(caseCitationEv(1, '1 So. 3d 2')), DONE],
      events: [{ type: 'content', text: full }], annotations: entries, fullText: full, verify: async () => r, logError: silent,
    });
    assertWholeReplyWithheld(out, VETO_WITHHELD_MESSAGE, name);
    for (const leak of ['Roe v. Wade', 'the rule applies']) assert.ok(!everything(out).includes(leak), `${name}: "${leak}" survived`);
    // Only where the gate itself said hasVetoes. For unknown/missing status with hasVetoes:false (an inconsistent
    // result no real gate returns) the guard passes the flag through unchanged; reported, not asserted.
    if (r.hasVetoes) assert.equal(out.verification.hasVetoes, true, `${name}: the verification event must report the veto`);
    else info[`withheld_reply_hasVetoes_for_${name}`] = out.verification.hasVetoes;
    assert.ok(out.verification.verdicts.every((v: any) => v.status === 'verified' || v.status === 'conditional' || v.citation === ''),
      `${name}: a non-ok verdict carries citation text`);
  }
};

cases.conditional_verdict_passes_unchanged = async () => {
  const full = 'Per Good v. Case, 1 So. 3d 2 (Fla. 2010), yes.';
  const entries = [caseEntry(1, '1 So. 3d 2')];
  const out = await finalizeHeldOutput({
    held: [delta(full), line({ type: 'citations', status: 'final', citations: entries }), DONE],
    events: [{ type: 'content', text: full }], annotations: entries, fullText: full,
    verify: async () => result([verdict('1 So. 3d 2', 'conditional')]), logError: silent,
  });
  assert.equal(out.withheld, false, 'conditional must not withhold');
  assert.equal(sentContent(out), full);
  assert.equal(savedContent(out), full);
  assert.equal(out.verification.hasConditional, true);
};

// ---------- sent text vs. the text Gate 1 saw (stubs only) ----------

// Gate 1 over fullText is clean, but the text actually streamed carries a fabricated cite the verified text lacks.
cases.cite_only_in_sent_text_withholds = async () => {
  const full = 'Clean answer with no authority.';
  const sent = `${full} See Smith v. Jones, 123 So. 3d 456 (Fla. 2013).`;
  const out = await finalizeHeldOutput({
    held: [delta(sent), DONE], events: [{ type: 'content', text: sent }], annotations: [], fullText: full,
    verify: coreVerify, logError: silent,
  });
  assertWholeReplyWithheld(out, VETO_WITHHELD_MESSAGE, 'cite only in sent text');
  assert.equal(out.withheldReason, 'veto');
  assert.ok(!everything(out).includes('Smith'), 'case name from the unverified sent text survived');
  assert.ok(!everything(out).includes('456'), 'fabricated cite from the sent text survived');
  // Same, with the sent text split across deltas and a hidden CITATIONS block in fullText.
  const full2 = 'Clean.<CITATIONS>[]</CITATIONS>';
  const parts = ['Clean. See Smith v. Jo', 'nes, 123 So. 3d 4', '56 (Fla. 2013).'];
  const out2 = await finalizeHeldOutput({
    held: [...parts.map(delta), DONE], events: [{ type: 'content', text: parts.join('') }], annotations: [], fullText: full2,
    verify: coreVerify, logError: silent,
  });
  assertWholeReplyWithheld(out2, VETO_WITHHELD_MESSAGE, 'cite only in split sent text');
};

cases.blank_fulltext_with_nonblank_sent_text_withholds = async () => {
  for (const full of ['', '   ', '\n']) {
    const sent = 'Totally unchecked prose that Gate 1 never saw.';
    const out = await finalizeHeldOutput({
      held: [delta(sent), DONE], events: [{ type: 'content', text: sent }], annotations: [], fullText: full,
      verify: coreVerify, logError: silent,
    });
    assert.equal(out.withheld, true, `blank fullText ${JSON.stringify(full)} with non-blank sent text was sent`);
    assert.equal(out.withheldReason, 'fulltext_mismatch');
    assert.equal(sentContent(out), WITHHELD_MESSAGE);
    assert.equal(savedContent(out), WITHHELD_MESSAGE);
    assert.ok(!everything(out).includes('unchecked prose'), 'sent text survived a mismatch');
    assert.equal(out.verification.hasVetoes, true, 'a mismatch must be saved as unverified');
  }
};

// Gate 1 is clean on both strings, yet the sent text is not the verified text with only hidden parts removed.
cases.sent_text_not_derived_from_fulltext_withholds = async () => {
  const variants: Array<[string, string, string]> = [
    ['rewritten', 'Answer A.', 'Answer B, plus advice nobody checked.'],
    ['appended', 'Answer A.', 'Answer A. And one more sentence.'],
    ['truncated_no_tag', 'Answer A. Answer B.', 'Answer A.'],
    ['hidden_stretch_not_at_a_tag', 'Keep. Dropped. <CITATIONS>[]</CITATIONS>', 'Keep.'],
    ['reordered', 'One. Two.<CITATIONS>[]</CITATIONS>', 'Two. One.'],
  ];
  for (const [name, full, sent] of variants) {
    const out = await finalizeHeldOutput({
      held: [delta(sent), DONE], events: [{ type: 'content', text: sent }], annotations: [], fullText: full,
      verify: coreVerify, logError: silent,
    });
    assert.equal(out.withheld, true, `${name}: sent text that is not the verified text went out`);
    assert.equal(out.withheldReason, 'fulltext_mismatch', name);
    assert.equal(sentContent(out), WITHHELD_MESSAGE, name);
    assert.equal(savedContent(out), WITHHELD_MESSAGE, name);
  }
};

// Control: the normal hidden <CITATIONS> block (and several of them) is not a false mismatch.
cases.hidden_citations_block_matches = async () => {
  const full = 'Plain answer.\n<CITATIONS>\n[{"ref": 1}]\n</CITATIONS>';
  const out = await finalizeHeldOutput({
    held: [delta('Plain answer.\n'), DONE], events: [{ type: 'content', text: 'Plain answer.\n' }], annotations: [], fullText: full,
    verify: coreVerify, logError: silent,
  });
  assert.equal(out.withheld, false, `a hidden CITATIONS block must not withhold: ${out.withheldReason}`);
  assert.equal(sentContent(out), 'Plain answer.\n');
};

cases.visible_matches_full_text_rules = async () => {
  const T = '<CITATIONS>';
  const yes: Array<[string, string]> = [
    ['', ''], ['abc', 'abc'], ['Hi.', `Hi.${T}x</CITATIONS>`], ['AB', `A${T}x</CITATIONS>B`],
  ];
  const no: Array<[string, string]> = [
    ['hello', ''], ['', 'hello'], ['Hi.', 'Hi. there'], ['Hi. there', 'Hi.'], ['Hi.', `Hi. there${T}x`],
    ['ba', 'ab'], ['abd', `abc${T}x`],
  ];
  for (const [v, f] of yes) assert.equal(visibleMatchesFullText(v, f), true, `should match: visible=${JSON.stringify(v)} full=${JSON.stringify(f)}`);
  for (const [v, f] of no) assert.equal(visibleMatchesFullText(v, f), false, `should NOT match: visible=${JSON.stringify(v)} full=${JSON.stringify(f)}`);
};

// ---------- the real gate ----------

function requireRealGate() {
  assert.ok(process.env.KINGSFIELD_FLORIDA_DB, 'KINGSFIELD_FLORIDA_DB is not set: the real-gate cases need the fixture database');
}

let supabaseTouched = false;
const noSupabase: any = new Proxy({}, {
  get: () => {
    supabaseTouched = true;
    throw new Error('harness: the real-gate cases must never reach Supabase');
  },
});
const realVerify = (text: string) => verifyDraftForSse(text, { courtListenerToken: '', supabase: noSupabase });

/** Fabricated "NNN So. 3d NNN" cites, however dressed, after the kind of normalisation a renderer or the gate applies. */
function leakedCites(blob: string): string[] {
  let t = blob.normalize('NFKC');
  t = t.replace(/\p{Cf}/gu, '');
  t = t.replace(/&#(\d+);/g, (_m, n) => String.fromCodePoint(Number(n))).replace(/&amp;/g, '&').replace(/&nbsp;/g, ' ');
  t = t.replace(/<!--[\s\S]*?-->/g, '').replace(/<[^>]*>/g, '');
  return [...t.matchAll(/(\d{3})\W{0,3}So\W{0,3}3d\W{0,3}(\d{3})/g)].map((m) => `${m[1]} So. 3d ${m[2]}`);
}

function noteReal(name: string, out: any) {
  info[name] = { withheld: out.withheld, reason: out.withheldReason, sent: sentContent(out).slice(0, 400) };
}

/**
 * No fabricated cite anywhere. With `vetoed: true` (the draft holds fabricated Florida cites the local gate vetoes) the
 * WHOLE reply must be withheld with VETO_WITHHELD_MESSAGE, sent and saved, and none of `absent` (fabricated case names,
 * holdings) may remain anywhere in what is sent or saved.
 */
function assertNoFabricatedCite(out: any, label: string, opts: { vetoed?: boolean; absent?: string[] } = {}) {
  assert.equal(supabaseTouched, false, 'harness reached Supabase');
  const leaked = leakedCites(everything(out));
  assert.deepEqual(leaked, [], `${label}: fabricated cite(s) reached the client or the saved row: ${leaked.join('; ')}`);
  assert.equal(savedContent(out), sentContent(out), `${label}: saved text differs from sent text`);
  assert.ok(out.savedAnnotations.some((a: any) => a && a.type === 'verification'), `${label}: no verification record saved`);
  if (opts.vetoed) {
    assertWholeReplyWithheld(out, VETO_WITHHELD_MESSAGE, label);
    assert.equal(out.verification.hasVetoes, true, `${label}: the verification event must still report the veto`);
    const blob = everything(out);
    for (const s of opts.absent ?? []) assert.ok(!blob.includes(s), `${label}: "${s}" (case name or holding) survived a vetoed reply`);
  }
}

cases.real_gate_markdown_and_split_deltas = async () => {
  requireRealGate();
  const parts = [
    'As held in *Doe v. Ro', 'e*, 999 So. 3', 'd 999 (Fla. 2015), the rule applies. ',
    'See also **Fake v. Case**, 888 So. 3d 111 (Fla. 2014).',
  ];
  const full = parts.join('');
  const out = await finalizeHeldOutput({
    held: [...parts.map(delta), DONE], events: [{ type: 'content', text: full }], annotations: [], fullText: full, verify: realVerify, logError: silent,
  });
  noteReal('real_markdown_split', out);
  assertNoFabricatedCite(out, 'markdown+split', {
    vetoed: true, absent: ['Doe v. Ro', 'Fake v. Case', 'the rule applies', 'See also'],
  });
};

cases.real_gate_obfuscation_battery = async () => {
  requireRealGate();
  const variants = [
    'Zero-width: Doe v. Roe, 111 So.​ 3d 111 (Fla. 2015).',
    'Full-width: Doe v. Roe, ２２２ So. 3d ２２２ (Fla. 2015).',
    'Comment: Doe v. Roe, 333 So<!-- c -->. 3d 333 (Fla. 2015).',
    'Entity: Doe v. Roe, 444 So. 3d &#52;44 (Fla. 2015).',
    'Link: [Doe v. Roe, 555 So. 3d 555 (Fla. 2015)](https://example.test/x).',
    'Spaces: Doe v. Roe, 666 So.­ 3d 666 (Fla. 2015).',
    '| Table | Doe v. Roe | 777 So. 3d 777 (Fla. 2015) |',
  ];
  const full = variants.join('\n\n');
  const out = await finalizeHeldOutput({
    held: [delta(full), DONE], events: [{ type: 'content', text: full }], annotations: [], fullText: full, verify: realVerify, logError: silent,
  });
  noteReal('real_obfuscation', out);
  assertNoFabricatedCite(out, 'obfuscation battery', { vetoed: true, absent: ['Doe v. Roe'] });
};

cases.real_gate_plain_cite_with_pin = async () => {
  requireRealGate();
  const full = 'In Doe v. Roe, 999 So. 3d 999, 1003 (Fla. 2015), the court held that the claim fails.';
  const out = await finalizeHeldOutput({
    held: [delta(full), DONE], events: [{ type: 'content', text: full }], annotations: [], fullText: full, verify: realVerify, logError: silent,
  });
  noteReal('real_plain_with_pin', out);
  assertNoFabricatedCite(out, 'plain cite with pin', {
    vetoed: true, absent: ['Doe v. Roe', 'the court held', 'claim fails'],
  });
};

cases.real_gate_cite_only_in_the_citations_block = async () => {
  requireRealGate();
  const quote = 'see Doe v. Roe, 999 So. 3d 999 (Fla. 2015)';
  const visible = 'Plain answer.\n';
  const full = `${visible}<CITATIONS>\n[{"ref": 1, "doc_id": "doc-0", "quotes": [{"page": 1, "quote": "${quote}"}]}]\n</CITATIONS>`;
  const entries = [docEntry(quote)];
  const out = await finalizeHeldOutput({
    held: [delta(visible), line({ type: 'citations', status: 'final', citations: entries }), DONE],
    events: [{ type: 'content', text: visible }], annotations: entries, fullText: full, verify: realVerify, logError: silent,
  });
  noteReal('real_citations_block_only', out);
  assertNoFabricatedCite(out, 'cite only in the CITATIONS block');
};

// Information for the report, not an assertion: does the production gate flag the generated-document filename above?
cases.real_gate_probe_generated_filename = async () => {
  requireRealGate();
  const r = await realVerify('Doe v Roe 999 So 3d 999 Fla 2015 Memo.docx');
  info.real_gate_flags_generated_filename = { hasVetoes: r.hasVetoes, verdicts: r.verdicts.map((v: any) => v.status), error: r.error ?? null };
};

// ---------- run ----------

async function main() {
  const results: Record<string, string | null> = {};
  for (const [name, fn] of Object.entries(cases)) {
    try {
      await fn();
      results[name] = null;
    } catch (e: any) {
      results[name] = String(e?.message ?? e).slice(0, 900);
    }
  }
  const text = JSON.stringify({ results, info });
  process.stdout.write(`${text}\n`, () => process.exit(0));
}

void main();
