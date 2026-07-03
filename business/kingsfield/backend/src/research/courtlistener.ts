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
  // (CL returns an array of {citation, status, clusters[]} — we flatten.)
  return (body as any[]).map((row) => ({
    citation: row.citation,
    status: row.status,
    cluster_id: row.clusters?.[0]?.id,
    case_name: row.clusters?.[0]?.case_name,
    date_filed: row.clusters?.[0]?.date_filed,
    court: row.clusters?.[0]?.court,
    url: row.clusters?.[0]?.absolute_url
      ? `https://www.courtlistener.com${row.clusters[0].absolute_url}`
      : undefined,
  }));
}

/**
 * Pull full cluster metadata. Used after a successful citation lookup to
 * fetch the opinion text for Gate 2 (quote accuracy).
 */
export async function getCluster(clusterId: number, token: string): Promise<OpinionCluster> {
  const res = await fetch(`${CL_BASE}/clusters/${clusterId}/`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(`Cluster fetch failed: ${res.status}`);
  return res.json();
}

/**
 * Pull a single opinion's full text. The cluster's sub_opinions field gives
 * the URLs; pass one of those here.
 */
export async function getOpinion(opinionUrl: string, token: string): Promise<Opinion> {
  const res = await fetch(opinionUrl, { headers: authHeaders(token) });
  if (!res.ok) throw new Error(`Opinion fetch failed: ${res.status}`);
  return res.json();
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
