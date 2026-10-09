import { Router } from "express";
import { requireAuth } from "../middleware/auth";
import { createServerSupabase } from "../lib/supabase";
import { downloadFile } from "../lib/storage";
import {
    attachActiveVersionPaths,
    loadActiveVersion,
} from "../lib/documentVersions";
import { normalizeDocxZipPaths } from "../lib/convert";
import {
    isAbortError,
    runLLMStream,
    TABULAR_TOOLS,
    type ChatMessage,
    type TabularCellStore,
} from "../lib/chatTools";
import {
    completeText,
    providerForModel,
    streamChatWithTools,
    type Provider,
    type UserApiKeys,
} from "../lib/llm";
import { getUserModelSettings } from "../lib/userSettings";
import {
    checkProjectAccess,
    ensureReviewAccess,
    filterAccessibleDocumentIds,
} from "../lib/access";
import { safeErrorLog } from "../lib/safeError";
import {
    GENERIC_ERROR_MESSAGE,
    createBufferingSseWriter,
    createLimiter,
    failedReplyRecord,
    finalizeHeldOutput,
    gateCellContent,
    gateTitleText,
    startSseKeepalive,
    unverifiableCell,
    userTitleFallback,
    verifyDraftForSse,
} from "../middleware/hallucination_guard";

function formatPromptSuffix(format?: string, tags?: string[]): string {
    switch (format) {
        case "bulleted_list":
            return ' The "summary" field in your JSON response must be a markdown bulleted list only — no prose. Format: each item on its own line, prefixed with "* " (asterisk + single space), e.g.\n* First item\n* Second item\n* Third item';
        case "number":
            return ' The "summary" field in your JSON response must be a single number only. No units or explanation.';
        case "percentage":
            return ' The "summary" field in your JSON response must be a single percentage value only (e.g. 42%). No explanation.';
        case "monetary_amount":
            return ' The "summary" field in your JSON response must be the monetary value only, including currency symbol (e.g. $1,234.56). No explanation.';
        case "currency":
            return ' The "summary" field in your JSON response must contain only the currency code(s). Wrap each code in double square brackets, e.g. [[USD]] or [[EUR]]. No other text.';
        case "yes_no":
            return ' The "summary" field in your JSON response must be [[Yes]] or [[No]] only. The "reasoning" field MUST include an inline citation [[page:N||quote:verbatim excerpt ≤25 words]] pointing to the exact language in the document that supports the Yes/No answer.';
        case "date":
            return ' The "summary" field in your JSON response must be the date only in DD Month YYYY format (e.g. 1 January 2024). If a range, give both dates separated by an em dash. The "reasoning" field MUST include an inline citation [[page:N||quote:verbatim excerpt ≤25 words]] pointing to the exact place in the document where the date is found.';
        case "tag":
            return tags?.length
                ? ` The \"summary\" field in your JSON response must contain exactly one tag wrapped in double square brackets. Available tags: ${tags.map((t) => `[[${t}]]`).join(", ")}. No other text. The \"reasoning\" field MUST include an inline citation [[page:N||quote:verbatim excerpt ≤25 words]] pointing to the exact language in the document that supports the chosen tag.`
                : "";
        default:
            return "";
    }
}

export const tabularRouter = Router();

// Every piece of model-written cell text goes through Gate 1 (gateCellContent) before it is saved or
// sent: in /generate and /regenerate-cell on the way in, and again on every read in GET /:reviewId
// (a stored row is never trusted). A cell that is vetoed, pending, of unknown status, or that Gate 1
// could not check is replaced whole by a fixed marker; other cells are not affected.
// At most CELL_GATE_CONCURRENCY cells are in the gate at once (the gate itself runs at most 4
// children and answers gate_busy, a veto, past that). Module-level, so the cap holds across requests.
// A gate call that has not answered within CELL_GATE_TIMEOUT_MS is abandoned: its slot is freed, its
// cell gets the "could not be verified" marker, and its late answer is ignored. The limit sits above
// the gate's own worst case (30 s waiting for a child slot plus 30 s for the child) so the gate's own
// answer, a veto or a clean result, normally arrives first.
const CELL_GATE_CONCURRENCY = 2;
const CELL_GATE_TIMEOUT_MS = 75_000;
const limitCellGate = createLimiter(CELL_GATE_CONCURRENCY, {
    timeoutMs: CELL_GATE_TIMEOUT_MS,
});

/** Returned (502 detail) in place of a model-written column prompt that Gate 1 vetoed or could not check. */
const PROMPT_WITHHELD_MESSAGE =
    "The generated prompt was withheld because it could not be verified.";

/** The Gate 1 verifier and server-side error sink gateCellContent is given, for every cell and prompt gate. */
function cellGateOptions(db: ReturnType<typeof createServerSupabase>, route: string) {
    return {
        verify: (text: string) =>
            verifyDraftForSse(text, {
                courtListenerToken: process.env.COURTLISTENER_TOKEN ?? "",
                supabase: db,
            }),
        logError: (context: string, error: unknown) =>
            console.error(`[${route}] ${context}`, error),
    };
}

function providerLabel(provider: Provider): string {
    if (provider === "claude") return "Anthropic";
    if (provider === "openai") return "OpenAI";
    return "Gemini";
}

function missingModelApiKey(model: string, apiKeys: UserApiKeys) {
    const provider = providerForModel(model);
    if (apiKeys[provider]?.trim()) return null;
    return {
        provider,
        model,
        detail: `${providerLabel(provider)} API key is required to use ${model}. Add an API key or select a different tabular review model.`,
    };
}

// GET /tabular-review
tabularRouter.get("/", requireAuth, async (req, res) => {
    const userId = res.locals.userId as string;
    const userEmail = res.locals.userEmail as string | undefined;
    const db = createServerSupabase();

    const projectIdFilter =
        typeof req.query.project_id === "string" && req.query.project_id
            ? (req.query.project_id as string)
            : null;

    const { data, error } = await db.rpc("get_tabular_reviews_overview", {
        p_user_id: userId,
        p_user_email: userEmail ?? null,
        p_project_id: projectIdFilter,
    });
    if (error) return void res.status(500).json({ detail: error.message });

    res.json(data ?? []);
});

// POST /tabular-review
tabularRouter.post("/", requireAuth, async (req, res) => {
    const userId = res.locals.userId as string;
    const userEmail = res.locals.userEmail as string | undefined;
    const { title, document_ids, columns_config, workflow_id, project_id } =
        req.body as {
            title?: string;
            document_ids: string[];
            columns_config: { index: number; name: string; prompt: string }[];
            workflow_id?: string;
            project_id?: string;
        };

    const db = createServerSupabase();
    if (project_id) {
        const access = await checkProjectAccess(
            project_id,
            userId,
            userEmail,
            db,
        );
        if (!access.ok)
            return void res.status(404).json({ detail: "Project not found" });
    }
    const allowedDocumentIds = Array.isArray(document_ids)
        ? await filterAccessibleDocumentIds(
              document_ids,
              userId,
              userEmail,
              db,
          )
        : [];
    const { data: review, error } = await db
        .from("tabular_reviews")
        .insert({
            user_id: userId,
            title: title ?? null,
            columns_config,
            document_ids: allowedDocumentIds,
            project_id: project_id ?? null,
            workflow_id: workflow_id ?? null,
        })
        .select("*")
        .single();
    if (error || !review)
        return void res
            .status(500)
            .json({ detail: error?.message ?? "Failed to create review" });

    const cells = allowedDocumentIds.flatMap((docId) =>
        columns_config.map((col) => ({
            review_id: review.id,
            document_id: docId,
            column_index: col.index,
            status: "pending",
        })),
    );
    if (cells.length) await db.from("tabular_cells").insert(cells);

    res.status(201).json(review);

    // Fire-and-forget: run the case-intelligence extraction agent on each
    // document so it's ready in Analytics without a manual "Analyze" step.
    // Uploading to Tabular Review is the trigger, per the product spec.
    void (async () => {
        try {
            const { runCaseExtraction } = await import("../lib/caseIntelligence.js");
            const settings = await getUserModelSettings(userId, db);
            for (const docId of allowedDocumentIds) {
                const { data: existing } = await db
                    .from("case_intelligence")
                    .select("id")
                    .eq("document_id", docId)
                    .maybeSingle();
                if (existing) continue; // don't re-extract
                await runCaseExtraction({
                    documentId: docId,
                    userId,
                    projectId: project_id ?? null,
                    model: settings.tabular_model,
                    apiKeys: settings.api_keys,
                    db,
                });
            }
        } catch (err) {
            console.error("[tabular/create] auto case-extraction failed", err);
        }
    })();
});

// POST /tabular-review/prompt (must come before /:reviewId routes)
tabularRouter.post("/prompt", requireAuth, async (req, res) => {
    const userId = res.locals.userId as string;
    const title =
        typeof req.body.title === "string" ? req.body.title.trim() : "";
    if (!title)
        return void res.status(400).json({ detail: "title is required" });

    const format: string =
        typeof req.body.format === "string" ? req.body.format : "text";
    const documentName: string =
        typeof req.body.documentName === "string"
            ? req.body.documentName.trim()
            : "";
    const tags: string[] = Array.isArray(req.body.tags)
        ? req.body.tags.filter((t: unknown) => typeof t === "string")
        : [];

    const formatDescriptions: Record<string, string> = {
        text: "free-form text",
        bulleted_list: "a bulleted list",
        number: "a single number",
        percentage: "a percentage value",
        monetary_amount: "a monetary amount",
        currency: "a currency code",
        yes_no: "Yes or No",
        date: "a date",
        tag: tags.length ? `one of these tags: ${tags.join(", ")}` : "a tag",
    };
    const formatHint = formatDescriptions[format] ?? "free-form text";
    const tagsNote =
        format === "tag" && tags.length
            ? `\nAvailable tags: ${tags.join(", ")}`
            : "";
    const docNote = documentName ? `\nDocument type/name: ${documentName}` : "";

    const userMessage =
        `Column title: ${title}` +
        docNote +
        `\nExpected response format: ${formatHint}` +
        tagsNote +
        `\n\nWrite the best extraction prompt for a legal tabular review column with this title. ` +
        `Do NOT include any instruction about the response format in the prompt — ` +
        `format handling is applied separately and must not be duplicated inside the prompt text.`;

    try {
        const { title_model, api_keys } = await getUserModelSettings(userId);
        const raw = await completeText({
            model: title_model,
            systemPrompt:
                'You write high-quality column prompts for legal tabular review workflows. Return only valid JSON with a single field: {"prompt": string}. The prompt you write must focus solely on what to extract — never on how to format the response.',
            user: userMessage,
            maxTokens: 512,
            apiKeys: api_keys,
        });
        const parsed = JSON.parse(
            raw
                .replace(/^```(?:json)?\n?/i, "")
                .replace(/\n?```$/, "")
                .trim(),
        ) as { prompt?: unknown };
        if (typeof parsed.prompt === "string" && parsed.prompt.trim()) {
            const prompt = parsed.prompt.trim();
            // Gate 1 over the model-written prompt before it goes anywhere. A veto, or any failure
            // of the gate, returns the one fixed message below, never the model's text. The
            // frontend treats a non-2xx answer as a failed generation and leaves the field as is.
            const db = createServerSupabase();
            const gated = await limitCellGate(
                () =>
                    gateCellContent(
                        { summary: prompt, flag: "grey", reasoning: "" },
                        cellGateOptions(db, "tabular/prompt"),
                    ),
                () => unverifiableCell(),
            );
            if (gated.withheld) {
                return void res
                    .status(502)
                    .json({ detail: PROMPT_WITHHELD_MESSAGE });
            }
            res.json({ prompt, source: "llm" });
        } else {
            res.status(502).json({ detail: "LLM returned an empty prompt" });
        }
    } catch (err) {
        console.error("[tabular/prompt] error", safeErrorLog(err));
        res.status(502).json({ detail: "Failed to generate prompt from LLM" });
    }
});

// GET /tabular-review/:reviewId
tabularRouter.get("/:reviewId", requireAuth, async (req, res) => {
    const userId = res.locals.userId as string;
    const userEmail = res.locals.userEmail as string | undefined;
    const { reviewId } = req.params;
    const db = createServerSupabase();

    const { data: review, error } = await db
        .from("tabular_reviews")
        .select("*")
        .eq("id", reviewId)
        .single();
    if (error || !review)
        return void res.status(404).json({ detail: "Review not found" });
    const access = await ensureReviewAccess(review, userId, userEmail, db);
    if (!access.ok)
        return void res.status(404).json({ detail: "Review not found" });

    const { data: cells } = await db
        .from("tabular_cells")
        .select("*")
        .eq("review_id", reviewId);
    const cellDocIds = [...new Set((cells ?? []).map((c) => c.document_id))];
    const hasExplicitDocIds = Array.isArray(review.document_ids);
    const explicitDocIds = hasExplicitDocIds
        ? (review.document_ids as string[])
        : [];
    const docIds =
        hasExplicitDocIds
            ? explicitDocIds
            : cellDocIds;
    const docsResult =
        docIds.length > 0
            ? await db.from("documents").select("*").in("id", docIds)
            : { data: [] as Record<string, unknown>[] };
    const docs = (docsResult.data ?? []) as unknown as {
        id: string;
        current_version_id?: string | null;
    }[];
    await attachActiveVersionPaths(db, docs);

    // Stored cells are model-written text, and rows saved before the gate existed (or by any path
    // that skipped it) carry none. Every stored cell goes through Gate 1 again on every read, as
    // GET /council/:id does for stored sessions; a verification record already in the row is never
    // trusted (it can be stale, or forged in an old row), and the row itself is not rewritten.
    // Identical cell texts within one request are gated once.
    const gatedByText = new Map<
        string,
        ReturnType<typeof gateCellContent>
    >();
    const gateStoredCell = (parsed: NonNullable<ReturnType<typeof parseCellContent>>) => {
        const key = JSON.stringify([parsed.summary, parsed.flag ?? null, parsed.reasoning ?? ""]);
        let gated = gatedByText.get(key);
        if (!gated) {
            gated = limitCellGate(
                () =>
                    gateCellContent(
                        parsed,
                        cellGateOptions(db, "tabular/get-review"),
                    ),
                () => unverifiableCell(),
            );
            gatedByText.set(key, gated);
        }
        return gated;
    };
    const gatedCells = await Promise.all(
        (cells ?? []).map(async (cell) => {
            const parsed = parseCellContent(cell.content);
            // Only the cell columns the client reads are returned; `citations` (never written by
            // this server) is model-shaped free text and is not passed on.
            return {
                id: cell.id,
                review_id: cell.review_id,
                document_id: cell.document_id,
                column_index: cell.column_index,
                status: cell.status,
                created_at: cell.created_at,
                content: parsed ? (await gateStoredCell(parsed)).content : null,
            };
        }),
    );

    res.json({
        review: { ...review, is_owner: access.isOwner },
        cells: gatedCells,
        documents: docs,
    });
});

// GET /tabular-review/:reviewId/people
// Owner email + display_name plus member display_names — the analog of
// /projects/:id/people. Used by the standalone TR detail page's People
// modal so the roster can show display_names alongside emails.
tabularRouter.get("/:reviewId/people", requireAuth, async (req, res) => {
    const userId = res.locals.userId as string;
    const userEmail = res.locals.userEmail as string | undefined;
    const { reviewId } = req.params;
    const db = createServerSupabase();

    const { data: review } = await db
        .from("tabular_reviews")
        .select("id, user_id, project_id, shared_with")
        .eq("id", reviewId)
        .single();
    if (!review)
        return void res.status(404).json({ detail: "Review not found" });
    const access = await ensureReviewAccess(review, userId, userEmail, db);
    if (!access.ok)
        return void res.status(404).json({ detail: "Review not found" });

    const sharedWith: string[] = (
        Array.isArray(review.shared_with)
            ? (review.shared_with as string[])
            : []
    ).map((e) => (e ?? "").toLowerCase());

    // Same pattern as /projects/:id/people: walk auth.users to map emails
    // to user_ids, then pull display_names from user_profiles by user_id.
    const { data: usersData } = await db.auth.admin.listUsers({
        perPage: 1000,
    });
    const allUsers = usersData?.users ?? [];
    const userByEmail = new Map<string, { id: string; email: string }>();
    const userById = new Map<string, { id: string; email: string }>();
    for (const u of allUsers) {
        if (!u.email) continue;
        const lower = u.email.toLowerCase();
        userByEmail.set(lower, { id: u.id, email: u.email });
        userById.set(u.id, { id: u.id, email: u.email });
    }

    const memberUserIds: string[] = [];
    for (const email of sharedWith) {
        const u = userByEmail.get(email);
        if (u) memberUserIds.push(u.id);
    }

    const profileIds = [review.user_id as string, ...memberUserIds].filter(
        (x, i, arr) => arr.indexOf(x) === i,
    );

    const profileByUserId = new Map<string, string | null>();
    if (profileIds.length > 0) {
        const { data: profiles } = await db
            .from("user_profiles")
            .select("user_id, display_name")
            .in("user_id", profileIds);
        for (const p of profiles ?? []) {
            profileByUserId.set(
                p.user_id as string,
                (p.display_name as string | null) ?? null,
            );
        }
    }

    const ownerInfo = userById.get(review.user_id as string);
    res.json({
        owner: {
            user_id: review.user_id,
            email: ownerInfo?.email ?? null,
            display_name: profileByUserId.get(review.user_id as string) ?? null,
        },
        members: sharedWith.map((email) => {
            const u = userByEmail.get(email);
            const display_name = u ? (profileByUserId.get(u.id) ?? null) : null;
            return { email, display_name };
        }),
    });
});

// PATCH /tabular-review/:reviewId
tabularRouter.patch("/:reviewId", requireAuth, async (req, res) => {
    const userId = res.locals.userId as string;
    const userEmail = res.locals.userEmail as string | undefined;
    const { reviewId } = req.params;
    const updates: Record<string, unknown> = {};
    if (req.body.title != null) updates.title = req.body.title;
    const projectIdUpdateProvided = req.body.project_id !== undefined;
    const projectIdUpdate =
        req.body.project_id === null
            ? null
            : typeof req.body.project_id === "string" &&
                req.body.project_id.trim()
              ? req.body.project_id.trim()
              : undefined;
    if (projectIdUpdateProvided && projectIdUpdate === undefined) {
        return void res.status(400).json({
            detail: "project_id must be a non-empty string or null",
        });
    }
    // shared_with edits are owner-only — gated below after we know who's
    // making the call. Normalize lowercase + dedupe + drop empties.
    let sharedWithUpdate: string[] | undefined;
    if (Array.isArray(req.body.shared_with)) {
        const normalizedUserEmail = userEmail?.trim().toLowerCase();
        const seen = new Set<string>();
        const cleaned: string[] = [];
        for (const raw of req.body.shared_with) {
            if (typeof raw !== "string") continue;
            const e = raw.trim().toLowerCase();
            if (!e || seen.has(e)) continue;
            if (normalizedUserEmail && e === normalizedUserEmail) {
                return void res.status(400).json({
                    detail: "You cannot share a tabular review with yourself.",
                });
            }
            seen.add(e);
            cleaned.push(e);
        }
        sharedWithUpdate = cleaned;
    }
    updates.updated_at = new Date().toISOString();

    const db = createServerSupabase();
    const { data: existingReview, error: reviewError } = await db
        .from("tabular_reviews")
        .select("*")
        .eq("id", reviewId)
        .single();
    if (reviewError || !existingReview)
        return void res.status(404).json({ detail: "Review not found" });
    const access = await ensureReviewAccess(
        existingReview,
        userId,
        userEmail,
        db,
    );
    if (!access.ok)
        return void res.status(404).json({ detail: "Review not found" });
    if (req.body.columns_config != null) {
        if (!access.isOwner) {
            return void res.status(403).json({
                detail: "Only the review owner can change columns",
            });
        }
        updates.columns_config = req.body.columns_config;
    }
    if (sharedWithUpdate !== undefined) {
        if (!access.isOwner)
            return void res
                .status(403)
                .json({ detail: "Only the review owner can change sharing" });
        updates.shared_with = sharedWithUpdate;
    }
    if (projectIdUpdateProvided) {
        if (!access.isOwner) {
            return void res.status(403).json({
                detail: "Only the review owner can move a review",
            });
        }
        if (projectIdUpdate) {
            const projectAccess = await checkProjectAccess(
                projectIdUpdate,
                userId,
                userEmail,
                db,
            );
            if (!projectAccess.ok) {
                return void res
                    .status(404)
                    .json({ detail: "Target project not found" });
            }
        }
        updates.project_id = projectIdUpdate;
    }

    const { data: updatedReview, error: updateError } = await db
        .from("tabular_reviews")
        .update(updates)
        .eq("id", reviewId)
        .select("*")
        .single();
    if (updateError || !updatedReview)
        return void res.status(500).json({
            detail: updateError?.message ?? "Failed to update review",
        });

    let persistedDocumentIds: string[] | undefined;
    if (
        Array.isArray(req.body.columns_config) ||
        Array.isArray(req.body.document_ids)
    ) {
        const { data: existingCells } = await db
            .from("tabular_cells")
            .select("document_id,column_index")
            .eq("review_id", reviewId);
        const existingKeys = new Set(
            (existingCells ?? []).map(
                (cell) => `${cell.document_id}:${cell.column_index}`,
            ),
        );

        let documentIds: string[];

        if (Array.isArray(req.body.document_ids)) {
            // document_ids is the new source of truth — delete removed docs' cells
            const requestedDocIds = req.body.document_ids as string[];
            const existingDocIds = (existingCells ?? []).map(
                (cell) => cell.document_id,
            );
            const existingDocIdSet = new Set(existingDocIds);
            const newDocCandidates = requestedDocIds.filter(
                (id) => !existingDocIdSet.has(id),
            );
            const newDocAllowed = await filterAccessibleDocumentIds(
                newDocCandidates,
                userId,
                userEmail,
                db,
            );
            const newDocAllowedSet = new Set(newDocAllowed);
            const newDocIds = requestedDocIds.filter(
                (id) => existingDocIdSet.has(id) || newDocAllowedSet.has(id),
            );
            const removedDocIds = existingDocIds.filter(
                (id) => !newDocIds.includes(id),
            );

            if (removedDocIds.length > 0) {
                const { error: deleteError } = await db
                    .from("tabular_cells")
                    .delete()
                    .eq("review_id", reviewId)
                    .in("document_id", removedDocIds);
                if (deleteError)
                    return void res
                        .status(500)
                        .json({ detail: deleteError.message });
            }

            documentIds = newDocIds;
        } else {
            // No document change — derive from existing cells
            documentIds = [
                ...new Set(
                    (existingCells ?? []).map((cell) => cell.document_id),
                ),
            ];
        }

        if (Array.isArray(req.body.document_ids)) {
            persistedDocumentIds = documentIds;
            const { error: documentIdsError } = await db
                .from("tabular_reviews")
                .update({
                    document_ids: documentIds,
                    updated_at: new Date().toISOString(),
                })
                .eq("id", reviewId);
            if (documentIdsError)
                return void res.status(500).json({
                    detail: documentIdsError.message,
                });
        }

        const activeColumns = Array.isArray(req.body.columns_config)
            ? req.body.columns_config
            : (updatedReview.columns_config ?? []);
        const newCells = documentIds.flatMap((documentId) =>
            activeColumns
                .filter(
                    (column: { index: number }) =>
                        !existingKeys.has(`${documentId}:${column.index}`),
                )
                .map((column: { index: number }) => ({
                    review_id: reviewId,
                    document_id: documentId,
                    column_index: column.index,
                    status: "pending",
                })),
        );

        if (newCells.length > 0) {
            const { error: insertError } = await db
                .from("tabular_cells")
                .insert(newCells);
            if (insertError)
                return void res
                    .status(500)
                    .json({ detail: insertError.message });
        }
    }

    res.json({
        ...updatedReview,
        ...(persistedDocumentIds ? { document_ids: persistedDocumentIds } : {}),
    });
});

// DELETE /tabular-review/:reviewId
tabularRouter.delete("/:reviewId", requireAuth, async (req, res) => {
    const userId = res.locals.userId as string;
    const { reviewId } = req.params;
    const db = createServerSupabase();
    const { error } = await db
        .from("tabular_reviews")
        .delete()
        .eq("id", reviewId)
        .eq("user_id", userId);
    if (error) return void res.status(500).json({ detail: error.message });
    res.status(204).send();
});

// POST /tabular-review/:reviewId/clear-cells
// Reset cells to an empty/pending state for the given document_ids. Does not
// delete the rows — it blanks `content` and sets `status` back to "pending".
tabularRouter.post("/:reviewId/clear-cells", requireAuth, async (req, res) => {
    const userId = res.locals.userId as string;
    const userEmail = res.locals.userEmail as string | undefined;
    const { reviewId } = req.params;
    const { document_ids } = req.body as { document_ids?: string[] };

    if (!Array.isArray(document_ids) || document_ids.length === 0)
        return void res
            .status(400)
            .json({ detail: "document_ids is required" });

    const db = createServerSupabase();
    const { data: review, error: reviewError } = await db
        .from("tabular_reviews")
        .select("id, user_id, project_id")
        .eq("id", reviewId)
        .single();
    if (reviewError || !review)
        return void res.status(404).json({ detail: "Review not found" });
    const access = await ensureReviewAccess(review, userId, userEmail, db);
    if (!access.ok)
        return void res.status(404).json({ detail: "Review not found" });

    const { error } = await db
        .from("tabular_cells")
        .update({ content: null, status: "pending" })
        .eq("review_id", reviewId)
        .in("document_id", document_ids);
    if (error) return void res.status(500).json({ detail: error.message });
    res.status(204).send();
});

// POST /tabular-review/:reviewId/regenerate-cell
tabularRouter.post(
    "/:reviewId/regenerate-cell",
    requireAuth,
    async (req, res) => {
        const userId = res.locals.userId as string;
        const userEmail = res.locals.userEmail as string | undefined;
        const { reviewId } = req.params;
        const { document_id, column_index } = req.body as {
            document_id: string;
            column_index: number;
        };

        if (!document_id || column_index == null)
            return void res
                .status(400)
                .json({ detail: "document_id and column_index are required" });

        const db = createServerSupabase();
        const { data: review, error: reviewError } = await db
            .from("tabular_reviews")
            .select("*")
            .eq("id", reviewId)
            .single();
        if (reviewError || !review)
            return void res.status(404).json({ detail: "Review not found" });
        const access = await ensureReviewAccess(review, userId, userEmail, db);
        if (!access.ok)
            return void res.status(404).json({ detail: "Review not found" });

        const column = (
            review.columns_config as {
                index: number;
                name: string;
                prompt: string;
                format?: string;
                tags?: string[];
            }[]
        ).find((c) => c.index === column_index);
        if (!column)
            return void res.status(400).json({ detail: "Column not found" });

        const docAllowed = await filterAccessibleDocumentIds(
            [document_id],
            userId,
            userEmail,
            db,
        );
        if (docAllowed.length === 0)
            return void res.status(404).json({ detail: "Document not found" });
        const { data: doc } = await db
            .from("documents")
            .select("id, current_version_id")
            .eq("id", document_id)
            .single();
        if (!doc)
            return void res.status(404).json({ detail: "Document not found" });
        const docActive = await loadActiveVersion(document_id, db);

        const { tabular_model, api_keys } = await getUserModelSettings(
            userId,
            db,
        );
        const missingKey = missingModelApiKey(tabular_model, api_keys);
        if (missingKey) {
            return void res.status(422).json({
                code: "missing_api_key",
                ...missingKey,
            });
        }

        await db
            .from("tabular_cells")
            .update({ status: "generating", content: null })
            .eq("review_id", reviewId)
            .eq("document_id", document_id)
            .eq("column_index", column_index);

        let markdown = "";
        if (docActive) {
            const buf = await downloadFile(docActive.storage_path);
            if (buf) {
                try {
                    markdown =
                        docActive.file_type === "pdf"
                            ? await extractPdfMarkdown(buf)
                            : await extractDocxMarkdown(buf);
                } catch (err) {
                    console.error(
                        `[regenerate-cell] extraction error doc=${document_id}`,
                        safeErrorLog(err),
                    );
                }
            }
        }

        // Anything that fails from here on marks the cell errored and answers with fixed text only.
        const markCellError = async () => {
            try {
                await db
                    .from("tabular_cells")
                    .update({ status: "error" })
                    .eq("review_id", reviewId)
                    .eq("document_id", document_id)
                    .eq("column_index", column_index);
            } catch (err) {
                console.error(
                    "[regenerate-cell] failed to mark the cell errored",
                    safeErrorLog(err),
                );
            }
        };

        try {
            const result = await queryTabularCell(
                tabular_model,
                docActive?.filename?.trim() || "Untitled document",
                markdown,
                column.prompt,
                column.format,
                column.tags,
                api_keys,
            );

            if (!result) {
                await markCellError();
                return void res.status(500).json({ detail: "Generation failed" });
            }

            // Gate 1 first, same as /generate: what is saved and returned is gated.content (the
            // model's cell, or the fixed marker) with its client-safe verification record, never
            // `result`. Saved equals returned.
            const gated = await limitCellGate(
                () =>
                    gateCellContent(
                        result,
                        cellGateOptions(db, "tabular/regenerate-cell"),
                    ),
                () => unverifiableCell(),
            );

            const { error: cellSaveError } = await db
                .from("tabular_cells")
                .update({
                    content: JSON.stringify(gated.content),
                    status: "done",
                })
                .eq("review_id", reviewId)
                .eq("document_id", document_id)
                .eq("column_index", column_index);
            if (cellSaveError) {
                // Not saved, so not returned.
                console.error(
                    `[regenerate-cell] failed to save cell doc=${document_id} col=${column_index}`,
                    safeErrorLog(cellSaveError),
                );
                await markCellError();
                return void res.status(500).json({ detail: "Generation failed" });
            }

            res.json(gated.content);
        } catch (err) {
            console.error("[regenerate-cell] error", safeErrorLog(err));
            await markCellError();
            if (!res.headersSent)
                res.status(500).json({ detail: "Generation failed" });
        }
    },
);

// POST /tabular-review/:reviewId/generate
tabularRouter.post("/:reviewId/generate", requireAuth, async (req, res) => {
    const userId = res.locals.userId as string;
    const userEmail = res.locals.userEmail as string | undefined;
    const { reviewId } = req.params;
    const db = createServerSupabase();

    const { data: review, error: reviewError } = await db
        .from("tabular_reviews")
        .select("*")
        .eq("id", reviewId)
        .single();
    if (reviewError || !review)
        return void res.status(404).json({ detail: "Review not found" });
    const access = await ensureReviewAccess(review, userId, userEmail, db);
    if (!access.ok)
        return void res.status(404).json({ detail: "Review not found" });

    const columns: {
        index: number;
        name: string;
        prompt: string;
        format?: string;
        tags?: string[];
    }[] = review.columns_config ?? [];
    if (columns.length === 0)
        return void res.status(400).json({ detail: "No columns configured" });

    const { data: cells } = await db
        .from("tabular_cells")
        .select("*")
        .eq("review_id", reviewId);
    const cellMap = new Map<string, Record<string, unknown>>();
    for (const cell of cells ?? [])
        cellMap.set(`${cell.document_id}:${cell.column_index}`, cell);

    const docIds = [...new Set((cells ?? []).map((c) => c.document_id))];
    const allowedDocIds = new Set(
        await filterAccessibleDocumentIds(docIds, userId, userEmail, db),
    );
    let docs: Record<string, unknown>[] = [];
    if (docIds.length > 0) {
        const filteredIds = docIds.filter((id) => allowedDocIds.has(id));
        const { data } =
            filteredIds.length > 0
                ? await db
                      .from("documents")
                      .select("id, current_version_id")
                      .in("id", filteredIds)
                : { data: [] as Record<string, unknown>[] };
        docs = data ?? [];
    } else if (review.project_id) {
        const { data } = await db
            .from("documents")
            .select("id, current_version_id")
            .eq("project_id", review.project_id)
            .order("created_at", { ascending: true });
        docs = data ?? [];
    }
    await attachActiveVersionPaths(
        db,
        docs as {
            id: string;
            current_version_id?: string | null;
        }[],
    );

    const { tabular_model, api_keys } = await getUserModelSettings(userId, db);
    const missingKey = missingModelApiKey(tabular_model, api_keys);
    if (missingKey) {
        return void res.status(422).json({
            code: "missing_api_key",
            ...missingKey,
        });
    }

    res.setHeader("Content-Type", "text/event-stream");
    res.setHeader("Cache-Control", "no-cache");
    res.setHeader("Connection", "keep-alive");
    res.setHeader("X-Accel-Buffering", "no");
    res.flushHeaders();

    const write = (line: string) => res.write(line);

    try {
        await Promise.all(
            docs.map(async (doc) => {
                const docId = doc.id as string;
                let markdown = "";

                const filename =
                    (typeof doc.filename === "string" && doc.filename.trim()
                        ? doc.filename.trim()
                        : "Untitled document");
                const storagePath =
                    typeof doc.storage_path === "string" ? doc.storage_path : "";
                const fileType =
                    typeof doc.file_type === "string" ? doc.file_type : "";
                if (storagePath) {
                    const buf = await downloadFile(storagePath);
                    if (buf) {
                        try {
                            markdown =
                                fileType === "pdf"
                                    ? await extractPdfMarkdown(buf)
                                    : await extractDocxMarkdown(buf);
                        } catch (err) {
                            console.error(
                                `[tabular/generate] extraction error doc=${docId}`,
                                safeErrorLog(err),
                            );
                        }
                    }
                }

                // Filter to only columns that need processing
                const columnsToProcess = columns.filter((col) => {
                    const cell = cellMap.get(`${docId}:${col.index}`);
                    return !(cell?.status === "done" && cell?.content);
                });
                if (columnsToProcess.length === 0) return;

                // Mark all as generating upfront
                for (const col of columnsToProcess) {
                    write(
                        `data: ${JSON.stringify({ type: "cell_update", document_id: docId, column_index: col.index, content: null, status: "generating" })}\n\n`,
                    );
                    const existingCell = cellMap.get(`${docId}:${col.index}`);
                    if (existingCell) {
                        await db
                            .from("tabular_cells")
                            .update({ status: "generating", content: null })
                            .eq("id", existingCell.id);
                    } else {
                        await db.from("tabular_cells").insert({
                            review_id: reviewId,
                            document_id: docId,
                            column_index: col.index,
                            status: "generating",
                        });
                    }
                }

                // Single LLM call for all columns, streaming one JSON line per column
                const receivedColumns = new Set<number>();
                try {
                    await queryTabularAllColumns(
                        tabular_model,
                        filename,
                        markdown,
                        columnsToProcess,
                        async (columnIndex, result) => {
                            // Gate 1 first: the cell is saved and sent as gated.content (the
                            // model's cell, or the fixed marker) with its client-safe verification
                            // record, never as `result`. Saved equals sent.
                            const gated = await limitCellGate(
                                () =>
                                    gateCellContent(
                                        result,
                                        cellGateOptions(db, "tabular/generate"),
                                    ),
                                () => unverifiableCell(),
                            );
                            const { error: cellSaveError } = await db
                                .from("tabular_cells")
                                .update({
                                    content: JSON.stringify(gated.content),
                                    status: "done",
                                })
                                .eq("review_id", reviewId)
                                .eq("document_id", docId)
                                .eq("column_index", columnIndex);
                            if (cellSaveError) {
                                // Not saved, so not sent: the cell falls through to the error marking below.
                                console.error(
                                    `[tabular/generate] failed to save cell doc=${docId} col=${columnIndex}`,
                                    safeErrorLog(cellSaveError),
                                );
                                return;
                            }
                            receivedColumns.add(columnIndex);
                            write(
                                `data: ${JSON.stringify({ type: "cell_update", document_id: docId, column_index: columnIndex, content: gated.content, status: "done" })}\n\n`,
                            );
                        },
                        api_keys,
                    );
                } catch (err) {
                    console.error(
                        `[tabular/generate] queryTabularAllColumns error doc=${docId}`,
                        safeErrorLog(err),
                    );
                }

                // Mark any columns the LLM didn't return as error
                for (const col of columnsToProcess) {
                    if (!receivedColumns.has(col.index)) {
                        await db
                            .from("tabular_cells")
                            .update({ status: "error" })
                            .eq("review_id", reviewId)
                            .eq("document_id", docId)
                            .eq("column_index", col.index);
                        write(
                            `data: ${JSON.stringify({ type: "cell_update", document_id: docId, column_index: col.index, content: null, status: "error" })}\n\n`,
                        );
                    }
                }
            }),
        );

        write("data: [DONE]\n\n");
    } catch (err) {
        console.error("[tabular/generate] stream error", safeErrorLog(err));
        try {
            // Fixed text only: no provider, exception or database text reaches the browser.
            write(
                `data: ${JSON.stringify({ type: "error", message: GENERIC_ERROR_MESSAGE })}\n\ndata: [DONE]\n\n`,
            );
        } catch {
            /* ignore */
        }
    } finally {
        res.end();
    }
});

// GET /tabular-review/:reviewId/chats — list chats (metadata only, no messages)
tabularRouter.get("/:reviewId/chats", requireAuth, async (req, res) => {
    const userId = res.locals.userId as string;
    const userEmail = res.locals.userEmail as string | undefined;
    const { reviewId } = req.params;
    const db = createServerSupabase();

    // Verify access (owner or shared-project member).
    const { data: review, error } = await db
        .from("tabular_reviews")
        .select("id, user_id, project_id")
        .eq("id", reviewId)
        .single();
    if (error || !review)
        return void res.status(404).json({ detail: "Review not found" });
    const access = await ensureReviewAccess(review, userId, userEmail, db);
    if (!access.ok)
        return void res.status(404).json({ detail: "Review not found" });

    // Show every member's chats for the review (collaborative), not just
    // the requester's. Per-chat access is gated above by review access.
    const { data: chats } = await db
        .from("tabular_review_chats")
        .select("id, title, created_at, updated_at, user_id")
        .eq("review_id", reviewId)
        .order("updated_at", { ascending: false });

    const gatedChats = await Promise.all((chats ?? []).map(async (chat) => {
        if (typeof chat.title !== "string" || !chat.title) return chat;
        const gated = await gateTitleText(chat.title, "Misc. Query", cellGateOptions(db, "tabular/chats"));
        return { ...chat, title: gated.title };
    }));
    res.json(gatedChats);
});

// DELETE /tabular-review/:reviewId/chats/:chatId — delete a single chat
tabularRouter.delete(
    "/:reviewId/chats/:chatId",
    requireAuth,
    async (req, res) => {
        const userId = res.locals.userId as string;
        const { chatId } = req.params;
        const db = createServerSupabase();
        // Owner-only delete — sibling collaborators shouldn't be able to wipe
        // each other's threads.
        const { error } = await db
            .from("tabular_review_chats")
            .delete()
            .eq("id", chatId)
            .eq("user_id", userId);
        if (error) return void res.status(500).json({ detail: error.message });
        res.status(204).send();
    },
);

// GET /tabular-review/:reviewId/chats/:chatId/messages — messages for a single chat
tabularRouter.get(
    "/:reviewId/chats/:chatId/messages",
    requireAuth,
    async (req, res) => {
        const userId = res.locals.userId as string;
        const userEmail = res.locals.userEmail as string | undefined;
        const { reviewId, chatId } = req.params;
        const db = createServerSupabase();

        const { data: review } = await db
            .from("tabular_reviews")
            .select("id, user_id, project_id")
            .eq("id", reviewId)
            .single();
        if (!review)
            return void res.status(404).json({ detail: "Review not found" });
        const access = await ensureReviewAccess(review, userId, userEmail, db);
        if (!access.ok)
            return void res.status(404).json({ detail: "Review not found" });

        const { data: chat, error: chatError } = await db
            .from("tabular_review_chats")
            .select("id, review_id")
            .eq("id", chatId)
            .single();
        if (chatError || !chat || chat.review_id !== reviewId)
            return void res.status(404).json({ detail: "Chat not found" });

        const { data: messages } = await db
            .from("tabular_review_chat_messages")
            .select("id, role, content, annotations, created_at")
            .eq("chat_id", chatId)
            .order("created_at", { ascending: true });

        res.json(messages ?? []);
    },
);

// ---------------------------------------------------------------------------
// Tabular citation parsing
// ---------------------------------------------------------------------------

const TABULAR_CITATIONS_BLOCK_RE = /<CITATIONS>\s*([\s\S]*?)\s*<\/CITATIONS>/;

function parseTabularCitations(text: string): unknown[] {
    const match = text.match(TABULAR_CITATIONS_BLOCK_RE);
    if (!match) return [];
    try {
        const parsed: unknown = JSON.parse(match[1]);
        return Array.isArray(parsed) ? parsed : [];
    } catch {
        return [];
    }
}

/** A finite, non-negative integer: the only thing a model-supplied ref / col_index / row_index may be. */
function isChipIndex(v: unknown): v is number {
    return typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
}

/** A name read from the review's own columns or documents; never anything the model wrote. */
function ownName(v: unknown): string | null {
    return typeof v === "string" && v.trim() ? v : null;
}

// A tabular chip is built field by field. ref, col_index and row_index must be finite non-negative
// integers (a chip with anything else is dropped whole); col_name and doc_name come only from the
// review's real columns and documents, or from a fixed fallback with no model text; any other key
// the model wrote is not copied. The one model-written string left is `quote`, which Gate 1 checks
// (finalizeHeldOutput with allowTabularCitations) before the chip is sent or saved.
const CHIP_UNKNOWN_COLUMN = "Unknown column";
const CHIP_UNKNOWN_DOCUMENT = "Unknown document";

function extractTabularAnnotations(
    fullText: string,
    tabularStore: TabularCellStore,
) {
    const chips: {
        type: "tabular_citation";
        ref: number;
        col_index: number;
        row_index: number;
        col_name: string;
        doc_name: string;
        quote: string;
    }[] = [];
    for (const c of parseTabularCitations(fullText)) {
        if (!c || typeof c !== "object" || Array.isArray(c)) continue;
        const { ref, col_index, row_index, quote } = c as Record<
            string,
            unknown
        >;
        if (!isChipIndex(ref) || !isChipIndex(col_index) || !isChipIndex(row_index))
            continue;
        if (typeof quote !== "string") continue;
        chips.push({
            type: "tabular_citation",
            ref,
            col_index,
            row_index,
            col_name:
                ownName(tabularStore.columns[col_index]?.name) ??
                CHIP_UNKNOWN_COLUMN,
            doc_name:
                ownName(tabularStore.documents[row_index]?.filename) ??
                CHIP_UNKNOWN_DOCUMENT,
            quote,
        });
    }
    return chips;
}

// ---------------------------------------------------------------------------
// Build messages for tabular chat
// ---------------------------------------------------------------------------

function buildTabularMessages(
    messages: ChatMessage[],
    tabularStore: TabularCellStore,
    reviewTitle: string,
): unknown[] {
    const docList = tabularStore.documents
        .map((d, i) => `- ROW:${i} "${d.filename}"`)
        .join("\n");
    const colList = tabularStore.columns
        .map((c, i) => `- COL:${i} "${c.name}"`)
        .join("\n");

    const systemContent = `You are Kingsfield, an AI legal assistant. You are helping with the tabular review titled "${reviewTitle}".

The review extracts specific fields from multiple legal documents into a structured table.
You do NOT have the cell content yet — call read_table_cells to fetch the cells you need before answering.

DOCUMENTS (rows):
${docList || "- (none)"}

COLUMNS (fields):
${colList || "- (none)"}

TABULAR CITATION INSTRUCTIONS:
When you reference specific cell content, place a numbered marker [1], [2], etc. inline in your prose at the point of reference.

After your complete response, append a <CITATIONS> block containing a JSON array with one entry per marker:

<CITATIONS>
[
  {"ref": 1, "col_index": 0, "row_index": 2, "quote": "verbatim text from the cell"},
  {"ref": 2, "col_index": 1, "row_index": 0, "quote": "another excerpt"}
]
</CITATIONS>

Rules:
- col_index and row_index are 0-based (matching the COL/ROW numbers listed above)
- Only cite cells you have read via read_table_cells
- quote should be verbatim text from the cell's summary
- Omit <CITATIONS> if you make no citations
- Do not fabricate cell content
- Answer in clear, concise prose. You may use markdown formatting.`;

    const formatted: unknown[] = [{ role: "system", content: systemContent }];
    for (const msg of messages) {
        formatted.push({ role: msg.role, content: msg.content ?? "" });
    }
    return formatted;
}

// ---------------------------------------------------------------------------
// POST /tabular-review/:reviewId/chat — agentic streaming
// ---------------------------------------------------------------------------

// POST /tabular-review/:reviewId/chat
tabularRouter.post("/:reviewId/chat", requireAuth, async (req, res) => {
    const userId = res.locals.userId as string;
    const userEmail = res.locals.userEmail as string | undefined;
    const { reviewId } = req.params;
    const {
        messages,
        chat_id: existingChatId,
        review_title: clientReviewTitle,
        project_name: clientProjectName,
    } = req.body as {
        messages: ChatMessage[];
        chat_id?: string;
        review_title?: string;
        project_name?: string;
    };

    const lastUser = [...(messages ?? [])]
        .reverse()
        .find((m) => m.role === "user");
    if (!lastUser?.content?.trim()) {
        return void res
            .status(400)
            .json({ detail: "messages must include a user message" });
    }

    const db = createServerSupabase();
    const { data: review, error } = await db
        .from("tabular_reviews")
        .select("*")
        .eq("id", reviewId)
        .single();
    if (error || !review)
        return void res.status(404).json({ detail: "Review not found" });
    const reviewAccess = await ensureReviewAccess(
        review,
        userId,
        userEmail,
        db,
    );
    if (!reviewAccess.ok)
        return void res.status(404).json({ detail: "Review not found" });

    // Fetch all cells and documents for this review
    const { data: cells } = await db
        .from("tabular_cells")
        .select("*")
        .eq("review_id", reviewId);

    const docIds = [
        ...new Set((cells ?? []).map((c: any) => c.document_id as string)),
    ];
    let docs: {
        id: string;
        filename: string;
        current_version_id?: string | null;
    }[] = [];
    if (docIds.length > 0) {
        const { data } = await db
            .from("documents")
            .select("id, current_version_id")
            .in("id", docIds)
            .order("created_at", { ascending: true });
        const attachedDocs = (data ?? []) as {
            id: string;
            current_version_id?: string | null;
            filename?: string | null;
        }[];
        await attachActiveVersionPaths(db, attachedDocs);
        docs = attachedDocs.map((doc) => ({
            ...doc,
            filename:
                (typeof doc.filename === "string" && doc.filename.trim()) ||
                "Untitled document",
        }));
    }

    const sortedColumns = (
        (review.columns_config ?? []) as { index: number; name: string }[]
    ).sort((a, b) => a.index - b.index);

    const tabularStore: TabularCellStore = {
        columns: sortedColumns,
        documents: docs,
        cells: new Map(
            (cells ?? []).map((c: any) => [
                `${c.column_index}:${c.document_id}`,
                parseCellContent(c.content),
            ]),
        ),
    };

    const { tabular_model, api_keys } = await getUserModelSettings(userId, db);
    const missingKey = missingModelApiKey(tabular_model, api_keys);
    if (missingKey) {
        return void res.status(422).json({
            code: "missing_api_key",
            ...missingKey,
        });
    }

    // Create or verify chat record
    let chatId = existingChatId ?? null;
    let chatTitle: string | null = null;
    const isFirstExchange =
        messages.filter((m) => m.role === "user").length === 1;

    if (chatId) {
        // The chat must belong to this exact review and to the requester.
        // Review access alone is not enough: otherwise a user could reuse one
        // of their chats from a different review in this route.
        const { data: existing } = await db
            .from("tabular_review_chats")
            .select("id, title, review_id, user_id")
            .eq("id", chatId)
            .single();
        const canUse =
            !!existing &&
            existing.review_id === reviewId &&
            existing.user_id === userId;
        if (!canUse || !existing) chatId = null;
        else chatTitle = existing.title;
    }

    if (!chatId) {
        const { data: newChat } = await db
            .from("tabular_review_chats")
            .insert({ review_id: reviewId, user_id: userId })
            .select("id, title")
            .single();
        chatId = newChat?.id ?? null;
        chatTitle = newChat?.title ?? null;
    }

    // Persist user message
    if (chatId) {
        await db.from("tabular_review_chat_messages").insert({
            chat_id: chatId,
            role: "user",
            content: lastUser.content,
        });
    }

    const apiMessages = buildTabularMessages(
        messages,
        tabularStore,
        review.title || "Untitled Review",
    );

    res.setHeader("Content-Type", "text/event-stream");
    res.setHeader("Cache-Control", "no-cache");
    res.setHeader("Connection", "keep-alive");
    res.setHeader("X-Accel-Buffering", "no");
    res.flushHeaders();
    const write = (line: string) => res.write(line);
    // Model-written output is held server-side until Gate 1 has run.
    const buffered = createBufferingSseWriter(write);
    const streamAbort = new AbortController();
    let streamFinished = false;
    // True once the finalized reply is in tabular_review_chat_messages. After that the catch only logs.
    let replySaved = false;
    // Held output is invisible to the browser; ping until it is released.
    const keepalive = startSseKeepalive(write);
    res.on("close", () => {
        keepalive.stop();
        if (!streamFinished) streamAbort.abort();
    });
    // The 'close' event may already have fired during the awaits above and never fires again.
    if (res.destroyed || res.writableEnded) streamAbort.abort();

    try {
        // A client that is already gone never starts the model.
        if (streamAbort.signal.aborted) {
            throw Object.assign(new Error("Stream aborted."), { name: "AbortError" });
        }
        if (chatId) {
            write(`data: ${JSON.stringify({ type: "chat_id", chatId })}\n\n`);
        }

        const { fullText, events, annotations } = await runLLMStream({
            apiMessages,
            docStore: new Map(),
            docIndex: {},
            userId,
            db,
            write: buffered.write,
            extraTools: TABULAR_TOOLS,
            includeResearchTools: false,
            tabularStore,
            buildCitations: (text) =>
                extractTabularAnnotations(text, tabularStore),
            model: tabular_model,
            apiKeys: api_keys,
            signal: streamAbort.signal,
        });

        // Gate 1 over the whole reply decides what is released: unchanged, or withheld
        // whole (never rewritten). The saved message is exactly what is sent.
        const finalized = await finalizeHeldOutput({
            held: buffered.takeHeld(),
            events,
            annotations,
            fullText,
            allowTabularCitations: true,
            verify: (text) =>
                verifyDraftForSse(text, {
                    courtListenerToken: process.env.COURTLISTENER_TOKEN ?? "",
                    supabase: db,
                }),
        });

        // Save first, then send: a failed save is caught below, before the
        // browser has been given a reply that was never stored.
        if (chatId) {
            const { error: replySaveError } = await db
                .from("tabular_review_chat_messages")
                .insert({
                    chat_id: chatId,
                    role: "assistant",
                    content: finalized.savedEvents.length
                        ? finalized.savedEvents
                        : null,
                    // Sent tabular citation chips plus the one client-safe verification record.
                    annotations: finalized.savedAnnotations,
                });
            if (replySaveError) {
                console.error(
                    "[tabular/chat] failed to save reply",
                    safeErrorLog(replySaveError),
                );
                throw new Error("Failed to save the reply.");
            }
        }
        replySaved = true;
        keepalive.stop();
        for (const line of finalized.linesToSend) write(line);
        const verification = finalized.verification;
        write(
            `data: ${JSON.stringify({
                type: "verification",
                verdicts: verification.verdicts,
                hasVetoes: verification.hasVetoes,
                hasConditional: verification.hasConditional,
                error: verification.error,
            })}\n\n`,
        );
        if (chatId) {
            await db
                .from("tabular_review_chats")
                .update({ updated_at: new Date().toISOString() })
                .eq("id", chatId);
        }

        // Title on the first exchange. The model's title is Gate 1 checked as the exact string that is
        // saved and sent; on any veto, pending status, gate failure or model failure the title is the
        // start of the user's own first message (user text, not gated), never the model's text. A
        // failure here only logs: the reply is already saved and sent.
        if (chatId && isFirstExchange && !chatTitle && lastUser.content) {
            const fallbackTitle = userTitleFallback(lastUser.content);
            let title = fallbackTitle;
            try {
                const { title_model } = await getUserModelSettings(userId, db);
                const modelTitle = await generateChatTitle(
                    title_model,
                    lastUser.content,
                    {
                        reviewTitle: clientReviewTitle ?? review.title ?? null,
                        projectName: clientProjectName ?? null,
                    },
                    api_keys,
                );
                if (modelTitle) {
                    const gatedTitle = await gateTitleText(
                        modelTitle,
                        fallbackTitle,
                        cellGateOptions(db, "tabular/chat"),
                    );
                    title = gatedTitle.title;
                }
            } catch (titleErr) {
                console.error("[tabular/chat] title", safeErrorLog(titleErr));
                title = fallbackTitle;
            }
            if (title) {
                await db
                    .from("tabular_review_chats")
                    .update({ title })
                    .eq("id", chatId);
                write(
                    `data: ${JSON.stringify({ type: "chat_title", chatId, title })}\n\n`,
                );
            }
        }
    } catch (err) {
        keepalive.stop();
        if (replySaved) {
            // The verified reply is already saved (and sent): nothing more is saved or sent.
            console.error(
                "[tabular/chat] error after the reply was saved:",
                safeErrorLog(err),
            );
            return;
        }
        // Anything the model wrote before this point, its tool results and any
        // annotations are dropped. Only a fixed marker is saved.
        const aborted = isAbortError(err);
        if (aborted) {
            console.log("[tabular/chat] client aborted stream", { chatId });
        } else {
            console.error("[tabular/chat] error", safeErrorLog(err));
        }
        const failedReply = failedReplyRecord(aborted ? "aborted" : "failed");
        if (chatId) {
            try {
                const { error: saveError } = await db
                    .from("tabular_review_chat_messages")
                    .insert({
                        chat_id: chatId,
                        role: "assistant",
                        content: failedReply.events,
                        annotations: failedReply.annotations,
                    });
                if (saveError)
                    console.error(
                        "[tabular/chat] failed to save marker",
                        safeErrorLog(saveError),
                    );
                await db
                    .from("tabular_review_chats")
                    .update({ updated_at: new Date().toISOString() })
                    .eq("id", chatId);
            } catch (saveErr) {
                console.error(
                    "[tabular/chat] failed to save marker",
                    safeErrorLog(saveErr),
                );
            }
        }
        // Aborted: the client is gone, nothing is written. Failed: the fixed error event, then [DONE].
        try {
            for (const line of failedReply.sseLines) write(line);
        } catch {
            /* ignore */
        }
    } finally {
        keepalive.stop();
        streamFinished = true;
        res.end();
    }
});

function parseCellContent(
    raw: unknown,
): { summary: string; flag?: string; reasoning?: string } | null {
    if (!raw) return null;
    if (typeof raw === "object" && raw !== null && "summary" in raw) {
        const c = raw as {
            summary?: unknown;
            flag?: unknown;
            reasoning?: unknown;
        };
        return {
            summary: String(c.summary ?? ""),
            flag: (["green", "grey", "yellow", "red"] as const).includes(
                c.flag as "green",
            )
                ? (c.flag as string)
                : undefined,
            reasoning: typeof c.reasoning === "string" ? c.reasoning : "",
        };
    }
    if (typeof raw === "string") {
        try {
            const p = JSON.parse(raw) as {
                summary?: unknown;
                value?: unknown;
                flag?: unknown;
                reasoning?: unknown;
            };
            return {
                summary: String(p.summary ?? p.value ?? "").trim(),
                flag: (["green", "grey", "yellow", "red"] as const).includes(
                    p.flag as "green",
                )
                    ? (p.flag as string)
                    : undefined,
                reasoning: typeof p.reasoning === "string" ? p.reasoning : "",
            };
        } catch {
            return { summary: raw, flag: "grey", reasoning: "" };
        }
    }
    return null;
}

async function queryTabularCell(
    model: string,
    filename: string,
    documentText: string,
    columnPrompt: string,
    format?: string,
    tags?: string[],
    apiKeys?: import("../lib/llm").UserApiKeys,
) {
    const suffix = formatPromptSuffix(format as never, tags);
    const fullPrompt = `${columnPrompt}${suffix} If not found, state "Not Found". Leave all reasoning and explanation in the "reasoning" field only.`;

    const EXTRACTION_SYSTEM = `You are a legal document analyst. Return ONLY valid JSON:
{"summary": string, "flag": "green"|"grey"|"yellow"|"red", "reasoning": string}

The "summary" and "reasoning" field values may use markdown formatting (bullets, bold, italics, etc.) — the values are still plain JSON strings (escape newlines as \\n), but the text inside will be rendered as markdown in the UI.

The "summary" field must contain only the extracted value with inline citations — no explanation or reasoning. Every factual claim in "summary" must be followed immediately by a citation in the format [[page:N||quote:exact quoted text]], where N is the page number and the quote is a short verbatim excerpt (≤ 25 words). The quote must be narrowly scoped to the specific claim it supports — extract only the exact words that support that statement, not the surrounding sentence or paragraph. Do not have multiple claims share the same long quote; if two different statements need different evidence, give each its own short, narrowly-scoped quote. All reasoning and explanation belongs in "reasoning" only, which may also contain citations.`;

    let raw: string;
    try {
        raw = await completeText({
            model,
            systemPrompt: EXTRACTION_SYSTEM,
            user: `Document: ${filename}\n\n${documentText.slice(0, 120_000)}\n\n---\nInstruction: ${fullPrompt}`,
            maxTokens: 2048,
            apiKeys,
        });
    } catch (err) {
        console.error("[queryTabularCell] completion failed", safeErrorLog(err));
        return null;
    }
    try {
        const parsed = JSON.parse(
            raw
                .replace(/^```(?:json)?\n?/i, "")
                .replace(/\n?```$/, "")
                .trim(),
        ) as {
            summary?: unknown;
            value?: unknown;
            flag?: unknown;
            reasoning?: unknown;
        };
        return {
            summary:
                String(parsed.summary ?? parsed.value ?? "").trim() ||
                "Not addressed",
            flag: (["green", "grey", "yellow", "red"] as const).includes(
                parsed.flag as "green",
            )
                ? (parsed.flag as "green")
                : "grey",
            reasoning: String(parsed.reasoning ?? ""),
        };
    } catch {
        return raw.trim()
            ? {
                  summary: raw.trim().slice(0, 500),
                  flag: "grey" as const,
                  reasoning: "",
              }
            : null;
    }
}

async function generateChatTitle(
    model: string,
    firstUserMessage: string,
    context?: { reviewTitle?: string | null; projectName?: string | null },
    apiKeys?: import("../lib/llm").UserApiKeys,
): Promise<string | null> {
    try {
        const contextLines: string[] = [];
        if (context?.projectName)
            contextLines.push(`Project: ${context.projectName}`);
        if (context?.reviewTitle)
            contextLines.push(`Tabular review: ${context.reviewTitle}`);
        const contextBlock = contextLines.length
            ? `This chat is in the context of a tabular review.\n${contextLines.join("\n")}\n\n`
            : "";

        const raw = await completeText({
            model,
            user: `${contextBlock}Generate a short title (4-6 words) for a chat that starts with the message below. The title should reflect the user's specific question, not the review or project name. Return only the title, no punctuation, no quotes:\n\n${firstUserMessage}`,
            maxTokens: 64,
            apiKeys,
        });
        return raw.trim().slice(0, 80) || null;
    } catch {
        return null;
    }
}

function buildTabularContext(
    columns: any[],
    docs: any[],
    cells: any[],
): string {
    const lines: string[] = [
        "# Tabular Review Context\n",
        "Columns (0-based index):",
    ];
    columns.forEach((col: any, i: number) =>
        lines.push(`- COL:${i} → "${col.name}"`),
    );
    lines.push("", "Documents (0-based row index):");
    docs.forEach((doc: any, i: number) =>
        lines.push(`- ROW:${i} → "${doc.filename}"`),
    );
    lines.push("", "## Table Data\n");
    lines.push(`| Document | ${columns.map((c: any) => c.name).join(" | ")} |`);
    lines.push(`|---|${columns.map(() => "---").join("|")}|`);
    docs.forEach((doc: any, rowIdx: number) => {
        const rowCells = columns.map((col: any, colPos: number) => {
            const cell = cells.find(
                (c: any) =>
                    c.document_id === doc.id && c.column_index === col.index,
            ) as any;
            if (
                !cell ||
                cell.status === "pending" ||
                cell.status === "generating"
            ) {
                return `(pending) [[COL:${colPos}||ROW:${rowIdx}]]`;
            }
            if (cell.status === "error") {
                return `(error) [[COL:${colPos}||ROW:${rowIdx}]]`;
            }
            const content = parseCellContent(cell.content);
            const summary = content?.summary?.trim() || "(not yet generated)";
            const truncated =
                summary.length > 400 ? summary.slice(0, 400) + "…" : summary;
            return `${truncated} [[COL:${colPos}||ROW:${rowIdx}]]`;
        });
        lines.push(
            `| ROW:${rowIdx} ${doc.filename} | ${rowCells.join(" | ")} |`,
        );
    });
    return lines.join("\n");
}

type CellResult = {
    summary: string;
    flag: "green" | "grey" | "yellow" | "red";
    reasoning: string;
};
type Column = {
    index: number;
    name: string;
    prompt: string;
    format?: string;
    tags?: string[];
};

async function queryTabularAllColumns(
    model: string,
    filename: string,
    documentText: string,
    columns: Column[],
    onResult: (columnIndex: number, result: CellResult) => Promise<void>,
    apiKeys?: import("../lib/llm").UserApiKeys,
): Promise<void> {
    const columnsDesc = columns
        .map((col) => {
            const suffix = formatPromptSuffix(col.format as never, col.tags);
            const fullPrompt = `${col.prompt}${suffix} If not found, state "Not Found".`;
            return `Column ${col.index} — "${col.name}": ${fullPrompt}`;
        })
        .join("\n");

    const SYSTEM = `You are a legal document analyst. Extract information for each column listed below.

For each column, output exactly one minified JSON object on its own line (no line breaks inside the JSON), then a newline. Process columns in order and output each result as soon as you finish it.

Line format:
{"column_index": <N>, "summary": <string>, "flag": <"green"|"grey"|"yellow"|"red">, "reasoning": <string>}

Rules:
- "summary": the extracted value with inline citations [[page:N||quote:verbatim excerpt ≤25 words]] after every factual claim. No explanation or reasoning here. Quotes must be narrowly scoped to the specific claim — extract only the exact supporting words, not the full surrounding sentence. Do not reuse one long quote across multiple statements; give each claim its own short, precise quote.
- "flag": green = standard/favorable, yellow = needs attention, red = problematic/unfavorable, grey = neutral/not found
- "reasoning": brief explanation of the extraction
- The "summary" and "reasoning" string VALUES may use markdown (bullets, bold, italics, etc.) — escape newlines as \\n inside the JSON string. This markdown is rendered in the UI.
- Output ONLY the JSON lines themselves. Do NOT wrap the response in markdown code fences (e.g. \`\`\`json), and do not add any preamble or summary.`;

    const USER = `Document: ${filename}\n\n${documentText.slice(0, 120_000)}\n\n---\nColumns to extract:\n${columnsDesc}`;

    let contentBuffer = "";
    const pending: Promise<unknown>[] = [];

    const processLine = async (line: string) => {
        const trimmed = line.trim();
        if (!trimmed) return;
        try {
            const parsed = JSON.parse(trimmed) as {
                column_index?: unknown;
                summary?: unknown;
                flag?: unknown;
                reasoning?: unknown;
            };
            if (typeof parsed.column_index !== "number") return;
            const col = columns.find((c) => c.index === parsed.column_index);
            if (!col) return;
            await onResult(parsed.column_index, {
                summary: String(parsed.summary ?? "").trim() || "Not addressed",
                flag: (["green", "grey", "yellow", "red"] as const).includes(
                    parsed.flag as "green",
                )
                    ? (parsed.flag as CellResult["flag"])
                    : "grey",
                reasoning: String(parsed.reasoning ?? ""),
            });
        } catch {
            // malformed line — skip
        }
    };

    try {
        await streamChatWithTools({
            model,
            systemPrompt: SYSTEM,
            messages: [{ role: "user", content: USER }],
            tools: [],
            apiKeys,
            callbacks: {
                onContentDelta: (delta) => {
                    contentBuffer += delta;
                    let newlineIdx: number;
                    while ((newlineIdx = contentBuffer.indexOf("\n")) !== -1) {
                        const completedLine = contentBuffer.slice(
                            0,
                            newlineIdx,
                        );
                        contentBuffer = contentBuffer.slice(newlineIdx + 1);
                        pending.push(processLine(completedLine));
                    }
                },
            },
        });
    } catch (err) {
        console.error("[queryTabularAllColumns] stream failed", safeErrorLog(err));
    }

    if (contentBuffer.trim()) pending.push(processLine(contentBuffer));
    await Promise.all(pending);
}

async function extractPdfMarkdown(buf: ArrayBuffer): Promise<string> {
    try {
        const pdfjsLib = await import(
            "pdfjs-dist/legacy/build/pdf.mjs" as string
        );
        const pdf = await (
            pdfjsLib as unknown as {
                getDocument: (opts: unknown) => {
                    promise: Promise<{
                        numPages: number;
                        getPage: (n: number) => Promise<{
                            getTextContent: () => Promise<{
                                items: { str?: string; hasEOL?: boolean }[];
                            }>;
                        }>;
                    }>;
                };
            }
        ).getDocument({ data: new Uint8Array(buf) }).promise;
        const pages: string[] = [];
        for (let i = 1; i <= pdf.numPages; i++) {
            const page = await pdf.getPage(i);
            const tc = await page.getTextContent();
            const text = tc.items
                .filter((it): it is { str: string } => "str" in it)
                .map((it) => it.str)
                .join(" ")
                .trim();
            if (text) pages.push(`## Page ${i}\n\n${text}`);
        }
        return pages.join("\n\n");
    } catch {
        return "";
    }
}

async function extractDocxMarkdown(buf: ArrayBuffer): Promise<string> {
    try {
        const mammoth = await import("mammoth");
        const normalized = await normalizeDocxZipPaths(Buffer.from(buf));
        const { value: html } = await mammoth.convertToHtml({
            buffer: normalized,
        });
        return html
            .replace(
                /<h([1-6])[^>]*>(.*?)<\/h\1>/gi,
                (_, l, t) => "#".repeat(Number(l)) + " " + t + "\n\n",
            )
            .replace(/<strong[^>]*>(.*?)<\/strong>/gi, "**$1**")
            .replace(/<li[^>]*>(.*?)<\/li>/gi, "- $1\n")
            .replace(/<p[^>]*>(.*?)<\/p>/gi, "$1\n\n")
            .replace(/<[^>]+>/g, "")
            .replace(/&nbsp;/g, " ")
            .replace(/&amp;/g, "&")
            .replace(/&lt;/g, "<")
            .replace(/&gt;/g, ">")
            .replace(/\n{3,}/g, "\n\n")
            .trim();
    } catch {
        return "";
    }
}
