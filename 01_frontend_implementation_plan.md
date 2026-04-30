# Home Redesign — Frontend Implementation Plan

**Scope**: All UI changes needed to ship the home page redesign, smart search, entity-first browsing, groundedness UI, and "Surprise Me" — slotted into the existing CAG Gateway frontend with minimum disruption.

**Companion doc**: See `02_backend_implementation_plan.md` for the API surface this UI consumes.

**Decisions locked**:
- Default chat from home → agentic
- Groundedness badges with click-to-expand panel for unverified claims
- "Surprise Me" for both reports and entities
- Skip Topics search channel; Entities is a primary channel
- Skip Sector facet; replace with Entity facet
- Headline copy: **"Audit Intelligence"**
- Disclaimer lives on directory only (linked from footer)
- Popular starting points: 10 deterministic items, daily seed
- Trending searches sanitized + threshold-gated server-side
- Desktop/tablet only — no mobile responsive work
- CSS Path B: isolated `home.css` module; same color theme as rest of app
- "Recently added" rail sorts by `report_year` desc (not `ingested_at`) for v1
- `index.tsx` refactor: extract `DirectoryPage` and `TimeSeriesPage` as Phase 0
- "Unknown Ministry" filtered everywhere on frontend

---

## 1. Where this slots into the existing codebase

The current frontend routes everything through `App()` in `index.tsx` (1800 lines). View dispatch is a string-typed local state `view: ViewState` from `types.ts`, with values: `'landing' | 'report' | 'time-series' | 'series-chat' | 'how-it-works'`.

We do **not** rewrite this. We extend it. The shape of the change is:

- `'landing'` (the report grid) gets renamed to **`'directory'`** and its rendering extracted into a new `DirectoryPage` component.
- The current hero in the directory (the "CAG Gateway" title + multi-paragraph explainer + disclaimer) stays on the directory page exactly as today. The home gets its own punchier hero.
- A new `'home'` view becomes the default landing.
- The header nav gets a new "Home" button to the left of "Report Directory."
- All existing tabs, hooks, and state machines stay where they are.

Zero changes to PDF viewer, chat panel, citation logic, time series rendering, or report detail flow. The redesign is purely additive.

---

## 2. Phase 0: `index.tsx` refactor (prerequisite)

`index.tsx` is 1800 lines. Adding home pushes it past 2000 — maintenance cliff. The home redesign is the natural moment to extract.

### 2.1 Extract the directory page

Create `frontend/components/Directory/DirectoryPage.tsx`. Move into it:
- The entire `view === 'landing'` block from `index.tsx` (lines ~1488-1659)
- The current hero section (title, subtitle, multi-paragraph explainer, disclaimer)
- The `TierSelector` invocation
- The stats bar
- The state filter dropdown
- The filter block (search, sector dropdown, ministry/year, audit-type pills, view toggle)
- The report grid render

Props it needs from `App()`: filters state, handlers, computed `filteredReports`, etc. Pass these down explicitly rather than reaching into `useAppStore` from inside the component — keeps `DirectoryPage` testable.

Keep the same CSS class names (`.landing-view`, `.hero-section`, `.stats-bar`, etc.) so styling carries through unchanged.

### 2.2 Extract the time series page

Create `frontend/components/TimeSeries/TimeSeriesPage.tsx`. Move into it:
- The `view === 'time-series'` block from `index.tsx` (lines ~1661-1681)
- Same prop-drilling pattern

### 2.3 What stays in `index.tsx`

After extraction, `App()` should be:
- All hooks/state declarations
- Handlers (these stay because they mutate `App()`-level state)
- Tab renderers for the report detail view (overview/findings/charts/tables/summaries) — they stay since the report-view layout is also in `App()`
- The header nav
- The view dispatcher: `{view === 'home' && <HomePage ... />}`, `{view === 'directory' && <DirectoryPage ... />}`, etc.
- The chat drawer
- The split-panel report-detail rendering (keep as-is)

Target after refactor: `index.tsx` around 1100 lines, two new component files at ~300 lines each.

This is a mechanical refactor. Do it first, before any home work. It de-risks everything that follows.

---

## 3. View state changes

### 3.1 `types.ts`

Update `ViewState`:

```
'home' | 'directory' | 'report' | 'time-series' | 'series-chat' | 'entity' | 'how-it-works'
```

`'directory'` replaces `'landing'`. `'entity'` is new (see §12).

### 3.2 `index.tsx` initial state

Change default view from `'landing'` to `'home'`:

```
const [view, setView] = useState<ViewState>('home');
```

### 3.3 New navigation handlers

Add `handleBackToHome` alongside the existing back handlers. The CAG logo click in the header routes to `home`.

### 3.4 Header nav update

```
Home | Report Directory | Time Series Analysis | How It Works
```

Active state highlighting follows the same pattern.

---

## 4. New components — directory tree

All new components live under `frontend/components/Home/`:

```
Home/
├── HomePage.tsx              ← top-level composer; called from index.tsx
├── HomeHero.tsx              ← title, search, explainer, big-yellow-numbers stats
├── SmartSearchBar.tsx        ← input + "/" shortcut + dropdown trigger
├── SearchDropdown.tsx        ← grouped result rendering
├── SearchResultRow.tsx       ← individual row inside the dropdown
├── EntityChannelTabs.tsx     ← All/Reports/Ministries/Entities/Findings/Glossary tabs above search
├── FacetChips.tsx            ← year/state/tier/audit-type/entity multi-select chips
├── StatsTiles.tsx            ← the big-yellow-numbers block (used inside HomeHero)
├── CTACards.tsx              ← three "Start Here / Compare / Ask" cards
├── PopularStartingPoints.tsx ← 10 deterministic entity/ministry tiles
├── MinistryRail.tsx          ← horizontally scrollable ministry cards
├── EntityRail.tsx            ← horizontally scrollable PSU/scheme cards
├── FeaturedReportsRail.tsx   ← reuses ReportCard in horizontal scroll
├── TrendingSearches.tsx      ← from query_logs aggregate
├── DeepDivesRail.tsx         ← reskin of TimeSeries cards
├── ToolsGrid.tsx             ← icon+label tiles for Chat/Charts/Tables/Glossary/Series
├── SurpriseMeButton.tsx      ← random report or random entity
└── home.css                  ← isolated CSS module (Path B)
```

Components in `Home/` should not import from each other except through `HomePage.tsx` — keeps each one independently testable and lazy-loadable later.

For the entity page (§12):

```
Entity/
├── EntityPage.tsx
├── EntityHeader.tsx
├── EntityFindingsTab.tsx
├── EntityReportsTab.tsx
├── EntityRelatedTab.tsx
└── EntityMentionsTab.tsx
```

---

## 5. New hooks

All in `frontend/hooks/`:

| Hook | Purpose | Cache | Refetch trigger |
|---|---|---|---|
| `useHomeStats.ts` | Single fetch of `/api/home/stats` | `useState` cached for session | mount only |
| `useHomeFacets.ts` | Single fetch of `/api/home/facets` | session cached | mount only |
| `useHomeFeatured.ts` | Featured ministries, entities, reports, trending, popular starts | session cached | mount only |
| `useSmartSearch.ts` | Debounced search-as-you-type, returns grouped results | none | every keystroke after 150ms debounce |
| `useSurpriseMe.ts` | Random report or entity on demand | none | manual call |
| `useEntity.ts` | Fetches entity detail + sub-resources by ID | per-ID cached | when `currentEntityId` changes |

`useSmartSearch` behaviors:
- 150ms debounce on input changes
- `AbortController` cancels in-flight on new keystroke
- Return shape: `{ results, isLoading, isLoadingByChannel, error }`
- Per-channel loading tracked independently — lexical channels render immediately; findings streams in when ready
- Findings channel only fires at `>=3` chars and 300ms idle

---

## 6. `HomePage.tsx` — section structure

Top-down render order:

```
<HomePage>
  <HomeHero>
    title: "AUDIT INTELLIGENCE"
    <EntityChannelTabs>     (All · Reports · Ministries · Entities · Findings · Glossary)
    <SmartSearchBar />
    <SurpriseMeButton variant="report" inline />
    explainer: ONE compact line e.g.,
      "Search 37 CAG audit reports — 390 entities, 25K mentions, 5K findings. Free, no signup."
    <StatsTiles>            (big yellow numbers — single placement, hero only)
  </HomeHero>

  <FacetChips />             (sticky bar, scrolls under hero)

  <CTACards>                 (3 cards in a row)
    1. Start Here → setView('directory')
    2. Compare Over Time → setView('time-series')
    3. Ask the Corpus → opens chat drawer in agentic mode
  </CTACards>

  <PopularStartingPoints />  (10 deterministic items)

  <MinistryRail />           ("Most-referenced ministries")
  <EntityRail />             ("Top-mentioned PSUs & schemes")
  <FeaturedReportsRail />    ("Recently added reports" — sorted by report_year desc)
  <DeepDivesRail />          (time series collections)
  <TrendingSearches />       ("Popular this week")

  <ToolsGrid />              (6-tile grid of capabilities)

  <Footer>
    Disclaimer link → opens directory page anchored to disclaimer block
    Privacy · Terms · © 2025 CAG Gateway
  </Footer>
</HomePage>
```

No tier selector on the home page. No multi-paragraph explainer. The explainer is a single sentence that does triple duty: states what the corpus is, gives concrete numbers, makes the value prop explicit.

---

## 7. Hero details

### 7.1 Layout

```
                    AUDIT INTELLIGENCE
       [ All · Reports · Ministries · Entities · Findings · Glossary ]
       ┌─────────────────────────────────────────────────────────┐
       │ 🔍 Search reports, entities, findings...           [/]  │
       └─────────────────────────────────────────────────────────┘
                              [ ⟳ Surprise Me ]

   Search 37 CAG audit reports — 390 entities, 25K mentions, 5K findings.
                            Free, no signup.

       ┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐
       │  37  │  │  390 │  │  25K │  │  5K  │  │  10  │
       │REPORT│  │ENTITY│  │ MENT │  │FINDIN│  │STATES│
       └──────┘  └──────┘  └──────┘  └──────┘  └──────┘
```

### 7.2 Title

`AUDIT INTELLIGENCE` in monospace caps, large (~64-80px desktop). No subtitle below it. The headline does the explanatory work.

### 7.3 Search bar

720px wide on desktop. Full-width on tablet. The slash-shortcut hint `[/]` sits inside the input on the right. Placeholder rotates between examples ("Try: railway safety findings", "Try: NHAI", "Try: Maharashtra 2023") every 3s.

### 7.4 Explainer

One sentence. Numbers pulled live from `useHomeStats`. Falls back to "—" placeholders during load. Style: small, secondary text color, ~16px.

### 7.5 Stats tiles

Five tiles in a row. Big numbers (~48px), small uppercase labels below. Numbers use `font-variant-numeric: tabular-nums` so they don't jitter during loading-to-loaded transitions.

Pulled from `useHomeStats`:
- Total reports
- Total entities
- Total mentions (formatted as "25K" not "25,000")
- Total findings
- States covered (count of distinct `state_name` from facets)

---

## 8. The smart search bar — UX detail

### 8.1 Visual states

- **Empty / unfocused**: rotating placeholder
- **Focused, empty**: dropdown shows static "Try searching for..." panel with 4-6 example chips that pre-fill the query
- **Typing, <3 chars**: lexical channels only (Reports, Ministries, Entities, Glossary). Findings does not fire
- **Typing, >=3 chars after 300ms idle**: all five channels fire
- **Loading**: spinner inline in the dropdown header per channel still loading
- **No results**: "No matches for 'X'. Try entity names like NHAI or topics like railway safety."

### 8.2 Keyboard

- `/` from anywhere on the home page focuses the search bar (skip if user is in another input)
- `Escape` closes the dropdown
- `↑/↓` navigates results across channels (treat as flat list, skip channel headers)
- `Enter` on a selected result → navigate to its destination
- `Enter` with no selection → smart Enter routing (§8.4)

### 8.3 EntityChannelTabs

```
[ All ] [ Reports ] [ Ministries ] [ Entities ] [ Findings ] [ Glossary ]
```

`All` is default. Selecting a tab filters already-fetched results client-side — no refetch. We always fetch all channels in parallel; tab switching is instant.

### 8.4 Smart Enter routing

When user hits Enter without selecting:

1. Top hit is a Report → navigate to that report's detail view
2. Top hit is an Entity or Ministry → navigate to its entity page (§12)
3. Top hit is a Finding → open chat drawer pre-populated with the query, send to agentic stream
4. Mixed top hits within 10% score → navigate to directory tab with query as filter, plus an "Ask the corpus" CTA at the top

`useSmartSearch` exposes `topHit` with channel info. `HomePage` reads it on Enter and dispatches.

### 8.5 SearchDropdown structure

```
┌─ Search dropdown ─────────────────────────────┐
│ ┌─ REPORTS (3) ──────────────────────────┐   │
│ │ → State Finances for Uttarakhand 2023  │   │
│ │   Compliance · 36 findings             │   │
│ ├─ MINISTRIES (1) ───────────────────────┤   │
│ │ → Ministry of Railways                 │   │
│ │   12 reports · 487 mentions            │   │
│ ├─ ENTITIES (4) ─────────────────────────┤   │
│ │ → NHAI · 650 mentions across 8 reports │   │
│ ├─ FINDINGS (5) ─────────────────────────┤   │
│ │ → "Revenue loss of ₹64.60 cr at..."    │   │
│ │   2023_07 · Section 3.2.1, p.36        │   │
│ └─ GLOSSARY (2) ─────────────────────────┘   │
└───────────────────────────────────────────────┘
```

`SearchResultRow.tsx` is one component with conditional rendering by channel. Channels with zero results are hidden. Glossary results matching the same `term` from different reports group together with a "+N more definitions" affordance.

`SearchResultRow` filters out any result with `ministry === "Unknown Ministry"`. Dead-string check.

---

## 9. FacetChips component

Horizontal row below the hero. Each chip is a multi-select popover:

```
[ Tier (1) ▾ ]  [ State (2) ▾ ]  [ Year ▾ ]  [ Ministry ▾ ]  [ Entity ▾ ]  [ Audit Type ▾ ]
```

The number in parens shows count of selected values. Selected facets stored in `appStore.searchFilters`. Clicking a chip opens a popover with checkboxes; "Apply" closes; "Clear" clears just that facet.

**Critical behavior**: changing a facet does not mutate the home page. On first facet selection:
1. Stores facets in `appStore.searchFilters`
2. Navigates to directory view via `setView('directory')`
3. Directory reads `appStore.searchFilters` and applies them to its filter state

Home is the launchpad, directory is the results surface.

Ministry and Entity chip popovers exclude `"Unknown Ministry"` and any entity with `mention_count < 5` (low-signal noise).

---

## 10. App store changes (`stores/appStore.ts`)

Add to existing `AppState`:

```ts
// View routing
previousView: ViewState | null;

// Search/home state
searchFilters: {
  tier?: 'union' | 'state' | 'local_body';
  states?: string[];
  years?: string[];
  ministry_entity_ids?: number[];
  entity_ids?: number[];
  audit_categories?: string[];
};

// Entity page
currentEntityId: number | null;

// Chat mode (home → agentic, report → regular)
chatMode: 'regular' | 'agentic';
```

Setters: `setSearchFilters`, `clearSearchFilters`, `setCurrentEntityId`, `setChatMode`, `goBack` (pops `previousView`).

Default `chatMode` to `'agentic'` for chat sessions launched from home; `'regular'` for chat launched from a report detail view. Set this when transitioning views.

---

## 11. Groundedness UI in chat (`ChatMessage.tsx`)

The `groundedness` event already comes through `useChatStream` but is currently only `console.log`'d. Surface it.

### 11.1 Wire-up changes

In `useChatStream.ts`, replace the console.log on `case 'groundedness'`:

```
setLastMessageGroundedness(event.data);
```

Add `groundednessReport: GroundednessReport | null` to the `Message` interface in the store, plus `setLastMessageGroundedness` action.

`GroundednessReport` type matches the Phase 13 backend payload: `{ verified, overall_score, num_claims, num_grounded, num_ungrounded, claims: [...], provider_used }`.

### 11.2 Visual states

In `ChatMessage.tsx`, after the message body finishes streaming (`!isStreaming` and `groundednessReport` is set), render a small badge below the answer:

- **`overall_score >= 0.8` and `verified === true`**: green checkmark `✓ Verified` (subtle)
- **`overall_score < 0.8` OR `num_ungrounded > 0`**: amber warning `⚠ N of M claims unverified` — clickable
- **No groundedness report**: render nothing. Don't show "checking..." — bad UX

### 11.3 Click-to-expand for unverified claims

When the amber warning is clicked, expand a panel below the message showing each claim and the verification reason:

```
┌─ Verification Details ──────────────────────────────────────┐
│ ⚠ 2 of 7 claims could not be verified against sources       │
│                                                              │
│ ✓ ₹124.18 crore loss at Nathavalasa toll plaza               │
│   Section 3.2.1, p.36 · confidence 0.95                     │
│                                                              │
│ ⚠ Equipment maintenance was deferred for 18 months          │
│   Reason: No source mentions the 18-month duration          │
│                                                              │
│ ✓ ETC equipment was non-functional                          │
│   Section 3.2.1, p.36 · confidence 0.92                     │
└──────────────────────────────────────────────────────────────┘
```

Collapsed by default. Accordion pattern. Don't overwhelm.

### 11.4 No latency penalty

Groundedness arrives ~200-400ms after `done`. Message must appear "complete" the moment `done` arrives — pen icon stops, status pill removed. Badge appears later as a non-blocking enhancement. Do not delay the "done" UI on groundedness.

---

## 12. Entity page

When a user clicks an entity from search, ministry rail, entity rail, or popular starts, navigate to the entity page:

```
┌─ Entity Page ───────────────────────────────────────────────────┐
│ ← Back                                                          │
│                                                                 │
│ NATIONAL HIGHWAYS AUTHORITY OF INDIA                            │
│ PSU · Union tier                                                │
│ Aliases: NHAI, National Highway Authority                       │
│                                                                 │
│ [stats: 8 reports · 650 mentions · 124 findings · ₹2,450 cr]    │
│                                                                 │
│ [ Findings ] [ Reports ] [ Related Entities ] [ Mentions ]      │
│                                                                 │
│ <render selected tab>                                           │
└──────────────────────────────────────────────────────────────────┘
```

Direct calls to existing entity graph endpoints:
- `GET /api/entities/{id}` for header
- `GET /api/entities/{id}/findings`
- `GET /api/entities/{id}/reports` → then `GET /api/reports/{id}` for each to render `ReportCard`
- `GET /api/entities/{id}/related`
- `GET /api/entities/{id}/mentions`

Components in `frontend/components/Entity/` (see §4).

`appStore` needs `currentEntityId: number | null`. Navigation: `setCurrentEntityId(123); setView('entity')`.

---

## 13. Ask-the-corpus flow

Home page CTA "Ask the Corpus" and any chat triggered from home (e.g., smart Enter on a finding) need a corpus-wide chat experience. Reuse the existing right-side chat drawer.

For home-launched chat:
1. Set `chatMode: 'agentic'` in app store
2. Keep `view: 'home'` — show the chat drawer overlaid on the home view
3. `sendMessage` called with `reportIds: undefined` and `mode: 'agentic'`

The home view stays underneath as the "you can come back to me" surface. Same pattern as report-detail today.

---

## 14. Surprise Me (`SurpriseMeButton.tsx`)

Two variants:

- `variant="report"` — calls `GET /api/home/surprise/report` → navigates to report detail
- `variant="entity"` — calls `GET /api/home/surprise/entity` → navigates to entity page

Default placement in the hero is `variant="report"`. Place a second instance near the bottom of the page with `variant="entity"`.

Animation: subtle shuffle icon spin on click. Don't over-animate.

---

## 15. Popular starting points (`PopularStartingPoints.tsx`)

10 tiles, deterministic per-day. The backend's `/api/home/featured` returns `popular_starts` seeded by date — same seed across all clients on the same UTC day. No client-side randomness.

Each tile shows:
- Icon (entity-type-specific: 🏛️ ministry, 🏢 PSU, 📋 scheme, etc.)
- Canonical name
- One-line stat: "8 reports · 650 mentions"
- Click → entity page (or directory if it's a tier/category aggregate)

Filter out any tile where `canonical_name === "Unknown Ministry"`.

---

## 16. API client additions (`lib/api.ts`)

Add functions for new endpoints:

```ts
// Home
getHomeStats(): Promise<HomeStats>
getHomeFacets(): Promise<HomeFacets>
getHomeFeatured(): Promise<HomeFeatured>
getHomeTrending(): Promise<TrendingSearch[]>
getSurpriseReport(): Promise<APIReportSummary>
getSurpriseEntity(): Promise<EntitySummary>

// Search
smartSearch(params: { q: string; type?: SearchChannel; limit?: number }): Promise<GroupedSearchResults>

// Entity (typed wrappers around existing /api/entities endpoints)
getEntityFull(id: number): Promise<EntityDetail>
```

Type definitions:
- `HomeStats`, `HomeFacets`, `HomeFeatured`, `TrendingSearch`
- `EntitySummary`, `EntityDetail`
- `GroupedSearchResults`, `SearchChannel`, `SearchResultRow` (discriminated union by `kind`)
- `GroundednessReport` (matching Phase 13 payload)

Match field names exactly to backend Pydantic models in `02_backend_implementation_plan.md`.

---

## 17. CSS / styling — Path B

Create `frontend/components/Home/home.css`. Import only in `HomePage.tsx`. All classes prefixed with `.home-` to prevent bleed.

### 17.1 Color theme

Identical to existing app — same slate/sky palette, same body text colors, same border styles. The home page inherits color tokens from `index.css` either via CSS custom properties or by reusing the same Tailwind utility classes already in use elsewhere.

### 17.2 What's distinct on home

- **Larger type scale** in the hero — title at ~64-80px (vs. 32px on directory)
- **Stats tiles** with bigger numbers (~48px) and uppercase labels with letter-spacing
- **Single dominant search bar** — 720px wide, prominent border-radius, subtle drop shadow on focus
- **Discovery rails** with horizontal scroll-snap: `overflow-x: auto; scroll-snap-type: x mandatory`
- **Tile hover states** — slight lift (`transform: translateY(-2px)`) and shadow

No dark mode. No new design tokens. Reuse existing palette.

### 17.3 Entity page styling

Add to `home.css` (or split into `entity.css` if it grows). Same color palette.

---

## 18. Routing transitions and back-button behavior

No react-router; navigation is state-driven. Back semantics:

| From | "Back" target | How |
|---|---|---|
| Home → Directory (CTA or facet) | Home | Logo click |
| Home → Entity page | Home | Back button on entity page header |
| Home → Report detail | Home | Existing back handler, retargeted |
| Directory → Report detail | Directory | Existing |
| Entity page → Report detail | Entity page | New |
| Any view → Home | Home | Logo click or "Home" nav button |

`previousView: ViewState | null` in app store + `goBack()` action that pops it. On any `setView()` call, push the current view onto `previousView` first.

---

## 19. Performance

### 19.1 Initial home page load

Target time-to-interactive: <1s on a fast connection.

Three parallel calls on mount from `HomePage.tsx`:
- `/api/home/stats` (~50ms)
- `/api/home/facets` (~30ms)
- `/api/home/featured` (~100ms)

Fire in parallel from a single effect. Don't block hero rendering — show "—" placeholders for numbers until they resolve. Search bar interactive immediately.

### 19.2 SmartSearch latency

Target dropdown render after first keystroke: <250ms p95.

- Lexical channels (reports, ministries, entities, glossary) hit in-memory or fast Postgres indexes. <50ms each. Render first.
- Findings channel (Qdrant semantic) ~200ms. Render as it arrives.

### 19.3 Code splitting

`HomePage` imported via `React.lazy()` so direct deep-links to a report don't load home assets. `EntityPage` similarly lazy. Not critical for v1 if bundle stays under ~600KB gzipped.

---

## 20. Phased rollout

### Phase 0 — `index.tsx` refactor (1 day)

Extract `DirectoryPage` and `TimeSeriesPage` as described in §2. No behavior change. Ship and verify nothing regressed before doing any home work.

### Phase A — Home scaffold (1.5 days)

- Add `'home'` and `'entity'` to `ViewState`, add `Home` button to nav
- Create `HomePage.tsx` with hero (title, search bar, explainer, stats tiles) and three CTA cards
- All stats hardcoded; no smart search yet
- Search bar renders but is non-functional (placeholder only)
- Facet chips render as static buttons
- Discovery rails stub: `<div>Loading...</div>` placeholders
- `home.css` set up
- Footer with disclaimer link

Ships a major UX upgrade just by adding a real landing surface.

### Phase B — Real data on home (2 days)

- `useHomeStats`, `useHomeFacets`, `useHomeFeatured` hooks
- `StatsTiles` reads from real endpoints
- `MinistryRail`, `EntityRail`, `FeaturedReportsRail` (sorted by `report_year` desc), `DeepDivesRail` render real data
- `PopularStartingPoints` with 10 deterministic tiles
- `FacetChips` deep-link to directory with filters
- `SurpriseMeButton` works for both variants

### Phase C — Smart search (3 days)

- `SmartSearchBar` with debounced multi-channel
- `SearchDropdown` with grouped results
- `EntityChannelTabs` filtering
- `useSmartSearch` hook with `AbortController` cancellation
- Smart Enter routing logic
- `TrendingSearches` rail (depends on backend `/api/home/trending`)

### Phase D — Entity page + Groundedness UI (2 days)

- `'entity'` view + `EntityPage` component tree
- Click-through from search/rails to entity page
- `ChatMessage` groundedness badge + expandable panel
- `useChatStream` updates to capture groundedness in store

### Phase E — Polish (1 day)

- `/` keyboard shortcut
- Empty-state copy in search dropdown
- Subtle animations on smart Enter routing
- Filter `"Unknown Ministry"` guards verified across all entry points

**Total**: ~10.5 frontend days end-to-end including Phase 0 refactor.

---

## 21. Things to NOT change

Stays byte-identical:

- `PDFViewer.tsx`
- `SideDrawer.tsx`
- `TablePreview.tsx`
- `ArtifactCard.tsx`
- The entire `HowItWorks/` tree
- Citation handling in `appStore`, `lib/citationUtils.ts`, and `ChatMessage` (except for the groundedness additions in §11)
- `useReports`, `useReport`, `useCharts`, `useTables`, `useSeries`, `useSeriesChat`, `useOverview`, `useSummaries` hooks
- `ReportCard` component (reused on home rails)
- Series-chat view in `index.tsx`
- Report detail tabs (Overview, Findings, Recommendations, Charts, Tables, Summaries)
- The hero section, multi-paragraph explainer, and disclaimer on the directory page (these stay there)

---

## 22. "Unknown Ministry" filtering — checklist

The string `"Unknown Ministry"` (or any value where the lowercased string contains `'unknown'`) must be filtered from:

- [ ] `MinistryRail` — exclude tiles
- [ ] `FeaturedReportsRail` — show report but suppress ministry label
- [ ] `PopularStartingPoints` — exclude tiles
- [ ] `SearchDropdown` Reports channel — show report but suppress ministry label
- [ ] `SearchDropdown` Ministries channel — exclude entirely
- [ ] `FacetChips` Ministry popover — exclude option
- [ ] `ReportCard` — already handles this via `isValidOrg` helper; verify

Centralize the check: add `isValidMinistry(value: string | null): boolean` to `frontend/utils.ts` and use it everywhere. One source of truth.

---

End of plan.
