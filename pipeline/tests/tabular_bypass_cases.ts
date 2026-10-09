// Adversary cases for the tabular review routes (merge blocker 4, part A). Attacks on:
//   POST /tabular-review/:reviewId/chat           (runLLMStream -> buffering writer -> finalizeHeldOutput, tabular chips)
//   POST /tabular-review/:reviewId/generate       (each cell -> gateCellContent before it is saved or sent)
//   POST /tabular-review/:reviewId/regenerate-cell (the natural way to redo a withheld cell)
//   GET  /tabular-review/:reviewId                (stored cells, including cells saved before the gate existed)
//   POST /tabular-review/prompt                   (model column prompt: Gate 1, fixed 502 on a veto or any gate failure)
//   chat title                                    (round 3, part C: gateTitleText over the exact title; fallback = the user's message; stored titles are an open item)
//   limiter                                       (the per-call gate timeout: frees the slot once, a late result is ignored)
//
// Run once by test_tabular_bypass.py under backend's tsx. REAL: the express router from backend/src/routes/tabular.ts
// (handlers pulled out of the router stack, after requireAuth) and the whole of hallucination_guard.ts. STUBBED: req /
// res, Supabase (a recording fake), runLLMStream (a stand-in that, like the real one, calls the route's own
// buildCitations on fullText), model calls, storage, access, auth. Gate 1 is a stub verifier, except the cases named
// "real_gate", which run the production verify closure (verifyDraftForSse -> verifyDraft -> localGate1Text ->
// pipeline/gate1.py) against the fixture database named by KINGSFIELD_FLORIDA_DB, with Supabase replaced by a Proxy
// that throws. No Supabase, CourtListener, LLM or network.
//
// Every assertion is about what can leave the server (res writes, res.json bodies, database payloads), never about the
// mechanism, so a fix may take any shape.
//
// Prints one JSON line: { results: { caseName: null | "failure text" }, info: { ... } }.

import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import path from 'node:path';
import {
  ABORTED_MESSAGE,
  CELL_VETO_WITHHELD_MESSAGE,
  CELL_WITHHELD_MESSAGE,
  GENERIC_ERROR_MESSAGE,
  VETO_WITHHELD_MESSAGE,
  WITHHELD_MESSAGE,
  type SseVerificationResult,
} from '../../backend/src/middleware/hallucination_guard';

// ---------- helpers ----------

const line = (ev: unknown) => `data: ${JSON.stringify(ev)}\n\n`;
const DONE = 'data: [DONE]\n\n';
const delta = (text: string) => line({ type: 'content_delta', text });
const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v));
const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

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
/** What localGate1Text answers when all its slots are taken: one whole-draft veto. */
const busy = () => result([{ ...verdict('[draft]', 'vetoed'), notes: ['gate_busy: every gate slot is in use'] }]);

const FAB = 'Doe v. Roe, 999 So. 3d 999 (Fla. 2015)';
const FAB_CORE = '999 So. 3d 999';
const RAW = 'SQLITE_CANTOPEN: unable to open /Users/x/kingsfield_florida.db; CourtListener 503 hidden-detail-7731';
const RAW_LEAKS = ['SQLITE', 'CANTOPEN', 'kingsfield_florida', 'hidden-detail-7731', '/Users/x'];

/** Stub Gate 1: vetoes any text holding the fabricated cite, as the real gate vetoes it. Sees only the text it is given. */
function fabVerify(text: string): SseVerificationResult {
  return text.includes(FAB_CORE) ? result([verdict(FAB, 'vetoed')]) : result([]);
}

function leakCheck(blob: string, needles: string[], label: string) {
  for (const n of needles) assert.ok(!blob.includes(n), `${label}: "${n}" reached the client or the database`);
}

/** Fabricated "NNN So. 3d NNN" cites, however dressed, after the normalisation a renderer or the gate applies. */
function leakedCites(blob: string): string[] {
  let t = blob.normalize('NFKC');
  t = t.replace(/\p{Cf}/gu, '');
  t = t.replace(/&#(\d+);/g, (_m, n) => String.fromCodePoint(Number(n))).replace(/&amp;/g, '&').replace(/&nbsp;/g, ' ');
  t = t.replace(/<!--[\s\S]*?-->/g, '').replace(/<[^>]*>/g, '');
  return [...t.matchAll(/(\d{3})\W{0,3}So\W{0,3}3d\W{0,3}(\d{3})/g)].map((m) => `${m[1]} So. 3d ${m[2]}`);
}

function requireRealGate() {
  assert.ok(process.env.KINGSFIELD_FLORIDA_DB, 'KINGSFIELD_FLORIDA_DB is not set: the real-gate cases need the fixture database');
}

const noSupabase: any = new Proxy({}, {
  get: () => {
    throw new Error('harness: the real-gate cases must never reach Supabase');
  },
});

// ---------- the real tabular router, with its dependencies stubbed ----------

const ROOT = process.cwd();
const nodeRequire = createRequire(path.join(ROOT, 'backend', 'package.json'));
const TABULAR = path.join(ROOT, 'backend', 'src', 'routes', 'tabular.ts');
const GUARD_PATH = path.join(ROOT, 'backend', 'src', 'middleware', 'hallucination_guard.ts');

const S: {
  db: any;
  realGate: boolean;
  verify: (text: string) => Promise<SseVerificationResult>;
  runLLMStream: (p: any) => Promise<any>;
  streamChatWithTools: (p: any) => Promise<void>;
  completeText: (p: any) => Promise<string>;
  getUserModelSettings: () => Promise<any>;
  timeline: string[];
} = {} as any;

function resetStubs() {
  S.db = undefined;
  S.realGate = false;
  S.verify = async () => CLEAN;
  S.runLLMStream = async () => {
    throw new Error('runLLMStream not set');
  };
  S.streamChatWithTools = async () => {
    throw new Error('streamChatWithTools not set');
  };
  S.completeText = async () => 'Table question';
  S.getUserModelSettings = async () => ({
    tabular_model: 'stub-model',
    title_model: 'stub-model',
    api_keys: { claude: 'k', openai: 'k', gemini: 'k' },
  });
  S.timeline = [];
}
resetStubs();

const requireAuthStub = function requireAuth(_req: any, _res: any, next: any) {
  next();
};

const realGuard = nodeRequire(GUARD_PATH);
const STUBS: Record<string, any> = {
  '../middleware/auth': { requireAuth: requireAuthStub },
  '../lib/supabase': { createServerSupabase: () => S.db },
  '../lib/storage': { downloadFile: async () => null },
  '../lib/documentVersions': { attachActiveVersionPaths: async () => {}, loadActiveVersion: async () => null },
  '../lib/convert': { normalizeDocxZipPaths: async (b: any) => b },
  '../lib/chatTools': {
    // Same rule as chatTools.isAbortError.
    isAbortError: (e: any) => !!e && typeof e === 'object' && (e.name === 'AbortError' || e.message === 'Stream aborted.'),
    runLLMStream: (p: any) => S.runLLMStream(p),
    TABULAR_TOOLS: [{ name: 'read_table_cells' }],
  },
  '../lib/llm': {
    completeText: (p: any) => S.completeText(p),
    providerForModel: () => 'claude',
    streamChatWithTools: (p: any) => S.streamChatWithTools(p),
  },
  '../lib/userSettings': { getUserModelSettings: () => S.getUserModelSettings() },
  '../lib/access': {
    checkProjectAccess: async () => ({ ok: true }),
    ensureReviewAccess: async () => ({ ok: true, isOwner: true }),
    filterAccessibleDocumentIds: async (ids: string[]) => ids,
  },
  // The real guard; only the Gate 1 verifier the routes call is replaced (stub, or the production closure).
  '../middleware/hallucination_guard': {
    ...realGuard,
    verifyDraftForSse: (text: string, _opts: unknown) => {
      S.timeline.push('verify');
      if (S.realGate) return realGuard.verifyDraftForSse(text, { courtListenerToken: '', supabase: noSupabase });
      return S.verify(text);
    },
  },
};

const ModuleCtor: any = nodeRequire('module');
const origLoad = ModuleCtor._load;
ModuleCtor._load = function (request: string, parent: any, ...rest: unknown[]) {
  if (parent && parent.filename === TABULAR && Object.prototype.hasOwnProperty.call(STUBS, request)) return STUBS[request];
  return origLoad.call(this, request, parent, ...rest);
};
const tabular = nodeRequire(TABULAR);
ModuleCtor._load = origLoad;

function handlerFor(method: 'get' | 'post', routePath: string) {
  const layer = tabular.tabularRouter.stack.find(
    (l: any) => l.route && l.route.path === routePath && l.route.methods && l.route.methods[method],
  );
  assert.ok(layer, `tabularRouter has no ${method.toUpperCase()} ${routePath}`);
  const stack = layer.route.stack;
  assert.ok(stack.length >= 2, `${method.toUpperCase()} ${routePath}: expected requireAuth plus a handler`);
  assert.equal(stack[0].handle, requireAuthStub, `${method.toUpperCase()} ${routePath}: requireAuth is not the first layer`);
  return stack[stack.length - 1].handle as (req: any, res: any) => Promise<void>;
}

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

function fakeRes() {
  const r: any = { statusCode: 200, headers: {}, body: undefined, writes: [] as string[], ended: false, listeners: {} };
  r.status = (c: number) => {
    r.statusCode = c;
    return r;
  };
  r.json = (b: unknown) => {
    r.body = clone(b);
    return r;
  };
  r.setHeader = (k: string, v: unknown) => {
    r.headers[k] = v;
    return r;
  };
  r.flushHeaders = () => {};
  r.write = (s: unknown) => {
    const str = String(s);
    r.writes.push(str);
    if (str.startsWith('data: {"type":"content_delta"')) S.timeline.push('write:content_delta');
    return true;
  };
  r.on = (ev: string, fn: unknown) => {
    (r.listeners[ev] ??= []).push(fn);
    return r;
  };
  r.end = () => {
    r.ended = true;
    return r;
  };
  r.locals = { userId: 'u1', userEmail: 'u@x.test' };
  return r;
}

type Op = { table: string; op: 'select' | 'insert' | 'update' | 'delete'; payload?: any; filters: any[][] };

/** Recording Supabase fake. `handle(op)` answers; the default is "no row, no error". */
function makeDb(handle: (op: Op) => { data?: any; error?: any; throws?: string } | undefined) {
  const ops: Op[] = [];
  const chain = (state: Op): any =>
    new Proxy(function () {}, {
      get(_t, prop) {
        if (prop === 'then') {
          return (res: any, rej: any) => {
            ops.push(state);
            if (state.table === 'tabular_review_chat_messages' && state.op === 'insert' && state.payload?.role === 'assistant') {
              S.timeline.push('insert:assistant');
            }
            if (state.table === 'tabular_cells' && state.op === 'update' && state.payload?.status === 'done') {
              S.timeline.push('save:done');
            }
            const r = handle(state) ?? {};
            if (r.throws) return Promise.reject(new Error(r.throws)).then(res, rej);
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
        return (...args: unknown[]) => {
          state.filters.push([String(prop), ...args]);
          return chain(state);
        };
      },
    });
  return { from: (table: string) => chain({ table, op: 'select', filters: [] }), ops };
}

const filterValue = (op: Op, name: string, col: string) => op.filters.find((f) => f[0] === name && f[1] === col)?.[2];

const REVIEW = {
  id: 'r1',
  user_id: 'u1',
  title: 'Lease review',
  project_id: null,
  document_ids: ['d1'],
  columns_config: [
    { index: 0, name: 'Term', prompt: 'p0' },
    { index: 1, name: 'Law', prompt: 'p1' },
  ],
};

const events = (res: any): any[] =>
  (res.writes as string[])
    .filter((w) => !w.startsWith(':'))
    .flatMap((w) => {
      const frames = w.split('\n\n').filter((f) => f !== '');
      assert.ok(frames.length >= 1, `an empty write: ${JSON.stringify(w)}`);
      return frames.map((f) => {
        if (f === 'data: [DONE]') return { type: '[DONE]' };
        const m = /^data: ([^\n]*)$/.exec(f);
        assert.ok(m, `a write that is neither a data line nor a keepalive: ${JSON.stringify(f.slice(0, 100))}`);
        return JSON.parse(m![1]);
      });
    });
const deltaText = (res: any) => events(res).filter((e) => e.type === 'content_delta').map((e) => e.text).join('');
const assistantRows = (db: any) =>
  db.ops.filter((o: Op) => o.table === 'tabular_review_chat_messages' && o.op === 'insert' && o.payload?.role === 'assistant');
const verificationOf = (res: any) => events(res).find((e) => e.type === 'verification');
const wireAndDb = (res: any) => JSON.stringify([res.writes, res.body ?? null, S.db.ops]);

// ---------- chat route ----------

function chatDb(opts: { throwOnAssistantInsert?: boolean } = {}) {
  return makeDb((op) => {
    if (op.table === 'tabular_reviews') return { data: REVIEW };
    if (op.table === 'tabular_cells') {
      return {
        data: [
          { document_id: 'd1', column_index: 0, content: JSON.stringify({ summary: '30 days', flag: 'green', reasoning: '' }) },
          { document_id: 'd1', column_index: 1, content: JSON.stringify({ summary: 'Florida', flag: 'grey', reasoning: '' }) },
        ],
      };
    }
    if (op.table === 'documents') return { data: [{ id: 'd1', current_version_id: null, filename: 'lease.docx' }] };
    if (op.table === 'tabular_review_chats' && op.op === 'insert') return { data: { id: 'chat1', title: null } };
    if (op.table === 'tabular_review_chat_messages' && op.op === 'insert' && op.payload?.role === 'assistant') {
      if (opts.throwOnAssistantInsert) return { throws: `db exploded ${RAW}` };
    }
    return undefined;
  });
}

/**
 * A runLLMStream stand-in faithful to the real one where it matters here: visible text streams as content_delta up to
 * the first <CITATIONS>, fullText keeps the block, and the final `citations` event carries whatever the ROUTE'S OWN
 * buildCitations makes of fullText (so the real extractTabularAnnotations builds the chips).
 */
function realisticLlm(spec: { text: string; citationsJson?: string; viaTool?: boolean }) {
  return async (p: any) => {
    const viaTool = spec.viaTool !== false;
    if (viaTool) {
      p.write(line({ type: 'tool_call_start', name: 'read_table_cells' }));
      p.write(line({ type: 'doc_read_start', filename: '2 columns x 1 row' }));
      p.write(line({ type: 'doc_read', filename: '2 columns x 1 row' }));
    }
    const half = Math.max(1, Math.floor(spec.text.length / 2));
    p.write(delta(spec.text.slice(0, half)));
    p.write(delta(spec.text.slice(half)));
    const fullText = spec.citationsJson === undefined ? spec.text : `${spec.text}<CITATIONS>${spec.citationsJson}</CITATIONS>`;
    const chips = typeof p.buildCitations === 'function' ? p.buildCitations(fullText) : [];
    p.write(line({ type: 'citations', status: 'final', citations: chips }));
    p.write(DONE);
    const evs: any[] = viaTool ? [{ type: 'doc_read', filename: '2 columns x 1 row' }] : [];
    evs.push({ type: 'content', text: spec.text });
    return { fullText, events: evs, annotations: chips };
  };
}

/** [{"ref":..,"col_index":..,"row_index":..,"quote":".."}] as JSON TEXT; `field` gets rawValue spliced in as a JSON string verbatim. */
function chipJson(field: string, rawValue: string, quote: string) {
  const val = (name: string, dflt: string) => (name === field ? `"${rawValue}"` : dflt);
  return `[{"ref":${val('ref', '1')},"col_index":${val('col_index', '0')},"row_index":${val('row_index', '0')},"quote":"${quote}"}]`;
}

async function callChatWith(res: any, body?: any) {
  const req: any = {
    body: body ?? { messages: [{ role: 'user', content: 'What law governs?' }] },
    params: { reviewId: 'r1' },
    query: {},
    headers: {},
  };
  await quiet(() => handlerFor('post', '/:reviewId/chat')(req, res));
  return res;
}
const callChat = (body?: any) => callChatWith(fakeRes(), body);

// ---------- generate / regenerate / get ----------

function genDb(opts: { cols?: number } = {}) {
  const colCount = opts.cols ?? 2;
  const cols = Array.from({ length: colCount }, (_, i) => ({ index: i, name: `C${i}`, prompt: `p${i}` }));
  const review = { ...REVIEW, columns_config: cols };
  return makeDb((op) => {
    if (op.table === 'tabular_reviews') return { data: review };
    if (op.table === 'tabular_cells' && op.op === 'select') {
      return { data: cols.map((c) => ({ id: `c${c.index}`, review_id: 'r1', document_id: 'd1', column_index: c.index, status: 'pending', content: null })) };
    }
    if (op.table === 'documents') return { data: [{ id: 'd1', current_version_id: null, filename: 'lease.docx', storage_path: '', file_type: 'docx' }] };
    return undefined;
  });
}

function genDbTwoDocs() {
  const cols = [{ index: 0, name: 'C0', prompt: 'p0' }];
  const review = { ...REVIEW, columns_config: cols, document_ids: ['d1', 'd2'] };
  return makeDb((op) => {
    if (op.table === 'tabular_reviews') return { data: review };
    if (op.table === 'tabular_cells' && op.op === 'select') {
      return {
        data: ['d1', 'd2'].map((d) => ({ id: `c-${d}`, review_id: 'r1', document_id: d, column_index: 0, status: 'pending', content: null })),
      };
    }
    if (op.table === 'documents') {
      return {
        data: [
          { id: 'd1', current_version_id: null, filename: 'one.docx', storage_path: '', file_type: 'docx' },
          { id: 'd2', current_version_id: null, filename: 'two.docx', storage_path: '', file_type: 'docx' },
        ],
      };
    }
    return undefined;
  });
}

/** Make the model stream these cells (one JSON line each), as queryTabularAllColumns expects. */
function modelCells(cells: Array<Record<string, unknown>>) {
  return async (p: any) => {
    for (const c of cells) p.callbacks.onContentDelta(`${JSON.stringify({ flag: 'green', reasoning: '', ...c })}\n`);
  };
}

async function callGenerate() {
  const req: any = { body: {}, params: { reviewId: 'r1' }, query: {}, headers: {} };
  const res = fakeRes();
  await quiet(() => handlerFor('post', '/:reviewId/generate')(req, res));
  return res;
}

const doneUpdate = (db: any, col: number, doc = 'd1') =>
  db.ops.find(
    (o: Op) =>
      o.table === 'tabular_cells' && o.op === 'update' && o.payload?.status === 'done' &&
      filterValue(o, 'eq', 'column_index') === col && filterValue(o, 'eq', 'document_id') === doc,
  );
const savedCell = (db: any, col: number, doc = 'd1') => {
  const op = doneUpdate(db, col, doc);
  assert.ok(op, `no cell was saved as done for ${doc} col ${col}`);
  return JSON.parse(op.payload.content);
};
const cellUpdates = (res: any, col: number, doc = 'd1') =>
  events(res).filter((e) => e.type === 'cell_update' && e.column_index === col && e.document_id === doc);
const sentDone = (res: any, col: number, doc = 'd1') => {
  const sent = cellUpdates(res, col, doc).filter((e) => e.status === 'done');
  assert.equal(sent.length, 1, `${doc} col ${col}: expected exactly one done cell_update, got ${sent.length}`);
  return sent[0].content;
};

function regenDb() {
  return makeDb((op) => {
    if (op.table === 'tabular_reviews') return { data: REVIEW };
    if (op.table === 'documents') return { data: { id: 'd1', current_version_id: null } };
    return undefined;
  });
}
async function callRegen() {
  const req: any = { body: { document_id: 'd1', column_index: 0 }, params: { reviewId: 'r1' }, query: {}, headers: {} };
  const res = fakeRes();
  await quiet(() => handlerFor('post', '/:reviewId/regenerate-cell')(req, res));
  return res;
}

/** Every database write of cell content must carry a verification record (i.e. have been through the cell gate). */
function ungatedCellWrites(db: any): string[] {
  const bad: string[] = [];
  for (const o of db.ops as Op[]) {
    if (o.table !== 'tabular_cells' || o.op !== 'update' || !o.payload?.content) continue;
    let rec: any = null;
    try {
      rec = typeof o.payload.content === 'string' ? JSON.parse(o.payload.content) : o.payload.content;
    } catch {
      rec = null;
    }
    if (!rec || !rec.verification || rec.verification.type !== 'verification') bad.push(String(o.payload.content).slice(0, 120));
  }
  return bad;
}

// ---------- cases ----------

const cases: Record<string, () => Promise<void>> = {};
const info: Record<string, unknown> = {};

// ===== chat: tabular chips are model-written and built by the route =====

// extractTabularAnnotations copies ref / col_index / row_index straight out of the model's JSON and builds
// col_name = `Col ${col_index}` / doc_name = `Row ${row_index}` from them when the index is not a real column / row.
// The finalizer checks only the chip's `quote`. A cite written with JSON unicode escapes is invisible to Gate 1 in fullText,
// where only the escaped form is present, so these three fields are an unchecked model-text channel.
cases.chat_chip_metadata_cannot_carry_a_fabricated_cite = async () => {
  const esc = '\\u0039\\u0039\\u0039 So. 3d \\u0039\\u0039\\u0039 (Fla. 2015)';
  const leaks: string[] = [];
  for (const field of ['ref', 'col_index', 'row_index']) {
    resetStubs();
    S.db = chatDb();
    S.verify = async (t) => fabVerify(t);
    S.runLLMStream = realisticLlm({ text: 'Cell [1] is relevant.', citationsJson: chipJson(field, esc, '30 days') });
    const res = await callChat();
    const blob = JSON.stringify([res.writes, S.db.ops]);
    if (blob.includes(FAB_CORE)) {
      const chips = (events(res).find((e) => e.type === 'citations') ?? { citations: [] }).citations;
      leaks.push(`${field} (sent chips: ${JSON.stringify(chips).slice(0, 300)})`);
    }
  }
  assert.deepEqual(leaks, [], `a fabricated cite in a tabular chip's ${leaks.length ? 'metadata' : ''} reached the client and the saved row via: ${leaks.join(' | ')}`);
};

// The same, end to end through the production gate. A JSON-unicode-escaped capital S in "So." leaves no reporter for the gate to read in fullText.
// The assertion is on the leak, not the mechanism: either the gate withholds the reply (no leak) or the chip leaks.
cases.chat_chip_metadata_real_gate = async () => {
  requireRealGate();
  const esc = '999 \\u0053o. 3d 999 (Fla. 2015)';
  const leaks: string[] = [];
  const how: Record<string, unknown> = {};
  for (const field of ['ref', 'col_index']) {
    resetStubs();
    S.realGate = true;
    S.db = chatDb();
    S.runLLMStream = realisticLlm({ text: 'Cell [1] is relevant.', citationsJson: chipJson(field, esc, ''), viaTool: false });
    const res = await callChat();
    const v = verificationOf(res);
    how[field] = { sent: deltaText(res).slice(0, 90), verificationError: v?.error ?? null, hasVetoes: v?.hasVetoes ?? null };
    const leaked = leakedCites(JSON.stringify([res.writes, S.db.ops]));
    if (leaked.length) leaks.push(`${field}: ${leaked.join('; ')}`);
  }
  info.chat_chip_metadata_real_gate = how;
  assert.deepEqual(leaks, [], `fabricated cite(s) reached the client or the saved row through a tabular chip (production gate): ${leaks.join(' | ')}`);
};

// The chip's quote IS checked (decoded, standalone). With the production gate a fabricated Florida cite in it must not survive.
cases.chat_chip_quote_with_a_fabricated_florida_cite_real_gate = async () => {
  requireRealGate();
  resetStubs();
  S.realGate = true;
  S.db = chatDb();
  S.runLLMStream = realisticLlm({
    text: 'Cell [1] is relevant.',
    citationsJson: chipJson('', '', 'see Doe v. Roe, 999 \\u0053o. 3d 999 (Fla. 2015)'),
    viaTool: false,
  });
  const res = await callChat();
  const v = verificationOf(res);
  const chips = (events(res).find((e) => e.type === 'citations') ?? { citations: [] }).citations;
  info.chat_chip_quote_real_gate = { sent: deltaText(res).slice(0, 90), chipsSent: chips.length, verificationError: v?.error ?? null };
  const blob = JSON.stringify([res.writes, S.db.ops]);
  assert.deepEqual(leakedCites(blob), [], 'a fabricated cite in a tabular chip quote reached the client or the saved row');
  leakCheck(blob, ['Doe v. Roe'], 'chip quote');
};

// ===== chat: the route-level wiring of the withhold rules =====

cases.chat_streamed_text_that_is_not_in_fulltext_is_withheld_at_the_route = async () => {
  S.db = chatDb();
  S.verify = async (t) => fabVerify(t);
  S.runLLMStream = async (p: any) => {
    p.write(delta(`Intro ${FAB}`));
    p.write(DONE);
    return { fullText: 'Intro', events: [{ type: 'content', text: 'Intro' }], annotations: [] };
  };
  const res = await callChat();
  assert.equal(deltaText(res), VETO_WITHHELD_MESSAGE);
  const rows = assistantRows(S.db);
  assert.equal(rows.length, 1);
  assert.deepEqual(rows[0].payload.content, [{ type: 'content', text: VETO_WITHHELD_MESSAGE }]);
  leakCheck(JSON.stringify([res.writes, S.db.ops]), ['Doe', 'Roe', '999'], 'streamed-only cite');
};

cases.chat_saved_text_that_is_not_the_sent_text_is_withheld_at_the_route = async () => {
  S.db = chatDb();
  S.verify = async (t) => fabVerify(t);
  S.runLLMStream = async (p: any) => {
    p.write(delta('Intro'));
    p.write(DONE);
    return { fullText: 'Intro', events: [{ type: 'content', text: `Intro ${FAB}` }], annotations: [] };
  };
  const res = await callChat();
  assert.equal(deltaText(res), WITHHELD_MESSAGE);
  const rows = assistantRows(S.db);
  assert.equal(rows.length, 1);
  assert.deepEqual(rows[0].payload.content, [{ type: 'content', text: WITHHELD_MESSAGE }]);
  leakCheck(JSON.stringify([res.writes, S.db.ops]), ['Doe', 'Roe', '999'], 'saved-only cite');
};

// Held lines that are not content: reasoning, an error with provider text, unknown event types, unparseable lines,
// a tool name carrying a cite. None may reach the client or the saved row, even though the reply itself is clean.
cases.chat_held_non_content_events_never_carry_model_text = async () => {
  S.db = chatDb();
  S.verify = async (t) => fabVerify(t);
  S.runLLMStream = async (p: any) => {
    p.write(line({ type: 'tool_call_start', name: FAB }));
    p.write(line({ type: 'reasoning_delta', text: FAB }));
    p.write(line({ type: 'reasoning_block_end' }));
    p.write(line({ type: 'error', message: `provider said ${RAW} ${FAB}` }));
    p.write(line({ type: 'mystery_event', text: FAB }));
    p.write(`data: not json ${FAB}\n\n`);
    p.write(`event: x ${FAB}\n\n`);
    p.write(delta('A clean answer.'));
    p.write(line({ type: 'citations', status: 'final', citations: [] }));
    p.write(DONE);
    return {
      fullText: 'A clean answer.',
      events: [
        { type: 'reasoning', text: FAB },
        { type: 'error', message: `provider said ${RAW}` },
        { type: 'mystery_event', text: FAB },
        { type: 'content', text: 'A clean answer.' },
      ],
      annotations: [],
    };
  };
  const res = await callChat();
  assert.equal(deltaText(res), 'A clean answer.');
  leakCheck(JSON.stringify([res.writes, S.db.ops]), ['Doe', 'Roe', '999', ...RAW_LEAKS], 'held non-content events');
  assert.equal(assistantRows(S.db).length, 1);
};

cases.chat_gate_busy_veto_withholds_the_reply = async () => {
  S.db = chatDb();
  S.runLLMStream = realisticLlm({ text: 'A clean answer.', viaTool: false });
  S.verify = async () => busy();
  const res = await callChat();
  assert.equal(deltaText(res), VETO_WITHHELD_MESSAGE);
  const rows = assistantRows(S.db);
  assert.equal(rows.length, 1);
  assert.deepEqual(rows[0].payload.content, [{ type: 'content', text: VETO_WITHHELD_MESSAGE }]);
  assert.equal(verificationOf(res).hasVetoes, true);
  leakCheck(JSON.stringify([res.writes, S.db.ops]), ['clean answer'], 'busy gate');
};

// ===== chat: abort and failure =====

// The client goes away mid-stream: the route's own close handler aborts the signal; nothing the model wrote may be saved or sent.
cases.chat_client_disconnect_mid_stream_saves_only_the_aborted_marker = async () => {
  S.db = chatDb();
  let verifyCalls = 0;
  S.verify = async () => {
    verifyCalls++;
    return CLEAN;
  };
  const res = fakeRes();
  S.runLLMStream = async (p: any) => {
    p.write(delta(`partial ${FAB}`));
    await new Promise<void>((_resolve, reject) => {
      p.signal.addEventListener('abort', () => {
        const err: any = new Error('Stream aborted.');
        err.name = 'AbortError';
        err.fullText = `partial ${FAB}`;
        err.events = [{ type: 'content', text: `partial ${FAB}` }];
        reject(err);
      });
      for (const fn of res.listeners.close ?? []) fn(); // the client leaves
    });
    return null;
  };
  await callChatWith(res);
  const rows = assistantRows(S.db);
  assert.equal(rows.length, 1, 'exactly one assistant row');
  assert.deepEqual(rows[0].payload.content, [{ type: 'content', text: ABORTED_MESSAGE }]);
  assert.equal(rows[0].payload.annotations, null);
  assert.equal(verifyCalls, 0, 'nothing is verified or released on an abort');
  assert.deepEqual(events(res).map((e) => e.type), ['chat_id'], 'only the chat id was written');
  assert.equal(res.ended, true);
  leakCheck(JSON.stringify([res.writes, S.db.ops]), ['partial', 'Doe', '999'], 'disconnect');
};

// The save of the verified reply throws (not an {error} result): the reply must not have been sent.
cases.chat_a_throwing_reply_save_means_the_reply_is_not_sent = async () => {
  S.db = chatDb({ throwOnAssistantInsert: true });
  S.runLLMStream = realisticLlm({ text: 'A perfectly clean answer about the lease.', viaTool: false });
  S.verify = async () => CLEAN;
  const res = await callChat();
  assert.ok(!res.writes.some((w: string) => w.includes('perfectly clean answer')), 'a reply that was never stored was sent');
  const evs = events(res);
  assert.ok(!evs.some((e) => e.type === 'content_delta' || e.type === 'verification'), `sent: ${evs.map((e) => e.type).join(',')}`);
  assert.ok(evs.some((e) => e.type === 'error' && e.message === GENERIC_ERROR_MESSAGE));
  leakCheck(JSON.stringify(res.writes), [...RAW_LEAKS, 'db exploded'], 'throwing save');
};

// ===== generate: every channel a model can write a cell through =====

cases.generate_every_model_channel_is_gated_or_dropped = async () => {
  S.db = genDb({ cols: 4 });
  S.streamChatWithTools = modelCells([
    { column_index: 0, summary: 'Yes', reasoning: `Because ${FAB}` }, // cite in the reasoning only
    { column_index: 1, summary: `Governed by ${FAB}`, reasoning: 'secret-reasoning-1' }, // cite in the summary only
    { column_index: 2, summary: 'Net 30', flag: FAB, note: FAB, value: FAB, evidence: FAB }, // cite in flag and in extra JSON fields
    { column_index: 3, summary: [FAB], reasoning: '' }, // summary is a JSON array: String() joins it into the cite
  ]);
  S.verify = async (t) => fabVerify(t);
  const res = await callGenerate();
  for (const c of [0, 1, 3]) {
    const saved = savedCell(S.db, c);
    assert.equal(saved.summary, CELL_VETO_WITHHELD_MESSAGE, `col ${c}`);
    assert.equal(saved.reasoning, '', `col ${c}`);
    assert.equal(saved.flag, 'grey', `col ${c}`);
    assert.equal(saved.verification.hasVetoes, true, `col ${c}`);
  }
  const ok = savedCell(S.db, 2);
  assert.equal(ok.summary, 'Net 30');
  assert.equal(ok.flag, 'grey', 'the flag is reduced to its four values');
  assert.deepEqual(Object.keys(ok).sort(), ['flag', 'reasoning', 'summary', 'verification'], 'extra model JSON fields are not stored');
  for (const c of [0, 1, 2, 3]) assert.deepEqual(sentDone(res, c), savedCell(S.db, c), `col ${c}: sent differs from saved`);
  leakCheck(JSON.stringify([res.writes, S.db.ops]), ['Doe', 'Roe', '999', 'Because', 'Governed by', 'secret-reasoning-1'], 'generate channels');
  assert.deepEqual(ungatedCellWrites(S.db), [], 'a cell was written without a verification record');
};

// A busy gate (one whole-draft veto), a throwing gate and a malformed gate result, each on its own cell.
cases.generate_busy_throwing_and_malformed_gate_results_fail_closed_per_cell = async () => {
  S.db = genDb({ cols: 4 });
  S.streamChatWithTools = modelCells([
    { column_index: 0, summary: 'BUSY one', reasoning: 'secret-r0' },
    { column_index: 1, summary: 'THROW one', reasoning: 'secret-r1' },
    { column_index: 2, summary: 'MALFORMED one', reasoning: 'secret-r2' },
    { column_index: 3, summary: 'fine', reasoning: 'r3' },
  ]);
  S.verify = async (t) => {
    if (t.includes('BUSY')) return busy();
    if (t.includes('THROW')) throw new Error(RAW);
    if (t.includes('MALFORMED')) return {} as any;
    return CLEAN;
  };
  const res = await callGenerate();
  assert.equal(savedCell(S.db, 0).summary, CELL_VETO_WITHHELD_MESSAGE, 'busy gate = whole-draft veto');
  assert.equal(savedCell(S.db, 0).verification.hasVetoes, true);
  for (const c of [1, 2]) {
    const saved = savedCell(S.db, c);
    assert.equal(saved.summary, CELL_WITHHELD_MESSAGE, `col ${c}`);
    assert.equal(saved.reasoning, '', `col ${c}`);
    assert.equal(saved.verification.hasVetoes, true, `col ${c}`);
    assert.equal(saved.verification.error, 'Verification failed.', `col ${c}`);
  }
  assert.equal(savedCell(S.db, 3).summary, 'fine');
  for (const c of [0, 1, 2, 3]) assert.deepEqual(sentDone(res, c), savedCell(S.db, c), `col ${c}: sent differs from saved`);
  leakCheck(
    JSON.stringify([res.writes, S.db.ops]),
    [...RAW_LEAKS, 'BUSY one', 'THROW one', 'MALFORMED one', 'secret-r0', 'secret-r1', 'secret-r2'],
    'per-cell gate failures',
  );
};

// Two documents, verdicts finishing out of order: each cell is saved and sent under its own document.
cases.generate_two_documents_keep_their_own_verdicts = async () => {
  S.db = genDbTwoDocs();
  S.streamChatWithTools = async (p: any) => {
    const one = String(p.messages[0].content).includes('Document: one.docx');
    p.callbacks.onContentDelta(
      `${JSON.stringify({ column_index: 0, flag: 'green', reasoning: '', summary: one ? `Per ${FAB}` : 'Net 30' })}\n`,
    );
  };
  S.verify = async (t) => {
    if (t.includes(FAB_CORE)) await sleep(15); // the vetoed cell finishes last
    return fabVerify(t);
  };
  const res = await callGenerate();
  assert.equal(savedCell(S.db, 0, 'd1').summary, CELL_VETO_WITHHELD_MESSAGE);
  assert.equal(savedCell(S.db, 0, 'd2').summary, 'Net 30');
  assert.equal(sentDone(res, 0, 'd1').summary, CELL_VETO_WITHHELD_MESSAGE);
  assert.equal(sentDone(res, 0, 'd2').summary, 'Net 30');
  leakCheck(JSON.stringify([res.writes, S.db.ops]), ['Doe', 'Roe', '999'], 'two documents');
};

// The production verify closure on cells: reasoning-only, full-width digits, zero-width space inside the reporter.
cases.generate_real_gate_obfuscated_cites_withhold_their_cells = async () => {
  requireRealGate();
  S.realGate = true;
  S.db = genDb({ cols: 3 });
  S.streamChatWithTools = modelCells([
    { column_index: 0, summary: 'Yes', reasoning: 'Per Doe v. Roe, 999 So. 3d 999 (Fla. 2015), the clause is void.' },
    { column_index: 1, summary: 'Doe v. Roe, ２２２ So. 3d ２２２ (Fla. 2015)', reasoning: '' },
    { column_index: 2, summary: 'Per Doe v. Roe, 111 So.​ 3d 111 (Fla. 2015).', reasoning: 'x' },
  ]);
  const res = await callGenerate();
  const how: Record<string, string> = {};
  for (const c of [0, 1, 2]) {
    const saved = savedCell(S.db, c);
    how[`col${c}`] = saved.summary === CELL_VETO_WITHHELD_MESSAGE ? 'veto' : saved.summary === CELL_WITHHELD_MESSAGE ? 'generic' : 'RELEASED';
    assert.ok(
      saved.summary === CELL_VETO_WITHHELD_MESSAGE || saved.summary === CELL_WITHHELD_MESSAGE,
      `col ${c} was released: ${JSON.stringify(saved).slice(0, 200)}`,
    );
    assert.deepEqual(sentDone(res, c), saved, `col ${c}: sent differs from saved`);
  }
  info.generate_real_gate = how;
  const blob = JSON.stringify([res.writes, S.db.ops]);
  assert.deepEqual(leakedCites(blob), [], 'a fabricated cite reached the client or the database');
  leakCheck(blob, ['Doe v. Roe', 'the clause is void'], 'real-gate cells');
};

// ===== regenerate-cell: round-1 finding F2 (was ungated); the route must gate what it saves and returns. =====

cases.regenerate_cell_a_vetoed_cell_never_reaches_the_client_or_the_database = async () => {
  S.db = regenDb();
  S.completeText = async () => JSON.stringify({ summary: `Governed by ${FAB}`, flag: 'red', reasoning: 'Clause 9 secret-reason' });
  S.verify = async (t) => fabVerify(t);
  const res = await callRegen();
  assert.ok(S.timeline.includes('verify'), 'regenerate-cell never called Gate 1');
  leakCheck(wireAndDb(res), ['Doe', 'Roe', '999', 'Governed by', 'secret-reason'], 'regenerate-cell');
  assert.deepEqual(ungatedCellWrites(S.db), [], 'regenerate-cell wrote cell content with no verification record');
};

cases.regenerate_cell_a_gate_failure_never_returns_the_raw_model_text = async () => {
  S.db = regenDb();
  S.completeText = async () => JSON.stringify({ summary: 'Net 30', flag: 'green', reasoning: 'secret-reason-77' });
  S.verify = async () => {
    throw new Error(RAW);
  };
  const res = await callRegen();
  assert.ok(S.timeline.includes('verify'), 'regenerate-cell never called Gate 1');
  leakCheck(wireAndDb(res), [...RAW_LEAKS, 'secret-reason-77', 'Net 30'], 'regenerate-cell gate failure');
};

cases.regenerate_cell_a_clean_cell_is_gated_before_it_is_saved_and_still_returned = async () => {
  S.db = regenDb();
  S.completeText = async () => JSON.stringify({ summary: 'Net 30', flag: 'green', reasoning: 'Clause 4.' });
  S.verify = async (t) => fabVerify(t);
  const res = await callRegen();
  const v = S.timeline.indexOf('verify');
  const save = S.timeline.indexOf('save:done');
  assert.ok(v >= 0, 'regenerate-cell never called Gate 1');
  assert.ok(save >= 0, 'the clean cell was not saved');
  assert.ok(v < save, `the cell was saved before Gate 1 ran: ${S.timeline.join()}`);
  assert.equal(res.body?.summary, 'Net 30', 'a clean regenerated cell must still be returned');
};

// ===== GET /:reviewId: round-1 finding F3 (cells stored before the gate existed carry no verification record) =====

cases.get_review_does_not_return_ungated_stored_cells = async () => {
  const legacy = (summary: string) => ({ summary, flag: 'red', reasoning: `see ${FAB}` });
  const cells = [
    { id: 'c0', document_id: 'd1', column_index: 0, status: 'done', content: JSON.stringify(legacy(`Governed by ${FAB}`)) },
    { id: 'c1', document_id: 'd1', column_index: 1, status: 'done', content: legacy(`Per ${FAB}`) },
    {
      id: 'c2', document_id: 'd1', column_index: 2, status: 'done',
      content: JSON.stringify({
        summary: 'Net 30', flag: 'green', reasoning: '',
        verification: { type: 'verification', verdicts: [], hasVetoes: false, hasConditional: false },
      }),
    },
    { id: 'c3', document_id: 'd1', column_index: 3, status: 'done', content: `Plain ruling ${FAB}` },
  ];
  S.db = makeDb((op) => {
    if (op.table === 'tabular_reviews') return { data: REVIEW };
    if (op.table === 'tabular_cells') return { data: cells };
    if (op.table === 'documents') return { data: [{ id: 'd1', current_version_id: null, filename: 'lease.docx' }] };
    return undefined;
  });
  S.verify = async (t) => fabVerify(t);
  const req: any = { body: {}, params: { reviewId: 'r1' }, query: {}, headers: {} };
  const res = fakeRes();
  await quiet(() => handlerFor('get', '/:reviewId')(req, res));
  assert.ok(res.body, `no body (status ${res.statusCode})`);
  const kept = (res.body.cells as any[]).find((c) => c.column_index === 2);
  assert.equal(kept?.content?.summary, 'Net 30', 'a cell that carries a clean verification record must still be returned');
  leakCheck(JSON.stringify(res.body), ['Doe', 'Roe', '999', 'Governed by'], 'GET /:reviewId');
};

// ===== round 2: chip coercion =====

/** Every character as a JSON \uXXXX escape: the model's JSON text then holds no readable form of the string, only its decoded value does. */
const jsonEsc = (s: string) => Array.from(s).map((c) => '\\u' + c.charCodeAt(0).toString(16).padStart(4, '0')).join('');

// ref / col_index / row_index must be safe non-negative integers or the chip is dropped; names come from the review's own
// columns and documents or a fixed fallback; no other model key is copied. The chips are built from hand-written JSON text so
// floats, exponents, -0, 1e400 (Infinity) and integers past 2^53 reach JSON.parse exactly as a model could write them.
cases.chat_chip_fields_are_coerced_to_safe_integers_fixed_keys_and_own_names = async () => {
  const E = jsonEsc(FAB);
  const chip = (fields: string, quote?: string) =>
    `{${fields}${quote === undefined ? '' : `,"quote":"${quote}"`}}`;
  const ok = '"ref":1,"col_index":0,"row_index":0';
  const raw = [
    chip('"ref":1,"col_index":0,"row_index":0', 'keep-good'),
    // extra keys and model-written names: none may be copied (an escaped cite is invisible to Gate 1 in fullText)
    chip(
      `"ref":2,"col_index":1,"row_index":0,"col_name":"${E}","doc_name":"${E}","note":"${E}","cluster_id":7,"kind":"document","type":"case_citation","citation":"${E}","url":"http://x.test"`,
      'keep-extra',
    ),
    chip('"ref":3,"col_index":99,"row_index":99', 'keep-range'),
    chip('"ref":4,"col_index":1.0,"row_index":0e0', 'keep-float-integer'),
    chip('"ref":5,"col_index":-0,"row_index":0', 'maybe-negative-zero'),
    chip('"ref":1.5,"col_index":0,"row_index":0', 'drop-float'),
    chip('"ref":-1,"col_index":0,"row_index":0', 'drop-negative-ref'),
    chip('"ref":1,"col_index":-1,"row_index":0', 'drop-negative-col'),
    chip('"ref":1,"col_index":0,"row_index":-3', 'drop-negative-row'),
    chip('"ref":1,"col_index":"0","row_index":0', 'drop-numeric-string-col'),
    chip(`"ref":"${E}","col_index":0,"row_index":0`, 'drop-string-ref'),
    chip('"ref":"1","col_index":0,"row_index":0', 'drop-numeric-string-ref'),
    chip('"ref":1,"col_index":1e300,"row_index":0', 'drop-huge-col'),
    chip('"ref":1,"col_index":0,"row_index":9007199254740993', 'drop-unsafe-integer-row'),
    chip('"ref":1,"col_index":1e400,"row_index":0', 'drop-infinity-col'),
    chip('"ref":null,"col_index":0,"row_index":0', 'drop-null-ref'),
    chip('"ref":true,"col_index":0,"row_index":0', 'drop-bool-ref'),
    chip('"ref":[1],"col_index":0,"row_index":0', 'drop-array-ref'),
    chip('"ref":{"a":1},"col_index":0,"row_index":0', 'drop-object-ref'),
    chip('"col_index":0,"row_index":0', 'drop-missing-ref'),
    chip(ok), // no quote at all
    `{${ok},"quote":5}`, // quote is not a string
    `{${ok},"quote":["${E}"]}`,
    '7',
    '"a string"',
    'null',
    '[1,2]',
  ].join(',');
  resetStubs();
  S.db = chatDb();
  S.verify = async (t) => fabVerify(t);
  S.runLLMStream = realisticLlm({ text: 'Cell [1] is relevant.', citationsJson: `[${raw}]`, viaTool: false });
  const res = await callChat();
  const sent: any[] = (events(res).find((e) => e.type === 'citations') ?? { citations: [] }).citations;
  const rows = assistantRows(S.db);
  assert.equal(rows.length, 1);
  const saved: any[] = (rows[0].payload.annotations ?? []).filter((a: any) => a?.type === 'tabular_citation');
  const KEYS = ['col_index', 'col_name', 'doc_name', 'quote', 'ref', 'row_index', 'type'];
  const check = (chips: any[], where: string) => {
    for (const c of chips) {
      assert.deepEqual(Object.keys(c).sort(), KEYS, `${where}: chip keys ${JSON.stringify(Object.keys(c))}`);
      for (const k of ['ref', 'col_index', 'row_index']) {
        assert.ok(Number.isSafeInteger(c[k]) && c[k] >= 0, `${where}: ${k}=${JSON.stringify(c[k])} is not a safe non-negative integer`);
      }
      assert.ok(['Term', 'Law', 'Unknown column'].includes(c.col_name), `${where}: col_name ${JSON.stringify(c.col_name)}`);
      assert.ok(['lease.docx', 'Unknown document'].includes(c.doc_name), `${where}: doc_name ${JSON.stringify(c.doc_name)}`);
      assert.ok(/^(keep|maybe)-/.test(c.quote), `${where}: a chip that should have been dropped survived: ${JSON.stringify(c).slice(0, 200)}`);
    }
    const byQuote = (q: string) => chips.find((c) => c.quote === q);
    for (const q of ['keep-good', 'keep-extra', 'keep-range', 'keep-float-integer']) {
      assert.ok(byQuote(q), `${where}: the valid chip ${q} was dropped (sent: ${chips.map((c) => c.quote).join(',')})`);
    }
    assert.equal(byQuote('keep-good').col_name, 'Term');
    assert.equal(byQuote('keep-good').doc_name, 'lease.docx');
    assert.equal(byQuote('keep-extra').col_name, 'Law', `${where}: a model-written col_name was used`);
    assert.equal(byQuote('keep-extra').doc_name, 'lease.docx', `${where}: a model-written doc_name was used`);
    assert.equal(byQuote('keep-range').col_name, 'Unknown column');
    assert.equal(byQuote('keep-range').doc_name, 'Unknown document');
    assert.ok(chips.length <= 5, `${where}: ${chips.length} chips survived, at most 5 were valid`);
  };
  check(sent, 'sent');
  check(saved, 'saved');
  const blob = JSON.stringify([res.writes, S.db.ops]);
  leakCheck(blob, ['Doe', 'Roe', '999', 'x.test', 'case_citation'], 'chip coercion');
  assert.deepEqual(leakedCites(blob), [], 'a fabricated cite reached the client or the saved row through a chip');
};

// ===== round 2: POST /prompt is gated =====

const PROMPT_WITHHELD = 'The generated prompt was withheld because it could not be verified.';

async function callPrompt(body: any = { title: 'Term' }) {
  const req: any = { body, params: {}, query: {}, headers: {} };
  const res = fakeRes();
  await quiet(() => handlerFor('post', '/prompt')(req, res));
  return res;
}

// A scaled clock for the limiter's per-call timeout (75 s in production): any timer of 30 s or more fires after 20 ms here.
// The requested delays are recorded so a test can check the limit has not been shortened below the gate's own worst case.
async function withScaledGateTimeout<T>(fn: () => Promise<T>): Promise<{ out: T; requested: number[] }> {
  const orig = globalThis.setTimeout;
  const requested: number[] = [];
  (globalThis as any).setTimeout = ((f: any, ms?: number, ...a: unknown[]) => {
    if (typeof ms === 'number' && ms >= 30_000) {
      requested.push(ms);
      return orig(f, 20, ...a);
    }
    return orig(f, ms, ...a);
  }) as any;
  try {
    return { out: await fn(), requested };
  } finally {
    globalThis.setTimeout = orig;
  }
}

/** Fails (instead of hanging the whole run) when a request that should have been freed by the gate timeout is not. */
function finishes<T>(p: Promise<T>, label: string, ms = 4000): Promise<T> {
  let t: any;
  return Promise.race([
    p,
    new Promise<T>((_resolve, reject) => {
      t = setTimeout(() => reject(new Error(`${label}: still running after ${ms} ms; the gate timeout did not free the request`)), ms);
    }),
  ]).finally(() => clearTimeout(t));
}

cases.prompt_route_a_vetoed_or_unverifiable_prompt_is_never_returned = async () => {
  const modelPrompt = `Extract the governing term, citing ${FAB}`;
  const scenarios: Array<[string, (t: string) => Promise<SseVerificationResult>]> = [
    ['veto', async (t) => fabVerify(t)],
    ['gate throws', async () => { throw new Error(RAW); }],
    ['gate busy', async () => busy()],
    ['malformed result', async () => ({}) as any],
    ['error result', async () => ({ verdicts: [], hasVetoes: true, hasConditional: false, error: RAW })],
    ['pending verdict', async () => result([verdict(FAB, 'pending')])],
    ['unknown status, hasVetoes false', async () => result([verdict(FAB, 'weird')], { hasVetoes: false })],
  ];
  for (const [name, gate] of scenarios) {
    resetStubs();
    S.db = makeDb(() => undefined);
    S.completeText = async () => JSON.stringify({ prompt: modelPrompt });
    S.verify = gate;
    const res = await callPrompt();
    assert.ok(S.timeline.includes('verify'), `${name}: the prompt never went to Gate 1`);
    assert.equal(res.statusCode, 502, `${name}: status`);
    assert.deepEqual(res.body, { detail: PROMPT_WITHHELD }, `${name}: body`);
    assert.deepEqual(res.writes, [], `${name}: wrote to the stream`);
    leakCheck(JSON.stringify([res.writes, res.body]), ['Doe', 'Roe', '999', 'Extract', 'governing', ...RAW_LEAKS], `prompt route (${name})`);
  }
};

// Failures before the gate: the model call throws, returns text that is not JSON, or returns a prompt that is not a string.
cases.prompt_route_model_failures_and_non_string_prompts_return_fixed_text_only = async () => {
  const fenced = '```json\n' + JSON.stringify({ prompt: `Cite ${FAB}` }) + '\n```';
  const scenarios: Array<[string, () => Promise<string>, string]> = [
    ['completeText throws', async () => { throw new Error(`${RAW} ${FAB}`); }, 'Failed to generate prompt from LLM'],
    ['not JSON', async () => `Sure! Cite ${FAB}`, 'Failed to generate prompt from LLM'],
    ['prompt is an array', async () => JSON.stringify({ prompt: [FAB] }), 'LLM returned an empty prompt'],
    ['prompt is a number', async () => JSON.stringify({ prompt: 5 }), 'LLM returned an empty prompt'],
    ['prompt is blank', async () => JSON.stringify({ prompt: '   ', note: FAB }), 'LLM returned an empty prompt'],
    ['prompt missing, other key carries the cite', async () => JSON.stringify({ text: FAB }), 'LLM returned an empty prompt'],
  ];
  for (const [name, model, detail] of scenarios) {
    resetStubs();
    S.db = makeDb(() => undefined);
    S.completeText = model;
    S.verify = async (t) => fabVerify(t);
    const res = await callPrompt();
    assert.equal(res.statusCode, 502, `${name}: status`);
    assert.deepEqual(res.body, { detail }, `${name}: body`);
    leakCheck(JSON.stringify([res.writes, res.body]), ['Doe', 'Roe', '999', ...RAW_LEAKS], `prompt route (${name})`);
  }
  // a fenced prompt carrying the cite reaches the gate decoded and is withheld
  resetStubs();
  S.db = makeDb(() => undefined);
  S.completeText = async () => fenced;
  S.verify = async (t) => fabVerify(t);
  const res = await callPrompt();
  assert.equal(res.statusCode, 502);
  assert.deepEqual(res.body, { detail: PROMPT_WITHHELD });
};

// A clean prompt still works, the gate saw exactly the text that is returned, and nothing else the model wrote comes back.
cases.prompt_route_a_clean_prompt_is_gated_as_returned_and_nothing_else_comes_back = async () => {
  const seen: string[] = [];
  S.db = makeDb(() => undefined);
  S.completeText = async () => JSON.stringify({ prompt: '  Extract the term length.  ', note: FAB, extra: { x: FAB }, source: 'user' });
  S.verify = async (t) => {
    seen.push(t);
    return fabVerify(t);
  };
  const res = await callPrompt();
  assert.equal(res.statusCode, 200);
  assert.deepEqual(res.body, { prompt: 'Extract the term length.', source: 'llm' });
  assert.ok(seen.includes(res.body.prompt), `the gate did not see the exact returned prompt (saw ${JSON.stringify(seen)})`);
  leakCheck(JSON.stringify(res.body), ['Doe', 'Roe', '999'], 'clean prompt');
};

cases.prompt_route_real_gate_obfuscated_cites_are_withheld = async () => {
  requireRealGate();
  const prompts = [
    'Extract the term, citing Doe v. Roe, 999 So. 3d 999 (Fla. 2015)',
    'Extract the term, citing Doe v. Roe, ２２２ So. 3d ２２２ (Fla. 2015)',
    'Extract the term, citing Doe v. Roe, 111 So.​ 3d 111 (Fla. 2015)',
  ];
  const how: Record<string, string> = {};
  for (const [i, p] of prompts.entries()) {
    resetStubs();
    S.realGate = true;
    S.db = makeDb(() => undefined);
    S.completeText = async () => JSON.stringify({ prompt: p });
    const res = await callPrompt();
    how[`prompt${i}`] = `${res.statusCode}`;
    assert.equal(res.statusCode, 502, `prompt ${i} was returned: ${JSON.stringify(res.body).slice(0, 200)}`);
    assert.deepEqual(res.body, { detail: PROMPT_WITHHELD });
    leakCheck(JSON.stringify([res.writes, res.body]), ['Doe', 'Roe', 'Extract'], `real-gate prompt ${i}`);
  }
  info.prompt_real_gate = how;
};

// ===== round 2: regenerate-cell failure paths =====

cases.regenerate_cell_model_and_save_failures_return_fixed_text_and_never_the_cell = async () => {
  const clean = JSON.stringify({ summary: 'Net 30', flag: 'green', reasoning: 'secret-reason-5' });
  const saveFails = (how: 'error' | 'throws') =>
    regenDbWith((op) =>
      op.table === 'tabular_cells' && op.op === 'update' && op.payload?.status === 'done'
        ? how === 'error' ? { error: { message: RAW } } : { throws: RAW }
        : undefined);
  const scenarios: Array<[string, () => any, () => Promise<string>]> = [
    ['save returns an error', () => saveFails('error'), async () => clean],
    ['save throws', () => saveFails('throws'), async () => clean],
    ['model call throws', () => regenDb(), async () => { throw new Error(RAW); }],
    ['model returns nothing', () => regenDb(), async () => '   '],
  ];
  for (const [name, db, model] of scenarios) {
    resetStubs();
    S.db = db();
    S.completeText = model;
    S.verify = async (t) => fabVerify(t);
    const res = await callRegen();
    assert.equal(res.statusCode, 500, `${name}: status ${res.statusCode}, body ${JSON.stringify(res.body)}`);
    assert.deepEqual(res.body, { detail: 'Generation failed' }, `${name}: body`);
    leakCheck(JSON.stringify([res.writes, res.body]), [...RAW_LEAKS, 'Net 30', 'secret-reason-5'], `regenerate-cell (${name})`);
  }
};

function regenDbWith(extra: (op: Op) => { data?: any; error?: any; throws?: string } | undefined) {
  return makeDb((op) => {
    const e = extra(op);
    if (e) return e;
    if (op.table === 'tabular_reviews') return { data: REVIEW };
    if (op.table === 'documents') return { data: { id: 'd1', current_version_id: null } };
    return undefined;
  });
}

// ===== round 2: GET /:reviewId re-gates stored cells =====

const storedCell = (id: string, col: number, content: unknown, extra: Record<string, unknown> = {}) => ({
  id,
  review_id: 'r1',
  document_id: 'd1',
  column_index: col,
  status: 'done',
  created_at: '2026-01-01T00:00:00Z',
  content,
  ...extra,
});

function getDb(cells: any[]) {
  return makeDb((op) => {
    if (op.table === 'tabular_reviews') return { data: REVIEW };
    if (op.table === 'tabular_cells') return { data: cells };
    if (op.table === 'documents') return { data: [{ id: 'd1', current_version_id: null, filename: 'lease.docx' }] };
    return undefined;
  });
}

async function callGet() {
  const req: any = { body: {}, params: { reviewId: 'r1' }, query: {}, headers: {} };
  const res = fakeRes();
  await quiet(() => handlerFor('get', '/:reviewId')(req, res));
  return res;
}

const cellByCol = (res: any, col: number) => (res.body?.cells as any[] | undefined)?.find((c) => c.column_index === col);
const writesIn = (db: any) => (db.ops as Op[]).filter((o) => o.op !== 'select');

// A stored verification record is data the database holds, not a verdict: a forged clean record on text that cites a fabricated
// case, columns the client does not read, and extra JSON fields in the cell must not come back.
cases.get_review_forged_records_extra_columns_and_extra_fields_never_reach_the_client = async () => {
  const forgedClean = {
    type: 'verification',
    verdicts: [{ citation: FAB, status: 'verified', gate1_existence: true, notes: [`see ${FAB}`] }],
    hasVetoes: false,
    hasConditional: false,
  };
  const forgedVetoWithError = { type: 'verification', verdicts: [], hasVetoes: true, hasConditional: false, error: RAW };
  const extras = { citations: [{ citation: FAB }], error: RAW, raw_response: FAB, user_id: 'u9-secret', model_notes: FAB };
  const cells = [
    storedCell('c0', 0, { summary: `Per ${FAB}`, flag: 'green', reasoning: '', verification: forgedClean }, extras),
    storedCell('c1', 1, JSON.stringify({ summary: 'Net 30', flag: 'green', reasoning: `Because ${FAB}`, verification: forgedClean, note: FAB, evidence: [FAB] }), extras),
    storedCell('c2', 2, JSON.stringify({ summary: 'Net 30', flag: 'green', reasoning: '', verification: forgedVetoWithError, note: FAB }), extras),
    storedCell('c3', 3, { summary: 'Net 30', flag: 'green', reasoning: '', verification: forgedClean, note: FAB, evidence: [FAB] }, extras),
  ];
  S.db = getDb(cells);
  S.verify = async (t) => fabVerify(t);
  const res = await callGet();
  assert.ok(res.body, `no body (status ${res.statusCode})`);
  const all = res.body.cells as any[];
  assert.equal(all.length, 4);
  for (const c of all) {
    assert.deepEqual(Object.keys(c).sort(), ['column_index', 'content', 'created_at', 'document_id', 'id', 'review_id', 'status'], `cell ${c.id}: returned columns`);
    if (c.content) assert.deepEqual(Object.keys(c.content).sort(), ['flag', 'reasoning', 'summary', 'verification'], `cell ${c.id}: content keys`);
  }
  for (const col of [0, 1]) {
    assert.equal(cellByCol(res, col).content.summary, CELL_VETO_WITHHELD_MESSAGE, `col ${col}: a forged clean record let a fabricated cite through`);
    assert.equal(cellByCol(res, col).content.verification.hasVetoes, true, `col ${col}`);
    assert.equal(cellByCol(res, col).content.reasoning, '', `col ${col}`);
  }
  for (const col of [2, 3]) {
    assert.equal(cellByCol(res, col).content.summary, 'Net 30', `col ${col}: a clean text with stored junk around it`);
    assert.equal(cellByCol(res, col).content.verification.hasVetoes, false, `col ${col}: the stored record was not re-derived`);
  }
  leakCheck(JSON.stringify(res.body), ['Doe', 'Roe', '999', ...RAW_LEAKS, 'u9-secret', 'raw_response', 'model_notes', 'evidence'], 'GET forged records');
  assert.deepEqual(writesIn(S.db), [], 'GET wrote to the database');
};

// Per-request dedupe keys on (summary, flag, reasoning). Cells that differ in anything else share a verdict; cells that differ
// in any of those three never do. Checked in both orders so the first cell cannot decide for the second.
cases.get_review_dedupe_never_lends_one_cells_verdict_to_a_different_text = async () => {
  const forgedVeto = { type: 'verification', verdicts: [], hasVetoes: true, hasConditional: false };
  const forgedClean = { type: 'verification', verdicts: [], hasVetoes: false, hasConditional: false };
  const base = { summary: 'Net 30', flag: 'green', reasoning: '' };
  const build = () => [
    storedCell('a0', 0, JSON.stringify(base)),
    storedCell('a1', 1, JSON.stringify({ ...base, verification: forgedClean }), { status: 'done', created_at: 'other' }), // differs only outside the key
    storedCell('a2', 2, JSON.stringify({ ...base, flag: 'red' })), // differs only in the flag
    storedCell('a3', 3, JSON.stringify({ ...base, reasoning: `see ${FAB}` })), // differs only in the reasoning
    storedCell('a4', 4, JSON.stringify({ summary: `Net 30\n\nsee ${FAB}`, flag: 'green', reasoning: '' })), // same checked text as a3, other key
    storedCell('a5', 5, JSON.stringify({ ...base, reasoning: '   ' })), // whitespace-only reasoning
    storedCell('a6', 6, JSON.stringify({ ...base, verification: forgedVeto })),
    storedCell('a7', 7, JSON.stringify({ ...base, flag: 'purple' })), // invalid flag
  ];
  for (const order of ['forward', 'reverse']) {
    resetStubs();
    const cells = order === 'forward' ? build() : build().reverse();
    S.db = getDb(cells);
    S.verify = async (t) => fabVerify(t);
    const res = await callGet();
    assert.ok(res.body, `${order}: no body`);
    for (const col of [3, 4]) {
      assert.equal(cellByCol(res, col).content.summary, CELL_VETO_WITHHELD_MESSAGE, `${order}: col ${col} was released`);
    }
    for (const col of [0, 1, 2, 5, 7]) {
      assert.equal(cellByCol(res, col).content.verification.hasVetoes, false, `${order}: col ${col} inherited a veto`);
      assert.equal(cellByCol(res, col).content.summary, 'Net 30', `${order}: col ${col}`);
    }
    assert.deepEqual(cellByCol(res, 1).content, cellByCol(res, 0).content, `${order}: identical texts differ`);
    assert.equal(cellByCol(res, 2).content.flag, 'red', `${order}: the flag of a deduped cell was lost`);
    assert.equal(cellByCol(res, 0).content.flag, 'green', `${order}`);
    assert.equal(cellByCol(res, 7).content.flag, 'grey', `${order}: an invalid flag is reduced to grey`);
    // col 6 carries a stored veto record on a clean text: the stored record is not trusted either way, but it must not leak.
    leakCheck(JSON.stringify(res.body), ['Doe', 'Roe', '999'], `GET dedupe (${order})`);
  }
};

// Stored content in every shape parseCellContent accepts or rejects, with the cite hidden in each.
cases.get_review_odd_stored_content_shapes_never_return_a_cite = async () => {
  const cells = [
    storedCell('s0', 0, { summary: ['ok', FAB], flag: 'green' }), // String(array) joins the cite into the summary
    storedCell('s1', 1, JSON.stringify({ value: FAB })), // legacy `value`
    storedCell('s2', 2, { value: FAB, reasoning: FAB }), // object without `summary`
    storedCell('s3', 3, JSON.stringify(`Per ${FAB}`)), // a JSON string literal
    storedCell('s4', 4, JSON.stringify([{ summary: FAB }])), // a JSON array
    storedCell('s5', 5, 5),
    // the digits written as JSON \uXXXX escapes in the stored text; JSON.parse decodes them before the gate sees the summary
    storedCell('s6', 6, `{"summary":"Doe v. Roe, ${jsonEsc('999')} So. 3d ${jsonEsc('999')} (Fla. 2015)"}`),
    storedCell('s7', 7, `Plain legacy ruling ${FAB}`),
    storedCell('s8', 8, { summary: 'Net 30', flag: 'green', reasoning: { text: FAB } }), // reasoning is not a string
    storedCell('s9', 9, JSON.stringify({ summary: { text: FAB }, reasoning: '' })), // summary is an object -> "[object Object]"
  ];
  S.db = getDb(cells);
  S.verify = async (t) => fabVerify(t);
  const res = await callGet();
  assert.ok(res.body, `no body (status ${res.statusCode})`);
  const blob = JSON.stringify(res.body);
  assert.deepEqual(leakedCites(blob), [], 'a fabricated cite came back from a stored cell');
  leakCheck(blob, ['Doe', 'Roe', '999'], 'GET odd shapes');
  for (const col of [0, 1, 6, 7]) {
    assert.equal(cellByCol(res, col).content?.summary, CELL_VETO_WITHHELD_MESSAGE, `col ${col}`);
  }
  assert.deepEqual(writesIn(S.db), [], 'GET wrote to the database');
};

cases.get_review_real_gate_stored_obfuscated_cites_are_withheld = async () => {
  requireRealGate();
  S.realGate = true;
  const cells = [
    storedCell('r0', 0, { summary: 'Yes', flag: 'green', reasoning: 'Per Doe v. Roe, 999 So. 3d 999 (Fla. 2015), the clause is void.' }),
    storedCell('r1', 1, JSON.stringify({ summary: 'Doe v. Roe, ２２２ So. 3d ２２２ (Fla. 2015)', flag: 'green', reasoning: '' })),
    storedCell('r2', 2, `Per Doe v. Roe, 111 So.​ 3d 111 (Fla. 2015).`),
  ];
  S.db = getDb(cells);
  const res = await callGet();
  assert.ok(res.body, `no body (status ${res.statusCode})`);
  const how: Record<string, string> = {};
  for (const col of [0, 1, 2]) {
    const s = cellByCol(res, col).content?.summary;
    how[`col${col}`] = s === CELL_VETO_WITHHELD_MESSAGE ? 'veto' : s === CELL_WITHHELD_MESSAGE ? 'generic' : 'RELEASED';
    assert.ok(s === CELL_VETO_WITHHELD_MESSAGE || s === CELL_WITHHELD_MESSAGE, `col ${col} was released: ${JSON.stringify(cellByCol(res, col).content).slice(0, 200)}`);
  }
  info.get_review_real_gate = how;
  const blob = JSON.stringify(res.body);
  assert.deepEqual(leakedCites(blob), []);
  leakCheck(blob, ['Doe v. Roe', 'the clause is void'], 'GET real gate');
};

// ===== round 2: the limiter's per-call timeout =====
// These run last: they hold the shared limiter's slots for the scaled 20 ms.

const HANG_MS = 400; // the stub gate answers this late; the (scaled) timeout fires at 20 ms
const hangThenClean = async () => {
  await sleep(HANG_MS);
  return CLEAN;
};

cases.regenerate_cell_a_gate_that_never_answers_withholds_the_cell_and_ignores_the_late_result = async () => {
  S.db = regenDb();
  S.completeText = async () => JSON.stringify({ summary: 'Net 30', flag: 'green', reasoning: 'secret-reason-9' });
  S.verify = hangThenClean;
  const { out: res, requested } = await withScaledGateTimeout(() => finishes(callRegen(), 'regenerate-cell'));
  assert.ok(S.timeline.includes('verify'), 'the gate was never called');
  assert.equal(requested.length >= 1, true, 'the route never armed a gate timeout of 30 s or more');
  assert.ok(Math.min(...requested) >= 60_000, `the gate timeout (${Math.min(...requested)} ms) is shorter than the gate's own worst case (30 s queue + 30 s child)`);
  const needles = ['Net 30', 'secret-reason-9'];
  if (res.statusCode === 200) {
    assert.equal(res.body?.summary, CELL_WITHHELD_MESSAGE, 'a timed-out gate must give the could-not-be-verified marker');
    assert.equal(res.body?.reasoning, '');
    assert.equal(res.body?.verification?.hasVetoes, true);
  }
  leakCheck(wireAndDb(res), needles, 'regenerate-cell timeout');
  await sleep(HANG_MS + 150); // the abandoned gate call now answers CLEAN: nothing may be written or sent because of it
  leakCheck(wireAndDb(res), needles, 'regenerate-cell after the late result');
  const contentWrites = (S.db.ops as Op[]).filter((o) => o.table === 'tabular_cells' && o.op === 'update' && o.payload?.content);
  const real = contentWrites.filter((o) => typeof o.payload.content === 'string' && o.payload.content !== 'null');
  assert.ok(real.length <= 1, `the cell was written ${real.length} times`);
};

cases.prompt_route_a_gate_that_never_answers_returns_the_fixed_502_and_ignores_the_late_result = async () => {
  S.db = makeDb(() => undefined);
  S.completeText = async () => JSON.stringify({ prompt: 'Extract the term length.' });
  S.verify = hangThenClean;
  const { out: res } = await withScaledGateTimeout(() => finishes(callPrompt(), 'POST /prompt'));
  assert.equal(res.statusCode, 502);
  assert.deepEqual(res.body, { detail: PROMPT_WITHHELD });
  await sleep(HANG_MS + 150);
  assert.equal(res.statusCode, 502, 'the late result changed the status');
  assert.deepEqual(res.body, { detail: PROMPT_WITHHELD }, 'the late result changed the body');
  assert.deepEqual(res.writes, []);
};

cases.get_review_gate_calls_that_never_answer_free_their_slots_and_late_results_are_ignored = async () => {
  const c = (id: string, col: number, summary: string) => storedCell(id, col, JSON.stringify({ summary, flag: 'green', reasoning: '' }));
  // Two slots. The first two cells hold both and never answer; the rest must still be gated once the timeout frees the slots.
  const cells = [c('c0', 0, 'HANG one'), c('c1', 1, 'HANG two'), c('c2', 2, 'fine two'), c('c3', 3, 'fine three'), c('c4', 4, 'HANG three'), c('c5', 5, 'fine four')];
  S.db = getDb(cells);
  S.verify = async (t) => (t.startsWith('HANG') ? hangThenClean() : CLEAN);
  const { out: res } = await withScaledGateTimeout(() => finishes(callGet(), 'GET /:reviewId'));
  assert.ok(res.body, `no body (status ${res.statusCode})`);
  for (const col of [0, 1, 4]) {
    const content = cellByCol(res, col).content;
    assert.equal(content.summary, CELL_WITHHELD_MESSAGE, `col ${col}: a timed-out gate must give the could-not-be-verified marker`);
    assert.equal(content.verification.hasVetoes, true, `col ${col}`);
    assert.equal(content.reasoning, '', `col ${col}`);
  }
  for (const [col, text] of [[2, 'fine two'], [3, 'fine three'], [5, 'fine four']] as Array<[number, string]>) {
    assert.equal(cellByCol(res, col).content.summary, text, `col ${col}: a cell behind the timed-out ones was not gated or was lost`);
    assert.equal(cellByCol(res, col).content.verification.hasVetoes, false, `col ${col}`);
  }
  leakCheck(JSON.stringify(res.body), ['HANG'], 'GET timeout');
  await sleep(HANG_MS + 150);
  assert.deepEqual(writesIn(S.db), [], 'a late gate result caused a database write');
  leakCheck(JSON.stringify(res.body), ['HANG'], 'GET after the late results');
};

// The limiter on its own, with an injected clock: a timeout frees the slot exactly once, a late answer or a late throw is ignored.
function fakeClock() {
  const list: Array<{ fn: () => void; ms: number; cleared: boolean; fired: boolean }> = [];
  return {
    list,
    timers: {
      setTimeout: (fn: () => void, ms: number) => {
        const t = { fn, ms, cleared: false, fired: false };
        list.push(t);
        return t;
      },
      clearTimeout: (h: any) => {
        h.cleared = true;
      },
    },
    fire(i: number) {
      const t = list[i];
      assert.ok(t && !t.cleared && !t.fired, `timer ${i} is not armed`);
      t.fired = true;
      t.fn();
    },
  };
}
const tick = () => new Promise<void>((r) => setImmediate(r));

cases.limiter_a_timeout_frees_the_slot_once_and_a_late_result_or_throw_changes_nothing = async () => {
  const unhandled: unknown[] = [];
  const onUnhandled = (e: unknown) => unhandled.push(e);
  process.on('unhandledRejection', onUnhandled);
  try {
    const clock = fakeClock();
    const lim = realGuard.createLimiter(1, { timeoutMs: 1000, timers: clock.timers });
    let settleA!: (v: string) => void;
    let failA!: (e: Error) => void;
    const pA = lim(() => new Promise<string>((res, rej) => { settleA = res; failA = rej; }), () => 'TIMEOUT');
    const started: string[] = [];
    const gate: Record<string, (v: string) => void> = {};
    const mk = (name: string) => lim(() => new Promise<string>((r) => { started.push(name); gate[name] = r; }), () => 'TIMEOUT');
    const pB = mk('B');
    const pC = mk('C');
    await tick();
    assert.deepEqual(started, [], 'queued tasks started while A holds the only slot');
    assert.equal(clock.list.length, 1, 'a queued task armed its timer before it started (queue time must not count)');
    clock.fire(0);
    assert.equal(await pA, 'TIMEOUT');
    await tick();
    assert.deepEqual(started, ['B'], 'the timeout did not free exactly one slot');
    settleA('LATE'); // A's abandoned work finishes after the timeout
    await tick();
    assert.deepEqual(started, ['B'], 'a late result freed a second slot (active counter decremented twice)');
    assert.equal(await pA, 'TIMEOUT', 'the caller promise changed after settling');
    gate.B('b');
    assert.equal(await pB, 'b');
    await tick();
    assert.deepEqual(started, ['B', 'C']);
    const pD = mk('D');
    await tick();
    assert.deepEqual(started, ['B', 'C'], 'D started while C holds the slot');
    gate.C('c');
    assert.equal(await pC, 'c');
    await tick();
    assert.deepEqual(started, ['B', 'C', 'D']);
    gate.D('d');
    assert.equal(await pD, 'd');
    // a throw that arrives after the timeout is ignored too
    const clock2 = fakeClock();
    const lim2 = realGuard.createLimiter(1, { timeoutMs: 1000, timers: clock2.timers });
    let fail2!: (e: Error) => void;
    const p2 = lim2(() => new Promise<string>((_r, rej) => { fail2 = rej; }), () => 'TIMEOUT');
    await tick();
    clock2.fire(0);
    assert.equal(await p2, 'TIMEOUT');
    fail2(new Error('late failure'));
    failA(new Error('late failure A'));
    await sleep(30);
    assert.deepEqual(unhandled, [], 'a late rejection became an unhandled rejection');
    assert.equal(clock.list.every((t) => t.fired || t.cleared), true, 'a timer was left armed after its task finished');
  } finally {
    process.removeListener('unhandledRejection', onUnhandled);
  }
};

cases.limiter_timeout_without_a_fallback_rejects_and_a_throwing_task_or_fallback_frees_its_slot = async () => {
  const clock = fakeClock();
  const lim = realGuard.createLimiter(1, { timeoutMs: 1000, timers: clock.timers });
  const pA = lim(() => new Promise<string>(() => {})).then(() => null, (e: any) => e);
  await tick();
  clock.fire(0);
  const err: any = await pA;
  assert.ok(err instanceof realGuard.LimiterTimeoutError, `expected a LimiterTimeoutError, got ${err}`);
  // a fallback that throws rejects the caller and still frees the slot
  const pB = lim(() => new Promise<string>(() => {}), () => { throw new Error('fallback boom'); }).then(() => null, (e: any) => e);
  await tick();
  clock.fire(1);
  assert.equal(((await pB) as Error).message, 'fallback boom');
  // a task that throws synchronously frees the slot
  const pC = lim(() => { throw new Error('sync boom'); }).then(() => null, (e: any) => e);
  assert.equal(((await pC) as Error).message, 'sync boom');
  // and the slot is really free
  assert.equal(await lim(async () => 'after', () => 'TIMEOUT'), 'after');
};

// ===== round 3 (Part C): the model-written tabular chat title =====
// The title runs after the reply is saved and sent: one update of tabular_review_chats.title and one chat_title event,
// both with the title that passed Gate 1 (gateTitleText over the exact string saved and sent), or with the start of the
// user's first message (user text, not gated), or with nothing at all. The title gate shares the reply's verifier, so every
// stub here answers CLEAN for the reply text and applies its rule to anything else.

const REPLY = 'A clean answer.';
const MARK = 'Zyxwv'; // a word only the model's title carries
const FIRST = 'What law governs?'; // the default first user message of callChat
const GOOD = 'Good v. Case, 1 So. 3d 2 (Fla. 2010)';

const CONFUSABLES: Record<string, string> = {
  'а': 'a', 'е': 'e', 'о': 'o', 'р': 'p', 'с': 'c', 'х': 'x', 'і': 'i', 'ѕ': 's',
  'Ѕ': 'S', 'О': 'O', 'ο': 'o', 'Ο': 'O',
};

/** Like leakedCites, but also finds a cite whose page is cut to one or two digits, folds Cyrillic/Greek look-alikes, keeps HTML attribute text and is case-blind. */
function leakedCitesCut(blob: string): string[] {
  let t = blob.normalize('NFKC');
  t = t.replace(/\p{Cf}/gu, '');
  t = t.replace(/[аеорсхіѕЅОοΟ]/g, (c) => CONFUSABLES[c] ?? c);
  t = t.replace(/&#(\d+);/g, (_m, n) => String.fromCodePoint(Number(n))).replace(/&amp;/g, '&').replace(/&nbsp;/g, ' ');
  t = t.replace(/<!--[\s\S]*?-->/g, '').replace(/[<>]/g, ' ');
  t = t.replace(/\\/g, '');
  return [...t.matchAll(/(\d{3})\W{0,3}So\W{0,3}3d\W{0,3}(\d{1,3})/gi)].map((m) => `${m[1]} So. 3d ${m[2]}`);
}

/** A verifier that lets the reply through and applies `rule` to every other string (the title). `rule` may return an Error to throw it. */
const replyAware = (rule: (t: string) => any) => async (t: string) => {
  if (t.includes(REPLY)) return CLEAN;
  const r = rule(t);
  if (r instanceof Error) throw r;
  return r;
};

/** Every string the title gate was given: whatever the verifier saw that is not the reply. */
function titleRunner(rule: (t: string) => any) {
  const seen: string[] = [];
  const verify = replyAware((t) => {
    seen.push(t);
    return rule(t);
  });
  return { verify, seen };
}

const tabTitleWrites = (db: any): Op[] =>
  db.ops.filter((o: Op) => o.table === 'tabular_review_chats' && o.op === 'update' && o.payload && Object.prototype.hasOwnProperty.call(o.payload, 'title'));
const chatTitleEvents = (res: any) => events(res).filter((e) => e.type === 'chat_title');

/** `expected` is the one title saved and sent, or null when neither may happen. The reply is saved once and is not touched by the title. */
function assertTabularTitle(res: any, expected: string | null, label: string) {
  const w = tabTitleWrites(S.db);
  const ev = chatTitleEvents(res);
  if (expected === null) {
    assert.deepEqual(w.map((o) => o.payload), [], `${label}: a title was saved`);
    assert.deepEqual(ev, [], `${label}: a chat_title event was sent`);
  } else {
    assert.equal(w.length, 1, `${label}: ${w.length} title writes`);
    assert.deepEqual(w[0].payload, { title: expected }, `${label}: saved payload`);
    assert.equal(filterValue(w[0], 'eq', 'id'), 'chat1', `${label}: title saved on the wrong chat`);
    assert.deepEqual(ev, [{ type: 'chat_title', chatId: 'chat1', title: expected }], `${label}: chat_title event`);
    const types = events(res).map((e) => e.type);
    assert.ok(types.includes('verification') && types.indexOf('chat_title') > types.lastIndexOf('verification'), `${label}: the title came before the reply was complete: ${types.join()}`);
  }
  assert.equal(assistantRows(S.db).length, 1, `${label}: assistant rows`);
  assert.ok(!events(res).some((e) => e.type === 'error'), `${label}: an error event was sent after the reply`);
}

/** The spec of the fallback, written independently of the code: the start of the user's own message, '' when nothing usable is left. */
const specFallback = (m: string) => Array.from(m.replace(/[\s\u0000-\u001f\u007f]+/g, ' ').trim()).slice(0, 120).join('').trim();

function tabularTitleSetup(rule: (t: string) => any, model: () => Promise<any>) {
  const run = titleRunner(rule);
  S.db = chatDb();
  S.runLLMStream = realisticLlm({ text: REPLY, viaTool: false });
  S.verify = run.verify;
  S.completeText = model;
  return run;
}

cases.chat_title_a_fabricated_cite_in_the_model_title_falls_back_to_the_users_message = async () => {
  const run = tabularTitleSetup(fabVerify, async () => FAB);
  const res = await callChat();
  assertTabularTitle(res, FIRST, 'plain');
  assert.deepEqual(run.seen, [FAB], 'the model title never went to Gate 1, or went more than once');
  leakCheck(JSON.stringify([res.writes, S.db.ops]), ['Doe', 'Roe', '999'], 'chat title');
};

cases.chat_title_a_clean_title_is_gated_as_saved_and_sent_once = async () => {
  const run = tabularTitleSetup(fabVerify, async () => '  Lease Term Question \n');
  const res = await callChat();
  assert.deepEqual(run.seen, ['Lease Term Question'], 'the gate must see exactly the string that is saved');
  assertTabularTitle(res, 'Lease Term Question', 'clean');
};

// The route trims and cuts to 80 characters; quotes and markdown stay. A cite must not survive any dressing, a cut cite is checked as
// cut, and a cite the cut removes is not put back.
cases.chat_title_padding_markdown_and_truncation_cannot_hide_a_cite = async () => {
  const padded = [
    `"${FAB}"`, `'${FAB}'`, `**${FAB}**`, `# ${FAB}`, `> ${FAB}`, `\n\n  ${FAB}  \n`, `[${FAB}](http://x.test)`, `"""${FAB}."""`, `${FAB}?!`,
  ];
  for (const raw of padded) {
    resetStubs();
    const run = tabularTitleSetup(fabVerify, async () => raw);
    const res = await callChat();
    assertTabularTitle(res, FIRST, `padded ${JSON.stringify(raw)}`);
    assert.equal(run.seen.length, 1, `padded ${JSON.stringify(raw)}: gate calls`);
    assert.ok(run.seen[0].includes(FAB_CORE), `padded ${JSON.stringify(raw)}: the gate was not given the cite`);
    leakCheck(JSON.stringify([res.writes, S.db.ops]), ['Doe', 'Roe', '999'], `padded ${JSON.stringify(raw)}`);
  }
  // (a) the cut leaves "999 So. 3d 9" at the end of the title.
  const tail = 'Doe v. Roe, 999 So. 3d 9';
  const raw = `${'q'.repeat(80 - tail.length - 1)} ${tail}99 (Fla. 2015) and more words after the cite`;
  assert.ok(raw.slice(0, 80).endsWith('So. 3d 9'), 'harness: the cut is not where the case needs it');
  resetStubs();
  const strict = tabularTitleSetup((t) => (/\d{3} So\. 3d \d/.test(t) ? result([verdict(FAB, 'vetoed')]) : CLEAN), async () => raw);
  let res = await callChat();
  assertTabularTitle(res, FIRST, 'cut cite');
  assert.equal(strict.seen.length, 1);
  assert.ok(strict.seen[0].length <= 80, `the gate was given ${strict.seen[0].length} characters`);
  assert.deepEqual(leakedCitesCut(JSON.stringify([res.writes, S.db.ops])), [], 'a cite fragment reached the client or the database');
  // (b) the cite starts after character 80 and is cut away; a gate that lets everything through must see, and the route save, the cut string.
  resetStubs();
  const beyond = `${'q'.repeat(78)} ${FAB}`;
  const lenient = tabularTitleSetup(() => CLEAN, async () => beyond);
  res = await callChat();
  assertTabularTitle(res, beyond.slice(0, 80), 'cite beyond the cut');
  assert.deepEqual(lenient.seen, [beyond.slice(0, 80)]);
  assert.deepEqual(leakedCitesCut(JSON.stringify([res.writes, S.db.ops])), [], 'a cite came back after the cut');
  leakCheck(JSON.stringify([res.writes, S.db.ops]), ['999'], 'cite beyond the cut');
};

cases.chat_title_every_gate_failure_mode_gives_the_users_message_and_nothing_else = async () => {
  const matrix: Array<[string, (t: string) => any]> = [
    ['veto', () => result([verdict(FAB, 'vetoed')])],
    ['pending', () => result([verdict(GOOD, 'pending')], { hasVetoes: false })],
    ['unknown status, no veto flag', () => result([verdict(GOOD, 'weird-status')], { hasVetoes: false })],
    ['missing status, no veto flag', () => ({ verdicts: [{ citation: GOOD, notes: [] }], hasVetoes: false, hasConditional: false })],
    ['veto flag with no verdict', () => ({ verdicts: [], hasVetoes: true, hasConditional: false })],
    ['whole-draft placeholder marked verified', () => result([verdict('[draft]', 'verified')], { hasVetoes: false })],
    ['gate busy (whole-draft veto)', () => busy()],
    ['error result', () => ({ verdicts: [], hasVetoes: true, hasConditional: false, error: RAW })],
    ['error result, no veto flag', () => ({ verdicts: [], hasVetoes: false, hasConditional: false, error: RAW })],
    ['throw', () => new Error(RAW)],
    ['malformed {}', () => ({})],
    ['null', () => null],
    ['a string', () => 'ok'],
    ['verdicts is not an array', () => ({ verdicts: 'x', hasVetoes: false, hasConditional: false })],
    ['one verified and one vetoed', () => result([verdict(GOOD, 'verified'), verdict(FAB, 'vetoed')])],
  ];
  for (const [label, rule] of matrix) {
    resetStubs();
    const run = tabularTitleSetup(rule, async () => `${MARK} ${GOOD}`);
    const res = await callChat();
    assertTabularTitle(res, FIRST, label);
    assert.equal(run.seen.length, 1, `${label}: the model title went to the gate ${run.seen.length} times`);
    leakCheck(JSON.stringify([res.writes, S.db.ops]), [MARK, 'Good v. Case', ...RAW_LEAKS], label);
  }
};

cases.chat_title_a_gate_that_never_answers_falls_back_ignores_the_late_answer_and_ends = async () => {
  const late: Array<(r: SseVerificationResult) => void> = [];
  tabularTitleSetup(() => new Promise<SseVerificationResult>((resolve) => late.push(resolve)), async () => `${MARK} Title`);
  const { out: res, requested } = await withScaledGateTimeout(() => finishes(callChat(), 'tabular chat'));
  assertTabularTitle(res, FIRST, 'timeout');
  assert.ok(requested.length >= 1, 'the route never armed a title gate timeout of 30 s or more');
  assert.ok(Math.min(...requested) >= 60_000, `the title gate limit (${Math.min(...requested)} ms) is shorter than the gate's own worst case (30 s queue + 30 s child)`);
  for (const r of late) r(CLEAN);
  await sleep(40);
  assertTabularTitle(res, FIRST, 'timeout, after the late answer');
  leakCheck(JSON.stringify([res.writes, S.db.ops]), [MARK], 'late answer');
};

// A failed model call is not a veto: the title is the user's own message and the gate is not involved.
cases.chat_title_model_failures_use_the_users_message_and_never_the_raw_error = async () => {
  const bad: Array<[string, () => Promise<any>]> = [
    ['throws', async () => { throw new Error(`provider exploded ${RAW}`); }],
    ['empty', async () => ''],
    ['blank', async () => '   \n'],
    ['null', async () => null],
    ['a number', async () => 5],
    ['an object', async () => ({ title: FAB })],
  ];
  for (const [label, model] of bad) {
    resetStubs();
    const run = tabularTitleSetup(fabVerify, model);
    const res = await callChat();
    assertTabularTitle(res, FIRST, label);
    assert.deepEqual(run.seen, [], `${label}: there was no model title, so nothing for the gate`);
    leakCheck(JSON.stringify([res.writes, S.db.ops]), [...RAW_LEAKS, 'provider exploded', 'Doe', '999'], label);
  }
};

// The title is written after the reply is saved and sent. A failing save only logs: the reply is not marked failed, no second
// message is saved, no error event goes out, and no raw text leaks.
cases.chat_title_a_failing_save_only_logs_and_leaves_the_reply_alone = async () => {
  const dbWith = (how: 'throws' | 'error') =>
    makeDb((op) => {
      if (op.table === 'tabular_review_chats' && op.op === 'update' && op.payload && 'title' in op.payload) {
        return how === 'throws' ? { throws: `title save exploded ${RAW}` } : { error: { message: RAW } };
      }
      if (op.table === 'tabular_reviews') return { data: REVIEW };
      if (op.table === 'tabular_cells') {
        return {
          data: [
            { document_id: 'd1', column_index: 0, content: JSON.stringify({ summary: '30 days', flag: 'green', reasoning: '' }) },
            { document_id: 'd1', column_index: 1, content: JSON.stringify({ summary: 'Florida', flag: 'grey', reasoning: '' }) },
          ],
        };
      }
      if (op.table === 'documents') return { data: [{ id: 'd1', current_version_id: null, filename: 'lease.docx' }] };
      if (op.table === 'tabular_review_chats' && op.op === 'insert') return { data: { id: 'chat1', title: null } };
      return undefined;
    });
  // throws: no chat_title, the reply stands
  tabularTitleSetup(fabVerify, async () => `${MARK} ${FAB}`);
  S.db = dbWith('throws');
  let res = await callChat();
  assert.deepEqual(chatTitleEvents(res), [], 'a chat_title was sent although the save threw');
  assert.equal(assistantRows(S.db).length, 1, 'a second assistant message was saved after the title failed');
  assert.ok(!events(res).some((e) => e.type === 'error'), 'an error event followed a reply that was already sent');
  assert.ok(events(res).some((e) => e.type === 'verification'), 'the reply was not completed');
  assert.equal(res.ended, true);
  leakCheck(JSON.stringify([res.writes, S.db.ops]), [...RAW_LEAKS, 'title save exploded', MARK, 'Doe', '999'], 'throwing title save');
  // an {error} result: the route does not look; what it sends is still only the gated title (here the fallback)
  resetStubs();
  tabularTitleSetup(fabVerify, async () => `${MARK} ${FAB}`);
  S.db = dbWith('error');
  res = await callChat();
  assert.deepEqual(chatTitleEvents(res), [{ type: 'chat_title', chatId: 'chat1', title: FIRST }]);
  leakCheck(JSON.stringify([res.writes]), [...RAW_LEAKS, MARK, 'Doe', '999'], 'error-result title save');
};

// The fallback is the start of the first user message in the request (client-supplied, not read back from the database): user text.
cases.chat_title_fallback_is_only_the_requesters_message_flattened_and_cut = async () => {
  info.chat_title_fallback_source = 'req.body.messages (client-supplied; chat history is not read back from tabular_review_chat_messages)';
  const messages = [
    '  What  are\nmy\ttermination\r\n rights?  ',
    'a\u0000b\u0007c\u007fd',
    'x'.repeat(500),
    '\u{1F600}'.repeat(200),
    `${MARK}-user wrote this`,
    '\u0007\u0001\u007f', // not whitespace, so the route proceeds, but nothing usable is left: no title at all
  ];
  for (const message of messages) {
    resetStubs();
    const run = tabularTitleSetup(fabVerify, async () => `${MARK}-model ${FAB}`);
    const res = await callChat({ messages: [{ role: 'user', content: message }] });
    const want = specFallback(message);
    assertTabularTitle(res, want === '' ? null : want, `message ${JSON.stringify(message).slice(0, 40)}`);
    assert.deepEqual(run.seen, [`${MARK}-model ${FAB}`], 'only the model title is gated');
    const blob = JSON.stringify([res.writes, S.db.ops]);
    assert.ok(!blob.includes(`${MARK}-model`), 'model words reached the client or the database');
    leakCheck(blob, ['Doe v. Roe', '999 So'], 'fallback');
    const t = tabTitleWrites(S.db)[0]?.payload.title as string | undefined;
    if (t !== undefined) {
      assert.ok(!/[\u0000-\u001f\u007f]/.test(t), 'a control character in the fallback title');
      assert.ok(Array.from(t).length <= 120, 'fallback longer than 120 code points');
    }
  }
};

cases.chat_title_real_gate_obfuscated_cites_fall_back_and_a_clean_title_passes = async () => {
  requireRealGate();
  const fabricated: Array<[string, string]> = [
    ['plain', 'Doe v. Roe, 999 So. 3d 999 (Fla. 2015)'],
    ['full-width digits', 'Doe v. Roe, ９９９ So. 3d ９９９ (Fla. 2015)'],
    ['zero-width space inside the volume', 'Doe v. Roe, 9​99 So. 3d 999 (Fla. 2015)'],
    ['period-less', 'Doe v. Roe, 999 So 3d 999 (Fla. 2015)'],
    ['markdown link title', '[Lease Rights](http://x.test "Doe v. Roe, 999 So. 3d 999 (Fla. 2015)")'],
  ];
  const released: string[] = [];
  const how: Record<string, string> = {};
  const realTitleGate = async (t: string) =>
    t.includes(REPLY) ? CLEAN : realGuard.verifyDraftForSse(t, { courtListenerToken: '', supabase: noSupabase });
  for (const [label, title] of fabricated) {
    assert.ok(title.length <= 80, `harness: "${label}" is ${title.length} units`);
    resetStubs();
    S.db = chatDb();
    S.runLLMStream = realisticLlm({ text: REPLY, viaTool: false });
    S.verify = realTitleGate;
    S.completeText = async () => title;
    const res = await callChat();
    const saved = tabTitleWrites(S.db).map((o) => o.payload.title);
    const sent = chatTitleEvents(res).map((e) => e.title);
    how[label] = saved.length === 1 && saved[0] === FIRST && sent.length === 1 && sent[0] === FIRST ? 'fallback' : `RELEASED saved=${JSON.stringify(saved)} sent=${JSON.stringify(sent)}`.slice(0, 120);
    if (how[label] !== 'fallback') released.push(`${label}: ${how[label]}`);
    const blob = JSON.stringify([res.writes, S.db.ops]);
    if (leakedCitesCut(blob).length) released.push(`${label}: ${leakedCitesCut(blob).join('; ')} reached the client or the database`);
  }
  info.chat_title_real_gate = how;
  assert.deepEqual(released, [], `fabricated cites were released as tabular chat titles (production gate): ${released.join(' | ')}`);
  // control: the gate is not vetoing everything
  resetStubs();
  S.db = chatDb();
  S.runLLMStream = realisticLlm({ text: REPLY, viaTool: false });
  S.verify = realTitleGate;
  S.completeText = async () => 'Lease Termination Rights';
  const res = await callChat();
  assertTabularTitle(res, 'Lease Termination Rights', 'control');
};

// ===== open items (skipped in Python with the reason; bodies intact) =====

// Titles saved before the title gate existed may be model-written and ungated; the list route returns them as stored.
cases.open_stored_tabular_chat_titles_are_gated_on_read = async () => {
  S.db = makeDb((op) => {
    if (op.table === 'tabular_reviews') return { data: { id: 'r1', user_id: 'u1', project_id: null } };
    if (op.table === 'tabular_review_chats') return { data: [{ id: 'chat1', title: FAB, created_at: 'x', updated_at: 'x', user_id: 'u1' }] };
    return undefined;
  });
  S.verify = async (t) => fabVerify(t);
  const req: any = { body: {}, params: { reviewId: 'r1' }, query: {}, headers: {} };
  const res = fakeRes();
  await quiet(() => handlerFor('get', '/:reviewId/chats')(req, res));
  assert.ok(res.body, `no body (status ${res.statusCode})`);
  leakCheck(JSON.stringify(res.body), ['Doe', 'Roe', '999'], 'stored tabular chat title on GET /:reviewId/chats');
};


// ---------- run ----------

async function main() {
  const results: Record<string, string | null> = {};
  for (const [name, fn] of Object.entries(cases)) {
    resetStubs();
    try {
      await fn();
      results[name] = null;
    } catch (e: any) {
      results[name] = String(e?.stack ?? e?.message ?? e).slice(0, 1200);
    }
  }
  const text = JSON.stringify({ results, info });
  process.stdout.write(`${text}\n`, () => process.exit(0));
}

void main();
