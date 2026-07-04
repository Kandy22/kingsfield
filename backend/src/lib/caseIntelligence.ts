// Case Intelligence extraction agent.
//
// Given an uploaded document, a pre-trained-style prompt strips the case down
// to structured facts: who's involved (judge, opposing counsel, DA, witnesses,
// parties, court), what's alleged, what the defense is, which legal authorities
// are cited, and how common/novel the fact pattern is. The structured output
// feeds the Analytics connection graph + allegation/defense/authority clusters.

import { createServerSupabase } from "./supabase.js";
import { completeText } from "./llm/index.js";
import { loadCurrentVersionBytes, extractPdfText } from "./chatTools.js";
import { citationLookup } from "../research/courtlistener.js";
import type { UserApiKeys } from "./llm/types.js";

export type EntityRole =
  | "judge"
  | "opposing_counsel"
  | "da"
  | "witness"
  | "party"
  | "court"
  | "expert"
  | "other";

export interface CaseEntity {
  name: string;
  role: EntityRole;
  note?: string;
}

export interface CaseAllegation {
  claim: string;
  authorities: string[];
  strength?: "strong" | "moderate" | "weak" | null;
  /** Agent-judged: how often this kind of claim shows up in litigation. */
  novelty?: "common" | "uncommon" | "novel" | null;
}

export interface CaseDefense {
  defense: string;
  responds_to?: string | null;
  authorities: string[];
  /** Agent-judged: how often this defense shows up in litigation. */
  novelty?: "common" | "uncommon" | "novel" | null;
}

export interface CaseAuthority {
  citation: string;
  proposition?: string;
  treatment?: "relied_on" | "distinguished" | "cited" | "criticized" | null;
  /** CourtListener citation count — how often the authority is cited overall.
   *  null when the citation didn't resolve (statutes, rules, lookup miss). */
  cite_count?: number | null;
}

export interface CaseRarity {
  score: number; // 0 (routine) – 100 (novel/rare)
  label: string;
  rationale: string;
}

export interface CaseIntelligence {
  caption: string | null;
  entities: CaseEntity[];
  allegations: CaseAllegation[];
  defenses: CaseDefense[];
  authorities: CaseAuthority[];
  rarity: CaseRarity | null;
  defense_summary: string | null;
}

const EXTRACTION_SYSTEM = `You are Kingsfield's case-intelligence extraction agent. You read a legal document (a complaint, motion, brief, opinion, or transcript) and strip it down to structured, verifiable facts. You do not editorialize. You extract only what is present or fairly inferable from the text.

Return ONLY a single JSON object (no markdown fence, no prose) with exactly these keys:

{
  "caption": string | null,            // the case caption or a short title, e.g. "Smith v. Acme Corp."
  "entities": [                        // every person/institution tied to the matter
    { "name": string, "role": "judge"|"opposing_counsel"|"da"|"witness"|"party"|"court"|"expert"|"other", "note": string }
  ],
  "allegations": [                     // claims/causes of action asserted
    { "claim": string, "authorities": [string], "strength": "strong"|"moderate"|"weak"|null, "novelty": "common"|"uncommon"|"novel" }
  ],
  "defenses": [                        // defenses / rebuttals raised or available
    { "defense": string, "responds_to": string|null, "authorities": [string], "novelty": "common"|"uncommon"|"novel" }
  ],
  "authorities": [                     // every legal authority cited in the document
    { "citation": string, "proposition": string, "treatment": "relied_on"|"distinguished"|"cited"|"criticized"|null }
  ],
  "rarity": { "score": number, "label": string, "rationale": string },  // 0=routine fact pattern, 100=novel/rare
  "defense_summary": string            // 1-3 sentence plain-English summary of the defense theory
}

Rules:
- "novelty" judges how routine that claim/defense is in litigation generally: "common" (boilerplate, seen constantly), "uncommon" (seen sometimes, fact-specific), "novel" (rare theory or unusual application).
- "authorities" inside allegations/defenses must be citation strings that also appear (or clearly belong) in the top-level "authorities" list.
- Use the exact citation form found in the document (e.g. "550 U.S. 544", "Fed. R. Civ. P. 12(b)(6)").
- If a field is genuinely absent, use an empty array or null — never invent parties or citations.
- Keep every string concise. No newlines inside strings.`;

function coerce(raw: string): CaseIntelligence {
  // The model should return bare JSON; strip any accidental fence.
  let s = raw.trim();
  const fence = s.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (fence) s = fence[1].trim();
  const start = s.indexOf("{");
  const end = s.lastIndexOf("}");
  if (start >= 0 && end > start) s = s.slice(start, end + 1);
  const obj = JSON.parse(s) as Partial<CaseIntelligence>;
  return {
    caption: obj.caption ?? null,
    entities: Array.isArray(obj.entities) ? obj.entities : [],
    allegations: Array.isArray(obj.allegations) ? obj.allegations : [],
    defenses: Array.isArray(obj.defenses) ? obj.defenses : [],
    authorities: Array.isArray(obj.authorities) ? obj.authorities : [],
    rarity: obj.rarity ?? null,
    defense_summary: obj.defense_summary ?? null,
  };
}

// Download + extract plain text for a ready document owned by the user.
export async function loadDocumentPlainText(
  documentId: string,
  userId: string,
  db: ReturnType<typeof createServerSupabase>,
): Promise<{ text: string; filename: string } | null> {
  // NOTE: the storage path lives on document_versions, not documents.
  const { data: doc } = await db
    .from("documents")
    .select("id, filename, file_type, current_version_id, status")
    .eq("id", documentId)
    .eq("user_id", userId)
    .maybeSingle();
  if (!doc) return null;

  const fileType = (doc as { file_type?: string }).file_type ?? "";
  const filename = (doc as { filename?: string }).filename ?? "document";

  // loadCurrentVersionBytes resolves the active version + downloads from R2.
  const current = await loadCurrentVersionBytes(documentId, db);
  if (!current) return null;
  const raw = current.bytes.buffer.slice(
    current.bytes.byteOffset,
    current.bytes.byteOffset + current.bytes.byteLength,
  ) as ArrayBuffer;

  let text = "";
  if (fileType === "pdf") {
    text = await extractPdfText(raw);
  } else {
    const mammoth = await import("mammoth");
    const result = await mammoth.extractRawText({ buffer: Buffer.from(raw) });
    text = result.value ?? "";
  }
  return { text, filename };
}

// Run the LLM extraction over document text.
export async function extractCaseIntelligence(
  text: string,
  model: string,
  apiKeys?: UserApiKeys,
): Promise<CaseIntelligence> {
  // Cap input so a huge brief doesn't blow the context / cost budget.
  const capped = text.slice(0, 60000);
  const out = await completeText({
    model,
    systemPrompt: EXTRACTION_SYSTEM,
    user: `Extract the case intelligence JSON from this document:\n\n${capped}`,
    maxTokens: 4096,
    apiKeys,
  });
  return coerce(out);
}

// Enrich extracted authorities with CourtListener citation counts so the
// Analytics page can cluster them landmark → rarely-cited. One batched
// citation-lookup call; statutes/rules simply don't resolve → cite_count null.
// Best-effort: any failure leaves the extraction untouched.
export async function enrichAuthorityCiteCounts(
  authorities: CaseAuthority[],
): Promise<CaseAuthority[]> {
  const token =
    process.env.COURTLISTENER_TOKEN ?? process.env.COURTLISTENER_API_TOKEN ?? "";
  if (!token || authorities.length === 0) return authorities;
  try {
    const hits = await citationLookup(
      authorities.map((a) => a.citation).join("\n"),
      token,
    );
    return authorities.map((a) => {
      const hit = hits.find(
        (h) =>
          h.status === "matched" &&
          (a.citation.includes(h.citation) || h.citation.includes(a.citation)),
      );
      return { ...a, cite_count: hit?.citation_count ?? null };
    });
  } catch (err) {
    console.warn(
      "[caseIntelligence] cite-count enrichment skipped:",
      err instanceof Error ? err.message : err,
    );
    return authorities;
  }
}

// Orchestrate: load text, extract, upsert the row. Returns the stored row.
export async function runCaseExtraction(params: {
  documentId: string;
  userId: string;
  projectId?: string | null;
  model: string;
  apiKeys?: UserApiKeys;
  db?: ReturnType<typeof createServerSupabase>;
}): Promise<{ ok: true; row: Record<string, unknown> } | { ok: false; error: string }> {
  const db = params.db ?? createServerSupabase();
  const loaded = await loadDocumentPlainText(params.documentId, params.userId, db);
  if (!loaded) return { ok: false, error: "Document not found or has no readable text." };
  if (!loaded.text.trim()) return { ok: false, error: "Document contains no extractable text." };

  let intel: CaseIntelligence;
  try {
    intel = await extractCaseIntelligence(loaded.text, params.model, params.apiKeys);
  } catch (err) {
    return { ok: false, error: `Extraction failed: ${err instanceof Error ? err.message : String(err)}` };
  }

  intel.authorities = await enrichAuthorityCiteCounts(intel.authorities);

  const { data, error } = await db
    .from("case_intelligence")
    .upsert(
      {
        user_id: params.userId,
        document_id: params.documentId,
        project_id: params.projectId ?? null,
        caption: intel.caption ?? loaded.filename,
        entities: intel.entities,
        allegations: intel.allegations,
        defenses: intel.defenses,
        authorities: intel.authorities,
        rarity: intel.rarity,
        defense_summary: intel.defense_summary,
        model: params.model,
        updated_at: new Date().toISOString(),
      },
      { onConflict: "document_id" },
    )
    .select("*")
    .single();
  if (error) return { ok: false, error: error.message };
  return { ok: true, row: data as Record<string, unknown> };
}
