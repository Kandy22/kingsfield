/**
 * CourtListener REST API v4 adapter.
 *
 * The Citation Lookup endpoint is the single highest-leverage tool in the
 * verification pipeline. Free Law Project (501(c)(3) nonprofit) explicitly
 * markets it as a guardrail against hallucinated citations.
 *
 * Auth: Bearer token. Rate limit: 5,000 queries/hour for authenticated users.
 * Docs: https://www.courtlistener.com/help/api/rest/
 */

const CL_BASE = 'https://www.courtlistener.com/api/rest/v4';

export interface CitationLookupHit {
  citation: string;
  status: 'matched' | 'ambiguous' | 'not-found';
  cluster_id?: number;
  case_name?: string;
  date_filed?: string;
  court?: string;
  url?: string;
  /** How many opinions cite this cluster — CL's citation_count. */
  citation_count?: number;
}

export interface OpinionCluster {
  id: number;
  case_name: string;
  date_filed: string;
  court: string;
  citations: Array<{ volume: number; reporter: string; page: number; type: number }>;
  sub_opinions: string[]; // URLs to opinion endpoints
  absolute_url: string;
}

export interface Opinion {
  id: number;
  cluster: string;
  type: string;
  html_with_citations: string; // recommended field
  plain_text?: string;
  download_url?: string;
}

function authHeaders(token: string) {
  return {
    Authorization: `Token ${token}`,
    'Content-Type': 'application/json',
  };
}

/**
 * Gate 1: existence check.
 *
 * Accepts either a single citation string ("424 U.S. 319") or a block of
 * draft text containing zero or more citations. Returns one hit per citation
 * found, with resolution status.
 *
 * If a hit returns status='not-found', the citation is presumed hallucinated
 * until proven otherwise.
 */
export async function citationLookup(
  textOrCitation: string,
  token: string,
): Promise<CitationLookupHit[]> {
  const res = await fetch(`${CL_BASE}/citation-lookup/`, {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify({ text: textOrCitation }),
  });
  if (!res.ok) {
    throw new Error(`CourtListener citation lookup failed: ${res.status} ${await res.text()}`);
  }
  const body = await res.json();
  // Normalize CL's response shape into our internal hit type.
  // CL v4 returns numeric HTTP status (200 = matched, 404 = not-found, etc.)
  // rather than the string "matched" — normalise to our internal enum.
  return (body as any[]).map((row) => {
    const hasClusters = Array.isArray(row.clusters) && row.clusters.length > 0;
    const numericStatus = typeof row.status === 'number' ? row.status : null;
    const status: 'matched' | 'ambiguous' | 'not-found' =
      numericStatus === 200 && hasClusters
        ? 'matched'
        : numericStatus === 300 || (numericStatus === 200 && !hasClusters)
          ? 'ambiguous'
          : 'not-found';
    return {
      citation: row.citation,
      status,
      cluster_id: row.clusters?.[0]?.id,
      case_name: row.clusters?.[0]?.case_name,
      date_filed: row.clusters?.[0]?.date_filed,
      court: row.clusters?.[0]?.court,
      url: row.clusters?.[0]?.absolute_url
        ? `https://www.courtlistener.com${row.clusters[0].absolute_url}`
        : undefined,
      citation_count:
        typeof row.clusters?.[0]?.citation_count === 'number'
          ? row.clusters[0].citation_count
          : undefined,
    };
  });
}

/**
 * Pull full cluster metadata. Used after a successful citation lookup to
 * fetch the opinion text for Gate 2 (quote accuracy).
 *
 * Normalises two CL v4 quirks so pipeline.ts doesn't have to know about them:
 *   1. `court`/`court_id` are NOT present on the cluster resource itself —
 *      as of the current v4 API, court lives on the linked `docket`
 *      resource instead. We fetch it and resolve to a slug (e.g. "scotus").
 *   2. `sub_opinions` may be relative paths or full URLs; we ensure full URLs.
 */
export async function getCluster(clusterId: number, token: string): Promise<OpinionCluster> {
  const res = await fetch(`${CL_BASE}/clusters/${clusterId}/`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(`Cluster fetch failed: ${res.status}`);
  const data = await res.json();

  const court = await resolveCourtFromDocket(data.docket, token);

  // Normalise sub_opinions: ensure all entries are fully-qualified URLs
  const sub_opinions: string[] = (data.sub_opinions ?? []).map((u: string) =>
    u.startsWith('http') ? u : `https://www.courtlistener.com${u}`,
  );

  return { ...data, court, sub_opinions };
}

/**
 * Resolve a cluster's court slug via its linked docket resource.
 * The docket exposes both `court_id` (already a slug, e.g. "scotus") and
 * `court` (full resource URL) — prefer the slug, fall back to parsing the
 * URL. Returns '' on any failure so callers degrade to Gate 4 treating the
 * source as unknown-jurisdiction rather than throwing.
 */
async function resolveCourtFromDocket(docketUrl: unknown, token: string): Promise<string> {
  if (typeof docketUrl !== 'string' || !docketUrl) return '';
  try {
    const res = await fetch(docketUrl, { headers: authHeaders(token) });
    if (!res.ok) return '';
    const docket = await res.json();
    if (typeof docket.court_id === 'string' && docket.court_id) return docket.court_id;
    const courtRaw: string = typeof docket.court === 'string' ? docket.court : '';
    return courtRaw ? (courtRaw.replace(/\/$/, '').split('/').pop() ?? courtRaw) : '';
  } catch {
    return '';
  }
}

/**
 * Pull a single opinion's full text. The cluster's sub_opinions field gives
 * the URLs; pass one of those here.
 *
 * Returns null rather than throwing — pipeline.ts uses optional chaining
 * (`opinion?.html_with_citations`) so a null here degrades gracefully:
 * Gate 2 is skipped (no quote to verify), Gate 3 still runs on cache hit.
 */
export async function getOpinion(opinionUrl: string, token: string): Promise<Opinion | null> {
  try {
    const res = await fetch(opinionUrl, { headers: authHeaders(token) });
    if (!res.ok) {
      console.warn(`[courtlistener] getOpinion HTTP ${res.status}: ${opinionUrl}`);
      return null;
    }
    return res.json();
  } catch (err) {
    console.error('[courtlistener] getOpinion error:', err);
    return null;
  }
}

// ── Docket search ──────────────────────────────────────────────────────────

export interface DocketSearchResult {
  id: number;
  docket_number: string;
  case_name: string;
  court: string;
  absolute_url: string;
  date_filed?: string;
  date_terminated?: string;
}

/**
 * Find a docket by case number and court code.
 * e.g. docketNumber="2:26-cv-00315", court="cand" (N.D. Cal.)
 * Returns the best match or null if not found.
 */
export async function searchDocket(
  docketNumber: string,
  court: string,
  token: string,
): Promise<DocketSearchResult | null> {
  const params = new URLSearchParams({ docket_number: docketNumber, court });
  const res = await fetch(`${CL_BASE}/dockets/?${params}`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(`Docket search failed: ${res.status}`);
  const body = await res.json();
  const results: any[] = body.results ?? [];
  if (!results.length) return null;
  const r = results[0];
  return {
    id: r.id,
    docket_number: r.docket_number,
    case_name: r.case_name,
    court: r.court,
    absolute_url: r.absolute_url,
    date_filed: r.date_filed,
    date_terminated: r.date_terminated,
  };
}

export interface DocketEntry {
  docket_entry_number: string;
  filing_date: string;
  description: string;
  doc_urls: string[]; // RECAP document URLs — treated as UNTRUSTED
}

/**
 * Pull docket entries since a given date (ISO string, e.g. "2026-04-01").
 * Returns at most 200 entries. Caller must treat description/doc_urls as
 * UNTRUSTED INPUT (the filer controls the text).
 */
export async function getDocketEntries(
  docketId: number,
  since: string,
  token: string,
): Promise<DocketEntry[]> {
  const params = new URLSearchParams({
    docket: String(docketId),
    date_filed__gte: since,
    order_by: 'date_filed',
    page_size: '200',
  });
  const res = await fetch(`${CL_BASE}/docket-entries/?${params}`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(`Docket entries fetch failed: ${res.status}`);
  const body = await res.json();
  const results: any[] = body.results ?? [];
  return results.map((r) => ({
    docket_entry_number: String(r.entry_number ?? r.id ?? ''),
    filing_date: r.date_filed ?? '',
    // UNTRUSTED: truncated to 400 chars, matching the reader schema
    description: String(r.description ?? '').slice(0, 400),
    // Collect RECAP doc URLs; filter to known CL/PACER/uscourts domains only
    doc_urls: (r.recap_documents ?? [])
      .map((d: any) => d.filepath_ia ?? d.filepath_local ?? '')
      .filter((u: string) =>
        /^https:\/\/([a-z0-9-]+\.)*(courtlistener\.com|uscourts\.gov|pacer\.gov)\//.test(u),
      )
      .slice(0, 10),
  }));
}

/**
 * Gate 3: currency check (best-effort, free-tier).
 *
 * Pull citing opinions. Scan for negative-treatment language. Returns a
 * coarse signal: 'green' (no negative signals), 'yellow' (some), 'red'
 * (clear negative treatment found).
 *
 * For high-stakes filings, supplement with paid Shepard's / KeyCite.
 */
export async function checkCurrency(
  opinionId: number,
  token: string,
): Promise<{
  signal: 'green' | 'yellow' | 'red';
  citingCount: number;
  negativeMentions: string[];
}> {
  const res = await fetch(
    `${CL_BASE}/opinions-cited/?cited_opinion=${opinionId}&page_size=100`,
    { headers: authHeaders(token) },
  );
  if (!res.ok) throw new Error(`Cited-by fetch failed: ${res.status}`);
  const body = await res.json();
  const results = body.results ?? [];

  // Scan for negative treatment markers in the citing opinions' surrounding text.
  // CL exposes `parenthetical` and treatment fields where available.
  const NEGATIVE = [
    /\boverruled\b/i,
    /\babrogated\b/i,
    /\bcalled into doubt\b/i,
    /\bdistinguished\b/i,
    /\bcriticized\b/i,
    /\bno longer good law\b/i,
  ];

  const negativeMentions: string[] = [];
  for (const r of results) {
    const text = `${r.parenthetical ?? ''} ${r.snippet ?? ''}`;
    for (const re of NEGATIVE) {
      if (re.test(text)) negativeMentions.push(text.trim().slice(0, 200));
    }
  }

  let signal: 'green' | 'yellow' | 'red' = 'green';
  if (negativeMentions.some((m) => /overruled|abrogated|no longer good law/i.test(m))) {
    signal = 'red';
  } else if (negativeMentions.length > 0) {
    signal = 'yellow';
  }

  return {
    signal,
    citingCount: results.length,
    negativeMentions: negativeMentions.slice(0, 5),
  };
}
