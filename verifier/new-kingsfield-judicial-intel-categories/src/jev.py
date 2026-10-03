#!/usr/bin/env python3
"""Jev jobs for the 3 / 6 / 29 catalog, over OpenRouter's Decisions API.

Only facts whose catalog row carries a non-"none" `jev.role` are sent to Jev.
Everything else stays tables and arithmetic in build_snapshots.py.

API (read 2026-09-24 from openrouter.ai/docs):
  POST https://openrouter.ai/api/alpha/decisions
  Authorization: Bearer $OPENROUTER_API_KEY
  body   {model, state, questions{name: {type, instructions, criteria}}, session_id?, user?}
         noul  criteria = {"true": ..., "false": ...}   (API reference marks it required)
         choice criteria = {option: description}
         score  criteria = [level0, level1, ...]
  answer noul -> {noul: P(true)}; choice -> {choice, confidence, probabilities};
         score -> {score, confidence, probabilities, legend}
  usage  {input_tokens, output_tokens, cost}
  32k-token context, input-priced ($0.042/M on typesafe/jev-1.13), output free.
  Questions in one request are answered in parallel and cannot see each other.

Modes
  --smoke                  two tiny calls: proves key, endpoint, and whether noul
                           needs `criteria` (call A has it, call B does not)
  --job classify           F08 + F09: practice area and matter type of each argued
                           case, from its oral-argument transcript + case name
  --dry-run                build payloads and print token estimates; no network

Key: $OPENROUTER_API_KEY, else read (never printed, never written) from
kingsfield/backend/.env.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from catalog import load as load_catalog  # noqa: E402

PIPE = ROOT.parent / "judicial-intel-analytics" / "pipeline"
sys.path.insert(0, str(PIPE))
from run_oa_panel import build_state as oa_build_state  # noqa: E402  (same 28k-token trimming)

DATA = ROOT.parent / "judicial-intel-analytics" / "data"
OUT = ROOT / "data" / "jev"

API_URL = "https://openrouter.ai/api/alpha/decisions"
MODEL = "typesafe/jev-1.13"
PRICE_PER_M_INPUT = 0.042
ABSTAIN_BELOW = 0.60      # choice confidence under this -> "unclassified", never a guess


# ---------------------------------------------------------------- key + client

def api_key() -> str:
    k = os.environ.get("OPENROUTER_API_KEY")
    if k:
        return k
    env = ROOT.parents[1] / "backend" / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("OPENROUTER_API_KEY="):
                v = line.split("=", 1)[1].strip().strip('"').strip("'")
                if v:
                    return v
    sys.exit("OPENROUTER_API_KEY not set and not found in kingsfield/backend/.env")


def call(session, payload: dict, key: str, url: str, retries: int = 6) -> dict:
    import requests
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    delay = 1.0
    for attempt in range(retries):
        try:
            r = session.post(url, json=payload, headers=headers, timeout=90)
        except requests.RequestException as e:
            if attempt == retries - 1:
                return {"error": f"request failed: {e}"}
            time.sleep(delay); delay *= 2; continue
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503, 524, 529):
            time.sleep(delay); delay *= 2; continue
        return {"error": f"HTTP {r.status_code}: {r.text[:500]}"}
    return {"error": "exhausted retries"}


def noul(instructions: str, true: str = "", false: str = "") -> dict:
    """Noul without `criteria`: the form proven in production (run_oa_panel.py, 1,500+ calls,
    incl. 2026-09-25). The API reference lists criteria as required but the service accepts
    this form; the --smoke test still checks both."""
    return {"type": "noul", "instructions": instructions}


# ---------------------------------------------------------------- F08 / F09 taxonomies (v0)
# Florida DCA docket. Workers' comp is excluded (1st DCA only). Edit here; the job
# records a hash of these lists with every row so a changed taxonomy is visible.

PRACTICE_AREAS = {
    "criminal": "Criminal prosecution, sentencing, or post-conviction relief.",
    "family": "Dissolution of marriage, timesharing, support, alimony, paternity, or domestic-violence injunctions.",
    "dependency_juvenile": "Dependency, termination of parental rights, or juvenile delinquency.",
    "torts": "Personal injury, negligence, malpractice, wrongful death, defamation, or other civil wrongs.",
    "contracts_commercial": "Contract, business, partnership, debt collection, arbitration, or commercial disputes.",
    "real_property": "Foreclosure, landlord-tenant, title, easements, HOA or condominium, or other land disputes.",
    "probate_trusts_guardianship": "Wills, estates, trusts, or guardianship.",
    "insurance": "Insurance coverage, first-party property claims, or bad faith.",
    "labor_employment": "Employment contracts, wrongful termination, discrimination, or wage claims.",
    "government_administrative": "Agency action, zoning and land use, public records, eminent domain, elections, or claims against government bodies.",
    "other_civil": "A civil matter that fits none of the areas above.",
    "not_determinable": "The transcript does not reveal what the case is about.",
}

MATTER_TYPES = {
    "criminal_trial_error": "Appeal of a conviction claiming trial error (evidence, jury instructions, argument).",
    "criminal_sentencing": "Challenge to a sentence, probation revocation, or restitution.",
    "criminal_postconviction": "Rule 3.850 / 3.800 / 3.853 or other post-conviction motion.",
    "criminal_search_suppression": "Motion to suppress, search and seizure, or Miranda.",
    "dissolution_equitable_distribution": "Dissolution of marriage and division of assets or debts.",
    "timesharing_custody": "Parenting plan, timesharing, relocation, or custody.",
    "alimony_child_support": "Alimony or child support, including modification.",
    "injunction_domestic_violence": "Injunction for protection against domestic, dating, repeat, or stalking violence.",
    "termination_parental_rights": "Termination of parental rights or dependency adjudication.",
    "juvenile_delinquency": "Juvenile delinquency adjudication or disposition.",
    "negligence_personal_injury": "Negligence causing injury, including auto and premises liability.",
    "medical_professional_malpractice": "Medical, legal, or other professional malpractice.",
    "wrongful_death": "Wrongful death claim.",
    "breach_of_contract": "Breach of contract or implied contract.",
    "business_partnership_dispute": "Dispute among owners, partners, shareholders, or members of a business.",
    "arbitration": "Motion to compel or vacate arbitration.",
    "mortgage_foreclosure": "Mortgage or lien foreclosure.",
    "landlord_tenant_eviction": "Eviction or landlord-tenant dispute.",
    "title_easement_boundary": "Quiet title, easement, boundary, or partition.",
    "hoa_condominium": "Homeowners' or condominium association dispute.",
    "eminent_domain": "Eminent domain or inverse condemnation.",
    "will_estate_contest": "Will contest, estate administration, or probate dispute.",
    "trust_dispute": "Trust validity, administration, or trustee conduct.",
    "guardianship": "Guardianship of an adult or minor.",
    "insurance_coverage": "Insurance coverage or first-party property claim, including hurricane and roof claims.",
    "insurance_bad_faith": "Insurer bad-faith claim.",
    "wrongful_termination_discrimination": "Wrongful termination, retaliation, or employment discrimination.",
    "zoning_land_use": "Zoning, permitting, or land-use decision.",
    "public_records_government": "Public records, sovereign immunity, or other claim involving a government body.",
    "attorney_fees_sanctions": "The dispute on appeal is chiefly attorney's fees, costs, or sanctions.",
    "jurisdiction_procedure": "The dispute on appeal is chiefly jurisdiction, venue, service, default, or another procedural ruling.",
    "other": "A matter type not listed above.",
    "not_determinable": "The transcript does not reveal what the case is about.",
}

CLASSIFY_QUESTIONS = {
    "practice_area": {
        "type": "choice",
        "instructions": "What broad practice area does the case argued in `transcript` belong to? Use the subject of the underlying lawsuit, not the appellate procedure.",
        "criteria": PRACTICE_AREAS,
    },
    "matter_type": {
        "type": "choice",
        "instructions": "Which matter type best describes the dispute argued in `transcript`?",
        "criteria": MATTER_TYPES,
    },
    "subject_stated": noul(
        "Do the judges or counsel in `transcript` say what the underlying case is about?",
        "The transcript states the facts or claims of the underlying case.",
        "The transcript does not say what the underlying case is about.",
    ),
}


def taxonomy_hash() -> str:
    import hashlib
    blob = json.dumps([PRACTICE_AREAS, MATTER_TYPES], sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()[:12]


# ---------------------------------------------------------------- smoke

def smoke(url: str, model: str) -> None:
    import requests
    key = api_key()
    s = requests.Session()
    state = {"transcript": "JUDGE: Counsel, the trial court denied the motion to suppress. Why was the stop unlawful? "
                           "APPELLANT'S COUNSEL: The officer had no reasonable suspicion; the tip was anonymous."}
    a = {"model": model, "state": state, "questions": {
        "is_criminal": noul("Is the case in `transcript` a criminal case?", "It is a criminal case.", "It is not a criminal case."),
        "area": {"type": "choice", "instructions": "Practice area of `transcript`?",
                 "criteria": {"criminal": "Criminal case.", "civil": "Civil case."}},
        "skepticism": {"type": "score", "instructions": "How skeptical is the judge toward the appellant in `transcript`?",
                       "criteria": ["Receptive.", "Neutral.", "Skeptical."]},
    }}
    b = {"model": model, "state": state, "questions": {
        "is_criminal": {"type": "noul", "instructions": "Is the case in `transcript` a criminal case?"}}}
    print(f"url={url}  model={model}")
    for name, p in (("A (noul with criteria + choice + score)", a), ("B (noul without criteria)", b)):
        t0 = time.time()
        r = call(s, p, key, url, retries=2)
        ms = int((time.time() - t0) * 1000)
        if "error" in r:
            print(f"\n{name}: FAIL in {ms} ms\n  {r['error']}")
        else:
            print(f"\n{name}: OK in {ms} ms  model={r.get('model')}  provider={r.get('provider')}  usage={r.get('usage')}")
            print(json.dumps(r.get("answers"), indent=1)[:1200])


# ---------------------------------------------------------------- F08 / F09 job

def wilson(k: int, n: int, z: float = 1.96) -> dict:
    if n == 0:
        return {"lo": 0.0, "hi": 0.0, "method": "wilson"}
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return {"lo": round(c - h, 3), "hi": round(c + h, 3), "method": "wilson"}


def named_shares(labels: list[str]) -> list[dict]:
    n = len(labels)
    return [{"name": k, "count": v, "share": round(v / n, 3), "ci95": wilson(v, n)}
            for k, v in Counter(labels).most_common()] if n else []


def eligible_videos(channel: str) -> list[str]:
    """Same gates as the OA panel: scored, passed both gates."""
    import csv
    path = DATA / channel / "panel" / "oa_results.csv"
    out = []
    for r in csv.DictReader(path.open(encoding="utf-8")):
        if r.get("error") or r.get("_gated_out"):
            continue
        try:
            if float(r.get("transcript_sufficient") or 0) < 0.5 or float(r.get("is_oral_argument") or 0) < 0.5:
                continue
        except ValueError:
            continue
        out.append(r["video_id"])
    return sorted(out)


def build_classify_state(channel: str, vid: str) -> tuple[dict, int]:
    doc = json.load(open(DATA / channel / "transcripts" / f"{vid}.turns.json"))
    state, est, _ = oa_build_state(doc)
    dk_path = DATA / channel / "dockets" / f"{vid}.json"
    if dk_path.exists():
        try:
            dk = json.load(open(dk_path))
            if dk.get("case_name"):
                state["case_name"] = dk["case_name"]   # context, not an outcome; disposition never goes in
        except Exception:
            pass
    return state, est


def job_classify(channel: str, url: str, model: str, workers: int, limit: int, dry: bool) -> None:
    out_dir = OUT / channel
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl = out_dir / "classify_f08_f09.jsonl"
    vids = eligible_videos(channel)
    done = set()
    if jsonl.exists():
        for line in jsonl.open(encoding="utf-8"):
            try:
                r = json.loads(line)
                if "error" not in r:
                    done.add(r["video_id"])
            except Exception:
                pass
    todo = [v for v in vids if v not in done]
    if limit:
        todo = todo[:limit]
    th = taxonomy_hash()
    print(f"channel={channel}  eligible={len(vids)}  done={len(done)}  to_run={len(todo)}  taxonomy={th}")

    if dry:
        ests = [build_classify_state(channel, v)[1] for v in todo[: max(limit, 5)]]
        q_tokens = int(len(json.dumps(CLASSIFY_QUESTIONS).split()) * 1.35)
        per = (sum(ests) / len(ests) if ests else 0) + q_tokens
        print(f"dry-run: ~{per:,.0f} input tokens/call (questions ~{q_tokens:,}); "
              f"{len(todo)} calls ≈ ${len(todo) * per * PRICE_PER_M_INPUT / 1e6:.4f}")
        return

    import requests
    key = api_key()
    s = requests.Session()
    lock = threading.Lock()
    stats = {"n": 0, "err": 0, "cost": 0.0, "tok": 0}
    t0 = time.time()

    def work(vid):
        state, est = build_classify_state(channel, vid)
        resp = call(s, {"model": model, "state": state, "questions": CLASSIFY_QUESTIONS,
                        "session_id": f"kf-classify-{channel}"}, key, url)
        rec = {"video_id": vid, "taxonomy": th, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        if "error" in resp:
            rec["error"] = resp["error"]
            return rec
        a = resp.get("answers") or {}
        for q in ("practice_area", "matter_type"):
            rec[q] = (a.get(q) or {}).get("choice")
            rec[f"{q}__confidence"] = (a.get(q) or {}).get("confidence")
            rec[f"{q}__probabilities"] = (a.get(q) or {}).get("probabilities")
        rec["subject_stated"] = (a.get("subject_stated") or {}).get("noul")
        u = resp.get("usage") or {}
        rec["_input_tokens"] = u.get("input_tokens", 0)
        rec["_cost"] = u.get("cost")
        rec["_model"] = resp.get("model")
        rec["_id"] = resp.get("id")
        return rec

    if todo:
        with jsonl.open("a", encoding="utf-8") as f, ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(work, v) for v in todo]
            for fut in as_completed(futs):
                rec = fut.result()
                with lock:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n"); f.flush()
                    stats["n"] += 1
                    stats["err"] += "error" in rec
                    stats["tok"] += rec.get("_input_tokens", 0)
                    stats["cost"] += rec.get("_cost") or 0
                    if stats["n"] % 25 == 0 or stats["n"] == len(todo):
                        print(f"  {stats['n']}/{len(todo)}  errors {stats['err']}  "
                              f"{stats['tok']:,} tok  ${stats['cost']:.4f}  {int(time.time() - t0)}s", flush=True)
    summarize_classify(channel)


def summarize_classify(channel: str) -> None:
    jsonl = OUT / channel / "classify_f08_f09.jsonl"
    latest = {}
    for line in jsonl.open(encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if "error" not in r:
            latest[r["video_id"]] = r
    errs = sum(1 for line in jsonl.open(encoding="utf-8") if '"error"' in line)
    rows = list(latest.values())

    def labels(q):
        keep, abstained = [], 0
        for r in rows:
            c = r.get(f"{q}__confidence") or 0
            if r.get(q) and r[q] != "not_determinable" and c >= ABSTAIN_BELOW:
                keep.append(r[q])
            else:
                abstained += 1
        return keep, abstained

    pa, pa_abs = labels("practice_area")
    mt, mt_abs = labels("matter_type")
    catalog = {f["id"]: f for f in load_catalog()["factual"]}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    prov = {"source": f"Jev {MODEL} via OpenRouter Decisions API on OA transcripts ({channel}); "
                      f"choice confidence < {ABSTAIN_BELOW} or not_determinable counted as abstain",
            "collected_at": now, "taxonomy": taxonomy_hash()}
    out = {
        "court_id": channel, "scope": "argued cases (court level)", "as_of": now[:10],
        "n_classified_rows": len(rows), "n_error_rows_in_log": errs,
        "fields": {
            "F08": {"name": catalog["F08"]["name"], "n": len(pa), "abstained": pa_abs, "value": named_shares(pa)},
            "F09": {"name": catalog["F09"]["name"], "n": len(mt), "abstained": mt_abs, "value": named_shares(mt)},
        },
        "provenance": {"F08": prov, "F09": prov},
    }
    p = OUT / channel / "F08_F09.json"
    p.write_text(json.dumps(out, indent=1))
    print(f"\n{len(rows)} rows classified | F08 n={len(pa)} abstained={pa_abs} | F09 n={len(mt)} abstained={mt_abs}")
    for fid in ("F08", "F09"):
        print(f"{fid} top:", ", ".join(f"{s['name']} {s['share']:.0%}" for s in out['fields'][fid]['value'][:6]))
    print(f"wrote {p}")


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--job", choices=["classify"])
    ap.add_argument("--channel", default="fl_2dca")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--summarize", action="store_true", help="rebuild F08_F09.json from the log only")
    ap.add_argument("--api-url", default=API_URL)
    ap.add_argument("--model", default=MODEL)
    a = ap.parse_args()

    roles = {f["id"]: f["jev"]["role"] for f in load_catalog()["factual"] if f["jev"]["role"] != "none"}
    if a.smoke:
        return smoke(a.api_url, a.model)
    if a.summarize:
        return summarize_classify(a.channel)
    if a.job == "classify":
        assert roles.get("F08") == roles.get("F09") == "classify_incoming", "catalog jev hints changed"
        return job_classify(a.channel, a.api_url, a.model, a.workers, a.limit, a.dry_run)
    print("Jev roles in catalog:", json.dumps(roles))
    ap.print_help()


if __name__ == "__main__":
    main()
