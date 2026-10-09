// Adversary cases for POST /crew/chat that route_behavior_cases.ts cannot reach (it runs in MOCK_LLM mode, where the
// request's documentIds and the crew are never touched). Run once by test_crew_chat_bypass.py under backend's tsx.
//
//   1. crew_chat_document_ids_of_another_user_are_never_read
//        User B posts documentIds = [A's document]. The route must not load that document's version or bytes for B.
//        (fetchDocumentTexts used to select documents by id with the service-role client and no owner check.)
//   2. crew_chat_nothing_is_sent_after_the_client_disconnects_and_the_fallback_model_call_is_skipped
//        The client leaves while runCrew is running. runCrew's signal is aborted, the keepalive is stopped, the
//        completeText fallback is not started, and nothing at all is written after the disconnect.
//   3. crew_chat_a_throwing_crew_after_disconnect_writes_nothing
//
// REAL: buildRoutes() from backend/src/routes/index.ts (the handler after requireAuth), the express Router, the whole
// of hallucination_guard.ts. STUBBED (by module, for index.ts only): the crew coordinator, documentVersions, storage, the
// user settings; Supabase is a fake that honours eq / in filters over plain rows; req / res are recording fakes. Gate 1
// for the reply runs for real against the fixture database (KINGSFIELD_FLORIDA_DB) but the replies here carry no cite.
//
// Prints one JSON line: { results: { caseName: null | "failure text" } }.

import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import path from 'node:path';

const ROOT = process.cwd();
const nodeRequire = createRequire(path.join(ROOT, 'backend', 'package.json'));
const INDEX = path.join(ROOT, 'backend', 'src', 'routes', 'index.ts');

type Row = Record<string, any>;
const S: {
  tables: Record<string, Row[]>;
  versionLoads: string[];
  downloads: string[];
  crewCalls: Array<{ input: any; signal: AbortSignal | undefined }>;
  inserts: Array<{ table: string; row: any }>;
  runCrew: (input: any, deps: any) => Promise<{ reply: string; authorities: any[] }>;
} = {} as any;

function reset() {
  S.tables = {
    documents: [
      { id: 'docA', user_id: 'userA', project_id: null, filename: 'secret.docx', current_version_id: 'vA', status: 'ready' },
    ],
  };
  S.versionLoads = [];
  S.downloads = [];
  S.crewCalls = [];
  S.inserts = [];
  S.runCrew = async () => ({ reply: 'ok', authorities: [] });
}
reset();

/** Supabase stand-in: eq / in filters are honoured, single / maybeSingle give one row or null, writes are dropped. */
function fakeSupabase(): any {
  const chain = (table: string, filters: Array<[string, string, any]>, single: boolean): any =>
    new Proxy(function () {}, {
      get(_t, prop) {
        if (prop === 'then') {
          return (res: any, rej: any) => {
            const rows = (S.tables[table] ?? []).filter((r) =>
              filters.every(([kind, col, val]) => (kind === 'eq' ? r[col] === val : Array.isArray(val) && val.includes(r[col]))),
            );
            const data = single ? (rows[0] ?? null) : rows;
            return Promise.resolve({ data, error: null }).then(res, rej);
          };
        }
        if (prop === 'eq') return (c: string, v: any) => chain(table, [...filters, ['eq', c, v]], single);
        if (prop === 'in') return (c: string, v: any[]) => chain(table, [...filters, ['in', c, v]], single);
        if (prop === 'single' || prop === 'maybeSingle') return () => chain(table, filters, true);
        return () => chain(table, filters, single);
      },
    });
  return {
    from: (t: string) => {
      const base = chain(t, [], false);
      return new Proxy(base, {
        get(target, prop, recv) {
          if (prop === 'insert') {
            return (row: unknown) => {
              S.inserts.push({ table: t, row: JSON.parse(JSON.stringify(row)) });
              return target;
            };
          }
          return Reflect.get(target, prop, recv);
        },
      });
    },
  };
}

const STUBS: Record<string, any> = {
  '../crew/coordinator.js': { runCrew: (input: any, deps: any) => { S.crewCalls.push({ input, signal: deps?.signal }); return S.runCrew(input, deps); } },
  '../lib/documentVersions.js': {
    loadActiveVersion: async (id: string) => {
      S.versionLoads.push(id);
      return { storage_path: `bytes/${id}`, filename: 'secret.docx', file_type: 'docx' };
    },
  },
  '../lib/storage.js': {
    downloadFile: async (p: string) => {
      S.downloads.push(p);
      return null;
    },
  },
  '../lib/userSettings.js': { getUserModelSettings: async () => ({ tabular_model: 'stub', api_keys: {} }) },
};
const ModuleCtor: any = nodeRequire('module');
const origLoad = ModuleCtor._load;
ModuleCtor._load = function (request: string, parent: any, ...rest: unknown[]) {
  if (parent && parent.filename === INDEX && Object.prototype.hasOwnProperty.call(STUBS, request)) return STUBS[request];
  return origLoad.call(this, request, parent, ...rest);
};
const { buildRoutes } = nodeRequire(INDEX);
ModuleCtor._load = origLoad;

function handlerFor(router: any, routePath: string, method: 'post' | 'get' = 'post') {
  const layer = router.stack.find((l: any) => l.route && l.route.path === routePath && l.route.methods && l.route.methods[method]);
  assert.ok(layer, `no ${method.toUpperCase()} ${routePath}`);
  return layer.route.stack[layer.route.stack.length - 1].handle as (req: any, res: any) => Promise<void>;
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

function fakeRes(userId: string) {
  const r: any = { statusCode: 200, writes: [] as string[], ended: false, listeners: {} as Record<string, Array<() => void>>, closedAtWrite: -1 };
  r.status = (c: number) => ((r.statusCode = c), r);
  r.json = (b: unknown) => ((r.body = JSON.parse(JSON.stringify(b))), r);
  r.setHeader = () => r;
  r.flushHeaders = () => {};
  r.write = (s: unknown) => {
    r.writes.push(String(s));
    return true;
  };
  r.on = (ev: string, fn: () => void) => ((r.listeners[ev] ??= []).push(fn), r);
  r.end = () => ((r.ended = true), r);
  r.close = () => {
    r.closedAtWrite = r.writes.length;
    for (const fn of r.listeners.close ?? []) fn();
  };
  r.locals = { userId, userEmail: `${userId}@x.test` };
  return r;
}

const cases: Record<string, () => Promise<void>> = {};

function router() {
  return buildRoutes({
    anthropic: {} as any,
    supabase: fakeSupabase(),
    courtListenerToken: '',
  });
}

cases.crew_chat_document_ids_of_another_user_are_never_read = async () => {
  const res = fakeRes('userB');
  const req: any = { body: { userMessage: 'Summarise the attached document.', documentIds: ['docA'] }, headers: {}, params: {}, query: {} };
  await quiet(() => handlerFor(router(), '/crew/chat')(req, res));
  assert.deepEqual(S.versionLoads.filter((id) => id === 'docA'), [], "user B's request loaded the version of user A's document (documentIds are not owner-checked)");
  assert.deepEqual(S.downloads, [], "user B's request downloaded the bytes of user A's document");
  assert.equal(S.crewCalls.length, 1, 'harness: the crew was not reached, so the case proves nothing');
  assert.ok(!String(S.crewCalls[0].input.documentName ?? '').includes('secret.docx'), "user A's filename reached the crew prompt of user B");
};

cases.crew_chat_the_owner_can_still_attach_their_own_document = async () => {
  // Non-vacuity: the owner's request must still reach the document loader, or the case above proves a broken route.
  const res = fakeRes('userA');
  const req: any = { body: { userMessage: 'Summarise the attached document.', documentIds: ['docA'] }, headers: {}, params: {}, query: {} };
  await quiet(() => handlerFor(router(), '/crew/chat')(req, res));
  assert.ok(S.versionLoads.includes('docA'), "the owner's own document was not loaded; the ownership check is too strict (or the harness is broken)");
};

cases.crew_chat_nothing_is_sent_after_the_client_disconnects_and_the_fallback_model_call_is_skipped = async () => {
  const res = fakeRes('userB');
  let signalAbortedAtReturn: boolean | null = null;
  S.runCrew = async (_input, deps) => {
    res.close(); // the client leaves while the crew is running
    signalAbortedAtReturn = deps.signal?.aborted ?? null;
    return { reply: '', authorities: [] }; // "no crew": the route would now call completeText
  };
  const req: any = { body: { userMessage: 'Hello there, please help.' }, headers: {}, params: {}, query: {} };
  await quiet(() => handlerFor(router(), '/crew/chat')(req, res));
  assert.equal(signalAbortedAtReturn, true, "runCrew's signal was not aborted by the client disconnect");
  assert.equal(res.writes.length, res.closedAtWrite, `bytes were written after the client left: ${JSON.stringify(res.writes.slice(res.closedAtWrite)).slice(0, 300)}`);
  assert.equal(res.ended, true, 'the response was not ended');
};

cases.crew_chat_a_throwing_crew_after_disconnect_writes_nothing = async () => {
  const res = fakeRes('userB');
  S.runCrew = async () => {
    res.close();
    throw new Error('Stream aborted.');
  };
  const req: any = { body: { userMessage: 'Hello there, please help.' }, headers: {}, params: {}, query: {} };
  await quiet(() => handlerFor(router(), '/crew/chat')(req, res));
  assert.equal(res.writes.length, res.closedAtWrite, `bytes were written after the client left: ${JSON.stringify(res.writes.slice(res.closedAtWrite)).slice(0, 300)}`);
  assert.equal(res.ended, true);
};

// GET /analytics re-checks every stored extraction. The check runs over JSON.stringify of the row, where a newline inside a string is
// the two characters backslash-n, which Gate 1 does not read as whitespace; the page renders the real newline. A cite split between
// its volume and its reporter by a newline must still withhold the row. (Real Gate 1; the cite does not exist in the fixture.)
cases.analytics_a_stored_row_with_a_cite_split_by_a_newline_is_withheld_on_read = async () => {
  S.tables.case_intelligence = [
    {
      id: 'ci1', user_id: 'userB', document_id: 'd1', project_id: null, caption: 'Roe v. Doe',
      entities: [{ name: 'Judge Roe', role: 'judge', note: 'See Doe v. Roe, 999\nSo. 3d 999 (Fla. 2015).' }],
      allegations: [], defenses: [], authorities: [], rarity: null, defense_summary: 'A summary.',
      updated_at: '2026-01-01T00:00:00.000Z',
    },
  ];
  const res = fakeRes('userB');
  const req: any = { body: {}, headers: {}, params: {}, query: {} };
  await quiet(() => handlerFor(router(), '/analytics', 'get')(req, res));
  assert.ok(res.body, 'no body');
  const blob = JSON.stringify(res.body);
  assert.ok(!/999/.test(blob), `a stored extraction with a fabricated cite split by a newline was returned: ${blob.slice(0, 200)}`);
};

// POST /council saves the session under the projectId in the request body. A project the caller does not own must not receive it
// (the text is gated, but it is still a write into another user's matter, and GET /council/:id then serves it to that user).
cases.council_does_not_save_a_session_under_a_project_the_caller_does_not_own = async () => {
  S.tables.projects = [{ id: 'projA', user_id: 'userA', name: 'A matter' }];
  const gen = { generate: async (_a: unknown) => 'Stub advisor text about the duty of care.' };
  const anthropic: any = { messages: { create: async () => ({ content: [{ type: 'text', text: 'Stub text about the duty of care.' }] }) } };
  const routerB = buildRoutes({ anthropic, gemini: gen, deepseek: gen, kimi: gen, supabase: fakeSupabase(), courtListenerToken: '' } as any);
  const res = fakeRes('userB');
  const req: any = { body: { rawQuestion: 'Should we pursue the duty of care claim against the landlord?', projectId: 'projA' }, headers: {}, params: {}, query: {} };
  await quiet(() => handlerFor(routerB, '/council')(req, res));
  assert.equal(res.statusCode, 200, `council status ${res.statusCode}: the harness did not reach the save`);
  assert.deepEqual(
    S.inserts.filter((i) => i.table === 'llm_council_sessions'),
    [],
    "user B saved a council session under user A's project",
  );
};

// Object keys of a stored extraction are returned with the row as well.
cases.analytics_a_cite_in_an_object_key_of_a_stored_row_is_withheld_on_read = async () => {
  S.tables.case_intelligence = [
    {
      id: 'ci2', user_id: 'userB', document_id: 'd2', project_id: null, caption: 'Roe v. Doe',
      entities: [{ name: 'Judge Roe', role: 'judge', 'Doe v. Roe, 999 So. 3d 999 (Fla. 2015)': 'x' }],
      allegations: [], defenses: [], authorities: [], rarity: null, defense_summary: 'A summary.',
      updated_at: '2026-01-01T00:00:00.000Z',
    },
  ];
  const res = fakeRes('userB');
  await quiet(() => handlerFor(router(), '/analytics', 'get')({ body: {}, headers: {}, params: {}, query: {} } as any, res));
  assert.ok(res.body, 'no body');
  assert.ok(!/999 So\. 3d 999/.test(JSON.stringify(res.body)), 'a fabricated cite stored as an object key was returned');
};

(async () => {
  const results: Record<string, string | null> = {};
  for (const [name, fn] of Object.entries(cases)) {
    reset();
    try {
      await fn();
      results[name] = null;
    } catch (e: any) {
      results[name] = String(e?.stack ?? e?.message ?? e).slice(0, 1500);
    }
  }
  process.stdout.write(`${JSON.stringify({ results })}\n`, () => process.exit(0));
})();
