# Aaron Ray — Executive Credential Synthesis

**Instrument Design Tier Package**

**Specialization**  
AI Emotional Benchmarking • Forensic Audiovisual Analysis • Artificial Senses Systems

---

## Deliverables

| File | Purpose | Size |
|------|---------|------|
| `Aaron-Ray-Executive-Credential-Synthesis.pptx` | Primary deck (6 slides, fully editable) | 138 KB |
| `Aaron-Ray-Executive-Credential-Synthesis.pdf` | Print-ready / shareable version | 85 KB |

**Recommended starting point:** Open the `.pptx` in PowerPoint or Keynote. Use the `.pdf` for email or print.

---

## Output Locations

**Easy copies (workspace root):**
- `/Users/aaronray/Aaron-Ray-Executive-Credential-Synthesis.pptx`
- `/Users/aaronray/Aaron-Ray-Executive-Credential-Synthesis.pdf`

**Full package directory (all artifacts + source):**
- `/Users/aaronray/aaron-ray-credentials/`

Inside this folder you will also find:
- `slide-1.jpg` … `slide-6.jpg` — High-resolution (160 DPI) individual slide renders (for visual QA and review)
- `credentials-grid.jpg` — 3-column overview grid of the entire deck
- `generate-credential-deck.js` — The exact Node.js script that produced the deck
- `unpacked/` — Raw PPTX XML (useful for advanced hand-editing if needed)
- `package.json` + `node_modules/` — Build dependencies (pptxgenjs)

---

## Design System: Instrument Design Tier

- **Colors**
  - Navy (title bg): `#051428`
  - Navy (text): `#0B1E3A`
  - Cream (content bg): `#F2EFE6`
  - Gold (rules, accents, numerals, subheads): `#C9A96E`

- **Typography**
  - Headers / display: Bebas Neue (condensed, authoritative)
  - Body / data: IBM Plex Mono

- **Motif**
  - Thin gold "rules" used as structural dividers and calibration lines
  - Left vertical gold accent bar on all content slides (instrument chassis / rail effect)
  - Large gold section numerals
  - Precise margins and consistent hierarchy
  - Dark title slide + light content slides ("sandwich" structure)

The deck follows a clean, precision-instrument aesthetic — minimal ornament, strong typography contrast, and gold lines that function as measurement marks rather than decoration.

---

## Fonts (for Pixel-Perfect Rendering)

The deck specifies:
- `Bebas Neue`
- `IBM Plex Mono`

These are free Google Fonts. Install them on any machine where you will present or edit for exact glyph fidelity. On macOS:

```bash
# Example via Homebrew
brew tap homebrew/cask-fonts
brew install --cask font-be bas-neue
brew install --cask font-ibm-plex-mono
```

(If the fonts are not present, PowerPoint/Keynote will substitute similar faces — the structure and hierarchy remain intact.)

---

## Rebuilding / Editing

1. Make sure you have Node.js.
2. From inside the package folder:

```bash
cd /Users/aaronray/aaron-ray-credentials
node generate-credential-deck.js
```

This will overwrite the `.pptx` with a fresh build from the current script.

To change content or layout, edit `generate-credential-deck.js` and re-run. The script is self-contained and uses `pptxgenjs`.

After editing, you can re-export a PDF using LibreOffice:

```bash
soffice --headless --convert-to pdf Aaron-Ray-Executive-Credential-Synthesis.pptx
```

Then regenerate slide images if needed:

```bash
pdftoppm -jpeg -r 160 Aaron-Ray-Executive-Credential-Synthesis.pdf slide
```

---

## Deck Structure (6 slides)

1. **Title** — Instrument cover with name, specialization, target package architecture note
2. **01 — Entertainment Industry Credential Base** — 35+ years scale + core creative analysis
3. **02 — Forensic Audiovisual Expertise** — Hollien (1990), Schiller & Koster (1998), stress tracking / deepfake foundation
4. **03 — AI/ML Technical Credentials** — TensorFlow/YOLOv3, Magenta/Jukebox/EarSketch, JHU & Michigan training
5. **04 — The Artificial Senses Framework** — Core thesis + 4 pillars (Music as Medicine, Judicial Analytics, Forensic Authentication, Narrative Persuasion)
6. **05 — Benchmark Qualification Statement** — The five-point convergence summary (including reference to the Kingsfield Legal Citation Benchmark methodology)

---

## Notes

- All text is taken verbatim from the source credential synthesis you provided.
- Visual QA was performed on the rendered slides (no text overflow, overlapping elements, or layout collisions were present).
- The gold rules are intentional structural elements, not decorative underlines.
- The left gold bar on content slides creates a consistent "instrument frame" across the deck.

---

**Generated:** June 2026  
**Tooling:** pptxgenjs + LibreOffice (for PDF + image verification)  
**Source script:** `generate-credential-deck.js` (kept in this folder for reproducibility)