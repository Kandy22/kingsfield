"use client";

import {
    useState,
    useCallback,
    useEffect,
    useRef,
    forwardRef,
    useImperativeHandle,
} from "react";
import {
    ArrowRight,
    Check,
    File,
    FileText,
    FolderOpen,
    Library,
    Square,
    X,
} from "lucide-react";
import { AddDocButton } from "./AddDocButton";
import { CaseExtractionCard } from "./CaseExtractionCard";
import { DocBinderPanel } from "./DocBinderPanel";
import { AddDocumentsModal } from "../shared/AddDocumentsModal";
import { AssistantWorkflowModal } from "./AssistantWorkflowModal";
import { ApiKeyMissingModal } from "../shared/ApiKeyMissingModal";
import { DocumentEditorModal } from "../shared/DocumentEditorModal";
import { ModelToggle } from "./ModelToggle";
import { useSelectedModel } from "@/app/hooks/useSelectedModel";
import { useUserProfile } from "@/contexts/UserProfileContext";
import {
    getModelProvider,
    isModelAvailable,
    type ModelProvider,
} from "@/app/lib/modelAvailability";
import type { CaseExtraction } from "@/app/lib/caseIntelligenceApi";
import type { Document, Message } from "../shared/types";
import { cn } from "@/lib/utils";

export interface ChatInputHandle {
    addDoc: (doc: Document) => void;
}

interface Props {
    onSubmit: (message: Message) => void;
    onCancel: () => void;
    isLoading: boolean;
    hideAddDocButton?: boolean;
    hideWorkflowButton?: boolean;
    onProjectsClick?: () => void;
    projectName?: string;
    projectCmNumber?: string | null;
}

export const ChatInput = forwardRef<ChatInputHandle, Props>(function ChatInput(
    {
        onSubmit,
        onCancel,
        isLoading,
        hideAddDocButton,
        hideWorkflowButton,
        onProjectsClick,
        projectName,
        projectCmNumber,
    }: Props,
    ref,
) {
    const [value, setValue] = useState("");
    const [attachedDocs, setAttachedDocs] = useState<Document[]>([]);
    const [selectedWorkflow, setSelectedWorkflow] = useState<{
        id: string;
        title: string;
    } | null>(null);
    const [model, setModel] = useSelectedModel();
    const { profile } = useUserProfile();
    const apiKeys = profile?.apiKeys;
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const controlsRef = useRef<HTMLDivElement>(null);
    const [compactControls, setCompactControls] = useState(false);
    const [docSelectorOpen, setDocSelectorOpen] = useState(false);
    const [workflowModalOpen, setWorkflowModalOpen] = useState(false);
    const [apiKeyModalProvider, setApiKeyModalProvider] =
        useState<ModelProvider | null>(null);
    const [editorDoc, setEditorDoc] = useState<Document | null>(null);
    const [editorAuthorities, setEditorAuthorities] = useState<string[]>([]);

    useImperativeHandle(ref, () => ({
        addDoc: (doc: Document) => {
            setAttachedDocs((prev) => {
                if (prev.some((d) => d.id === doc.id)) return prev;
                return [...prev, doc];
            });
            requestAnimationFrame(() => {
                const el = textareaRef.current;
                if (!el) return;
                el.focus();
                el.scrollIntoView({ block: "nearest", behavior: "smooth" });
            });
        },
    }));

    useEffect(() => {
        const el = controlsRef.current;
        if (!el) return;
        const update = () => setCompactControls(el.offsetWidth < 430);
        update();
        const observer = new ResizeObserver(update);
        observer.observe(el);
        return () => observer.disconnect();
    }, []);

    const focusComposer = useCallback(() => {
        // After attach/extract UI grows, keep the ask bar focused and on-screen.
        requestAnimationFrame(() => {
            const el = textareaRef.current;
            if (!el) return;
            el.focus({ preventScroll: false });
            el.scrollIntoView({ block: "nearest", behavior: "smooth" });
        });
    }, []);

    const handleAddDocFromProject = useCallback(
        (doc: Document) => {
            setAttachedDocs((prev) => {
                if (prev.some((d) => d.id === doc.id)) return prev;
                return [...prev, doc];
            });
            focusComposer();
        },
        [focusComposer],
    );

    const handleAddDocsFromSelector = useCallback(
        (selectedDocs: Document[]) => {
            setAttachedDocs((prev) => {
                const existing = new Set(prev.map((d) => d.id));
                return [
                    ...prev,
                    ...selectedDocs.filter((d) => !existing.has(d.id)),
                ];
            });
            focusComposer();
        },
        [focusComposer],
    );

    const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
        setValue(e.target.value);
        const el = e.target;
        el.style.height = "auto";
        el.style.height = `${el.scrollHeight}px`;
    };

    const handleSubmit = () => {
        const query = value.trim();
        if (!query || isLoading) return;
        if (apiKeys && !isModelAvailable(model, apiKeys)) {
            setApiKeyModalProvider(getModelProvider(model));
            return;
        }
        setValue("");
        if (textareaRef.current) {
            textareaRef.current.style.height = "auto";
        }

        const files = attachedDocs.map((d) => ({
            filename: d.filename,
            document_id: d.id,
        }));
        setAttachedDocs([]);
        const wf = selectedWorkflow;
        setSelectedWorkflow(null);

        onSubmit?.({
            role: "user",
            content: query,
            files: files.length > 0 ? files : undefined,
            workflow: wf ?? undefined,
            model,
        });
    };

    const handleActionClick = () => {
        if (isLoading) {
            onCancel();
        } else {
            handleSubmit();
        }
    };

    const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            handleSubmit();
        }
    };

    const openEditor = (doc: Document, extraction: CaseExtraction | null) => {
        setEditorDoc(doc);
        setEditorAuthorities(
            (extraction?.authorities ?? []).map((a) => a.citation).filter(Boolean),
        );
    };

    return (
        <>
            <div className="w-full space-y-3">
                {/* Composer first — natural chat home; binder only after attach */}
                <div className="relative z-10 rounded-[18px] border border-gray-200 bg-white shadow-sm md:rounded-[22px] dark:border-white/15 dark:bg-ink-2 dark:shadow-none">
                    {/* Attached chips */}
                    {(selectedWorkflow || attachedDocs.length > 0) && (
                        <div className="flex flex-wrap gap-1.5 px-2 pt-2">
                            {selectedWorkflow && (
                                <div className="inline-flex items-center gap-1 pl-2.5 pr-1 py-0.5 rounded-full text-xs bg-blue-600 text-white border border-white/20 shadow backdrop-blur-sm">
                                    <Library className="h-2.5 w-2.5 shrink-0" />
                                    <span className="max-w-[140px] truncate">
                                        {selectedWorkflow.title}
                                    </span>
                                    <button
                                        type="button"
                                        onClick={() =>
                                            setSelectedWorkflow(null)
                                        }
                                        className="rounded-full p-0.5 ml-0.5 text-white/60 hover:text-white hover:bg-white/20 transition-colors"
                                    >
                                        <X className="h-2.5 w-2.5" />
                                    </button>
                                </div>
                            )}
                            {attachedDocs.map((doc) => {
                                const ft = doc.file_type?.toLowerCase();
                                const isPdf = ft === "pdf";
                                return (
                                    <div
                                        key={doc.id}
                                        className="inline-flex items-center gap-1 rounded-[10px] border border-gray-200 bg-gray-100 py-0.5 pl-2 pr-1 text-xs text-gray-800 dark:border-white/10 dark:bg-white/10 dark:text-paper"
                                    >
                                        {isPdf ? (
                                            <FileText className="h-2.5 w-2.5 shrink-0 text-red-500" />
                                        ) : (
                                            <File className="h-2.5 w-2.5 shrink-0 text-blue-500" />
                                        )}
                                        <span className="max-w-[140px] truncate">
                                            {doc.filename}
                                        </span>
                                        <button
                                            type="button"
                                            onClick={() =>
                                                setAttachedDocs((prev) =>
                                                    prev.filter(
                                                        (d) => d.id !== doc.id,
                                                    ),
                                                )
                                            }
                                            className="ml-0.5 rounded-full p-0.5 text-gray-400 transition-colors hover:bg-gray-900/5 hover:text-gray-700 dark:hover:text-paper"
                                        >
                                            <X className="h-2.5 w-2.5" />
                                        </button>
                                    </div>
                                );
                            })}
                        </div>
                    )}

                    {/* Input — high contrast; always interactive after upload */}
                    <div className="px-4 pt-4">
                        <textarea
                            ref={textareaRef}
                            rows={2}
                            placeholder="Message, upload, or ask…"
                            value={value}
                            onChange={handleChange}
                            onKeyDown={handleKeyDown}
                            disabled={false}
                            aria-label="Message"
                            className={cn(
                                "w-full resize-none overflow-y-auto border-0 p-0 bg-transparent outline-none",
                                "text-base leading-6 max-h-48 min-h-[3rem]",
                                "text-gray-900 dark:text-paper",
                                "placeholder:text-gray-400 dark:placeholder:text-gray-500",
                                "caret-gray-900 dark:caret-paper",
                                "disabled:cursor-not-allowed",
                            )}
                        />
                    </div>

                    {/* Controls */}
                    <div
                        ref={controlsRef}
                        className="flex items-center justify-between md:p-2.5 p-2"
                    >
                        <div className="flex items-center gap-1">
                            {!hideAddDocButton && (
                                <AddDocButton
                                    onSelectDoc={handleAddDocFromProject}
                                    onBrowseAll={() => setDocSelectorOpen(true)}
                                    selectedDocIds={attachedDocs.map(
                                        (d) => d.id,
                                    )}
                                    hideLabel={compactControls}
                                />
                            )}
                            {!hideWorkflowButton && (
                                <button
                                    type="button"
                                    onClick={() => setWorkflowModalOpen(true)}
                                    aria-label="Open workflows"
                                    className={cn(
                                        "flex items-center gap-1.5 rounded-lg px-2 h-8 text-sm transition-colors",
                                        selectedWorkflow
                                            ? "text-blue-600 hover:bg-gray-100 dark:hover:bg-white/10"
                                            : "text-gray-400 hover:bg-gray-100 hover:text-gray-700 dark:hover:bg-white/10 dark:hover:text-paper",
                                    )}
                                >
                                    {selectedWorkflow ? (
                                        <Check className="h-3.5 w-3.5" />
                                    ) : (
                                        <Library className="h-3.5 w-3.5" />
                                    )}
                                    <span
                                        className={
                                            compactControls
                                                ? "hidden"
                                                : "hidden sm:inline"
                                        }
                                    >
                                        Workflows
                                    </span>
                                </button>
                            )}
                            {onProjectsClick && (
                                <button
                                    type="button"
                                    onClick={onProjectsClick}
                                    aria-label="Open projects"
                                    className={cn(
                                        "flex items-center gap-1.5 rounded-lg px-2 h-8 text-sm text-gray-400 hover:text-gray-700 transition-colors",
                                        "hover:bg-gray-100 dark:hover:bg-white/10 dark:hover:text-paper",
                                    )}
                                >
                                    <FolderOpen className="h-3.5 w-3.5" />
                                    <span className="hidden sm:inline">
                                        Projects
                                    </span>
                                </button>
                            )}
                        </div>

                        <div className="flex items-center gap-1">
                            <ModelToggle
                                value={model}
                                onChange={setModel}
                                apiKeys={apiKeys}
                            />
                            <button
                                type="button"
                                className={cn(
                                    "relative bg-gradient-to-b from-neutral-700 to-black text-white rounded-[10px] h-8 w-8 flex items-center justify-center cursor-pointer disabled:cursor-default disabled:from-neutral-600 disabled:to-black backdrop-blur-xl border border-white/30 active:enabled:scale-95 transition-all duration-150",
                                    "shadow-[0_5px_14px_rgba(15,23,42,0.18),inset_0_1px_0_rgba(255,255,255,0.24)]",
                                )}
                                onClick={handleActionClick}
                                disabled={!isLoading && !value.trim()}
                            >
                                {isLoading ? (
                                    <Square
                                        className="h-4 w-4"
                                        fill="currentColor"
                                        strokeWidth={0}
                                    />
                                ) : (
                                    <ArrowRight className="h-4 w-4" />
                                )}
                            </button>
                        </div>
                    </div>
                </div>

                {/* After attach: case extract + File Search binder */}
                {attachedDocs.length > 0 && (
                    <div className="space-y-2 max-h-[45vh] overflow-y-auto overscroll-contain">
                        {attachedDocs.map((doc) => (
                            <CaseExtractionCard
                                key={doc.id}
                                doc={doc}
                                onOpenEditor={openEditor}
                            />
                        ))}
                        <DocBinderPanel docs={attachedDocs} />
                    </div>
                )}
            </div>

            <AddDocumentsModal
                open={docSelectorOpen}
                onClose={() => setDocSelectorOpen(false)}
                onSelect={handleAddDocsFromSelector}
                breadcrumb={["Assistant", "Add Documents"]}
            />
            <AssistantWorkflowModal
                open={workflowModalOpen}
                onClose={() => setWorkflowModalOpen(false)}
                onSelect={(wf) => {
                    setSelectedWorkflow({ id: wf.id, title: wf.title });
                    setWorkflowModalOpen(false);
                }}
                projectName={projectName}
                projectCmNumber={projectCmNumber}
            />
            <ApiKeyMissingModal
                open={apiKeyModalProvider !== null}
                provider={apiKeyModalProvider}
                onClose={() => setApiKeyModalProvider(null)}
            />
            <DocumentEditorModal
                doc={editorDoc}
                authorities={editorAuthorities}
                onClose={() => {
                    setEditorDoc(null);
                    setEditorAuthorities([]);
                }}
            />
        </>
    );
});
