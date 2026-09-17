# CAG Gateway — Backend-Coordinated Redesign Plan

## 1. Overview Tab — AI-Powered Executive Summary

**Problem:** Current executive summary is raw concatenated chunk text. AI summaries already exist in `data/batch_jobs/summaries/`.

**Strategy:** Serve a curated executive summary derived from the existing AI summary variants, not the raw `executive_summary_index` chunks.

**Backend changes:**
- In the overview API route (`services/api/routes/overview.py`), add an `executive_summary` field to the response.
- Source: Load the report's summary JSON from `data/batch_jobs/summaries/`. Use the **Executive Brief** variant — it's already tailored for decision-makers and is the closest match for an overview tab.
- Extract just the first 2-3 paragraphs (the "Context & Scope" and first key finding sections) — cap at ~300 words. This keeps the overview tab scannable while the full word version lives in the Summaries tab.
- Fallback: If no summary file exists for a report, fall back to the existing `executive_summary_index.items` text (current behavior).

**Frontend changes:**
- Replace the current executive summary text block with the AI-generated content.
- Add a "Read full summary →" link that switches to the Summaries tab with Executive Brief pre-selected.

**Files:** `services/api/routes/overview.py`, overview tab component in frontend, `frontend/hooks/useOverview.ts`

---

## 2. Key Findings & Recommendations — Full Text + Expand/Collapse

**Problem:** Texts truncated mid-sentence. Root cause: `semantic_enrichment.findings[].text` is cut off during extraction (confirmed: some don't end with sentence terminators). The `source_chunk_id` field points to the full source chunk.

**Strategy:** Two-layer fix — backend resolves full text, frontend adds expand/collapse.

**Backend changes (text resolution):**
- In the report detail API route (likely `services/api/routes/reports.py` or wherever findings/recs are served):
  - For each finding/recommendation, check if `.text` ends with a sentence terminator (`.`, `)`, `]`, `"`).
  - If truncated: look up the `source_chunk_id` in `child_chunks`, extract the full paragraph, and replace `.text` with the complete sentence(s). Use a simple heuristic — find the truncated suffix in the source chunk content, then extend to the next sentence boundary (`.` followed by space or end).
  - Preserve the original `.summary` field as-is (it's used for card previews).
- Also clean up leading bullet characters (`•`, `➢`, `-`) from both `.text` and `.summary` — normalize to clean text, let the frontend handle visual formatting.

**Alternative (pipeline-level fix):** If you want to fix at source, update `semantic_enrichment_service.py` to resolve sentence boundaries during extraction. But the API-level fix is faster and doesn't require re-processing all reports.

**Frontend changes:**
- Each finding/recommendation card: show `.summary` (or first ~2 sentences of `.text`) as the collapsed view.
- "Show more ↓" toggle expands to full `.text`.
- Add chapter/section context as a subtle breadcrumb below each item: `Chapter 3 › 3.2 Accuracy of Accounts` using the existing `chapter` and `section` fields.
- Findings: show severity badge (use existing `severity` field — `critical` = red, `high` = amber, `medium` = blue). Show monetary impact if `monetary_values` exists.
- Recommendations: show `status` badge (`pending` = yellow, `accepted` = green), `target_entity` as a tag.

**Files:** `services/api/routes/reports.py` (or wherever findings served), frontend findings/recommendations tab components

---


## 3. Tables Tab — Deduplicated Names + Data Previews

**Problem:** Multiple tables share identical names ("Data Table: 2.3 Sources and Utilisation of funds1"). Tables have `has_structured_data: true` with full row/column data — but none of it surfaces in the UI.

**Strategy:** Fix naming disambiguation + render a mini data preview as the table "thumbnail."

**Backend changes (naming):**
- When building the tables listing response, detect duplicate `caption` values.
- For duplicates, append a disambiguator. Priority order:
  1. If `structured_data.title` exists and is unique → use it.
  2. Else append page number: `"2.3 Sources and Utilisation of funds (Page 24)"`.
  3. Else append dimensions: `"2.3 Sources and Utilisation of funds (7×3)"`.
- Also: clean up the generic "Data Table:" prefix — if the caption already starts with a section number like "2.3", drop the prefix.

**Backend changes (preview data):**
- In the tables listing endpoint, include a `preview` field for each table:
  - Extract first 3 rows × first 4 columns from `structured_data.rows` and `structured_data.columns`.
  - Return as `{ headers: string[], rows: string[][] }` — just cleaned text values, no formatting.
  - This is lightweight (<1KB per table) and lets the frontend render a mini-table.

**Frontend changes:**
- In `ArtifactCard.tsx` (table variant): replace the grid icon placeholder with a **mini-table preview**.
  - Render a tiny HTML table in the card header area: 3 rows × 4 cols max, `text-[10px]` monospace, with a light grid. Cells truncated to ~8 chars each with `...`.
  - Use alternating row colors (`bg-slate-50` / `bg-white`) matching the green tint in the current design.
  - Keep dimensions badge (7×3) as an overlay, top-right.
- Updated caption display using the deduplicated name.
- If `preview` is null (no structured data), fall back to the existing icon.

**Files:** Table listing logic in `services/api/routes/reports.py` (or `assets.py`), `frontend/components/ArtifactCard.tsx`

---

## Implementation Order

1. **Findings & Recommendations text fix** — highest user impact, backend-only change to start, then frontend expand/collapse
2. **Executive Summary** — straightforward data routing, minimal risk
3. **Tables deduplication + preview** — backend naming fix is quick, preview data needs structured_data parsing

## Data Availability Summary

| Feature | Data exists? | Where | Gap |
|---|---|---|---|
| AI Executive Summary | ✅ | `data/batch_jobs/summaries/` | Need to route to overview API |
| Full finding text | ✅ | `child_chunks[source_chunk_id]` | Need sentence-boundary resolution |
| Table structured data | ✅ | `child_chunks[].structured_data` | Need preview extraction in API |
| Table dedup names | ✅ | `caption` + `page` + dims available | Need dedup logic in API |
