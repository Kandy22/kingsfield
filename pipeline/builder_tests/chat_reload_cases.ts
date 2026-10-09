// A vetoed chat reply is persisted by the REAL POST routes (chat.ts, projectChat.ts) and read back by the REAL
// GET /chat/:chatId handler (chat.ts, which now also gates the stored title on read). Proves that the veto record
// survives the reload byte for byte, that no vetoed text comes back, and that the title read-gate neither drops nor
// reshapes the messages.
//
// Run by test_chat_reload.py once under backend's tsx. Real: chat.ts, projectChat.ts, hallucination_guard.ts (except the
// Gate 1 verifier), safeError.ts, express's Router. Stubbed: req / res, auth, a STATEFUL in-memory Supabase fake (inserts
// land in tables, selects read them back), runLLMStream (writes scripted SSE lines), settings, access, the model client.
// No Supabase, CourtListener, LLM, Python gate or network. Prints {caseName: null | "failure text"}.

import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import path from 'node:path';

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v));
const line = (ev: unknown) => `data: ${JSON.stringify(ev)}\n\n`;
const delta = (text: string) => line({ type: 'content_delta', text });

const verdict = (citation: string, status: string) => ({
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

/** Vetoes any "999 So. 3d N" cite, verifies every other "N So. 3d N" cite. */
function coreVerify(text: string) {
  const seen = new Map<string, any>();
  for (const m of text.matchAll(/(\d{1,4}) So\. 3d (\d{1,5})/g)) {
    if (!seen.has(m[0])) seen.set(m[0], verdict(m[0], m[1] === '999' ? 'vetoed' : 'verified'));
  }
  return result([...seen.values()]);
}

const ROOT = process.cwd();
const nodeRequire = createRequire(path.join(ROOT, 'backend', 'package.json'));
const CHAT = path.join(ROOT, 'backend', 'src', 'routes', 'chat.ts');
const PROJECT_CHAT = path.join(ROOT, 'backend', 'src', 'routes', 'projectChat.ts');
const GUARD_PATH = path.join(ROOT, 'backend', 'src', 'middleware', 'hallucination_guard.ts');
const realGuard = nodeRequire(GUARD_PATH);

const S: {
  db: any;
  verify: (text: string) => Promise<any>;
  /** What the stubbed runLLMStream does: write these SSE lines through the route's writer, then return this. */
  stream: { lines: string[]; fullText: string; events: any[]; annotations: any[] } | Error;
} = {} as any;

const requireAuthStub = function requireAuth(_req: any, _res: any, next: any) {
  next();
};
const STUBS: Record<string, any> = {
  '../middleware/auth': { requireAuth: requireAuthStub },
  '../lib/supabase': { createServerSupabase: () => S.db },
  '../lib/chatTools': {
    buildDocContext: async () => ({ docIndex: {}, docStore: new Map() }),
    buildProjectDocContext: async () => ({ docIndex: {}, docStore: new Map(), folderPaths: new Map() }),
    buildMessages: () => [],
    enrichWithPriorEvents: (m: unknown) => m,
    buildWorkflowStore: async () => ({}),
    isAbortError: () => false,
    PROJECT_EXTRA_TOOLS: [],
    runLLMStream: async (p: any) => {
      if (S.stream instanceof Error) throw S.stream;
      for (const l of S.stream.lines) p.write(l);
      return { fullText: S.stream.fullText, events: clone(S.stream.events), annotations: clone(S.stream.annotations) };
    },
  },
  '../lib/llm': { completeText: async () => 'unused' },
  '../lib/userSettings': { getUserModelSettings: async () => ({ title_model: 'stub', api_keys: {}, legal_research_us: false }) },
  '../lib/access': { checkProjectAccess: async () => ({ ok: true }) },
  '../middleware/hallucination_guard': {
    ...realGuard,
    verifyDraftForSse: (text: string, _opts: unknown) => S.verify(text),
  },
};
const ModuleCtor: any = nodeRequire('module');
const origLoad = ModuleCtor._load;
function loadRoute(file: string): any {
  ModuleCtor._load = function (request: string, parent: any, ...rest: unknown[]) {
    if (parent && parent.filename === file && Object.prototype.hasOwnProperty.call(STUBS, request)) return STUBS[request];
    return origLoad.call(this, request, parent, ...rest);
  };
  try {
    return nodeRequire(file);
  } finally {
    ModuleCtor._load = origLoad;
  }
}
const chat = loadRoute(CHAT);
const projectChat = loadRoute(PROJECT_CHAT);

function handlerOf(router: any, routePath: string, method: 'get' | 'post') {
  const layer = router.stack.find((l: any) => l.route && l.route.path === routePath && l.route.methods && l.route.methods[method]);
  assert.ok(layer, `no ${method.toUpperCase()} ${routePath}`);
  const stack = layer.route.stack;
  assert.equal(stack[0].handle, requireAuthStub, 'requireAuth is not the first layer');
  return stack[stack.length - 1].handle as (req: any, res: any) => Promise<void>;
}

async function quiet<T>(fn: () => Promise<T>): Promise<T> {
  const orig = { log: console.log, info: console.info, warn: console.warn, error: console.error };
  for (const k of Object.keys(orig) as Array<keyof typeof orig>) (console as any)[k] = () => {};
  try {
    return await fn();
  } finally {
    Object.assign(console, orig);
  }
}

function fakeRes() {
  const r: any = { statusCode: 200, body: undefined, written: [] as string[], closeHandlers: [] as Array<() => void>, locals: { userId: 'u1', userEmail: 'u@x.test' } };
  r.setHeader = () => r;
  r.flushHeaders = () => {};
  r.write = (s: string) => {
    r.written.push(s);
    return true;
  };
  r.end = () => {};
  r.on = (ev: string, fn: () => void) => {
    if (ev === 'close') r.closeHandlers.push(fn);
    return r;
  };
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

/** Stateful in-memory Supabase fake: insert / select / update / order / eq / in / single / maybeSingle over plain arrays. */
function makeDb() {
  const tables: Record<string, any[]> = { chats: [], chat_messages: [], document_edits: [], document_versions: [] };
  let clock = 0;
  let ids = 0;
  const chain = (st: any): any =>
    new Proxy(function () {}, {
      get(_t, prop) {
        if (prop === 'then') {
          return (res: any, rej: any) => {
            const rows = (tables[st.table] ??= []);
            const matches = () =>
              rows.filter((r) => st.filters.every(([kind, col, val]: any[]) => (kind === 'eq' ? r[col] === val : (val as unknown[]).includes(r[col]))));
            let out: any;
            if (st.action === 'insert') {
              const row = { id: st.table === 'chats' ? `c${++ids}` : `m${++ids}`, created_at: ++clock, title: null, ...clone(st.payload) };
              rows.push(row);
              out = { data: st.single ? clone(row) : [clone(row)], error: null };
            } else if (st.action === 'update') {
              for (const r of matches()) Object.assign(r, clone(st.payload));
              out = { data: null, error: null };
            } else {
              let found = matches().map(clone);
              if (st.order) found.sort((a, b) => (a[st.order] - b[st.order]));
              out = { data: st.single ? (found[0] ?? null) : found, error: null };
            }
            return Promise.resolve(out).then(res, rej);
          };
        }
        if (prop === 'insert' || prop === 'update') {
          return (payload: unknown) => chain({ ...st, action: prop, payload });
        }
        if (prop === 'eq') return (col: string, val: unknown) => chain({ ...st, filters: [...st.filters, ['eq', col, val]] });
        if (prop === 'in') return (col: string, val: unknown[]) => chain({ ...st, filters: [...st.filters, ['in', col, val]] });
        if (prop === 'order') return (col: string) => chain({ ...st, order: col });
        if (prop === 'single' || prop === 'maybeSingle') return () => chain({ ...st, single: true });
        return () => chain(st); // select(...), limit(...)
      },
    });
  return {
    tables,
    from: (table: string) => chain({ table, action: 'select', filters: [], single: false, order: null }),
  };
}

const FAB = 'Doe v. Roe, 999 So. 3d 999 (Fla. 2015)';
const GOOD = 'Good v. Case, 1 So. 3d 2 (Fla. 2010)';
const caseEntry = (id: number, citation: string) => ({
  type: 'citation_data', kind: 'case', ref: id, cluster_id: id, case_name: `Case ${id}`, citation, url: `https://example.test/${id}`, quotes: [],
});

function script(parts: string[], annotations: any[] = []) {
  const fullText = parts.join('');
  return { lines: [...parts.map(delta), 'data: [DONE]\n\n'], fullText, events: [{ type: 'content', text: fullText }], annotations };
}

const sseEvents = (res: any): any[] =>
  res.written
    .join('')
    .split('\n\n')
    .filter((s: string) => s.startsWith('data: ') && s !== 'data: [DONE]')
    .map((s: string) => JSON.parse(s.slice(6)));

async function post(router: any, routePath: string, body: unknown, params: Record<string, string> = {}) {
  const res = fakeRes();
  await quiet(() => handlerOf(router, routePath, 'post')({ body, params, query: {} }, res));
  return res;
}
async function reload(chatId: string) {
  const res = fakeRes();
  await quiet(() => handlerOf(chat.chatRouter, '/:chatId', 'get')({ params: { chatId }, query: {}, body: {} }, res));
  assert.equal(res.statusCode, 200, `reload status ${res.statusCode}: ${JSON.stringify(res.body)}`);
  return res.body as { chat: any; messages: any[] };
}

const VETO_MESSAGE: string = realGuard.VETO_WITHHELD_MESSAGE;
const WITHHELD_MESSAGE: string = realGuard.WITHHELD_MESSAGE;

const cases: Record<string, () => Promise<void>> = {};

/** The checks every vetoed reload must pass, whichever route stored it. */
function assertVetoSurvived(sent: any[], loaded: { chat: any; messages: any[] }, label: string) {
  const sseRecord = sent.find((e) => e.type === 'verification');
  assert.ok(sseRecord, `${label}: no verification event was sent`);
  assert.equal(sseRecord.hasVetoes, true, `${label}: the sent verification event does not carry the veto`);
  const assistant = loaded.messages.filter((m) => m.role === 'assistant');
  assert.equal(assistant.length, 1, `${label}: one assistant row after reload`);
  const m = assistant[0];
  const records = (m.annotations as any[]).filter((a) => a && a.type === 'verification');
  assert.equal(records.length, 1, `${label}: exactly one verification record after reload`);
  assert.equal(m.annotations[m.annotations.length - 1], records[0], `${label}: the record is not last`);
  assert.deepEqual(records[0], sseRecord, `${label}: reloaded record differs from the event that was sent`);
  assert.equal(records[0].hasVetoes, true);
  const vetoed = records[0].verdicts.filter((v: any) => v.status === 'vetoed');
  assert.equal(vetoed.length, 1, `${label}: vetoed verdict count`);
  assert.equal(vetoed[0].citation, '', `${label}: a vetoed verdict carries no citation text`);
  assert.deepEqual(
    (m.content as any[]).map((e) => e.type),
    ['content'],
    `${label}: reloaded content is not the single fixed message`,
  );
  assert.equal(m.content[0].text, VETO_MESSAGE, `${label}: reloaded text is not the fixed veto message`);
  // what the browser was given equals what a reload gives
  const sentText = sent.filter((e) => e.type === 'content_delta').map((e) => e.text).join('');
  assert.equal(sentText, m.content[0].text, `${label}: saved differs from sent`);
  const blob = JSON.stringify(loaded.messages.filter((x) => x.role === 'assistant')) + JSON.stringify(sent);
  for (const leak of ['999', 'Doe', 'Roe', 'rule applies', 'Case 1']) {
    assert.ok(!blob.includes(leak), `${label}: "${leak}" survived the veto (sent or reloaded)`);
  }
}

const FAB_PARTS = ['As held in Doe v. Ro', 'e, 999 So. 3d 9', '99 (Fla. 2015), the rule applies. See also ', GOOD, '.'];

cases.chat_route_a_vetoed_reply_is_stored_and_a_reload_shows_the_veto = async () => {
  S.db = makeDb();
  S.verify = async (t) => coreVerify(t);
  S.stream = script(FAB_PARTS, [caseEntry(1, '999 So. 3d 999'), caseEntry(2, '1 So. 3d 2')]);
  const res = await post(chat.chatRouter, '/', { messages: [{ role: 'user', content: 'What does the rule say?' }] });
  const sent = sseEvents(res);
  const chatId = sent.find((e) => e.type === 'chat_id').chatId;
  const loaded = await reload(chatId);
  assert.equal(loaded.messages.length, 2, 'user row and assistant row');
  assert.equal(loaded.messages[0].role, 'user');
  assertVetoSurvived(sent, loaded, 'chat.ts');
  // the stored row is the one the route inserted, not something the reload rebuilt
  const stored = S.db.tables.chat_messages.filter((r: any) => r.role === 'assistant');
  assert.equal(stored.length, 1);
  assert.deepEqual(loaded.messages[1].annotations, stored[0].annotations);
  assert.deepEqual(loaded.messages[1].content, stored[0].content);
};

cases.project_route_a_vetoed_reply_is_stored_and_a_reload_shows_the_veto = async () => {
  S.db = makeDb();
  S.verify = async (t) => coreVerify(t);
  S.stream = script(FAB_PARTS, [caseEntry(1, '999 So. 3d 999')]);
  const res = await post(projectChat.projectChatRouter, '/', { messages: [{ role: 'user', content: 'What does the rule say?' }] }, { projectId: 'p1' });
  const sent = sseEvents(res);
  const chatId = sent.find((e) => e.type === 'chat_id').chatId;
  const loaded = await reload(chatId);
  assert.equal(loaded.chat.project_id, 'p1');
  assertVetoSurvived(sent, loaded, 'projectChat.ts');
};

cases.a_withheld_reply_after_a_gate_error_reloads_as_unverified = async () => {
  S.db = makeDb();
  S.verify = async () => {
    throw new Error('SQLITE_CANTOPEN: unable to open /Users/x/kingsfield_florida.db');
  };
  S.stream = script(['Per ', GOOD, ' it holds.']);
  const res = await post(chat.chatRouter, '/', { messages: [{ role: 'user', content: 'Hello' }] });
  const sent = sseEvents(res);
  const loaded = await reload(sent.find((e) => e.type === 'chat_id').chatId);
  const m = loaded.messages.find((x) => x.role === 'assistant');
  const record = m.annotations.find((a: any) => a.type === 'verification');
  assert.equal(record.hasVetoes, true);
  assert.equal(record.error, 'Verification failed.');
  assert.equal(m.content[0].text, WITHHELD_MESSAGE);
  assert.deepEqual(record, sent.find((e) => e.type === 'verification'));
  const blob = JSON.stringify(m);
  for (const leak of ['SQLITE', 'kingsfield_florida', 'Good v. Case', 'it holds']) assert.ok(!blob.includes(leak), `leaked ${leak}`);
};

cases.a_clean_reply_reloads_unchanged_with_a_clean_record = async () => {
  S.db = makeDb();
  S.verify = async (t) => coreVerify(t);
  S.stream = script(['Per ', GOOD, ', yes.']);
  const res = await post(chat.chatRouter, '/', { messages: [{ role: 'user', content: 'Is that so?' }] });
  const sent = sseEvents(res);
  const loaded = await reload(sent.find((e) => e.type === 'chat_id').chatId);
  const m = loaded.messages.find((x) => x.role === 'assistant');
  const record = m.annotations.find((a: any) => a.type === 'verification');
  assert.equal(record.hasVetoes, false);
  assert.deepEqual(record, sent.find((e) => e.type === 'verification'));
  assert.equal(m.content.filter((e: any) => e.type === 'content').map((e: any) => e.text).join(''), `Per ${GOOD}, yes.`);
};

cases.a_failed_stream_reloads_as_the_fixed_marker_only = async () => {
  S.db = makeDb();
  S.verify = async (t) => coreVerify(t);
  S.stream = new Error('upstream exploded while writing 999 So. 3d 999');
  const res = await post(chat.chatRouter, '/', { messages: [{ role: 'user', content: 'Hello' }] });
  const chatId = sseEvents(res).find((e) => e.type === 'chat_id').chatId;
  const loaded = await reload(chatId);
  const blob = JSON.stringify(loaded.messages.filter((x) => x.role === 'assistant'));
  assert.ok(!blob.includes('999') && !blob.includes('exploded'), blob);
  assert.equal(loaded.messages.filter((x) => x.role === 'assistant').length, 1);
};

cases.the_title_read_gate_replaces_a_bad_stored_title_and_leaves_the_messages_alone = async () => {
  S.db = makeDb();
  S.verify = async (t) => coreVerify(t);
  S.stream = script(FAB_PARTS);
  // The user's own first message (a fabricated cite) becomes the stored title on the success path.
  const asked = `Is ${FAB} good law?`;
  const res = await post(chat.chatRouter, '/', { messages: [{ role: 'user', content: asked }] });
  const sent = sseEvents(res);
  const chatId = sent.find((e) => e.type === 'chat_id').chatId;
  assert.equal(S.db.tables.chats[0].title, asked.slice(0, 120), 'the success path stored the user\'s text as the title');
  const loaded = await reload(chatId);
  assert.equal(loaded.chat.title, 'Misc. Query', 'the stored title is replaced on read');
  assert.ok(!JSON.stringify(loaded.chat).includes('999'));
  // The messages come back exactly as stored, veto included; only the chat title was touched.
  assert.equal(loaded.messages.length, 2);
  assert.equal(loaded.messages[0].content, asked, 'the user\'s own message is shown as typed');
  assertVetoSurvived(sent, loaded, 'title replaced');
  assert.equal(S.db.tables.chats[0].title, asked.slice(0, 120), 'the stored title row is not rewritten by a read');
};

cases.a_failing_title_gate_does_not_hide_or_reshape_the_messages = async () => {
  S.db = makeDb();
  S.stream = script(FAB_PARTS);
  const asked = 'Plain question about the rule';
  S.verify = async (t) => coreVerify(t);
  const res = await post(chat.chatRouter, '/', { messages: [{ role: 'user', content: asked }] });
  const sent = sseEvents(res);
  const chatId = sent.find((e) => e.type === 'chat_id').chatId;
  // From now on Gate 1 blows up on every call: the title read-gate fails, the reload must still work.
  S.verify = async () => {
    throw new Error('gate down');
  };
  const loaded = await reload(chatId);
  assert.equal(loaded.chat.title, 'Misc. Query', 'a title that cannot be checked is replaced');
  assertVetoSurvived(sent, loaded, 'title gate down');
};

(async () => {
  const report: Record<string, string | null> = {};
  for (const [name, fn] of Object.entries(cases)) {
    try {
      await fn();
      report[name] = null;
    } catch (err: any) {
      report[name] = String(err?.stack ?? err).slice(0, 2500);
    }
  }
  process.stdout.write('\nRELOAD_REPORT=' + JSON.stringify(report) + '\n');
  process.exit(0);
})();
