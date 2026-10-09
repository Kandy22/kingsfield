// Cases for Gate 1 over the tabular review routes (merge blocker 4, part A):
//   POST /tabular-review/:reviewId/chat      (runLLMStream with TABULAR_TOOLS -> buffering writer -> finalizeHeldOutput)
//   POST /tabular-review/:reviewId/generate  (every generated cell -> gateCellContent before it is saved or sent)
// plus the guard helpers they use (gateCellContent, createLimiter, allowTabularCitations).
//
// Run by test_tabular_route.py once under backend's tsx. What is real: the express router from
// backend/src/routes/tabular.ts, its handlers (pulled out of the router stack, after requireAuth), the whole of
// hallucination_guard.ts, safeError.ts. What is stubbed: req / res (fake objects that record writes), Supabase (a
// recording fake), runLLMStream, the model streaming / completion calls, storage, access checks, auth, and the Gate 1
// verifier (verifyDraftForSse is replaced by a stub). No Supabase, CourtListener, LLM, Python gate or network.
// Prints {caseName: null | "failure text"}.

import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import path from 'node:path';
import {
  ABORTED_MESSAGE,
  CELL_VETO_WITHHELD_MESSAGE,
  CELL_WITHHELD_MESSAGE,
  GENERIC_ERROR_MESSAGE,
  LimiterTimeoutError,
  VETO_WITHHELD_MESSAGE,
  WITHHELD_MESSAGE,
  createLimiter,
  failedReplyRecord,
  finalizeHeldOutput,
  gateCellContent,
  unverifiableCell,
  type SseVerificationResult,
} from '../../backend/src/middleware/hallucination_guard';

// ---------- helpers ----------

const line = (ev: unknown) => `data: ${JSON.stringify(ev)}\n\n`;
const DONE = 'data: [DONE]\n\n';
const delta = (text: string) => line({ type: 'content_delta', text });
const silent = () => {};
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
const RAW = 'SQLITE_CANTOPEN: unable to open /Users/x/kingsfield_florida.db; CourtListener 503 hidden-detail-7731';
const RAW_LEAKS = ['SQLITE', 'CANTOPEN', 'kingsfield_florida', 'hidden-detail-7731', '/Users/x'];

/** Vetoes any text with the fabricated cite, verifies the good one. */
function fabVerify(text: string): SseVerificationResult {
  const vs: any[] = [];
  if (text.includes(FAB_CORE)) vs.push(verdict(FAB, 'vetoed'));
  if (text.includes('1 So. 3d 2')) vs.push(verdict(GOOD, 'verified'));
  return result(vs);
}

/**
 * The route stamps rows with new Date().toISOString() (tabular_review_chats.updated_at), and the saved-ops log is scanned
 * for the fabricated cite's "999". A clock whose milliseconds read .999 would trip that scan (1 run in 1000), so ISO
 * timestamps are masked first. Nothing a model writes has this shape and a cite cannot hide inside one.
 */
const ISO_TIMESTAMP = /\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z/g;
function leakCheck(blob: string, needles: string[], label: string) {
  const scanned = blob.replace(ISO_TIMESTAMP, '<timestamp>');
  for (const n of needles) assert.ok(!scanned.includes(n), `${label}: "${n}" reached the client or a saved row`);
}

// ---------- the real tabular router, with its dependencies stubbed ----------

const ROOT = process.cwd();
const nodeRequire = createRequire(path.join(ROOT, 'backend', 'package.json'));
const TABULAR = path.join(ROOT, 'backend', 'src', 'routes', 'tabular.ts');
const GUARD_PATH = path.join(ROOT, 'backend', 'src', 'middleware', 'hallucination_guard.ts');

/** Everything a case may set. Reset before each case. */
const S: {
  db: any;
  verify: (text: string) => Promise<SseVerificationResult>;
  runLLMStream: (p: any) => Promise<any>;
  streamChatWithTools: (p: any) => Promise<void>;
  completeText: (p: any) => Promise<string>;
  getUserModelSettings: () => Promise<any>;
  timeline: string[];
  llmParams: any[];
  /** When set, every limiter timer fires after this many ms instead of the route's own limit. */
  timeoutOverrideMs: number | null;
} = {} as any;

/** What the route module asked createLimiter for when it loaded (not reset between cases). */
const limiterConfigs: Array<{ max: number; timeoutMs: number | undefined }> = [];

function resetStubs() {
  S.timeoutOverrideMs = null;
  S.db = undefined;
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
  S.llmParams = [];
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
    runLLMStream: (p: any) => {
      S.llmParams.push(p);
      return S.runLLMStream(p);
    },
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
  // The real guard, with only the Gate 1 verifier replaced (the route calls verifyDraftForSse itself).
  '../middleware/hallucination_guard': {
    ...realGuard,
    verifyDraftForSse: (text: string, _opts: unknown) => {
      S.timeline.push('verify');
      return S.verify(text);
    },
    // The title gate keeps its own module-level limiter inside the guard; when a case shortens the limiter
    // timeout, give it a limiter with that timeout (the real limit is far too long to wait for in a test).
    gateTitleText: (title: unknown, fallback: string, opts: any) =>
      realGuard.gateTitleText(
        title,
        fallback,
        S.timeoutOverrideMs === null
          ? opts
          : {
              ...opts,
              limiter: realGuard.createLimiter(1, {
                timeoutMs: S.timeoutOverrideMs,
                timers: { setTimeout: (fn: () => void, ms: number) => setTimeout(fn, ms), clearTimeout: (h: any) => clearTimeout(h) },
              }),
            },
      ),
    // The real limiter. Records what the route asked for, and lets a case shorten the timeout (the route's own
    // limit is far too long to wait for in a test) without changing anything else about the limiter.
    createLimiter: (max: number, opts: any) => {
      limiterConfigs.push({ max, timeoutMs: opts?.timeoutMs });
      return realGuard.createLimiter(max, {
        ...opts,
        timers: {
          setTimeout: (fn: () => void, ms: number) => setTimeout(fn, S.timeoutOverrideMs ?? ms),
          clearTimeout: (h: any) => clearTimeout(h),
        },
      });
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

function handlerFor(routePath: string, method: 'get' | 'post' = 'post') {
  const label = `${method.toUpperCase()} ${routePath}`;
  const layer = tabular.tabularRouter.stack.find(
    (l: any) => l.route && l.route.path === routePath && l.route.methods && l.route.methods[method],
  );
  assert.ok(layer, `tabularRouter has no ${label}`);
  const stack = layer.route.stack;
  assert.ok(stack.length >= 2, `${label}: expected requireAuth plus a handler`);
  assert.equal(stack[0].handle, requireAuthStub, `${label}: requireAuth is not the first layer`);
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
  // One chain per query: every call returns the same state, and awaiting it records and answers the query.
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

// ---------- chat route ----------

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

function chatDb(opts: { failMessageInserts?: boolean; failFirstOnly?: boolean } = {}) {
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
      if (opts.failMessageInserts) return { error: { message: 'db down: hidden-detail-7731' } };
    }
    return undefined;
  });
}

const chip = (ref: number, quote: string) => ({
  type: 'tabular_citation', ref, col_index: 0, row_index: 0, col_name: 'Term', doc_name: 'lease.docx', quote,
});

/** A runLLMStream stand-in: writes what the real one would write through `write`, then returns what it returns. */
function llmReply(spec: { text: string; chips?: any[]; fullText?: string; viaTool?: boolean }) {
  return async (p: any) => {
    const chips = spec.chips ?? [];
    if (spec.viaTool !== false) {
      p.write(line({ type: 'tool_call_start', name: 'read_table_cells' }));
      p.write(line({ type: 'doc_read_start', filename: '2 columns x 1 row' }));
      p.write(line({ type: 'doc_read', filename: '2 columns x 1 row' }));
    }
    const half = Math.max(1, Math.floor(spec.text.length / 2));
    p.write(delta(spec.text.slice(0, half)));
    p.write(delta(spec.text.slice(half)));
    p.write(line({ type: 'citations', status: 'final', citations: chips }));
    p.write(DONE);
    return {
      fullText: spec.fullText ?? spec.text,
      events: [{ type: 'doc_read', filename: '2 columns x 1 row' }, { type: 'content', text: spec.text }],
      annotations: chips,
    };
  };
}

async function callChat(body?: any) {
  const req: any = {
    body: body ?? { messages: [{ role: 'user', content: 'What law governs?' }] },
    params: { reviewId: 'r1' },
    query: {},
    headers: {},
  };
  const res = fakeRes();
  await quiet(() => handlerFor('/:reviewId/chat')(req, res));
  return res;
}

const events = (res: any): any[] =>
  (res.writes as string[])
    .filter((w) => !w.startsWith(':'))
    .flatMap((w) => {
      // One write may hold several SSE frames.
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

/** The verifier must never be reached while model text has already gone out. */
function guardedVerify(res: () => any, rule: (t: string) => SseVerificationResult | Error) {
  return async (text: string) => {
    const r = res();
    if (r) {
      const early = (r.writes as string[]).filter((w) => /"type":"(content_delta|citations|doc_read|doc_read_start)"/.test(w));
      assert.deepEqual(early, [], 'model text was sent before Gate 1 ran');
    }
    const out = rule(text);
    if (out instanceof Error) throw out;
    return out;
  };
}

// ---------- cases ----------

const cases: Record<string, () => Promise<void>> = {};

// ===== guard helpers =====

cases.cell_clean_text_passes_unchanged_with_a_clean_record = async () => {
  const cell = { summary: `Per ${GOOD}`, flag: 'green', reasoning: 'Fine.' };
  const calls: string[] = [];
  const out = await gateCellContent(cell, {
    verify: async (t) => {
      calls.push(t);
      return fabVerify(t);
    },
    logError: silent,
  });
  assert.equal(out.withheld, false);
  assert.equal(out.withheldReason, null);
  assert.equal(out.content.summary, cell.summary);
  assert.equal(out.content.reasoning, cell.reasoning);
  assert.equal(out.content.flag, 'green');
  assert.equal(out.content.verification.type, 'verification');
  assert.equal(out.content.verification.hasVetoes, false);
  assert.equal(calls.length, 1, 'one gate call per cell');
  assert.ok(calls[0].includes(cell.summary) && calls[0].includes(cell.reasoning), 'the gate saw summary and reasoning');
};

cases.cell_veto_in_the_summary_replaces_the_whole_cell_with_the_fixed_marker = async () => {
  const out = await gateCellContent({ summary: `Governed by ${FAB}`, flag: 'red', reasoning: 'Clause secret-9' }, { verify: async (t) => fabVerify(t), logError: silent });
  assert.equal(out.withheld, true);
  assert.equal(out.withheldReason, 'veto');
  assert.equal(out.content.summary, CELL_VETO_WITHHELD_MESSAGE);
  assert.equal(out.content.reasoning, '');
  assert.equal(out.content.flag, 'grey');
  assert.equal(out.content.verification.hasVetoes, true);
  const vetoed = out.content.verification.verdicts.filter((v: any) => v.status === 'vetoed');
  assert.equal(vetoed.length, 1);
  assert.equal(vetoed[0].citation, '', 'a vetoed verdict carries no citation text');
  leakCheck(JSON.stringify(out), ['Doe', 'Roe', '999', 'Governed by', 'secret-9'], 'vetoed cell');
};

cases.cell_veto_only_in_the_reasoning_withholds = async () => {
  const out = await gateCellContent({ summary: 'Yes', flag: 'green', reasoning: `See ${FAB}.` }, { verify: async (t) => fabVerify(t), logError: silent });
  assert.equal(out.withheld, true);
  assert.equal(out.content.summary, CELL_VETO_WITHHELD_MESSAGE);
  leakCheck(JSON.stringify(out), ['Doe', '999'], 'reasoning veto');
};

cases.cell_pending_unknown_and_conditional_statuses = async () => {
  for (const status of ['pending', 'weird-status']) {
    const out = await gateCellContent({ summary: `x ${GOOD}`, flag: 'grey', reasoning: '' }, {
      verify: async () => result([verdict(GOOD, status)], { hasVetoes: false }),
      logError: silent,
    });
    assert.equal(out.withheld, true, status);
    assert.equal(out.content.summary, CELL_VETO_WITHHELD_MESSAGE, status);
    assert.equal(out.content.verification.hasVetoes, true, `${status}: record must say vetoed`);
  }
  const ok = await gateCellContent({ summary: `x ${GOOD}`, flag: 'grey', reasoning: '' }, {
    verify: async () => result([verdict(GOOD, 'conditional')]),
    logError: silent,
  });
  assert.equal(ok.withheld, false, 'a conditional verdict passes, as in chat');
  assert.equal(ok.content.verification.hasConditional, true);
};

cases.cell_gate_error_throw_and_malformed_result_withhold_with_the_generic_marker = async () => {
  const logged: string[] = [];
  const logError = (ctx: string, e: unknown) => logged.push(`${ctx} ${JSON.stringify(e)}`);
  const rules: Array<[string, (t: string) => Promise<any>]> = [
    ['error result', async () => result([], { error: RAW, hasVetoes: true })],
    ['throw', async () => { throw new Error(RAW); }],
    ['malformed', async () => ({ nope: true })],
    ['null', async () => null],
  ];
  for (const [label, verify] of rules) {
    const out = await gateCellContent({ summary: `Per ${FAB}`, flag: 'green', reasoning: 'secret reasoning' }, { verify, logError });
    assert.equal(out.withheld, true, label);
    assert.equal(out.content.summary, CELL_WITHHELD_MESSAGE, label);
    assert.equal(out.content.reasoning, '', label);
    assert.equal(out.content.verification.hasVetoes, true, label);
    assert.equal(out.content.verification.error, 'Verification failed.', label);
    leakCheck(JSON.stringify(out), [...RAW_LEAKS, 'Doe', '999', 'secret reasoning'], label);
  }
  assert.ok(logged.join('\n').includes('hidden-detail-7731'), 'the raw failure goes to the server log');
};

cases.cell_malformed_input_withholds_without_calling_the_gate = async () => {
  let calls = 0;
  const verify = async () => {
    calls++;
    return CLEAN;
  };
  for (const bad of [null, undefined, 'text', 5, [], { summary: 5, reasoning: '' }, { summary: 'x' }, { summary: 'x', reasoning: null }]) {
    const out = await gateCellContent(bad, { verify, logError: silent });
    assert.equal(out.withheld, true, JSON.stringify(bad));
    assert.equal(out.content.summary, CELL_WITHHELD_MESSAGE);
  }
  assert.equal(calls, 0);
};

cases.cell_flag_is_reduced_to_its_four_values_and_extra_keys_are_dropped = async () => {
  const out = await gateCellContent({ summary: 'a', flag: 'purple; DROP', reasoning: 'b', extra: 'Doe v. Roe, 999 So. 3d 999' }, { verify: async () => CLEAN, logError: silent });
  assert.equal(out.withheld, false);
  assert.equal(out.content.flag, 'grey');
  assert.deepEqual(Object.keys(out.content).sort(), ['flag', 'reasoning', 'summary', 'verification']);
  assert.ok(!JSON.stringify(out).includes('999'));
};

cases.cell_marker_strings_are_fixed_and_distinct = async () => {
  assert.equal(CELL_VETO_WITHHELD_MESSAGE, 'This cell was withheld because it cited a case that could not be verified.');
  assert.equal(CELL_WITHHELD_MESSAGE, 'This cell could not be verified and was withheld.');
  assert.notEqual(CELL_VETO_WITHHELD_MESSAGE, CELL_WITHHELD_MESSAGE);
};

cases.limiter_runs_at_most_max_tasks_in_order_and_survives_failures = async () => {
  const limit = createLimiter(2);
  let active = 0;
  let max = 0;
  const started: number[] = [];
  const task = (i: number, fail = false) => () =>
    new Promise<number>((resolve, reject) => {
      active++;
      max = Math.max(max, active);
      started.push(i);
      setTimeout(() => {
        active--;
        if (fail) reject(new Error('boom'));
        else resolve(i);
      }, 3);
    });
  const results = await Promise.allSettled([0, 1, 2, 3, 4, 5, 6].map((i) => limit(task(i, i === 2))));
  assert.ok(max <= 2, `max in flight ${max}`);
  assert.equal(max, 2, 'the cap is actually used');
  assert.deepEqual(started, [0, 1, 2, 3, 4, 5, 6], 'FIFO');
  assert.equal(results.filter((r) => r.status === 'rejected').length, 1);
  assert.deepEqual(results.filter((r) => r.status === 'fulfilled').map((r: any) => r.value), [0, 1, 3, 4, 5, 6]);
  // A task that throws synchronously frees its slot too.
  await assert.rejects(limit(() => { throw new Error('sync'); }));
  assert.equal(await limit(async () => 'after'), 'after');
  // Nonsense limits fall back to 1.
  const one = createLimiter(0);
  let a = 0;
  let m = 0;
  await Promise.all([1, 2, 3].map(() => one(async () => { a++; m = Math.max(m, a); await new Promise((r) => setTimeout(r, 1)); a--; })));
  assert.equal(m, 1);
};

cases.tabular_chips_are_kept_only_when_asked_and_only_if_the_quote_is_clean = async () => {
  const good = chip(1, 'Payment is due in 30 days');
  const bad = chip(2, FAB);
  const text = 'Cell [1] and [2] say things.';
  const fullText = `${text}<CITATIONS>[{"ref":1,"quote":"Payment is due in 30 days"},{"ref":2,"quote":"\\u0039\\u0039\\u0039 So. 3d \\u0039\\u0039\\u0039"}]</CITATIONS>`;
  const held = [delta(text), line({ type: 'citations', status: 'final', citations: [good, bad] }), DONE];
  const base = { held, events: [{ type: 'content', text }], annotations: [good, bad], fullText, verify: async (t: string) => fabVerify(t), logError: silent };

  const off = await finalizeHeldOutput(base);
  assert.equal(off.withheld, false);
  const offCites = off.linesToSend.filter((l) => l !== DONE).map((l) => JSON.parse(l.slice(6))).find((e) => e.type === 'citations');
  assert.deepEqual(offCites.citations, [], 'default: tabular chips are dropped (chat behaviour unchanged)');
  assert.deepEqual(off.savedAnnotations.filter((a: any) => a.type !== 'verification'), []);

  const on = await finalizeHeldOutput({ ...base, allowTabularCitations: true });
  assert.equal(on.withheld, false);
  const onCites = on.linesToSend.filter((l) => l !== DONE).map((l) => JSON.parse(l.slice(6))).find((e) => e.type === 'citations');
  assert.deepEqual(onCites.citations, [good], 'the clean chip is sent; the flagged one is dropped');
  assert.deepEqual(on.savedAnnotations.filter((a: any) => a.type !== 'verification'), [good], 'saved equals sent');
  assert.equal(on.savedAnnotations[on.savedAnnotations.length - 1].type, 'verification');
  leakCheck(JSON.stringify([on.linesToSend, on.savedAnnotations]), ['999', 'Doe'], 'dropped chip');

  // A withheld reply never keeps a chip, even when the option is on.
  const veto = await finalizeHeldOutput({ ...base, allowTabularCitations: true, fullText: `${text} ${FAB}`, held: [delta(`${text} ${FAB}`), DONE], events: [{ type: 'content', text: `${text} ${FAB}` }] });
  assert.equal(veto.withheld, true);
  assert.deepEqual(veto.savedAnnotations.map((a: any) => a.type), ['verification']);
};

// ===== chat route =====

cases.chat_buffers_model_output_and_uses_the_buffering_writer = async () => {
  S.db = chatDb();
  let probe: any = null;
  S.runLLMStream = async (p: any) => {
    const before = res0.writes.length;
    p.write(delta('model text that must be held'));
    const heldBack = res0.writes.length === before;
    p.write(line({ type: 'tool_call_start', name: 'read_table_cells' }));
    const liveOk = res0.writes.length === before + 1;
    probe = { heldBack, liveOk, isRawWrite: p.write === res0.write, tools: p.extraTools };
    p.write(DONE);
    return { fullText: 'model text that must be held', events: [{ type: 'content', text: 'model text that must be held' }], annotations: [] };
  };
  const res0 = fakeRes();
  const req: any = { body: { messages: [{ role: 'user', content: 'hi' }] }, params: { reviewId: 'r1' }, query: {}, headers: {} };
  await quiet(() => handlerFor('/:reviewId/chat')(req, res0));
  assert.ok(probe, 'runLLMStream was not called');
  assert.equal(probe.isRawWrite, false, 'runLLMStream was handed the raw res.write');
  assert.equal(probe.heldBack, true, 'model text went straight to the client');
  assert.equal(probe.liveOk, true, 'a status-only event should pass live');
  assert.deepEqual(probe.tools, [{ name: 'read_table_cells' }], 'TABULAR_TOOLS must still be passed');
  assert.ok((res0.listeners.close ?? []).length >= 1, 'a close handler is registered');
};

cases.chat_vetoed_reply_sends_and_saves_only_the_withheld_message = async () => {
  S.db = chatDb();
  let res: any = null;
  const text = `As held in ${FAB}, the rule applies. Also ${GOOD}.`;
  S.runLLMStream = llmReply({ text, chips: [chip(1, 'a quote')] });
  S.verify = guardedVerify(() => res, (t) => fabVerify(t));
  const pending = (async () => {
    res = fakeRes();
    const req: any = { body: { messages: [{ role: 'user', content: 'What law governs?' }] }, params: { reviewId: 'r1' }, query: {}, headers: {} };
    await quiet(() => handlerFor('/:reviewId/chat')(req, res));
    return res;
  })();
  await pending;
  assert.equal(res.ended, true);
  assert.equal(deltaText(res), VETO_WITHHELD_MESSAGE, 'only the fixed veto message is sent');
  const types = events(res).map((e) => e.type);
  assert.ok(!types.includes('citations'), `no citations event when withheld (sent: ${types.join(',')})`);
  assert.ok(!types.includes('doc_read') && !types.includes('doc_read_start'), 'held tool-result events are dropped when withheld');
  assert.equal(types.filter((t) => t === '[DONE]').length, 1);
  const v = verificationOf(res);
  assert.ok(v, 'a verification event is sent');
  assert.equal(v.hasVetoes, true);
  const rows = assistantRows(S.db);
  assert.equal(rows.length, 1, 'exactly one assistant row');
  assert.deepEqual(rows[0].payload.content, [{ type: 'content', text: VETO_WITHHELD_MESSAGE }]);
  assert.equal(rows[0].payload.annotations.length, 1);
  assert.equal(rows[0].payload.annotations[0].type, 'verification');
  assert.equal(rows[0].payload.annotations[0].hasVetoes, true);
  assert.deepEqual(
    { verdicts: v.verdicts, hasVetoes: v.hasVetoes, hasConditional: v.hasConditional },
    { verdicts: rows[0].payload.annotations[0].verdicts, hasVetoes: true, hasConditional: rows[0].payload.annotations[0].hasConditional },
    'the saved record is the verification event',
  );
  // (A verified verdict keeps its citation in the client-safe record, as in chat; the reply text and chips are gone.)
  leakCheck(JSON.stringify([res.writes, S.db.ops]), ['Doe', 'Roe', '999', 'the rule applies', 'As held in', 'Also', 'a quote'], 'vetoed tabular reply');
};

cases.chat_gate_error_withholds_with_the_generic_message_and_leaks_nothing = async () => {
  S.db = chatDb();
  S.runLLMStream = llmReply({ text: `See ${FAB}.` });
  S.verify = async () => {
    throw new Error(RAW);
  };
  const res = await callChat();
  assert.equal(deltaText(res), WITHHELD_MESSAGE);
  const rows = assistantRows(S.db);
  assert.equal(rows.length, 1);
  assert.deepEqual(rows[0].payload.content, [{ type: 'content', text: WITHHELD_MESSAGE }]);
  assert.equal(verificationOf(res).error, 'Verification failed.');
  assert.equal(rows[0].payload.annotations[0].error, 'Verification failed.');
  leakCheck(JSON.stringify([res.writes, S.db.ops]), [...RAW_LEAKS, 'Doe', '999'], 'gate error');
};

cases.chat_clean_reply_is_sent_and_saved_unchanged_with_its_chips_and_a_verification_record = async () => {
  S.db = chatDb();
  const text = `The lease runs 30 days [1]. See ${GOOD}.`;
  const good = chip(1, 'Payment is due in 30 days');
  S.runLLMStream = llmReply({ text, chips: [good] });
  S.verify = async (t) => fabVerify(t);
  const res = await callChat();
  assert.equal(deltaText(res), text);
  const cites = events(res).find((e) => e.type === 'citations');
  assert.deepEqual(cites.citations, [good], 'the tabular chip survives a clean reply');
  const rows = assistantRows(S.db);
  assert.equal(rows.length, 1);
  assert.deepEqual(rows[0].payload.content.find((e: any) => e.type === 'content'), { type: 'content', text });
  assert.deepEqual(rows[0].payload.annotations.slice(0, 1), [good]);
  const rec = rows[0].payload.annotations[rows[0].payload.annotations.length - 1];
  assert.equal(rec.type, 'verification');
  assert.equal(rec.hasVetoes, false);
  assert.equal(verificationOf(res).hasVetoes, false);
};

cases.chat_chip_with_a_flagged_quote_is_dropped_but_the_clean_reply_is_sent = async () => {
  S.db = chatDb();
  const text = 'Two cells say things [1] [2].';
  const good = chip(1, 'Payment is due in 30 days');
  const bad = chip(2, FAB);
  const fullText = `${text}<CITATIONS>[{"ref":1},{"ref":2,"quote":"\\u0039\\u0039\\u0039 So. 3d \\u0039\\u0039\\u0039"}]</CITATIONS>`;
  S.runLLMStream = llmReply({ text, chips: [good, bad], fullText });
  S.verify = async (t) => fabVerify(t);
  const res = await callChat();
  assert.equal(deltaText(res), text);
  const sentChips = events(res).find((e) => e.type === 'citations').citations;
  assert.deepEqual(sentChips, [good]);
  const rows = assistantRows(S.db);
  assert.deepEqual(rows[0].payload.annotations.filter((a: any) => a.type !== 'verification'), [good]);
  leakCheck(JSON.stringify([res.writes, S.db.ops]), ['Doe', '999'], 'flagged quote chip');
};

/** Runs fn with `new Date()` / Date.now() frozen at a time whose milliseconds are 999. */
async function withClockAt999<T>(fn: () => Promise<T>): Promise<T> {
  const RealDate = Date;
  const FIXED = RealDate.UTC(2026, 9, 9, 12, 0, 0, 999);
  class FixedDate extends RealDate {
    constructor(...args: any[]) {
      super(...((args.length === 0 ? [FIXED] : args) as [any]));
    }
    static now() {
      return FIXED;
    }
  }
  (globalThis as any).Date = FixedDate;
  try {
    return await fn();
  } finally {
    (globalThis as any).Date = RealDate;
  }
}

const abortBody = async () => {
  S.db = chatDb();
  let verifyCalls = 0;
  S.verify = async () => {
    verifyCalls++;
    return CLEAN;
  };
  S.runLLMStream = async (p: any) => {
    p.write(delta(`partial ${FAB}`));
    const err: any = new Error('Stream aborted.');
    err.name = 'AbortError';
    err.fullText = `partial ${FAB}`;
    err.events = [{ type: 'content', text: `partial ${FAB}` }];
    throw err;
  };
  const res = await callChat();
  const rows = assistantRows(S.db);
  assert.equal(rows.length, 1, 'exactly one assistant row');
  const marker = failedReplyRecord('aborted');
  assert.deepEqual(rows[0].payload.content, marker.events);
  assert.deepEqual(rows[0].payload.content, [{ type: 'content', text: ABORTED_MESSAGE }]);
  assert.equal(rows[0].payload.annotations, null, 'a marker has no annotations');
  assert.equal(verifyCalls, 0, 'nothing to verify on an abort');
  assert.deepEqual(events(res).map((e) => e.type), ['chat_id'], 'the client is gone: nothing but the chat id was written');
  assert.equal(res.ended, true);
  leakCheck(JSON.stringify([res.writes, S.db.ops]), ['partial', 'Doe', '999'], 'aborted reply');
};
cases.chat_abort_saves_only_the_aborted_marker_and_sends_nothing = abortBody;
// The route stamps tabular_review_chats.updated_at with new Date().toISOString() after the marker is saved. The ops log
// is scanned for the fabricated cite's "999", so a clock whose milliseconds read 999 (1 run in 1000) used to fail this
// case. Frozen here so the old behaviour is a deterministic failure, not a flake.
cases.chat_abort_case_does_not_depend_on_the_wall_clock = () => withClockAt999(abortBody);

cases.chat_error_saves_only_the_failed_marker_and_sends_only_the_generic_error = async () => {
  S.db = chatDb();
  S.runLLMStream = async (p: any) => {
    p.write(delta(`partial ${FAB}`));
    const err: any = new Error('provider exploded: sk-ant-api03-SECRETSECRETSECRET1234 hidden-detail-7731');
    err.fullText = `partial ${FAB}`;
    err.events = [{ type: 'content', text: `partial ${FAB}` }, { type: 'error', message: 'provider exploded hidden-detail-7731' }];
    throw err;
  };
  const res = await callChat();
  const rows = assistantRows(S.db);
  assert.equal(rows.length, 1);
  assert.deepEqual(rows[0].payload.content, failedReplyRecord('failed').events);
  assert.equal(rows[0].payload.annotations, null);
  const evs = events(res);
  assert.deepEqual(evs.map((e) => e.type), ['chat_id', 'error', '[DONE]']);
  assert.equal(evs[1].message, GENERIC_ERROR_MESSAGE);
  leakCheck(JSON.stringify([res.writes, S.db.ops]), ['partial', 'Doe', '999', 'provider exploded', 'hidden-detail-7731', 'sk-ant'], 'failed reply');
  // The raw error goes only to the server log, and redacted.
  const logged = logs.join('\n');
  assert.ok(!logged.includes('SECRETSECRETSECRET'), 'a provider key was logged unredacted');
};

cases.chat_a_failed_save_of_the_reply_means_the_reply_is_not_sent = async () => {
  S.db = chatDb({ failMessageInserts: true });
  S.runLLMStream = llmReply({ text: 'A perfectly clean answer about the lease.' });
  S.verify = async () => CLEAN;
  const res = await callChat();
  assert.ok(!res.writes.some((w: string) => w.includes('perfectly clean answer')), 'a reply that was never stored was sent');
  const evs = events(res);
  assert.ok(!evs.some((e) => e.type === 'content_delta' || e.type === 'verification'));
  assert.ok(evs.some((e) => e.type === 'error' && e.message === GENERIC_ERROR_MESSAGE));
  leakCheck(JSON.stringify(res.writes), ['hidden-detail-7731', 'db down'], 'failed save');
};

cases.chat_reply_is_saved_before_it_is_sent = async () => {
  S.db = chatDb();
  S.runLLMStream = llmReply({ text: 'A clean answer.' });
  S.verify = async () => CLEAN;
  await callChat();
  const i = S.timeline.indexOf('insert:assistant');
  const w = S.timeline.indexOf('write:content_delta');
  assert.ok(i >= 0 && w >= 0, S.timeline.join());
  assert.ok(S.timeline.indexOf('verify') < i, 'Gate 1 runs before the save');
  assert.ok(i < w, `the reply was sent before it was saved: ${S.timeline.join()}`);
};

cases.chat_an_error_after_the_reply_is_saved_saves_no_second_message = async () => {
  S.db = chatDb();
  S.runLLMStream = llmReply({ text: 'A clean answer.' });
  S.verify = async () => CLEAN;
  let n = 0;
  S.getUserModelSettings = async () => {
    // First call is the route's own settings read; the second is the title model after the reply was sent.
    if (++n >= 2) throw new Error(RAW);
    return { tabular_model: 'm', title_model: 'm', api_keys: { claude: 'k' } };
  };
  const res = await callChat();
  assert.equal(n, 2, 'the title step was reached');
  assert.equal(assistantRows(S.db).length, 1, 'only the verified reply is saved');
  assert.equal(deltaText(res), 'A clean answer.');
  assert.ok(!events(res).some((e) => e.type === 'error'), 'no error event after a reply was delivered');
  leakCheck(JSON.stringify(res.writes), RAW_LEAKS, 'late error');
};

// ===== generate route =====

const GEN_COLS = [
  { index: 0, name: 'Term', prompt: 'p0' },
  { index: 1, name: 'Law', prompt: 'p1' },
];

function genDb(opts: { cols?: number; failDoneUpdateFor?: number; throwOnGenerating?: string } = {}) {
  const colCount = opts.cols ?? 2;
  const cols = Array.from({ length: colCount }, (_, i) => ({ index: i, name: `C${i}`, prompt: `p${i}` }));
  const review = { ...REVIEW, columns_config: cols };
  return makeDb((op) => {
    if (op.table === 'tabular_reviews') return { data: review };
    if (op.table === 'tabular_cells' && op.op === 'select') {
      return { data: cols.map((c) => ({ id: `c${c.index}`, review_id: 'r1', document_id: 'd1', column_index: c.index, status: 'pending', content: null })) };
    }
    if (op.table === 'documents') return { data: [{ id: 'd1', current_version_id: null, filename: 'lease.docx', storage_path: '', file_type: 'docx' }] };
    if (op.table === 'tabular_cells' && op.op === 'update') {
      if (opts.throwOnGenerating && op.payload?.status === 'generating') return { throws: opts.throwOnGenerating };
      if (op.payload?.status === 'done' && opts.failDoneUpdateFor === filterValue(op, 'eq', 'column_index')) {
        return { error: { message: 'db down: hidden-detail-7731' } };
      }
    }
    return undefined;
  });
}

/** Make the model stream these cells (one JSON line each), as queryTabularAllColumns expects. */
function modelCells(cells: Array<{ column_index: number; summary: string; flag?: string; reasoning?: string }>) {
  return async (p: any) => {
    for (const c of cells) p.callbacks.onContentDelta(`${JSON.stringify({ flag: 'green', reasoning: '', ...c })}\n`);
  };
}

async function callGenerate() {
  const req: any = { body: {}, params: { reviewId: 'r1' }, query: {}, headers: {} };
  const res = fakeRes();
  await quiet(() => handlerFor('/:reviewId/generate')(req, res));
  return res;
}

const doneUpdate = (db: any, col: number) =>
  db.ops.find((o: Op) => o.table === 'tabular_cells' && o.op === 'update' && o.payload?.status === 'done' && filterValue(o, 'eq', 'column_index') === col);
const cellUpdates = (res: any, col: number) => events(res).filter((e) => e.type === 'cell_update' && e.column_index === col);

cases.generate_one_vetoed_cell_is_replaced_and_the_clean_cell_is_untouched = async () => {
  S.db = genDb();
  let res: any = null;
  S.streamChatWithTools = modelCells([
    { column_index: 0, summary: '30 days [[page:2||quote:Payment due in 30 days]]', flag: 'green', reasoning: 'Clause 4.' },
    { column_index: 1, summary: `Governed by ${FAB}`, flag: 'red', reasoning: 'Clause 9, see also 999 So. 3d 999.' },
  ]);
  const gateInputs: string[] = [];
  S.verify = async (t) => {
    gateInputs.push(t);
    const early = (res?.writes ?? []).filter((w: string) => /"type":"cell_update"/.test(w) && !/"status":"generating"/.test(w));
    assert.deepEqual(early, [], 'a finished cell was sent before Gate 1 ran');
    return fabVerify(t);
  };
  res = fakeRes();
  const req: any = { body: {}, params: { reviewId: 'r1' }, query: {}, headers: {} };
  await quiet(() => handlerFor('/:reviewId/generate')(req, res));

  assert.equal(gateInputs.length, 2, 'one gate call per generated cell');

  // clean cell: saved and sent exactly as written, plus a clean record
  const saved0 = JSON.parse(doneUpdate(S.db, 0).payload.content);
  assert.equal(saved0.summary, '30 days [[page:2||quote:Payment due in 30 days]]');
  assert.equal(saved0.flag, 'green');
  assert.equal(saved0.reasoning, 'Clause 4.');
  assert.equal(saved0.verification.type, 'verification');
  assert.equal(saved0.verification.hasVetoes, false);

  // vetoed cell: the fixed marker, its verdict stored with it
  const saved1 = JSON.parse(doneUpdate(S.db, 1).payload.content);
  assert.equal(saved1.summary, CELL_VETO_WITHHELD_MESSAGE);
  assert.equal(saved1.reasoning, '');
  assert.equal(saved1.flag, 'grey');
  assert.equal(saved1.verification.hasVetoes, true);
  const vetoed = saved1.verification.verdicts.filter((v: any) => v.status === 'vetoed');
  assert.equal(vetoed.length, 1, `the veto is recorded with the cell: ${JSON.stringify(saved1.verification)}`);
  assert.equal(vetoed[0].citation, '');
  assert.equal(doneUpdate(S.db, 1).payload.status, 'done');

  // sent equals saved, for both
  const sent0 = cellUpdates(res, 0).filter((e) => e.status === 'done');
  const sent1 = cellUpdates(res, 1).filter((e) => e.status === 'done');
  assert.equal(sent0.length, 1);
  assert.equal(sent1.length, 1);
  assert.deepEqual(sent0[0].content, saved0);
  assert.deepEqual(sent1[0].content, saved1);
  leakCheck(JSON.stringify([res.writes, S.db.ops.filter((o: Op) => o.payload?.status === 'done')]).replace(/"summary":"30 days[^"]*"/g, ''), ['Doe', 'Roe', 'Governed by', 'Clause 9'], 'vetoed cell');
  assert.deepEqual(events(res).slice(-1), [{ type: '[DONE]' }]);
  assert.equal(res.ended, true);
};

cases.generate_a_gate_error_on_one_cell_fails_closed_for_that_cell_only = async () => {
  S.db = genDb();
  S.streamChatWithTools = modelCells([
    { column_index: 0, summary: 'Net 30' },
    { column_index: 1, summary: 'BOOM text', reasoning: 'why' },
  ]);
  S.verify = async (t) => {
    if (t.includes('BOOM')) throw new Error(RAW);
    return CLEAN;
  };
  const res = await callGenerate();
  const saved0 = JSON.parse(doneUpdate(S.db, 0).payload.content);
  assert.equal(saved0.summary, 'Net 30');
  const saved1 = JSON.parse(doneUpdate(S.db, 1).payload.content);
  assert.equal(saved1.summary, CELL_WITHHELD_MESSAGE);
  assert.equal(saved1.reasoning, '');
  assert.equal(saved1.verification.hasVetoes, true);
  assert.equal(saved1.verification.error, 'Verification failed.');
  assert.deepEqual(cellUpdates(res, 1).filter((e) => e.status === 'done')[0].content, saved1);
  leakCheck(JSON.stringify([res.writes, S.db.ops]), [...RAW_LEAKS, 'BOOM', 'why'], 'cell gate error');
};

cases.generate_pending_and_reasoning_only_vetoes_withhold_their_cells = async () => {
  S.db = genDb({ cols: 3 });
  S.streamChatWithTools = modelCells([
    { column_index: 0, summary: 'PENDING here' },
    { column_index: 1, summary: 'Yes', reasoning: `Because ${FAB}` },
    { column_index: 2, summary: `Fine ${GOOD}`, flag: 'green' },
  ]);
  S.verify = async (t) => (t.includes('PENDING') ? result([verdict(GOOD, 'pending')], { hasVetoes: false }) : fabVerify(t));
  await callGenerate();
  assert.equal(JSON.parse(doneUpdate(S.db, 0).payload.content).summary, CELL_VETO_WITHHELD_MESSAGE);
  assert.equal(JSON.parse(doneUpdate(S.db, 1).payload.content).summary, CELL_VETO_WITHHELD_MESSAGE);
  const ok = JSON.parse(doneUpdate(S.db, 2).payload.content);
  assert.equal(ok.summary, `Fine ${GOOD}`);
  assert.equal(ok.verification.hasVetoes, false);
};

cases.generate_gate_calls_are_capped_not_unbounded = async () => {
  const n = 8;
  S.db = genDb({ cols: n });
  S.streamChatWithTools = modelCells(Array.from({ length: n }, (_, i) => ({ column_index: i, summary: `value ${i}` })));
  let active = 0;
  let max = 0;
  let calls = 0;
  S.verify = async () => {
    calls++;
    active++;
    max = Math.max(max, active);
    await new Promise((r) => setTimeout(r, 4));
    active--;
    return CLEAN;
  };
  await callGenerate();
  assert.equal(calls, n, 'every cell is gated');
  assert.ok(max <= 2, `up to ${max} gate calls in flight at once; the cap is 2`);
  for (let i = 0; i < n; i++) assert.equal(JSON.parse(doneUpdate(S.db, i).payload.content).summary, `value ${i}`);
};

cases.generate_a_model_failure_marks_cells_errored_and_sends_no_error_text = async () => {
  S.db = genDb();
  S.streamChatWithTools = async () => {
    throw new Error(`provider exploded: ${RAW}`);
  };
  let gateCalls = 0;
  S.verify = async () => {
    gateCalls++;
    return CLEAN;
  };
  const res = await callGenerate();
  assert.equal(gateCalls, 0, 'no cell, nothing to gate');
  for (const col of [0, 1]) {
    const last = cellUpdates(res, col).pop();
    assert.equal(last.status, 'error');
    assert.equal(last.content, null);
    assert.equal(doneUpdate(S.db, col), undefined, 'no cell was saved as done');
  }
  leakCheck(JSON.stringify(res.writes), [...RAW_LEAKS, 'provider exploded'], 'model failure');
  assert.deepEqual(events(res).slice(-1), [{ type: '[DONE]' }]);
};

cases.generate_a_stream_level_error_sends_only_the_generic_message = async () => {
  S.db = genDb({ throwOnGenerating: `db exploded: ${RAW}` });
  S.streamChatWithTools = modelCells([{ column_index: 0, summary: 'x' }]);
  const res = await callGenerate();
  const errs = events(res).filter((e) => e.type === 'error');
  assert.equal(errs.length, 1);
  assert.equal(errs[0].message, GENERIC_ERROR_MESSAGE);
  assert.deepEqual(events(res).slice(-1), [{ type: '[DONE]' }]);
  leakCheck(JSON.stringify(res.writes), [...RAW_LEAKS, 'db exploded'], 'stream-level error');
  assert.equal(res.ended, true);
};

cases.generate_a_cell_that_could_not_be_saved_is_not_sent_as_done = async () => {
  S.db = genDb({ failDoneUpdateFor: 1 });
  S.streamChatWithTools = modelCells([
    { column_index: 0, summary: 'Net 30' },
    { column_index: 1, summary: 'Florida law applies' },
  ]);
  S.verify = async () => CLEAN;
  const res = await callGenerate();
  assert.equal(cellUpdates(res, 0).filter((e) => e.status === 'done').length, 1);
  assert.equal(cellUpdates(res, 1).filter((e) => e.status === 'done').length, 0, 'an unsaved cell was sent as done');
  const last = cellUpdates(res, 1).pop();
  assert.equal(last.status, 'error');
  assert.equal(last.content, null);
  leakCheck(JSON.stringify(res.writes), ['Florida law applies', 'hidden-detail-7731', 'db down'], 'unsaved cell');
};

cases.generate_cells_not_returned_by_the_model_stay_errored_with_no_content = async () => {
  S.db = genDb();
  S.streamChatWithTools = modelCells([{ column_index: 0, summary: 'Net 30' }]);
  S.verify = async () => CLEAN;
  const res = await callGenerate();
  assert.equal(JSON.parse(doneUpdate(S.db, 0).payload.content).summary, 'Net 30');
  const last = cellUpdates(res, 1).pop();
  assert.equal(last.status, 'error');
  assert.equal(last.content, null);
};

// ===== limiter: per-call timeout =====

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

cases.limiter_timeout_abandons_the_task_frees_the_slot_and_ignores_the_late_result = async () => {
  const limit = createLimiter(1, { timeoutMs: 15 });
  const timedOut = Symbol('timed out');
  let lateRan = false;
  // Task A never answers in time; it resolves long after its slot was given away.
  const a = limit(
    () => new Promise<string>((resolve) => setTimeout(() => { lateRan = true; resolve('late result'); }, 80)),
    () => timedOut as unknown as string,
  );
  // Task B is queued behind A on a one-slot limiter: it can only run once A's slot is freed by the timeout.
  const b = limit(async () => 'b done');
  assert.equal(await a, timedOut, 'the caller gets onTimeout()');
  assert.equal(await b, 'b done');
  // Ordered, not timed: timers fire in expiry order and microtasks drain between them, so B's whole run fits between the
  // 15 ms timeout and A's 80 ms late finish however slow the machine is.
  assert.equal(lateRan, false, 'B ran as soon as the timeout freed the slot, not when A finished');
  await sleep(90);
  assert.equal(lateRan, true, 'the abandoned task did finish later');
  assert.equal(await a, timedOut, 'the late result changed nothing');

  // A late REJECTION is swallowed too (no unhandled rejection), and a rejection without onTimeout is a LimiterTimeoutError.
  const rej = limit(() => new Promise<string>((_r, reject) => setTimeout(() => reject(new Error('late boom')), 50)));
  await assert.rejects(rej, (e: any) => e instanceof LimiterTimeoutError && e.name === 'LimiterTimeoutError');
  await sleep(70);
  assert.equal(await limit(async () => 'after'), 'after');
};

cases.limiter_timeout_counts_run_time_only_and_leaves_fast_tasks_alone = async () => {
  const limit = createLimiter(1, { timeoutMs: 40 });
  // Two 25 ms tasks on one slot: the second waits 25 ms in the queue and runs 25 ms. Neither exceeds 40 ms of run time.
  const results = await Promise.all([
    limit(async () => { await sleep(25); return 1; }, () => -1),
    limit(async () => { await sleep(25); return 2; }, () => -1),
  ]);
  assert.deepEqual(results, [1, 2]);
  // A task that errors in time is still a plain rejection, not a timeout.
  await assert.rejects(limit(async () => { throw new Error('plain'); }, () => 0), /plain/);
  // Nonsense limits mean "no limit".
  for (const bad of [0, -5, NaN, Infinity, undefined, null as any, '30' as any]) {
    const none = createLimiter(1, { timeoutMs: bad });
    assert.equal(await none(async () => { await sleep(10); return 'ok'; }, () => 'timed out'), 'ok', String(bad));
  }
};

cases.limiter_timeout_timer_is_cleared_when_the_task_finishes = async () => {
  const set: number[] = [];
  const cleared: unknown[] = [];
  const fns: Array<() => void> = [];
  const timers = {
    setTimeout: (fn: () => void, ms: number) => { fns.push(fn); set.push(ms); return fns.length; },
    clearTimeout: (h: unknown) => { cleared.push(h); },
  };
  const limit = createLimiter(2, { timeoutMs: 1234, timers });
  assert.equal(await limit(async () => 'x', () => 'timeout'), 'x');
  assert.deepEqual(set, [1234]);
  assert.deepEqual(cleared, [1], 'the timer of a finished task is cleared');
  // Firing the stale timer afterwards changes nothing.
  fns[0]();
  assert.equal(await limit(async () => 'y', () => 'timeout'), 'y');
  // A hung task is abandoned when its timer fires.
  const hung = limit(() => new Promise<string>(() => {}), () => 'abandoned');
  await sleep(1);
  fns[fns.length - 1]();
  assert.equal(await hung, 'abandoned');
};

cases.limiter_timeout_is_not_what_the_gate_returns_for_an_unverifiable_cell = async () => {
  const cell = unverifiableCell();
  assert.equal(cell.withheld, true);
  assert.equal(cell.content.summary, CELL_WITHHELD_MESSAGE);
  assert.equal(cell.content.reasoning, '');
  assert.equal(cell.content.flag, 'grey');
  assert.equal(cell.content.verification.hasVetoes, true);
  assert.equal(cell.content.verification.error, 'Verification failed.');
  assert.deepEqual(Object.keys(cell.content).sort(), ['flag', 'reasoning', 'summary', 'verification']);
};

cases.route_limiter_is_one_module_level_limiter_with_a_cap_and_a_timeout = async () => {
  assert.deepEqual(limiterConfigs, [{ max: 2, timeoutMs: 75_000 }], 'one limiter, cap 2, 75 s per gate call');
};

// ===== tabular chips (F1) =====

/** The visible text streams as content_delta; fullText keeps the <CITATIONS> block; the chips are what the ROUTE's own buildCitations makes of it. */
function realisticLlm(spec: { text: string; citationsJson?: string }) {
  return async (p: any) => {
    const half = Math.max(1, Math.floor(spec.text.length / 2));
    p.write(delta(spec.text.slice(0, half)));
    p.write(delta(spec.text.slice(half)));
    const fullText = spec.citationsJson === undefined ? spec.text : `${spec.text}<CITATIONS>${spec.citationsJson}</CITATIONS>`;
    const chips = p.buildCitations(fullText);
    p.write(line({ type: 'citations', status: 'final', citations: chips }));
    p.write(DONE);
    return { fullText, events: [{ type: 'content', text: spec.text }], annotations: chips };
  };
}

async function chipBuilder() {
  S.db = chatDb();
  S.runLLMStream = llmReply({ text: 'x', viaTool: false });
  await callChat();
  const p = S.llmParams[S.llmParams.length - 1];
  assert.equal(typeof p.buildCitations, 'function', 'the route passes buildCitations');
  return (json: string) => p.buildCitations(`Answer.<CITATIONS>${json}</CITATIONS>`) as any[];
}

cases.chip_fields_are_built_from_integers_and_the_reviews_own_names = async () => {
  const build = await chipBuilder();
  // The review has columns Term (0), Law (1) and one document, lease.docx.
  assert.deepEqual(build('[{"ref":1,"col_index":1,"row_index":0,"quote":"Florida"}]'), [
    { type: 'tabular_citation', ref: 1, col_index: 1, row_index: 0, col_name: 'Law', doc_name: 'lease.docx', quote: 'Florida' },
  ]);
  // Out of range: a fixed fallback with no number and no model text in it.
  assert.deepEqual(build('[{"ref":2,"col_index":9,"row_index":7,"quote":"q"}]'), [
    { type: 'tabular_citation', ref: 2, col_index: 9, row_index: 7, col_name: 'Unknown column', doc_name: 'Unknown document', quote: 'q' },
  ]);
  // Model keys that look like chip fields are never copied: only the built keys exist.
  const withExtras = build(
    `[{"ref":1,"col_index":0,"row_index":0,"quote":"q","col_name":"${FAB}","doc_name":"${FAB}","type":"x","kind":"case","cluster_id":5,"note":"${FAB}"}]`,
  );
  assert.equal(withExtras.length, 1);
  assert.deepEqual(Object.keys(withExtras[0]).sort(), ['col_index', 'col_name', 'doc_name', 'quote', 'ref', 'row_index', 'type']);
  assert.equal(withExtras[0].type, 'tabular_citation');
  assert.equal(withExtras[0].col_name, 'Term');
  assert.equal(withExtras[0].doc_name, 'lease.docx');
  leakCheck(JSON.stringify(withExtras), ['Doe', '999'], 'extra chip keys');
  // 0 is a valid index.
  assert.equal(build('[{"ref":0,"col_index":0,"row_index":0,"quote":""}]').length, 1);
};

cases.chip_with_a_non_integer_index_or_ref_or_quote_is_dropped_whole = async () => {
  const build = await chipBuilder();
  const esc = '\\u0039\\u0039\\u0039 So. 3d \\u0039\\u0039\\u0039 (Fla. 2015)';
  const bad = [
    `{"ref":"${esc}","col_index":0,"row_index":0,"quote":"q"}`,
    `{"ref":1,"col_index":"${esc}","row_index":0,"quote":"q"}`,
    `{"ref":1,"col_index":0,"row_index":"${esc}","quote":"q"}`,
    '{"ref":"1","col_index":0,"row_index":0,"quote":"q"}',
    '{"ref":1,"col_index":"0","row_index":0,"quote":"q"}',
    '{"ref":1,"col_index":0,"row_index":"0","quote":"q"}',
    '{"ref":-1,"col_index":0,"row_index":0,"quote":"q"}',
    '{"ref":1,"col_index":-2,"row_index":0,"quote":"q"}',
    '{"ref":1,"col_index":0,"row_index":-3,"quote":"q"}',
    '{"ref":1.5,"col_index":0,"row_index":0,"quote":"q"}',
    '{"ref":1,"col_index":0.1,"row_index":0,"quote":"q"}',
    '{"ref":1e400,"col_index":0,"row_index":0,"quote":"q"}',
    '{"ref":9007199254740993,"col_index":0,"row_index":0,"quote":"q"}',
    '{"ref":null,"col_index":0,"row_index":0,"quote":"q"}',
    '{"ref":true,"col_index":0,"row_index":0,"quote":"q"}',
    '{"ref":[1],"col_index":0,"row_index":0,"quote":"q"}',
    '{"ref":{"a":1},"col_index":0,"row_index":0,"quote":"q"}',
    '{"col_index":0,"row_index":0,"quote":"q"}',
    '{"ref":1,"row_index":0,"quote":"q"}',
    '{"ref":1,"col_index":0,"quote":"q"}',
    '{"ref":1,"col_index":0,"row_index":0}',
    '{"ref":1,"col_index":0,"row_index":0,"quote":5}',
    '{"ref":1,"col_index":0,"row_index":0,"quote":null}',
    '{"ref":1,"col_index":0,"row_index":0,"quote":["q"]}',
    'null',
    '7',
    '"text"',
    '[1]',
    '[]',
  ];
  for (const entry of bad) assert.deepEqual(build(`[${entry}]`), [], entry);
  // One bad entry does not take the good ones with it.
  const mixed = build(`[${bad[0]},{"ref":1,"col_index":0,"row_index":0,"quote":"keep"},${bad[3]}]`);
  assert.deepEqual(mixed.map((c) => c.quote), ['keep']);
  // Not an array / not JSON / no block: no chips.
  for (const json of ['{"ref":1,"col_index":0,"row_index":0,"quote":"q"}', '"x"', '12', 'null', 'not json', '']) {
    assert.deepEqual(build(json), [], json);
  }
  S.db = chatDb();
  assert.deepEqual((S.llmParams[S.llmParams.length - 1].buildCitations as (t: string) => unknown[])('no block here'), []);
};

cases.chip_names_never_come_from_a_non_string_or_blank_review_name = async () => {
  const review = { ...REVIEW, columns_config: [{ index: 0, name: { x: FAB } }, { index: 1, name: '   ' }] };
  S.db = makeDb((op) => {
    if (op.table === 'tabular_reviews') return { data: review };
    if (op.table === 'tabular_cells') return { data: [{ document_id: 'd1', column_index: 0, content: null }] };
    if (op.table === 'documents') return { data: [{ id: 'd1', current_version_id: null, filename: 42 }] };
    if (op.table === 'tabular_review_chats' && op.op === 'insert') return { data: { id: 'chat1', title: null } };
    return undefined;
  });
  S.runLLMStream = llmReply({ text: 'x', viaTool: false });
  await callChat();
  const build = S.llmParams[S.llmParams.length - 1].buildCitations;
  const chips = build('a<CITATIONS>[{"ref":1,"col_index":0,"row_index":0,"quote":"q"},{"ref":2,"col_index":1,"row_index":0,"quote":"q"}]</CITATIONS>');
  assert.equal(chips.length, 2);
  for (const c of chips) {
    assert.equal(c.col_name, 'Unknown column');
    // The route itself names a document without a usable filename "Untitled document" before the chips are built.
    assert.equal(c.doc_name, 'Untitled document');
  }
  // A row past the documents the review has: the chip's own fixed fallback.
  const far = build('a<CITATIONS>[{"ref":1,"col_index":0,"row_index":5,"quote":"q"}]</CITATIONS>');
  assert.equal(far[0].doc_name, 'Unknown document');
};

cases.chat_a_fabricated_cite_in_chip_metadata_never_reaches_the_client_or_the_row = async () => {
  const esc = '\\u0039\\u0039\\u0039 So. 3d \\u0039\\u0039\\u0039 (Fla. 2015)';
  for (const field of ['ref', 'col_index', 'row_index']) {
    resetStubs();
    S.db = chatDb();
    S.verify = async (t) => fabVerify(t);
    const val = (name: string, dflt: string) => (name === field ? `"${esc}"` : dflt);
    S.runLLMStream = realisticLlm({
      text: 'Cell [1] is relevant.',
      citationsJson: `[{"ref":${val('ref', '1')},"col_index":${val('col_index', '0')},"row_index":${val('row_index', '0')},"quote":"30 days"}]`,
    });
    const res = await callChat();
    leakCheck(JSON.stringify([res.writes, S.db.ops]), [FAB_CORE, 'Doe', 'Roe'], `chip ${field}`);
    // The reply itself is clean and the chip was simply dropped.
    assert.equal(deltaText(res), 'Cell [1] is relevant.', field);
    const chips = events(res).find((e) => e.type === 'citations').citations;
    assert.deepEqual(chips, [], `${field}: the chip with a model string in an index field is dropped`);
  }
  // A clean chip with real indices still goes out and is saved.
  resetStubs();
  S.db = chatDb();
  S.verify = async (t) => fabVerify(t);
  S.runLLMStream = realisticLlm({ text: 'Cell [1] is relevant.', citationsJson: '[{"ref":1,"col_index":1,"row_index":0,"quote":"Florida"}]' });
  const ok = await callChat();
  const sent = events(ok).find((e) => e.type === 'citations').citations;
  assert.equal(sent.length, 1);
  assert.equal(sent[0].col_name, 'Law');
  assert.equal(assistantRows(S.db)[0].payload.annotations[0].col_name, 'Law');
};

// ===== regenerate-cell (F2) =====

function regenDb(opts: { failSave?: boolean; throwSave?: boolean } = {}) {
  return makeDb((op) => {
    if (op.table === 'tabular_reviews') return { data: REVIEW };
    if (op.table === 'documents') return { data: { id: 'd1', current_version_id: null } };
    if (op.table === 'tabular_cells' && op.op === 'update' && op.payload?.status === 'done') {
      if (opts.throwSave) return { throws: `db exploded ${RAW}` };
      if (opts.failSave) return { error: { message: 'db down: hidden-detail-7731' } };
    }
    return undefined;
  });
}
async function callRegen() {
  const req: any = { body: { document_id: 'd1', column_index: 0 }, params: { reviewId: 'r1' }, query: {}, headers: {} };
  const res = fakeRes();
  await quiet(() => handlerFor('/:reviewId/regenerate-cell')(req, res));
  return res;
}
const wireAndDb = (res: any) => JSON.stringify([res.writes, res.body ?? null, S.db.ops]);
const regenSaved = () => {
  const ops = S.db.ops.filter((o: Op) => o.table === 'tabular_cells' && o.op === 'update' && o.payload?.status === 'done');
  assert.equal(ops.length, 1, 'exactly one cell save');
  return JSON.parse(ops[0].payload.content);
};
const errorMarks = () => S.db.ops.filter((o: Op) => o.table === 'tabular_cells' && o.op === 'update' && o.payload?.status === 'error');

cases.regenerate_cell_a_vetoed_cell_is_replaced_by_the_fixed_marker_and_the_verdict_recorded = async () => {
  S.db = regenDb();
  S.completeText = async () => JSON.stringify({ summary: `Governed by ${FAB}`, flag: 'red', reasoning: 'Clause 9 secret-reason' });
  S.verify = async (t) => fabVerify(t);
  const res = await callRegen();
  assert.equal(res.statusCode, 200);
  const saved = regenSaved();
  assert.equal(saved.summary, CELL_VETO_WITHHELD_MESSAGE);
  assert.equal(saved.reasoning, '');
  assert.equal(saved.flag, 'grey');
  assert.equal(saved.verification.type, 'verification');
  assert.equal(saved.verification.hasVetoes, true);
  const vetoed = saved.verification.verdicts.filter((v: any) => v.status === 'vetoed');
  assert.equal(vetoed.length, 1);
  assert.equal(vetoed[0].citation, '');
  assert.deepEqual(res.body, saved, 'returned equals saved, the same shape /generate sends');
  leakCheck(wireAndDb(res), ['Doe', 'Roe', '999', 'Governed by', 'secret-reason'], 'regenerate-cell veto');
};

cases.regenerate_cell_a_gate_failure_withholds_with_the_generic_marker_and_leaks_nothing = async () => {
  for (const [label, verify] of [
    ['throw', async () => { throw new Error(RAW); }],
    ['error result', async () => result([], { error: RAW, hasVetoes: true })],
    ['malformed', async () => ({ nope: 1 }) as any],
  ] as Array<[string, (t: string) => Promise<any>]>) {
    resetStubs();
    S.db = regenDb();
    S.completeText = async () => JSON.stringify({ summary: 'Net 30', flag: 'green', reasoning: 'secret-reason-77' });
    S.verify = verify;
    const res = await callRegen();
    const saved = regenSaved();
    assert.equal(saved.summary, CELL_WITHHELD_MESSAGE, label);
    assert.equal(saved.verification.error, 'Verification failed.', label);
    assert.deepEqual(res.body, saved, label);
    leakCheck(wireAndDb(res), [...RAW_LEAKS, 'Net 30', 'secret-reason-77'], `regenerate-cell ${label}`);
  }
};

cases.regenerate_cell_a_clean_cell_is_gated_before_it_is_saved_and_returned_with_its_record = async () => {
  S.db = regenDb();
  S.completeText = async () => JSON.stringify({ summary: `Per ${GOOD}`, flag: 'green', reasoning: 'Clause 4.' });
  S.verify = async (t) => fabVerify(t);
  const res = await callRegen();
  const v = S.timeline.indexOf('verify');
  const save = S.timeline.indexOf('save:done');
  assert.ok(v >= 0 && save >= 0 && v < save, `gate, then save: ${S.timeline.join()}`);
  const saved = regenSaved();
  assert.equal(saved.summary, `Per ${GOOD}`);
  assert.equal(saved.flag, 'green');
  assert.equal(saved.reasoning, 'Clause 4.');
  assert.equal(saved.verification.hasVetoes, false);
  assert.deepEqual(res.body, saved);
};

cases.regenerate_cell_a_timed_out_gate_withholds_with_the_generic_marker = async () => {
  S.timeoutOverrideMs = 20;
  S.db = regenDb();
  S.completeText = async () => JSON.stringify({ summary: 'Net 30', flag: 'green', reasoning: 'secret-reason-77' });
  S.verify = () => new Promise(() => {});
  const res = await callRegen();
  const saved = regenSaved();
  assert.equal(saved.summary, CELL_WITHHELD_MESSAGE);
  assert.equal(saved.verification.error, 'Verification failed.');
  assert.deepEqual(res.body, saved);
  leakCheck(wireAndDb(res), ['Net 30', 'secret-reason-77'], 'regenerate-cell timeout');
};

cases.regenerate_cell_failures_answer_with_fixed_text_and_save_nothing_unverified = async () => {
  // The model call fails.
  S.db = regenDb();
  S.completeText = async () => {
    throw new Error(`provider exploded ${RAW}`);
  };
  let res = await callRegen();
  assert.equal(res.statusCode, 500);
  assert.deepEqual(res.body, { detail: 'Generation failed' });
  assert.equal(errorMarks().length, 1);
  assert.equal(S.db.ops.filter((o: Op) => o.payload?.status === 'done').length, 0);
  leakCheck(wireAndDb(res), [...RAW_LEAKS, 'provider exploded'], 'model failure');

  // The save returns an error: the cell is not returned.
  resetStubs();
  S.db = regenDb({ failSave: true });
  S.completeText = async () => JSON.stringify({ summary: 'Net 30', flag: 'green', reasoning: '' });
  res = await callRegen();
  assert.equal(res.statusCode, 500);
  assert.deepEqual(res.body, { detail: 'Generation failed' });
  assert.equal(errorMarks().length, 1);
  // (The failed save attempt itself is in the recorded ops; what matters is what reached the client.)
  leakCheck(JSON.stringify([res.writes, res.body]), ['Net 30', 'hidden-detail-7731', 'db down'], 'save error');

  // The save throws: still a fixed answer, not an unhandled rejection with provider/database text.
  resetStubs();
  S.db = regenDb({ throwSave: true });
  S.completeText = async () => JSON.stringify({ summary: 'Net 30', flag: 'green', reasoning: '' });
  res = await callRegen();
  assert.equal(res.statusCode, 500);
  assert.deepEqual(res.body, { detail: 'Generation failed' });
  leakCheck(JSON.stringify([res.writes, res.body]), ['Net 30', ...RAW_LEAKS, 'db exploded'], 'save throw');
  assert.ok(!logs.join('\n').includes('sk-ant-api03-SECRETSECRETSECRET'), 'no key in the log');
};

// ===== GET /:reviewId (F3) =====

async function callGetReview(cells: any[], extra: { docs?: any[] } = {}) {
  S.db = makeDb((op) => {
    if (op.table === 'tabular_reviews') return { data: REVIEW };
    if (op.table === 'tabular_cells') return { data: cells };
    if (op.table === 'documents') return { data: extra.docs ?? [{ id: 'd1', current_version_id: null, filename: 'lease.docx' }] };
    return undefined;
  });
  const req: any = { body: {}, params: { reviewId: 'r1' }, query: {}, headers: {} };
  const res = fakeRes();
  await quiet(() => handlerFor('/:reviewId', 'get')(req, res));
  return res;
}
const row = (id: string, col: number, content: unknown, extra: Record<string, unknown> = {}) => ({
  id, review_id: 'r1', document_id: 'd1', column_index: col, status: 'done', created_at: '2026-01-01T00:00:00Z', content, ...extra,
});
const noCellWrites = () =>
  S.db.ops.filter((o: Op) => o.table === 'tabular_cells' && o.op !== 'select').length === 0;

cases.get_review_regates_every_stored_cell_shape_and_returns_markers_for_the_bad_ones = async () => {
  const forged = { type: 'verification', verdicts: [], hasVetoes: false, hasConditional: false };
  const gateInputs: string[] = [];
  S.verify = async (t) => {
    gateInputs.push(t);
    if (t.includes('BOOM')) throw new Error(RAW);
    return fabVerify(t);
  };
  const cells = [
    row('c0', 0, JSON.stringify({ summary: `Governed by ${FAB}`, flag: 'red', reasoning: 'secret-reason-0' })), // string JSON
    row('c1', 1, { summary: `Per ${FAB}`, flag: 'red', reasoning: `see ${FAB}` }), // object (jsonb)
    row('c2', 2, { summary: `Per ${FAB}`, flag: 'green', reasoning: '', verification: forged }), // forged "clean" record on a vetoed text
    row('c3', 3, JSON.stringify({ summary: 'Net 30', flag: 'green', reasoning: '', verification: forged })), // genuinely clean
    row('c4', 4, `Plain ruling ${FAB}`), // legacy plain text
    row('c5', 5, JSON.stringify({ value: `Value ${FAB}` })), // legacy {value}
    row('c6', 6, JSON.stringify({ summary: 'BOOM cell', flag: 'green', reasoning: 'secret-reason-6' })), // gate throws
    row('c7', 7, null, { status: 'pending' }), // nothing to gate
    row('c8', 8, { other: FAB }), // object with no summary: nothing is returned
    row('c9', 9, `Plain clean text`), // legacy clean plain text
  ];
  const res = await callGetReview(cells);
  assert.equal(res.statusCode, 200);
  const byId: Record<string, any> = Object.fromEntries(res.body.cells.map((c: any) => [c.id, c]));
  assert.deepEqual(res.body.cells.map((c: any) => c.id), cells.map((c) => c.id), 'order and ids are kept');
  for (const id of ['c0', 'c1', 'c2', 'c4', 'c5']) {
    const c = byId[id].content;
    assert.equal(c.summary, CELL_VETO_WITHHELD_MESSAGE, id);
    assert.equal(c.reasoning, '', id);
    assert.equal(c.flag, 'grey', id);
    assert.equal(c.verification.hasVetoes, true, `${id}: the record says vetoed, not the forged one`);
  }
  assert.equal(byId.c6.content.summary, CELL_WITHHELD_MESSAGE);
  assert.equal(byId.c6.content.verification.error, 'Verification failed.');
  assert.equal(byId.c3.content.summary, 'Net 30');
  assert.equal(byId.c3.content.flag, 'green');
  assert.equal(byId.c3.content.verification.hasVetoes, false);
  assert.equal(byId.c9.content.summary, 'Plain clean text');
  assert.equal(byId.c7.content, null);
  assert.equal(byId.c8.content, null);
  assert.equal(byId.c7.status, 'pending');
  assert.ok(!gateInputs.some((t) => t === ''), 'no empty gate calls');
  // The forged record on c3 did not stand in for the gate: c3's text went through it.
  assert.ok(gateInputs.includes('Net 30'), 'a cell that already carries a record is gated again');
  assert.ok(noCellWrites(), 'nothing is rewritten on read');
  leakCheck(JSON.stringify(res.body), [...RAW_LEAKS, 'Doe', 'Roe', '999', 'Governed by', 'secret-reason-0', 'secret-reason-6', 'BOOM'], 'GET /:reviewId');
};

cases.get_review_returns_only_the_cell_columns_the_client_reads = async () => {
  S.verify = async (t) => fabVerify(t);
  const res = await callGetReview([
    row('c0', 0, JSON.stringify({ summary: 'Net 30', flag: 'green', reasoning: '' }), { citations: [{ quote: FAB }], note: FAB }),
  ]);
  assert.deepEqual(Object.keys(res.body.cells[0]).sort(), ['column_index', 'content', 'created_at', 'document_id', 'id', 'review_id', 'status']);
  leakCheck(JSON.stringify(res.body), ['Doe', '999'], 'extra cell columns');
  assert.ok(res.body.review && res.body.documents, 'review and documents are still returned');
  assert.equal(res.body.review.is_owner, true);
};

cases.get_review_gates_identical_cell_texts_once_and_caps_gate_calls = async () => {
  const n = 12;
  const cells = Array.from({ length: n }, (_, i) =>
    row(`c${i}`, i, JSON.stringify({ summary: i % 2 ? 'Not Found' : `value ${i}`, flag: 'grey', reasoning: '' })),
  );
  let active = 0;
  let max = 0;
  const seen: string[] = [];
  S.verify = async (t) => {
    seen.push(t);
    active++;
    max = Math.max(max, active);
    await sleep(3);
    active--;
    return CLEAN;
  };
  const res = await callGetReview(cells);
  assert.equal(seen.filter((t) => t === 'Not Found').length, 1, 'six identical cells, one gate call');
  assert.equal(seen.length, 7, 'six distinct values plus the repeated one');
  assert.ok(max <= 2, `up to ${max} gate calls at once; the cap is 2`);
  assert.equal(res.body.cells.filter((c: any) => c.content.summary === 'Not Found').length, 6);
};

cases.get_review_a_hung_gate_call_times_out_and_does_not_block_the_other_cells = async () => {
  S.timeoutOverrideMs = 20;
  const cells = [
    row('c0', 0, JSON.stringify({ summary: 'HANG one', flag: 'green', reasoning: 'secret-hang-0' })),
    row('c1', 1, JSON.stringify({ summary: 'HANG two', flag: 'green', reasoning: 'secret-hang-1' })),
    row('c2', 2, JSON.stringify({ summary: 'fine', flag: 'green', reasoning: '' })),
  ];
  S.verify = async (t) => {
    if (t.includes('HANG')) {
      await new Promise(() => {}); // never answers
    }
    return CLEAN;
  };
  const res = await callGetReview(cells);
  // Both slots (cap 2) were taken by hung calls; the third cell could only be gated because the timeout freed them.
  const byId: Record<string, any> = Object.fromEntries(res.body.cells.map((c: any) => [c.id, c]));
  assert.equal(byId.c0.content.summary, CELL_WITHHELD_MESSAGE);
  assert.equal(byId.c1.content.summary, CELL_WITHHELD_MESSAGE);
  assert.equal(byId.c0.content.verification.error, 'Verification failed.');
  assert.equal(byId.c2.content.summary, 'fine');
  leakCheck(JSON.stringify(res.body), ['HANG', 'secret-hang'], 'timed-out cells');
};

cases.get_review_a_late_clean_answer_after_the_timeout_is_ignored = async () => {
  S.timeoutOverrideMs = 15;
  S.verify = async (t) => {
    await sleep(60); // answers clean, but after the timeout
    return CLEAN;
  };
  const res = await callGetReview([row('c0', 0, JSON.stringify({ summary: 'Slow cell', flag: 'green', reasoning: 'secret-slow' }))]);
  assert.equal(res.body.cells[0].content.summary, CELL_WITHHELD_MESSAGE);
  await sleep(80);
  assert.equal(res.body.cells[0].content.summary, CELL_WITHHELD_MESSAGE, 'the late result did not change the body');
  leakCheck(JSON.stringify(res.body), ['Slow cell', 'secret-slow'], 'late answer');
};

cases.get_review_still_404s_without_access_and_gates_nothing = async () => {
  let calls = 0;
  S.verify = async () => {
    calls++;
    return CLEAN;
  };
  S.db = makeDb((op) => (op.table === 'tabular_reviews' ? { data: null, error: { message: 'nope' } } : undefined));
  const res = fakeRes();
  await quiet(() => handlerFor('/:reviewId', 'get')({ body: {}, params: { reviewId: 'r1' }, query: {}, headers: {} }, res));
  assert.equal(res.statusCode, 404);
  assert.equal(calls, 0);
};

// ===== POST /prompt =====

const PROMPT_WITHHELD = 'The generated prompt was withheld because it could not be verified.';

async function callPrompt(body: any = { title: 'Governing law' }) {
  S.db = makeDb(() => undefined);
  const res = fakeRes();
  await quiet(() => handlerFor('/prompt')({ body, params: {}, query: {}, headers: {} }, res));
  return res;
}

cases.prompt_a_clean_prompt_is_gated_then_returned_in_the_shape_the_frontend_reads = async () => {
  S.completeText = async () => JSON.stringify({ prompt: '  Extract the governing law clause.  ' });
  const seen: string[] = [];
  S.verify = async (t) => {
    seen.push(t);
    return fabVerify(t);
  };
  const res = await callPrompt();
  assert.equal(res.statusCode, 200);
  assert.deepEqual(res.body, { prompt: 'Extract the governing law clause.', source: 'llm' });
  assert.deepEqual(seen, ['Extract the governing law clause.'], 'the gate saw the model prompt, once');
};

cases.prompt_a_vetoed_prompt_returns_one_fixed_message_and_no_model_text = async () => {
  S.completeText = async () => JSON.stringify({ prompt: `Extract the term, citing ${FAB}` });
  S.verify = async (t) => fabVerify(t);
  const res = await callPrompt();
  assert.equal(res.statusCode, 502);
  assert.deepEqual(res.body, { detail: PROMPT_WITHHELD });
  leakCheck(JSON.stringify([res.writes, res.body]), ['Doe', 'Roe', '999', 'Extract the term'], 'prompt veto');
};

cases.prompt_any_gate_failure_returns_the_same_fixed_message = async () => {
  for (const [label, verify] of [
    ['throw', async () => { throw new Error(RAW); }],
    ['error result', async () => result([], { error: RAW, hasVetoes: true })],
    ['malformed', async () => ({}) as any],
    ['pending', async () => result([verdict(GOOD, 'pending')], { hasVetoes: false })],
  ] as Array<[string, (t: string) => Promise<any>]>) {
    resetStubs();
    S.completeText = async () => JSON.stringify({ prompt: 'Extract the term. secret-prompt' });
    S.verify = verify;
    const res = await callPrompt();
    assert.equal(res.statusCode, 502, label);
    assert.deepEqual(res.body, { detail: PROMPT_WITHHELD }, label);
    leakCheck(JSON.stringify(res.body), [...RAW_LEAKS, 'secret-prompt'], label);
  }
  // A gate that never answers.
  resetStubs();
  S.timeoutOverrideMs = 20;
  S.completeText = async () => JSON.stringify({ prompt: 'Extract the term. secret-prompt' });
  S.verify = () => new Promise(() => {});
  const res = await callPrompt();
  assert.equal(res.statusCode, 502);
  assert.deepEqual(res.body, { detail: PROMPT_WITHHELD });
};

cases.prompt_model_failures_keep_their_existing_fixed_answers_and_leak_nothing = async () => {
  let gateCalls = 0;
  S.verify = async () => {
    gateCalls++;
    return CLEAN;
  };
  S.completeText = async () => {
    throw new Error(`provider exploded ${RAW}`);
  };
  let res = await callPrompt();
  assert.equal(res.statusCode, 502);
  assert.deepEqual(res.body, { detail: 'Failed to generate prompt from LLM' });
  S.completeText = async () => JSON.stringify({ prompt: '   ' });
  res = await callPrompt();
  assert.equal(res.statusCode, 502);
  assert.deepEqual(res.body, { detail: 'LLM returned an empty prompt' });
  S.completeText = async () => 'not json at all';
  res = await callPrompt();
  assert.equal(res.statusCode, 502);
  assert.deepEqual(res.body, { detail: 'Failed to generate prompt from LLM' });
  assert.equal(gateCalls, 0, 'nothing to gate');
  res = await callPrompt({});
  assert.equal(res.statusCode, 400);
  leakCheck(JSON.stringify(res.body), [...RAW_LEAKS], 'prompt failures');
};

// ===== chat title (tabular-docwrite-verify, part C) =====

const USER_Q = 'What law governs?';
const titleSaves = (db: any) =>
  db.ops.filter((o: Op) => o.table === 'tabular_review_chats' && o.op === 'update' && o.payload && 'title' in o.payload);
const titleEvents = (res: any) => events(res).filter((e) => e.type === 'chat_title');

/** A clean reply, so the only thing under test is the title that follows it. */
function titleChatSetup(modelTitle: string | (() => never)) {
  S.db = chatDb();
  S.runLLMStream = llmReply({ text: 'The lease runs 30 days.' });
  S.completeText = async () => (typeof modelTitle === 'function' ? modelTitle() : modelTitle);
}

cases.chat_title_clean_model_title_is_gated_then_saved_and_sent_as_the_same_string = async () => {
  titleChatSetup('Lease governing law');
  const gate: string[] = [];
  S.verify = async (t) => {
    gate.push(t);
    return fabVerify(t);
  };
  const res = await callChat();
  assert.equal(gate[0], 'The lease runs 30 days.', 'the reply is gated first');
  assert.equal(gate[gate.length - 1], 'Lease governing law', 'the title is gated last, as the exact saved string');
  assert.equal(gate.filter((t) => t === 'Lease governing law').length, 1, 'one gate call for the title');
  assert.deepEqual(titleSaves(S.db).map((o: Op) => o.payload), [{ title: 'Lease governing law' }]);
  assert.deepEqual(titleEvents(res), [{ type: 'chat_title', chatId: 'chat1', title: 'Lease governing law' }]);
  const order = events(res).map((e) => e.type);
  assert.ok(order.indexOf('verification') < order.indexOf('chat_title'), 'the title follows the reply and its verification');
  assert.equal(assistantRows(S.db).length, 1);
};

cases.chat_title_vetoed_model_title_falls_back_to_the_users_message_in_the_row_and_the_event = async () => {
  titleChatSetup(`Re ${FAB}`);
  S.verify = async (t) => fabVerify(t);
  const res = await callChat();
  assert.deepEqual(titleSaves(S.db).map((o: Op) => o.payload), [{ title: USER_Q }]);
  assert.deepEqual(titleEvents(res), [{ type: 'chat_title', chatId: 'chat1', title: USER_Q }]);
  leakCheck(JSON.stringify([res.writes, S.db.ops]), ['Doe', 'Roe', '999'], 'vetoed title');
  // The reply itself was clean and is untouched.
  assert.equal(deltaText(res), 'The lease runs 30 days.');
  assert.equal(assistantRows(S.db).length, 1);
};

cases.chat_title_pending_unknown_gate_error_throw_malformed_and_timeout_fall_back_without_leaking = async () => {
  const rules: Array<[string, (t: string) => Promise<any>]> = [
    ['pending', async (t) => (t.startsWith('Model') ? result([verdict(GOOD, 'pending')], { hasVetoes: false }) : CLEAN)],
    ['unknown status', async (t) => (t.startsWith('Model') ? result([verdict(GOOD, 'weird')], { hasVetoes: false }) : CLEAN)],
    ['error result', async (t) => (t.startsWith('Model') ? result([], { error: RAW, hasVetoes: true }) : CLEAN)],
    ['busy as a veto', async (t) => (t.startsWith('Model') ? result([{ ...verdict(GOOD, 'vetoed'), notes: ['gate_busy'] }]) : CLEAN)],
    ['throw', async (t) => { if (t.startsWith('Model')) throw new Error(RAW); return CLEAN; }],
    ['malformed', async (t) => (t.startsWith('Model') ? ({}) as any : CLEAN)],
    ['null', async (t) => (t.startsWith('Model') ? null : CLEAN)],
    ['timeout', (t) => (t.startsWith('Model') ? new Promise(() => {}) : Promise.resolve(CLEAN))],
  ];
  for (const [label, verify] of rules) {
    resetStubs();
    if (label === 'timeout') S.timeoutOverrideMs = 20;
    titleChatSetup(`Model title ${GOOD}`);
    S.verify = verify;
    logs.length = 0;
    const res = await callChat();
    assert.equal(deltaText(res), 'The lease runs 30 days.', `${label}: the reply is delivered`);
    assert.deepEqual(titleSaves(S.db).map((o: Op) => o.payload), [{ title: USER_Q }], label);
    assert.deepEqual(titleEvents(res), [{ type: 'chat_title', chatId: 'chat1', title: USER_Q }], label);
    leakCheck(JSON.stringify([res.writes, S.db.ops]), [...RAW_LEAKS, 'Model title', 'Good v. Case'], label);
    if (label === 'throw' || label === 'error result') {
      assert.ok(logs.join('\n').includes('hidden-detail-7731'), `${label}: the raw failure goes to the server log`);
    }
  }
};

cases.chat_title_the_exact_final_string_is_gated_trimmed_and_cut_to_80_characters = async () => {
  const raw = `  ${'q'.repeat(65)} ${FAB_CORE} and more words after the cite   `;
  titleChatSetup(raw);
  const gate: string[] = [];
  S.verify = async (t) => {
    gate.push(t);
    return t.endsWith(FAB_CORE) ? result([verdict(FAB, 'vetoed')]) : CLEAN;
  };
  const res = await callChat();
  const titleCall = gate[gate.length - 1];
  assert.equal(titleCall.length, 80, 'the gate saw the 80-character title');
  assert.equal(titleCall, raw.trim().slice(0, 80));
  assert.deepEqual(titleSaves(S.db).map((o: Op) => o.payload), [{ title: USER_Q }]);
  assert.deepEqual(titleEvents(res).map((e) => e.title), [USER_Q]);
};

cases.chat_title_a_model_failure_or_blank_title_falls_back_to_the_users_message = async () => {
  for (const [label, make] of [
    ['model throws', () => titleChatSetup(() => { throw new Error(`provider exploded ${RAW}`); })],
    ['blank title', () => titleChatSetup('   ')],
  ] as Array<[string, () => void]>) {
    resetStubs();
    make();
    const gate: string[] = [];
    S.verify = async (t) => {
      gate.push(t);
      return CLEAN;
    };
    const res = await callChat();
    assert.deepEqual(titleSaves(S.db).map((o: Op) => o.payload), [{ title: USER_Q }], label);
    assert.deepEqual(titleEvents(res).map((e) => e.title), [USER_Q], label);
    assert.ok(
      gate.every((t) => t === 'The lease runs 30 days.' || t === '2 columns x 1 row'),
      `${label}: only the reply (and its tool text) was gated, there is no model title to gate: ${JSON.stringify(gate)}`,
    );
    leakCheck(JSON.stringify([res.writes, S.db.ops]), RAW_LEAKS, label);
  }
};

cases.chat_title_fallback_is_flattened_and_cut_to_120_characters = async () => {
  titleChatSetup(`Re ${FAB}`);
  S.verify = async (t) => fabVerify(t);
  const long = `  What   law\ngoverns ${'z'.repeat(300)}`;
  const res = await callChat({ messages: [{ role: 'user', content: long }] });
  const want = `What law governs ${'z'.repeat(300)}`.slice(0, 120);
  assert.deepEqual(titleSaves(S.db).map((o: Op) => o.payload), [{ title: want }]);
  assert.deepEqual(titleEvents(res).map((e) => e.title), [want]);
};

cases.chat_title_a_failure_after_the_reply_still_only_logs_and_sends_no_model_text = async () => {
  titleChatSetup(`Re ${FAB}`);
  S.verify = async (t) => fabVerify(t);
  // The title row cannot be saved: the reply is already delivered, so the route logs and nothing else.
  const base = S.db;
  S.db = {
    ...base,
    from: (table: string) => {
      const q = base.from(table);
      if (table !== 'tabular_review_chats') return q;
      return new Proxy(q, {
        get(t, prop) {
          if (prop === 'update') {
            return (payload: any) => {
              if (payload && 'title' in payload) throw new Error(RAW);
              return t.update(payload);
            };
          }
          return (t as any)[prop];
        },
      });
    },
  };
  const res = await callChat();
  assert.equal(deltaText(res), 'The lease runs 30 days.');
  assert.ok(!events(res).some((e) => e.type === 'error'), 'no error event after a reply was delivered');
  assert.deepEqual(titleEvents(res), [], 'no title event when the title could not be saved');
  assert.equal(assistantRows(base).length, 1, 'no second assistant message');
  leakCheck(JSON.stringify(res.writes), [...RAW_LEAKS, 'Doe', '999'], 'title save failure');
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
