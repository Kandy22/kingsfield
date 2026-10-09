#!/usr/bin/env python3
"""Jev pre-labels for the review tool (one yes/no question per row), via OpenRouter's Decisions API.

DRY RUN BY DEFAULT: prints how many rows would be sent and the estimated cost; nothing leaves the Mac.
  python3 jev_prelabel.py --rows review_rows.jsonl            # dry run
  python3 jev_prelabel.py --rows review_rows.jsonl --run      # real calls (key: $OPENROUTER_API_KEY, else
                                                               # read, never printed, from kingsfield/backend/.env)
Model typesafe/jev-1.13, about $0.042 per million input tokens (pennies for this job). Resumable: rows that
already have a Jev answer are skipped. The answer is only a sort key and a hint; a human decides.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

API_URL = "https://openrouter.ai/api/alpha/decisions"
MODEL = "typesafe/jev-1.13"
PRICE_PER_M = 0.042
ENV_FILE = Path(__file__).resolve().parent.parent / "backend" / ".env"


def api_key() -> str:
    k = os.environ.get("OPENROUTER_API_KEY")
    if k:
        return k
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1].strip().strip("'\"")
    sys.exit("OPENROUTER_API_KEY is not set and was not found in kingsfield/backend/.env")


def state_for(row: dict) -> dict:
    c = row.get("candidate") or {}
    return {"statement_or_citation": row.get("claim", ""), "text_around_it": row.get("context", ""),
            "candidate": f"{c.get('text', '')} {c.get('meta', '')}".strip()}


def call(session, payload, key, retries=5):
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    delay = 1.0
    for i in range(retries):
        try:
            r = session.post(API_URL, json=payload, headers=headers, timeout=90)
        except Exception as e:  # network
            if i == retries - 1:
                return {"error": str(e)}
            time.sleep(delay); delay *= 2; continue
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503, 524, 529):
            time.sleep(delay); delay *= 2; continue
        return {"error": f"HTTP {r.status_code}: {r.text[:300]}"}
    return {"error": "exhausted retries"}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rows", required=True)
    ap.add_argument("--run", action="store_true", help="make the real API calls (default is a dry run)")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    path = Path(a.rows)
    rows = [json.loads(l) for l in path.open(encoding="utf-8")]
    todo = [r for r in rows if not r.get("jev")]
    if a.limit:
        todo = todo[: a.limit]
    est_tokens = sum(len(json.dumps(state_for(r))) // 4 + 120 for r in todo)
    print(f"{len(rows)} rows, {len(todo)} need a Jev answer; about {est_tokens:,} input tokens, "
          f"about ${est_tokens / 1e6 * PRICE_PER_M:.4f}")
    if not a.run:
        print("dry run: nothing sent. Add --run to call the API.")
        return
    import requests
    key, s, done = api_key(), requests.Session(), 0
    for r in todo:
        q = {"match": {"type": "noul", "instructions": r.get("question") or "Is the statement correct?"}}
        resp = call(s, {"model": MODEL, "state": state_for(r), "questions": q, "session_id": "kf-review-prelabel"}, key)
        if "error" in resp:
            print("  error on", r["id"], resp["error"][:120]); continue
        p = ((resp.get("answers") or {}).get("match") or {}).get("noul")
        if p is None:
            continue
        r["jev"] = {"answer": "yes" if p >= 0.5 else "no", "confidence": round(max(p, 1 - p), 3), "p_true": round(p, 3)}
        done += 1
        if done % 25 == 0:
            path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf-8")
            print(f"  {done}/{len(todo)}", flush=True)
        time.sleep(0.2)
    path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf-8")
    print(f"done: {done} rows labeled")


if __name__ == "__main__":
    main()
