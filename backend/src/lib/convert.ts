import { promisify } from "util";
import { execSync } from "child_process";
import fs from "fs";
import JSZip from "jszip";

// Ported from upstream Mike (03e8acf, "find LibreOffice in the macOS app
// bundle"): the official macOS installer keeps soffice inside the app bundle
// and puts nothing on PATH, so a `which` check alone reports LibreOffice as
// missing on a Mac that has it. Explicit paths can also be set by env var.
const MAC_BUNDLE_SOFFICE = "/Applications/LibreOffice.app/Contents/MacOS/soffice";

function isExecutable(filePath: string): boolean {
  try {
    fs.accessSync(filePath, fs.constants.X_OK);
    return true;
  } catch {
    return false;
  }
}

function explicitSofficePaths(): string[] {
  return [process.env.SOFFICE_BINARY_PATH, process.env.LIBREOFFICE_BINARY_PATH]
    .filter((p): p is string => Boolean(p))
    .filter(isExecutable);
}

function libreOfficeAvailable(): boolean {
  if (explicitSofficePaths().length > 0 || isExecutable(MAC_BUNDLE_SOFFICE)) {
    return true;
  }
  try {
    execSync("which libreoffice soffice 2>/dev/null", { stdio: "pipe" });
    return true;
  } catch {
    return false;
  }
}

const LIBREOFFICE_AVAILABLE = libreOfficeAvailable();

const CONVERTER_UNAVAILABLE_MESSAGE =
  "LibreOffice (soffice) was not found, so DOCX→PDF conversion is unavailable. " +
  "Install LibreOffice or set SOFFICE_BINARY_PATH or LIBREOFFICE_BINARY_PATH " +
  "to the soffice executable, then restart the backend.";

let _convert:
  | ((buf: Buffer, ext: string, filter: undefined) => Promise<Buffer>)
  | null = null;

async function getConvert() {
  if (!_convert) {
    const libre = await import("libreoffice-convert");
    const sofficeBinaryPaths = explicitSofficePaths();
    const convertWithOptions = promisify(
      libre.default.convertWithOptions.bind(libre.default),
    );
    _convert = (buf, ext, filter) =>
      convertWithOptions(buf, ext, filter, { sofficeBinaryPaths });
  }
  return _convert;
}

/**
 * Some older Windows/Word archives store .docx entries with backslash
 * separators (e.g. `word\document.xml`). Mammoth and LibreOffice both look
 * up entries by exact string and miss those files, producing empty output
 * or conversion failures. Rewrite any such entries to the canonical
 * forward-slash form before handing the buffer off.
 */
export async function normalizeDocxZipPaths(buffer: Buffer): Promise<Buffer> {
  let zip: JSZip;
  try {
    zip = await JSZip.loadAsync(buffer);
  } catch {
    return buffer;
  }
  const renames: [string, string][] = [];
  zip.forEach((relativePath) => {
    if (relativePath.includes("\\")) {
      renames.push([relativePath, relativePath.replace(/\\/g, "/")]);
    }
  });
  if (renames.length === 0) return buffer;
  for (const [oldPath, newPath] of renames) {
    const entry = zip.file(oldPath);
    if (!entry) continue;
    const content = await entry.async("nodebuffer");
    zip.remove(oldPath);
    zip.file(newPath, content);
  }
  return zip.generateAsync({ type: "nodebuffer" });
}

/**
 * Convert a DOCX/DOC buffer to PDF using LibreOffice.
 * Throws if LibreOffice is not installed, not found, or conversion fails.
 * Times out after 30 seconds to prevent hanging when LibreOffice is missing.
 */
export async function docxToPdf(buffer: Buffer): Promise<Buffer> {
  if (!LIBREOFFICE_AVAILABLE) {
    throw new Error(CONVERTER_UNAVAILABLE_MESSAGE);
  }
  const convert = await getConvert();
  const normalized = await normalizeDocxZipPaths(buffer);
  return convert(normalized, ".pdf", undefined);
}

export function convertedPdfKey(userId: string, docId: string): string {
  return `converted-pdfs/${userId}/${docId}.pdf`;
}
