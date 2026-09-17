# TOC Improvement Initiative — Shared Context for Claude Code

> **Read this file FIRST before implementing any session.**
> This provides the architectural context that every implementation session needs.

---

## 1. What We're Doing & Why

The CAG-Gateway parsing pipeline extracts Table of Contents (TOC) from 1,297 Indian government audit report PDFs. The TOC drives **everything downstream**: parent chunk creation, child-to-parent assignment, hierarchy in the Qdrant vector store, and LLM context grouping in the RAG system.

Current TOC extraction (~90% accuracy) uses heuristic font-based detection + PDF bookmarks + a table parser. We're adding **three new signals** and **two minor fixes** to push accuracy toward 97%+.

**The core insight**: Docling (already running in Phase 5) detects `Section-header` blocks with bounding boxes and confidence scores — but Phase 4 (TOC extraction) runs BEFORE Phase 5, so this high-quality signal is completely unused for TOC building. We're fixing that.

---

## 2. Pipeline Architecture (Phases 1–10)

```
Phase 1: Manifest Ingestion (Excel → DocumentTask)
Phase 2: Document Triage (native vs scanned)
Phase 3: OCR (Tesseract for scanned PDFs)
Phase 4: Document Scaffolding ← TOC extraction happens here
Phase 5: Layout Analysis (Docling v2) ← Section-headers detected here
  Phase 5.5: TOC Reconciliation ← NEW: Fuse Phase 4 + Phase 5 signals
Phase 6: Content Extraction (3-tier table strategy)
Phase 7: Hierarchical Chunking (parent-child)
  Phase 7.5: Hierarchy Enrichment (detect sub-sections)
Phase 8: Document Assembly (JSON output)
Phase 9: Semantic Enrichment (findings, recommendations)
Phase 10: Batch API (summaries, overviews)
```

**Data flow for TOC:**
```
scaffold.toc (Phase 4) → parent_chunks (Phase 7) → Qdrant parents (indexer) → RAG context grouping
scaffold.heading_positions (Phase 4) → Y-aware child assignment (Phase 7)
```

---

## 3. Key Data Contracts

### DocumentTask (the pipeline's main data carrier)
```python
class DocumentTask(BaseModel):
    report_id: str
    scaffold: Optional[dict] = None       # Contains 'toc', 'page_map', 'heading_positions'
    layout: Optional[Dict[int, List[Dict]]] = None  # page_num → list of layout blocks
    extracted_content: Optional[List[ExtractedContent]] = None
    parent_chunks: Optional[List[ParentChunk]] = None
    child_chunks: Optional[List[ChildChunk]] = None
    # ... other fields
```

### scaffold dict structure
```python
task.scaffold = {
    "toc": [
        [1, "Chapter I Introduction", 5],           # [level, title, page_physical_0indexed]
        [2, "1.1 Background", 7],
        [2, "1.2 Audit Objectives", 9],
        [1, "Chapter II Compliance Audit", 15],
        # ...
    ],
    "page_map": {
        0: "i", 1: "ii", 5: "1", 6: "2",          # physical_page → logical_label
    },
    "heading_positions": {
        "5_Chapter I Introduction": 72.5,            # f"{page}_{title[:30]}" → y_coordinate
        "7_1.1 Background": 145.3,
    },
    "toc_quality": 85,      # 0-100 quality score
    "toc_method": "embedded",  # or "heuristic", "table_parser"
}
```

### Layout block structure (from Docling, Phase 5)
```python
# task.layout[page_num] = list of blocks
block = {
    "bbox": [x0, y0, x1, y1],     # Top-left origin, PyMuPDF compatible
    "label": "Section-header",      # or "Text", "Table", "Figure", etc.
    "confidence": 0.92,
    "content_type": "SectionHeader", # Original Docling class name
    # NOTE: No text content! Must use PyMuPDF to clip text from bbox.
}
```

### heading_positions format (CRITICAL for chunking_service.py compatibility)
```python
# Key format: f"{page_physical}_{title[:30]}"
# Value: y_coordinate (float, top-left origin)
# Used in: chunking_service.py line 301
position_key = f"{start_page}_{title[:30]}"
start_y_position = heading_positions.get(position_key, None)
```

### ParentChunk
```python
class ParentChunk(BaseModel):
    chunk_id: str
    report_id: str
    hierarchy: Dict[str, str]              # {"level_1": "Chapter II", "level_2": "2.3 Findings"}
    page_range_physical: Tuple[int, int]   # (start, end) 0-indexed
    toc_entry: str                         # Title from TOC
    toc_level: int                         # 1=Chapter, 2=Section, etc.
    start_y_position: Optional[float]      # Y-coordinate for multi-section pages
```

---

## 4. File Locations

All paths relative to project root (`~/Projects/CAG/`):

### Parsing Pipeline (Phase 4-7)
```
services/parsing_pipeline/src/
├── core/data_contracts.py              # DocumentTask, ParentChunk, ChildChunk
├── parsing_pipeline/
│   ├── main.py                         # Pipeline orchestrator (Phase 1-10)
│   └── modules/
│       ├── scaffolding_service.py      # Phase 4: TOC extraction
│       ├── layout_analysis_service.py  # Phase 5: Docling analysis
│       ├── toc_table_parser.py         # TOC line parser (11 regex patterns)
│       ├── intelligent_toc_service.py  # TOC orchestrator (4 layers)
│       ├── chunking_service.py         # Phase 7: Parent-child chunking
│       └── hierarchy_enricher.py       # Phase 7.5: Sub-section detection
```

### RAG Pipeline (Qdrant + Retrieval)
```
src/rag_pipeline/
├── embedding_service.py    # Hierarchy prefix already implemented here
├── qdrant_service.py       # Vector store operations
├── retrieval_service.py    # Hybrid search + reranking
├── rag_service.py          # LLM context building + generation
├── indexer.py              # JSON → Qdrant ingestion
└── models.py               # RetrievedChunk, ParentContext, etc.
```

---

## 5. Implementation Sessions Overview

### Session 1: Quick Wins (Sonnet)
- **K-Means → quantile bucketing** in scaffolding_service.py
- **Reranker breadcrumb fix** in retrieval_service.py
- Total: ~40 lines, two independent changes

### Session 2: Printed TOC Pre-Pass (Sonnet)
- Add raw text extraction at top of `build_scaffold()`
- Feed through toc_table_parser regex patterns
- ~80 lines in scaffolding_service.py

### Session 3: Phase 5.5 TOC Reconciliation (Opus)
- New file: `toc_reconciliation_service.py`
- Integration in main.py between Phase 5 and Phase 6
- Extract text from Docling Section-header bboxes via PyMuPDF
- Reconcile with Phase 4 scaffold.toc
- ~250 lines

### Session 4: LLM Validation for Low-Quality TOCs (Sonnet)
- Depends on Session 3 being complete
- For TOCs with quality < 50 after reconciliation
- Uses Claude Haiku via Anthropic API
- ~150 lines

---

## 6. Testing Approach

All sessions should:
1. Add/modify tests in the existing test suite
2. Test with at least 2-3 sample reports if possible
3. Ensure backward compatibility (if reconciliation degrades, fall back to Phase 4 output)
4. Log quality metrics for before/after comparison

Existing test command:
```bash
cd services/parsing_pipeline
python -m pytest tests/ -v
```

---

## 7. Critical Constraints

1. **159 passing tests** — don't break them
2. **heading_positions key format** must be `f"{page}_{title[:30]}"` or chunking breaks
3. **Docling layout blocks have NO text** — must use PyMuPDF to clip from bbox
4. **toc_quality score** is used downstream — new methods should update it appropriately
5. **Phase ordering**: Phase 5.5 runs AFTER Docling (Phase 5) and BEFORE content extraction (Phase 6)
6. **PyMuPDF** (`fitz`) is already a dependency in the pipeline — no new installs needed
7. **scaffold dict** is the single source of truth — all TOC improvements must write back to it
