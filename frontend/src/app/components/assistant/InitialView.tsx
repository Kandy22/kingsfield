"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { useUserProfile } from "@/contexts/UserProfileContext";
import { KingsfieldIcon } from "@/components/chat/mike-icon";
import { ChatInput } from "./ChatInput";
import { FeatureGuide } from "./FeatureGuide";
import { SelectAssistantProjectModal } from "./SelectAssistantProjectModal";
import type { Message } from "../shared/types";

interface InitialViewProps {
    onSubmit: (message: Message) => void;
}

const ICON_SIZE = 30;
const GAP = 12; // gap-4 = 1rem = 16px

export function InitialView({ onSubmit }: InitialViewProps) {
    const { user } = useAuth();
    const { profile } = useUserProfile();
    const [loaded, setLoaded] = useState(false);
    const [projectModalOpen, setProjectModalOpen] = useState(false);
    const [iconOffset, setIconOffset] = useState(0);
    const [textOffset, setTextOffset] = useState(0);
    const textRef = useRef<HTMLHeadingElement>(null);

    const username =
        profile?.displayName?.trim() || user?.email?.split("@")[0] || "there";

    useLayoutEffect(() => {
        if (!profile || !textRef.current) return;
        const h1Width = textRef.current.offsetWidth;
        setIconOffset((h1Width + GAP) / 2);
        setTextOffset((ICON_SIZE + GAP) / 2);
    }, [profile]);

    useEffect(() => {
        if (!iconOffset) return;
        const t = setTimeout(() => setLoaded(true), 100);
        return () => clearTimeout(t);
    }, [iconOffset]);

    return (
        <div className="flex flex-col h-full w-full min-h-0 overflow-y-auto px-6">
            {/* Scrollable home: when extract cards grow after upload, the
                ask bar must stay reachable (was justify-center + no scroll). */}
            <div className="flex flex-1 flex-col items-center justify-center min-h-full py-8 sm:py-12">
                <div className="flex flex-col items-center w-full max-w-4xl relative px-0 xl:px-8">
                    <div className="mb-8 sm:mb-10 relative flex items-center justify-center h-10 w-full shrink-0">
                        <div
                            className="absolute h-[30px] w-[30px] top-[-2px]"
                            style={{
                                left: "50%",
                                transform: loaded
                                    ? `translateX(calc(-50% - ${iconOffset}px))`
                                    : "translateX(-50%)",
                                transition:
                                    "transform 900ms cubic-bezier(0.25, 0.46, 0.45, 0.94)",
                            }}
                        >
                            <KingsfieldIcon size={ICON_SIZE} />
                        </div>
                        <h1
                            ref={textRef}
                            className="absolute text-4xl font-serif font-light text-gray-900 dark:text-paper whitespace-nowrap"
                            style={{
                                left: "50%",
                                transform: loaded
                                    ? `translateX(calc(-50% + ${textOffset}px))`
                                    : "translateX(-50%)",
                                opacity: loaded ? 1 : 0,
                                transition:
                                    "transform 900ms cubic-bezier(0.25, 0.46, 0.45, 0.94), opacity 800ms ease-in-out 300ms",
                            }}
                        >
                            Hi, {username}
                        </h1>
                    </div>

                    <div className="w-full shrink-0">
                        <ChatInput
                            onSubmit={onSubmit}
                            onCancel={() => {}}
                            isLoading={false}
                            onProjectsClick={() => setProjectModalOpen(true)}
                        />
                    </div>

                    <div className="text-center shrink-0">
                        <p className="text-xs py-3 mb-1 text-gray-500">
                            Every citation verified · Primary sources only · Not legal advice — legal knowledge.
                        </p>
                    </div>

                    <FeatureGuide />
                </div>
            </div>

            <SelectAssistantProjectModal
                open={projectModalOpen}
                onClose={() => setProjectModalOpen(false)}
            />
        </div>
    );
}
