import fs from "fs";
import path from "path";
import https from "https";
import { URL } from "url";

export const ALLOWED_STATUTE_DOMAINS = new Set([
  "leg.colorado.gov",
  "www.congress.gov",
  "uscode.house.gov",
  "www.ecfr.gov",
  "www.federalregister.gov",
  "www.govinfo.gov",
  "constitution.congress.gov",
]);

const CORPUS_ROOT = path.join(process.cwd(), "data", "statute-corpus");

export function assertAllowedHost(url: string): URL {
  const parsed = new URL(url);
  const host = parsed.hostname.toLowerCase();
  if (!ALLOWED_STATUTE_DOMAINS.has(host)) {
    throw new Error(`Host not allowlisted for statute crawl: ${host}`);
  }
  return parsed;
}

function fetchText(url: string): Promise<string> {
  assertAllowedHost(url);
  return new Promise((resolve, reject) => {
    https
      .get(url, { headers: { "User-Agent": "Kingsfield-StatuteScanner/1.0" } }, (res) => {
        if (res.statusCode && res.statusCode >= 400) {
          reject(new Error(`HTTP ${res.statusCode} for ${url}`));
          return;
        }
        const chunks: Buffer[] = [];
        res.on("data", (c) => chunks.push(c));
        res.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
      })
      .on("error", reject);
  });
}

function htmlToMarkdown(html: string): string {
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, "")
    .replace(/<style[\s\S]*?<\/style>/gi, "")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export async function crawlStatutePage(
  url: string,
  jurisdiction: string,
): Promise<{ filePath: string; excerpt: string }> {
  const parsed = assertAllowedHost(url);
  const html = await fetchText(parsed.href);
  const text = htmlToMarkdown(html).slice(0, 120_000);
  const slug = parsed.pathname.replace(/[^a-z0-9]+/gi, "-").slice(0, 80) || "index";
  const dir = path.join(CORPUS_ROOT, jurisdiction);
  fs.mkdirSync(dir, { recursive: true });
  const filePath = path.join(dir, `${slug}.md`);
  const body = `# Source\n${parsed.href}\n\n${text}`;
  fs.writeFileSync(filePath, body, "utf8");
  return { filePath, excerpt: text.slice(0, 8000) };
}

export function loadCorpusIndex(jurisdiction: string): string {
  const indexPath = path.join(CORPUS_ROOT, jurisdiction, "index.md");
  if (fs.existsSync(indexPath)) {
    return fs.readFileSync(indexPath, "utf8");
  }
  return "";
}

export function findCorpusMatch(jurisdiction: string, query: string): string | null {
  const dir = path.join(CORPUS_ROOT, jurisdiction);
  if (!fs.existsSync(dir)) return null;
  const q = query.toLowerCase();
  for (const name of fs.readdirSync(dir)) {
    if (!name.endsWith(".md") || name === "index.md") continue;
    const full = path.join(dir, name);
    const text = fs.readFileSync(full, "utf8").toLowerCase();
    if (text.includes(q) || name.toLowerCase().includes(q.replace(/\s+/g, "-"))) {
      return fs.readFileSync(full, "utf8").slice(0, 24_000);
    }
  }
  return null;
}