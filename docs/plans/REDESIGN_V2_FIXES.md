# Redesign v2 — Fixes to Current Implementation

## 1. Report Cards — Title Strategy & Visual Cleanup

### 1a. Report Badge
- Make the full "Report XX of 20XX" text bold and dark: `font-semibold text-slate-800`.
- Keep the existing grey rounded box (`bg-slate-100 rounded`).
- **Add report type** next to the badge in a matching style: `Performance Audit`, `Compliance Audit`, or `Financial Audit`. Render as a second pill, same grey style but with a subtle text color distinction: `text-slate-600`. Example: `[Report 13 of 2024]  [Compliance Audit]`
- Source: `report_metadata.report_type` field in the chunks JSON (values: `"Financial Audit"`, `"Performance Audit"`, `"Compliance Audit"`). This needs to be surfaced in the reports listing API response if not already.

### 1b. Concise Card Titles
This is the most impactful change. Current titles repeat information already shown elsewhere on the card.

**Title sanitization logic** (implement as a utility function, used by both grid and list views):

Strip the following from card display titles, in order:
1. Remove report number prefix patterns: `"Report No. XX of 20XX - "`, `"Report no. X of 20XX, of the "`, `"Report of the "`, etc. — regex: `/^Report\s*(No\.?\s*\d+\s*of\s*\d{4}\s*[-–,]\s*(of the\s*)?)?/i`
2. Remove "Comptroller and Auditor General of India" and "CAG" references: `/Comptroller and Auditor General of India\s*(on)?/i`, `/CAG['']?s?\s*/i`
3. Remove trailing ministry/department boilerplate that duplicates the sector: e.g., `"Union Government Department of Revenue"` when sector is already `"Taxes and Duties"`. This is harder to regex — approach: if title ends with `"Union Government..."` after the substantive part, truncate at a reasonable break.
4. Remove report number suffix patterns: `"Report No. XX of 20XX (Financial Audit)"` at the end.
5. Trim, collapse whitespace, remove leading dashes/commas.

**Examples of transformation:**
- `"Report No. 13 of 2024 - Union Government, Department of Revenue – Direct Taxes"` → `"Department of Revenue – Direct Taxes"`
- `"Report of the Comptroller and Auditor General of India on Accounts of the Union Government for the year 2023-24 Union Government Ministry of Finance Report No. 16 of 2025 (Financial Audit)"` → `"Accounts of the Union Government for the year 2023-24"`
- `"Report no. 3 of 2025, of the Comptroller and Auditor General of India on Compliance of the Fiscal Responsibility and Budget Management Act, 2003 for the year 2022-23"` → `"Fiscal Responsibility and Budget Management Act, 2003 Compliance for 2022-23"`
- `"Report No.6 of 2025 - General Purpose Financial Reports of Central Public Sector..."` → `"General Purpose Financial Reports of Central Public Sector..."`

**Where to implement:** Create `utils/titleSanitizer.ts` (or add to existing `utils.ts`). Apply in both `ReportCard.tsx` (grid) and list view row component. Keep the full raw title accessible via `title` attribute for hover tooltip.

**Important:** Only apply sanitization on the homepage cards/list. The report detail page header should keep the full official title.


### 1c. Sector Pill Color Palette — Professional Tones
Replace the current colors with muted, professional tones that work with the slate/navy theme:

```
Taxes and Duties     → bg-slate-100 text-slate-700 (neutral, most common)
Finance              → bg-sky-50 text-sky-700
Commercial           → bg-stone-100 text-stone-600
Social Infrastructure → bg-slate-100 text-slate-600
Education, Health... → bg-slate-100 text-slate-600
Transport & Infra    → bg-slate-100 text-slate-600
```

Rule: no bright greens, purples, or saturated colors. The only colored pills should be `Finance` (subtle sky) and everything else in neutral slate/stone tones. Multi-sector pills (like "Finance, Industry and Commerce, Power & Energy, Transport & Infrastructure") need to be truncated: show first sector + `+N more` with full list on hover tooltip.

### 1e. Fix Content Spillover (Report 06)
The card with long multi-sector tags is breaking out of bounds. Fix:
- Sector pill container: `overflow-hidden` + `max-w-full` + `truncate` on the pill text.
- If sector string > 30 chars: show first sector name + `+N` badge. Full list in tooltip.
- Card itself: `overflow-hidden` as a safety net.
- Metadata row: `flex-wrap` should NOT be used — keep single line with truncation to prevent layout shifts.
- Having bigger cards is better than truncation.

---

## 2. List View — Title Fix & Remove KEY METRICS

### 2a. Title Sanitization
Apply the same `titleSanitizer` function from 1b. This will immediately fix the redundancy in list mode since the full unsanitized titles are even more painful in a dense list.

### 2b. Remove "KEY METRICS" Header
Delete the `KEY METRICS` annotation text from both grid and list views. It adds no information — the metrics (year, findings count) are self-evident from context.

---

## 3. Ask AI — Revert to Bottom Banner with Minimize

### 3a. Remove FAB
Delete the floating action button implementation entirely.

### 3b. Restore Bottom Banner — Enhanced Design
Bring back the full-width sticky bottom banner but with these improvements:

**Expanded state (default on page load):**
- Same dark navy bar (`bg-slate-800`) with sparkle icon + "Ask AI about this report" + subtitle "Get summaries, find data" + "Start chat →" button.
- Add an `×` close button on the right edge (or top-right corner of the banner): `text-slate-400 hover:text-white`.
- Clicking `×` collapses to minimized state.

**Minimized state:**
- Collapses to a small pill/chip anchored bottom-right: approximately `48px` height, auto width.
- Content: sparkle icon + "Ask AI →" text. Same dark navy background, `rounded-full` or `rounded-t-lg`.
- **Key requirement:** even minimized, the icon and text must clearly communicate "AI chat available" — not a generic support widget. The sparkle/stars icon (already in use) plus the "Ask AI →" text achieves this.
- Clicking the minimized pill expands back to full banner.


**Animation:**
- Expand/collapse: `transition-all duration-300` with height animation. No jarring snap.
- The content area above should have `padding-bottom` that adjusts to match banner height (expanded: ~64px, minimized: 0 since the pill is absolutely positioned and doesn't push content).

**Files:** Component rendering the banner (revert FAB changes), `appStore.ts` or local component state for expand/minimize.

---

## Implementation Order

1. **Title sanitizer utility** — shared by grid + list, biggest scannability win
2. **Card visual cleanup** — remove left borders, fix sector colors, fix overflow
3. **List view cleanup** — apply sanitizer, remove KEY METRICS
4. **Ask AI banner revert** — restore banner with minimize feature
