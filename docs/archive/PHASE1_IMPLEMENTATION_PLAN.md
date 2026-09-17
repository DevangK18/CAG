# CAG Pipeline Enhancement: Phase 1 Implementation Plan

## Foundation & Critical Fixes (P0 + P1)

**Version:** 1.0  
**Scope:** Algorithmic improvements, no LLM dependencies  
**Timeline:** 6-8 weeks  
**Prerequisites:** Existing parsing pipeline (Phases 1-9)

---

## Executive Summary

Phase 1 addresses critical RAG quality issues through purely algorithmic improvements. No LLM calls are required—all enhancements use regex patterns, heuristics, and data structure improvements.

### Tasks Overview

| Task | Priority | Effort | Description |
|------|----------|--------|-------------|
| **P0-1** | Critical | 2 weeks | Structured Table Extraction (Queryable JSON) |
| **P0-2** | Critical | 1 week | Hierarchy Concentration Fix (Y-Coordinate Awareness) |
| **P0-3** | Critical | 1 week | Multi-Page Table Stitching |
| **P1-1** | High | 1 week | Report Type Adaptation |
| **P1-2** | High | 1 week | Enhanced Semantic Patterns |
| **P1-3** | High | 2 weeks | Evidence Cross-Reference Linking |

### Expected Impact

| Metric | Current | After Phase 1 |
|--------|---------|---------------|
| Table Queryability | 0% | 100% |
| Hierarchy Concentration | 92.3% in single section | <15% max |
| Multi-page Table Handling | Fragmented | Unified |
| Compliance Report Findings | 0 | Extracted |
| Evidence Linking | None | Cross-referenced |

---

## Task P0-1: Structured Table Extraction

**Priority:** P0 (Critical)  
**Effort:** 2 weeks  
**Dependencies:** None

### Objective

Transform markdown tables into structured, queryable JSON that enables direct answering of questions like "What was expenditure in FY 2022-23?" without LLM re-parsing.

### Current Problem

```
Current: "| State | 2021-22 | 2022-23 |\n| Maharashtra | 847.71 | 923.45 |"
         ↓
         Stored as opaque markdown string
         ↓
         RAG retrieves, LLM must re-parse every time
```

### Solution Architecture

```
PDF Table → TATR → Tesseract → Markdown
                                  ↓
                    StructuredTableExtractor
                                  ↓
              StructuredTable (queryable JSON)
                    │
    ┌───────────────┼───────────────┐
    ↓               ↓               ↓
TableColumn    TableRow       TableCell
(classified)   (typed)        (parsed)
```

### Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `src/core/table_contracts.py` | **NEW** | Data models for structured tables |
| `src/core/data_contracts.py` | **MODIFY** | Add `structured_data` field |
| `src/parsing/extractors/table_extractor.py` | **MODIFY** | Integrate structured extraction |
| `src/parsing/services/structured_table_extractor.py` | **NEW** | Core extraction logic |

### Data Models

```python
# src/core/table_contracts.py

class CellDataType(str, Enum):
    TEXT = "text"
    INTEGER = "integer"
    DECIMAL = "decimal"
    CURRENCY = "currency"
    PERCENTAGE = "percentage"
    DATE = "date"
    YEAR = "year"
    FISCAL_YEAR = "fiscal_year"
    EMPTY = "empty"

class CellSemanticType(str, Enum):
    COLUMN_HEADER = "column_header"
    ROW_HEADER = "row_header"
    DATA = "data"
    TOTAL = "total"
    SUBTOTAL = "subtotal"

class TableCell(BaseModel):
    row_idx: int
    col_idx: int
    raw_text: str
    cleaned_text: str
    data_type: CellDataType
    semantic_type: CellSemanticType
    parsed_value: Optional[Union[str, int, float]]
    unit: Optional[str]  # "crore", "lakh", "%"
    normalized_value: Optional[float]  # Normalized to paise for currency

class TableColumn(BaseModel):
    col_idx: int
    header_text: str
    header_hierarchy: List[str]  # Multi-level headers
    column_type: str  # "entity", "time_period", "metric", "variance", "status"
    dominant_data_type: CellDataType

class TableRow(BaseModel):
    row_idx: int
    cells: List[TableCell]
    row_type: str  # "header", "data", "total", "subtotal"

class StructuredTable(BaseModel):
    table_id: str
    source_chunk_id: str
    source_page_physical: int
    source_bbox: List[float]
    
    # Structure
    columns: List[TableColumn]
    rows: List[TableRow]
    num_header_rows: int
    
    # Metadata
    title: Optional[str]
    monetary_unit: Optional[str]  # "₹ in crore"
    time_periods_covered: List[str]
    entities_covered: List[str]
    has_totals: bool
    
    # Original for backward compatibility
    markdown_representation: str
    
    # Helper methods
    def get_cell(self, row_idx: int, col_idx: int) -> Optional[TableCell]
    def get_column_values(self, col_idx: int) -> List[Any]
    def find_column_by_header(self, pattern: str) -> Optional[int]
    def sum_column(self, col_idx: int, exclude_totals: bool = True) -> float
```

### CAG-Specific Parsing Patterns

```python
# Indian currency patterns
CURRENCY_PATTERNS = [
    (r'^[₹`]?\s*([\d,]+(?:\.\d+)?)\s*$', None),
    (r'^[₹`]?\s*([\d,]+(?:\.\d+)?)\s*(crore|cr\.?)s?$', 'crore'),
    (r'^[₹`]?\s*([\d,]+(?:\.\d+)?)\s*(lakh|lac)s?$', 'lakh'),
]

# Fiscal year patterns
PERIOD_PATTERNS = [
    (r'^(\d{4})-(\d{2,4})$', 'fy_range'),      # 2021-22
    (r'^FY\s*(\d{4})-(\d{2,4})$', 'fy_explicit'), # FY 2021-22
]

# Total row indicators
TOTAL_INDICATORS = [
    r'^total$', r'^grand\s+total$', r'^sub[\-\s]?total$',
    r'^all\s+india$', r'^overall$', r'^aggregate$',
]

# Column classification keywords
ENTITY_KEYWORDS = ['state', 'ministry', 'department', 'scheme', 'name', 'particulars']
TIME_KEYWORDS = ['year', 'period', 'fy', 'quarter']
METRIC_KEYWORDS = ['amount', 'expenditure', 'receipt', 'budget', 'actual']
```

### Integration with data_contracts.py

```python
# Add to ExtractedContent
class ExtractedContent(BaseModel):
    # ... existing fields ...
    
    # P0-1 ADDITION
    structured_data: Optional[Dict[str, Any]] = Field(
        None,
        description="Structured representation for tables. Contains StructuredTable dict."
    )

# Add to ChildChunk  
class ChildChunk(BaseModel):
    # ... existing fields ...
    
    # P0-1 ADDITION
    structured_data: Optional[Dict[str, Any]] = Field(
        None,
        description="Structured representation inherited from ExtractedContent."
    )
```

### Testing Requirements

```python
def test_currency_parsing():
    """Test Indian currency formats."""
    assert parse_currency("₹847.71 crore") == {
        'value': 847.71, 'unit': 'crore', 'normalized': 8477100000000
    }
    assert parse_currency("(23.45)") == {
        'value': -23.45, 'unit': None, 'normalized': -2345
    }

def test_fiscal_year_detection():
    """Test FY column detection."""
    assert detect_period("2021-22") == {'type': 'fiscal_year', 'start': 2021, 'end': 2022}
    
def test_total_row_detection():
    """Test total row classification."""
    assert classify_row_type(["Total", "1234.56", "5678.90"]) == "total"
    assert classify_row_type(["All India", "100%", "200%"]) == "total"
```

---

## Task P0-2: Hierarchy Concentration Fix

**Priority:** P0 (Critical)  
**Effort:** 1 week  
**Dependencies:** None

### Objective

Fix the 92.3% concentration of child chunks in a single parent by using Y-coordinate awareness for accurate section assignment.

### Current Problem

```
Page 15 contains:
  - End of "3.1.2 Budget Allocation" (y: 0-200)
  - Start of "3.1.3 Implementation" (y: 200-800)

Current behavior: ALL content on page 15 → assigned to 3.1.2
Result: 92.3% of chunks in PMGSY report go to ONE section
```

### Solution

```
ScaffoldingService                  ChunkingService
      │                                   │
      ▼                                   ▼
_detect_headings_with_positions()    _find_best_parent_for_page(page, content_bbox)
      │                                   │
      ▼                                   │
scaffold['heading_positions'] ────────────┘
      │                                   │
      │     ┌─────────────────────────────┘
      ▼     ▼
ParentChunk.start_y_position ─► Y-aware assignment
```

### Files to Modify

| File | Changes |
|------|---------|
| `src/core/data_contracts.py` | Add `start_y_position` to ParentChunk |
| `src/parsing/services/scaffolding_service.py` | Capture heading Y-coordinates |
| `src/parsing/services/chunking_service.py` | Use Y-position in parent assignment |

### Implementation

**scaffolding_service.py changes:**

```python
def _detect_headings_with_positions(self, pdf_path: str) -> Tuple[List[Dict], Dict[str, float]]:
    """
    Detect headings AND capture their Y-positions.
    
    Returns:
        (heading_candidates, heading_positions)
        where heading_positions = {"page_title[:30]": y_coordinate}
    """
    candidates = []
    heading_positions = {}
    
    for page_num, page in enumerate(doc):
        blocks = page.get_text("dict")["blocks"]
        for block in blocks:
            if self._is_heading(block):
                title = block.get("text", "")[:30]
                y_pos = block["bbox"][1]  # y0 coordinate
                
                candidates.append({
                    "page": page_num,
                    "title": title,
                    "bbox": block["bbox"]
                })
                
                key = f"{page_num}_{title}"
                heading_positions[key] = y_pos
    
    return candidates, heading_positions

def process(self, task: DocumentTask) -> DocumentTask:
    # ... existing logic ...
    
    toc, heading_positions = self._generate_toc_with_positions(...)
    
    task.scaffold = {
        'toc': toc,
        'page_map': page_map,
        'heading_positions': heading_positions  # NEW
    }
    
    return task
```

**chunking_service.py changes:**

```python
def _find_best_parent_for_page(
    self,
    page_num: int,
    parents: List[ParentChunk],
    content_bbox: Optional[List[float]] = None  # NEW parameter
) -> Optional[ParentChunk]:
    """
    Find best parent using Y-position awareness.
    """
    candidates = [p for p in parents if p.page_range_physical[0] <= page_num <= p.page_range_physical[1]]
    
    if not candidates:
        return None
    
    if len(candidates) == 1:
        return candidates[0]
    
    # Multiple candidates - use Y-position
    content_y = content_bbox[1] if content_bbox else 0
    
    valid_parents = []
    for parent in candidates:
        parent_y = parent.start_y_position or 0
        
        # Content must be at or below section start
        if parent.page_range_physical[0] == page_num:
            if content_y >= parent_y - 10:  # 10px tolerance
                valid_parents.append(parent)
        else:
            # Content is on a later page of this section
            valid_parents.append(parent)
    
    if not valid_parents:
        valid_parents = candidates
    
    # Return deepest (most specific) section
    return max(valid_parents, key=lambda p: p.toc_level)
```

### Validation

```python
def test_hierarchy_concentration():
    """Ensure no section gets >50% of chunks."""
    result = process_report("pmgsy_report.pdf")
    
    parent_counts = Counter(c.parent_chunk_id for c in result.child_chunks)
    total = len(result.child_chunks)
    max_concentration = max(parent_counts.values()) / total
    
    assert max_concentration < 0.50, f"Concentration too high: {max_concentration:.1%}"
```

---

## Task P0-3: Multi-Page Table Stitching

**Priority:** P0 (Critical)  
**Effort:** 1 week  
**Dependencies:** P0-1 (Structured Table Extraction)

### Objective

Detect and merge tables that span multiple pages into unified structures.

### Detection Signals

| Signal | Weight | Example |
|--------|--------|---------|
| Continuation marker | High | "Contd.", "(continued)", "..." at end |
| Header repetition | High | Same headers on next page |
| Column structure match | Medium | Jaccard similarity > 0.8 |
| Missing totals | Medium | First fragment has no "Total" row |
| Position analysis | Low | Table at bottom → content at top of next |

### Implementation

```python
# src/parsing/services/multi_page_table_handler.py

class MultiPageTableHandler:
    """Detects and merges tables spanning multiple pages."""
    
    CONTINUATION_MARKERS = [
        r'\bcontd\.?\b', r'\bcontinued\b', r'\(contd\.\)', r'\.{3,}$'
    ]
    
    def detect_and_merge(
        self,
        tables: List[StructuredTable],
        page_sequence: List[int]
    ) -> List[StructuredTable]:
        """
        Detect table continuations and merge fragments.
        
        Returns:
            List of merged tables (fewer items than input if merges occurred)
        """
        if len(tables) < 2:
            return tables
        
        merged = []
        i = 0
        
        while i < len(tables):
            current = tables[i]
            
            # Look for continuation on next pages
            fragments = [current]
            j = i + 1
            
            while j < len(tables) and self._should_merge(fragments[-1], tables[j]):
                fragments.append(tables[j])
                j += 1
            
            if len(fragments) > 1:
                merged.append(self._merge_fragments(fragments))
            else:
                merged.append(current)
            
            i = j
        
        return merged
    
    def _should_merge(self, prev: StructuredTable, curr: StructuredTable) -> bool:
        """Determine if two tables should be merged."""
        # Must be consecutive pages
        if curr.source_page_physical != prev.source_page_physical + 1:
            return False
        
        # Check continuation markers
        if self._has_continuation_marker(prev):
            return True
        
        # Check column structure similarity
        if self._column_similarity(prev, curr) > 0.8:
            # Additional checks
            if not self._has_total_row(prev) or self._has_repeated_header(prev, curr):
                return True
        
        return False
    
    def _merge_fragments(self, fragments: List[StructuredTable]) -> StructuredTable:
        """Merge multiple table fragments into one."""
        base = fragments[0]
        
        all_rows = list(base.rows)
        all_pages = [base.source_page_physical]
        all_footnotes = list(base.footnotes)
        
        for fragment in fragments[1:]:
            # Skip repeated headers
            start_idx = fragment.num_header_rows if self._has_repeated_header(base, fragment) else 0
            all_rows.extend(fragment.rows[start_idx:])
            all_pages.append(fragment.source_page_physical)
            all_footnotes.extend(fragment.footnotes)
        
        return StructuredTable(
            table_id=f"{base.table_id}_merged",
            source_chunk_id=base.source_chunk_id,
            source_page_physical=base.source_page_physical,
            source_pages=all_pages,
            source_bbox=base.source_bbox,
            is_multi_page=True,
            columns=base.columns,
            rows=all_rows,
            num_rows=len(all_rows),
            num_cols=base.num_cols,
            num_header_rows=base.num_header_rows,
            title=base.title,
            monetary_unit=base.monetary_unit,
            footnotes=list(set(all_footnotes)),
            has_totals=any(r.row_type == 'total' for r in all_rows),
            markdown_representation=self._regenerate_markdown(all_rows, base.columns),
        )
```

---

## Task P1-1: Report Type Adaptation

**Priority:** P1 (High)  
**Effort:** 1 week  
**Dependencies:** None

### Objective

Adapt extraction patterns based on report type (Compliance, Performance, Financial, etc.).

### Report Type Profiles

```python
# src/parsing/services/report_type_profiles.py

REPORT_PROFILES = {
    "compliance": {
        "finding_patterns": [
            r"(?:audit|scrutiny)\s+(?:revealed|observed|noticed)",
            r"(?:non-?compliance|violation|deviation)",
            r"(?:contrary|violation)\s+(?:to|of)\s+(?:rules?|provisions?)",
        ],
        "section_markers": {
            "findings": ["audit findings", "observations", "results of audit"],
            "recommendations": ["recommendations", "suggested actions"],
        },
        "monetary_context": "irregular_expenditure",
        "evidence_weight": "high",
    },
    
    "performance": {
        "finding_patterns": [
            r"(?:shortfall|gap|deficiency)\s+(?:in|of)",
            r"(?:targets?|objectives?)\s+(?:not|were not)\s+(?:achieved|met)",
            r"(?:performance|outcome)\s+(?:below|under)",
        ],
        "section_markers": {
            "scope": ["audit scope", "coverage"],
            "criteria": ["audit criteria", "benchmarks"],
            "findings": ["audit findings", "observations"],
        },
        "monetary_context": "performance_shortfall",
        "evidence_weight": "medium",
    },
    
    "financial": {
        "finding_patterns": [
            r"(?:misstatement|error|discrepancy)",
            r"(?:understatement|overstatement)",
            r"(?:unreconciled|unexplained)\s+(?:differences?|balances?)",
        ],
        "section_markers": {
            "opinion": ["audit opinion", "auditor's report"],
            "notes": ["notes to accounts", "significant accounting"],
        },
        "monetary_context": "financial_irregularity",
        "evidence_weight": "high",
    },
}
```

### Detection Logic

```python
def detect_report_type(task: DocumentTask) -> str:
    """
    Detect report type from metadata and content signals.
    """
    # Check metadata first
    metadata = task.initial_metadata
    if "report_type" in metadata and metadata["report_type"]:
        return normalize_report_type(metadata["report_type"])
    
    # Analyze title
    title = metadata.get("report_title", "").lower()
    if "compliance" in title:
        return "compliance"
    if "performance" in title:
        return "performance"
    if "financial" in title or "accounts" in title:
        return "financial"
    
    # Analyze ToC structure
    toc_entries = [e.get("title", "").lower() for e in task.scaffold.get("toc", [])]
    
    compliance_signals = sum(1 for e in toc_entries if any(
        kw in e for kw in ["compliance", "irregularity", "audit observation"]
    ))
    performance_signals = sum(1 for e in toc_entries if any(
        kw in e for kw in ["performance", "outcome", "achievement", "target"]
    ))
    
    if compliance_signals > performance_signals:
        return "compliance"
    elif performance_signals > compliance_signals:
        return "performance"
    
    return "general"
```

---

## Task P1-2: Enhanced Semantic Patterns

**Priority:** P1 (High)  
**Effort:** 1 week  
**Dependencies:** P1-1 (Report Type Adaptation)

### Objective

Expand finding extraction patterns to capture implicit findings, especially for compliance audit reports that currently show 0 findings.

### Pattern Categories

```python
# src/parsing/services/semantic_patterns.py

class SemanticPatternMatcher:
    """Enhanced pattern matching for CAG report semantics."""
    
    # ═══════════════════════════════════════════════════════════════════════
    # EXPLICIT FINDING PATTERNS
    # ═══════════════════════════════════════════════════════════════════════
    
    EXPLICIT_PATTERNS = {
        "audit_revealed": [
            r"audit\s+(?:revealed|observed|noticed|found|disclosed)",
            r"(?:scrutiny|examination|review)\s+(?:revealed|showed|indicated)",
            r"(?:it\s+was|we)\s+(?:observed|noticed|found)\s+that",
        ],
        "non_compliance": [
            r"(?:non-?compliance|violation|deviation|departure)\s+(?:with|from|of)",
            r"contrary\s+to\s+(?:the\s+)?(?:provisions?|rules?|guidelines?)",
            r"in\s+(?:violation|contravention)\s+of",
        ],
        "loss_damage": [
            r"(?:loss|damage|wastage)\s+of\s+₹?\s*[\d.,]+\s*(?:crore|lakh)?",
            r"(?:avoidable|undue|extra)\s+(?:expenditure|payment|burden)",
            r"(?:resulted|led)\s+(?:in|to)\s+(?:loss|damage)",
        ],
    }
    
    # ═══════════════════════════════════════════════════════════════════════
    # IMPLICIT FINDING PATTERNS (for compliance reports with 0 findings)
    # ═══════════════════════════════════════════════════════════════════════
    
    IMPLICIT_PATTERNS = {
        "variance_issue": [
            r"(?:variance|difference|gap)\s+of\s+₹?\s*[\d.,]+",
            r"(?:shortfall|excess)\s+of\s+₹?\s*[\d.,]+",
            r"(?:actual|expenditure)\s+(?:was|were)\s+(?:higher|lower|less|more)",
        ],
        "target_miss": [
            r"(?:target|objective|goal)\s+(?:was|were)\s+not\s+(?:achieved|met|attained)",
            r"(?:achievement|progress)\s+(?:was|were)\s+(?:only|merely)\s+\d+%?",
            r"against\s+(?:the\s+)?target\s+of.*(?:only|merely)",
        ],
        "procedural_lapse": [
            r"(?:without|in\s+absence\s+of)\s+(?:proper|required|necessary)\s+(?:approval|sanction)",
            r"(?:records?|documents?)\s+(?:were|was)\s+not\s+(?:maintained|available|produced)",
            r"(?:no|lack\s+of)\s+(?:evidence|proof|documentation)",
        ],
        "pending_issue": [
            r"(?:pending|outstanding|overdue)\s+(?:since|for)\s+(?:more\s+than\s+)?\d+\s+(?:years?|months?)",
            r"(?:no\s+action|action\s+not)\s+taken\s+(?:till|as\s+of)\s+date",
            r"(?:remained|lying)\s+(?:unresolved|pending|unsettled)",
        ],
    }
```

### Confidence Scoring

```python
def calculate_finding_confidence(text: str, patterns_matched: List[str], report_type: str) -> float:
    """
    Calculate confidence score for a potential finding.
    
    Returns:
        Float between 0.0 and 1.0
    """
    score = 0.0
    
    # Pattern match scoring
    if "audit_revealed" in patterns_matched:
        score += 0.4  # Strong explicit signal
    if "non_compliance" in patterns_matched:
        score += 0.3
    if "loss_damage" in patterns_matched:
        score += 0.3
    
    # Monetary value present
    if re.search(r'₹\s*[\d.,]+\s*(?:crore|lakh)?', text):
        score += 0.2
    
    # Report type boost
    profile = REPORT_PROFILES.get(report_type, {})
    if profile.get("evidence_weight") == "high":
        score *= 1.2
    
    return min(score, 1.0)
```

---

## Task P1-3: Evidence Cross-Reference Linking

**Priority:** P1 (High)  
**Effort:** 2 weeks  
**Dependencies:** P0-1 (Structured Tables)

### Objective

Link findings to their supporting evidence (tables, paragraphs, annexures).

### Reference Patterns

```python
REFERENCE_PATTERNS = {
    "table_ref": [
        r"(?:as\s+(?:shown|given|detailed|indicated)\s+in\s+)?Table\s+(\d+(?:\.\d+)?)",
        r"(?:vide|see|refer)\s+Table\s+(\d+(?:\.\d+)?)",
        r"Annexure[\s-]?([A-Z]|\d+)",
    ],
    "para_ref": [
        r"(?:Para(?:graph)?|Para\.?)\s+(\d+(?:\.\d+)*)",
        r"(?:as\s+mentioned|discussed)\s+(?:in|at)\s+Para\.?\s+(\d+(?:\.\d+)*)",
    ],
    "page_ref": [
        r"(?:page|pg\.?)\s+(\d+)",
        r"\(p\.?\s*(\d+)\)",
    ],
}
```

### Evidence Link Model

```python
class EvidenceLink(BaseModel):
    """Links a finding to its supporting evidence."""
    link_id: str
    finding_id: str
    evidence_type: str  # "table", "paragraph", "annexure", "page"
    evidence_id: str    # Table ID, chunk ID, or page number
    reference_text: str # Original reference text found
    confidence: float
    
class EvidenceLinker:
    """Creates links between findings and evidence."""
    
    def link_finding_to_evidence(
        self,
        finding: Finding,
        tables: List[StructuredTable],
        chunks: List[ChildChunk]
    ) -> List[EvidenceLink]:
        """Extract references from finding and link to actual content."""
        links = []
        
        # Find table references
        for pattern in REFERENCE_PATTERNS["table_ref"]:
            for match in re.finditer(pattern, finding.text, re.IGNORECASE):
                table_num = match.group(1)
                linked_table = self._find_table_by_number(table_num, tables)
                if linked_table:
                    links.append(EvidenceLink(
                        link_id=f"link_{finding.finding_id}_{linked_table.table_id}",
                        finding_id=finding.finding_id,
                        evidence_type="table",
                        evidence_id=linked_table.table_id,
                        reference_text=match.group(0),
                        confidence=0.9
                    ))
        
        # Find paragraph references
        for pattern in REFERENCE_PATTERNS["para_ref"]:
            for match in re.finditer(pattern, finding.text, re.IGNORECASE):
                para_num = match.group(1)
                linked_chunk = self._find_chunk_by_para(para_num, chunks)
                if linked_chunk:
                    links.append(EvidenceLink(
                        link_id=f"link_{finding.finding_id}_{linked_chunk.chunk_id}",
                        finding_id=finding.finding_id,
                        evidence_type="paragraph",
                        evidence_id=linked_chunk.chunk_id,
                        reference_text=match.group(0),
                        confidence=0.85
                    ))
        
        return links
```

---

## Timeline & Dependencies

```
Week 1-2: P0-1 Structured Table Extraction
    ├── table_contracts.py (data models)
    ├── structured_table_extractor.py (core logic)
    ├── Update data_contracts.py
    └── Integration tests

Week 2-3: P0-2 Hierarchy Concentration Fix
    ├── scaffolding_service.py (Y-position capture)
    ├── chunking_service.py (Y-aware assignment)
    └── Concentration validation tests

Week 3-4: P0-3 Multi-Page Table Stitching
    ├── multi_page_table_handler.py
    ├── Integration with table_extractor.py
    └── Multi-page table tests

Week 4-5: P1-1 Report Type Adaptation
    ├── report_type_profiles.py
    ├── Integration with semantic_enrichment_service.py
    └── Profile validation tests

Week 5-6: P1-2 Enhanced Semantic Patterns
    ├── semantic_patterns.py (expanded patterns)
    ├── Confidence scoring
    └── Pattern coverage tests

Week 6-8: P1-3 Evidence Cross-Reference Linking
    ├── evidence_linker.py
    ├── Reference resolution logic
    └── End-to-end linking tests
```

### Dependency Graph

```
P0-1 (Structured Tables) ─────────────────┐
                                          ├───► P1-3 (Cross-References)
P0-2 (Hierarchy Fix) ─────────────────────┤
                                          │
P0-3 (Multi-Page) ────────────────────────┘
         │
         └───► (Depends on P0-1)

P1-1 (Report Type) ───► P1-2 (Enhanced Patterns)
```

---

## Success Metrics

| Metric | Target | Validation Method |
|--------|--------|-------------------|
| Table queryability | 100% of tables have structured_data | Unit tests |
| Max hierarchy concentration | <15% per section | Concentration test |
| Multi-page table detection | >90% recall | Manual validation on sample |
| Compliance report findings | >0 per report | Run on known compliance reports |
| Evidence link coverage | >70% of findings have links | Link coverage analysis |

---

## File Summary

### New Files

| File | Task | Description |
|------|------|-------------|
| `src/core/table_contracts.py` | P0-1 | Structured table data models |
| `src/parsing/services/structured_table_extractor.py` | P0-1 | Markdown → JSON extraction |
| `src/parsing/services/multi_page_table_handler.py` | P0-3 | Table fragment merging |
| `src/parsing/services/report_type_profiles.py` | P1-1 | Report type configurations |
| `src/parsing/services/semantic_patterns.py` | P1-2 | Enhanced finding patterns |
| `src/parsing/services/evidence_linker.py` | P1-3 | Finding-evidence linking |

### Modified Files

| File | Task | Changes |
|------|------|---------|
| `src/core/data_contracts.py` | P0-1, P0-2 | Add `structured_data`, `start_y_position` |
| `src/parsing/extractors/table_extractor.py` | P0-1 | Integrate structured extraction |
| `src/parsing/services/scaffolding_service.py` | P0-2 | Capture Y-positions |
| `src/parsing/services/chunking_service.py` | P0-2 | Y-aware parent assignment |
| `src/parsing/services/semantic_enrichment_service.py` | P1-1, P1-2 | Report-type aware extraction |

---

## Next Steps After Phase 1

Phase 1 completion enables:
- Direct table querying in RAG
- Accurate section assignment
- Unified multi-page tables
- Report-type specific extraction
- Evidence traceability

**Phase 2** will add:
- LLM-augmented enrichment (batch processing)
- Chart data extraction
- Query-ready JSON schema
- Visualization service

See `PHASE2_IMPLEMENTATION_PLAN.md` for details.
