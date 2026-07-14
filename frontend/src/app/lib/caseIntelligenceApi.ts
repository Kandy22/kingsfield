import { getApiBase } from "./apiBase";
import { supabase } from "@/lib/supabase";

export type Novelty = "common" | "uncommon" | "novel";

export interface CaseEntity {
    name: string;
    role: string;
    note?: string;
}

export interface CaseAllegation {
    claim: string;
    authorities: string[];
    strength?: string | null;
    novelty?: Novelty | null;
}

export interface CaseDefense {
    defense: string;
    responds_to?: string | null;
    authorities: string[];
    novelty?: Novelty | null;
}

export interface CaseAuthority {
    citation: string;
    proposition?: string;
    treatment?: string | null;
    cite_count?: number | null;
}

export interface CaseRarity {
    score: number;
    label: string;
    rationale: string;
}

export interface CaseExtraction {
    id: string;
    document_id: string;
    caption: string | null;
    entities: CaseEntity[];
    allegations: CaseAllegation[];
    defenses: CaseDefense[];
    authorities: CaseAuthority[];
    rarity: CaseRarity | null;
    defense_summary: string | null;
    updated_at: string;
}

export type ExtractionWaitResult =
    | { ok: true; extraction: CaseExtraction }
    | { ok: false; error: string };

async function authHeaders(): Promise<Record<string, string>> {
    const {
        data: { session },
    } = await supabase.auth.getSession();
    if (!session?.access_token) return {};
    return { Authorization: `Bearer ${session.access_token}` };
}

/** True when extract ran but body was empty (scan / stamp-only). */
export function isHollowExtraction(ex: CaseExtraction): boolean {
    const claims = ex.allegations?.length ?? 0;
    const defs = ex.defenses?.length ?? 0;
    const auths = ex.authorities?.length ?? 0;
    if (claims + defs + auths > 0) return false;
    const cap = (ex.caption ?? "").trim();
    // Docket-style captions like "1:25-cr-00503-JSR" with no body content
    if (/^\d+:\d{2}-[a-z]{2}-\d+/i.test(cap)) return true;
    if (!ex.defense_summary && (ex.entities?.length ?? 0) <= 2) return true;
    return false;
}

export async function fetchExtractionForDocument(
    documentId: string,
): Promise<CaseExtraction | null> {
    const headers = await authHeaders();
    const res = await fetch(
        `${getApiBase()}/api/analytics?documentId=${encodeURIComponent(documentId)}`,
        { headers },
    );
    if (!res.ok) return null;
    const data = (await res.json()) as { extractions?: CaseExtraction[] };
    return data.extractions?.[0] ?? null;
}

export async function runExtraction(
    documentId: string,
    projectId?: string | null,
): Promise<
    | { ok: true; extraction: CaseExtraction }
    | { ok: false; error: string }
> {
    const headers = await authHeaders();
    const res = await fetch(`${getApiBase()}/api/analytics/extract`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...headers },
        body: JSON.stringify({ documentId, projectId: projectId ?? null }),
    });
    const data = (await res.json().catch(() => ({}))) as {
        extraction?: CaseExtraction;
        detail?: string;
    };
    if (!res.ok) {
        return {
            ok: false,
            error:
                data.detail ??
                `Extraction failed (${res.status}). Try a text-based PDF or OCR first.`,
        };
    }
    if (!data.extraction) {
        return { ok: false, error: "Extraction returned no data." };
    }
    return { ok: true, extraction: data.extraction };
}

/**
 * Poll for an auto-extract started at upload time. After a short wait,
 * kick a manual extract once if nothing landed (covers race / silent failure).
 */
export async function waitForExtraction(
    documentId: string,
    opts?: {
        projectId?: string | null;
        timeoutMs?: number;
        intervalMs?: number;
        signal?: AbortSignal;
    },
): Promise<ExtractionWaitResult> {
    const timeoutMs = opts?.timeoutMs ?? 90_000;
    const intervalMs = opts?.intervalMs ?? 2_000;
    const started = Date.now();
    let kicked = false;
    let lastError: string | null = null;

    while (Date.now() - started < timeoutMs) {
        if (opts?.signal?.aborted) {
            return { ok: false, error: "Cancelled." };
        }
        const row = await fetchExtractionForDocument(documentId);
        if (row) {
            if (isHollowExtraction(row)) {
                return {
                    ok: false,
                    error:
                        "Extract found almost no body text — this PDF is likely a scan " +
                        "(image-only PACER filing). Allegations, authorities, and defenses " +
                        "cannot be read from header stamps alone. OCR the file or re-download " +
                        "a text PDF, then re-upload.",
                };
            }
            return { ok: true, extraction: row };
        }

        // After ~8s with no row, force one extract (covers failed fire-and-forget).
        if (!kicked && Date.now() - started > 8_000) {
            kicked = true;
            const forced = await runExtraction(documentId, opts?.projectId);
            if (forced.ok) {
                if (isHollowExtraction(forced.extraction)) {
                    return {
                        ok: false,
                        error:
                            "Extract found almost no body text — this PDF is likely a scan. " +
                            "OCR or re-upload a text-based PDF.",
                    };
                }
                return forced;
            }
            lastError = forced.error;
            // If sparse-text rejection, stop polling — no point waiting.
            if (/scan|image-only|extractable text|PACER|OCR/i.test(forced.error)) {
                return forced;
            }
        }

        await new Promise((r) => setTimeout(r, intervalMs));
    }
    return {
        ok: false,
        error:
            lastError ??
            "Extraction timed out. Check that the document has readable text, then try Analyze on Case Map.",
    };
}
