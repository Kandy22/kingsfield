#!/usr/bin/env python3
"""
Kingsfield — enrich existing results.json
Adds cl_url from cluster_id so sandbox links work.
No API calls needed — just builds URLs from existing data.
"""
import json, re

INPUT = "results.json"

with open(INPUT) as f:
    results = json.load(f)

fixed = 0
for r in results:
    cluster_id = r.get('cl_cluster')
    if cluster_id and not r.get('cl_url'):
        r['cl_url'] = f"https://www.courtlistener.com/opinion/{cluster_id}/"
        fixed += 1

with open(INPUT, 'w') as f:
    json.dump(results, f, indent=2)

print(f"Done. Added cl_url to {fixed} entries.")
