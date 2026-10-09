// Adversary cases for Gate 1 over model-written chat titles, route POST /chat/:chatId/generate-title (chat.ts).
// (The tabular chat title is attacked in tabular_bypass_cases.ts.)
//
// Run once by test_title_gate_bypass.py under backend's tsx. REAL: the express router from backend/src/routes/chat.ts
// (the handler is pulled out of the router stack, after requireAuth) and all of hallucination_guard.ts, including the
// module-level title-gate limiter (cap 2, 75 s limit; the cases that need the limit scale the clock the way the
// tabular cases do). STUBBED: req / res, Supabase (a recording fake), the title model call, settings, auth, access,
// chatTools. Gate 1 is a stub verifier, except the cases named "real_gate": those run the production verify closure
// (verifyDraftForSse -> verifyDraft -> localGate1Text -> pipeline/gate1.py) against the fixture database named by
// KINGSFIELD_FLORIDA_DB, with Supabase replaced by a Proxy that throws. No Supabase, CourtListener, LLM or network.
//
// Every assertion is about what can leave the server (the JSON body and the database payloads), never about the
// mechanism, so a fix may take any shape. Prints one JSON line: { results: { caseName: null | "failure text" }, info }.

import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import path from 'node:path';
import type { SseVerificationResult } from '../../backend/src/middleware/hallucination_guard';

// ---------- helpers ----------

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
const GOOD = 'Good v. Case, 1 So. 3d 2 (Fla. 2010)';
const RAW = 'SQLITE_CANTOPEN: unable to open /Users/x/kingsfield_florida.db; CourtListener 503 hidden-detail-7731';
const RAW_LEAKS = ['SQLITE', 'CANTOPEN', 'kingsfield_florida', 'hidden-detail-7731', '/Users/x'];
const MARK = 'Zyxwv'; // a word only the model's title carries
const MISC = 'Misc. Query';
const OWN = 'my own question';

/** Stub Gate 1: vetoes any text holding the fabricated cite, as the real gate vetoes it. Sees only the text it is given. */
function fabVerify(text: string): SseVerificationResult {
  return text.includes(FAB_CORE) ? result([verdict(FAB, 'vetoed')]) : result([]);
}

function leakCheck(blob: string, needles: string[], label: string) {
  for (const n of needles) assert.ok(!blob.includes(n), `${label}: "${n}" reached the client or a saved row`);
}

const CONFUSABLES: Record<string, string> = {
  'а': 'a', 'е': 'e', 'о': 'o', 'р': 'p', 'с': 'c', 'х': 'x', 'і': 'i', 'ѕ': 's',
  'Ѕ': 'S', 'О': 'O', 'ο': 'o', 'Ο': 'O',
};

/** Fabricated "NNN So. 3d N" cites, however dressed, after the normalisation a renderer or the gate applies. */
function leakedCites(blob: string): string[] {
  let t = blob.normalize('NFKC');
  t = t.replace(/\p{Cf}/gu, '');
  t = t.replace(/[аеорсхіѕЅОοΟ]/g, (c) => CONFUSABLES[c] ?? c);
  t = t.replace(/&#(\d+);/g, (_m, n) => String.fromCodePoint(Number(n))).replace(/&amp;/g, '&').replace(/&nbsp;/g, ' ');
  t = t.replace(/<!--[\s\S]*?-->/g, '').replace(/[<>]/g, ' ');
  t = t.replace(/\\/g, '');
  return [...t.matchAll(/(\d{3})\W{0,3}So\W{0,3}3d\W{0,3}(\d{1,3})/gi)].map((m) => `${m[1]} So. 3d ${m[2]}`);
}

function requireRealGate() {
  assert.ok(process.env.KINGSFIELD_FLORIDA_DB, 'KINGSFIELD_FLORIDA_DB is not set: the real-gate cases need the fixture database');
}

const noSupabase: any = new Proxy({}, {
  get: () => {
    throw new Error('harness: the real-gate cases must never reach Supabase');
  },
});

/** Stub verifier recording every call. `rule` may return an Error to make the gate throw it. */
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

/** The spec of the fallback title, written independently of the code: the start of the user's own message. */
function expectedFallback(message: string): string {
  const flat = message.replace(/[\s\u0000-\u001f\u007f]+/g, ' ').trim();
  return Array.from(flat).slice(0, 120).join('').trim() || MISC;
}

// ---------- the real chat router, with its dependencies stubbed ----------

const ROOT = process.cwd();
const nodeRequire = createRequire(path.join(ROOT, 'backend', 'package.json'));
const CHAT = path.join(ROOT, 'backend', 'src', 'routes', 'chat.ts');
const GUARD_PATH = path.join(ROOT, 'backend', 'src', 'middleware', 'hallucination_guard.ts');

const S: {
  db: any;
  realGate: boolean;
  projectAccess: boolean;
  verify: (text: string) => Promise<SseVerificationResult>;
  completeText: (p: any) => Promise<any>;
  completeParams: any[];
} = {} as any;

function resetStubs() {
  S.db = undefined;
  S.realGate = false;
  S.projectAccess = false;
  S.verify = async () => CLEAN;
  S.completeText = async () => 'Lease Termination Rights';
  S.completeParams = [];
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
  '../lib/access': { checkProjectAccess: async () => ({ ok: S.projectAccess }) },
  // The real guard; only the Gate 1 verifier the route calls is replaced (stub, or the production closure).
  '../middleware/hallucination_guard': {
    ...realGuard,
    verifyDraftForSse: (text: string, _opts: unknown) =>
      S.realGate ? realGuard.verifyDraftForSse(text, { courtListenerToken: '', supabase: noSupabase }) : S.verify(text),
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

function handlerFor(method: 'get' | 'post', routePath: string) {
  const layer = chat.chatRouter.stack.find(
    (l: any) => l.route && l.route.path === routePath && l.route.methods && l.route.methods[method],
  );
  assert.ok(layer, `chatRouter has no ${method.toUpperCase()} ${routePath}`);
  const stack = layer.route.stack;
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

/** The chat row belongs to u1 (unless `owner` says otherwise); `updateThrows` / `updateError` break the title save. */
function chatDbFor(opts: { noChat?: boolean; owner?: string; projectId?: string | null; updateThrows?: boolean; updateError?: boolean } = {}) {
  return makeDb((op) => {
    if (op.table === 'chats' && op.op === 'select') {
      if (opts.noChat) return { data: null };
      return {
        data: {
          id: filterValue(op, 'eq', 'id') ?? 'c1',
          user_id: opts.owner ?? 'u1',
          project_id: opts.projectId ?? null,
          title: null,
        },
      };
    }
    if (op.table === 'chats' && op.op === 'update') {
      if (opts.updateThrows) return { throws: RAW };
      if (opts.updateError) return { error: { message: RAW } };
    }
    return undefined;
  });
}

async function callTitleRaw(message: unknown, chatId = 'c1') {
  const req: any = { body: { message }, params: { chatId }, query: {}, headers: {} };
  const res = fakeRes();
  await handlerFor('post', '/:chatId/generate-title')(req, res);
  return res;
}
const callTitle = (message: unknown, chatId = 'c1') => quiet(() => callTitleRaw(message, chatId));

const titleWrites = (db: any, chatId?: string): Op[] =>
  db.ops.filter((o: Op) => o.table === 'chats' && o.op === 'update' && (chatId === undefined || filterValue(o, 'eq', 'id') === chatId));

/**
 * The one shape every successful answer has: 200, a body of exactly {title}, exactly one database write that is
 * exactly {title} on the right chat, nothing else written, and nothing read or written outside `chats`.
 */
function assertOnlyTitle(res: any, db: any, expected: string, label: string, chatId = 'c1') {
  assert.equal(res.statusCode, 200, `${label}: status ${res.statusCode} ${JSON.stringify(res.body)}`);
  assert.deepEqual(Object.keys(res.body ?? {}), ['title'], `${label}: response keys`);
  assert.equal(res.body.title, expected, `${label}: returned title`);
  const w = titleWrites(db, chatId);
  assert.equal(w.length, 1, `${label}: ${w.length} title writes for ${chatId}`);
  assert.deepEqual(w[0].payload, { title: expected }, `${label}: saved payload`);
  assert.deepEqual(
    db.ops.filter((o: Op) => o.op !== 'select' && o.table === 'chats' && filterValue(o, 'eq', 'id') === chatId && o !== w[0]),
    [],
    `${label}: another write on the chat`,
  );
  assert.ok(db.ops.every((o: Op) => o.table === 'chats'), `${label}: a table other than chats was touched`);
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

// ---------- cases ----------

const cases: Record<string, () => Promise<void>> = {};
const info: Record<string, unknown> = {};

// ===== a fabricated Florida cite in the model's title =====

cases.title_plain_fabricated_cite_never_reaches_the_json_or_the_database = async () => {
  const gate = recorder(fabVerify);
  S.verify = gate.verify;
  S.db = chatDbFor();
  S.completeText = async () => FAB;
  const res = await callTitle('What are my termination rights?');
  assertOnlyTitle(res, S.db, 'What are my termination rights?', 'plain');
  assert.deepEqual(gate.calls, [FAB], 'the model title never went to Gate 1, or went more than once');
  leakCheck(JSON.stringify([res.body, S.db.ops]), ['Doe', 'Roe', '999'], 'plain');
};

// Quotes, markdown, a heading or quote marker, trailing punctuation, whitespace: the route normalizes before it saves.
// The string Gate 1 saw must be the string that is saved, and a fabricated cite must not survive any dressing.
cases.title_padded_with_quotes_markdown_and_whitespace_is_gated_as_it_is_saved = async () => {
  const padded = [
    `"${FAB}"`, `'${FAB}'`, `\`${FAB}\``, `**${FAB}**`, `# ${FAB}`, `> ${FAB}`, `${FAB}.`, `${FAB}?!`, `  \n ${FAB} \n `,
    `"""${FAB}"""`, `_${FAB}_`, `"${FAB}".`, `Title: ${FAB}`, `"${FAB}`, `${FAB}"`, `[${FAB}](http://x.test)`,
  ];
  for (const raw of padded) {
    resetStubs();
    const gate = recorder(fabVerify);
    S.verify = gate.verify;
    S.db = chatDbFor();
    S.completeText = async () => raw;
    const res = await callTitle(OWN);
    assertOnlyTitle(res, S.db, OWN, `padded ${JSON.stringify(raw)}`);
    assert.equal(gate.calls.length, 1, `padded ${JSON.stringify(raw)}: gate calls ${gate.calls.length}`);
    assert.ok(gate.calls[0].includes(FAB_CORE), `padded ${JSON.stringify(raw)}: the gate was not given the cite`);
    leakCheck(JSON.stringify([res.body, S.db.ops]), ['Doe', 'Roe', '999'], `padded ${JSON.stringify(raw)}`);
  }
  // Clean titles in the same dressing: the exact string that is saved and returned is the string the gate saw.
  const cleanPadded = ['"Lease Rights"', "'Lease Rights'.", '`Lease Rights`', '  Lease Rights?!  ', '**Lease Rights**', '# Lease Rights', '"""Lease Rights"""', 'Lease Rights:'];
  for (const raw of cleanPadded) {
    resetStubs();
    const gate = recorder(fabVerify);
    S.verify = gate.verify;
    S.db = chatDbFor();
    S.completeText = async () => raw;
    const res = await callTitle(OWN);
    assert.equal(res.statusCode, 200, `clean ${JSON.stringify(raw)}`);
    assert.equal(gate.calls.length, 1, `clean ${JSON.stringify(raw)}: gate calls`);
    assert.equal(res.body.title, gate.calls[0], `clean ${JSON.stringify(raw)}: returned title is not the string the gate saw`);
    assert.deepEqual(titleWrites(S.db).map((o) => o.payload), [{ title: gate.calls[0] }], `clean ${JSON.stringify(raw)}: saved title is not the string the gate saw`);
    assert.ok(res.body.title.includes('Lease Rights') && res.body.title.length <= 80, `clean ${JSON.stringify(raw)}: ${res.body.title}`);
  }
};

// The route cuts the title to 80 characters before it saves it. A cite cut in half is checked as cut; a cite the cut removes
// is gone; nothing is re-expanded.
cases.title_a_cite_cut_by_truncation_is_checked_as_cut_and_never_re_expanded = async () => {
  // (a) the cut leaves "999 So. 3d 9" at the end of the title: a cite shape with a one-digit page and no court. A strict gate vetoes it.
  const tail = 'Doe v. Roe, 999 So. 3d 9';
  const raw = `${'q'.repeat(80 - tail.length - 1)} ${tail}99 (Fla. 2015) and more words after the cite`;
  assert.ok(raw.slice(0, 80).endsWith('So. 3d 9'), 'harness: the cut is not where the case needs it');
  const strict = recorder((t) => (/\d{3} So\. 3d \d/.test(t) ? result([verdict(FAB, 'vetoed')]) : CLEAN));
  S.verify = strict.verify;
  S.db = chatDbFor();
  S.completeText = async () => raw;
  let res = await callTitle(OWN);
  assertOnlyTitle(res, S.db, OWN, 'cut cite');
  assert.equal(strict.calls.length, 1);
  assert.ok(strict.calls[0].length <= 80, `the gate was given ${strict.calls[0].length} characters, the saved title is at most 80`);
  assert.deepEqual(leakedCites(JSON.stringify([res.body, S.db.ops])), [], 'a cite fragment reached the client or the database');

  // (b) the cite starts after character 80: it is cut away. With a gate that lets everything through, what is saved has no cite and
  // is no longer than 80, so the route did not put the rest back.
  resetStubs();
  const lenient = recorder(() => CLEAN);
  S.verify = lenient.verify;
  S.db = chatDbFor();
  S.completeText = async () => `${'q'.repeat(78)} ${FAB}`;
  res = await callTitle(OWN);
  assert.equal(res.statusCode, 200);
  assert.ok(res.body.title.length <= 80, `title length ${res.body.title.length}`);
  assert.equal(res.body.title, lenient.calls[0], 'saved title differs from the string the gate saw');
  assert.deepEqual(leakedCites(JSON.stringify([res.body, S.db.ops])), [], 'a cite came back after the cut');
  leakCheck(JSON.stringify([res.body, S.db.ops]), ['999'], 'cite beyond the cut');

  // (c) the cut is in UTF-16 units, so it can leave half a surrogate pair. Documented, not a Gate 1 matter: the gated string is
  // still the saved string and the title stays within 80 units.
  resetStubs();
  const emo = recorder(() => CLEAN);
  S.verify = emo.verify;
  S.db = chatDbFor();
  S.completeText = async () => `${'q'.repeat(79)}\u{1F600} and more`;
  res = await callTitle(OWN);
  assert.equal(res.statusCode, 200);
  assert.ok(res.body.title.length <= 80, 'cut title longer than 80 units');
  assert.equal(res.body.title, emo.calls[0]);
};

// ===== every way the gate itself can fail =====

cases.title_every_gate_failure_mode_gives_the_fallback_and_nothing_else = async () => {
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
    const gate = recorder(rule);
    S.verify = gate.verify;
    S.db = chatDbFor();
    S.completeText = async () => `${MARK} ${GOOD}`;
    logs.length = 0;
    const res = await callTitle(OWN);
    assertOnlyTitle(res, S.db, OWN, label);
    assert.equal(gate.calls.length, 1, `${label}: the model title went to the gate ${gate.calls.length} times`);
    leakCheck(JSON.stringify([res.body, S.db.ops]), [MARK, 'Good v. Case', ...RAW_LEAKS], label);
  }
};

// The gate never answers: the title falls back when the (scaled) limit passes, the late answer changes nothing, the slot is freed.
cases.title_a_gate_that_never_answers_falls_back_ignores_the_late_answer_and_frees_the_slot = async () => {
  const late: Array<(r: SseVerificationResult) => void> = [];
  S.verify = () => new Promise<SseVerificationResult>((resolve) => late.push(resolve));
  S.db = chatDbFor();
  S.completeText = async () => `${MARK} Title`;
  const { out: res, requested } = await withScaledGateTimeout(() => finishes(callTitle(OWN), 'generate-title'));
  assertOnlyTitle(res, S.db, OWN, 'timeout');
  assert.ok(requested.length >= 1, 'the route never armed a gate timeout of 30 s or more');
  assert.ok(Math.min(...requested) >= 60_000, `the title gate limit (${Math.min(...requested)} ms) is shorter than the gate's own worst case (30 s queue + 30 s child)`);
  for (const r of late) r(CLEAN); // the abandoned gate call answers "clean" after the fact
  await sleep(40);
  assertOnlyTitle(res, S.db, OWN, 'timeout, after the late answer');
  leakCheck(JSON.stringify([res.body, S.db.ops]), [MARK], 'late answer');
  // the slot is free again: the next title through the same module-level limiter is gated normally and saved
  S.verify = async () => CLEAN;
  S.db = chatDbFor();
  S.completeText = async () => 'Lease Rights';
  const res2 = await callTitle(OWN);
  assertOnlyTitle(res2, S.db, 'Lease Rights', 'after the timeout');
};

// More hung gates than the limiter has slots (2): the queued requests must still end, each in the fallback of its own message.
cases.title_more_hung_gates_than_slots_still_end_each_in_its_own_fallback = async () => {
  S.verify = () => new Promise<SseVerificationResult>(() => {});
  S.db = chatDbFor();
  S.completeText = async () => `${MARK} Title`;
  const ids = [1, 2, 3, 4, 5].map((i) => `c${i}`);
  const { out } = await withScaledGateTimeout(() =>
    finishes(quiet(() => Promise.all(ids.map((id, i) => callTitleRaw(`question ${i + 1}`, id)))), 'five hung gates', 6000),
  );
  ids.forEach((id, i) => {
    const res: any = out[i];
    assertOnlyTitle(res, S.db, `question ${i + 1}`, `hung ${id}`, id);
  });
  leakCheck(JSON.stringify(S.db.ops), [MARK], 'hung gates');
};

// Six requests at once with different titles, delays and verdicts: nothing crosses between chats.
cases.title_concurrent_requests_keep_their_own_verdicts = async () => {
  const plan: Array<[string, string, number]> = [
    ['m1', 'Lease Rights', 0],
    ['m2', FAB, 30],
    ['m3', 'Notice Period', 10],
    ['m4', `Re ${FAB}`, 0],
    ['m5', 'Rent Escalation', 20],
    ['m6', `${MARK} ${FAB_CORE}`, 5],
  ];
  S.db = chatDbFor();
  S.completeText = async (p: any) => {
    const m = plan.find((x) => String(p.user).includes(`Message: ${x[0]}`));
    assert.ok(m, 'harness: no plan for ' + String(p.user).slice(-40));
    await sleep(m![2]);
    return m![1];
  };
  S.verify = async (t) => {
    await sleep((t.length % 3) * 7);
    return fabVerify(t);
  };
  const ids = plan.map((_p, i) => `c${i + 1}`);
  const out = await quiet(() => Promise.all(plan.map((p, i) => callTitleRaw(p[0], ids[i]))));
  const expected = [plan[0][1], 'm2', plan[2][1], 'm4', plan[4][1], 'm6'];
  expected.forEach((title, i) => assertOnlyTitle(out[i], S.db, title, `request ${plan[i][0]}`, ids[i]));
  leakCheck(JSON.stringify([out.map((r) => r.body), S.db.ops]), ['Doe', 'Roe', '999', MARK], 'concurrent');
};

// ===== the model call itself, and the save =====

cases.title_model_failures_save_nothing_return_the_fixed_500_and_empty_titles_become_the_fixed_title = async () => {
  const bad: Array<[string, () => Promise<any>]> = [
    ['throws', async () => { throw new Error(`provider exploded ${RAW}`); }],
    ['null', async () => null],
    ['undefined', async () => undefined],
    ['a number', async () => 5],
    ['an object', async () => ({ title: FAB })],
    ['an array', async () => [FAB]],
  ];
  for (const [label, model] of bad) {
    resetStubs();
    const gate = recorder(fabVerify);
    S.verify = gate.verify;
    S.db = chatDbFor();
    S.completeText = model;
    const res = await callTitle(OWN);
    assert.equal(res.statusCode, 500, `${label}: status ${res.statusCode} ${JSON.stringify(res.body)}`);
    assert.deepEqual(res.body, { detail: 'Failed to generate title' }, `${label}: body`);
    assert.deepEqual(titleWrites(S.db), [], `${label}: a title was saved`);
    leakCheck(JSON.stringify([res.body, S.db.ops]), [...RAW_LEAKS, 'provider exploded', 'Doe', '999'], label);
  }
  // Nothing usable after normalisation: the fixed title, and the fixed title is what was gated and saved.
  for (const raw of ['', '   ', '"."', '  "." ', '...']) {
    resetStubs();
    const gate = recorder(fabVerify);
    S.verify = gate.verify;
    S.db = chatDbFor();
    S.completeText = async () => raw;
    const res = await callTitle(OWN);
    assertOnlyTitle(res, S.db, MISC, `empty ${JSON.stringify(raw)}`);
    assert.deepEqual(gate.calls, [MISC], `empty ${JSON.stringify(raw)}: the saved string is the one gated`);
  }
};

cases.title_a_failing_save_returns_only_fixed_text_or_the_gated_title = async () => {
  // The save throws: fixed 500, no model text, no raw error.
  S.verify = async (t) => fabVerify(t);
  S.db = chatDbFor({ updateThrows: true });
  S.completeText = async () => `${MARK} ${FAB}`;
  let res = await callTitle(OWN);
  assert.equal(res.statusCode, 500);
  assert.deepEqual(res.body, { detail: 'Failed to generate title' });
  leakCheck(JSON.stringify(res.body), [...RAW_LEAKS, MARK, 'Doe', '999'], 'throwing save');
  // The save returns an {error}: the route does not look, so whatever it answers must still be the gated title only.
  resetStubs();
  S.verify = async (t) => fabVerify(t);
  S.db = chatDbFor({ updateError: true });
  S.completeText = async () => `${MARK} ${FAB}`;
  res = await callTitle(OWN);
  assert.equal(res.statusCode, 200);
  assert.deepEqual(res.body, { title: OWN });
  leakCheck(JSON.stringify([res.body, S.db.ops]), [...RAW_LEAKS, MARK, 'Doe', '999'], 'error-result save');
};

// ===== where the fallback comes from =====

// The fallback is built from req.body.message (client-supplied; the route never reads the chat's stored messages). It is user text,
// not model text: the model's wording must not reach it, whatever the message holds.
cases.title_fallback_is_only_the_requesters_message_flattened_and_cut = async () => {
  info.title_fallback_source = 'req.body.message (client-supplied, not read back from chat_messages)';
  const messages = [
    'What are my termination rights under the lease?',
    '  What  are\nmy\ttermination\r\n rights?  ',
    'a\u0000b\u0007c\u007fd',
    'x'.repeat(500),
    '\u{1F600}'.repeat(200),
    `${MARK}-user wrote this`,
    `Is Smith v. State, 100 So. 3d 200 (Fla. 2012) still good law?`,
    '\u0007\u0001\u007f', // not whitespace, so the route proceeds, but nothing usable is left: the fixed title
  ];
  for (const message of messages) {
    resetStubs();
    const gate = recorder(fabVerify);
    S.verify = gate.verify;
    S.db = chatDbFor();
    S.completeText = async () => `${MARK}-model ${FAB}`;
    const res = await callTitle(message);
    const want = expectedFallback(message);
    assertOnlyTitle(res, S.db, want, `message ${JSON.stringify(message).slice(0, 40)}`);
    assert.deepEqual(gate.calls, [`${MARK}-model ${FAB}`.slice(0, 80)], 'only the model title is gated; the fallback is the user text');
    assert.ok(!/[\u0000-\u001f\u007f]/.test(res.body.title), 'a control character in the fallback title');
    assert.ok(Array.from(res.body.title).length <= 120, 'fallback longer than 120 code points');
    assert.ok(!/[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/.test(res.body.title), 'a lone surrogate in the fallback');
    assert.ok(!res.body.title.includes(`${MARK}-model`), 'model words reached the fallback');
  }
  // A message that is not a non-blank string is refused before any model call, database write or gate call.
  for (const bad of [undefined, null, 5, {}, ['x'], '', '   ', '\n\t ']) {
    resetStubs();
    const gate = recorder(() => CLEAN);
    S.verify = gate.verify;
    S.db = chatDbFor();
    const res = await callTitle(bad);
    assert.equal(res.statusCode, 400, `message ${JSON.stringify(bad)}: status ${res.statusCode}`);
    assert.deepEqual(S.completeParams, [], `message ${JSON.stringify(bad)}: the model was called`);
    assert.deepEqual(gate.calls, []);
    assert.deepEqual(titleWrites(S.db), []);
  }
};

// Authorization comes before generation: a chat the user cannot reach is never titled, and the model is never called.
cases.title_a_chat_the_user_cannot_reach_is_never_titled = async () => {
  for (const [label, db, access] of [
    ['someone else\'s chat', chatDbFor({ owner: 'u2' }), false],
    ['someone else\'s chat in a project the user cannot open', chatDbFor({ owner: 'u2', projectId: 'p1' }), false],
    ['no such chat', chatDbFor({ noChat: true }), true],
  ] as Array<[string, any, boolean]>) {
    resetStubs();
    S.projectAccess = access;
    const gate = recorder(() => CLEAN);
    S.verify = gate.verify;
    S.db = db;
    const res = await callTitle(OWN);
    assert.equal(res.statusCode, 404, `${label}: status ${res.statusCode}`);
    assert.deepEqual(res.body, { detail: 'Chat not found' }, label);
    assert.deepEqual(S.completeParams, [], `${label}: the model was called`);
    assert.deepEqual(gate.calls, [], `${label}: the gate was called`);
    assert.deepEqual(titleWrites(S.db), [], `${label}: a title was saved`);
  }
};

// ===== real gate, fixture database =====

/** A titles list to run through the production gate. Every one must be at most 80 UTF-16 units, or the route's cut would hide the cite. */
// (Each one spawns the Python gate once: the list is kept to what the other Gate 1 suites do not already cover for titles.)
const REAL_GATE_FABRICATED: Array<[string, string]> = [
  ['plain', 'Doe v. Roe, 999 So. 3d 999 (Fla. 2015)'],
  ['no court parenthetical', 'Doe v. Roe, 999 So. 3d 999'],
  ['full-width digits', 'Doe v. Roe, ９９９ So. 3d ９９９ (Fla. 2015)'],
  ['zero-width space inside the reporter', 'Doe v. Roe, 111 So.​ 3d 111 (Fla. 2015)'],
  ['zero-width space inside the volume', 'Doe v. Roe, 9​99 So. 3d 999 (Fla. 2015)'],
  ['period-less', 'Doe v. Roe, 999 So 3d 999 (Fla. 2015)'],
  ['upper-case', 'DOE V. ROE, 999 SO. 3D 999 (FLA. 2015)'],
  ['Cyrillic o in So.', 'Doe v. Roe, 999 Sо. 3d 999 (Fla. 2015)'],
  ['OCR zero for o', 'Doe v. Roe, 999 S0. 3d 999 (Fla. 2015)'],
  ['Fla. L. Weekly', 'Doe v. Roe, 999 Fla. L. Weekly D999 (Fla. 2015)'],
  ['real volume and page, another case\'s caption', 'Jones v. Acme Insurance Co., 100 So. 3d 200 (Fla. 2012)'],
  ['real cite, pin past the last page', 'Smith v. State, 100 So. 3d 200, 460 (Fla. 2012)'],
  ['markdown link title (hidden channel)', '[Lease Rights](http://x.test "Doe v. Roe, 999 So. 3d 999 (Fla. 2015)")'],
  ['html attribute (hidden channel)', '<b title="Doe v. Roe, 999 So. 3d 999 (Fla. 2015)">Lease</b>'],
  ['numeric entity', 'Doe v. Roe, &#57;&#57;&#57; So. 3d 999 (Fla. 2015)'],
];

cases.title_real_gate_obfuscated_and_near_miss_cites_fall_back = async () => {
  requireRealGate();
  const released: string[] = [];
  const leaks: string[] = [];
  const how: Record<string, string> = {};
  for (const [label, title] of REAL_GATE_FABRICATED) {
    assert.ok(title.length <= 80, `harness: "${label}" is ${title.length} units; the route's cut would hide the cite`);
    resetStubs();
    S.realGate = true;
    S.db = chatDbFor();
    S.completeText = async () => title;
    const res = await callTitle(OWN);
    how[label] = res.statusCode === 200 && res.body?.title === OWN ? 'fallback' : `RELEASED ${res.statusCode} ${JSON.stringify(res.body).slice(0, 80)}`;
    if (how[label] !== 'fallback') released.push(`${label}: ${how[label]}`);
    const blob = JSON.stringify([res.body, S.db.ops]);
    const found = leakedCites(blob);
    if (found.length) leaks.push(`${label}: ${found.join('; ')}`);
    if (blob.includes('Doe v. Roe') || blob.includes('Jones v. Acme') || blob.includes('Smith v. State')) leaks.push(`${label}: a caption reached the client or the database`);
  }
  info.title_real_gate = how;
  assert.deepEqual(released, [], `fabricated or near-miss cites were released as titles (production gate): ${released.join(' | ')}`);
  assert.deepEqual(leaks, [], `cites reached the client or the database: ${leaks.join(' | ')}`);
};

// A cite the cut leaves whole is checked as cut; the production gate must veto the half it can see.
cases.title_real_gate_a_cite_cut_in_half_by_truncation_does_not_survive = async () => {
  requireRealGate();
  const cuts: Array<[string, string]> = [];
  for (const tail of ['Doe v. Roe, 999 So. 3d 9', 'Doe v. Roe, 999 So. 3d 999 (F', 'Doe v. Roe, 999 So. 3']) {
    cuts.push([tail, `${'q'.repeat(80 - tail.length - 1)} ${tail}${FAB.slice(tail.length)} and more words`]);
  }
  const bad: string[] = [];
  for (const [tail, raw] of cuts) {
    resetStubs();
    S.realGate = true;
    S.db = chatDbFor();
    S.completeText = async () => raw;
    const res = await callTitle(OWN);
    assert.equal(res.statusCode, 200, tail);
    const saved = res.body.title as string;
    assert.ok(saved.length <= 80, `${tail}: saved title is ${saved.length} units`);
    assert.deepEqual(Object.keys(res.body), ['title']);
    assert.deepEqual(titleWrites(S.db).map((o) => o.payload), [{ title: saved }], `${tail}: saved differs from returned`);
    // Either the fallback, or a title that holds no complete reporter cite. "999 So. 3d 9" is a complete cite shape.
    if (saved !== OWN && leakedCites(saved).length) bad.push(`${tail}: released ${JSON.stringify(saved)}`);
  }
  assert.deepEqual(bad, [], `a cite cut by truncation was released as a title: ${bad.join(' | ')}`);
};

// Controls: the gate is not vetoing everything, and a real local pass does not skip the rest of the pipeline.
cases.title_real_gate_clean_titles_pass_and_a_cite_without_the_rest_of_the_pipeline_fails_closed = async () => {
  requireRealGate();
  for (const clean of ['Lease Termination Rights']) {
    resetStubs();
    S.realGate = true;
    S.db = chatDbFor();
    S.completeText = async () => clean;
    const res = await callTitle(OWN);
    assertOnlyTitle(res, S.db, clean, `control ${clean}`);
  }
  // A cite that exists in the fixture passes the local index, then the pipeline reads the cache (Supabase): here it is unreachable.
  // The title must then fall back rather than release a cite that was not fully verified.
  resetStubs();
  S.realGate = true;
  S.db = chatDbFor();
  S.completeText = async () => 'Smith v. State, 100 So. 3d 200 (Fla. 2012)';
  const res = await callTitle(OWN);
  info.title_real_gate_existing_cite_without_supabase = res.body;
  assertOnlyTitle(res, S.db, OWN, 'existing cite, pipeline unavailable');
};

// ===== open item: titles stored before the gate existed are read back as they are =====

cases.open_stored_chat_titles_are_gated_on_read = async () => {
  S.db = makeDb((op) => {
    if (op.table === 'chats') return { data: { id: 'c1', user_id: 'u1', project_id: null, title: FAB } };
    if (op.table === 'chat_messages') return { data: [] };
    return undefined;
  });
  S.verify = async (t) => fabVerify(t);
  const req: any = { body: {}, params: { chatId: 'c1' }, query: {}, headers: {} };
  const res = fakeRes();
  await quiet(() => handlerFor('get', '/:chatId')(req, res));
  assert.ok(res.body, `no body (status ${res.statusCode})`);
  leakCheck(JSON.stringify(res.body), ['Doe', 'Roe', '999'], 'stored chat title on GET /chat/:chatId');
};

// ---------- run ----------

async function main() {
  const results: Record<string, string | null> = {};
  // The limiter's timers are unref'd; keep the loop alive while a case waits on one.
  const keep = setInterval(() => {}, 1000);
  for (const [name, fn] of Object.entries(cases)) {
    resetStubs();
    try {
      await fn();
      results[name] = null;
    } catch (e: any) {
      results[name] = String(e?.stack ?? e?.message ?? e).slice(0, 1500);
    }
  }
  clearInterval(keep);
  const text = JSON.stringify({ results, info });
  process.stdout.write(`${text}\n`, () => process.exit(0));
}

void main();
