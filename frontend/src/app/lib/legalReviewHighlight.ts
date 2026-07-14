/**
 * Legal Review highlighting for document viewers.
 * Authorities / citations → blue. Prior filings / docket refs → green.
 * No multi-style modes — one Review paint pass.
 */

const AUTHORITY_RE =
    /\b(?:\d+\s+U\.?\s?S\.?\s+\d+|\d+\s+F\.\s?(?:2d|3d|4th)\s+\d+|\d+\s+S\.\s?Ct\.\s+\d+|\d+\s+L\.\s?Ed\.\s?(?:2d\s+)?\d+|(?:Fed\.\s?R\.\s?(?:Civ|Crim|Evid|App)\.\s?P\.?\s+\d+(?:\([a-z0-9]+\))?)|(?:\d+\s+U\.?S\.?C\.?\s*§?\s*\d+[a-z0-9\-]*)|(?:[A-Z][A-Za-z.'\-\s]{1,60}\s+v\.\s+[A-Z][A-Za-z.'\-\s]{1,60}(?:,\s*\d+\s+[A-Za-z.\s]+\d+)?))\b/g;

const PRIOR_FILING_RE =
    /\b(?:ECF\s+No\.?\s*\d+(?:-\d+)?|Dkt\.?\s*(?:No\.?\s*)?\d+(?:-\d+)?|Doc(?:ument)?\.?\s*No\.?\s*\d+(?:-\d+)?|Docket\s+(?:No\.?\s*)?\d+|Filing\s+No\.?\s*\d+|\[?\s*Doc\.?\s*\d+\s*\]?)\b/gi;

const HIGHLIGHT_ATTR = "data-kf-review";

function escapeRegExp(s: string): string {
    return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function wrapMatchesInTextNode(
    node: Text,
    pattern: RegExp,
    kind: "authority" | "prior-filing",
): void {
    const text = node.nodeValue ?? "";
    if (!text.trim()) return;
    pattern.lastIndex = 0;
    const matches = [...text.matchAll(pattern)];
    if (matches.length === 0) return;

    const frag = document.createDocumentFragment();
    let cursor = 0;
    for (const m of matches) {
        const start = m.index ?? 0;
        if (start < cursor) continue;
        if (start > cursor) {
            frag.appendChild(document.createTextNode(text.slice(cursor, start)));
        }
        const span = document.createElement("span");
        span.setAttribute(HIGHLIGHT_ATTR, kind);
        span.className =
            kind === "authority"
                ? "kf-review-authority"
                : "kf-review-prior-filing";
        span.textContent = m[0];
        frag.appendChild(span);
        cursor = start + m[0].length;
    }
    if (cursor < text.length) {
        frag.appendChild(document.createTextNode(text.slice(cursor)));
    }
    node.parentNode?.replaceChild(frag, node);
}

function walkTextNodes(root: HTMLElement, visit: (n: Text) => void): void {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes: Text[] = [];
    let n = walker.nextNode();
    while (n) {
        nodes.push(n as Text);
        n = walker.nextNode();
    }
    for (const text of nodes) {
        // Skip already-highlighted nodes
        const parent = text.parentElement;
        if (parent?.closest(`[${HIGHLIGHT_ATTR}]`)) continue;
        if (parent?.closest("script, style, ins, del")) continue;
        visit(text);
    }
}

/** Apply Review-mode semantic colors to a rendered document root. */
export function applyLegalReviewHighlights(
    root: HTMLElement,
    extraAuthorities: string[] = [],
): void {
    // Clear previous paint so re-render is clean
    root.querySelectorAll(`[${HIGHLIGHT_ATTR}]`).forEach((el) => {
        const parent = el.parentNode;
        if (!parent) return;
        parent.replaceChild(
            document.createTextNode(el.textContent ?? ""),
            el,
        );
        parent.normalize();
    });

    // Known authorities from case extraction (exact-ish phrase match)
    const cleaned = extraAuthorities
        .map((a) => a.trim())
        .filter((a) => a.length >= 4)
        .slice(0, 40);
    if (cleaned.length > 0) {
        const alt = cleaned.map(escapeRegExp).join("|");
        try {
            const exact = new RegExp(`(?:${alt})`, "gi");
            walkTextNodes(root, (node) =>
                wrapMatchesInTextNode(node, exact, "authority"),
            );
        } catch {
            /* ignore bad regex from odd citations */
        }
    }

    walkTextNodes(root, (node) => {
        wrapMatchesInTextNode(node, PRIOR_FILING_RE, "prior-filing");
        wrapMatchesInTextNode(node, AUTHORITY_RE, "authority");
    });
}

export const LEGAL_REVIEW_HIGHLIGHT_CSS = `
.kf-review-authority {
  color: #5B9BD5;
  background: rgba(43, 92, 230, 0.10);
  border-radius: 2px;
  padding: 0 1px;
}
.kf-review-prior-filing {
  color: #6FBF73;
  background: rgba(31, 138, 91, 0.12);
  border-radius: 2px;
  padding: 0 1px;
}
.dark .kf-review-authority,
[data-theme="dark"] .kf-review-authority {
  color: #7EB6E8;
  background: rgba(91, 155, 213, 0.16);
}
.dark .kf-review-prior-filing,
[data-theme="dark"] .kf-review-prior-filing {
  color: #8FD694;
  background: rgba(111, 191, 115, 0.14);
}
`;
