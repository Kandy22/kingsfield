"""Pull the narrative JSON out of a saved browser tool-result file.

The javascript_tool writes oversized results to disk rather than returning
them, which is how the 123-judge narrative corpus reaches the workspace
without passing through the model context. The saved file is a JSON list of
{type,text} blocks; the first block holds our JSON array followed by a
trailing provenance note, so decode just the leading value.
"""
import json, sys

def load(path):
    blocks = json.load(open(path, encoding="utf-8"))
    for b in blocks:
        t = b.get("text", "") if isinstance(b, dict) else ""
        t = t.lstrip()
        if not t or t[0] not in '["':
            continue
        obj, _ = json.JSONDecoder().raw_decode(t)
        # the block is usually a JSON *string* holding the array (double encoded)
        if isinstance(obj, str):
            try:
                obj = json.loads(obj)
            except json.JSONDecodeError:
                continue
        if isinstance(obj, list) and obj and isinstance(obj[0], dict) and "txt" in obj[0]:
            return obj
    return []

if __name__ == "__main__":
    recs = []
    seen = set()
    for p in sys.argv[1:-1]:
        for r in load(p):
            if r.get("u") in seen:
                continue
            seen.add(r.get("u"))
            recs.append(r)
    out = sys.argv[-1]
    json.dump(recs, open(out, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"{len(recs)} unique narratives -> {out}")
    print("chars:", sum(len(r.get("txt","")) for r in recs))
