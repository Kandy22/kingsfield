"use client";

/**
 * Full-width page definition strip — elegant, thin Helvetica Neue.
 * Use under PageHeader / page titles so section copy spans the content area
 * (not a half-width max-w-3xl column).
 */
export function SectionIntro({
    lead,
    children,
    className = "",
}: {
    /** Short label, e.g. "What a project is:" */
    lead: string;
    children: React.ReactNode;
    className?: string;
}) {
    return (
        <div className={`w-full px-6 pb-5 ${className}`}>
            <p className="text-sm font-light text-gray-600 dark:text-gray-400 leading-relaxed max-w-none">
                <span className="font-normal text-gray-900 dark:text-paper">
                    {lead}
                </span>{" "}
                {children}
            </p>
        </div>
    );
}
