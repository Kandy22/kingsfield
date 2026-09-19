"""
scholar_fl_scraper.py
Kingsfield Lawfare — Google Scholar FL Case Law Scraper
June 2026

Scrapes Google Scholar case law with Florida filter (as_sdt=4,9).
Extracts: case name, citation, court, date, snippet, Scholar URL,
          citation count, "how cited" URL, related case links.

Output files:
  scholar_fl_results.json    — full structured results
  scholar_fl_manifest.json   — lightweight index (matches fl_2dca_index.json format)
  scholar_fl_errors.log      — failed pages / rate limit hits

Run on your Mac (NOT in Claude container — Scholar blocks datacenter IPs):
  pip install requests beautifulsoup4
  python3 scholar_fl_scraper.py --query "ADA accommodation" --pages 5
  python3 scholar_fl_scraper.py --query "pro se filing restriction" --pages 10 --deep
  python3 scholar_fl_scraper.py --batch queries.txt --pages 5

RATE LIMIT WARNING:
  Scholar will 429 or CAPTCHA you if you go too fast.
  Default delay: 8-15s random. Do not reduce below 5s.
  If you hit a CAPTCHA wall: stop, wait 30 min, restart with --delay 20.

WEX COMPATIBILITY:
  Output schema matches wex_h_through_m.json for downstream JOIN:
    { "term": ..., "slug": ..., "url": ..., "letter": ... }
  Cases are joinable via legal term extraction (see --extract-terms flag).
"""

import argparse
import json
import logging
import os
import random
import re
import sys
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode, urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

# ── Constants ─────────────────────────────────────────────────────────────────

BASE_URL   = "https://scholar.google.com"
SEARCH_URL = "https://scholar.google.com/scholar"
CITED_URL  = "https://scholar.google.com/scholar?cites={cluster_id}&as_sdt=4,9"

# as_sdt=4,9 — 4=case law mode required, 9=Florida state courts
# To add federal courts alongside FL: as_sdt=4,9,20 (20=11th Circuit)
# To search ALL courts: as_sdt=4
FL_SDT = "4,9"
FL_SDT_PLUS_11TH = "4,9,20"   # FL state + 11th Circuit federal

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
]

DEFAULT_DELAY_MIN = 8    # seconds — do not go below 5
DEFAULT_DELAY_MAX = 15


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class ScholarCase:
    """One case result from Google Scholar."""
    # Core identity
    title:           str   = ""
    citation:        str   = ""          # e.g. "123 So.3d 456 (Fla. 2019)"
    court:           str   = ""          # e.g. "District Court of Appeal of Florida, 2nd"
    year:            Optional[int] = None
    date_raw:        str   = ""          # raw date string from Scholar

    # Content
    snippet:         str   = ""          # excerpt Scholar shows in results
    full_text_url:   str   = ""          # link to full opinion (Scholar or external)
    scholar_url:     str   = ""          # Scholar result URL
    cluster_id:      str   = ""          # Scholar cluster ID (for citation graph)
    how_cited_url:   str   = ""          # "How cited" / citator URL

    # Citation graph
    cited_by_count:  int   = 0
    cited_by_url:    str   = ""          # Scholar search for cases citing this one
    related_urls:    list  = field(default_factory=list)   # "Related articles" links

    # Kingsfield metadata
    query:           str   = ""          # search query that produced this result
    scraped_at:      str   = ""
    page_index:      int   = 0           # which result page (0=first)
    result_rank:     int   = 0           # position on that page (0-9)

    # WEX join compatibility
    slug:            str   = ""          # lowercase underscore version of title
    letter:          str   = ""          # first letter of title (for indexing)


@dataclass
class ScrapeRun:
    """Metadata for one complete scrape run."""
    query:           str
    as_sdt:          str
    pages_requested: int
    pages_scraped:   int
    total_results:   int
    started_at:      str
    finished_at:     str
    errors:          list = field(default_factory=list)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_slug(title: str) -> str:
    """Convert case title to URL-slug format for WEX join compatibility."""
    s = title.lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_-]+", "_", s)
    return s.strip("_")[:120]


def extract_year(text: str) -> Optional[int]:
    """Pull 4-digit year from a date/citation string."""
    m = re.search(r"\b(19[5-9]\d|20[0-2]\d)\b", text)
    return int(m.group(1)) if m else None


def extract_cluster_id(url: str) -> str:
    """Extract Scholar cluster_id from a URL."""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    # Scholar result URLs: /scholar_case?case=NNNNN or ?cites=NNNNN
    for key in ("case", "cites", "cluster"):
        if key in qs:
            return qs[key][0]
    # Try path-based IDs
    m = re.search(r"[?&](?:case|cites|cluster)=(\d+)", url)
    return m.group(1) if m else ""


def polite_sleep(min_s=DEFAULT_DELAY_MIN, max_s=DEFAULT_DELAY_MAX):
    t = random.uniform(min_s, max_s)
    logging.debug(f"Sleeping {t:.1f}s")
    time.sleep(t)


def get_headers() -> dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Referer": "https://scholar.google.com/",
        "Upgrade-Insecure-Requests": "1",
    }


# ── Session ───────────────────────────────────────────────────────────────────

class ScholarSession:
    """Manages a requests Session with cookie persistence (Scholar needs cookies)."""

    def __init__(self, delay_min=DEFAULT_DELAY_MIN, delay_max=DEFAULT_DELAY_MAX):
        self.session = requests.Session()
        self.delay_min = delay_min
        self.delay_max = delay_max
        self._init_cookies()

    def _init_cookies(self):
        """Hit Scholar homepage first to get session cookies."""
        try:
            r = self.session.get(
                BASE_URL, headers=get_headers(), timeout=15
            )
            logging.debug(f"Cookie init: {r.status_code}")
            time.sleep(random.uniform(2, 4))
        except Exception as e:
            logging.warning(f"Cookie init failed: {e}")

    def get(self, url: str, params: dict = None) -> Optional[requests.Response]:
        """GET with retry on 429, abort on CAPTCHA."""
        for attempt in range(3):
            try:
                r = self.session.get(
                    url, params=params, headers=get_headers(), timeout=20
                )
                if r.status_code == 200:
                    # CAPTCHA detection
                    if "captcha" in r.text.lower() or "unusual traffic" in r.text.lower():
                        logging.error(
                            "CAPTCHA detected. Stop scraping, wait 30+ min, "
                            "restart with --delay 20"
                        )
                        return None
                    return r
                elif r.status_code == 429:
                    wait = 60 * (attempt + 1)
                    logging.warning(f"429 rate limit — waiting {wait}s (attempt {attempt+1})")
                    time.sleep(wait)
                else:
                    logging.warning(f"HTTP {r.status_code} for {url}")
                    return None
            except requests.RequestException as e:
                logging.warning(f"Request error (attempt {attempt+1}): {e}")
                time.sleep(10)
        return None


# ── Parsers ───────────────────────────────────────────────────────────────────

def parse_search_page(html: str, query: str, page_idx: int) -> list[ScholarCase]:
    """Parse one Scholar case-law search results page."""
    soup = BeautifulSoup(html, "html.parser")
    results = []

    # Scholar wraps each result in div.gs_r.gs_or.gs_scl (or similar)
    # Case law results specifically: div[data-lid] or div.gs_ri
    containers = soup.find_all("div", class_="gs_r")
    if not containers:
        # Fallback to broader selector
        containers = soup.find_all("div", attrs={"data-lid": True})

    for rank, div in enumerate(containers):
        case = ScholarCase(
            query=query,
            scraped_at=datetime.now(timezone.utc).isoformat(),
            page_index=page_idx,
            result_rank=rank,
        )

        # Title + Scholar URL
        title_tag = div.find("h3", class_="gs_rt")
        if not title_tag:
            title_tag = div.find("h3")
        if title_tag:
            a = title_tag.find("a", href=True)
            if a:
                case.title = a.get_text(strip=True)
                href = a["href"]
                case.scholar_url = href if href.startswith("http") else BASE_URL + href
                case.cluster_id = extract_cluster_id(case.scholar_url)
                case.full_text_url = case.scholar_url
            else:
                case.title = title_tag.get_text(strip=True)

        if not case.title:
            continue

        # Slug + letter for WEX join
        case.slug   = make_slug(case.title)
        case.letter = case.title[0].upper() if case.title else ""

        # Court + date line (gs_a)
        meta_tag = div.find("div", class_="gs_a")
        if meta_tag:
            meta_text = meta_tag.get_text(separator=" ", strip=True)
            case.date_raw = meta_text
            case.year     = extract_year(meta_text)
            # Try to extract court from meta (typically: "Court Name - Year")
            # Scholar formats: "Author - Court - Year" or "Court, Year"
            parts = [p.strip() for p in re.split(r"\s*[-–]\s*", meta_text)]
            if parts:
                # Court is usually the second segment for case law
                if len(parts) >= 2:
                    case.court = parts[-2] if len(parts) > 1 else parts[0]
                else:
                    case.court = parts[0]

        # Snippet (gs_rs)
        snippet_tag = div.find("div", class_="gs_rs")
        if snippet_tag:
            case.snippet = snippet_tag.get_text(separator=" ", strip=True)

        # Citation string — Scholar sometimes embeds it in the title or snippet
        # Pattern: NNN So.3d NNN, NNN F.3d NNN, etc.
        citation_patterns = [
            r"\d+\s+(?:So|F|S\.W|P|A|N\.E|N\.W|S\.E)\.?(?:2d|3d)?\s+\d+",
            r"\d+\s+Fla\.\s+\d+",
            r"\d+\s+F\.(?:Supp|App\'x)\.?(?:2d|3d)?\s+\d+",
        ]
        full_text = (case.title + " " + case.date_raw + " " + case.snippet)
        for pat in citation_patterns:
            m = re.search(pat, full_text)
            if m:
                case.citation = m.group(0)
                break

        # Cited by + How Cited links (gs_fl)
        fl_div = div.find("div", class_="gs_fl")
        if fl_div:
            for a in fl_div.find_all("a", href=True):
                link_text = a.get_text(strip=True).lower()
                href = a["href"]
                full_href = href if href.startswith("http") else BASE_URL + href

                if "cited by" in link_text:
                    # e.g. "Cited by 47"
                    m = re.search(r"cited by\s+(\d+)", link_text)
                    if m:
                        case.cited_by_count = int(m.group(1))
                    case.cited_by_url = full_href

                elif "related" in link_text:
                    case.related_urls.append(full_href)

                elif "how cited" in link_text or "cites" in href:
                    case.how_cited_url = full_href

            # Build how_cited_url from cluster_id if not found directly
            if not case.how_cited_url and case.cluster_id:
                case.how_cited_url = CITED_URL.format(cluster_id=case.cluster_id)

        results.append(case)

    return results


def parse_how_cited_page(html: str, source_case: ScholarCase) -> list[dict]:
    """
    Parse the 'How Cited' page for a case.
    Returns list of { title, url, snippet, relationship } dicts.
    These form the citation graph edges.
    """
    soup = BeautifulSoup(html, "html.parser")
    citations = []

    for div in soup.find_all("div", class_="gs_r"):
        title_tag = div.find("h3", class_="gs_rt")
        if not title_tag:
            continue
        a = title_tag.find("a", href=True)
        if not a:
            continue

        href = a["href"]
        snippet_tag = div.find("div", class_="gs_rs")

        citations.append({
            "citing_case_title": a.get_text(strip=True),
            "citing_case_url": href if href.startswith("http") else BASE_URL + href,
            "cited_case_title": source_case.title,
            "cited_case_cluster_id": source_case.cluster_id,
            "snippet": snippet_tag.get_text(strip=True) if snippet_tag else "",
        })

    return citations


# ── Main scraper ──────────────────────────────────────────────────────────────

class FLScholarScraper:

    def __init__(
        self,
        as_sdt: str = FL_SDT,
        delay_min: float = DEFAULT_DELAY_MIN,
        delay_max: float = DEFAULT_DELAY_MAX,
        output_dir: str = ".",
        deep: bool = False,
    ):
        self.as_sdt    = as_sdt
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.deep      = deep      # if True, also crawl how_cited pages
        self.session   = ScholarSession(delay_min, delay_max)

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[
                logging.StreamHandler(sys.stdout),
                logging.FileHandler(self.output_dir / "scholar_fl_errors.log"),
            ],
        )

    def build_search_url(self, query: str, start: int = 0) -> str:
        params = {
            "q":      query,
            "hl":     "en",
            "as_sdt": self.as_sdt,
            "start":  start,
        }
        return SEARCH_URL + "?" + urlencode(params)

    def scrape_query(self, query: str, max_pages: int = 5) -> tuple[list[ScholarCase], list[dict]]:
        """
        Scrape up to max_pages (10 results each) for a query.
        Returns (cases, citation_edges).
        """
        all_cases: list[ScholarCase] = []
        all_edges: list[dict]        = []
        errors: list[str]            = []

        logging.info(f"Query: '{query}' | as_sdt={self.as_sdt} | pages={max_pages}")

        for page in range(max_pages):
            start = page * 10
            url   = self.build_search_url(query, start)
            logging.info(f"  Page {page+1}/{max_pages} (start={start}) ...")

            resp = self.session.get(url)
            if resp is None:
                errors.append(f"Failed page {page+1} for query '{query}'")
                break

            cases = parse_search_page(resp.text, query, page)
            if not cases:
                logging.info(f"  No results on page {page+1} — stopping.")
                break

            logging.info(f"  Got {len(cases)} cases")
            all_cases.extend(cases)

            # Deep mode: crawl citation graph for each case
            if self.deep:
                for case in cases:
                    if case.how_cited_url:
                        polite_sleep(self.delay_min, self.delay_max)
                        cited_resp = self.session.get(case.how_cited_url)
                        if cited_resp:
                            edges = parse_how_cited_page(cited_resp.text, case)
                            all_edges.extend(edges)
                            logging.info(
                                f"    '{case.title[:50]}' → {len(edges)} citing cases"
                            )

            if page < max_pages - 1:
                polite_sleep(self.delay_min, self.delay_max)

        return all_cases, all_edges

    def scrape_batch(self, queries: list[str], max_pages: int = 5) -> dict:
        """Run multiple queries, aggregate results."""
        all_cases: list[ScholarCase] = []
        all_edges: list[dict]        = []
        run_meta = {
            "as_sdt": self.as_sdt,
            "queries": queries,
            "pages_per_query": max_pages,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "deep": self.deep,
        }

        for i, query in enumerate(queries):
            logging.info(f"\n=== Query {i+1}/{len(queries)}: '{query}' ===")
            cases, edges = self.scrape_query(query, max_pages)
            all_cases.extend(cases)
            all_edges.extend(edges)
            if i < len(queries) - 1:
                # Extra pause between different queries
                polite_sleep(self.delay_min * 1.5, self.delay_max * 2)

        # Deduplicate by cluster_id, then by title
        seen_clusters = set()
        seen_titles   = set()
        unique_cases  = []
        for c in all_cases:
            key = c.cluster_id or c.title
            if key and key not in seen_clusters:
                seen_clusters.add(key)
                unique_cases.append(c)

        run_meta["finished_at"]    = datetime.now(timezone.utc).isoformat()
        run_meta["total_raw"]      = len(all_cases)
        run_meta["total_unique"]   = len(unique_cases)
        run_meta["citation_edges"] = len(all_edges)

        return {
            "metadata": run_meta,
            "cases":    [asdict(c) for c in unique_cases],
            "citation_graph": all_edges,
        }

    def save(self, data: dict, prefix: str = "scholar_fl"):
        """Write full JSON + lightweight manifest."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Full results
        full_path = self.output_dir / f"{prefix}_results_{ts}.json"
        with open(full_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logging.info(f"Full results → {full_path}")

        # Lightweight manifest (matches fl_2dca_index.json format)
        manifest = {
            "metadata": {
                **data["metadata"],
                "source": "Google Scholar Case Law",
                "filter": f"as_sdt={data['metadata']['as_sdt']}",
                "note": (
                    "Lightweight index — see _results_ file for full data. "
                    "Compatible with fl_2dca_index.json format."
                ),
            },
            "cases": [
                {
                    "title":        c["title"],
                    "citation":     c["citation"],
                    "court":        c["court"],
                    "year":         c["year"],
                    "scholar_url":  c["scholar_url"],
                    "cluster_id":   c["cluster_id"],
                    "cited_by":     c["cited_by_count"],
                    "query":        c["query"],
                    # WEX join fields
                    "slug":         c["slug"],
                    "letter":       c["letter"],
                }
                for c in data["cases"]
            ],
            "citation_graph_summary": {
                "total_edges": len(data["citation_graph"]),
                "note": "Full graph in _results_ file → citation_graph array",
            },
        }
        manifest_path = self.output_dir / f"{prefix}_manifest_{ts}.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        logging.info(f"Manifest → {manifest_path}")

        return full_path, manifest_path


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Google Scholar FL case law scraper — Kingsfield Lawfare"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--query", "-q", help="Single search query")
    group.add_argument("--batch", "-b", help="Path to .txt file with one query per line")

    parser.add_argument(
        "--pages", "-p", type=int, default=5,
        help="Pages per query (10 results each, default 5 = 50 results)"
    )
    parser.add_argument(
        "--deep", action="store_true",
        help="Also crawl 'How Cited' pages for citation graph (slower, more data)"
    )
    parser.add_argument(
        "--sdt", default=FL_SDT,
        help=f"as_sdt value (default: {FL_SDT} = FL courts). "
             f"Use '{FL_SDT_PLUS_11TH}' to add 11th Circuit."
    )
    parser.add_argument(
        "--delay", type=float, default=None,
        help="Override minimum delay between requests (seconds, default 8). "
             "Never set below 5."
    )
    parser.add_argument(
        "--output", "-o", default=".",
        help="Output directory (default: current directory)"
    )
    parser.add_argument(
        "--prefix", default="scholar_fl",
        help="Output filename prefix (default: scholar_fl)"
    )

    args = parser.parse_args()

    delay_min = max(5.0, args.delay) if args.delay else DEFAULT_DELAY_MIN
    delay_max = delay_min + 7

    scraper = FLScholarScraper(
        as_sdt=args.sdt,
        delay_min=delay_min,
        delay_max=delay_max,
        output_dir=args.output,
        deep=args.deep,
    )

    # Build query list
    if args.query:
        queries = [args.query]
    else:
        batch_path = Path(args.batch)
        if not batch_path.exists():
            print(f"ERROR: batch file not found: {batch_path}", file=sys.stderr)
            sys.exit(1)
        queries = [
            line.strip() for line in batch_path.read_text().splitlines()
            if line.strip() and not line.startswith("#")
        ]
        if not queries:
            print("ERROR: No queries found in batch file.", file=sys.stderr)
            sys.exit(1)
        print(f"Loaded {len(queries)} queries from {batch_path}")

    # Run
    data = scraper.scrape_batch(queries, args.pages)

    # Summary
    n = data["metadata"]["total_unique"]
    e = data["metadata"]["citation_edges"]
    print(f"\n✓ {n} unique cases, {e} citation edges")

    # Save
    full_path, manifest_path = scraper.save(data, args.prefix)
    print(f"  Full:     {full_path}")
    print(f"  Manifest: {manifest_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
