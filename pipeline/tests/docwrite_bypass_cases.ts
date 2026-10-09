// Adversary cases for tabular-docwrite-verify, part B: Gate 1 before document writes.
// Driven by test_docwrite_bypass.py (one tsx process). Prints "DOCWRITE_REPORT=" + JSON {caseName: null | failureText}.
//
// What is REAL here: chatTools.ts (runToolCalls), hallucination_guard.ts (gateCellContent, finalizeHeldOutput,
// createBufferingSseWriter, createLimiter), docxTrackedChanges.ts (the real tracked-changes engine), the docx and jszip
// packages (generate_docx builds a real .docx in memory), and, for the "real_*" and "edit_*" cases, the REAL Gate 1:
// local_sqlite_gate.localGate1Text -> pipeline/gate1.py --text against the fixture database built by the Python test
// (env DOCWRITE_DB). What is stubbed: storage (records every uploaded byte, serves them back), Supabase (recording fake
// that logs every non-select query), the model client, CourtListener and MCP modules, and the second half of
// verifyDraftForSse (the CourtListener / cache / currency gates: a local pass becomes "verified", a fall-through
// "conditional", a veto "vetoed"; no network).
//
// The strongest oracle: after a write the stored document is READ BACK (accepted-view body text, as read_document sees
// it) and run through the real Gate 1. A written document that reads back with a vetoed citation is a leak, whatever
// the gate saw in the tool arguments. The gate is never mutated; its call order is asserted in the .py file.

import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import path from 'node:path';

// ---------- helpers ----------

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v));

const verdict = (citation: string, status: string) => ({
  citation,
  status,
  gate1_existence: status !== 'vetoed',
  gate2_quote_accuracy: null,
  gate3_currency: null,
  gate4_jurisdiction_fit: null,
  notes: [] as string[],
});
const result = (verdicts: any[], extra: Record<string, unknown> = {}): any => ({
  verdicts,
  hasVetoes: verdicts.some((v) => v.status === 'vetoed' || v.status === 'pending'),
  hasConditional: verdicts.some((v) => v.status === 'conditional'),
  ...extra,
});
const CLEAN = result([]);

const FAB = 'Doe v. Roe, 999 So. 3d 999 (Fla. 2015)';
const FAB_CORE = '999 So. 3d 999';
const FAB_NO_PERIODS = '999 So 3d 999';
const SMITH_CITE = 'Smith v. State, 100 So. 3d 200 (Fla. 2012)'; // a real record in the fixture database

/** Stub verifier: vetoes any text carrying the fabricated cite (with or without periods). */
function fabVerify(text: string): any {
  return text.includes(FAB_CORE) || text.includes(FAB_NO_PERIODS) ? result([verdict(FAB, 'vetoed')]) : CLEAN;
}

// ---------- chatTools.ts with its dependencies stubbed ----------

const ROOT = process.cwd();
const nodeRequire = createRequire(path.join(ROOT, 'backend', 'package.json'));
const CHAT_TOOLS = path.join(ROOT, 'backend', 'src', 'lib', 'chatTools.ts');
const GUARD_PATH = path.join(ROOT, 'backend', 'src', 'middleware', 'hallucination_guard.ts');
const GATE_PATH = path.join(ROOT, 'backend', 'src', 'verification', 'local_sqlite_gate.ts');
const DTC_PATH = path.join(ROOT, 'backend', 'src', 'lib', 'docxTrackedChanges.ts');
const DB: string = process.env.DOCWRITE_DB as string;
const SRC_PATH = 'documents/u1/d1/a.docx';

type Op = { table: string; op: 'select' | 'insert' | 'update' | 'delete'; payload?: any; filters: any[][] };

const S: {
  db: any;
  verify: (text: string) => any;
  verified: string[];
  uploads: Array<{ key: string; contentType: string; bytes: Buffer }>;
  files: Map<string, Buffer>;
  activePath: string;
  downloads: string[];
  timeline: string[];
  dbPath: string;
  gateLog: string[];
  mcpCalls: Array<{ name: string; args: unknown }>;
} = {} as any;

function resetStubs() {
  S.db = undefined;
  S.verify = () => CLEAN;
  S.verified = [];
  S.uploads = [];
  S.files = new Map();
  S.activePath = SRC_PATH;
  S.downloads = [];
  S.timeline = [];
  S.dbPath = DB;
  S.gateLog = [];
  S.mcpCalls = [];
}
resetStubs();

const realGuard = nodeRequire(GUARD_PATH);
const gateMod = nodeRequire(GATE_PATH);
const STUBS: Record<string, any> = {
  './storage': {
    uploadFile: async (key: string, bytes: any, contentType: string) => {
      S.timeline.push('upload');
      const copy = Buffer.from(new Uint8Array(bytes));
      S.uploads.push({ key, contentType, bytes: copy });
      S.files.set(key, copy);
      if (key.includes('/edits/')) S.activePath = key;
    },
    downloadFile: async (p: string) => {
      S.downloads.push(p);
      const b = S.files.get(p);
      return b ? b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength) : new Uint8Array([1, 2, 3]).buffer;
    },
    generatedDocKey: (u: string, d: string, f: string) => `generated/${u}/${d}/${f}`,
    storageKey: (u: string, d: string, f: string) => `documents/${u}/${d}/${f}`,
  },
  './convert': { convertedPdfKey: (u: string, d: string) => `pdf/${u}/${d}.pdf` },
  './supabase': { createServerSupabase: () => S.db },
  './downloadTokens': { buildDownloadUrl: (k: string, f: string) => `https://dl.test/${k}?f=${encodeURIComponent(f)}` },
  './documentVersions': {
    attachActiveVersionPaths: async () => {},
    loadActiveVersion: async () => ({
      storage_path: S.activePath,
      filename: 'a.docx',
      pdf_storage_path: null,
      file_type: 'docx',
      size_bytes: 3,
      page_count: 1,
    }),
  },
  './courtlistener': {
    getCourtlistenerCaseOpinions: async () => {
      throw new Error('network');
    },
    getCourtlistenerCases: async () => {
      throw new Error('network');
    },
    searchCourtlistenerCaseLaw: async () => {
      throw new Error('network');
    },
    verifyCourtlistenerCitations: async () => {
      throw new Error('network');
    },
  },
  './legalSourcesTools/courtlistenerTools': {
    COURTLISTENER_SYSTEM_PROMPT: '',
    COURTLISTENER_TOOLS: [],
    COURTLISTENER_TOOL_NAMES: {
      searchCaseLaw: 'courtlistener_search_case_law',
      getCases: 'courtlistener_get_cases',
      findInCase: 'courtlistener_find_in_case',
      readCase: 'courtlistener_read_case',
      verifyCitations: 'courtlistener_verify_citations',
    },
  },
  './mcpConnectors': {
    buildUserMcpTools: async () => [],
    // Records what would be sent to an external connector (a possible document write outside the three gated tools).
    executeMcpToolCall: async (_userId: string, name: string, args: unknown) => {
      S.mcpCalls.push({ name, args });
      return { content: JSON.stringify({ ok: true }), event: { connector_name: 'c', tool_name: 't', status: 'ok' } };
    },
  },
  './llm': {
    streamChatWithTools: async () => {
      throw new Error('model not available');
    },
    resolveModel: (m: unknown) => m ?? 'stub-model',
    DEFAULT_MAIN_MODEL: 'stub-model',
  },
  // The real guard with only the Gate 1 verifier replaced (chatTools calls verifyDraftForSse itself).
  '../middleware/hallucination_guard': {
    ...realGuard,
    verifyDraftForSse: (text: string, _opts: unknown) => {
      S.timeline.push('verify');
      S.verified.push(text);
      return S.verify(text);
    },
  },
  // NOTE: './docxTrackedChanges' is deliberately NOT stubbed: the real engine applies the real edits.
};

const ModuleCtor: any = nodeRequire('module');
const origLoad = ModuleCtor._load;
ModuleCtor._load = function (request: string, parent: any, ...rest: unknown[]) {
  if (parent && parent.filename === CHAT_TOOLS && Object.prototype.hasOwnProperty.call(STUBS, request)) {
    return STUBS[request];
  }
  return origLoad.call(this, request, parent, ...rest);
};
const chatTools = nodeRequire(CHAT_TOOLS);
ModuleCtor._load = origLoad;
const dtc = nodeRequire(DTC_PATH);

const FIXED: string = chatTools.DOC_WRITE_REFUSED_MESSAGE;
const FIXED_RESULT = JSON.stringify({ ok: false, error: FIXED });

// ---------- the real Gate 1 as a verifier ----------

/** The real local Gate 1 over `text`; veto -> vetoed, pass -> verified, fall_through -> conditional (no network). */
async function realGate1(text: string): Promise<any> {
  const rs: any[] = await gateMod.localGate1Text(text, { dbPath: S.dbPath });
  S.gateLog.push(rs.map((r) => `${r.verdict}:${r.reason}:${String(r.text ?? '').slice(0, 50)}`).join(' | ') || '(no citations)');
  return result(
    rs.map((r) =>
      verdict(r.text || '[draft]', r.verdict === 'veto' ? 'vetoed' : r.verdict === 'pass' ? 'verified' : 'conditional'),
    ),
  );
}

// ---------- fakes ----------

async function quiet<T>(fn: () => Promise<T>): Promise<T> {
  const orig = { log: console.log, info: console.info, warn: console.warn, error: console.error };
  for (const k of Object.keys(orig) as Array<keyof typeof orig>) (console as any)[k] = () => {};
  try {
    return await fn();
  } finally {
    Object.assign(console, orig);
  }
}

/** Recording Supabase fake: every query is logged; non-select queries also land on the timeline. */
function makeDb() {
  const ops: Op[] = [];
  const answer = (op: Op): { data?: any; error?: any } => {
    if (op.op === 'select') {
      if (op.table === 'documents') return { data: { id: 'd1' } };
      return { data: null };
    }
    if (op.op === 'insert') {
      const rows = Array.isArray(op.payload) ? op.payload : [op.payload];
      if (op.table === 'documents') {
        const out = rows.map((_: unknown, i: number) => ({ id: `n${i + 1}` }));
        return { data: Array.isArray(op.payload) ? out : out[0] };
      }
      if (op.table === 'document_versions') {
        const out = rows.map((r: any, i: number) => ({ id: `v${i + 1}`, document_id: r.document_id }));
        return { data: Array.isArray(op.payload) ? out : out[0] };
      }
      if (op.table === 'document_edits') {
        return { data: rows.map((r: any, i: number) => ({ id: `e${i}`, ...r })) };
      }
    }
    return {};
  };
  const chain = (state: Op): any =>
    new Proxy(function () {}, {
      get(_t, prop) {
        if (prop === 'then') {
          return (res: any, rej: any) => {
            ops.push(state);
            if (state.op !== 'select') S.timeline.push(`write:${state.table}:${state.op}`);
            const r = answer(state);
            return Promise.resolve({ data: r.data ?? null, error: r.error ?? null }).then(res, rej);
          };
        }
        if (prop === 'insert' || prop === 'update' || prop === 'delete') {
          return (payload?: unknown) => {
            state.op = prop as Op['op'];
            state.payload = payload === undefined ? undefined : clone(payload);
            return chain(state);
          };
        }
        if (prop === 'upsert') {
          return (payload?: unknown) => {
            state.op = 'insert';
            state.payload = payload === undefined ? undefined : clone(payload);
            return chain(state);
          };
        }
        return (...args: unknown[]) => {
          state.filters.push([String(prop), ...args]);
          return chain(state);
        };
      },
    });
  return { from: (table: string) => chain({ table, op: 'select', filters: [] }), ops };
}

const writesOf = (db: any) => db.ops.filter((o: Op) => o.op !== 'select');

/** Nothing written anywhere: no storage object, no insert / update / delete / upsert on any table. */
function assertNothingWritten(label: string) {
  assert.deepEqual(S.uploads.map((u) => u.key), [], `${label}: a storage object was written`);
  assert.deepEqual(writesOf(S.db), [], `${label}: a table was written`);
  assert.ok(!S.timeline.some((t) => t === 'upload' || t.startsWith('write:')), `${label}: timeline shows a write`);
}

const call = (name: string, args: unknown, id = `call-${name}`) => ({
  id,
  function: { name, arguments: JSON.stringify(args) },
});

const DOC_INDEX = () => ({ 'doc-0': { document_id: 'd1', filename: 'a.docx' } });
const DOC_STORE = () => new Map([['doc-0', { storage_path: SRC_PATH, file_type: 'docx', filename: 'a.docx' }]]);

async function run(calls: any[], opts: { turnEditState?: any } = {}) {
  const writes: string[] = [];
  const out = await quiet(() =>
    chatTools.runToolCalls(
      calls,
      DOC_STORE(),
      'u1',
      S.db,
      (s: string) => writes.push(s),
      undefined,
      undefined,
      DOC_INDEX(),
      opts.turnEditState ?? new Map(),
      'p1',
    ),
  );
  return { ...out, writes };
}

const contents = (out: any): string[] => out.toolResults.map((r: any) => String(r.content));

/** A tiny real .docx: one plain run per paragraph. */
async function makeDocx(paragraphs: string[]): Promise<Buffer> {
  const mod = nodeRequire('jszip');
  const JSZip = mod.default ?? mod;
  const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const zip = new JSZip();
  zip.file(
    '[Content_Types].xml',
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/></Types>',
  );
  zip.file(
    'word/document.xml',
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' +
      paragraphs.map((p) => `<w:p><w:r><w:t xml:space="preserve">${esc(p)}</w:t></w:r></w:p>`).join('') +
      '</w:body></w:document>',
  );
  return zip.generateAsync({ type: 'nodebuffer' });
}

/** Accepted-view body text of the document most recently uploaded (what read_document / a reader sees). */
async function lastUploadText(): Promise<string> {
  const u = S.uploads[S.uploads.length - 1];
  return dtc.extractDocxBodyText(u.bytes);
}

const collapse = (s: string) => s.replace(/\s+/g, ' ').trim();

/** The refused result for every tool call in `out`, with nothing written. On a miss, reads the document back through the real gate. */
async function expectRefused(out: any, label: string) {
  const c = contents(out);
  const refused = c.length >= 1 && c.every((x) => x === FIXED_RESULT);
  if (!refused) {
    let readback = '(nothing uploaded)';
    let gate = 'n/a';
    if (S.uploads.length) {
      readback = await lastUploadText();
      const g = await realGate1(readback);
      gate = JSON.stringify(g.verdicts.map((v: any) => `${v.status}:${v.citation}`));
    }
    assert.fail(
      `${label}: NOT REFUSED (LEAK unless the tool result below is an engine error, which would mean the test setup is wrong). ` +
        `tool result(s): ${JSON.stringify(c).slice(0, 300)}; uploads=${S.uploads.length}; ` +
        `the stored document reads back as ${JSON.stringify(readback.slice(0, 500))}; ` +
        `real Gate 1 on that text: ${gate}; gate calls: ${S.gateLog.join(' // ')}`,
    );
  }
  assertNothingWritten(label);
}

/** The stored document must read back clean under the real gate. */
async function expectReadsBackClean(label: string) {
  assert.ok(S.uploads.length >= 1, `${label}: nothing was written`);
  const text = await lastUploadText();
  const g = await realGate1(text);
  const bad = g.verdicts.filter((v: any) => v.status !== 'verified' && v.status !== 'conditional');
  assert.ok(
    !g.hasVetoes && !g.error && bad.length === 0,
    `${label}: the stored document reads back with a vetoed citation. text=${JSON.stringify(text.slice(0, 500))}; gate=${S.gateLog[S.gateLog.length - 1]}`,
  );
}

const GOOD_TITLE = 'Service Agreement';
const genArgs = (sections: unknown[], over: Record<string, unknown> = {}) => ({ title: GOOD_TITLE, sections, ...over });
const P_SMITH = ['Intro paragraph.', `See ${SMITH_CITE}.`];

async function runEdits(paras: string[], edits: Array<Record<string, unknown>>) {
  S.files.set(SRC_PATH, await makeDocx(paras));
  S.activePath = SRC_PATH;
  // One tool call per edit, in one batch (one assistant turn): the turn-scoped version is reused after the first.
  const calls = edits.map((e, i) => call('edit_document', { doc_id: 'doc-0', edits: [e] }, `e${i}`));
  return run(calls, { turnEditState: new Map() });
}

const cases: Record<string, () => Promise<void>> = {};

// ===================================================================================================================
// A. generate_docx, real Gate 1
// ===================================================================================================================

cases.real_control_valid_cite_is_written_and_reads_back_clean = async () => {
  // Non-vacuity: the real gate must let a record that exists through, or every refusal below proves nothing.
  S.db = makeDb();
  S.verify = realGate1;
  const out = await run([call('generate_docx', genArgs([{ content: `As held below. See ${SMITH_CITE}.` }]))]);
  const r = JSON.parse(contents(out)[0]);
  assert.equal(r.filename, 'Service Agreement.docx', `control refused or failed: ${contents(out)[0]} gate=${S.gateLog.join(' // ')}`);
  assert.equal(S.uploads.length, 1);
  assert.equal(S.verified.length, 1);
  assert.equal(S.timeline[0], 'verify', 'the gate ran before the first write');
  await expectReadsBackClean('control');
};

cases.real_fabricated_cite_in_prose_is_refused = async () => {
  S.db = makeDb();
  S.verify = realGate1;
  const out = await run([call('generate_docx', genArgs([{ content: `As held below. See ${FAB}.` }]))]);
  await expectRefused(out, 'fabricated cite in prose');
};

cases.real_upper_case_fabricated_cite_is_refused = async () => {
  S.db = makeDb();
  S.verify = realGate1;
  const out = await run([call('generate_docx', genArgs([{ content: 'AS HELD BELOW. SEE DOE V. ROE, 999 SO. 3D 999 (FLA. 2015).' }]))]);
  await expectRefused(out, 'upper-case fabricated cite');
};

cases.real_missing_database_fails_closed_for_a_valid_cite = async () => {
  S.db = makeDb();
  S.verify = realGate1;
  S.dbPath = '/nonexistent/dir/kingsfield_florida.db';
  const out = await run([call('generate_docx', genArgs([{ content: `As held below. See ${SMITH_CITE}.` }]))]);
  await expectRefused(out, 'missing database');
};

cases.real_cite_split_heading_then_content_is_refused = async () => {
  // Natural key order (heading, content): the two are adjacent paragraphs on the page and adjacent in the gated text.
  S.db = makeDb();
  S.verify = realGate1;
  const out = await run([
    call('generate_docx', genArgs([{ heading: 'Doe v. Roe, 999 So.', level: 2, content: '3d 999 (Fla. 2015).' }])),
  ]);
  await expectRefused(out, 'split heading/content (natural key order)');
};

cases.real_cite_split_heading_then_content_in_unnatural_key_order_is_refused = async () => {
  // Same document, JSON keys written content-first. The renderer always puts the heading before the content, so the page
  // reads "Doe v. Roe, 999 So." / "3d 999 (Fla. 2015)." whatever the key order. The gate must follow the page, not the keys.
  S.db = makeDb();
  S.verify = realGate1;
  const out = await run([
    call('generate_docx', genArgs([{ content: '3d 999 (Fla. 2015).', heading: 'Doe v. Roe, 999 So.', level: 2 }])),
  ]);
  await expectRefused(out, 'split heading/content (content-first key order)');
};

cases.real_cite_split_table_then_content_in_unnatural_key_order_is_refused = async () => {
  // Renderer order inside a section is heading, table, content. Keys written content-first put the table after it in the
  // gated text, so the tail of the cite ("3d 999 ...") precedes its head ("Doe v. Roe, 999 So.") there.
  S.db = makeDb();
  S.verify = realGate1;
  const out = await run([
    call(
      'generate_docx',
      genArgs([{ content: '3d 999 (Fla. 2015).', table: { headers: ['Doe v. Roe, 999 So.'], rows: [] } }]),
    ),
  ]);
  await expectRefused(out, 'split table/content (content-first key order)');
};

cases.real_cite_split_down_a_table_column_is_refused = async () => {
  // Natural order, one column: row 1 ends the head of the cite, row 2 starts its tail. Adjacent in reading order.
  S.db = makeDb();
  S.verify = realGate1;
  const out = await run([
    call(
      'generate_docx',
      genArgs([{ heading: 'Authority', level: 2, table: { headers: ['Cite'], rows: [['Doe v. Roe, 999 So.'], ['3d 999 (Fla. 2015).']] } }]),
    ),
  ]);
  await expectRefused(out, 'split down a table column');
};

// ===================================================================================================================
// B. edit_document, real engine, real Gate 1, read-back oracle
// ===================================================================================================================

cases.edit_control_clean_edit_is_written_and_reads_back_clean = async () => {
  S.db = makeDb();
  S.verify = realGate1;
  const out = await runEdits(P_SMITH, [
    { find: 'Intro paragraph.', replace: 'Intro text.', context_before: '', context_after: '', reason: 'tighten' },
  ]);
  const r = JSON.parse(contents(out)[0]);
  assert.equal(r.ok, true, `control edit did not apply: ${contents(out)[0]} gate=${S.gateLog.join(' // ')}`);
  assert.equal(S.uploads.length, 1);
  assert.equal(S.timeline[0], 'verify', 'the gate ran before the first write');
  await expectReadsBackClean('control edit');
};

cases.edit_fabricated_replacement_is_refused = async () => {
  S.db = makeDb();
  S.verify = realGate1;
  const out = await runEdits(P_SMITH, [
    { find: 'Intro paragraph.', replace: `Intro. See ${FAB}.`, context_before: '', context_after: '', reason: 'add authority' },
  ]);
  await expectRefused(out, 'fabricated replacement');
};

cases.edit_changing_one_token_of_the_users_real_cite_is_refused = async () => {
  // The user's paragraph holds a real, verified cite. The edit swaps the volume: find "100" -> "999", no context. The tool
  // arguments hold only the digits "999"; the document afterwards holds "Smith v. State, 999 So. 3d 200 (Fla. 2012)".
  S.db = makeDb();
  S.verify = realGate1;
  const out = await runEdits(P_SMITH, [
    { find: '100', replace: '999', context_before: '', context_after: '', reason: 'correct the volume' },
  ]);
  await expectRefused(out, 'volume changed in the user\'s cite');
};

cases.edit_changing_the_court_of_the_users_real_cite_is_refused = async () => {
  // Smith is a Florida Supreme Court record; "(Fla. 1st DCA 2012)" makes it a court mismatch once it reads back.
  S.db = makeDb();
  S.verify = realGate1;
  const out = await runEdits(P_SMITH, [
    { find: '(Fla. 2012)', replace: '(Fla. 1st DCA 2012)', context_before: '', context_after: '', reason: 'court' },
  ]);
  await expectRefused(out, 'court changed in the user\'s cite');
};

cases.edit_adding_an_out_of_range_pin_to_the_users_real_cite_is_refused = async () => {
  // Smith spans pages 200-215. find "200" -> "200, 999" leaves "100 So. 3d 200, 999 (Fla. 2012)" in the document.
  S.db = makeDb();
  S.verify = realGate1;
  const out = await runEdits(P_SMITH, [
    { find: '200', replace: '200, 999', context_before: '', context_after: '', reason: 'pin cite' },
  ]);
  await expectRefused(out, 'out-of-range pin added to the user\'s cite');
};

cases.edit_filling_a_citation_template_in_two_calls_never_stores_a_vetoed_cite = async () => {
  // A template with blanks: "See Doe v. Roe, ___ So. 3d ___ (Fla. 2015)." Two calls in one turn fill one blank each with
  // "999". Each call alone carries only a fragment. Either a call is refused, or the stored document must read back clean.
  S.db = makeDb();
  S.verify = realGate1;
  const out = await runEdits(['Intro paragraph.', 'See Doe v. Roe, ___ So. 3d ___ (Fla. 2015).'], [
    { find: '___', replace: '999', context_before: 'Roe, ', context_after: ' So.', reason: 'fill volume' },
    { find: '___', replace: '999', context_before: '', context_after: '', reason: 'fill page' },
  ]);
  const c = contents(out);
  const refusals = c.filter((x) => x === FIXED_RESULT).length;
  if (S.uploads.length === 0) {
    assert.ok(refusals > 0, `template fill: nothing written and nothing refused; engine problem? results=${JSON.stringify(c).slice(0, 400)}`);
    return;
  }
  // The turn's final document (the second call overwrites the first call's file in place).
  const text = collapse(await lastUploadText());
  if (text.includes(FAB_CORE)) {
    const g = await realGate1(text);
    assert.fail(
      `LEAK: both fragment edits were written and the document reads back as ${JSON.stringify(text.slice(0, 400))}; ` +
        `real Gate 1 on it: ${S.gateLog[S.gateLog.length - 1]}; hasVetoes=${g.hasVetoes}; tool results: ${JSON.stringify(c).slice(0, 300)}`,
    );
  }
};

// ===================================================================================================================
// C. stub-gate cases: seams around the gate
// ===================================================================================================================

/** runToolCalls behind the same buffering writer and finalizeHeldOutput that chat.ts / projectChat.ts / tabular.ts use. */
async function throughRoute(calls: any[], opts: { docStore?: any; docIndex?: any } = {}) {
  const live: string[] = [];
  const buf = realGuard.createBufferingSseWriter((l: string) => {
    live.push(l);
  });
  await quiet(() =>
    chatTools.runToolCalls(
      calls,
      opts.docStore ?? DOC_STORE(),
      'u1',
      S.db,
      buf.write,
      undefined,
      undefined,
      opts.docIndex ?? DOC_INDEX(),
      new Map(),
      'p1',
    ),
  );
  const held: string[] = buf.takeHeld();
  const parse = (l: string): any => {
    const m = /^data: ([^\n]*)\n\n$/.exec(l);
    if (!m) return null;
    try {
      return JSON.parse(m[1]);
    } catch {
      return null;
    }
  };
  const fin = await realGuard.finalizeHeldOutput({
    held: [...held, 'data: ' + JSON.stringify({ type: 'content_delta', text: 'ok' }) + '\n\n', 'data: [DONE]\n\n'],
    events: [...held.map(parse).filter(Boolean), { type: 'content', text: 'ok' }],
    annotations: [],
    fullText: 'ok',
    verify: async (t: string) => S.verify(t),
    logError: () => {},
  });
  return { client: [...live, ...fin.linesToSend].join(''), saved: JSON.stringify(fin.savedEvents), held };
}

cases.seam_model_text_echoed_in_events_of_refused_and_failed_doc_tools_never_reaches_the_client = async () => {
  // doc_created_start carries the title-derived filename BEFORE the gate has run, and the failure events echo model-chosen
  // doc ids and `find` text. The route layer (buffering writer + finalizeHeldOutput) is what keeps them from the client.
  const scenarios: Record<string, () => Promise<any>> = {
    title_cite_refused: () =>
      throughRoute([call('generate_docx', genArgs([{ content: 'fine' }], { title: `Memo ${FAB_CORE}` }))]),
    section_cite_refused: () => throughRoute([call('generate_docx', genArgs([{ content: FAB }]))]),
    edit_unknown_doc_id_echo: () =>
      throughRoute([call('edit_document', { doc_id: `Brief ${FAB_CORE}`, edits: [{ find: 'a', replace: 'b' }] })]),
    replicate_unknown_doc_id_echo: () =>
      throughRoute([call('replicate_document', { doc_id: `Brief ${FAB_CORE}`, new_filename: 'Copy.docx' })]),
    edit_find_text_echoed_by_the_engine_error: async () => {
      S.files.set(SRC_PATH, await makeDocx(['Intro paragraph.']));
      return throughRoute([
        call('edit_document', {
          doc_id: 'doc-0',
          edits: [{ find: FAB, replace: 'x', context_before: '', context_after: '', reason: 'r' }],
        }),
      ]);
    },
  };
  for (const [name, go] of Object.entries(scenarios)) {
    resetStubs();
    S.db = makeDb();
    S.verify = fabVerify;
    const r = await go();
    assert.ok(r.held.length > 0, `${name}: no events were produced, nothing was tested`);
    assert.ok(!r.client.includes('999'), `${name}: model text reached the client: ${r.client.slice(0, 300)}`);
    assert.ok(!r.saved.includes('999'), `${name}: model text was saved: ${r.saved.slice(0, 300)}`);
    assertNothingWritten(name);
  }
};

cases.find_text_is_never_persisted_anywhere = async () => {
  // `find` is matched against the user's document. Matching is tolerant (NBSP and zero-width characters are normalised), so
  // a `find` that differs from the document in those characters still matches. Whatever is persisted must be the
  // document's own text, never the model's `find`.
  S.db = makeDb();
  S.verify = () => CLEAN;
  const NBSP = ' ';
  const out = await runEdits(['Intro paragraph.'], [
    { find: `Intro${NBSP}paragraph.`, replace: 'Intro text.', context_before: '', context_after: '', reason: 'x' },
  ]);
  assert.equal(JSON.parse(contents(out)[0]).ok, true, `edit did not apply: ${contents(out)[0]}`);
  assert.equal(S.uploads.length, 1);
  const persisted = JSON.stringify(writesOf(S.db).map((o: Op) => o.payload));
  assert.ok(!persisted.includes(NBSP), 'the model\'s `find` text (NBSP form) was persisted in a table');
  assert.ok(!(await lastUploadText()).includes(NBSP), 'the model\'s `find` text (NBSP form) is in the stored document');
  assert.ok(!sentOf(out).includes(NBSP), 'the model\'s `find` text (NBSP form) was sent in an event');
};

const sentOf = (out: any): string => (out.writes as string[]).join('');

cases.malformed_generate_args_write_nothing_and_echo_nothing = async () => {
  const variants: Record<string, { args: any; mustBeFixed?: boolean }> = {
    title_missing: { args: { sections: [{ content: FAB }] } },
    title_is_an_array: { args: { title: [FAB], sections: [] } },
    sections_is_a_string: { args: { title: 'T', sections: FAB } },
    content_is_an_array_holding_the_cite: { args: { title: 'T', sections: [{ content: [FAB] }] }, mustBeFixed: true },
    heading_is_an_object_holding_the_cite: { args: { title: 'T', sections: [{ heading: { text: FAB } }] }, mustBeFixed: true },
    cite_in_an_unknown_numeric_keyed_field: { args: { title: 'T', sections: [{ content: 'x', '0': FAB }] }, mustBeFixed: true },
  };
  for (const [name, v] of Object.entries(variants)) {
    resetStubs();
    S.db = makeDb();
    S.verify = fabVerify;
    let out: any = null;
    try {
      out = await run([call('generate_docx', v.args)]);
    } catch {
      out = null; // a throw is a refusal too: nothing below may have been written
    }
    assertNothingWritten(name);
    if (out) {
      for (const c of contents(out)) assert.ok(!c.includes('999'), `${name}: the tool result echoed model text: ${c}`);
      assert.ok(!sentOf(out).includes('999'), `${name}: an event echoed model text`);
      if (v.mustBeFixed) assert.equal(contents(out)[0], FIXED_RESULT, `${name}: not the fixed refusal`);
    } else if (v.mustBeFixed) {
      assert.fail(`${name}: threw instead of returning the fixed refusal`);
    }
  }
};

cases.generate_everything_rendered_was_shown_to_the_gate = async () => {
  // Differential oracle: for assorted shapes, every non-empty paragraph of the document that is written (read back) must
  // appear, whitespace-collapsed, inside the single string the gate was given. A renderer step that adds or rewrites
  // text after the gate would show up here.
  const shapes: Array<{ title: string; sections: unknown[] }> = [
    {
      title: GOOD_TITLE,
      sections: [
        { heading: '1.2 Fees and Payment', content: 'Pay within 30 days.\n\n- bullet one\n(a) first item\n(ii) roman item\n3.1 numbered line' },
        { heading: 'Signatures', content: 'By: ____\nName: ____\nTitle: ____\nDate: ____', pageBreak: true },
      ],
    },
    {
      title: GOOD_TITLE,
      sections: [
        { heading: GOOD_TITLE, content: 'Body text.' },
        { heading: 'Table', level: 2, table: { headers: ['A', '', 'C'], rows: [['x', 'y', 'z'], ['p']] } },
      ],
    },
    { title: 'Straße & Co. – Ünïcode Title that is rather long and goes past sixty four characters in length', sections: [{ content: 'Straße über alles' }] },
  ];
  for (const [i, shape] of shapes.entries()) {
    resetStubs();
    S.db = makeDb();
    S.verify = () => CLEAN;
    const out = await run([call('generate_docx', shape)]);
    assert.equal(S.uploads.length, 1, `shape ${i}: not written: ${contents(out)[0]}`);
    assert.equal(S.verified.length, 1, `shape ${i}: gate calls`);
    const gated = collapse(S.verified[0]);
    const lines = (await lastUploadText()).split('\n').map(collapse).filter(Boolean);
    assert.ok(lines.length > 0, `shape ${i}: nothing read back`);
    for (const line of lines) {
      assert.ok(gated.includes(line), `shape ${i}: rendered text was never shown to the gate: ${JSON.stringify(line)}`);
    }
  }
};

// ===================================================================================================================
// D. other egress of model text that can write a document somewhere else
// ===================================================================================================================

cases.mcp_connector_tool_arguments_with_a_vetoed_cite_are_not_sent_out = async () => {
  // DECISION CASE. A connected MCP tool (e.g. a drive "create file") receives the model's arguments verbatim and runs at once,
  // before any gate. If connector writes are out of scope for Constraint A, drop this case; otherwise the arguments need the
  // same Gate 1 as the three document tools.
  S.db = makeDb();
  S.verify = fabVerify;
  await run([call('mcp_drive_create_file', { name: 'Brief', content: `See ${FAB}.` })]);
  assert.deepEqual(
    S.mcpCalls.map((c) => c.name),
    [],
    `model text carrying a fabricated cite was sent to an external connector: ${JSON.stringify(S.mcpCalls).slice(0, 300)}`,
  );
};

// ---------- run ----------

(async () => {
  const report: Record<string, string | null> = {};
  for (const [name, fn] of Object.entries(cases)) {
    resetStubs();
    try {
      await fn();
      report[name] = null;
    } catch (err: any) {
      report[name] = String(err?.stack ?? err).slice(0, 2500);
    }
  }
  process.stdout.write('\nDOCWRITE_REPORT=' + JSON.stringify(report) + '\n');
  process.exit(0);
})();
