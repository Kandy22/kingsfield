// Snapshot CourtListener's /courts list into backend/data/courtlistener-courts.json.
//
// The v4 /courts endpoint is hard-capped at page_size=20 AND throttled at
// ~5 requests/min (even authenticated), so the full list (~3,400 courts)
// cannot be fetched at request time — it takes ~35 minutes of polite paging.
// Run this script to (re)build the snapshot; GET /api/research/courts serves it.
// Court lists change rarely (a few times a year) — re-run when CL announces changes.
//
// Usage: node scripts/fetch-courts.mjs   (reads COURTLISTENER_TOKEN from backend/.env)
// Resumable: crashes/5xx checkpoint progress to a .checkpoint.json next to OUT
// and pick up from there on the next run instead of starting over.

import { readFileSync, writeFileSync, mkdirSync, existsSync, unlinkSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const envFile = readFileSync(join(here, "..", ".env"), "utf8");
const token = envFile.match(/^COURTLISTENER_TOKEN=(.+)$/m)?.[1]?.trim();
if (!token) {
  console.error("COURTLISTENER_TOKEN not found in backend/.env");
  process.exit(1);
}

const OUT = join(here, "..", "data", "courtlistener-courts.json");
const CHECKPOINT = join(here, "..", "data", ".courtlistener-courts.checkpoint.json");
// 5/min shared throttle: pace at ~3/min so interactive search (case-law page)
// keeps headroom while the crawl runs. Full crawl ≈ 60 min.
const DELAY_MS = 20_000;
const MAX_5XX_RETRIES = 6; // exponential backoff: 5s,10s,20s,40s,80s,160s
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let url =
  "https://www.courtlistener.com/api/rest/v4/courts/?page_size=20" +
  "&fields=id,full_name,short_name,citation_string,jurisdiction,in_use";
let courts = [];
let page = 0;

if (existsSync(CHECKPOINT)) {
  const cp = JSON.parse(readFileSync(CHECKPOINT, "utf8"));
  courts = cp.courts;
  url = cp.next;
  page = cp.page;
  console.log(`resuming from checkpoint: page ${page}, ${courts.length} courts so far`);
}

function saveCheckpoint(nextUrl) {
  writeFileSync(CHECKPOINT, JSON.stringify({ courts, next: nextUrl, page }));
}

while (url) {
  let res;
  let attempt = 0;
  for (;;) {
    res = await fetch(url, { headers: { Authorization: `Token ${token}` } });
    if (res.status === 429) {
      const body = await res.json().catch(() => ({}));
      const wait = Number(body?.detail?.match(/(\d+) seconds/)?.[1] ?? 60) + 2;
      console.log(`throttled — waiting ${wait}s`);
      await sleep(wait * 1000);
      continue;
    }
    if (res.ok) break;
    if (res.status >= 500 && attempt < MAX_5XX_RETRIES) {
      const wait = 5 * 2 ** attempt;
      console.log(`CourtListener ${res.status} on page ${page + 1} — retrying in ${wait}s (attempt ${attempt + 1}/${MAX_5XX_RETRIES})`);
      await sleep(wait * 1000);
      attempt += 1;
      continue;
    }
    console.error(`CourtListener ${res.status} on page ${page + 1} — checkpointed, re-run to resume`);
    saveCheckpoint(url);
    process.exit(1);
  }
  const body = await res.json();
  for (const c of body.results ?? []) {
    courts.push({
      id: c.id,
      full_name: c.full_name ?? "",
      short_name: c.short_name ?? "",
      citation_string: c.citation_string ?? "",
      jurisdiction: c.jurisdiction ?? "",
      in_use: Boolean(c.in_use),
    });
  }
  page += 1;
  url = body.next;
  if (page % 10 === 0) {
    console.log(`page ${page} — ${courts.length} courts so far`);
    saveCheckpoint(url);
  }
  if (url) await sleep(DELAY_MS);
}

mkdirSync(dirname(OUT), { recursive: true });
writeFileSync(
  OUT,
  JSON.stringify({ fetched_at: new Date().toISOString(), count: courts.length, courts }, null, 1),
);
if (existsSync(CHECKPOINT)) unlinkSync(CHECKPOINT);
console.log(`wrote ${courts.length} courts to ${OUT}`);
