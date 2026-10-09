// Cases for Gate 1 over model-written chat titles (tabular-docwrite-verify, part C):
//   gateTitleText / userTitleFallback in hallucination_guard.ts, and
//   POST /chat/:chatId/generate-title in routes/chat.ts (the REAL router and handler).
// (The tabular chat title is covered in tabular_route_cases.ts, which already loads the real tabular router.)
//
// Run by test_title_gate.py once under backend's tsx. Real: chat.ts, its handler (after requireAuth), all of
// hallucination_guard.ts, safeError.ts. Stubbed: req / res, Supabase (recording fake), the model call, settings,
// auth, access, chatTools, and the Gate 1 verifier. No Supabase, CourtListener, LLM, Python gate or network.
// Prints {caseName: null | "failure text"}.

import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import path from 'node:path';
import {
  TITLE_FALLBACK_MAX_CHARS,
  TITLE_GATE_CONCURRENCY,
  TITLE_GATE_TIMEOUT_MS,
  createLimiter,
  gateTitleText,
  userTitleFallback,
  type SseVerificationResult,
} from '../../backend/src/middleware/hallucination_guard';

// ---------- helpers ----------

const silent = () => {};
/** Limiter timers that keep the process alive (the real ones are unref'd, so a hung case would end the run early). */
const refTimers = {
  setTimeout: (fn: () => void, ms: number) => setTimeout(fn, ms),
  clearTimeout: (h: unknown) => clearTimeout(h as ReturnType<typeof setTimeout>),
};
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

const FAB = 'Doe v. Roe, 999 So. 3d 999 (Fla. 2015)';
const FAB_CORE = '999 So. 3d 999';
const GOOD = 'Good v. Case, 1 So. 3d 2 (Fla. 2010)';
const RAW = 'SQLITE_CANTOPEN: unable to open /Users/x/kingsfield_florida.db; CourtListener 503 hidden-detail-7731';
const RAW_LEAKS = ['SQLITE', 'CANTOPEN', 'kingsfield_florida', 'hidden-detail-7731', '/Users/x'];

/** Vetoes any text with the fabricated cite, verifies the good one. */
function fabVerify(text: string): SseVerificationResult {
  const vs: any[] = [];
  if (text.includes(FAB_CORE)) vs.push(verdict(FAB, 'vetoed'));
  if (text.includes('1 So. 3d 2')) vs.push(verdict(GOOD, 'verified'));
  return result(vs);
}

function leakCheck(blob: string, needles: string[], label: string) {
  for (const n of needles) assert.ok(!blob.includes(n), `${label}: "${n}" reached the client or a saved row`);
}

/** Stub verifier recording every call. */
function recorder(rule: (text: string) => any) {
  const calls: string[] = [];
  const verify = async (text: string) => {
    calls.push(text);
    const r = rule(text);
    if (r instanceof Error) throw r;
    return r;
  };
  return { verify, calls };
}

// ---------- the real chat router, with its dependencies stubbed ----------

const ROOT = process.cwd();
const nodeRequire = createRequire(path.join(ROOT, 'backend', 'package.json'));
const CHAT = path.join(ROOT, 'backend', 'src', 'routes', 'chat.ts');
const GUARD_PATH = path.join(ROOT, 'backend', 'src', 'middleware', 'hallucination_guard.ts');

const S: {
  db: any;
  verify: (text: string) => Promise<SseVerificationResult>;
  completeText: (p: any) => Promise<string>;
  completeParams: any[];
  /** When set, the route's title gate runs on a limiter with this timeout (the real one is 75 s). */
  timeoutMs: number | null;
} = {} as any;

function resetStubs() {
  S.db = undefined;
  S.verify = async () => CLEAN;
  S.completeText = async () => 'Lease Termination Rights';
  S.completeParams = [];
  S.timeoutMs = null;
}
resetStubs();

const requireAuthStub = function requireAuth(_req: any, _res: any, next: any) {
  next();
};

const realGuard = nodeRequire(GUARD_PATH);
const STUBS: Record<string, any> = {
  '../middleware/auth': { requireAuth: requireAuthStub },
  '../lib/supabase': { createServerSupabase: () => S.db },
  '../lib/chatTools': {
    buildDocContext: async () => ({}),
    buildMessages: () => [],
    enrichWithPriorEvents: () => [],
    buildWorkflowStore: async () => new Map(),
    isAbortError: () => false,
    runLLMStream: async () => {
      throw new Error('runLLMStream is not used by generate-title');
    },
  },
  '../lib/llm': {
    completeText: (p: any) => {
      S.completeParams.push(p);
      return S.completeText(p);
    },
  },
  '../lib/userSettings': {
    getUserModelSettings: async () => ({ title_model: 'stub-model', api_keys: { claude: 'k' } }),
  },
  '../lib/access': { checkProjectAccess: async () => ({ ok: false }) },
  // The real guard, with only the Gate 1 verifier replaced (the route calls verifyDraftForSse itself) and,
  // when a case asks, the title gate's limiter shortened (the real limit is far too long to wait for here).
  '../middleware/hallucination_guard': {
    ...realGuard,
    verifyDraftForSse: (text: string, _opts: unknown) => S.verify(text),
    gateTitleText: (title: unknown, fallback: string, opts: any) =>
      realGuard.gateTitleText(
        title,
        fallback,
        S.timeoutMs === null ? opts : { ...opts, limiter: realGuard.createLimiter(1, { timeoutMs: S.timeoutMs, timers: refTimers }) },
      ),
  },
};

const ModuleCtor: any = nodeRequire('module');
const origLoad = ModuleCtor._load;
ModuleCtor._load = function (request: string, parent: any, ...rest: unknown[]) {
  if (parent && parent.filename === CHAT && Object.prototype.hasOwnProperty.call(STUBS, request)) return STUBS[request];
  return origLoad.call(this, request, parent, ...rest);
};
const chat = nodeRequire(CHAT);
ModuleCtor._load = origLoad;

function titleHandler() {
  const layer = chat.chatRouter.stack.find(
    (l: any) => l.route && l.route.path === '/:chatId/generate-title' && l.route.methods && l.route.methods.post,
  );
  assert.ok(layer, 'chatRouter has no POST /:chatId/generate-title');
  const stack = layer.route.stack;
  assert.equal(stack[0].handle, requireAuthStub, 'requireAuth is not the first layer');
  return stack[stack.length - 1].handle as (req: any, res: any) => Promise<void>;
}

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
  const r: any = { statusCode: 200, body: undefined, locals: { userId: 'u1', userEmail: 'u@x.test' } };
  r.status = (c: number) => {
    r.statusCode = c;
    return r;
  };
  r.json = (b: unknown) => {
    r.body = clone(b);
    return r;
  };
  return r;
}

type Op = { table: string; op: 'select' | 'update'; payload?: any; filters: any[][] };

/** Recording Supabase fake: the chat row is owned by u1; `titleSaveError` makes the title update fail. */
function makeDb(opts: { noChat?: boolean; titleSaveThrows?: boolean } = {}) {
  const ops: Op[] = [];
  const chain = (state: Op): any =>
    new Proxy(function () {}, {
      get(_t, prop) {
        if (prop === 'then') {
          return (res: any, rej: any) => {
            ops.push(state);
            if (state.table === 'chats' && state.op === 'select') {
              return Promise.resolve({
                data: opts.noChat ? null : { id: 'c1', user_id: 'u1', project_id: null, title: null },
                error: null,
              }).then(res, rej);
            }
            if (state.op === 'update' && opts.titleSaveThrows) return Promise.reject(new Error(RAW)).then(res, rej);
            return Promise.resolve({ data: null, error: null }).then(res, rej);
          };
        }
        if (prop === 'update') {
          return (payload?: unknown) => {
            state.op = 'update';
            state.payload = clone(payload);
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

const titleUpdates = (db: any) => db.ops.filter((o: Op) => o.table === 'chats' && o.op === 'update');

async function callTitle(message: unknown = 'What are my termination rights under the lease?') {
  const req: any = { body: { message }, params: { chatId: 'c1' }, query: {}, headers: {} };
  const res = fakeRes();
  await quiet(() => titleHandler()(req, res));
  return res;
}

// ---------- cases ----------

const cases: Record<string, () => Promise<void>> = {};

// ===== userTitleFallback =====

cases.fallback_is_the_start_of_the_users_text_flattened_and_cut = async () => {
  assert.equal(TITLE_FALLBACK_MAX_CHARS, 120);
  assert.equal(userTitleFallback('  What  are\n my\trights?  '), 'What are my rights?');
  assert.equal(userTitleFallback('a'.repeat(300)), 'a'.repeat(120));
  assert.equal(userTitleFallback('x\u0000y\u0007z'), 'x y z', 'control characters are removed');
  // Cut on characters, not UTF-16 halves.
  const emoji = '\u{1F600}'.repeat(200);
  assert.equal(Array.from(userTitleFallback(emoji)).length, 120);
  assert.ok(!/[\ud800-\udbff](?![\udc00-\udfff])/.test(userTitleFallback(emoji)), 'no lone surrogate');
  for (const bad of [undefined, null, 5, {}, [], '', '   \n\t ']) assert.equal(userTitleFallback(bad), '', String(bad));
  assert.equal(userTitleFallback('abcdef', 3), 'abc');
};

// ===== gateTitleText =====

cases.gate_clean_title_is_returned_unchanged_after_one_gate_call = async () => {
  const { verify, calls } = recorder(fabVerify);
  const out = await gateTitleText('Lease Termination Rights', 'fallback', { verify, logError: silent });
  assert.deepEqual(out, { title: 'Lease Termination Rights', usedFallback: false, reason: null });
  assert.deepEqual(calls, ['Lease Termination Rights'], 'the gate saw exactly the title');
  // A verified and a conditional cite pass, as in chat.
  for (const status of ['verified', 'conditional']) {
    const o = await gateTitleText(`Per ${GOOD}`, 'fallback', { verify: async () => result([verdict(GOOD, status)]), logError: silent });
    assert.equal(o.usedFallback, false, status);
    assert.equal(o.title, `Per ${GOOD}`, status);
  }
};

cases.gate_veto_uses_the_fallback_and_never_the_model_text = async () => {
  const logged: string[] = [];
  const { verify, calls } = recorder(fabVerify);
  const out = await gateTitleText(`Re ${FAB}`, 'My own words', { verify, logError: (c, e) => logged.push(`${c} ${JSON.stringify(e)}`) });
  assert.deepEqual(out, { title: 'My own words', usedFallback: true, reason: 'veto' });
  assert.equal(calls.length, 1);
  leakCheck(JSON.stringify(out), ['Doe', 'Roe', '999'], 'vetoed title');
  assert.deepEqual(logged, [], 'a plain veto logs nothing');
};

cases.gate_pending_unknown_status_and_whole_draft_placeholder_use_the_fallback = async () => {
  const rules: Array<[string, any]> = [
    ['pending', result([verdict(GOOD, 'pending')], { hasVetoes: false })],
    ['unknown status', result([verdict(GOOD, 'weird-status')], { hasVetoes: false })],
    ['no status', result([{ citation: GOOD, notes: [] }], { hasVetoes: false })],
    ['whole-draft placeholder', result([verdict('[draft]', 'vetoed')])],
    ['hasVetoes with no verdict', result([], { hasVetoes: true })],
    ['null verdict entry', { verdicts: [null], hasVetoes: false, hasConditional: false }],
  ];
  for (const [label, r] of rules) {
    const out = await gateTitleText(`Re ${GOOD}`, 'fallback', { verify: async () => r, logError: silent });
    assert.equal(out.usedFallback, true, label);
    assert.equal(out.title, 'fallback', label);
  }
};

cases.gate_error_throw_malformed_and_null_use_the_fallback_and_log_the_raw_error_only = async () => {
  const rules: Array<[string, (t: string) => Promise<any>]> = [
    ['error result', async () => result([], { error: RAW, hasVetoes: true })],
    ['error with no veto flag', async () => result([], { error: RAW })],
    ['throw', async () => { throw new Error(RAW); }],
    ['malformed', async () => ({ nope: true })],
    ['null', async () => null],
    ['string', async () => 'ok' as any],
  ];
  for (const [label, verify] of rules) {
    const logged: string[] = [];
    const out = await gateTitleText('Some Title', 'fallback', {
      verify,
      logError: (c, e) => logged.push(`${c} ${JSON.stringify(e)}`),
    });
    assert.deepEqual(out, { title: 'fallback', usedFallback: true, reason: out.reason }, label);
    assert.ok(out.reason, `${label}: a reason is given`);
    leakCheck(JSON.stringify(out), [...RAW_LEAKS, 'Some Title'], label);
    if (label === 'throw' || label === 'error result' || label === 'error with no veto flag') {
      assert.ok(logged.join('\n').includes('hidden-detail-7731'), `${label}: the raw failure goes to the server log`);
    }
  }
};

cases.gate_busy_answer_from_the_real_gate_uses_the_fallback = async () => {
  // The local gate answers gate_busy as a veto note; the helper must treat it like any veto.
  const busy = result([{ ...verdict('1 So. 3d 2', 'vetoed'), notes: ['CITATION VETOED by the local Florida index (gate_busy).'] }]);
  const out = await gateTitleText('Re 1 So. 3d 2', 'fallback', { verify: async () => busy, logError: silent });
  assert.deepEqual(out, { title: 'fallback', usedFallback: true, reason: 'veto' });
};

cases.gate_timeout_uses_the_fallback_frees_the_slot_and_ignores_the_late_answer = async () => {
  const limiter = createLimiter(1, { timeoutMs: 20, timers: refTimers });
  let release: (r: SseVerificationResult) => void = () => {};
  const hung = new Promise<SseVerificationResult>((resolve) => (release = resolve));
  const logged: string[] = [];
  const out = await gateTitleText('Slow Title', 'fallback', {
    verify: () => hung,
    logError: (c, e) => logged.push(`${c} ${JSON.stringify(e)}`),
    limiter,
  });
  assert.deepEqual(out, { title: 'fallback', usedFallback: true, reason: 'gate_timeout' });
  release(CLEAN); // a late clean answer changes nothing
  await new Promise((r) => setTimeout(r, 10));
  assert.equal(out.title, 'fallback');
  // The slot is free: the next title through the same limiter is gated normally.
  const next = await gateTitleText('Quick Title', 'fallback', { verify: async () => CLEAN, logError: silent, limiter });
  assert.equal(next.title, 'Quick Title');
  assert.ok(logged.length >= 1, 'the timeout is logged server-side');
};

cases.gate_blank_or_non_string_titles_use_the_fallback_without_calling_the_gate = async () => {
  const { verify, calls } = recorder(() => CLEAN);
  for (const bad of ['', '   ', '\n', null, undefined, 5, {}, ['x']]) {
    const out = await gateTitleText(bad, 'fallback', { verify, logError: silent });
    assert.deepEqual(out, { title: 'fallback', usedFallback: true, reason: 'empty_title' }, String(bad));
  }
  assert.deepEqual(calls, []);
};

cases.gate_a_non_string_fallback_becomes_an_empty_string_not_model_text = async () => {
  const out = await gateTitleText(`Re ${FAB}`, undefined as any, { verify: async (t) => fabVerify(t), logError: silent });
  assert.equal(out.title, '');
  assert.equal(out.usedFallback, true);
};

cases.gate_module_limiter_has_a_cap_and_the_75s_limit = async () => {
  assert.equal(TITLE_GATE_CONCURRENCY, 2);
  assert.equal(TITLE_GATE_TIMEOUT_MS, 75_000);
};

// ===== POST /chat/:chatId/generate-title =====

cases.route_clean_title_is_gated_then_saved_and_returned_as_the_same_string = async () => {
  const gate = recorder(fabVerify);
  S.verify = gate.verify;
  S.db = makeDb();
  S.completeText = async () => 'Lease Termination Rights';
  const res = await callTitle();
  assert.equal(res.statusCode, 200);
  assert.deepEqual(res.body, { title: 'Lease Termination Rights' });
  assert.deepEqual(gate.calls, ['Lease Termination Rights']);
  const saves = titleUpdates(S.db);
  assert.equal(saves.length, 1);
  assert.deepEqual(saves[0].payload, { title: 'Lease Termination Rights' });
};

cases.route_vetoed_title_saves_and_returns_the_start_of_the_users_message = async () => {
  S.verify = async (t) => fabVerify(t);
  S.db = makeDb();
  S.completeText = async () => `Re ${FAB}`;
  const message = '  What are my termination rights\nunder the lease?  ';
  const res = await callTitle(message);
  assert.equal(res.statusCode, 200);
  assert.deepEqual(res.body, { title: 'What are my termination rights under the lease?' });
  assert.deepEqual(titleUpdates(S.db).map((o: Op) => o.payload), [{ title: 'What are my termination rights under the lease?' }]);
  leakCheck(JSON.stringify([res.body, S.db.ops]), ['Doe', 'Roe', '999'], 'vetoed title');
};

cases.route_fallback_is_cut_to_120_characters = async () => {
  S.verify = async (t) => fabVerify(t);
  S.db = makeDb();
  S.completeText = async () => `Re ${FAB}`;
  const res = await callTitle('b'.repeat(500));
  assert.equal(res.body.title, 'b'.repeat(120));
  assert.equal(titleUpdates(S.db)[0].payload.title, 'b'.repeat(120));
};

cases.route_pending_unknown_gate_error_throw_malformed_and_null_use_the_fallback = async () => {
  const rules: Array<[string, (t: string) => Promise<any>]> = [
    ['pending', async () => result([verdict(GOOD, 'pending')], { hasVetoes: false })],
    ['unknown status', async () => result([verdict(GOOD, 'weird-status')], { hasVetoes: false })],
    ['error result', async () => result([], { error: RAW, hasVetoes: true })],
    ['busy as a veto', async () => result([{ ...verdict(GOOD, 'vetoed'), notes: ['gate_busy'] }])],
    ['throw', async () => { throw new Error(RAW); }],
    ['malformed', async () => ({}) as any],
    ['null', async () => null],
  ];
  for (const [label, verify] of rules) {
    resetStubs();
    S.verify = verify;
    S.db = makeDb();
    S.completeText = async () => `Model Title ${GOOD}`;
    logs.length = 0;
    const res = await callTitle('my own question');
    assert.equal(res.statusCode, 200, label);
    assert.deepEqual(res.body, { title: 'my own question' }, label);
    assert.deepEqual(titleUpdates(S.db).map((o: Op) => o.payload), [{ title: 'my own question' }], label);
    leakCheck(JSON.stringify([res.body, S.db.ops]), [...RAW_LEAKS, 'Model Title', 'Good v. Case'], label);
    if (label === 'error result' || label === 'throw') {
      assert.ok(logs.join('\n').includes('hidden-detail-7731'), `${label}: the raw failure goes to the server log`);
    }
  }
};

cases.route_a_gate_that_never_answers_times_out_to_the_fallback = async () => {
  S.timeoutMs = 20;
  S.verify = () => new Promise(() => {});
  S.db = makeDb();
  S.completeText = async () => 'Model Title';
  const res = await callTitle('my own question');
  assert.equal(res.statusCode, 200);
  assert.deepEqual(res.body, { title: 'my own question' });
  assert.deepEqual(titleUpdates(S.db).map((o: Op) => o.payload), [{ title: 'my own question' }]);
};

cases.route_the_exact_normalized_string_is_what_the_gate_sees_and_what_is_saved = async () => {
  // Normalization strips the wrapping quotes and the closing period: the cite is a bare string only afterwards.
  const raw = `"${FAB}".`;
  const gate = recorder((t) => (t === FAB ? result([verdict(FAB, 'vetoed')]) : CLEAN));
  S.verify = gate.verify;
  S.db = makeDb();
  S.completeText = async () => raw;
  const res = await callTitle('my own question');
  assert.deepEqual(gate.calls, [FAB], 'the gate saw the normalized string, not the raw model output');
  assert.deepEqual(res.body, { title: 'my own question' });
  assert.deepEqual(titleUpdates(S.db).map((o: Op) => o.payload), [{ title: 'my own question' }]);
  leakCheck(JSON.stringify([res.body, S.db.ops]), ['Doe', '999'], 'normalized veto');
};

cases.route_a_cite_that_truncation_leaves_at_the_end_is_checked_as_cut = async () => {
  // 65 filler characters + " 999 So. 3d 999" = 80 characters, then more words. The title is cut to 80 before the gate.
  const raw = `${'q'.repeat(65)} ${FAB_CORE} and more words after the cite`;
  const gate = recorder((t) => (t.endsWith(FAB_CORE) ? result([verdict(FAB, 'vetoed')]) : CLEAN));
  S.verify = gate.verify;
  S.db = makeDb();
  S.completeText = async () => raw;
  const res = await callTitle('my own question');
  assert.equal(gate.calls.length, 1);
  assert.equal(gate.calls[0].length, 80, 'the gate saw the 80-character title');
  assert.equal(gate.calls[0], raw.slice(0, 80));
  assert.deepEqual(res.body, { title: 'my own question' });
};

cases.route_an_empty_model_title_becomes_the_fixed_misc_query_after_the_gate = async () => {
  const gate = recorder(() => CLEAN);
  S.verify = gate.verify;
  S.db = makeDb();
  S.completeText = async () => '  "." ';
  const res = await callTitle('my own question');
  assert.deepEqual(res.body, { title: 'Misc. Query' });
  assert.deepEqual(gate.calls, ['Misc. Query'], 'the final saved string is the one gated');
};

cases.route_the_users_own_cite_in_the_fallback_is_not_gated = async () => {
  // The fallback is the user's text. Only the model's title goes to the gate.
  const gate = recorder(fabVerify);
  S.verify = gate.verify;
  S.db = makeDb();
  S.completeText = async () => `Re ${FAB}`;
  const res = await callTitle(`Is ${FAB} still good law?`);
  assert.deepEqual(res.body, { title: `Is ${FAB} still good law?` });
  assert.deepEqual(gate.calls, [`Re ${FAB}`], 'one gate call, for the model title only');
};

cases.route_a_failed_title_save_still_returns_only_the_gated_title_and_leaks_nothing = async () => {
  S.verify = async (t) => fabVerify(t);
  S.db = makeDb({ titleSaveThrows: true });
  S.completeText = async () => `Re ${FAB}`;
  const res = await callTitle('my own question');
  assert.equal(res.statusCode, 500);
  assert.deepEqual(res.body, { detail: 'Failed to generate title' });
  leakCheck(JSON.stringify(res.body), [...RAW_LEAKS, 'Doe', '999'], 'save failure');
};

cases.route_model_failure_keeps_the_existing_fixed_500_and_saves_nothing = async () => {
  const gate = recorder(() => CLEAN);
  S.verify = gate.verify;
  S.db = makeDb();
  S.completeText = async () => {
    throw new Error(`provider exploded ${RAW}`);
  };
  const res = await callTitle('my own question');
  assert.equal(res.statusCode, 500);
  assert.deepEqual(res.body, { detail: 'Failed to generate title' });
  assert.deepEqual(titleUpdates(S.db), []);
  assert.deepEqual(gate.calls, []);
  leakCheck(JSON.stringify(res.body), RAW_LEAKS, 'model failure');
};

cases.route_missing_message_and_missing_chat_still_answer_before_any_model_or_gate_call = async () => {
  const gate = recorder(() => CLEAN);
  S.verify = gate.verify;
  S.db = makeDb();
  let res = await callTitle('   ');
  assert.equal(res.statusCode, 400);
  res = await callTitle(null);
  assert.equal(res.statusCode, 400);
  S.db = makeDb({ noChat: true });
  res = await callTitle('my own question');
  assert.equal(res.statusCode, 404);
  assert.deepEqual(S.completeParams, []);
  assert.deepEqual(gate.calls, []);
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
