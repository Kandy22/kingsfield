// runCaseExtraction (backend/src/lib/caseIntelligence.ts): the model's extraction must pass Gate 1 BEFORE it is saved.
// The saved row feeds GET /analytics and the Analytics page; those re-check on read, but the requirement is gate-before-save.
//
// REAL: caseIntelligence.ts, mammoth (a tiny real .docx), the whole of hallucination_guard.ts, and the production Gate 1
// (verifyDraftForSse -> pipeline/gate1.py against KINGSFIELD_FLORIDA_DB). STUBBED: the model call, storage (the docx bytes),
// CourtListener, Supabase (a recording fake). Prints one JSON line: { results }.

import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import path from 'node:path';

const ROOT = process.cwd();
const nodeRequire = createRequire(path.join(ROOT, 'backend', 'package.json'));
const CI = path.join(ROOT, 'backend', 'src', 'lib', 'caseIntelligence.ts');

const S: { llm: () => string; upserts: any[] } = { llm: () => '{}', upserts: [] };

async function makeDocx(text: string): Promise<Buffer> {
  const mod = nodeRequire('jszip');
  const JSZip = mod.default ?? mod;
  const zip = new JSZip();
  zip.file('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>');
  zip.file('_rels/.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>');
  zip.file('word/document.xml', `<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>${text}</w:t></w:r></w:p></w:body></w:document>`);
  return zip.generateAsync({ type: 'nodebuffer' });
}

function fakeDb(): any {
  const chain = (table: string, op: string): any =>
    new Proxy(function () {}, {
      get(_t, prop) {
        if (prop === 'then') {
          return (res: any, rej: any) => {
            const data = table === 'documents' ? { id: 'd1', filename: 'a.docx', file_type: 'docx', current_version_id: 'v1', status: 'ready' } : null;
            return Promise.resolve({ data, error: null }).then(res, rej);
          };
        }
        if (prop === 'upsert') {
          return (row: unknown) => {
            S.upserts.push(JSON.parse(JSON.stringify(row)));
            return new Proxy(function () {}, {
              get(_t2, p2) {
                if (p2 === 'then') return (res: any, rej: any) => Promise.resolve({ data: S.upserts[S.upserts.length - 1], error: null }).then(res, rej);
                return () => chain(table, 'upsert');
              },
            });
          };
        }
        return () => chain(table, op);
      },
    });
  return { from: (t: string) => chain(t, 'select') };
}

const LONG = 'The plaintiff alleges that the defendant breached the lease by failing to maintain the premises. '.repeat(8);
const STUBS: Record<string, any> = {
  './supabase.js': { createServerSupabase: () => fakeDb() },
  './llm/index.js': { completeText: async () => S.llm() },
  './chatTools.js': {
    loadCurrentVersionBytes: async () => ({ bytes: await makeDocx(LONG), storage_path: 'p' }),
    extractPdfText: async () => '',
  },
  '../research/courtlistener.js': { citationLookup: async () => [] },
};
const ModuleCtor: any = nodeRequire('module');
const origLoad = ModuleCtor._load;
ModuleCtor._load = function (request: string, parent: any, ...rest: unknown[]) {
  if (parent && parent.filename === CI && Object.prototype.hasOwnProperty.call(STUBS, request)) return STUBS[request];
  return origLoad.call(this, request, parent, ...rest);
};
const ci = nodeRequire(CI);
ModuleCtor._load = origLoad;

const extraction = (note: string) =>
  JSON.stringify({
    caption: 'Roe v. Doe',
    entities: [{ name: 'Judge Roe', role: 'judge', note }],
    allegations: [], defenses: [], authorities: [],
    rarity: { score: 10, label: 'routine', rationale: 'common' },
    defense_summary: 'A summary.',
  });

async function extract(note: string) {
  S.upserts = [];
  S.llm = () => extraction(note);
  const orig = { log: console.log, warn: console.warn, error: console.error };
  console.log = console.warn = console.error = () => {};
  try {
    return await ci.runCaseExtraction({ documentId: 'd1', userId: 'u1', model: 'stub', db: fakeDb() });
  } finally {
    Object.assign(console, orig);
  }
}

const cases: Record<string, () => Promise<void>> = {};

cases.control_a_clean_extraction_is_saved = async () => {
  const r = await extract('Presided over the matter.');
  assert.equal(r.ok, true, `control failed: ${JSON.stringify(r).slice(0, 200)}`);
  assert.equal(S.upserts.length, 1);
};

cases.a_fabricated_cite_is_not_saved = async () => {
  const r = await extract('See Doe v. Roe, 999 So. 3d 999 (Fla. 2015).');
  assert.equal(r.ok, false);
  assert.deepEqual(S.upserts, []);
};

// JSON.stringify(intel) spells a backspace as \b and other controls as \u00XX; on the page (and in the decoded string) the control
// character is dropped and the cite reads "999So. 3d 999". The gate must see the decoded string, so the row is not saved.
cases.a_cite_glued_by_a_control_character_is_not_saved = async () => {
  const leaks: string[] = [];
  for (const [label, ch] of [['backspace', '\b'], ['vertical tab', '\u000b'], ['unit separator', '\u001f'], ['newline', '\n'], ['tab', '\t']] as Array<[string, string]>) {
    const r = await extract(`See Doe v. Roe, 999${ch}So. 3d 999 (Fla. 2015).`);
    if (S.upserts.length) leaks.push(`${label}: saved (ok=${r.ok})`);
  }
  assert.ok(leaks.length === 0, `an extraction with a fabricated cite was saved: ${leaks.join('; ')}`);
};

// Object KEYS are saved with the row too (the model chooses the keys of every entity / allegation / authority object).
cases.a_cite_in_an_object_key_is_not_saved = async () => {
  S.upserts = [];
  const FAB = 'Doe v. Roe, 999 So. 3d 999 (Fla. 2015)';
  const obj = JSON.parse(extraction('Presided.'));
  obj.entities[0][FAB] = 'x';
  obj.rarity[FAB] = 'x';
  S.llm = () => JSON.stringify(obj);
  const r = await ci.runCaseExtraction({ documentId: 'd1', userId: 'u1', model: 'stub', db: fakeDb() });
  assert.ok(!S.upserts.some((u) => JSON.stringify(u).includes('999 So. 3d 999')), `a fabricated cite saved as an object key (ok=${r.ok})`);
};

// The unspaced / escaped forms must not survive either (strings only, no keys).
cases.escaped_separator_spellings_are_not_saved = async () => {
  const leaks: string[] = [];
  for (const sep of ['\\u000a', '\\x0a', '\\u0085', '\\u00a0', '\\xa0', '\\u0008', '\\b']) {
    S.upserts = [];
    await extract(`See Doe v. Roe, 999${sep}So. 3d 999 (Fla. 2015).`);
    if (S.upserts.length) leaks.push(sep);
  }
  assert.ok(leaks.length === 0, `saved with a fabricated cite split by a literal escape: ${leaks.join(' ')}`);
};

(async () => {
  const results: Record<string, string | null> = {};
  for (const [name, fn] of Object.entries(cases)) {
    try {
      await fn();
      results[name] = null;
    } catch (e: any) {
      results[name] = String(e?.stack ?? e?.message ?? e).slice(0, 700);
    }
  }
  process.stdout.write(`${JSON.stringify({ results })}\n`, () => process.exit(0));
})();
