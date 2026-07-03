# Archived Citation Scripts

Superseded by the Grinder pipeline (`make_queue.py` → MCP `opinion_view` → `harvest.py` → `ground.py`).

| Script | Why archived |
|---|---|
| `verifier.py` | Original monolith; CL rate limits blocked at 87/1979 grounded |
| `finish.py` | Per-entry CL retry; superseded by Grinder |
| `batch_lookup.py` | Batch citation lookup experiment on `results.json` subset |
| `agent_test.py` | Agent testing on 250-entry subset only |
| `ai_verify.py` | Full 1,979 AI-only run — **already captured in `results_full.json`** |

Canonical dataset: `../results_full.json`

To re-run model eval (e.g. fix truncated Gemini reasons):
```bash
export ANTHROPIC_KEY=... GEMINI_KEY=... OPENAI_KEY=...
python3 archive/ai_verify.py --redo-gemini
```