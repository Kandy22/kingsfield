"use client";

import { useRef, useState } from "react";
import { PlusIcon, Upload, LayoutGridIcon, Loader2Icon } from "lucide-react";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { uploadStandaloneDocument } from "@/app/lib/mikeApi";
import type { Document } from "../shared/types";
import { cn } from "@/lib/utils";

interface Props {
    onSelectDoc: (doc: Document) => void;
    onBrowseAll: () => void;
    selectedDocIds?: string[];
    hideLabel?: boolean;
}

/**
 * Primary attach control — always high-contrast (not faded gray-400).
 */
export function AddDocButton({
    onSelectDoc,
    onBrowseAll,
    selectedDocIds = [],
    hideLabel = false,
}: Props) {
    const [isOpen, setIsOpen] = useState(false);
    const [uploading, setUploading] = useState(false);
    const fileInputRef = useRef<HTMLInputElement>(null);

    const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const files = Array.from(e.target.files || []);
        if (!files.length) return;
        setUploading(true);
        try {
            const uploaded = await Promise.all(
                files.map((f) => uploadStandaloneDocument(f)),
            );
            uploaded.forEach((doc) => onSelectDoc(doc));
        } catch (err) {
            console.error("Upload failed:", err);
        } finally {
            setUploading(false);
            if (fileInputRef.current) fileInputRef.current.value = "";
        }
    };

    const hasDocs = selectedDocIds.length > 0;

    return (
        <>
            <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.docx,.doc"
                multiple
                className="hidden"
                onChange={handleUpload}
            />
            <DropdownMenu onOpenChange={setIsOpen}>
                <DropdownMenuTrigger asChild>
                    <button
                        type="button"
                        disabled={uploading}
                        className={cn(
                            "flex items-center gap-1.5 h-8 rounded-lg px-2.5 text-sm font-medium transition-colors cursor-pointer",
                            "border border-gray-300 bg-white text-gray-900",
                            "hover:bg-gray-50 hover:border-gray-400",
                            "dark:border-white/20 dark:bg-white/10 dark:text-paper dark:hover:bg-white/15",
                            "disabled:opacity-60 disabled:cursor-wait",
                            isOpen && "ring-2 ring-gray-900/20 dark:ring-white/20",
                            hasDocs && "border-blue-500/50 bg-blue-50 text-blue-900 dark:bg-blue-500/15 dark:text-blue-100",
                        )}
                        title="Add documents"
                        aria-label="Add documents"
                    >
                        {uploading ? (
                            <Loader2Icon className="h-4 w-4 shrink-0 animate-spin" />
                        ) : hasDocs ? (
                            <span className="font-medium tabular-nums min-w-[1ch]">
                                {selectedDocIds.length}
                            </span>
                        ) : (
                            <PlusIcon
                                className={cn(
                                    "h-4 w-4 shrink-0 transition-transform duration-300",
                                    isOpen && "rotate-[135deg]",
                                )}
                            />
                        )}
                        <span className={hideLabel ? "hidden" : "hidden sm:inline"}>
                            {uploading
                                ? "Uploading…"
                                : hasDocs
                                  ? selectedDocIds.length === 1
                                      ? "Document"
                                      : "Documents"
                                  : "Documents"}
                        </span>
                    </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent
                    className="w-44 z-50"
                    side="bottom"
                    align="start"
                >
                    <DropdownMenuItem
                        className="cursor-pointer"
                        disabled={uploading}
                        onSelect={(e) => {
                            e.preventDefault();
                            fileInputRef.current?.click();
                        }}
                    >
                        {uploading ? (
                            <Loader2Icon className="h-4 w-4 mr-2 animate-spin text-gray-400" />
                        ) : (
                            <Upload className="h-4 w-4 mr-2 text-gray-500" />
                        )}
                        <span className="text-sm">
                            {uploading ? "Uploading…" : "Upload files"}
                        </span>
                    </DropdownMenuItem>
                    <DropdownMenuItem
                        className="cursor-pointer"
                        onClick={onBrowseAll}
                    >
                        <LayoutGridIcon className="h-4 w-4 mr-2 text-gray-500" />
                        <span className="text-sm">Browse all</span>
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>
        </>
    );
}
