"""
run_all.py — rebuild the Colorado judicial database end to end.

    python3 run_all.py              # seed corpus, no network
    CL_TOKEN=... python3 run_all.py # full CourtListener pull

Order matters: build_co_judges drops and recreates the DB, then ingest_opinions
fills opinions and co-panel edges on top. Running build alone leaves those empty.
"""

import subprocess, sqlite3, sys, os

def run(script, required=True):
    print(f"\n{'='*74}\n{script}\n{'='*74}")
    r = subprocess.run([sys.executable, script], env=os.environ)
    if r.returncode:
        if required:
            sys.exit(f"FAILED: {script}")
        print(f"SKIPPED/FAILED (non-fatal): {script}")

run("build_co_judges.py")
run("ingest_opinions.py")
# Needs data/ojpe2026/narratives.json, which is harvested through a browser
# session because judicialperformance.colorado.gov 403s non-browser clients.
# Non-fatal so a clean checkout still rebuilds the roster without the corpus.
run("ingest_ojpe_2026.py", required=False)

cx = sqlite3.connect("co_judges.db")
print(f"\n{'='*74}\nFINAL COVERAGE\n{'='*74}")
print(f"{'TABLE':<22}{'ROWS':>7}")
print("-" * 32)
for t, _, n in cx.execute("SELECT t,o,n FROM coverage ORDER BY o"):
    print(f"{t:<22}{n:>7}" + ("" if n else "   <- empty"))
filled = sum(1 for _, _, n in cx.execute("SELECT t,o,n FROM coverage") if n)
total = sum(1 for _ in cx.execute("SELECT t FROM coverage"))
print(f"\n{filled}/{total} tables populated")
cx.close()
