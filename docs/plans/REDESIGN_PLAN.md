# CAG Gateway Frontend Redesign Plan

## 1. Report Cards — Scannability Overhaul

**Current problem:** Cards are text-heavy walls with no visual differentiation. Report numbers, sectors, and findings all compete at the same visual weight.

**Redesign strategy:**

**Card layout (box view):**
- **Top strip:** Colored left border (4px) keyed to sector. Define a sector color map: `Direct Taxes → blue-600`, `Commercial → amber-600`, `Finance → emerald-600`, `Social Infrastructure → purple-600`, `Education/Health → rose-600`, `Union Govt Civil → slate-600`. Apply as `border-l-4` on the card.
- **Report badge:** Keep "Report 13 of 2024" badge but make the number bold/large: render as `Report **13** of 2024` with the number in `text-lg font-bold` and the rest in `text-xs text-muted`.
- **Title:** Truncate to 2 lines with `line-clamp-2`. Full title on hover via `title` attribute.
- **Metadata row:** Horizontally lay out sector as a small colored pill (matching the left border color), year as plain text, and findings count as a small badge (e.g., `98 findings` in a subtle rounded chip).
- **"Interact →"** stays bottom-right.

**List/grid view toggle:**
- Add a toggle group (two icons: grid `LayoutGrid` + list `List` from lucide) next to the Sector filter dropdown, right-aligned.
- Store preference in component state (or `appStore.ts` if you want persistence).
- **Grid view** = current card layout (improved above), use `grid-cols-1 md:grid-cols-2 lg:grid-cols-3` (reduce from current ~5 cols — cards are too cramped at 5).
- **List view** = single-column rows. Each row: `flex items-center gap-4` with — colored sector dot (8px circle), report number (bold), truncated title (flex-1), sector pill, year, findings count, Interact link. Essentially a table-like density without an actual table.

**Files to modify:**
- Page component that renders the report directory (likely where `useReports` hook is consumed)
- Extract a `ReportCard.tsx` component if not already separated
- Add `constants.ts` entry for `SECTOR_COLORS` map

---

## 2. "Ask AI" Banner — Prominent but Non-Intrusive

**Current problem:** Fixed bottom banner steals ~60px of vertical space on every tab, even when user is deep in Charts/Tables and doesn't need it.

**Redesign strategy:**

Replace the full-width sticky banner with a **floating action button (FAB)** that expands on hover/click:

- **Collapsed state:** Fixed `bottom-6 right-6`, a 56px circular button with the sparkle/AI icon (already used), subtle pulse animation on first load (runs once, `animate-pulse` for 3 cycles then stops). Background: your existing dark navy (`bg-slate-800`). Include a small tooltip on hover: "Ask AI about this report".
- **Hover/expanded state:** Button morphs into a pill shape (`w-auto px-4 rounded-full`) revealing "Ask AI → Start chat". Transition: `transition-all duration-200`.
- **Click:** Opens the `SideDrawer.tsx` chat panel as it does now.
- **First-visit nudge (optional):** On first report page load per session, show a transient tooltip callout pointing to the FAB: "Ask AI about this report — get summaries, find data". Auto-dismiss after 4s or on click. Track with a `sessionStorage` flag.

This frees up the full viewport width for content while keeping AI chat access always one click away with strong visual presence.

**Files to modify:**
- Component rendering the bottom banner (likely in the report detail page layout)
- `SideDrawer.tsx` — trigger mechanism may need adjustment if currently tied to the banner button

---

## 3. PDF Viewer — Visual Indicators for Navigation

**Current problem:** PDF viewer navigates to correct page on "View in PDF" clicks, but there's no visual highlight showing *what* the user navigated to. Citations, charts, and tables blend into the page.

**Redesign strategy:**

Since `PDFViewer.tsx` likely uses `react-pdf` or an iframe/embed approach, the highlighting strategy depends on the renderer:

**Approach A — Overlay-based (works with any PDF renderer):**
- When a "View in PDF" click or citation click fires, pass highlight coordinates to `PDFViewer` via props or a shared store: `{ page: number, bbox: { x, y, width, height } }` (bounding box as percentages of page dimensions).
- Render a semi-transparent overlay `div` absolutely positioned over the PDF canvas/container at the bbox coordinates. Style: `bg-amber-400/20 border-2 border-amber-400 rounded-sm` with a fade-in animation (`animate-in fade-in duration-300`).
- Auto-dismiss the highlight after 4-5 seconds with a fade-out, or on next navigation.
- For citations (text chunks): highlight the chunk region with a more subtle `bg-blue-100/30 border-l-3 border-blue-500` style to differentiate from chart/table highlights.

**Data requirement:** Your processed JSONs likely already store `page` numbers for charts/tables/chunks. If bounding box coordinates aren't available, fall back to **full-page highlight with a banner**: after navigating to the page, show a small dismissible banner at the top of the PDF panel: `"📊 Figure 2.1 — Page 21"` or `"📋 Table 2.3 — Page 24"` with the same amber styling. This is simpler and still solves the "what am I looking at" problem.

**Scroll behavior:** When navigating, add `scroll-behavior: smooth` to the PDF container and scroll the target page to vertical center, not top, so context above is visible.

**Files to modify:**
- `PDFViewer.tsx` — add overlay rendering logic, accept highlight props
- `ArtifactCard.tsx` — "View in PDF" click handler should dispatch highlight info
- Chat citation click handlers in `ChatMessage.tsx`
- Potentially `appStore.ts` for shared highlight state between right panel and PDF viewer

---

## 4. Typography & Spacing Polish

**Current problems:** Report detail page title is too long and dominant. Metadata badges are small. Tab bar spacing is tight. Cards on Charts/Tables tabs need breathing room.

**Fixes:**

**Report detail page header:**
- Sector + report number badges: increase to `text-sm px-3 py-1` (currently look like `text-xs`). These are the primary identifiers.
- Title: Cap at 2 lines on desktop with `line-clamp-2`, reduce from what appears to be `text-2xl` to `text-xl font-semibold`. Full title in a `title` tooltip.
- "Union Government (Civil) • 2025" subtitle: keep as-is, it's well-sized.
- Net effect: header block shrinks by ~30px, pushing content up.

**Tab bar:**
- Add slightly more horizontal padding between tabs: `gap-1` → `gap-2`.
- The count badges (Charts 43, Tables 80) are good — ensure consistent sizing (`min-w-[28px] text-center`).

**Overview tab content:**
- Audit Scope / Audit Objectives sections: add `space-y-4` between sections instead of what looks like `space-y-2`.
- Entity tags ("Union Government Civil Ministries", "Controller General of Accounts"): slightly increase pill padding `px-3 py-1.5` and add `text-sm` if currently smaller.

**Charts/Tables grid:**
- Reduce to `grid-cols-1 md:grid-cols-2 lg:grid-cols-3` (currently appears to be 4 cols — too tight).
- Card internal padding: ensure `p-4` minimum.
- Chart card descriptions: `line-clamp-2` for consistency.

**Key Findings / Recommendations:**
- Add `line-clamp-4` with an expand toggle ("Show more ↓" / "Show less ↑") per item. This is the truncation fix mentioned in the original critique — findings cut off mid-sentence currently.

**Global spacing:**
- Page-level horizontal padding: verify it's `px-6 lg:px-8` (not less).
- Section headers ("REPORT DETAILS", "KEY METRICS"): ensure `tracking-wider text-xs font-medium text-muted-foreground` for the small-caps label look you're using — currently looks slightly inconsistent in weight.

**Files to modify:**
- Report detail page component (header, tabs, tab content areas)
- `ArtifactCard.tsx` (chart/table card spacing)
- Key Findings and Recommendations tab components
- Possibly `index.css` for any global spacing tokens

---

## Implementation Order

1. **Typography & Spacing** (lowest risk, biggest visual uplift, touches everything so do first)
2. **Report Cards redesign + view toggle** (high-impact homepage improvement)
3. **Ask AI banner → FAB** (contained change, frees viewport)
4. **PDF viewer highlights** (most complex, needs coordinate data verification)
