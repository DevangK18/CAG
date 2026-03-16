# Backend Redesign - Detailed Implementation Plan

This plan provides step-by-step implementation instructions for Sonnet. Each section includes exact file paths, field names, and code patterns.

---

## Implementation Order

1. **Findings & Recommendations Text Fix** (highest user impact)
2. **Executive Summary** (straightforward routing)
3. **Tables Deduplication + Preview** (backend naming + preview extraction)

---

# TASK 1: Findings & Recommendations - Full Text Resolution

## Problem Summary
- `semantic_enrichment.findings[].text` is often truncated mid-sentence
- The `source_chunk_id` field points to the full source chunk in `child_chunks[]`
- Need to resolve full text at API level and add expand/collapse in frontend

## Backend Implementation

### Step 1.1: Create Text Resolution Utility

**File:** `src/api/utils/text_resolution.py` (NEW FILE)

```python
"""Utilities for resolving truncated text from source chunks."""
import re
from typing import Optional

# Sentence terminators that indicate complete text
SENTENCE_TERMINATORS = {'.', ')', ']', '"', '?', '!'}

# Leading bullet characters to strip
BULLET_CHARS = re.compile(r'^[\s]*[•➢\-–—\*►▪◦○●]\s*')


def is_truncated(text: str) -> bool:
    """Check if text appears to be truncated (doesn't end with sentence terminator)."""
    if not text:
        return True
    text = text.rstrip()
    if not text:
        return True
    return text[-1] not in SENTENCE_TERMINATORS


def clean_bullet_prefix(text: str) -> str:
    """Remove leading bullet characters from text."""
    return BULLET_CHARS.sub('', text).strip()


def find_sentence_boundary(content: str, start_pos: int) -> int:
    """
    Find the next sentence boundary after start_pos.
    Returns the position after the terminator (or end of string).
    """
    # Look for sentence terminators followed by space, newline, or end
    pattern = re.compile(r'[.!?](?:\s|$|"|\)|\])')
    match = pattern.search(content, start_pos)
    if match:
        # Return position after the terminator
        return match.start() + 1
    # No boundary found, return end of content
    return len(content)


def resolve_full_text(
    truncated_text: str,
    source_chunk_content: str
) -> str:
    """
    Resolve truncated text by finding it in source chunk and extending to sentence boundary.

    Args:
        truncated_text: The potentially truncated finding/recommendation text
        source_chunk_content: The full content of the source chunk

    Returns:
        The complete text extended to sentence boundary, or original if not found
    """
    if not truncated_text or not source_chunk_content:
        return truncated_text or ""

    # Clean both texts for matching
    clean_truncated = truncated_text.strip()
    clean_source = source_chunk_content.strip()

    # If text is not truncated, just clean bullets and return
    if not is_truncated(clean_truncated):
        return clean_bullet_prefix(clean_truncated)

    # Try to find the truncated text in source
    # Use the last ~50 chars of truncated text for matching (more reliable than full text)
    search_suffix = clean_truncated[-50:] if len(clean_truncated) > 50 else clean_truncated

    pos = clean_source.find(search_suffix)
    if pos == -1:
        # Try case-insensitive search
        pos = clean_source.lower().find(search_suffix.lower())

    if pos == -1:
        # Could not find in source, return cleaned original
        return clean_bullet_prefix(clean_truncated)

    # Found! Now extend to next sentence boundary
    end_of_match = pos + len(search_suffix)
    boundary = find_sentence_boundary(clean_source, end_of_match)

    # Extract full text: from start of truncated position to sentence boundary
    # First, find where the truncated text actually starts
    truncated_start = clean_truncated[:30] if len(clean_truncated) > 30 else clean_truncated
    start_pos = clean_source.find(truncated_start)
    if start_pos == -1:
        start_pos = clean_source.lower().find(truncated_start.lower())
    if start_pos == -1:
        start_pos = pos - len(clean_truncated) + len(search_suffix)
        start_pos = max(0, start_pos)

    full_text = clean_source[start_pos:boundary].strip()
    return clean_bullet_prefix(full_text)
```

### Step 1.2: Update Overview Route to Resolve Findings Text

**File:** `src/api/routes/overview.py`

Find the `get_findings` endpoint (around line 150-200). Modify it to resolve truncated text.

**Add import at top:**
```python
from src.api.utils.text_resolution import resolve_full_text, clean_bullet_prefix, is_truncated
```

**Modify the findings endpoint to:**
1. Load child_chunks from the main chunks file (for source_chunk_id lookup)
2. For each finding, check if text is truncated
3. If truncated, resolve from source_chunk_id

**Implementation pattern:**
```python
@router.get("/reports/{report_id}/findings")
async def get_findings(
    report_id: str,
    # ... existing params
):
    # Load overview data (existing code)
    overview_path = PROCESSED_DIR / f"{report_id}_overview.json"
    # ...

    # NEW: Also load chunks file for source resolution
    chunks_path = PROCESSED_DIR / f"{report_id}_chunks.json"
    child_chunks_lookup = {}
    if chunks_path.exists():
        with open(chunks_path) as f:
            chunks_data = json.load(f)
            # Build lookup dict: chunk_id -> content
            for chunk in chunks_data.get("child_chunks", []):
                child_chunks_lookup[chunk["chunk_id"]] = chunk.get("content", "")

    # Process findings (existing loop, add text resolution)
    findings_list = overview_data.get("findings_list", [])
    for finding in findings_list:
        # Resolve truncated text
        source_id = finding.get("source_chunk_id")
        if source_id and source_id in child_chunks_lookup:
            original_text = finding.get("text", "")
            if is_truncated(original_text):
                finding["text"] = resolve_full_text(
                    original_text,
                    child_chunks_lookup[source_id]
                )

        # Clean bullet prefixes from text and summary
        finding["text"] = clean_bullet_prefix(finding.get("text", ""))
        finding["summary"] = clean_bullet_prefix(finding.get("summary", ""))

    # ... rest of existing code
```

### Step 1.3: Update Recommendations Endpoint Similarly

Same file, find `get_recommendations` endpoint and apply same pattern:

```python
@router.get("/reports/{report_id}/recommendations")
async def get_recommendations(report_id: str, ...):
    # Load overview + chunks (same pattern as findings)
    # ...

    recommendations = overview_data.get("recommendations", [])
    for rec in recommendations:
        source_id = rec.get("source_chunk_id")
        if source_id and source_id in child_chunks_lookup:
            original_text = rec.get("text", "")
            if is_truncated(original_text):
                rec["text"] = resolve_full_text(
                    original_text,
                    child_chunks_lookup[source_id]
                )

        rec["text"] = clean_bullet_prefix(rec.get("text", ""))
        rec["summary"] = clean_bullet_prefix(rec.get("summary", ""))
```

### Step 1.4: Consider Caching (Optional Optimization)

If performance is a concern, cache the child_chunks_lookup at service level:

**File:** `src/api/services/report_service.py`

Add a method to get child chunks lookup:
```python
_chunks_cache: dict[str, dict] = {}

def get_child_chunks_lookup(report_id: str) -> dict[str, str]:
    """Get chunk_id -> content lookup for a report."""
    if report_id in _chunks_cache:
        return _chunks_cache[report_id]

    chunks_path = PROCESSED_DIR / f"{report_id}_chunks.json"
    if not chunks_path.exists():
        return {}

    with open(chunks_path) as f:
        data = json.load(f)

    lookup = {
        chunk["chunk_id"]: chunk.get("content", "")
        for chunk in data.get("child_chunks", [])
    }
    _chunks_cache[report_id] = lookup
    return lookup
```

---

## Frontend Implementation

### Step 1.5: Update FindingItem Type

**File:** `frontend/types.ts`

The `FindingItem` interface should already have `text` and `summary`. Verify these fields exist:

```typescript
interface FindingItem {
  id: string;
  severity: 'critical' | 'high' | 'medium' | 'low';
  type: string;
  amount_crore: number | null;
  chapter: string;
  section: string;
  page: number;
  text: string;      // Full resolved text
  summary: string;   // First ~200 chars for preview
  source_chunk_id?: string;
}
```

### Step 1.6: Create Expandable Finding Card Component

**File:** `frontend/components/FindingCard.tsx` (NEW FILE)

```tsx
import React, { useState } from 'react';

interface FindingCardProps {
  finding: {
    id: string;
    severity: 'critical' | 'high' | 'medium' | 'low';
    type: string;
    amount_crore: number | null;
    chapter: string;
    section: string;
    page: number;
    text: string;
    summary: string;
  };
  onNavigate?: (page: number) => void;
}

const SEVERITY_COLORS = {
  critical: { bg: 'bg-red-50', border: 'border-red-200', badge: 'bg-red-100 text-red-700' },
  high: { bg: 'bg-amber-50', border: 'border-amber-200', badge: 'bg-amber-100 text-amber-700' },
  medium: { bg: 'bg-blue-50', border: 'border-blue-200', badge: 'bg-blue-100 text-blue-700' },
  low: { bg: 'bg-slate-50', border: 'border-slate-200', badge: 'bg-slate-100 text-slate-600' },
};

export function FindingCard({ finding, onNavigate }: FindingCardProps) {
  const [expanded, setExpanded] = useState(false);
  const colors = SEVERITY_COLORS[finding.severity] || SEVERITY_COLORS.medium;

  // Determine if we need expand/collapse (text significantly longer than summary)
  const needsExpand = finding.text.length > finding.summary.length + 50;

  // Display text: summary when collapsed, full text when expanded
  const displayText = expanded ? finding.text : finding.summary;

  // Format monetary value
  const monetaryDisplay = finding.amount_crore
    ? `₹${finding.amount_crore.toLocaleString('en-IN')} Cr`
    : null;

  return (
    <div className={`rounded-lg border ${colors.border} ${colors.bg} p-4`}>
      {/* Header: Severity + Type + Monetary */}
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <span className={`px-2 py-0.5 rounded text-xs font-medium uppercase ${colors.badge}`}>
          {finding.severity}
        </span>
        <span className="px-2 py-0.5 rounded text-xs bg-slate-100 text-slate-600">
          {finding.type.replace(/_/g, ' ')}
        </span>
        {monetaryDisplay && (
          <span className="px-2 py-0.5 rounded text-xs bg-emerald-100 text-emerald-700 font-medium">
            {monetaryDisplay}
          </span>
        )}
      </div>

      {/* Breadcrumb: Chapter > Section */}
      <div className="text-xs text-slate-500 mb-2">
        {finding.chapter}
        {finding.section && finding.section !== finding.chapter && (
          <> › {finding.section}</>
        )}
        <span
          className="ml-2 text-blue-600 cursor-pointer hover:underline"
          onClick={() => onNavigate?.(finding.page)}
        >
          p.{finding.page}
        </span>
      </div>

      {/* Text Content */}
      <p className="text-sm text-slate-700 leading-relaxed">
        {displayText}
        {!expanded && needsExpand && '...'}
      </p>

      {/* Expand/Collapse Toggle */}
      {needsExpand && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="mt-2 text-xs text-blue-600 hover:text-blue-800 font-medium"
        >
          {expanded ? 'Show less ↑' : 'Show more ↓'}
        </button>
      )}
    </div>
  );
}
```

### Step 1.7: Create Recommendation Card Component

**File:** `frontend/components/RecommendationCard.tsx` (NEW FILE)

```tsx
import React, { useState } from 'react';

interface RecommendationCardProps {
  recommendation: {
    id: string;
    text: string;
    summary: string;
    chapter: string;
    section?: string;
    page: number;
    status?: 'pending' | 'accepted' | 'implemented' | 'rejected';
    target_entity?: string;
    extraction_strategy?: string;
    rec_number?: string;
  };
  onNavigate?: (page: number) => void;
}

const STATUS_COLORS = {
  pending: 'bg-yellow-100 text-yellow-700',
  accepted: 'bg-green-100 text-green-700',
  implemented: 'bg-emerald-100 text-emerald-700',
  rejected: 'bg-red-100 text-red-700',
};

export function RecommendationCard({ recommendation, onNavigate }: RecommendationCardProps) {
  const [expanded, setExpanded] = useState(false);

  const needsExpand = recommendation.text.length > recommendation.summary.length + 50;
  const displayText = expanded ? recommendation.text : recommendation.summary;
  const statusColor = STATUS_COLORS[recommendation.status || 'pending'];

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      {/* Header: Status + Target Entity */}
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        {recommendation.status && (
          <span className={`px-2 py-0.5 rounded text-xs font-medium ${statusColor}`}>
            {recommendation.status}
          </span>
        )}
        {recommendation.target_entity && (
          <span className="px-2 py-0.5 rounded text-xs bg-purple-100 text-purple-700">
            {recommendation.target_entity}
          </span>
        )}
        {recommendation.rec_number && (
          <span className="text-xs text-slate-500">
            {recommendation.rec_number}
          </span>
        )}
      </div>

      {/* Breadcrumb */}
      <div className="text-xs text-slate-500 mb-2">
        {recommendation.chapter}
        {recommendation.section && recommendation.section !== recommendation.chapter && (
          <> › {recommendation.section}</>
        )}
        <span
          className="ml-2 text-blue-600 cursor-pointer hover:underline"
          onClick={() => onNavigate?.(recommendation.page)}
        >
          p.{recommendation.page}
        </span>
      </div>

      {/* Text Content */}
      <p className="text-sm text-slate-700 leading-relaxed">
        {displayText}
        {!expanded && needsExpand && '...'}
      </p>

      {/* Expand/Collapse Toggle */}
      {needsExpand && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="mt-2 text-xs text-blue-600 hover:text-blue-800 font-medium"
        >
          {expanded ? 'Show less ↑' : 'Show more ↓'}
        </button>
      )}
    </div>
  );
}
```

### Step 1.8: Update Main App to Use New Components

**File:** `frontend/index.tsx`

Find the Findings tab section (search for `activeTab === 'findings'`) and replace the current rendering with the new component:

```tsx
// Add import at top
import { FindingCard } from './components/FindingCard';
import { RecommendationCard } from './components/RecommendationCard';

// In the render section for findings tab:
{activeTab === 'findings' && (
  <div className="space-y-3 p-4">
    {findingsList?.map((finding) => (
      <FindingCard
        key={finding.id}
        finding={finding}
        onNavigate={(page) => {
          setPdfPage(page);
          // Optionally scroll PDF into view
        }}
      />
    ))}
  </div>
)}

// Similarly for recommendations tab:
{activeTab === 'recommendations' && (
  <div className="space-y-3 p-4">
    {recommendations?.map((rec) => (
      <RecommendationCard
        key={rec.id}
        recommendation={rec}
        onNavigate={(page) => setPdfPage(page)}
      />
    ))}
  </div>
)}
```

---

# TASK 2: Executive Summary - AI-Powered Content

## Problem Summary
- Current executive summary shows raw concatenated chunk text
- AI summaries already exist in `data/batch_jobs/summaries/{report_id}_summaries.json`
- Need to serve Executive Brief variant in overview tab

## Backend Implementation

### Step 2.1: Update Overview Endpoint to Include AI Summary

**File:** `src/api/routes/overview.py`

Modify the main `get_overview` endpoint to include an `executive_summary` field sourced from the AI summaries:

```python
from pathlib import Path

SUMMARIES_DIR = Path("data/batch_jobs/summaries")

@router.get("/reports/{report_id}/overview")
async def get_overview(report_id: str):
    # ... existing overview loading code ...

    # NEW: Load AI executive summary
    ai_executive_summary = None
    summaries_path = SUMMARIES_DIR / f"{report_id}_summaries.json"

    if summaries_path.exists():
        try:
            with open(summaries_path) as f:
                summaries_data = json.load(f)

            # Get executive variant (best for overview tab)
            executive_variant = summaries_data.get("variants", {}).get("executive", {})
            full_content = executive_variant.get("content", "")

            if full_content:
                # Extract first 2-3 paragraphs, cap at ~300 words
                ai_executive_summary = extract_overview_excerpt(full_content, max_words=300)
        except Exception as e:
            logger.warning(f"Failed to load AI summary for {report_id}: {e}")

    # Build response with AI summary
    response = {
        # ... existing fields ...
        "executive_summary": ai_executive_summary,  # NEW: AI-generated
        "executive_summary_fallback": overview_data.get("executive_summary_index"),  # Original
    }

    return response


def extract_overview_excerpt(content: str, max_words: int = 300) -> str:
    """
    Extract first ~300 words from AI summary, preserving paragraph structure.
    Aims to include Context & Scope and first key finding sections.
    """
    paragraphs = content.split('\n\n')
    excerpt_parts = []
    word_count = 0

    for para in paragraphs:
        # Skip markdown headers for word count but include them
        para_text = para.strip()
        if not para_text:
            continue

        # Count words (excluding markdown syntax)
        clean_text = re.sub(r'[#*_\[\]()]', '', para_text)
        para_words = len(clean_text.split())

        if word_count + para_words > max_words and excerpt_parts:
            # We've hit the limit, stop here
            break

        excerpt_parts.append(para_text)
        word_count += para_words

    return '\n\n'.join(excerpt_parts)
```

### Step 2.2: Update Overview Response Model

**File:** `src/api/models.py` (if using Pydantic models for responses)

Add the new field to the overview response:

```python
class OverviewResponse(BaseModel):
    # ... existing fields ...
    executive_summary: Optional[str] = None  # AI-generated excerpt
    executive_summary_fallback: Optional[dict] = None  # Original index
```

---

## Frontend Implementation

### Step 2.3: Update useOverview Hook Return Type

**File:** `frontend/hooks/useOverview.ts`

The hook should already return the full overview object. Verify that `executive_summary` is accessible:

```typescript
interface OverviewData {
  // ... existing fields ...
  executive_summary?: string;  // AI-generated excerpt (new)
  executive_summary_fallback?: ExecutiveSummaryIndex;  // Original
}
```

### Step 2.4: Update Overview Tab to Display AI Summary

**File:** `frontend/index.tsx`

Find the Overview tab section and update the executive summary display:

```tsx
{activeTab === 'overview' && overview && (
  <div className="p-4 space-y-6">
    {/* Executive Summary Section */}
    <section>
      <h3 className="text-lg font-semibold text-slate-800 mb-3">Executive Summary</h3>

      {overview.executive_summary ? (
        <div className="prose prose-sm max-w-none">
          {/* Render AI-generated summary with markdown */}
          {renderMarkdown(overview.executive_summary)}

          {/* Link to full summary */}
          <button
            onClick={() => {
              setActiveTab('summaries');
              // Optionally pre-select executive variant
            }}
            className="mt-3 text-sm text-blue-600 hover:text-blue-800 font-medium inline-flex items-center gap-1"
          >
            Read full summary
            <span aria-hidden="true">→</span>
          </button>
        </div>
      ) : (
        // Fallback to original executive summary index
        <div className="text-sm text-slate-600">
          {overview.executive_summary_fallback?.items?.map((item, idx) => (
            <p key={idx} className="mb-2">{item.text}</p>
          )) || (
            <p className="text-slate-400 italic">No executive summary available</p>
          )}
        </div>
      )}
    </section>

    {/* ... rest of overview sections ... */}
  </div>
)}
```

### Step 2.5: Add "Read Full Summary" Navigation

When clicking "Read full summary", switch to Summaries tab and pre-select executive variant:

```tsx
// In the useSummaries hook usage area, track selected variant
const { selectVariant } = useSummaries(currentReportId);

// Update the link handler:
onClick={() => {
  setActiveTab('summaries');
  selectVariant('executive');  // Pre-select executive variant
}}
```

---

# TASK 3: Tables - Deduplication + Data Previews

## Problem Summary
- Multiple tables share identical names (e.g., "Data Table: 2.3 Sources...")
- Tables have `structured_data` with full row/column data but it's not exposed in UI
- Need: (1) disambiguate duplicate names, (2) provide mini-table preview

## Backend Implementation

### Step 3.1: Create Table Utilities

**File:** `src/api/utils/table_utils.py` (NEW FILE)

```python
"""Utilities for table name deduplication and preview generation."""
import re
from typing import Optional
from collections import Counter


def clean_table_caption(caption: str) -> str:
    """
    Clean up table caption:
    - Remove generic "Data Table:" prefix if caption starts with section number
    - Strip whitespace
    """
    if not caption:
        return "Untitled Table"

    caption = caption.strip()

    # If starts with "Data Table:" followed by a number, remove the prefix
    # Pattern: "Data Table: 2.3 Title" -> "2.3 Title"
    if caption.lower().startswith("data table:"):
        rest = caption[11:].strip()
        # Check if it starts with a section number (e.g., "2.3", "12.1.2")
        if re.match(r'^\d+\.', rest):
            return rest

    return caption


def disambiguate_table_names(tables: list[dict]) -> list[dict]:
    """
    Add disambiguators to tables with duplicate captions.

    Priority:
    1. Use structured_data.title if unique
    2. Append page number: "Title (Page 24)"
    3. Append dimensions: "Title (7×3)"
    """
    # First pass: clean all captions and count duplicates
    for table in tables:
        table["_clean_caption"] = clean_table_caption(table.get("caption", ""))

    caption_counts = Counter(t["_clean_caption"] for t in tables)

    # Second pass: disambiguate duplicates
    seen_captions: dict[str, int] = {}

    for table in tables:
        clean_cap = table["_clean_caption"]

        if caption_counts[clean_cap] > 1:
            # This caption has duplicates, need to disambiguate

            # Try 1: Use structured_data.title if different and unique
            struct_title = (table.get("structured_data") or {}).get("title", "")
            if struct_title and struct_title != clean_cap:
                # Check if this title would be unique
                other_titles = [
                    (t.get("structured_data") or {}).get("title", "")
                    for t in tables if t["_clean_caption"] == clean_cap and t is not table
                ]
                if struct_title not in other_titles:
                    table["display_caption"] = clean_table_caption(struct_title)
                    continue

            # Try 2: Append page number
            page = table.get("page")
            if page:
                disambiguated = f"{clean_cap} (Page {page})"
                if disambiguated not in seen_captions:
                    table["display_caption"] = disambiguated
                    seen_captions[disambiguated] = 1
                    continue

            # Try 3: Append dimensions
            rows = table.get("rows", 0)
            cols = table.get("columns", 0)
            if rows and cols:
                disambiguated = f"{clean_cap} ({rows}×{cols})"
                if disambiguated not in seen_captions:
                    table["display_caption"] = disambiguated
                    seen_captions[disambiguated] = 1
                    continue

            # Fallback: append index
            idx = seen_captions.get(clean_cap, 0) + 1
            seen_captions[clean_cap] = idx
            table["display_caption"] = f"{clean_cap} ({idx})"
        else:
            # Unique caption, use as-is
            table["display_caption"] = clean_cap

    # Clean up temp field
    for table in tables:
        del table["_clean_caption"]

    return tables


def extract_table_preview(
    structured_data: Optional[dict],
    max_rows: int = 3,
    max_cols: int = 4,
    max_cell_chars: int = 12
) -> Optional[dict]:
    """
    Extract a mini-preview from structured_data for card display.

    Returns:
        {
            "headers": ["Col1", "Col2", ...],  # Up to max_cols
            "rows": [["val1", "val2", ...], ...],  # Up to max_rows
            "truncated": {"rows": bool, "cols": bool}
        }
    """
    if not structured_data:
        return None

    columns = structured_data.get("columns", [])
    rows = structured_data.get("rows", [])

    if not columns or not rows:
        return None

    # Extract headers (first max_cols columns)
    headers = []
    for col in columns[:max_cols]:
        header = col.get("header_text", "") or f"Col {col.get('col_idx', 0) + 1}"
        # Truncate long headers
        if len(header) > max_cell_chars:
            header = header[:max_cell_chars - 1] + "…"
        headers.append(header)

    # Extract data rows (skip header rows, take first max_rows data rows)
    preview_rows = []
    data_row_count = 0

    for row in rows:
        if row.get("row_type") == "header":
            continue

        if data_row_count >= max_rows:
            break

        cells = row.get("cells", [])
        row_data = []

        for cell in cells[:max_cols]:
            text = cell.get("cleaned_text") or cell.get("raw_text", "")
            # Truncate long cell values
            if len(text) > max_cell_chars:
                text = text[:max_cell_chars - 1] + "…"
            row_data.append(text)

        # Pad row if needed
        while len(row_data) < len(headers):
            row_data.append("")

        preview_rows.append(row_data)
        data_row_count += 1

    if not preview_rows:
        return None

    return {
        "headers": headers,
        "rows": preview_rows,
        "truncated": {
            "rows": len(rows) > max_rows + 1,  # +1 for header row
            "cols": len(columns) > max_cols
        }
    }
```

### Step 3.2: Update Tables Endpoint

**File:** `src/api/routes/assets.py`

Find the `get_tables` endpoint and modify it to use the new utilities:

```python
from src.api.utils.table_utils import disambiguate_table_names, extract_table_preview

@router.get("/reports/{report_id}/tables")
async def get_tables(
    report_id: str,
    page: Optional[int] = None,
    min_rows: Optional[int] = None,
    min_columns: Optional[int] = None,
    limit: int = 50,
    offset: int = 0
):
    # ... existing table loading code ...

    # After loading tables list:
    tables = load_tables_from_chunks(report_id)  # existing function

    # Add preview data to each table
    for table in tables:
        structured_data = table.get("structured_data")
        table["preview"] = extract_table_preview(structured_data)

    # Disambiguate duplicate names
    tables = disambiguate_table_names(tables)

    # Apply filters (existing code)
    if page is not None:
        tables = [t for t in tables if t.get("page") == page]
    if min_rows:
        tables = [t for t in tables if t.get("rows", 0) >= min_rows]
    if min_columns:
        tables = [t for t in tables if t.get("columns", 0) >= min_columns]

    # Apply pagination
    total = len(tables)
    tables = tables[offset:offset + limit]

    return {
        "tables": tables,
        "total": total,
        "limit": limit,
        "offset": offset
    }
```

### Step 3.3: Update Table Response Model

**File:** `src/api/models.py`

Add preview field to TableItem:

```python
class TablePreview(BaseModel):
    headers: list[str]
    rows: list[list[str]]
    truncated: dict  # {"rows": bool, "cols": bool}

class TableItem(BaseModel):
    id: str
    title: str  # Will be display_caption
    section: str
    page: int
    rows: int
    columns: int
    analysis: Optional[str] = None
    headers: Optional[list[str]] = None
    preview: Optional[TablePreview] = None  # NEW
    # ... other fields
```

---

## Frontend Implementation

### Step 3.4: Update TableItem Type

**File:** `frontend/types.ts`

```typescript
interface TablePreview {
  headers: string[];
  rows: string[][];
  truncated: {
    rows: boolean;
    cols: boolean;
  };
}

interface TableItem {
  id: string;
  title: string;  // Now disambiguated
  section: string;
  page: number;
  rows: number;
  columns: number;
  analysis?: string;
  headers?: string[];
  preview?: TablePreview;  // NEW
  source_chunk_id?: string;
  bbox?: number[];
}
```

### Step 3.5: Create Mini-Table Preview Component

**File:** `frontend/components/TablePreview.tsx` (NEW FILE)

```tsx
import React from 'react';

interface TablePreviewProps {
  preview: {
    headers: string[];
    rows: string[][];
    truncated: {
      rows: boolean;
      cols: boolean;
    };
  };
}

export function TablePreview({ preview }: TablePreviewProps) {
  return (
    <div className="overflow-hidden rounded border border-slate-200 bg-white">
      <table className="w-full text-[10px] font-mono">
        <thead>
          <tr className="bg-slate-100">
            {preview.headers.map((header, idx) => (
              <th
                key={idx}
                className="px-1 py-0.5 text-left text-slate-600 font-medium truncate max-w-[60px]"
                title={header}
              >
                {header}
              </th>
            ))}
            {preview.truncated.cols && (
              <th className="px-1 py-0.5 text-slate-400">…</th>
            )}
          </tr>
        </thead>
        <tbody>
          {preview.rows.map((row, rowIdx) => (
            <tr
              key={rowIdx}
              className={rowIdx % 2 === 0 ? 'bg-white' : 'bg-slate-50'}
            >
              {row.map((cell, cellIdx) => (
                <td
                  key={cellIdx}
                  className="px-1 py-0.5 text-slate-700 truncate max-w-[60px]"
                  title={cell}
                >
                  {cell || '-'}
                </td>
              ))}
              {preview.truncated.cols && (
                <td className="px-1 py-0.5 text-slate-400">…</td>
              )}
            </tr>
          ))}
          {preview.truncated.rows && (
            <tr className="bg-slate-50">
              <td
                colSpan={preview.headers.length + (preview.truncated.cols ? 1 : 0)}
                className="px-1 py-0.5 text-center text-slate-400"
              >
                …
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
```

### Step 3.6: Update Table Card Display

**File:** `frontend/index.tsx` (or wherever tables are rendered)

Find the Tables tab section and update to use the mini-table preview:

```tsx
import { TablePreview } from './components/TablePreview';

// In tables tab rendering:
{activeTab === 'tables' && (
  <div className="grid grid-cols-1 md:grid-cols-2 gap-4 p-4">
    {tables?.map((table) => (
      <div
        key={table.id}
        className="border border-slate-200 rounded-lg p-4 bg-white hover:shadow-md transition-shadow cursor-pointer"
        onClick={() => {
          // Navigate to table in PDF
          setPdfPage(table.page);
        }}
      >
        {/* Header with dimensions badge */}
        <div className="flex items-start justify-between mb-2">
          <h4 className="text-sm font-medium text-slate-800 line-clamp-2">
            {table.title}
          </h4>
          <span className="ml-2 px-2 py-0.5 rounded text-xs bg-slate-100 text-slate-600 whitespace-nowrap">
            {table.rows}×{table.columns}
          </span>
        </div>

        {/* Mini-table preview or fallback icon */}
        <div className="mb-2">
          {table.preview ? (
            <TablePreview preview={table.preview} />
          ) : (
            <div className="h-16 bg-slate-50 rounded flex items-center justify-center">
              <svg className="w-8 h-8 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 10h18M3 14h18m-9-4v8m-7 0h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
            </div>
          )}
        </div>

        {/* Section and page info */}
        <div className="text-xs text-slate-500">
          {table.section && <span>{table.section} · </span>}
          <span>Page {table.page}</span>
        </div>
      </div>
    ))}
  </div>
)}
```

---

# Testing Checklist

## Task 1: Findings & Recommendations
- [ ] Truncated finding text now shows full sentence
- [ ] Bullet prefixes (•, ➢, -) are removed from text
- [ ] Expand/collapse works when text is long
- [ ] Severity badges show correct colors (critical=red, high=amber, medium=blue)
- [ ] Monetary values display correctly (₹X,XXX Cr)
- [ ] Chapter/section breadcrumb displays
- [ ] Page click navigates PDF
- [ ] Recommendations show status badges
- [ ] Recommendations show target entity tags

## Task 2: Executive Summary
- [ ] AI-generated summary appears in Overview tab
- [ ] Summary is ~300 words or less
- [ ] Markdown renders correctly (headers, lists, bold)
- [ ] "Read full summary" link appears
- [ ] Clicking link navigates to Summaries tab with executive variant selected
- [ ] Fallback to original index when no AI summary exists

## Task 3: Tables
- [ ] Duplicate table names are disambiguated
- [ ] "Data Table:" prefix removed when redundant
- [ ] Mini-table preview displays in card
- [ ] Preview shows max 3 rows × 4 cols
- [ ] Long cell values truncated with ellipsis
- [ ] Truncation indicators (…) show when data is cut off
- [ ] Dimensions badge shows row×col count
- [ ] Click navigates to table page in PDF
- [ ] Fallback icon shows when no structured data

---

# File Summary

## New Files
- `src/api/utils/text_resolution.py` - Text truncation resolution
- `src/api/utils/table_utils.py` - Table naming and preview utilities
- `frontend/components/FindingCard.tsx` - Expandable finding card
- `frontend/components/RecommendationCard.tsx` - Expandable recommendation card
- `frontend/components/TablePreview.tsx` - Mini-table preview

## Modified Files
- `src/api/routes/overview.py` - Add text resolution, AI summary
- `src/api/routes/assets.py` - Add table disambiguation and preview
- `src/api/models.py` - Add new response fields
- `frontend/types.ts` - Add preview types
- `frontend/hooks/useOverview.ts` - Verify types
- `frontend/index.tsx` - Use new components
