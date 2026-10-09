// edit_document with the REAL tracked-changes engine (docxTrackedChanges.ts) and a stub Gate 1 verifier.
// Shows (1) what the applied changes' contextBefore / contextAfter really are, (2) that the second gate pass sees the
// text really next to each change, and (3) that the user's own text elsewhere in the document is not gated.
// Run by test_doc_write_engine.py under backend's tsx. Prints {caseName: null | "failure text"}.

import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import path from 'node:path';

const ROOT = process.cwd();
const nodeRequire = createRequire(path.join(ROOT, 'backend', 'package.json'));
const CHAT_TOOLS = path.join(ROOT, 'backend', 'src', 'lib', 'chatTools.ts');
const GUARD_PATH = path.join(ROOT, 'backend', 'src', 'middleware', 'hallucination_guard.ts');
const DTC_PATH = path.join(ROOT, 'backend', 'src', 'lib', 'docxTrackedChanges.ts');
const SRC_PATH = 'documents/u1/d1/a.docx';

const FAB_CORE = '999 So. 3d 999';
const SMITH = 'Smith v. State, 100 So. 3d 200 (Fla. 2012)';
const CLEAN = { verdicts: [], hasVetoes: false, hasConditional: false };
const VETOED = {
  verdicts: [{ citation: 'x', status: 'vetoed', gate1_existence: false, gate2_quote_accuracy: null, gate3_currency: null, gate4_jurisdiction_fit: null, notes: [] }],
  hasVetoes: true,
  hasConditional: false,
};
const squash = (t: string) => t.replace(/\s+/g, ' ');

const S: any = {};
function reset() {
  S.verified = [];
  S.uploads = [];
  S.files = new Map();
  S.active = SRC_PATH;
  S.timeline = [];
  S.writes = [];
  // Vetoes any text where a volume other than the real one sits in front of "So. 3d".
  S.verify = (t: string) => (/\b999 So\. 3d/.test(squash(t)) ? VETOED : CLEAN);
}
reset();

const realGuard = nodeRequire(GUARD_PATH);
const STUBS: Record<string, any> = {
  './storage': {
    uploadFile: async (key: string, bytes: any) => {
      S.timeline.push('upload');
      const copy = Buffer.from(new Uint8Array(bytes));
      S.uploads.push(key);
      S.files.set(key, copy);
      if (key.includes('/edits/')) S.active = key;
    },
    downloadFile: async (p: string) => {
      const b = S.files.get(p);
      return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength);
    },
    generatedDocKey: (u: string, d: string, f: string) => `generated/${u}/${d}/${f}`,
    storageKey: (u: string, d: string, f: string) => `documents/${u}/${d}/${f}`,
  },
  './convert': { convertedPdfKey: (u: string, d: string) => `pdf/${u}/${d}.pdf` },
  './supabase': { createServerSupabase: () => S.db },
  './downloadTokens': { buildDownloadUrl: (k: string, f: string) => `https://dl.test/${k}?f=${encodeURIComponent(f)}` },
  './documentVersions': {
    attachActiveVersionPaths: async () => {},
    loadActiveVersion: async () => ({ storage_path: S.active, filename: 'a.docx', pdf_storage_path: null, file_type: 'docx', size_bytes: 3, page_count: 1 }),
  },
  './courtlistener': {},
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
  './mcpConnectors': { buildUserMcpTools: async () => [], executeMcpToolCall: async () => ({}) },
  './llm': { streamChatWithTools: async () => {}, resolveModel: (m: unknown) => m ?? 'stub', DEFAULT_MAIN_MODEL: 'stub' },
  '../middleware/hallucination_guard': {
    ...realGuard,
    verifyDraftForSse: (text: string) => {
      S.timeline.push('verify');
      S.verified.push(text);
      return S.verify(text);
    },
  },
  // './docxTrackedChanges' is deliberately NOT stubbed.
};
const ModuleCtor: any = nodeRequire('module');
const origLoad = ModuleCtor._load;
ModuleCtor._load = function (request: string, parent: any, ...rest: unknown[]) {
  if (parent && parent.filename === CHAT_TOOLS && Object.prototype.hasOwnProperty.call(STUBS, request)) return STUBS[request];
  return origLoad.call(this, request, parent, ...rest);
};
const chatTools = nodeRequire(CHAT_TOOLS);
ModuleCtor._load = origLoad;
const dtc = nodeRequire(DTC_PATH);
const FIXED: string = chatTools.DOC_WRITE_REFUSED_MESSAGE;

function makeDb() {
  const chain = (state: any): any =>
    new Proxy(function () {}, {
      get(_t, prop) {
        if (prop === 'then') {
          return (res: any, rej: any) => {
            if (state.op !== 'select') {
              S.timeline.push(`write:${state.table}`);
              S.writes.push(`${state.table}:${state.op}`);
            }
            let data: any = null;
            if (state.op === 'select' && state.table === 'documents') data = { id: 'd1' };
            if (state.op === 'insert' && state.table === 'document_versions') data = { id: 'v1' };
            if (state.op === 'insert' && state.table === 'document_edits') data = (state.payload as any[]).map((r, i) => ({ id: `e${i}`, ...r }));
            return Promise.resolve({ data, error: null }).then(res, rej);
          };
        }
        if (prop === 'insert' || prop === 'update' || prop === 'delete' || prop === 'upsert') {
          return (payload?: unknown) => {
            state.op = prop === 'upsert' ? 'insert' : prop;
            state.payload = payload;
            return chain(state);
          };
        }
        return () => chain(state);
      },
    });
  return { from: (table: string) => chain({ table, op: 'select' }) };
}

async function makeDocx(paragraphs: string[]): Promise<Buffer> {
  const mod = nodeRequire('jszip');
  const JSZip = mod.default ?? mod;
  const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const zip = new JSZip();
  zip.file('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/></Types>');
  zip.file(
    'word/document.xml',
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' +
      paragraphs.map((p) => `<w:p><w:r><w:t xml:space="preserve">${esc(p)}</w:t></w:r></w:p>`).join('') +
      '</w:body></w:document>',
  );
  return zip.generateAsync({ type: 'nodebuffer' });
}

const call = (name: string, args: unknown, id = `call-${name}`) => ({ id, function: { name, arguments: JSON.stringify(args) } });

async function runEdit(paras: string[], edit: Record<string, unknown>) {
  reset();
  S.db = makeDb();
  S.files.set(SRC_PATH, await makeDocx(paras));
  const out = await chatTools.runToolCalls(
    [call('edit_document', { doc_id: 'doc-0', edits: [edit] })],
    new Map([['doc-0', { storage_path: SRC_PATH, file_type: 'docx', filename: 'a.docx' }]]),
    'u1',
    S.db,
    () => {},
    undefined,
    undefined,
    { 'doc-0': { document_id: 'd1', filename: 'a.docx' } },
    new Map(),
    'p1',
  );
  return out.toolResults.map((r: any) => String(r.content));
}

const FILLER = 'Plain words that cite nothing at all. '.repeat(40);
const cases: Record<string, () => Promise<void>> = {};

cases.the_applied_changes_carry_the_models_context_not_the_documents = async () => {
  // The engine copies edit.context_before / context_after into the change verbatim. With a context that is not in the
  // document it falls back to a looser anchor and still applies the edit, so the "context" on the change is the model's
  // claim, not what sits next to the change.
  const bytes = await makeDocx(['Alpha beta gamma delta.', `See ${SMITH}.`]);
  const r = await dtc.applyTrackedEdits(bytes, [
    { find: 'beta', replace: 'BETA', context_before: 'THIS IS NOT IN THE DOCUMENT', context_after: 'NEITHER IS THIS', reason: 'x' },
  ]);
  assert.equal(r.changes.length, 1, JSON.stringify(r.errors));
  assert.equal(r.changes[0].contextBefore, 'THIS IS NOT IN THE DOCUMENT');
  assert.equal(r.changes[0].contextAfter, 'NEITHER IS THIS');
  const text = await dtc.extractDocxBodyText(r.bytes);
  assert.ok(!text.includes('THIS IS NOT IN THE DOCUMENT'));
  assert.ok(text.includes('Alpha BETA gamma'));
};

cases.a_changed_volume_in_the_users_cite_is_gated_from_the_document = async () => {
  // Nothing the model wrote holds the cite: find "100", replace "999". The neighbourhood does.
  const c = await runEdit(['Intro.', `See ${SMITH}.`], { find: '100', replace: '999', context_before: '', context_after: '', reason: 'volume' });
  assert.deepEqual(c, [JSON.stringify({ ok: false, error: FIXED })]);
  assert.deepEqual(S.uploads, []);
  assert.deepEqual(S.writes, []);
  assert.equal(S.verified.length, 2);
  assert.ok(squash(S.verified[1]).includes('Smith v. State, 999 So. 3d 200 (Fla. 2012)'), S.verified[1]);
};

cases.the_users_own_bad_cite_elsewhere_does_not_block_an_edit = async () => {
  const c = await runEdit(
    [`Earlier the user wrote Doe v. Roe, ${FAB_CORE} (Fla. 2015).`, FILLER, 'The old clause ends here.'],
    { find: 'old clause', replace: 'new clause', context_before: 'The ', context_after: ' ends', reason: 'wording' },
  );
  assert.equal(JSON.parse(c[0]).ok, true, c[0]);
  assert.equal(S.uploads.length, 1);
  assert.equal(S.verified.length, 2);
  assert.ok(squash(S.verified[1]).includes('new clause ends here'));
  assert.ok(!S.verified[1].includes('999'));
};

cases.a_fragment_completed_by_the_text_next_to_it_is_gated = async () => {
  // Inserting "999" in front of the user's "So. 3d 999" yields the fabricated cite; the model's own strings hold only "999".
  const c = await runEdit(['See Doe v. Roe, ___ So. 3d 999 (Fla. 2015).'], { find: '___', replace: '999', context_before: '', context_after: '', reason: 'fill' });
  assert.deepEqual(c, [JSON.stringify({ ok: false, error: FIXED })]);
  assert.deepEqual(S.uploads, []);
  assert.ok(squash(S.verified[1]).includes(`Roe, ${FAB_CORE}`));
};

cases.a_clean_edit_next_to_a_clean_cite_is_written = async () => {
  const c = await runEdit(['Intro.', `See ${SMITH}.`], { find: 'Intro.', replace: 'Introduction.', context_before: '', context_after: '', reason: 'x' });
  assert.equal(JSON.parse(c[0]).ok, true, c[0]);
  assert.equal(S.uploads.length, 1);
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
  process.stdout.write('\nENGINE_REPORT=' + JSON.stringify(report) + '\n');
  process.exit(0);
})();
