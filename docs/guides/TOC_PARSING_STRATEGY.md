# Table of Contents Parsing Strategy

**Last Updated:** 2026-02-24
**Status:** ✅ Fully Operational

---

## Executive Summary

The TOC (Table of Contents) parsing subsystem is the **foundational layer** of the CAG Interactive Gateway's RAG pipeline. It builds a rich, hierarchical document structure that enables:

1. **Parent-Child Chunking** - Section-level context (parents) linked to atomic content (children)
2. **Semantic Navigation** - Hierarchical document understanding for retrieval
3. **Query Auditability** - Citation paths showing exactly where information came from
4. **Multi-Level Filtering** - Navigate reports by chapter → section → subsection → paragraph

The deeper and more accurate the TOC, the better the RAG retrieval quality and citation precision.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Multi-Layer TOC Extraction Strategy](#multi-layer-toc-extraction-strategy)
3. [Phase 4: Scaffolding Service (Core TOC Building)](#phase-4-scaffolding-service)
4. [Intelligent TOC Service (Multi-Layer Orchestrator)](#intelligent-toc-service)
5. [TOC Table Parser (Printed TOC Extraction)](#toc-table-parser)
6. [Hierarchy Enricher (Deep Parent-Child Links)](#hierarchy-enricher)
7. [Integration: Chunking Service](#integration-chunking-service)
8. [Integration: Assembly Service](#integration-assembly-service)
9. [TOC Quality Metrics](#toc-quality-metrics)
10. [Code Reference Map](#code-reference-map)
11. [Known Limitations & Future Work](#known-limitations--future-work)

---

## Architecture Overview

### Pipeline Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    PHASE 4: SCAFFOLDING SERVICE                 │
│                     (src/parsing_pipeline/modules/              │
│                       scaffolding_service.py)                   │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────────┐         ┌────────────────────────────┐   │
│  │  Embedded TOC    │         │   Heuristic TOC            │   │
│  │  (PDF Bookmarks) │  ───►   │   (Font-Based Detection)   │   │
│  └──────────────────┘         └────────────────────────────┘   │
│         │                              │                        │
│         └──────────────┬───────────────┘                        │
│                        ▼                                        │
│              ┌──────────────────┐                               │
│              │  TOC Validation  │                               │
│              │  & Filtering     │                               │
│              └──────────────────┘                               │
│                        │                                        │
│                        ▼                                        │
│              ┌──────────────────┐                               │
│              │  Scaffold Output │                               │
│              │  - toc: [[level, │                               │
│              │          title,  │                               │
│              │          page]]  │                               │
│              │  - page_map      │                               │
│              │  - heading_pos   │                               │
│              └──────────────────┘                               │
└─────────────────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│              OPTIONAL: INTELLIGENT TOC SERVICE                  │
│              (src/parsing_pipeline/modules/                     │
│                intelligent_toc_service.py)                      │
├─────────────────────────────────────────────────────────────────┤
│  Layer 1: PDF Bookmarks (with quality scoring)                 │
│  Layer 2: TOC Table Parser (parse printed TOC from content)    │
│  Layer 3: Heuristic Detection (fallback)                       │
│  Layer 4: Hierarchy Enrichment (sub-section detection)         │
└─────────────────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│                   PHASE 7: CHUNKING SERVICE                     │
│                   (src/parsing_pipeline/modules/                │
│                     chunking_service.py)                        │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────────┐         ┌────────────────────────────┐   │
│  │  Parent Chunks   │         │   Child Chunks             │   │
│  │  (from TOC)      │  ───►   │   (from ExtractedContent)  │   │
│  │  - Section-level │         │   - Paragraph/Table/Image  │   │
│  │  - Page ranges   │         │   - Linked to parent       │   │
│  │  - Hierarchy     │         │   - Inherit hierarchy      │   │
│  └──────────────────┘         └────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│               PHASE 7.5: HIERARCHY ENRICHER                     │
│               (src/parsing_pipeline/modules/                    │
│                 hierarchy_enricher.py)                          │
├─────────────────────────────────────────────────────────────────┤
│  Detects sub-sections within large chapters:                   │
│  - Numbered sections: "1.1 Background", "1.2 Scope"            │
│  - Lettered sections: "A. Karnataka", "B. Rajasthan"           │
│  - Roman numerals: "(i) Finding", "(ii) Recommendation"        │
│  - Creates NEW parent chunks for detected sections             │
│  - Reassigns children to most specific parent                  │
└─────────────────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│                  PHASE 8: ASSEMBLY SERVICE                      │
│                  (src/parsing_pipeline/modules/                 │
│                    assembly_service.py)                         │
├─────────────────────────────────────────────────────────────────┤
│  Final JSON output with:                                       │
│  - parent_chunks[] with hierarchy metadata                     │
│  - child_chunks[] with parent_chunk_id links                   │
│  - visual_asset_registry (navigable TOC for frontend)          │
│  - footnote_index                                              │
└─────────────────────────────────────────────────────────────────┘
```

### Core Data Structures

**TOC Entry Format:**
```python
[level: int, title: str, page_physical: int]
```

**Example:**
```python
[
  [1, "Chapter I Introduction", 1],
  [2, "1.1 Background", 5],
  [2, "1.2 Audit Scope", 8],
  [1, "Chapter II Findings", 12],
  [2, "2.1 Financial Irregularities", 13],
  [3, "2.1.1 Irregular Expenditure", 14]
]
```

**Scaffold Output:**
```python
{
  "toc": [[level, title, page], ...],
  "page_map": {0: "i", 1: "ii", 10: "1", ...},
  "heading_positions": {"1_Chapter I": 72.5, ...}  # Y-coordinates
}
```

---

## Multi-Layer TOC Extraction Strategy

### Strategy: Hybrid Approach with Quality Gates

The pipeline uses a **cascading fallback strategy** to ensure every report gets the best possible TOC:

#### Current Implementation (ScaffoldingService)

**Layer 1: Embedded TOC (PDF Bookmarks)**
- **Source:** `PyMuPDF.get_toc()` extracts PDF outlines/bookmarks
- **Validation:**
  - Minimum 5 entries (configurable)
  - Multiple hierarchy levels required
  - Page coverage check (>10% of document pages)
- **Success Rate:** ~40% of CAG reports
- **Quality:** High when present, but often sparse or missing

**Layer 2: Heuristic TOC (Font-Based Detection)**
- **Source:** Multi-factor text block analysis
- **Triggers:** When embedded TOC fails validation
- **Method:**
  1. Extract all text blocks with font metadata
  2. Build style profile (baseline font size, common fonts)
  3. Score headings based on size, boldness, position, length
  4. Apply comprehensive validation patterns
  5. Cluster heading levels using K-Means
  6. Construct synthetic TOC
- **Success Rate:** ~90% of reports
- **Quality:** Good, but may miss complex nested structures

#### Enhanced Implementation (IntelligentTOCService - Optional)

**Layer 1: PDF Bookmarks (with Quality Scoring)**
- Same as above, but with additional quality metrics
- Penalizes file-assembly artifacts ("01 Cover", "05 Final_Report")
- Rewards CAG-specific patterns ("Chapter I", "Annexure")

**Layer 2: TOC Table Parser**
- **Source:** Parses printed Table of Contents from pages 3-10
- **Method:** Pattern matching on text/table content
- **Patterns Matched:**
  - "Chapter I Introduction 1"
  - "1.1 Background 5"
  - "Annexure I (Refer Para 2.1) 45"
  - Dot leaders: "Executive Summary.......iii"
- **Success Rate:** ~60% when embedded TOC is poor

**Layer 3: Heuristic Detection**
- Same as ScaffoldingService Layer 2

**Layer 4: Hierarchy Enrichment**
- **Triggers:** Flat TOC (few parents or high child concentration)
- **Method:** Detect numbered sub-sections within chapters
- **Creates:** New parent chunks for detected sections

---

## Phase 4: Scaffolding Service

**File:** `src/parsing_pipeline/modules/scaffolding_service.py`

### Purpose

Builds the initial document scaffold with TOC and page mappings. This is **Phase 4** in the 10-phase pipeline.

### Core Logic Flow

```python
def build_scaffold(task: DocumentTask) -> DocumentTask:
    """
    1. Extract embedded TOC (PDF bookmarks)
    2. Validate embedded TOC quality
    3. If invalid: Generate heuristic TOC
    4. Build page number mappings (physical ↔ logical)
    5. Filter and deduplicate TOC entries
    6. Return scaffold with toc, page_map, heading_positions
    """
```

### Embedded TOC Extraction

**Method:** `_extract_embedded_toc()`

```python
def _extract_embedded_toc(task, doc):
    """
    Extract PDF bookmarks using PyMuPDF.

    Steps:
    1. Get TOC via doc.get_toc(simple=False)
    2. Validate against quality thresholds:
       - Minimum entries (5)
       - Multiple hierarchy levels (≥2)
       - Page coverage (≥10% of document)
    3. Clean titles (remove page numbers, dot leaders)
    4. Return cleaned TOC
    """
```

**Validation Logic:**

```python
def _validate_embedded_toc(toc, total_pages):
    """
    Quality gates for embedded TOC:

    1. Entry Count: len(toc) >= 5
    2. Hierarchy Depth: len(unique_levels) >= 2
    3. Page Coverage: covered_pages / total_pages >= 0.1

    Returns: True if all gates pass
    """
```

**Example:**
```python
# PASS: Good embedded TOC
toc = [
  [1, "Preface", 1],
  [1, "Executive Summary", 3],
  [1, "Chapter I Introduction", 10],
  [2, "1.1 Background", 12],
  [2, "1.2 Audit Scope", 15],
  [1, "Chapter II Findings", 20],
  # ... 15 more entries across 80% of pages
]
# ✅ 20 entries, 2 levels, 80% coverage → ACCEPTED

# FAIL: Sparse bookmarks
toc = [
  [1, "Preface", 1],
  [1, "Executive Summary", 3],
  [1, "Annexure", 95]
]
# ❌ 3 entries, 1 level, 3% coverage → REJECTED
```

### Heuristic TOC Generation

**Method:** `_generate_heuristic_toc()`

**5-Phase Algorithm:**

```python
def _generate_heuristic_toc(doc, report_id):
    """
    Phase 1: Extract Text Blocks
    - Parse PDF with PyMuPDF (get_text("dict"))
    - Extract font name, size, flags, position for each block
    - Returns: List[TextBlock]

    Phase 2: Statistical Style Profiling
    - Calculate body font baseline (80th percentile)
    - Identify common font families
    - Detect common formatting flags
    - Returns: StyleProfile

    Phase 3: Heading Detection with Validation
    - Score blocks using multi-factor analysis
    - Apply comprehensive validation patterns
    - Log rejections for monitoring
    - Returns: List[TextBlock] (heading candidates)

    Phase 4: Intelligent Hierarchy Inference
    - Cluster heading font sizes using K-Means
    - Map clusters to hierarchy levels
    - Returns: Dict[TextBlock, level]

    Phase 5: Synthetic TOC Construction
    - Sort candidates by page and position
    - Build TOC entries
    - Capture Y-coordinates for later use
    - Returns: (toc_entries, heading_positions)
    """
```

#### Phase 1: Text Block Extraction

```python
def _extract_text_blocks(doc, max_pages=100):
    """
    Extract rich text blocks with metadata.

    For each page (up to max_pages):
      For each text block:
        Extract:
        - bbox: (x0, y0, x1, y1)
        - text: cleaned content
        - font_name, font_size, font_flags
        - position: (x, y)
        - word_count, char_count

    Returns: List[TextBlock]
    """
```

#### Phase 2: Style Profiling

```python
def _build_style_profile(text_blocks):
    """
    Build statistical profile of document typography.

    1. Collect all font sizes
    2. Remove outliers using IQR (Interquartile Range)
    3. Calculate body baseline (80th percentile)
       → Text below this threshold is body text
       → Text above this threshold is likely a heading
    4. Identify top 3 font families
    5. Identify common formatting flags

    Returns: StyleProfile {
      body_font_size_baseline: 12.0,
      body_font_families: ["Times-Roman", "Arial"],
      body_text_flags: {0, 16},  # Normal, Bold
      page_stats: {width: 595, height: 842, ...}
    }
    """
```

#### Phase 3: Heading Detection with Validation

**Multi-Factor Scoring:**

```python
def _calculate_heading_score(block, style_profile):
    """
    Composite score (0-200 points):

    Factor 1: Font Size Deviation (0-100 pts)
    - size_ratio = block.font_size / baseline
    - if size_ratio >= 1.4: score += min(100, (ratio - 1.0) * 50)

    Factor 2: Font Style Change (0-25 pts)
    - if bold and not common_bold: score += 20

    Factor 3: Position Analysis (0-50 pts)
    - Left-aligned: +30 pts
    - Center-aligned: +10 pts

    Factor 4: Text Characteristics (0-25 pts)
    - Length >= 10 chars: +15 pts
    - Word count <= 15: +10 pts

    Threshold: 75 points required to be a candidate
    """
```

**Validation Patterns:**

The system uses **two-tier pattern matching** to filter false positives:

**REJECT Patterns** (77 patterns across 2 phases):
```python
TOC_REJECT_PATTERNS = [
    # Phase 1: Basic rejections
    r"^Report No\.?\s+\d+",        # Page headers
    r"^Table\s+\d+[\.:]\s",        # Table captions
    r"^Figure\s+\d+[\.:]\s",       # Figure captions
    r"^\(₹",                        # Currency units
    r"^Total\s+[\d,\.]+",          # Data rows

    # Phase 2: OCR table content (NEW)
    r".*\|.*\|",                    # Pipe characters (table cells)
    r"[\d,]{4,}\s+[\d,]{4,}",      # Multiple comma-formatted numbers
    r"\d{4}[-–]\d{2,4}\s+\d{3,}",  # Year-number patterns
    r"[\u0900-\u097F]{3,}",        # Devanagari script (Hindi OCR)
]
```

**ACCEPT Patterns** (38 high-confidence patterns):
```python
TOC_ACCEPT_PATTERNS = [
    # Chapter patterns
    r"^Chapter\s+[IVX\d]+[:\s]",

    # Section patterns
    r"^\d+\.\d+(\.\d+)?\s+[A-Z]",

    # Common front matter (EXACT MATCH)
    r"^Preface$",
    r"^Executive\s+Summary$",
    r"^Introduction$",

    # CAG-specific
    r"^Audit\s+Objectives?$",
    r"^Key\s+Audit\s+Findings$",

    # Lettered sections
    r"^[A-Z]\.\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*$",  # "A. Karnataka"
]
```

**Structural Checks (executed BEFORE pattern matching):**
```python
def _is_valid_toc_entry(text, page_num, seen_entries):
    """
    Pre-pattern structural validation:

    1. Pipe Character Check:
       - if count("|") >= 2: REJECT (table cell)

    2. Number Density Check:
       - if number_groups >= 5: REJECT (data row)

    3. Comma-Formatted Numbers:
       - if comma_numbers >= 2: REJECT (financial data)

    4. Year-Data Pattern:
       - if "YYYY-YY 123": REJECT (annual data)

    5. Devanagari Script:
       - if 3+ consecutive Devanagari chars: REJECT (OCR artifact)

    6. Number/Word Ratio:
       - if numbers > words AND numbers >= 3: REJECT (table)

    THEN check ACCEPT patterns
    THEN check REJECT patterns
    THEN check duplicates

    Returns: (is_valid, rejection_reason, matched_pattern)
    """
```

**Rejection Logging:**

All rejections are logged to `logs/rejected_toc.log` for monitoring:

```python
class TOCRejectionLogger:
    """
    Logs rejected TOC candidates for quality monitoring.

    Features:
    - Writes all rejections with reason and pattern
    - Calculates rejection rate per report
    - Alerts if rejection rate > 25%

    Purpose: Ensure legitimate chapter headings aren't filtered
    """
```

#### Phase 4: Hierarchy Inference

```python
def _infer_hierarchy(heading_candidates):
    """
    Cluster headings by font size to infer hierarchy levels.

    1. Extract font sizes from candidates
    2. Determine optimal K (2-5 clusters) using silhouette score
    3. Run K-Means clustering
    4. Map clusters to levels (largest font = level 1)

    Returns: Dict[TextBlock, level]

    Example:
      Cluster 1 (18pt): Level 1 (Chapters)
      Cluster 2 (14pt): Level 2 (Sections)
      Cluster 3 (12pt): Level 3 (Subsections)
    """
```

#### Phase 5: TOC Construction

```python
def _construct_toc(heading_candidates, hierarchy_map):
    """
    Build final TOC with Y-coordinates.

    1. Sort candidates by (page, y_position)
    2. For each candidate:
       - Extract level from hierarchy_map
       - Clean title (remove page numbers, dots)
       - Get page_physical
       - Capture bbox Y-coordinate
       - Create [level, title, page] entry
       - Store Y-position in heading_positions dict

    Returns: (toc_entries, heading_positions)

    heading_positions format:
    {
      "1_Chapter I": 72.5,   # Y-coordinate on page 1
      "5_1.1 Background": 120.3,
    }

    Purpose: Y-coordinates used in chunking for accurate
             parent assignment when multiple sections on same page
    """
```

### Title Cleaning

```python
def _clean_toc_title(text):
    """
    Clean and normalize TOC titles.

    Handles:
    1. Trailing page numbers: "Chapter IV 77-99" → "Chapter IV"
    2. Dot leaders: "Introduction......" → "Introduction"
    3. Hyphenation artifacts
    4. Excessive whitespace
    5. Trailing punctuation

    Returns: Cleaned title string
    """
```

### Page Mappings

```python
def _build_page_mappings(task, doc):
    """
    Build physical → logical page number mappings.

    For each page in PDF:
      Extract page label (if present)
      Map: physical_page_num → logical_label

    Example:
    {
      0: "i",      # Front matter (Roman numerals)
      1: "ii",
      2: "iii",
      10: "1",     # Main content (Arabic numerals)
      11: "2",
      95: "A-1",   # Annexure
    }
    """
```

---

## Intelligent TOC Service

**File:** `src/parsing_pipeline/modules/intelligent_toc_service.py`

**Status:** Optional enhanced layer (not currently in main pipeline)

### Purpose

Multi-layer TOC extraction with quality scoring and orchestration.

### Architecture

```python
class IntelligentTOCService:
    """
    Orchestrates 4-layer TOC extraction:

    Layer 1: PDF Bookmarks (with quality scoring)
    Layer 2: TOC Table Parser (parse printed TOC)
    Layer 3: Heuristic Detection
    Layer 4: Hierarchy Enrichment
    """
```

### Layer 1: Enhanced Bookmark Extraction

```python
def _extract_bookmarks(doc, total_pages, report_id):
    """
    Extract and score PDF bookmarks.

    Quality Scoring:
    1. Base metrics (TOCQualityMetrics)
    2. Apply penalties for file-assembly patterns
    3. Apply bonuses for CAG-specific patterns
    4. Calculate confidence score

    Assembly Patterns (penalized):
    - "01 Cover", "05 Final_Report"
    - "Part 1", "Section 1" (no context)

    CAG Patterns (rewarded):
    - "Chapter I"
    - "Annexure"
    - "Executive Summary"
    - "Audit Objective"

    Returns: (toc, TOCQualityMetrics)
    """
```

### Layer 2: TOC Table Parser

```python
def _extract_toc_table(child_chunks, total_pages, report_id):
    """
    Parse printed Table of Contents from document content.

    Process:
    1. Filter chunks from pages 0-15
    2. Find "Table of Contents" header
    3. Parse entries using TOCTableParser
    4. Calculate confidence score
    5. Compare with bookmark quality

    Returns: (toc, TOCQualityMetrics)
    """
```

### Quality Metrics

```python
@dataclass
class TOCQualityMetrics:
    """
    Quality metrics for TOC extraction.

    Fields:
    - source: "bookmarks" | "toc_table" | "heuristic"
    - entry_count: Number of entries
    - level_count: Unique hierarchy levels
    - has_chapters: Boolean
    - has_sections: Boolean (numbered sections)
    - page_coverage: 0.0-1.0
    - confidence: 0.0-1.0

    Scoring Function (0-100):
    - Entry count: min(30, entry_count * 2)
    - Level depth: min(25, level_count * 8)
    - Has chapters: 15 points
    - Has sections: 15 points
    - Page coverage: coverage * 15

    Final Score = score * confidence
    """
```

### Layer Selection Logic

```python
def extract_toc(pdf_path, child_chunks, report_id):
    """
    Select best TOC using cascading strategy.

    1. Try Layer 1 (Bookmarks)
       if score >= 60: return bookmarks

    2. Try Layer 2 (TOC Table)
       if score > bookmarks_score: return toc_table

    3. Fall back to Layer 1 (if exists)

    4. Return empty TOC (triggers heuristic in scaffolding)

    Returns: (toc, metrics)
    """
```

---

## TOC Table Parser

**File:** `src/parsing_pipeline/modules/toc_table_parser.py`

### Purpose

Parses the **printed Table of Contents** (usually on pages 3-10) rather than relying on PDF bookmarks.

### Supported TOC Formats

CAG reports typically have these formats:

```
Chapter I Introduction.......1
1.1 Background 5
1.2 Audit Scope 8
Annexure I (Refer Para 2.1) 45
```

### Entry Patterns

**11 pattern types** matched (in order of specificity):

```python
TOC_ENTRY_PATTERNS = [
    # 1. Chapter with Roman numeral
    (r"^(Chapter[\s\-]+[IVX]+)[:\s\-]+(.+?)\s+(\d+)$", 1),

    # 2. Chapter with Arabic numeral
    (r"^(Chapter[\s\-]+\d+)[:\s\-]+(.+?)\s+(\d+)$", 1),

    # 3. Numbered section 3 levels
    (r"^(\d+\.\d+\.\d+)\s+(.+?)\s+(\d+)$", 3),

    # 4. Numbered section 2 levels
    (r"^(\d+\.\d+)\s+(.+?)\s+(\d+)$", 2),

    # 5. Single number section
    (r"^(\d+)\s+([A-Z][a-z].+?)\s+(\d+)$", 1),

    # 6. Annexure
    (r"^(Annexure[\s\-]+[IVX\d\-A-Z]+)\s*(\([^)]+\))?\s*(.*)?\s+(\d+)$", 1),

    # 7. Appendix
    (r"^(Appendix[\s\-]+[A-Z\d]+)\s*(.*)?\s+(\d+)$", 1),

    # 8. Lettered sections
    (r"^([A-Z])\.\s+(.+?)\s+(\d+)$", 2),

    # 9. Standard sections
    (r"^(Executive\s+Summary|Preface|...) ([ivx]+|\d+)$", 1),

    # 10. Entry with dot leader
    (r"^(.+?)\.{3,}\s*(\d+|[ivx]+)$", 1),

    # 11. Simple entry with page
    (r"^([A-Z][a-z][^0-9]{5,}?)\s+(\d+|[ivx]+)$", 1),
]
```

### Parsing Process

```python
def parse_from_chunks(child_chunks, report_id):
    """
    Extract TOC from content chunks.

    Step 1: Filter TOC Page Chunks (pages 0-15)
    - Extract chunks from likely TOC pages
    - Sort by page and Y-position

    Step 2: Find TOC Header
    - Look for "Contents", "Table of Contents", "Index"
    - Start parsing after header (or from beginning)

    Step 3: Parse Entries
    - For each chunk in range:
      - Skip if too short
      - Check for TOC end markers
      - Try pattern matching
      - Build TOCEntry objects

    Step 4: Calculate Confidence
    - Base: 0.5 if min_entries met
    - +0.2 if multiple levels
    - +0.2 if sequential page numbers
    - +0.1 if has chapters

    Returns: (List[TOCEntry], confidence)
    """
```

### Confidence Calculation

```python
def _calculate_confidence(entries, chunks):
    """
    Score: 0.0 - 1.0

    Base: 0.5 (for having entries)

    Bonuses:
    - Multiple levels: +0.2
    - Sequential pages: +0.2 * (sequential_rate)
    - Has chapters: +0.1

    Max: 1.0
    """
```

### Roman Numeral Handling

```python
def _parse_page_number(page_str):
    """
    Convert Roman/Arabic numerals to integers.

    Examples:
    - "iii" → 3
    - "xii" → 12
    - "15" → 15

    Algorithm for Roman numerals:
    - Traverse right to left
    - If current value < previous: subtract
    - Else: add
    """
```

---

## Hierarchy Enricher

**File:** `src/parsing_pipeline/modules/hierarchy_enricher.py`

**Status:** ✅ Integrated in Phase 7.5 (after chunking, before assembly)

### Purpose

Creates **deeper parent-child hierarchy** by detecting numbered sub-sections within flat TOC structures.

### Problem Statement

Many CAG reports have sparse TOC:

```
❌ BEFORE ENRICHMENT:
Chapter I Introduction (contains 500 paragraphs)
Chapter II Findings (contains 800 paragraphs)
Chapter III Recommendations (contains 200 paragraphs)

Result: Poor retrieval precision (too much content per parent)
```

**After enrichment:**

```
✅ AFTER ENRICHMENT:
Chapter I Introduction
  └─ 1.1 Background
  └─ 1.2 Audit Objectives
  └─ 1.3 Audit Scope
Chapter II Findings
  └─ 2.1 Financial Irregularities
      └─ 2.1.1 Irregular Expenditure
      └─ 2.1.2 Unauthorized Payments
  └─ 2.2 Procurement Issues
Chapter III Recommendations
  └─ (i) Strengthen internal controls
  └─ (ii) Improve monitoring

Result: Better retrieval precision (30-50 paragraphs per parent)
```

### Triggering Conditions

```python
def should_enrich_hierarchy(parent_chunks, child_chunks):
    """
    Enrichment triggered when:

    Condition 1: Few parents (< 10)
    Condition 2: Flat hierarchy (< 30% of children have level_2+)
    Condition 3: High concentration (> 40% children to one parent)

    Returns: (needs_enrichment: bool, reason: str)
    """
```

### Detection Patterns

**5 Hierarchy Levels Supported:**

```python
SECTION_PATTERNS = {
    # Level 1: Major document sections
    1: [
        r"^(Preface)$",
        r"^(Executive\s+Summary)$",
        r"^(Chapter)\s+([IVX]+)\b",
        r"^(Chapter)\s+(\d+)\b",
    ],

    # Level 2: Main sections within chapter
    2: [
        r"^(\d+\.\d+)\.?\s+([A-Z].{5,})$",  # "1.1 Introduction"
        r"^([A-Z])\.\s+([A-Z][a-z]+)$",      # "A. Karnataka"
        r"^([a-z])\.\s+([A-Z].{3,})$",       # "a. Irregularities" (Direct Taxes)
    ],

    # Level 3: Sub-sections
    3: [
        r"^(\d+\.\d+\.\d+)\.?\s+([A-Z].{3,})$",  # "1.1.1 Background"
        r"^\(([ivx]+)\)\s+([A-Z].{5,})$",         # "(i) Finding"
        r"^([ivx]+)\.\s+([a-z].{5,})$",           # "i. whether all"
    ],

    # Level 4: Detail points
    4: [
        r"^(\d+\.\d+\.\d+\.\d+)\.?\s+(.{5,})$",  # "1.1.1.1 Detail"
        r"^[•●○]\s+(.{10,})$",                    # "• Finding detail"
    ],

    # Level 5: Deep detail (rare)
    5: [
        r"^(\d+\.\d+\.\d+\.\d+\.\d+)\.?\s+(.{3,})$",
    ],
}
```

### Enrichment Process

```python
def enrich_hierarchy(parent_chunks, child_chunks, report_id, aggressive=False):
    """
    Main enrichment algorithm.

    Step 1: Check Trigger Conditions
    - Is hierarchy severely flat (≤3 parents)?
    - Or aggressive mode requested?

    Step 2: Process Each Parent
    - Get children in parent's page range
    - Check parent concentration (>30% of all children?)
    - Detect sections using pattern matching
    - Create new parent chunks for detected sections

    Step 3: Assign Children to Sections
    - For each child:
      - Find nearest section (by page + Y-position)
      - Update parent_chunk_id
      - Inherit hierarchy from new parent

    Step 4: Combine Parent Lists
    - Original parents + new sub-parents

    Step 5: Post-Process Sync
    - Ensure all children have matching hierarchy
    - Fix any timing mismatches

    Returns: (enriched_parents, updated_children)
    """
```

### Section Detection Logic

```python
def _detect_sections(chunks, parent, report_id, aggressive=False):
    """
    Scan child chunks for section headers.

    For each chunk:
      1. Check content length
      2. Check if content_type is header OR matches header pattern
      3. In aggressive mode: also check first line of paragraphs
      4. Try pattern matching at each level (1-5)
      5. Build DetectedSection objects

    Returns: List[DetectedSection]

    DetectedSection:
    - section_id: "1.1", "i", "A"
    - title: Full title
    - level: Hierarchy level (1-5)
    - page_physical, page_logical
    - bbox: For Y-position sorting
    - confidence: 1.0
    """
```

### Parent Chunk Creation

```python
def _create_sub_parent(section, parent, report_id):
    """
    Create a new parent chunk for detected section.

    1. Generate unique chunk_id:
       - Format: {report_id}_parent_L{level}_{section_id}_{hash}

    2. Build hierarchy:
       - Inherit levels ABOVE this section's level from mega-parent
       - Add this section at its level
       - Example: Parent has {level_1: "Chapter I"}
                  Section is level 2 "1.1 Background"
                  → {level_1: "Chapter I", level_2: "1.1 Background"}

    3. Set page range to section's page (will extend later)

    Returns: ParentChunk dict
    """
```

### Child Reassignment

```python
def _assign_children_to_sections(children, sections, fallback_parent_id):
    """
    Assign each child to its nearest section.

    Algorithm:
    1. Sort sections by (page, Y-position)
    2. For each child:
       - Get child page and Y-position
       - Scan sections in order:
         - If section.page < child.page: candidate
         - If section.page == child.page AND section.y <= child.y: candidate
       - Assign to last valid candidate

    Returns: Dict[child_id, new_parent_id]
    """
```

### Example Transformation

**Input:**
```python
parent_chunks = [
  {chunk_id: "2023_07_parent_1_ChapterI", toc_level: 1, toc_entry: "Chapter I Introduction"}
]

child_chunks = [
  {chunk_id: "child_001", content: "1.1 Background\n\nThe audit was..."},
  {chunk_id: "child_002", content: "This scheme was launched..."},
  {chunk_id: "child_003", content: "1.2 Audit Scope\n\nThe audit covered..."},
  # ... 47 more children
]
```

**Output:**
```python
enriched_parents = [
  {chunk_id: "2023_07_parent_1_ChapterI", toc_level: 1, toc_entry: "Chapter I Introduction"},
  {chunk_id: "2023_07_parent_L2_1_1_abc123", toc_level: 2, toc_entry: "1.1 Background",
   hierarchy: {level_1: "Chapter I Introduction", level_2: "1.1 Background"}},
  {chunk_id: "2023_07_parent_L2_1_2_def456", toc_level: 2, toc_entry: "1.2 Audit Scope",
   hierarchy: {level_1: "Chapter I Introduction", level_2: "1.2 Audit Scope"}},
]

updated_children = [
  {chunk_id: "child_001", parent_chunk_id: "2023_07_parent_L2_1_1_abc123",
   hierarchy: {level_1: "Chapter I Introduction", level_2: "1.1 Background"}},
  {chunk_id: "child_002", parent_chunk_id: "2023_07_parent_L2_1_1_abc123",
   hierarchy: {level_1: "Chapter I Introduction", level_2: "1.1 Background"}},
  {chunk_id: "child_003", parent_chunk_id: "2023_07_parent_L2_1_2_def456",
   hierarchy: {level_1: "Chapter I Introduction", level_2: "1.2 Audit Scope"}},
]
```

---

## Integration: Chunking Service

**File:** `src/parsing_pipeline/modules/chunking_service.py`

**Phase:** 7 in the pipeline

### Purpose

Creates parent-child chunk hierarchy using the TOC from scaffolding.

### Parent Chunk Creation

```python
def _create_parent_chunks_from_toc(task, toc, page_map):
    """
    Convert TOC entries to ParentChunk objects.

    For each TOC entry:
      1. Extract: level, title, page_physical
      2. Calculate page range:
         - Start: entry's page
         - End: Look forward to next entry at same/higher level
         - Handle overlapping sections (multiple sections on same page)
         - Use Y-coordinates for disambiguation
      3. Build hierarchy dict:
         - Walk backwards through TOC to find ancestors
         - Create: {level_1: "Chapter", level_2: "Section", ...}
      4. Create ParentChunk with:
         - chunk_id (unique hash)
         - page_range_physical, page_range_logical
         - hierarchy
         - start_y_position (for multi-section pages)

    Returns: List[ParentChunk]
    """
```

**Page Range Calculation (Forward-Looking):**

```python
# For each TOC entry at index i:
start_page = toc[i].page
end_page = max_page  # Default: to end of document

# Look forward for next entry at same or higher level
for j in range(i+1, len(toc)):
    if toc[j].level <= level:
        # Found next sibling or parent section

        # Check if Y-coordinates available
        if has_y_coords:
            # Allow overlap, Y-coords will disambiguate
            end_page = toc[j].page
        else:
            # No Y-coords, end before next section
            end_page = max(start_page, toc[j].page - 1)
        break

# Ensure end >= start (critical fix)
if end_page < start_page:
    end_page = start_page
```

**Hierarchy Building:**

```python
def _build_hierarchy_for_parent(toc, index):
    """
    Build full ancestor chain for TOC entry.

    Algorithm:
      1. Get current entry: (level, title, page)
      2. Walk backwards through TOC (index-1 to 0)
      3. For each previous entry:
         - If entry.level < current_level:
           - Add to hierarchy: {level_X: entry.title}
           - Update current_level
      4. Add self at own level

    Returns: {level_1: "...", level_2: "...", level_3: "..."}

    Example:
      TOC:
      [1, "Chapter I", 10]
      [2, "1.1 Background", 12]
      [3, "1.1.1 Context", 14]  ← Building for this

      Result:
      {
        level_1: "Chapter I",
        level_2: "1.1 Background",
        level_3: "1.1.1 Context"
      }
    """
```

### Child Chunk Creation

```python
def _create_child_chunks(task, parent_chunks):
    """
    Convert ExtractedContent to ChildChunks with parent links.

    Step 1: Build Page-Parent Index
    - For each parent chunk:
      - For each page in parent's range:
        - Add parent to page_index[page]
    - Result: Fast lookup of all parents for a given page

    Step 2: Create Child Chunks
    - For each extracted_content:
      - Find best parent using page and Y-coordinate
      - Inherit full hierarchy from parent
      - Create ChildChunk with:
        - chunk_id (unique)
        - parent_chunk_id
        - content_type, content
        - source_page_physical, source_page_logical
        - source_bbox
        - hierarchy (inherited)
        - structured_data (for tables)

    Returns: List[ChildChunk]
    """
```

**Best Parent Selection (Y-Coordinate Aware):**

```python
def _find_best_parent_for_page(page, parent_chunks, page_index, content_bbox):
    """
    Find the MOST SPECIFIC parent for a child on given page.

    Algorithm:
      1. Get all parents containing this page
      2. If no parents: return None (fallback to first parent)
      3. If one parent: return it
      4. If multiple parents (overlapping sections):
         - Check if Y-coordinates available
         - Filter to parents whose start_y <= content_y
         - Return deepest level (most specific)

    Example:
      Page 12 has two sections:
      - Parent A: Chapter I (level 1, y=50)
      - Parent B: 1.1 Background (level 2, y=150)

      Child at y=200:
      → Both A and B contain page 12
      → Both have y <= 200
      → B is level 2 (deeper than A's level 1)
      → Return Parent B ✅
    """
```

---

## Integration: Assembly Service

**File:** `src/parsing_pipeline/modules/assembly_service.py`

**Phase:** 8 in the pipeline

### TOC in Final Output

The assembly service serializes parent and child chunks to JSON with full hierarchy metadata:

```json
{
  "report_metadata": {
    "report_id": "2023_07_...",
    "report_title": "...",
    "report_year": 2023
  },
  "parent_chunks": [
    {
      "chunk_id": "2023_07_parent_1_ChapterI",
      "report_id": "2023_07_...",
      "hierarchy": {
        "level_1": "Chapter I Introduction"
      },
      "page_range_physical": [10, 25],
      "page_range_logical": ["1", "16"],
      "toc_entry": "Chapter I Introduction",
      "toc_level": 1,
      "start_y_position": 72.5
    },
    {
      "chunk_id": "2023_07_parent_2_1_1",
      "hierarchy": {
        "level_1": "Chapter I Introduction",
        "level_2": "1.1 Background"
      },
      "page_range_physical": [12, 14],
      "toc_entry": "1.1 Background",
      "toc_level": 2
    }
  ],
  "child_chunks": [
    {
      "chunk_id": "2023_07_child_p012_para_001",
      "parent_chunk_id": "2023_07_parent_2_1_1",
      "content_type": "paragraph",
      "content": "The scheme was launched...",
      "hierarchy": {
        "level_1": "Chapter I Introduction",
        "level_2": "1.1 Background"
      },
      "source_page_physical": 12,
      "source_page_logical": "3"
    }
  ],
  "visual_asset_registry": {
    "tables_by_section": {...},
    "figures_by_section": {...}
  }
}
```

### Visual Asset Registry

**Phase 4.5 Enhancement:**

```python
def _build_visual_asset_registry(child_chunks, parent_chunks):
    """
    Build navigable index of tables and figures by TOC section.

    For each child chunk:
      if content_type == "table" or "figure":
        - Get parent_chunk_id
        - Look up parent's hierarchy
        - Add to registry under hierarchy path

    Returns:
    {
      "total_tables": 45,
      "total_figures": 23,
      "tables_by_section": {
        "Chapter I": {
          "1.1 Background": [
            {chunk_id: "...", page: 12, title: "Table 1.1: ..."}
          ]
        }
      },
      "figures_by_section": {...}
    }

    Purpose: Frontend can show "Tables in this section" dropdown
    """
```

---

## TOC Quality Metrics

### Embedded TOC Validation

**Thresholds:**
- Minimum entries: 5
- Minimum hierarchy levels: 2
- Minimum page coverage: 10%

**Example Quality Assessment:**

```python
# Report A: Good embedded TOC
toc_entries = 42
unique_levels = 3
page_coverage = 0.85
verdict = "ACCEPTED"

# Report B: Poor embedded TOC
toc_entries = 3
unique_levels = 1
page_coverage = 0.03
verdict = "REJECTED → Heuristic TOC"
```

### Heuristic TOC Rejection Monitoring

**Rejection Logging:**
- Location: `logs/rejected_toc.log`
- Alert threshold: 25% rejection rate
- Purpose: Ensure legitimate headings aren't filtered

**Example Log Entry:**
```
2026-02-24 10:15:23 | REJECTED | Page  12 | reject_pattern_match    | Pattern: ^Table\s+\d+        | Text: Table 2.1: Financial Irregularities in Assessment
```

### Hierarchy Enrichment Metrics

**Trigger Metrics:**

```python
# Condition 1: Few parents
parent_count < 10

# Condition 2: Flat hierarchy
deep_children = children with len(hierarchy) > 1
deep_rate = deep_children / total_children
if deep_rate < 0.30: trigger

# Condition 3: High concentration
max_children_per_parent / total_children > 0.40
```

**Output Metrics:**

```
Hierarchy Enricher: Added 15 sub-sections, updated 450 child assignments
Distribution: 18/18 parents have children
Concentration: 15.2% to top parent (down from 62.3%)
Deep hierarchy: 87.5% of children have level_2+ (up from 8.3%)
```

---

## Code Reference Map

### Core TOC Files

| File | Phase | Purpose | Key Classes/Functions |
|------|-------|---------|----------------------|
| `scaffolding_service.py` | 4 | Core TOC building (embedded + heuristic) | `ScaffoldingService`, `_extract_embedded_toc()`, `_generate_heuristic_toc()`, `TOCRejectionLogger` |
| `intelligent_toc_service.py` | 4 (optional) | Multi-layer TOC orchestration | `IntelligentTOCService`, `TOCQualityMetrics`, `extract_toc()` |
| `toc_table_parser.py` | 4 (layer 2) | Parse printed TOC from content | `TOCTableParser`, `parse_from_chunks()`, `TOCEntry` |
| `hierarchy_enricher.py` | 7.5 | Detect sub-sections, create deep hierarchy | `HierarchyEnricher`, `enrich_hierarchy()`, `should_enrich_hierarchy()` |
| `chunking_service.py` | 7 | Create parent chunks from TOC | `ChunkingService`, `_create_parent_chunks_from_toc()`, `_find_best_parent_for_page()` |
| `assembly_service.py` | 8 | Serialize TOC hierarchy to JSON | `AssemblyService`, `_build_visual_asset_registry()` |
| `report_type_profiles.py` | 4 (detect) | Detect report type from TOC | `_detect_from_toc()` |
| `validation_service.py` | 9 | Validate TOC quality | `validate_report()` |

### Supporting Files

| File | Purpose |
|------|---------|
| `src/core/data_contracts.py` | `ParentChunk`, `ChildChunk`, `DocumentTask` contracts |
| `main.py` | Pipeline orchestration (calls scaffolding → chunking → enrichment) |
| `logs/rejected_toc.log` | Rejection monitoring log |

### Key Functions by Phase

**Phase 4: TOC Extraction**
```
scaffolding_service.py:
├─ build_scaffold()
├─ _extract_embedded_toc()
│  └─ _validate_embedded_toc()
├─ _generate_heuristic_toc()
│  ├─ _extract_text_blocks()
│  ├─ _build_style_profile()
│  ├─ _detect_headings()
│  │  ├─ _calculate_heading_score()
│  │  └─ _is_valid_toc_entry()
│  ├─ _infer_hierarchy()
│  └─ _construct_toc()
└─ _build_page_mappings()
```

**Phase 7: Parent Chunk Creation**
```
chunking_service.py:
├─ chunk_document()
├─ _create_parent_chunks_from_toc()
│  └─ _build_hierarchy_for_parent()
├─ _create_child_chunks()
│  ├─ _build_page_parent_index()
│  └─ _find_best_parent_for_page()
```

**Phase 7.5: Hierarchy Enrichment**
```
hierarchy_enricher.py:
├─ should_enrich_hierarchy()
├─ enrich_hierarchy()
│  ├─ _detect_sections()
│  ├─ _create_sub_parent()
│  └─ _assign_children_to_sections()
```

---

## Known Limitations & Future Work

### Current Limitations

1. **Heuristic TOC Quality**
   - May miss complex nested structures
   - Sensitive to unusual font choices
   - Can struggle with multi-column layouts

2. **TOC Table Parser**
   - Not yet integrated in main pipeline
   - Requires content chunks (chicken-egg problem)
   - Needs further testing on diverse report formats

3. **Y-Coordinate Dependency**
   - Heuristic TOC provides Y-coordinates
   - Embedded TOC does NOT (bookmarks have no position)
   - Multi-section pages may have ambiguous assignments with embedded TOC

4. **Hierarchy Enricher Patterns**
   - Covers common CAG patterns
   - May need expansion for specialized reports
   - Aggressive mode can be too aggressive

### Planned Improvements

1. **Integrate Intelligent TOC Service**
   - Replace scaffolding_service with intelligent_toc_service
   - Enable TOC table parsing as Layer 2
   - Add quality scoring to pipeline output

2. **Multi-Language TOC Support**
   - Add Hindi TOC parsing
   - Support bilingual TOC entries

3. **TOC Correction Service**
   - Machine learning model to fix TOC errors
   - User feedback loop for corrections

4. **Visual TOC Extraction**
   - OCR-based TOC extraction from page images
   - Handle TOC tables rendered as images

5. **Cross-Reference Resolution**
   - Link "Refer Para 2.1" to actual section
   - Build bidirectional reference graph

---

## Usage Examples

### Running the Pipeline

```bash
# Standard pipeline (Scaffolding Service)
python -m src.parsing_pipeline.main "Newtest.xlsx"

# Output includes TOC in scaffold
```

### Checking TOC Quality

```python
# After Phase 4 completes, check:
task.scaffold = {
  "toc": [[1, "Chapter I", 10], [2, "1.1 Background", 12], ...],
  "page_map": {0: "i", 10: "1", ...},
  "heading_positions": {"10_Chapter I": 72.5, ...}
}

# Count entries
toc_entry_count = len(task.scaffold["toc"])

# Check hierarchy depth
levels = set(entry[0] for entry in task.scaffold["toc"])
hierarchy_depth = len(levels)

# Check if enrichment needed
needs_enrichment, reason = should_enrich_hierarchy(
    task.parent_chunks,
    task.child_chunks
)
```

### Manual TOC Correction

If heuristic TOC has errors, you can manually edit the scaffold before chunking:

```python
# After scaffolding, before chunking:
task.scaffold["toc"] = [
  [1, "Preface", 1],
  [1, "Executive Summary", 3],
  [1, "Chapter I Introduction", 10],
  [2, "1.1 Background", 12],
  # ... corrected entries
]
```

---

## Conclusion

The TOC parsing subsystem is a **multi-layered, adaptive strategy** that ensures every CAG report gets a usable hierarchical structure, regardless of PDF quality. The combination of embedded TOC extraction, heuristic generation, table parsing, and hierarchy enrichment creates a robust foundation for the RAG pipeline's parent-child chunking strategy.

**Key Strengths:**
- ✅ Handles both high-quality and low-quality PDFs
- ✅ Comprehensive validation prevents false positives
- ✅ Y-coordinate awareness enables multi-section pages
- ✅ Hierarchy enrichment creates deep parent-child links
- ✅ Rejection logging ensures quality monitoring

**Key Metrics:**
- ~90% success rate for TOC extraction
- Average 20-30 parent chunks per report
- Average 60-80 child chunks per parent (before enrichment)
- Average 30-50 child chunks per parent (after enrichment)

The deeper and more accurate the TOC, the better the RAG retrieval quality and user auditability.

---

**End of Document**
