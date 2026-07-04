// Snapshot CourtListener's /courts list into backend/data/courtlistener-courts.json.
//
// The v4 /courts endpoint is hard-capped at page_size=20 AND throttled at
// ~5 requests/min (even authenticated), so the full list (~3,400 courts)
// cannot be fetched at request time — it takes ~35 minutes of polite paging.
// Run this script to (re)build the snapshot; GET /api/research/courts serves it.
// Court lists change rarely (a few times a year) — re-run when CL announces changes.
//
// Usage: node scripts/fetch-courts.mjs   (reads COURTLISTENER_TOKEN from backend/.env)

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
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
// 5/min shared throttle: pace at ~3/min so interactive search (case-law page)
// keeps headroom while the crawl runs. Full crawl ≈ 60 min.
const DELAY_MS = 20_000;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let url =
  "https://www.courtlistener.com/api/rest/v4/courts/?page_size=20" +
  "&fields=id,full_name,short_name,citation_string,jurisdiction,in_use";
const courts = [];
let page = 0;

while (url) {
  const res = await fetch(url, { headers: { Authorization: `Token ${token}` } });
  if (res.status === 429) {
    const body = await res.json().catch(() => ({}));
    const wait = Number(body?.detail?.match(/(\d+) seconds/)?.[1] ?? 60) + 2;
    console.log(`throttled — waiting ${wait}s`);
    await sleep(wait * 1000);
    continue;
  }
  if (!res.ok) {
    console.error(`CourtListener ${res.status} on page ${page + 1} — aborting`);
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
  if (page % 10 === 0) console.log(`page ${page} — ${courts.length} courts so far`);
  url = body.next;
  if (url) await sleep(DELAY_MS);
}

mkdirSync(dirname(OUT), { recursive: true });
writeFileSync(
  OUT,
  JSON.stringify({ fetched_at: new Date().toISOString(), count: courts.length, courts }, null, 1),
);
console.log(`wrote ${courts.length} courts to ${OUT}`);
