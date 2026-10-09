// Cases for Gate 1 before document writes (tabular-docwrite-verify, part B): the three chat tools in
// backend/src/lib/chatTools.ts that write model text into the user's documents.
//   generate_docx        title, headings, prose, tables, any other field, and the derived stored filename
//   edit_document        replacement text, reason, context strings (document_edits stores them), tracked-changes path
//   replicate_document   the model-chosen new filename(s)
// Every caller of those tools (chat.ts, projectChat.ts, tabular.ts) reaches them through runLLMStream -> runToolCalls,
// so the cases drive the REAL runToolCalls (and, for the tabular shape, the real runLLMStream).
//
// Run by test_doc_write_gate.py once under backend's tsx. What is real: chatTools.ts, the whole of
// hallucination_guard.ts (so gateCellContent / finalizeHeldOutput / createLimiter), safeError.ts, the docx and jszip
// packages (a clean generate_docx builds a real .docx in memory). What is stubbed: storage (records every upload),
// Supabase (a recording fake that logs every non-select query), the tracked-changes engine, the model client,
// CourtListener and MCP modules, and the Gate 1 verifier (verifyDraftForSse). No Supabase, CourtListener, model,
// Python gate or network.
// Prints {caseName: null | "failure text"}.

import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import path from 'node:path';
import type { SseVerificationResult } from '../../backend/src/middleware/hallucination_guard';

// ---------- helpers ----------

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v));

type Status = 'verified' | 'conditional' | 'vetoed' | 'pending';
const verdict = (citation: string, status: Status | string) => ({
  citation,
  status,
  gate1_existence: status !== 'vetoed',
  gate2_quote_accuracy: null,
  gate3_currency: null,
  gate4_jurisdiction_fit: null,
  notes: [] as string[],
});
const result = (verdicts: any[], extra: Partial<SseVerificationResult> = {}): SseVerificationResult => ({
  verdicts: verdicts as any,
  hasVetoes: verdicts.some((v) => v.status === 'vetoed' || v.status === 'pending'),
  hasConditional: verdicts.some((v) => v.status === 'conditional'),
  ...extra,
});
const CLEAN = result([]);

const GOOD = 'Good v. Case, 1 So. 3d 2 (Fla. 2010)';
const FAB = 'Doe v. Roe, 999 So. 3d 999 (Fla. 2015)';
const FAB_CORE = '999 So. 3d 999';
/** What the filename rule leaves of FAB_CORE (periods are stripped from stored filenames). */
const FAB_NO_PERIODS = '999 So 3d 999';
const RAW = 'SQLITE_CANTOPEN: unable to open /Users/x/kingsfield_florida.db; CourtListener 503 hidden-detail-7731';
const RAW_LEAKS = ['SQLITE', 'CANTOPEN', 'kingsfield_florida', 'hidden-detail-7731', '/Users/x'];

/** Vetoes any text with the fabricated cite (with or without periods); verifies the good one. */
function fabVerify(text: string): SseVerificationResult {
  const vs: any[] = [];
  if (text.includes(FAB_CORE) || text.includes(FAB_NO_PERIODS)) vs.push(verdict(FAB, 'vetoed'));
  if (text.includes('1 So. 3d 2')) vs.push(verdict(GOOD, 'verified'));
  return result(vs);
}

// ---------- chatTools.ts, with its dependencies stubbed ----------

const ROOT = process.cwd();
const nodeRequire = createRequire(path.join(ROOT, 'backend', 'package.json'));
const CHAT_TOOLS = path.join(ROOT, 'backend', 'src', 'lib', 'chatTools.ts');
const GUARD_PATH = path.join(ROOT, 'backend', 'src', 'middleware', 'hallucination_guard.ts');

type Op = { table: string; op: 'select' | 'insert' | 'update' | 'delete'; payload?: any; filters: any[][] };

const S: {
  db: any;
  verify: (text: string) => Promise<SseVerificationResult>;
  verified: string[];
  uploads: Array<{ key: string; contentType: string }>;
  downloads: string[];
  trackedCalls: number;
  streamChatWithTools: (p: any) => Promise<void>;
  timeline: string[];
  timeoutOverrideMs: number | null;
} = {} as any;

function resetStubs() {
  S.db = undefined;
  S.verify = async () => CLEAN;
  S.verified = [];
  S.uploads = [];
  S.downloads = [];
  S.trackedCalls = 0;
  S.streamChatWithTools = async () => {
    throw new Error('streamChatWithTools not set');
  };
  S.timeline = [];
  S.timeoutOverrideMs = null;
}
resetStubs();

const realGuard = nodeRequire(GUARD_PATH);
const STUBS: Record<string, any> = {
  './storage': {
    uploadFile: async (key: string, _bytes: unknown, contentType: string) => {
      S.timeline.push('upload');
      S.uploads.push({ key, contentType });
    },
    downloadFile: async (p: string) => {
      S.downloads.push(p);
      return new Uint8Array([1, 2, 3]).buffer;
    },
    generatedDocKey: (u: string, d: string, f: string) => `generated/${u}/${d}/${f}`,
    storageKey: (u: string, d: string, f: string) => `documents/${u}/${d}/${f}`,
  },
  './convert': { convertedPdfKey: (u: string, d: string) => `pdf/${u}/${d}.pdf` },
  './supabase': { createServerSupabase: () => S.db },
  './docxTrackedChanges': {
    extractDocxBodyText: async () => '',
    // The engine is stubbed: it reports one applied change per edit. Counting calls shows the gate ran first.
    applyTrackedEdits: async (_bytes: unknown, edits: any[]) => {
      S.trackedCalls++;
      return {
        bytes: Buffer.from([9, 9, 9]),
        changes: edits.map((e, i) => ({
          id: `c${i}`,
          delId: `d${i}`,
          insId: `i${i}`,
          deletedText: `old ${i}`,
          insertedText: String(e.replace ?? ''),
          contextBefore: String(e.context_before ?? ''),
          contextAfter: String(e.context_after ?? ''),
          reason: e.reason,
        })),
        errors: [],
      };
    },
  },
  './downloadTokens': { buildDownloadUrl: (k: string, f: string) => `https://dl.test/${k}?f=${encodeURIComponent(f)}` },
  './documentVersions': {
    attachActiveVersionPaths: async () => {},
    loadActiveVersion: async () => ({
      storage_path: 'documents/u1/d1/a.docx',
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
    executeMcpToolCall: async () => {
      throw new Error('mcp not available');
    },
  },
  './llm': {
    streamChatWithTools: (p: any) => S.streamChatWithTools(p),
    resolveModel: (m: unknown) => m ?? 'stub-model',
    DEFAULT_MAIN_MODEL: 'stub-model',
  },
  // The real guard with only the Gate 1 verifier replaced (chatTools calls verifyDraftForSse itself) and the
  // limiter's timer shortened on request (the module's own limit is far too long to wait for in a test).
  '../middleware/hallucination_guard': {
    ...realGuard,
    verifyDraftForSse: (text: string, _opts: unknown) => {
      S.timeline.push('verify');
      S.verified.push(text);
      return S.verify(text);
    },
    createLimiter: (max: number, opts: any) =>
      realGuard.createLimiter(max, {
        ...opts,
        timers: {
          setTimeout: (fn: () => void, ms: number) => setTimeout(fn, S.timeoutOverrideMs ?? ms),
          clearTimeout: (h: any) => clearTimeout(h),
        },
      }),
  },
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

const FIXED: string = chatTools.DOC_WRITE_REFUSED_MESSAGE;
const FIXED_RESULT = JSON.stringify({ ok: false, error: FIXED });

// ---------- fakes ----------

const logs: string[] = [];
async function quiet<T>(fn: () => Promise<T>): Promise<T> {
  const orig = { log: console.log, info: console.info, warn: console.warn, error: console.error };
  for (const k of Object.keys(orig) as Array<keyof typeof orig>) {
    (console as any)[k] = (...a: unknown[]) => {
      logs.push(`${k}: ${a.map((x) => (typeof x === 'string' ? x : JSON.stringify(x))).join(' ')}`);
    };
  }
  try {
    return await fn();
  } finally {
    Object.assign(console, orig);
  }
}

/** Recording Supabase fake: every query is logged; non-select queries also land on the timeline as write:<table>:<op>. */
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
  assert.deepEqual(S.uploads, [], `${label}: a storage object was written`);
  assert.deepEqual(writesOf(S.db), [], `${label}: a table was written`);
  assert.ok(!S.timeline.some((t) => t === 'upload' || t.startsWith('write:')), `${label}: timeline shows a write`);
}

const call = (name: string, args: unknown, id = `call-${name}`) => ({
  id,
  function: { name, arguments: JSON.stringify(args) },
});

const DOC_INDEX = () => ({ 'doc-0': { document_id: 'd1', filename: 'a.docx' } });
const DOC_STORE = () =>
  new Map([['doc-0', { storage_path: 'documents/u1/d1/a.docx', file_type: 'docx', filename: 'a.docx' }]]);

/** Run runToolCalls the way runLLMStream does. */
async function run(calls: any[], opts: { projectId?: string | null; docIndex?: any; turnEditState?: any } = {}) {
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
      opts.docIndex ?? DOC_INDEX(),
      opts.turnEditState ?? new Map(),
      opts.projectId === undefined ? 'p1' : opts.projectId,
    ),
  );
  return { ...out, writes };
}

const contents = (out: any): string[] => out.toolResults.map((r: any) => String(r.content));
const sent = (out: any): string => out.writes.join('');

// A clean document the model might write.
const GOOD_SECTIONS = () => [
  { heading: 'Parties', level: 1, content: 'This agreement is made today.\n\nSecond paragraph.' },
  { heading: 'Fees', table: { headers: ['Item', 'Amount'], rows: [['Retainer', '$500']] } },
];
const genArgs = (over: Record<string, unknown> = {}) => ({ title: 'Service Agreement', sections: GOOD_SECTIONS(), ...over });
const editArgs = (edit: Record<string, unknown> = {}) => ({
  doc_id: 'doc-0',
  edits: [{ find: 'old', replace: 'new', context_before: 'before ', context_after: ' after', reason: 'clearer', ...edit }],
});
const repArgs = (over: Record<string, unknown> = {}) => ({ doc_id: 'doc-0', ...over });

/** Asserts the single refused result and that the model's text did not come back. */
function assertRefused(out: any, label: string, leaks: string[] = [FAB_CORE, '999']) {
  const c = contents(out);
  assert.equal(c.length, 1, `${label}: one tool result`);
  assert.equal(c[0], FIXED_RESULT, `${label}: the fixed result`);
  for (const l of leaks) assert.ok(!c[0].includes(l), `${label}: tool result echoed "${l}"`);
  assertNothingWritten(label);
}

// ---------- the cases ----------

const cases: Record<string, () => Promise<void>> = {};

// ===== generate_docx =====

cases.generate_clean_content_is_written_as_before_and_gated_first = async () => {
  S.db = makeDb();
  S.verify = async (t) => fabVerify(t);
  const out = await run([call('generate_docx', genArgs({ landscape: true }))]);
  assert.equal(S.uploads.length, 1, 'one storage object');
  assert.ok(S.uploads[0].key.endsWith('/Service Agreement.docx'), S.uploads[0].key);
  assert.deepEqual(
    writesOf(S.db).map((o: Op) => `${o.table}:${o.op}`),
    ['documents:insert', 'document_versions:insert', 'documents:update'],
  );
  assert.equal(writesOf(S.db)[0].payload.project_id, 'p1');
  assert.equal(writesOf(S.db)[1].payload.filename, 'Service Agreement.docx');
  const c = JSON.parse(contents(out)[0]);
  assert.equal(c.filename, 'Service Agreement.docx');
  assert.equal(c.document_id, 'n1');
  assert.equal(c.doc_id, 'doc-1');
  assert.ok(!('download_url' in c) && !('storage_path' in c));
  assert.equal(out.docsCreated.length, 1);
  assert.ok(sent(out).includes('"download_url":"https://dl.test/'), 'the card event carries the download url');
  // One gate call, before the first write, over every written string.
  assert.equal(S.verified.length, 1);
  assert.equal(S.timeline[0], 'verify');
  const text = S.verified[0];
  for (const s of ['Service Agreement', 'SERVICE AGREEMENT', 'Parties', 'Second paragraph.', 'Fees', 'Item', 'Retainer', '$500']) {
    assert.ok(text.includes(s), `gated text is missing "${s}"`);
  }
};

cases.generate_a_verified_and_a_conditional_cite_are_still_written = async () => {
  S.db = makeDb();
  S.verify = async () =>
    result([verdict(GOOD, 'verified'), verdict('Other v. Case, 2 So. 3d 3 (Fla. 2011)', 'conditional')]);
  await run([call('generate_docx', genArgs({ sections: [{ heading: 'Law', content: `See ${GOOD}.` }] }))]);
  assert.equal(S.uploads.length, 1);
  assert.equal(writesOf(S.db).length, 3);
};

cases.generate_vetoed_cite_in_prose_writes_nothing_and_returns_the_fixed_result = async () => {
  S.db = makeDb();
  S.verify = async (t) => fabVerify(t);
  const out = await run([call('generate_docx', genArgs({ sections: [{ heading: 'Law', content: `See ${FAB}.` }] }))]);
  assertRefused(out, 'prose');
  assert.equal(S.verified.length, 1, 'gated once');
  assert.equal(out.docsCreated.length, 0);
  assert.ok(!sent(out).includes('"download_url":"https://'), 'no download link was offered');
  assert.ok(!sent(out).includes('999'), 'no event carries the cite');
  // The card the UI opened is closed as a failure (empty url), never as a document.
  assert.ok(sent(out).includes('"type":"doc_created"'));
  assert.ok(sent(out).includes('"download_url":""'));
};

cases.generate_a_cite_only_in_the_title_is_refused = async () => {
  S.db = makeDb();
  S.verify = async (t) => fabVerify(t);
  const out = await run([call('generate_docx', genArgs({ title: `Memo on ${FAB_CORE}` }))]);
  assertRefused(out, 'title');
};

cases.generate_a_cite_only_in_the_derived_filename_is_refused = async () => {
  S.db = makeDb();
  // "S.o." in the title is stripped to "So" in the stored filename, which then reads as the cite.
  S.verify = async (t) => fabVerify(t);
  const title = 'Memo 999 S.o. 3d 999';
  assert.ok(!title.includes(FAB_CORE) && !title.includes(FAB_NO_PERIODS), 'the raw title is not itself the cite');
  const out = await run([call('generate_docx', genArgs({ title }))]);
  assertRefused(out, 'filename');
  assert.ok(S.verified[0].includes(`${FAB_NO_PERIODS}.docx`), 'the derived filename was checked');
};

cases.generate_a_cite_in_a_table_cell_header_or_across_cells_is_refused = async () => {
  const table = (headers: string[], rows: string[][]) => [{ heading: 'T', table: { headers, rows } }];
  const variants: Record<string, any[]> = {
    cell: table(['Case', 'Note'], [['ok', `see ${FAB}`]]),
    header: table([`${FAB_CORE}`, 'Note'], [['a', 'b']]),
    second_row: table(['A', 'B'], [['x', 'y'], ['p', `${FAB_CORE}`]]),
    // each cell alone is harmless; read across the row they are the cite
    across_cells: table(['A', 'B', 'C'], [['999', 'So. 3d', '999']]),
  };
  for (const [name, sections] of Object.entries(variants)) {
    resetStubs();
    S.db = makeDb();
    S.verify = async (t) => fabVerify(t);
    const out = await run([call('generate_docx', genArgs({ sections }))]);
    assertRefused(out, `table ${name}`);
  }
};

cases.generate_a_cite_in_a_heading_or_in_an_unrendered_field_is_refused = async () => {
  const variants: Record<string, any[]> = {
    heading: [{ heading: `Per ${FAB_CORE}`, content: 'fine' }],
    nested_unknown_field: [{ heading: 'A', content: 'fine', footnote: { text: [`n. ${FAB_CORE}`] } }],
    second_section: [{ heading: 'A', content: 'fine' }, { content: `x\n\n${FAB_CORE}` }],
  };
  for (const [name, sections] of Object.entries(variants)) {
    resetStubs();
    S.db = makeDb();
    S.verify = async (t) => fabVerify(t);
    const out = await run([call('generate_docx', genArgs({ sections }))]);
    assertRefused(out, `generate ${name}`);
  }
};

cases.generate_pending_and_unknown_status_verdicts_are_refused = async () => {
  for (const status of ['pending', 'something_new', 'vetoed']) {
    resetStubs();
    S.db = makeDb();
    S.verify = async () => result([verdict(FAB, status)], { hasVetoes: status !== 'something_new' ? true : false });
    const out = await run([call('generate_docx', genArgs())]);
    assertRefused(out, `status ${status}`);
  }
};

cases.generate_every_gate_failure_refuses_and_leaks_no_raw_error = async () => {
  const failures: Record<string, () => Promise<SseVerificationResult>> = {
    throws: async () => {
      throw new Error(RAW);
    },
    error_result: async () => result([], { hasVetoes: true, error: RAW }),
    error_without_veto_flag: async () => result([], { hasVetoes: false, error: RAW }),
    malformed_result: async () => undefined as any,
    busy: async () => result([], { hasVetoes: true, error: 'gate_busy' }),
  };
  for (const [name, verify] of Object.entries(failures)) {
    resetStubs();
    S.db = makeDb();
    S.verify = verify;
    const out = await run([call('generate_docx', genArgs())]);
    assertRefused(out, `gate ${name}`, RAW_LEAKS);
    for (const l of RAW_LEAKS) assert.ok(!sent(out).includes(l), `gate ${name}: event leaked "${l}"`);
  }
  // A gate that never answers is abandoned at its time limit.
  resetStubs();
  S.db = makeDb();
  S.timeoutOverrideMs = 20;
  S.verify = () => new Promise(() => {});
  const out = await run([call('generate_docx', genArgs())]);
  assertRefused(out, 'gate timeout');
};

cases.generate_malformed_shapes_are_refused_without_a_gate_call_or_a_write = async () => {
  const deep: any = { content: 'x' };
  let cur: any = deep;
  for (let i = 0; i < 40; i++) {
    cur.next = { content: 'y' };
    cur = cur.next;
  }
  const variants: Record<string, unknown> = {
    sections_not_an_array: 'not an array',
    sections_missing: undefined,
    nested_too_deep: [deep],
    too_many_strings: [{ content: 'x', extra: Array.from({ length: 25_000 }, () => 'a') }],
  };
  for (const [name, sections] of Object.entries(variants)) {
    resetStubs();
    S.db = makeDb();
    const out = await run([call('generate_docx', { title: 'T', sections })]);
    assertRefused(out, `shape ${name}`);
    assert.equal(S.verified.length, 0, `shape ${name}: nothing to ask the gate`);
  }
  resetStubs();
  S.db = makeDb();
  const out = await run([call('generate_docx', { title: 'T', sections: [{ content: 'x'.repeat(2_100_000) }] })]);
  assertRefused(out, 'oversize');
  assert.equal(S.verified.length, 0);
};

// ===== edit_document =====

cases.edit_clean_edits_are_written_as_before_and_gated_first = async () => {
  S.db = makeDb();
  S.verify = async (t) => fabVerify(t);
  const out = await run([call('edit_document', editArgs({ replace: `new text citing ${GOOD}` }))]);
  assert.equal(S.trackedCalls, 1);
  assert.equal(S.uploads.length, 1);
  assert.deepEqual(
    writesOf(S.db).map((o: Op) => `${o.table}:${o.op}`),
    ['document_versions:insert', 'document_edits:insert', 'documents:update'],
  );
  const c = JSON.parse(contents(out)[0]);
  assert.equal(c.ok, true);
  assert.equal(c.applied, 1);
  assert.equal(out.docsEdited.length, 1);
  assert.equal(S.verified.length, 1);
  assert.equal(S.timeline[0], 'verify', 'the gate ran before the first write');
  const text = S.verified[0];
  for (const s of ['new text citing', 'clearer', 'before ', ' after']) assert.ok(text.includes(s), `gated text is missing "${s}"`);
};

cases.edit_a_vetoed_replacement_writes_nothing_and_returns_the_fixed_result = async () => {
  S.db = makeDb();
  S.verify = async (t) => fabVerify(t);
  const out = await run([call('edit_document', editArgs({ replace: `now see ${FAB}` }))]);
  assertRefused(out, 'replace');
  assert.equal(S.trackedCalls, 0, 'the edit engine never ran');
  assert.equal(out.docsEdited.length, 0);
  assert.equal(S.downloads.length, 0, 'the document was not even read');
  assert.ok(!sent(out).includes('999'), 'no event carries the cite');
  assert.ok(sent(out).includes(FIXED), 'the failed card carries the fixed message');
};

cases.edit_a_cite_only_in_the_reason_or_the_context_is_refused = async () => {
  const variants: Record<string, Record<string, unknown>> = {
    reason: { reason: `Because ${FAB_CORE} requires it` },
    context_before: { context_before: `see ${FAB_CORE} ` },
    context_after: { context_after: ` ${FAB_CORE}.` },
    // none of the three holds the cite alone; assembled in the document they read as one
    assembled: { context_before: 'see 999 So. ', replace: '3d', context_after: ' 999.' },
  };
  for (const [name, over] of Object.entries(variants)) {
    resetStubs();
    S.db = makeDb();
    S.verify = async (t) => fabVerify(t.includes('see 999 So. 3d 999.') ? FAB_CORE : t);
    const out = await run([call('edit_document', editArgs(over))]);
    assertRefused(out, `edit ${name}`);
    assert.equal(S.trackedCalls, 0);
  }
};

cases.edit_one_vetoed_edit_among_several_refuses_the_whole_call = async () => {
  S.db = makeDb();
  S.verify = async (t) => fabVerify(t);
  const args = {
    doc_id: 'doc-0',
    edits: [
      { find: 'a', replace: 'b', context_before: 'x ', context_after: ' y', reason: 'ok' },
      { find: 'c', replace: 'd', context_before: 'x ', context_after: ' y', reason: 'ok' },
      { find: 'e', replace: FAB_CORE, context_before: 'x ', context_after: ' y', reason: 'ok' },
    ],
  };
  const out = await run([call('edit_document', args)]);
  assertRefused(out, 'several');
};

cases.edit_the_reused_version_path_is_gated_too = async () => {
  S.db = makeDb();
  S.verify = async (t) => fabVerify(t);
  const turnEditState = new Map([['d1', { versionId: 'v-turn', versionNumber: 2, storagePath: 'documents/u1/d1/edits/v-turn.docx' }]]);
  let out = await run([call('edit_document', editArgs({ replace: FAB_CORE }))], { turnEditState });
  assertRefused(out, 'reuse refused');
  assert.deepEqual([...turnEditState.keys()], ['d1']);
  assert.equal(turnEditState.get('d1')!.versionId, 'v-turn', 'turn state untouched');
  // And a clean one on the same path overwrites the turn's file in place, as before.
  resetStubs();
  S.db = makeDb();
  S.verify = async (t) => fabVerify(t);
  out = await run([call('edit_document', editArgs())], { turnEditState });
  assert.deepEqual(S.uploads.map((u) => u.key), ['documents/u1/d1/edits/v-turn.docx']);
  assert.deepEqual(
    writesOf(S.db).map((o: Op) => `${o.table}:${o.op}`),
    ['document_versions:update', 'document_edits:insert', 'documents:update'],
  );
};

cases.edit_a_cite_in_find_alone_does_not_block_a_clean_replacement = async () => {
  // `find` only locates text already in the user's document; it is never written. Fixing a bad cite must stay possible.
  S.db = makeDb();
  S.verify = async (t) => fabVerify(t);
  await run([call('edit_document', editArgs({ find: FAB_CORE, replace: 'the correct cite' }))]);
  assert.equal(S.uploads.length, 1);
  assert.ok(!S.verified[0].includes(FAB_CORE), '`find` is not part of the gated text');
};

cases.edit_every_gate_failure_refuses = async () => {
  const failures: Record<string, () => Promise<SseVerificationResult>> = {
    throws: async () => {
      throw new Error(RAW);
    },
    error_result: async () => result([], { hasVetoes: true, error: RAW }),
    pending: async () => result([verdict(FAB, 'pending')]),
    malformed_result: async () => null as any,
  };
  for (const [name, verify] of Object.entries(failures)) {
    resetStubs();
    S.db = makeDb();
    S.verify = verify;
    const out = await run([call('edit_document', editArgs())]);
    assertRefused(out, `edit gate ${name}`, RAW_LEAKS);
    assert.equal(S.trackedCalls, 0);
  }
  resetStubs();
  S.db = makeDb();
  S.timeoutOverrideMs = 20;
  S.verify = () => new Promise(() => {});
  assertRefused(await run([call('edit_document', editArgs())]), 'edit gate timeout');
};

cases.edit_malformed_edits_are_refused_without_a_write = async () => {
  // runToolCalls stringifies each field, so call runEditDocument directly with shapes the dispatch can't produce.
  const shapes: Record<string, unknown> = {
    not_an_array: 'x',
    null_edit: [null],
    array_edit: [['a']],
    too_deep: [{ replace: 'x', extra: JSON.parse('['.repeat(30) + ']'.repeat(30)) }],
  };
  for (const [name, edits] of Object.entries(shapes)) {
    resetStubs();
    S.db = makeDb();
    const r = await quiet(() => chatTools.runEditDocument({ documentId: 'd1', userId: 'u1', edits, db: S.db }));
    assert.deepEqual(r, { ok: false, error: FIXED }, name);
    assertNothingWritten(`edit shape ${name}`);
    assert.equal(S.trackedCalls, 0);
  }
};

cases.edit_two_calls_in_one_batch_are_each_gated_on_their_own = async () => {
  S.db = makeDb();
  S.verify = async (t) => fabVerify(t);
  const out = await run([
    call('edit_document', editArgs({ replace: 'clean one' }), 'c1'),
    call('edit_document', editArgs({ replace: FAB_CORE }), 'c2'),
    call('edit_document', editArgs({ reason: FAB_CORE }), 'c3'),
  ]);
  const c = contents(out);
  assert.equal(c.length, 3);
  assert.equal(JSON.parse(c[0]).ok, true);
  assert.equal(c[1], FIXED_RESULT);
  assert.equal(c[2], FIXED_RESULT);
  assert.equal(S.uploads.length, 1, 'only the clean call wrote a file');
  assert.equal(S.trackedCalls, 1);
  assert.equal(S.verified.length, 3, 'one gate call per tool call');
  assert.equal(
    writesOf(S.db).filter((o: Op) => o.table === 'document_edits').length,
    1,
    'only the clean call recorded edits',
  );
};

// ===== replicate_document =====

cases.replicate_clean_filenames_are_written_as_before_and_gated_first = async () => {
  S.db = makeDb();
  S.verify = async (t) => fabVerify(t);
  const out = await run([call('replicate_document', repArgs({ count: 2, new_filename: 'NDA Template.docx' }))]);
  assert.deepEqual(
    writesOf(S.db).map((o: Op) => `${o.table}:${o.op}`),
    ['documents:insert', 'document_versions:insert', 'documents:update', 'documents:update'],
  );
  assert.equal(S.uploads.length, 2);
  const names = writesOf(S.db)[1].payload.map((r: any) => r.filename);
  assert.deepEqual(names, ['NDA Template (1).docx', 'NDA Template (2).docx']);
  const c = JSON.parse(contents(out)[0]);
  assert.equal(c.ok, true);
  assert.equal(c.count, 2);
  assert.equal(S.verified.length, 1);
  assert.equal(S.timeline[0], 'verify', 'the gate ran before any read or write');
  assert.equal(S.downloads.length, 1, 'the source was read once, after the gate');
  for (const s of ['NDA Template.docx', 'NDA Template (1).docx', 'NDA Template (2).docx']) {
    assert.ok(S.verified[0].includes(s), `gated text is missing "${s}"`);
  }
};

cases.replicate_a_vetoed_new_filename_writes_nothing_and_returns_the_fixed_result = async () => {
  S.db = makeDb();
  S.verify = async (t) => fabVerify(t);
  const out = await run([call('replicate_document', repArgs({ new_filename: `Brief ${FAB_CORE}.docx` }))]);
  assertRefused(out, 'filename');
  assert.equal(S.downloads.length, 0, 'the source bytes were not even read');
  assert.equal(out.docsReplicated.length, 0);
  assert.ok(!sent(out).includes('999'));
};

cases.replicate_a_cite_formed_only_in_the_final_filename_is_refused = async () => {
  // The extension is forced to the source's and a suffix is added; the cite must be checked as the final name.
  S.db = makeDb();
  S.verify = async (t) => fabVerify(t.includes('Brief 999 So. 3d (1).docx') ? FAB_CORE : t);
  const out = await run([call('replicate_document', repArgs({ count: 2, new_filename: 'Brief 999 So. 3d.pdf' }))]);
  assertRefused(out, 'final filename');
  assert.ok(S.verified[0].includes('Brief 999 So. 3d (1).docx'), 'checked as the final name');
};

cases.replicate_every_gate_failure_refuses = async () => {
  const failures: Record<string, () => Promise<SseVerificationResult>> = {
    throws: async () => {
      throw new Error(RAW);
    },
    error_result: async () => result([], { hasVetoes: true, error: RAW }),
    unknown_status: async () => result([verdict(FAB, 'pending')]),
  };
  for (const [name, verify] of Object.entries(failures)) {
    resetStubs();
    S.db = makeDb();
    S.verify = verify;
    const out = await run([call('replicate_document', repArgs({ new_filename: 'Copy.docx' }))]);
    assertRefused(out, `replicate gate ${name}`, RAW_LEAKS);
    assert.equal(S.downloads.length, 0);
  }
  resetStubs();
  S.db = makeDb();
  S.timeoutOverrideMs = 20;
  S.verify = () => new Promise(() => {});
  assertRefused(await run([call('replicate_document', repArgs({ new_filename: 'Copy.docx' }))]), 'replicate gate timeout');
};

cases.replicate_without_a_new_filename_copies_under_the_users_own_name_without_asking_the_gate = async () => {
  // Nothing is model-written here: the name is the user's own filename plus " (copy)".
  S.db = makeDb();
  S.verify = async (t) => fabVerify(t);
  const store = new Map([['doc-0', { storage_path: 'documents/u1/d1/a.docx', file_type: 'docx', filename: `Re ${FAB_CORE}.docx` }]]);
  const writes: string[] = [];
  const out = await quiet(() =>
    chatTools.runToolCalls([call('replicate_document', repArgs())], store, 'u1', S.db, (s: string) => writes.push(s), undefined, undefined, DOC_INDEX(), new Map(), 'p1'),
  );
  assert.equal(S.verified.length, 0, 'no gate call');
  assert.equal(S.uploads.length, 1);
  assert.equal(JSON.parse(String(out.toolResults[0].content)).copies[0].filename, `Re ${FAB_CORE} (copy).docx`);
};

cases.replicate_failures_that_are_not_the_gate_are_unchanged = async () => {
  S.db = makeDb();
  let out = await run([call('replicate_document', repArgs({ new_filename: 'X.docx' }))], { projectId: null });
  assert.equal(JSON.parse(contents(out)[0]).error, 'replicate_document is only available in project chats.');
  assert.equal(S.verified.length, 0);
  out = await run([call('replicate_document', { doc_id: 'doc-9', new_filename: 'X.docx' })]);
  assert.ok(JSON.parse(contents(out)[0]).error.includes('not found'));
  assert.equal(S.verified.length, 0);
  assertNothingWritten('unchanged failures');
};

// ===== across tools and callers =====

cases.the_three_tools_return_the_identical_refused_result = async () => {
  S.db = makeDb();
  S.verify = async () => result([verdict(FAB, 'vetoed')]);
  const out = await run([
    call('generate_docx', genArgs(), 'g'),
    call('edit_document', editArgs(), 'e'),
    call('replicate_document', repArgs({ new_filename: 'N.docx' }), 'r'),
  ]);
  const c = contents(out);
  assert.equal(c.length, 3);
  assert.deepEqual(new Set(c), new Set([FIXED_RESULT]));
  assert.equal(FIXED_RESULT, JSON.stringify({ ok: false, error: 'The document was not written because its content contained a citation that could not be verified.' }));
  assertNothingWritten('three tools');
};

cases.a_refusal_does_not_stop_the_next_tool_call_in_the_same_batch = async () => {
  S.db = makeDb();
  S.verify = async (t) => fabVerify(t);
  const out = await run([
    call('generate_docx', genArgs({ title: FAB_CORE }), 'bad'),
    call('generate_docx', genArgs({ title: 'Clean Title' }), 'good'),
  ]);
  const c = contents(out);
  assert.equal(c[0], FIXED_RESULT);
  assert.equal(JSON.parse(c[1]).filename, 'Clean Title.docx');
  assert.equal(S.uploads.length, 1);
  assert.equal(writesOf(S.db).length, 3);
};

/** Drive the real runLLMStream the way tabular.ts calls it (empty docIndex, TABULAR_TOOLS, no research tools, no project). */
async function streamWith(calls: any[], shape: 'tabular' | 'project') {
  const tabularTools = chatTools.TABULAR_TOOLS;
  let toolResults: any[] = [];
  let offered: string[] = [];
  S.streamChatWithTools = async (p: any) => {
    offered = p.tools.map((t: any) => t.function.name);
    toolResults = await p.runTools(calls.map((c) => ({ id: c.id, name: c.function.name, input: JSON.parse(c.function.arguments) })));
  };
  const writes: string[] = [];
  await quiet(() =>
    chatTools.runLLMStream({
      apiMessages: [{ role: 'system', content: 's' }, { role: 'user', content: 'hi' }],
      docStore: shape === 'tabular' ? new Map() : DOC_STORE(),
      docIndex: shape === 'tabular' ? {} : DOC_INDEX(),
      userId: 'u1',
      db: S.db,
      write: (s: string) => writes.push(s),
      ...(shape === 'tabular'
        ? { extraTools: tabularTools, includeResearchTools: false, tabularStore: { columns: [], documents: [], cells: new Map() } }
        : { projectId: 'p1' }),
    }),
  );
  return { toolResults, offered, writes };
}

cases.tabular_chat_shape_offers_generate_docx_and_the_gate_covers_it = async () => {
  S.db = makeDb();
  S.verify = async (t) => fabVerify(t);
  let r = await streamWith([call('generate_docx', genArgs({ sections: [{ content: FAB_CORE }] }))], 'tabular');
  assert.ok(r.offered.includes('generate_docx'), 'tabular chat offers generate_docx (TOOLS is always in the tool list)');
  assert.ok(r.offered.includes('read_table_cells'));
  assert.equal(r.toolResults[0].content, FIXED_RESULT);
  assertNothingWritten('tabular vetoed');
  // Clean content from the same shape is written, as a standalone document.
  resetStubs();
  S.db = makeDb();
  S.verify = async (t) => fabVerify(t);
  r = await streamWith([call('generate_docx', genArgs())], 'tabular');
  assert.equal(S.uploads.length, 1);
  assert.equal(writesOf(S.db)[0].payload.project_id, null);
  // edit/replicate have no document to act on in that shape, and write nothing.
  resetStubs();
  S.db = makeDb();
  S.verify = async (t) => fabVerify(t);
  r = await streamWith([call('edit_document', editArgs()), call('replicate_document', repArgs({ new_filename: 'N.docx' }))], 'tabular');
  assertNothingWritten('tabular edit/replicate');
};

cases.project_chat_shape_runs_all_three_tools_through_the_gate = async () => {
  S.db = makeDb();
  S.verify = async () => result([verdict(FAB, 'vetoed')]);
  const r = await streamWith(
    [call('generate_docx', genArgs(), 'g'), call('edit_document', editArgs(), 'e'), call('replicate_document', repArgs({ new_filename: 'N.docx' }), 'r')],
    'project',
  );
  assert.deepEqual(r.toolResults.map((t) => t.content), [FIXED_RESULT, FIXED_RESULT, FIXED_RESULT]);
  assertNothingWritten('project shape');
};

cases.the_gate_is_serialised_by_a_capped_limiter = async () => {
  // Many parallel tool calls must not fan out into unbounded gate calls.
  S.db = makeDb();
  let active = 0;
  let peak = 0;
  S.verify = async () => {
    active++;
    peak = Math.max(peak, active);
    await new Promise((r) => setTimeout(r, 5));
    active--;
    return CLEAN;
  };
  // (one quiet() around the whole batch: it swaps the global console, so it is not safe to overlap)
  await quiet(() =>
    Promise.all(
      Array.from({ length: 6 }, (_, i) =>
        chatTools.runToolCalls([call('generate_docx', genArgs({ title: `T${i}` }), `c${i}`)], DOC_STORE(), 'u1', S.db, () => {}, undefined, undefined, DOC_INDEX(), new Map(), 'p1'),
      ),
    ),
  );
  assert.equal(S.verified.length, 6);
  assert.ok(peak <= 2, `at most 2 gate calls at once, saw ${peak}`);
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
      report[name] = String(err?.stack ?? err).slice(0, 2000);
    }
  }
  process.stdout.write(JSON.stringify(report));
  process.exit(0);
})();
