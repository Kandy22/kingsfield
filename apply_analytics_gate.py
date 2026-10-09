#!/usr/bin/env python3
"""Refuse an analytics extraction whose model text fails Gate 1."""
from pathlib import Path

intel = Path("backend/src/lib/caseIntelligence.ts")
text = intel.read_text()
if "extraction withheld" not in text:
    old = 'import { citationLookup } from "../research/courtlistener.js";\n'
    new = old + 'import { gateTitleText, verifyDraftForSse } from "../middleware/hallucination_guard.js";\n'
    if old not in text:
        raise SystemExit("caseIntelligence import missing")
    text = text.replace(old, new, 1)
    old = '  intel.authorities = await enrichAuthorityCiteCounts(intel.authorities);\n\n  const { data, error } = await db'
    new = '''  intel.authorities = await enrichAuthorityCiteCounts(intel.authorities);

  // extraction withheld: Gate 1 over the model JSON before the row is saved.
  const extracted = JSON.stringify(intel);
  const gated = await gateTitleText(extracted, "", {
    verify: (value) => verifyDraftForSse(value, {
      courtListenerToken: process.env.COURTLISTENER_TOKEN ?? "",
      supabase: db,
    }),
    logError: (context, error) => console.error(`[analytics/extract] ${context}`, error),
  });
  if (gated.title !== extracted) {
    return { ok: false, error: "The extraction was withheld because it could not be verified." };
  }

  const { data, error } = await db'''
    if old not in text:
        raise SystemExit("upsert site missing")
    text = text.replace(old, new, 1)
    intel.write_text(text)
    print("patched", intel)
else:
    print("caseIntelligence already patched")

route = Path("backend/src/routes/index.ts")
rt = route.read_text()
old = '''      if (!result.ok) return void res.status(422).json({ detail: result.error });
      res.json({ extraction: result.row });
    } catch (err: any) {
      console.error('[analytics/extract] error', err);
      res.status(500).json({ detail: err?.message ?? 'Extraction failed' });
    }'''
new = '''      if (!result.ok) {
        const detail = result.error.startsWith("The extraction was withheld")
          || result.error.startsWith("Document")
          || result.error.startsWith("This PDF")
          ? result.error
          : "Extraction failed.";
        return void res.status(422).json({ detail });
      }
      res.json({ extraction: result.row });
    } catch (err) {
      console.error('[analytics/extract] error', safeErrorLog(err));
      res.status(500).json({ detail: "Extraction failed." });
    }'''
if old not in rt:
    raise SystemExit("extract route missing")
route.write_text(rt.replace(old, new, 1))
print("patched", route)
