# Kingsfield UI Mockups

Screenshots of current Kingsfield UI pages, captured May 2026.
Add image files to this folder alongside this README as the UI evolves.

---

## Pages documented

### Landing page (`landing.png`)
- Black background, serif wordmark "Kingsfield"
- Taglines: "Smart. Not Stupid." / "Know the Rules. Use Them" / "We Are Not Lawyers"
- Shakespeare epigraph: *"First, kill all the lawyers."*
- Single search/auth bar with Log in / Sign up

### Assistant (`assistant.png`)
- Main chat interface
- Left nav: Assistant, Projects, Case Law, Legislation, Tabular Review, Workflows, Council

### Case Law (`case-law.png`)
- Search bar: "Search case name, citation or keywords"
- Jurisdiction dropdown: All jurisdictions
- Source attribution: CourtListener (Free Law Project) + four-gate verification
- Tabs: Recent Cases · Favorites

### Legislation (`legislation.png`)
- Search by citation (18 USC 1001, 26 CFR 1.61-1, Cal. Penal Code §187)
- Sources: Congress.gov, GovInfo.gov, eCFR.gov (federal); official state sites
- Federal: U.S. Code, U.S. Constitution, Code of Federal Regulations
- State grid: all 50 states + territories

### Council (`council.png`, `council-2.png`)
- Five advisors displayed as named cards:
  | Role | Model |
  |------|-------|
  | The Contrarian | Claude Opus |
  | First Principles | Gemini Pro |
  | The Expansionist | Claude Sonnet |
  | The Outsider | Gemini Flash |
  | The Executor | Claude Sonnet |
- Question textarea (placeholder: 12(b)(6) motion example)
- Context textarea (optional — matter summary, prior filings, facts)
- Footer: "Eleven model calls per session (~30s, ~$0.40 with current pricing)."
- CTA: "Convene the council"

### Court Records Map (`court-records-map.png`)
- Choropleth map of U.S. states, two-tone blue
- Hover state: tooltip "California — detailed guide · click to open"
- Caption: "Map of U.S. states with court records access information"
- Dark blue = more open access; light blue = restricted

---

## Planned pages (not yet built)

- Specialties hub — practice-area vertical agents
- Docket Watcher dashboard — per-matter renewal + filing alerts
- IP Portfolio — asset table, deadline calendar
- Document upload + Tabular Review detail view
- Workflows builder — multi-step pipeline UI

---

## Design notes

- Font: serif display (Playfair Display or similar) for headers; system sans for body
- Color: near-white background (#F5F5F0 approx.), dark navy text
- Nav is minimal — icon + label, no nested menus yet
- Council page intentionally shows model names as a trust/transparency signal
