// Behavioral cases for POST /crew/chat and POST /council (adversary vector 3, chat-route-verify).
//
// Run by test_route_behavior.py under backend's tsx, once per mode (ROUTE_CASES_MODE=crew | council). Two processes
// are needed because routes/index.ts reads MOCK_ENABLED once, at import: /crew/chat can only be driven without a hosted
// model through MOCK_CREW (MOCK_LLM=true), while /council must NOT be in mock mode or it never calls the model clients
// and never saves a session.
//
// What is real: buildRoutes(deps) from backend/src/routes/index.ts, the route handler pulled out of the express router
// stack (the handler after requireAuth), runLLMCouncil / runCrew's mock branch, finalizeCrewReply, gateCouncilOutput,
// verifyDraftForSse -> verifyDraft -> localGate1Text -> pipeline/gate1.py against the fixture database named by
// KINGSFIELD_FLORIDA_DB, and the CourtListener citation-lookup call.
// What is stubbed: req / res (fake objects that record writes, status and json), the Anthropic / Gemini / DeepSeek / Kimi
// clients handed to buildRoutes, Supabase (records inserts; "no row" for the cache), and global fetch (CourtListener
// answers "not found"; any other URL is recorded as a stray fetch and answered 404). No network, no model API.
//
// Prints one JSON line: { results: { caseName: null | "failure text" }, info: { ... } }.

import assert from 'node:assert/strict';
import { buildRoutes } from '../../backend/src/routes/index';
import { requireAuth } from '../../backend/src/middleware/auth';
import { MOCK_ENABLED, MOCK_CREW } from '../../backend/src/lib/mock-llm';
import {
  CLIENT_VERIFICATION_ERROR,
  GENERIC_ERROR_MESSAGE,
  VETO_WITHHELD_MESSAGE,
  WITHHELD_MESSAGE,
} from '../../backend/src/middleware/hallucination_guard';

const MODE = process.env.ROUTE_CASES_MODE;
const DONE = 'data: [DONE]\n\n';
const info: Record<string, unknown> = {};

// ---------- stubs ----------

const logs: string[] = [];

/** Run fn with console silenced; everything the route logged is kept in `logs`. */
async function quiet<T>(fn: () => Promise<T>): Promise<T> {
  const orig = { log: console.log, info: console.info, warn: console.warn, error: console.error };
  for (const k of Object.keys(orig) as Array<keyof typeof orig>) {
    (console as any)[k] = (...a: unknown[]) => {
      logs.push(`${k}: ${a.map((x) => String(x)).join(' ')}`);
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
    r.body = JSON.parse(JSON.stringify(b)); // what the client would receive
    return r;
  };
  r.setHeader = (k: string, v: unknown) => {
    r.headers[k] = v;
    return r;
  };
  r.flushHeaders = () => {};
  r.write = (s: unknown) => {
    r.writes.push(String(s));
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
  r.locals = {};
  return r;
}

/** Supabase stand-in: every chain resolves to "no row"; inserts are recorded; `from('sources')` can be made to throw. */
function makeSupabase(throwOnSources?: string) {
  const inserts: Array<{ table: string; row: any }> = [];
  const tables: string[] = [];
  const noRow = { data: null, error: null };
  const builder = (table: string): any =>
    new Proxy(function () {}, {
      get: (_t, prop) => {
        if (prop === 'then') return (res: any, rej: any) => Promise.resolve(noRow).then(res, rej);
        if (prop === 'insert') {
          return (row: unknown) => {
            inserts.push({ table, row: JSON.parse(JSON.stringify(row)) });
            return builder(table);
          };
        }
        return () => builder(table);
      },
    });
  const client: any = {
    from: (t: string) => {
      tables.push(t);
      if (throwOnSources && t === 'sources') throw new Error(throwOnSources);
      return builder(t);
    },
  };
  return { client, inserts, tables };
}

/** CourtListener citation-lookup answers "not found" for everything; any other URL is a stray fetch. */
function stubFetch() {
  const clCalls: string[] = [];
  const stray: string[] = [];
  const real = globalThis.fetch;
  globalThis.fetch = (async (input: any, init?: any) => {
    const url = String(typeof input === 'string' ? input : (input?.url ?? input));
    if (/\/citation-lookup\/?(?:\?.*)?$/.test(url)) {
      let text = '';
      try {
        text = String(JSON.parse(init?.body ?? '{}').text ?? '');
      } catch {
        /* keep '' */
      }
      clCalls.push(text);
      return new Response(JSON.stringify([{ citation: text, status: 404, clusters: [] }]), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }
    stray.push(url);
    return new Response('not found', { status: 404 });
  }) as typeof fetch;
  return { clCalls, stray, restore: () => { globalThis.fetch = real; } };
}

/** The route handler that runs after requireAuth, taken from the real express router stack. */
function findHandler(router: any, routePath: string) {
  const layer = router.stack.find((l: any) => l.route && l.route.path === routePath && l.route.methods && l.route.methods.post);
  assert.ok(layer, `buildRoutes() has no POST ${routePath} route`);
  const stack = layer.route.stack;
  assert.ok(stack.length >= 2, `POST ${routePath}: expected requireAuth plus a handler, found ${stack.length} layer(s)`);
  assert.equal(stack[0].handle, requireAuth, `POST ${routePath}: requireAuth is not the first layer`);
  return stack[stack.length - 1].handle as (req: any, res: any, next: any) => Promise<void>;
}

async function call(handler: (req: any, res: any, next: any) => Promise<void>, body: unknown) {
  const req: any = { body, headers: {}, params: {}, query: {} };
  const res = fakeRes();
  await quiet(() => handler(req, res, () => { throw new Error('harness: next() was called'); }));
  return res;
}

function leakCheck(blob: string, needles: string[], label: string) {
  for (const n of needles) assert.ok(!blob.includes(n), `${label}: "${n}" reached the client or the saved row`);
}

// Two fixed strings a failing dependency would put in an error: neither may ever reach a client.
const RAW = 'SQLITE_CANTOPEN: unable to open /Users/x/kingsfield_florida.db while checking; CourtListener 503 token=abc123';
const RAW_LEAKS = ['SQLITE', 'CANTOPEN', 'kingsfield_florida', 'token=abc', '/Users/x'];
const FED = 'United States v. Perez, 600 F.3d 100 (11th Cir. 2010)';
const FED_LEAKS = ['Perez', '600 F.3d', '11th Cir'];

const cases: Record<string, () => Promise<void>> = {};

// =====================================================================================================
// POST /crew/chat   (MOCK_LLM=true: the handler uses MOCK_CREW.reply, then the real Gate 1 finalizer)
// =====================================================================================================

function sseOf(res: any): any[] {
  const out: any[] = [];
  for (const w of res.writes as string[]) {
    if (w === DONE) {
      out.push({ type: '[DONE]' });
      continue;
    }
    if (w.startsWith(':')) continue; // keepalive comment
    const m = /^data: ([^\n]*)\n\n$/.exec(w);
    assert.ok(m, `a write that is neither a data line nor a keepalive: ${JSON.stringify(w.slice(0, 120))}`);
    out.push(JSON.parse(m![1]));
  }
  return out;
}

/** The SSE shape of a withheld /crew/chat reply: one fixed message, one verification record, [DONE]. Returns the record. */
function assertCrewWithheld(res: any, message: string, label: string, leaks: string[]) {
  assert.equal(res.statusCode, 200, `${label}: status`);
  assert.equal(res.body, undefined, `${label}: a JSON body was sent on the SSE route`);
  assert.equal(res.ended, true, `${label}: the response was never ended`);
  assert.equal(res.headers['Content-Type'], 'text/event-stream', `${label}: not an SSE response`);
  const ev = sseOf(res);
  const types = ev.map((e) => e.type);
  for (const t of types) {
    assert.ok(['content_delta', 'verification', 'citations', '[DONE]'].includes(t), `${label}: unexpected event type ${t} (sent: ${types.join(',')})`);
  }
  assert.equal(types[types.length - 1], '[DONE]', `${label}: [DONE] is not last (sent: ${types.join(',')})`);
  assert.equal(types.filter((t) => t === '[DONE]').length, 1, `${label}: more than one [DONE]`);
  for (const e of ev) if (e.type === 'citations') assert.deepEqual(e.citations, [], `${label}: a citations event carried entries`);
  const deltaText = ev.filter((e) => e.type === 'content_delta').map((e) => e.text).join('');
  assert.equal(deltaText, message, `${label}: the text sent is not the fixed withheld message`);
  const vers = ev.filter((e) => e.type === 'verification');
  assert.equal(vers.length, 1, `${label}: expected exactly one verification event, got ${vers.length}`);
  assert.ok(types.lastIndexOf('content_delta') < types.indexOf('verification'), `${label}: verification must follow the text`);
  assert.ok(types.indexOf('verification') < types.indexOf('[DONE]'), `${label}: verification must precede [DONE]`);
  assert.equal(vers[0].hasVetoes, true, `${label}: the verification event does not say hasVetoes`);
  for (const v of vers[0].verdicts) {
    if (v.status !== 'verified' && v.status !== 'conditional') assert.equal(v.citation, '', `${label}: a non-ok verdict carries citation text`);
  }
  leakCheck(res.writes.join(''), leaks, label);
  return vers[0];
}

if (MODE === 'crew') {
  const MOCK_REPLY = MOCK_CREW.reply;
  const MOCK_LEAKS = ['Mock v. Reality', 'Mock Cir', '123 F.3d', 'F.3d', 'Bottom line', 'Stub response', 'MOCK', 'Reality'];

  const crewRun = async (reply: unknown, supabase: ReturnType<typeof makeSupabase>) => {
    const f = stubFetch();
    (MOCK_CREW as any).reply = reply;
    try {
      const handler = findHandler(
        buildRoutes({ anthropic: {} as any, supabase: supabase.client, courtListenerToken: '' }),
        '/crew/chat',
      );
      const res = await call(handler, { userMessage: 'Does the stub answer survive Gate 1 before it is sent?' });
      return { res, f };
    } finally {
      (MOCK_CREW as any).reply = MOCK_REPLY;
      f.restore();
    }
  };

  cases.crew_chat_vetoed_mock_reply_is_withheld_whole_with_a_recorded_veto = async () => {
    assert.ok(
      MOCK_REPLY.includes('Mock v. Reality') && MOCK_REPLY.includes('123 F.3d 456 (Mock Cir. 2024)'),
      'MOCK_CREW.reply no longer carries the fabricated federal cite; the case needs updating',
    );
    const sb = makeSupabase();
    const { res, f } = await crewRun(MOCK_REPLY, sb);
    const record = assertCrewWithheld(res, VETO_WITHHELD_MESSAGE, 'crew veto', MOCK_LEAKS);
    assert.equal(record.error, undefined, 'a Gate 1 veto must not be reported as a verification error');
    assert.ok(record.verdicts.length >= 1, 'the veto record carries no verdict');
    assert.deepEqual(f.stray, [], `unexpected fetch beyond citation-lookup: ${f.stray.join(', ')}`);
    assert.deepEqual(sb.inserts, [], 'something was inserted while the reply was being verified');
    info.crew_veto = { citationLookupCalls: f.clCalls.length, supabaseTables: sb.tables, verdicts: record.verdicts.map((v: any) => v.status) };
  };

  cases.crew_chat_clean_reply_is_sent_unchanged_with_a_clean_record = async () => {
    const CLEAN =
      'The Crew replied with a plain answer. The filing deadline depends on the court rules, so read the local rules ' +
      'and the scheduling order before you file anything.';
    const sb = makeSupabase();
    const { res, f } = await crewRun(CLEAN, sb);
    assert.equal(res.statusCode, 200);
    assert.equal(res.ended, true);
    const ev = sseOf(res);
    const types = ev.map((e) => e.type);
    assert.equal(types[types.length - 1], '[DONE]');
    assert.equal(ev.filter((e) => e.type === 'content_delta').map((e) => e.text).join(''), CLEAN, 'a clean reply was altered or withheld');
    const vers = ev.filter((e) => e.type === 'verification');
    assert.equal(vers.length, 1);
    assert.equal(vers[0].hasVetoes, false);
    assert.equal(vers[0].error, undefined);
    assert.ok(!res.writes.join('').includes(WITHHELD_MESSAGE) && !res.writes.join('').includes(VETO_WITHHELD_MESSAGE), 'a clean reply carries a withheld message');
    for (const e of ev) if (e.type === 'citations') assert.deepEqual(e.citations, []);
    assert.deepEqual(f.stray, []);
    info.crew_clean = { types };
  };

  cases.crew_chat_gate_error_withholds_with_the_generic_message_and_no_raw_error = async () => {
    const sb = makeSupabase(RAW); // the cache read for the federal cite throws: verifyDraftForSse returns an error result
    const { res, f } = await crewRun(`The panel followed ${FED} on this point.`, sb);
    const record = assertCrewWithheld(res, WITHHELD_MESSAGE, 'crew gate error', [...RAW_LEAKS, ...FED_LEAKS, 'Verification failed:']);
    assert.equal(record.error, CLIENT_VERIFICATION_ERROR, 'the client-safe error text is not the fixed one');
    assert.deepEqual(f.stray, []);
    assert.deepEqual(sb.inserts, []);
    assert.ok(sb.tables.includes('sources'), 'the gate never reached the stubbed cache read, so the error path was not exercised');
    info.crew_gate_error = { supabaseTables: sb.tables, logged: logs.length };
  };

  cases.crew_chat_malformed_reply_withholds_with_the_generic_message = async () => {
    const sb = makeSupabase();
    const { res } = await crewRun(12345, sb);
    const record = assertCrewWithheld(res, WITHHELD_MESSAGE, 'crew malformed reply', ['12345']);
    assert.equal(record.error, CLIENT_VERIFICATION_ERROR);
  };
}

// =====================================================================================================
// POST /council   (MOCK_LLM unset: the handler calls the stubbed model clients, then the real gate)
// =====================================================================================================

const FRAMED = 'Stub framed question about a duty of care claim.';
const ADV_CLAUDE = 'Stub claude advisor text about the duty of care.';
const ADV_GEMINI = 'Stub gemini advisor text about causation.';
const ADV_KIMI = 'Stub kimi advisor text about damages.';
const ADV_DEEP_CLEAN = 'Stub deepseek advisor text about notice.';
const ADV_DEEP_BAD =
  'Stub deepseek advisor text. In Doe v. Roe, 999 So. 3d 999 (Fla. 2015), the court held that the zebra doctrine controls.';
const REVIEW = 'Stub reviewer text comparing the responses.';
const CHAIR = 'Stub chairman verdict on the duty of care claim.';
const STUB_TEXTS = [FRAMED, ADV_CLAUDE, ADV_GEMINI, ADV_KIMI, ADV_DEEP_CLEAN, REVIEW, CHAIR, 'Stub ', 'zebra', 'court held'];
const COUNCIL_ROLES = ['contrarian', 'first_principles', 'expansionist', 'outsider', 'executor'];
const QUESTION = 'Should we pursue the duty of care claim against the landlord?';

function councilClients(deepseekText: string, anthropicThrows?: string) {
  const calls = { anthropic: 0, gemini: 0, deepseek: 0, kimi: 0 };
  const anthropic: any = {
    messages: {
      create: async (args: any) => {
        calls.anthropic++;
        if (anthropicThrows) throw new Error(anthropicThrows);
        const user = String(args?.messages?.[0]?.content ?? '');
        const text = user.startsWith('RAW QUESTION:') ? FRAMED
          : user.startsWith('FRAMED QUESTION:') ? CHAIR
          : user.startsWith('QUESTION:') ? REVIEW
          : ADV_CLAUDE;
        return { content: [{ type: 'text', text }] };
      },
    },
  };
  const gen = (key: 'gemini' | 'deepseek' | 'kimi', text: string) => ({
    generate: async (_a: unknown) => {
      calls[key]++;
      return text;
    },
  });
  return {
    calls,
    deps: { anthropic, gemini: gen('gemini', ADV_GEMINI), deepseek: gen('deepseek', deepseekText), kimi: gen('kimi', ADV_KIMI) },
  };
}

async function councilRun(deepseekText: string, supabase: ReturnType<typeof makeSupabase>, body: Record<string, unknown>, anthropicThrows?: string) {
  const f = stubFetch();
  const clients = councilClients(deepseekText, anthropicThrows);
  try {
    const handler = findHandler(
      buildRoutes({ ...clients.deps, supabase: supabase.client, courtListenerToken: '' } as any),
      '/council',
    );
    const res = await call(handler, { rawQuestion: QUESTION, ...body });
    return { res, f, calls: clients.calls };
  } finally {
    f.restore();
  }
}

/** The withheld /council response: every text field is the fixed message, five seats, five reviews, and the record says so. */
function assertCouncilWithheld(body: any, message: string, label: string) {
  assert.equal(body.withheld, true, `${label}: withheld flag`);
  assert.equal(body.framedQuestion, message, `${label}: framedQuestion`);
  assert.equal(body.chairmanVerdict, message, `${label}: chairmanVerdict`);
  assert.equal(body.advisors.length, 5, `${label}: advisor seats`);
  for (const a of body.advisors) {
    assert.equal(a.text, message, `${label}: advisor ${a.role} text`);
    assert.deepEqual(a.model, { provider: 'withheld', model: 'withheld' }, `${label}: advisor ${a.role} still names a real model`);
  }
  assert.equal(body.reviewers.length, 5, `${label}: reviewer seats`);
  for (const r of body.reviewers) assert.equal(r.text, message, `${label}: reviewer ${r.reviewerRole} text`);
  assert.equal(body.verification.hasVetoes, true, `${label}: the verification record does not say hasVetoes`);
  for (const v of body.verification.verdicts) {
    if (v.status !== 'verified' && v.status !== 'conditional') assert.equal(v.citation, '', `${label}: a non-ok verdict carries citation text`);
  }
}

function assertSavedRowIsWithheld(sb: ReturnType<typeof makeSupabase>, projectId: string, message: string, leaks: string[], label: string) {
  assert.deepEqual(sb.inserts.map((i) => i.table), ['llm_council_sessions'], `${label}: unexpected inserts: ${JSON.stringify(sb.inserts.map((i) => i.table))}`);
  const row = sb.inserts[0].row;
  assert.equal(row.project_id, projectId, `${label}: project_id`);
  assert.equal(row.framed_question, message, `${label}: saved framed_question`);
  assert.equal(row.chairman_verdict, message, `${label}: saved chairman_verdict`);
  assert.equal(row.advisors.length, 5);
  for (const a of row.advisors) assert.equal(a.text, message, `${label}: saved advisor text`);
  assert.equal(row.reviewers.length, 5);
  for (const r of row.reviewers) assert.equal(r.text, message, `${label}: saved reviewer text`);
  leakCheck(JSON.stringify(row), leaks, `${label} (saved row)`);
}

if (MODE === 'council') {
  cases.council_vetoed_advisor_withholds_the_whole_output_and_saves_only_the_withheld_text = async () => {
    const sb = makeSupabase();
    const { res, f, calls } = await councilRun(ADV_DEEP_BAD, sb, { projectId: 'proj-1' });
    assert.equal(res.statusCode, 200, 'status');
    assert.ok(res.body, 'no JSON body was sent');
    const leaks = ['Doe v. Roe', 'Roe', '999 So', 'So. 3d', ...STUB_TEXTS];
    assertCouncilWithheld(res.body, VETO_WITHHELD_MESSAGE, 'council veto');
    assert.equal(res.body.verification.error, undefined, 'a Gate 1 veto must not be reported as a verification error');
    assert.ok(res.body.verification.verdicts.length >= 1, 'the veto record carries no verdict');
    leakCheck(JSON.stringify(res.body), leaks, 'council veto');
    assert.deepEqual([calls.gemini, calls.deepseek, calls.kimi], [1, 1, 1], `the stubbed provider clients were not all used: ${JSON.stringify(calls)}`);
    assertSavedRowIsWithheld(sb, 'proj-1', VETO_WITHHELD_MESSAGE, leaks, 'council veto');
    assert.deepEqual(f.stray, [], `unexpected fetch: ${f.stray.join(', ')}`);
    info.council_veto = { calls, citationLookupCalls: f.clCalls.length, verdicts: res.body.verification.verdicts.map((v: any) => v.status) };
  };

  cases.council_vetoed_advisor_without_a_project_id_saves_nothing = async () => {
    const sb = makeSupabase();
    const { res } = await councilRun(ADV_DEEP_BAD, sb, {});
    assertCouncilWithheld(res.body, VETO_WITHHELD_MESSAGE, 'council veto, no project');
    leakCheck(JSON.stringify(res.body), ['Doe v. Roe', '999 So', 'So. 3d', 'zebra', ...STUB_TEXTS], 'council veto, no project');
    assert.deepEqual(sb.inserts, [], 'a session was saved without a projectId');
  };

  cases.council_clean_output_passes_through_unchanged_and_is_saved_as_sent = async () => {
    const sb = makeSupabase();
    const { res, f } = await councilRun(ADV_DEEP_CLEAN, sb, { projectId: 'proj-2' });
    assert.equal(res.statusCode, 200);
    const b = res.body;
    assert.equal(b.withheld, false, 'a clean council output was withheld');
    assert.equal(b.framedQuestion, FRAMED);
    assert.equal(b.chairmanVerdict, CHAIR);
    const byRole: Record<string, string> = {};
    for (const a of b.advisors) byRole[a.role] = a.text;
    assert.deepEqual(byRole, {
      contrarian: ADV_CLAUDE, first_principles: ADV_DEEP_CLEAN, expansionist: ADV_GEMINI, outsider: ADV_KIMI, executor: ADV_CLAUDE,
    });
    assert.deepEqual(b.advisors.map((a: any) => a.role), COUNCIL_ROLES);
    assert.deepEqual(b.reviewers.map((r: any) => r.text), [REVIEW, REVIEW, REVIEW, REVIEW, REVIEW]);
    assert.equal(b.verification.hasVetoes, false);
    assert.equal(b.verification.error, undefined);
    assert.ok(!JSON.stringify(b).includes(VETO_WITHHELD_MESSAGE) && !JSON.stringify(b).includes(WITHHELD_MESSAGE), 'a clean output carries a withheld message');
    assert.deepEqual(sb.inserts.map((i) => i.table), ['llm_council_sessions']);
    const row = sb.inserts[0].row;
    assert.equal(row.project_id, 'proj-2');
    assert.equal(row.framed_question, b.framedQuestion);
    assert.equal(row.chairman_verdict, b.chairmanVerdict);
    assert.deepEqual(row.advisors, b.advisors, 'the saved advisors differ from the ones sent');
    assert.deepEqual(row.reviewers, b.reviewers, 'the saved reviewers differ from the ones sent');
    assert.deepEqual(f.stray, []);
  };

  cases.council_gate_error_withholds_with_the_generic_message_and_leaks_no_raw_error = async () => {
    const sb = makeSupabase(RAW); // the cache read for the federal cite throws: verifyDraftForSse returns an error result
    const { res, f } = await councilRun(`A federal panel followed ${FED} on this point.`, sb, { projectId: 'proj-3' });
    assert.equal(res.statusCode, 200);
    assertCouncilWithheld(res.body, WITHHELD_MESSAGE, 'council gate error');
    assert.equal(res.body.verification.error, CLIENT_VERIFICATION_ERROR, 'the client-safe error text is not the fixed one');
    const leaks = [...RAW_LEAKS, ...FED_LEAKS, 'Verification failed:', ...STUB_TEXTS];
    leakCheck(JSON.stringify(res.body), leaks, 'council gate error');
    assert.ok(sb.tables.includes('sources'), 'the gate never reached the stubbed cache read, so the error path was not exercised');
    // The session insert goes through llm_council_sessions only; the throwing table is "sources".
    assertSavedRowIsWithheld(sb, 'proj-3', WITHHELD_MESSAGE, leaks, 'council gate error');
    assert.deepEqual(f.stray, []);
  };

  cases.council_model_failure_sends_the_fixed_500_and_saves_nothing = async () => {
    const sb = makeSupabase();
    const { res } = await councilRun(ADV_DEEP_CLEAN, sb, { projectId: 'proj-4' }, RAW);
    assert.equal(res.statusCode, 500);
    assert.deepEqual(res.body, { error: GENERIC_ERROR_MESSAGE });
    leakCheck(JSON.stringify(res.body), RAW_LEAKS, 'council model failure');
    assert.deepEqual(sb.inserts, [], 'a session was saved after the model run failed');
  };
}

// ---------- run ----------

async function main() {
  const results: Record<string, string | null> = {};
  try {
    if (MODE !== 'crew' && MODE !== 'council') throw new Error(`ROUTE_CASES_MODE must be crew or council, got ${String(MODE)}`);
    assert.ok(process.env.KINGSFIELD_FLORIDA_DB, 'KINGSFIELD_FLORIDA_DB is not set: the real gate needs the fixture database');
    assert.equal(MOCK_ENABLED, MODE === 'crew', `MOCK_ENABLED is ${MOCK_ENABLED} in ${MODE} mode (the harness env was overridden?)`);
    for (const [name, fn] of Object.entries(cases)) {
      logs.length = 0;
      try {
        await fn();
        results[name] = null;
      } catch (e: any) {
        results[name] = String(e?.message ?? e).slice(0, 1200);
      }
    }
  } catch (e: any) {
    results.__harness_setup__ = String(e?.message ?? e).slice(0, 1200);
  }
  const text = JSON.stringify({ mode: MODE, results, info });
  process.stdout.write(`${text}\n`, () => process.exit(0));
}

void main();
