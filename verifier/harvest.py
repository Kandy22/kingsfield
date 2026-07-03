#!/usr/bin/env python3
"""
Harvest opinion text from persisted MCP tool-results into opinion_cache/.

Why this exists:
The CourtListener `opinion_view` MCP tool returns full opinion text (often 30-80KB).
When the result is large, the runtime auto-persists it to disk under
  .claude/projects/<proj>/<run>/tool-results/<toolu_*>.json
and only a small preview returns to the agent's context. This script scans those
persisted files and extracts the full opinion text WITHOUT routing it back through
the agent's context window — which is what makes grinding 800+ opinions feasible.

The agent's job each run is simply: call opinion_view on a batch of citations,
then run `python3 harvest.py && python3 ground.py`.

Resumable & idempotent: already-cached citations are skipped.
"""
import json, glob, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, "opinion_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# Search roots for persisted tool-results (session-specific paths vary per run,
# so glob broadly rather than hard-coding one session id).
SEARCH_GLOBS = [
    "/sessions/*/mnt/.claude/projects/*/*/tool-results/*.json",
    "/sessions/*/mnt/.claude/projects/*/*/tool-results/*opinion_view*.txt",
    os.path.expanduser("~/.claude/projects/*/*/tool-results/*.json"),
    os.path.expanduser("~/.claude/projects/*/*/tool-results/*opinion_view*.txt"),
]

def slug(cite):
    return re.sub(r"[^A-Za-z0-9]+", "_", (cite or "").strip()).strip("_")

def iter_persisted():
    seen = set()
    for g in SEARCH_GLOBS:
        for path in glob.glob(g):
            if path in seen:
                continue
            seen.add(path)
            yield path

def extract_opinion(path):
    """Return (identifier, text) from a persisted opinion_view result, or None.

    Handles two on-disk formats:
      - .json wrapper: [{"type":"text","text":"<json string>"}]
      - .txt plain dump: the raw JSON string itself (saved when output errored on size)
    """
    content = open(path, encoding="utf-8", errors="ignore").read()
    candidates = []
    try:
        raw = json.loads(content)
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict) and "text" in item:
                    candidates.append(item["text"])
        elif isinstance(raw, dict):
            candidates.append(content)
    except Exception:
        # plain-text dump: treat the whole file as the JSON candidate
        candidates.append(content)
    for c in candidates:
        try:
            inner = json.loads(c)
        except Exception:
            continue
        if isinstance(inner, dict) and inner.get("text") and inner.get("identifier"):
            ident = inner.get("identifier")
            if inner.get("identifier_type") == "citation" or re.search(r"\bU\.?\s?S\.?\b|\bF\.?\s?\dd?\b", str(ident)):
                return str(ident), inner["text"]
    return None

def main():
    found = {}
    for path in iter_persisted():
        res = extract_opinion(path)
        if res:
            ident, text = res
            # keep the longest text seen for a given citation (handles truncated portions)
            if ident not in found or len(text) > len(found[ident]):
                found[ident] = text
    written = 0
    for ident, text in found.items():
        dest = os.path.join(CACHE_DIR, slug(ident) + ".txt")
        if os.path.exists(dest) and os.path.getsize(dest) >= len(text):
            continue
        with open(dest, "w", encoding="utf-8") as f:
            f.write(text)
        written += 1
    print(f"persisted opinions found: {len(found)}")
    print(f"cache files written/updated: {written}")
    cached = len(glob.glob(os.path.join(CACHE_DIR, "*.txt")))
    print(f"total cached opinions: {cached}")

if __name__ == "__main__":
    main()
