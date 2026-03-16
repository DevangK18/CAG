# Session 3: Phase 5.5 — TOC Reconciliation Service

> **Model:** Opus | **Estimated effort:** 3-4 hours | **Lines changed:** ~250-300
> **Pre-requisite:** Read `TOC_IMPROVEMENT_CONTEXT.md` first
> **Dependencies:** None (can be implemented independently)

---

## Context & Motivation

This is the highest-impact change in the TOC improvement initiative.

**The structural gap**: Phase 4 (scaffolding) builds the TOC using heuristics, font analysis, and PDF bookmarks — all BEFORE the document layout is analyzed. Phase 5 (Docling) then runs full layout analysis and detects `Section-header` blocks with bounding boxes and confidence scores. But **Phase 4's TOC is never validated or enriched using Phase 5's independent signal**.

**What we're building**: A lightweight reconciliation phase (5.5) that runs AFTER Phase 5 and BEFORE Phase 6. It:
1. Extracts all `Section-header` blocks from Docling's layout output
2. Uses PyMuPDF to clip the actual text from each header's bounding box
3. Reconciles the Docling-detected headers with Phase 4's scaffold TOC
4. Updates the scaffold with improved TOC + heading_positions

**Why this matters so much**: Parent chunk quality in Qdrant depends entirely on TOC accuracy. A wrong TOC entry causes the RAG system to group unrelated children under the wrong parent, feeding misleading context structure to the LLM.

---

## Architecture

### New file: `toc_reconciliation_service.py`

Location: `services/parsing_pipeline/src/parsing_pipeline/modules/toc_reconciliation_service.py`

```
Input:  DocumentTask (with task.scaffold from Phase 4 and task.layout from Phase 5)
Output: DocumentTask (with task.scaffold.toc updated/enriched)
```

### Integration point: `main.py`

Insert a new loop between Phase 5 (layout analysis) and Phase 6 (content extraction), approximately at line 259.

---

## Detailed Implementation

### Part 1: The Service Class

```python
"""
TOC Reconciliation Service (Phase 5.5)

Fuses Phase 4 heuristic TOC with Phase 5 Docling Section-header detections
to produce a higher-quality, validated TOC with Y-coordinates.

Key insight: Docling independently detects section headers with bounding boxes.
This provides a second opinion on document structure that can validate, correct,
or supplement the heuristic TOC from Phase 4.
"""

import logging
import re
from typing import Dict, List, Optional, Tuple
from difflib import SequenceMatcher

import fitz  # PyMuPDF — already a pipeline dependency

from src.core.data_contracts import DocumentTask

logger = logging.getLogger(__name__)


class TOCReconciliationService:
    """
    Reconciles Phase 4 scaffold TOC with Phase 5 Docling section headers.
    
    Strategy:
    - High quality Phase 4 TOC (quality >= 70): Supplement with missed headers
    - Medium quality (40-69): Merge signals, prefer Docling for validation
    - Low quality (<40): Prefer Docling-detected headers as primary structure
    
    Always: Add Y-coordinates from Docling bboxes to heading_positions.
    """
    
    def __init__(
        self,
        similarity_threshold: float = 0.65,
        min_docling_headers: int = 3,
        confidence_threshold: float = 0.60,
    ):
        """
        Args:
            similarity_threshold: Min string similarity for title matching (0-1)
            min_docling_headers: Min Docling headers to consider usable signal
            confidence_threshold: Min Docling confidence for a Section-header block
        """
        self.similarity_threshold = similarity_threshold
        self.min_docling_headers = min_docling_headers
        self.confidence_threshold = confidence_threshold
    
    def reconcile(self, task: DocumentTask) -> DocumentTask:
        """
        Main entry point. Reconcile scaffold TOC with Docling headers.
        
        Args:
            task: DocumentTask with scaffold (Phase 4) and layout (Phase 5)
            
        Returns:
            DocumentTask with updated scaffold.toc and scaffold.heading_positions
        """
        if not task.layout:
            logger.debug(f"[{task.report_id}] No layout data — skipping reconciliation")
            return task
        
        if not task.scaffold:
            task.scaffold = {"toc": [], "page_map": {}, "heading_positions": {}}
        
        # Step 1: Extract Docling section headers with text
        docling_headers = self._extract_docling_headers(task)
        
        if len(docling_headers) < self.min_docling_headers:
            logger.info(
                f"[{task.report_id}] Only {len(docling_headers)} Docling headers "
                f"(min {self.min_docling_headers}) — skipping reconciliation"
            )
            return task
        
        # Step 2: Get current Phase 4 TOC
        current_toc = task.scaffold.get("toc", [])
        current_quality = task.scaffold.get("toc_quality", 50)
        
        # Step 3: Reconcile based on quality tier
        if current_quality >= 70 and current_toc:
            reconciled_toc, method = self._supplement_high_quality(
                current_toc, docling_headers, task.report_id
            )
        elif current_quality >= 40 and current_toc:
            reconciled_toc, method = self._merge_medium_quality(
                current_toc, docling_headers, task.report_id
            )
        else:
            reconciled_toc, method = self._prefer_docling_low_quality(
                current_toc, docling_headers, task.report_id
            )
        
        # Step 4: Update heading_positions with Y-coordinates from Docling
        heading_positions = task.scaffold.get("heading_positions", {})
        heading_positions = self._update_heading_positions(
            heading_positions, docling_headers, reconciled_toc
        )
        
        # Step 5: Update scaffold
        prev_count = len(current_toc)
        task.scaffold["toc"] = reconciled_toc
        task.scaffold["heading_positions"] = heading_positions
        task.scaffold["toc_method"] = f"{task.scaffold.get('toc_method', 'unknown')}+reconciled_{method}"
        
        # Update quality score
        new_quality = self._assess_reconciled_quality(reconciled_toc, docling_headers)
        task.scaffold["toc_quality"] = max(current_quality, new_quality)
        
        logger.info(
            f"[{task.report_id}] Reconciliation ({method}): "
            f"{prev_count} → {len(reconciled_toc)} entries, "
            f"quality {current_quality} → {task.scaffold['toc_quality']}, "
            f"{len(heading_positions)} heading positions"
        )
        
        return task
```

### Part 2: Docling Header Extraction

This is the trickiest part. Docling layout blocks don't contain text — only bounding boxes and labels. We must open the PDF and clip text from each Section-header bbox.

```python
    def _extract_docling_headers(self, task: DocumentTask) -> List[Dict]:
        """
        Extract section headers from Docling layout with text content.
        
        Docling blocks only have bbox + label. We use PyMuPDF to clip the
        actual text from each Section-header's bounding box.
        
        Returns:
            List of dicts: [
                {
                    "title": "Chapter II Compliance Audit",
                    "page": 15,           # 0-indexed physical
                    "y_position": 72.5,    # Y coordinate (top-left origin)
                    "confidence": 0.92,
                    "bbox": [x0, y0, x1, y1],
                    "level": 1,            # Inferred level
                },
                ...
            ]
        """
        headers = []
        
        # Get PDF path (same logic as layout_analysis_service.py)
        pdf_path = None
        if task.ocred_pdf_path:
            from pathlib import Path
            if Path(task.ocred_pdf_path).exists():
                pdf_path = task.ocred_pdf_path
        if not pdf_path and task.local_pdf_path:
            from pathlib import Path
            if Path(task.local_pdf_path).exists():
                pdf_path = task.local_pdf_path
        
        if not pdf_path:
            logger.warning(f"[{task.report_id}] No PDF path for text clipping")
            return []
        
        try:
            doc = fitz.open(pdf_path)
        except Exception as e:
            logger.warning(f"[{task.report_id}] Failed to open PDF for reconciliation: {e}")
            return []
        
        try:
            for page_num, blocks in task.layout.items():
                for block in blocks:
                    if block.get("label") != "Section-header":
                        continue
                    
                    if block.get("confidence", 0) < self.confidence_threshold:
                        continue
                    
                    bbox = block.get("bbox")
                    if not bbox or len(bbox) < 4:
                        continue
                    
                    # Clip text from bbox using PyMuPDF
                    title = self._clip_text_from_bbox(doc, page_num, bbox)
                    
                    if not title or len(title.strip()) < 3:
                        continue
                    
                    # Clean the title
                    title = self._clean_header_title(title)
                    
                    if not title:
                        continue
                    
                    # Infer hierarchy level
                    level = self._infer_level_from_docling(
                        title, bbox, block.get("confidence", 0.8)
                    )
                    
                    headers.append({
                        "title": title,
                        "page": page_num,
                        "y_position": bbox[1],  # y0 = top of header
                        "confidence": block.get("confidence", 0.8),
                        "bbox": bbox,
                        "level": level,
                    })
        finally:
            doc.close()
        
        # Sort by page then Y position
        headers.sort(key=lambda h: (h["page"], h["y_position"]))
        
        logger.info(f"[{task.report_id}] Extracted {len(headers)} Docling section headers")
        return headers

    def _clip_text_from_bbox(self, doc, page_num: int, bbox: List[float]) -> str:
        """
        Extract text from a bounding box region of a PDF page.
        
        Args:
            doc: PyMuPDF document object
            page_num: 0-indexed page number
            bbox: [x0, y0, x1, y1] in top-left origin
            
        Returns:
            Extracted text string
        """
        try:
            if page_num >= len(doc):
                return ""
            
            page = doc[page_num]
            rect = fitz.Rect(bbox[0], bbox[1], bbox[2], bbox[3])
            
            # Expand rect slightly to catch text at edges
            rect.x0 = max(0, rect.x0 - 2)
            rect.y0 = max(0, rect.y0 - 2)
            rect.x1 = min(page.rect.width, rect.x1 + 2)
            rect.y1 = min(page.rect.height, rect.y1 + 2)
            
            text = page.get_text("text", clip=rect)
            return text.strip()
            
        except Exception as e:
            logger.debug(f"Text clip failed on page {page_num}: {e}")
            return ""

    def _clean_header_title(self, title: str) -> str:
        """Clean extracted header text."""
        # Remove page numbers that might be caught
        title = re.sub(r'\s+\d+\s*$', '', title)
        # Remove excessive whitespace
        title = re.sub(r'\s+', ' ', title).strip()
        # Remove leading/trailing special chars
        title = title.strip('.-–—:;,')
        # Skip if too short or looks like noise
        if len(title) < 3 or title.isdigit():
            return ""
        return title
```

### Part 3: Level Inference

```python
    def _infer_level_from_docling(
        self, title: str, bbox: List[float], confidence: float
    ) -> int:
        """
        Infer hierarchy level from Docling header properties.
        
        Uses multiple signals:
        - Title patterns (Chapter, Annexure → level 1)
        - Numbered sections (1.1 → level 2, 1.1.1 → level 3)
        - Bbox height as proxy for font size
        """
        title_lower = title.lower().strip()
        
        # Pattern-based level detection
        if re.match(r'^chapter\s+[ivx\d]+', title_lower):
            return 1
        if re.match(r'^(annexure|appendix)\s+', title_lower):
            return 1
        if title_lower in ('preface', 'executive summary', 'introduction', 
                          'conclusion', 'recommendations', 'glossary',
                          'acknowledgement', 'abbreviations'):
            return 1
        
        # Numbered sections
        if re.match(r'^\d+\.\d+\.\d+', title):
            return 3
        if re.match(r'^\d+\.\d+', title):
            return 2
        if re.match(r'^\d+\.?\s+[A-Z]', title):
            return 1
        
        # Bbox height as font size proxy (larger = higher level)
        bbox_height = bbox[3] - bbox[1] if len(bbox) >= 4 else 0
        if bbox_height > 25:  # Large header
            return 1
        elif bbox_height > 18:
            return 2
        else:
            return 2  # Default to level 2 (safe middle ground)
```

### Part 4: Reconciliation Strategies

```python
    def _supplement_high_quality(
        self, current_toc, docling_headers, report_id
    ) -> Tuple[List[List], str]:
        """
        High quality Phase 4 TOC (>=70): Keep existing, add missed headers.
        
        Only adds Docling headers that don't match any existing TOC entry.
        """
        existing_titles = {entry[1].lower().strip() for entry in current_toc}
        existing_pages = {entry[2] for entry in current_toc}
        
        new_entries = []
        for header in docling_headers:
            # Check if already in TOC (fuzzy title match)
            matched = False
            header_title_lower = header["title"].lower().strip()
            
            for existing_title in existing_titles:
                similarity = SequenceMatcher(
                    None, header_title_lower, existing_title
                ).ratio()
                if similarity >= self.similarity_threshold:
                    matched = True
                    break
            
            if not matched:
                new_entries.append([
                    header["level"], header["title"], header["page"]
                ])
        
        if new_entries:
            merged = current_toc + new_entries
            merged.sort(key=lambda e: (e[2], e[0]))  # Sort by page, then level
            logger.info(f"[{report_id}] Supplemented: +{len(new_entries)} headers from Docling")
            return merged, "supplemented"
        
        return current_toc, "validated"

    def _merge_medium_quality(
        self, current_toc, docling_headers, report_id
    ) -> Tuple[List[List], str]:
        """
        Medium quality Phase 4 TOC (40-69): Merge both signals.
        
        For entries that exist in both: keep Phase 4's (it has better level info).
        For entries only in Docling: add them.
        For entries only in Phase 4: keep them (Docling may have missed some).
        """
        # Build Docling lookup
        docling_lookup = {}
        for header in docling_headers:
            key = header["title"].lower().strip()[:30]
            docling_lookup[key] = header
        
        # Match existing TOC entries to Docling
        matched_docling_keys = set()
        for entry in current_toc:
            entry_key = entry[1].lower().strip()[:30]
            for dk, dh in docling_lookup.items():
                similarity = SequenceMatcher(None, entry_key, dk).ratio()
                if similarity >= self.similarity_threshold:
                    matched_docling_keys.add(dk)
                    break
        
        # Add unmatched Docling headers
        new_entries = []
        for key, header in docling_lookup.items():
            if key not in matched_docling_keys:
                new_entries.append([
                    header["level"], header["title"], header["page"]
                ])
        
        merged = current_toc + new_entries
        merged.sort(key=lambda e: (e[2], e[0]))
        
        logger.info(
            f"[{report_id}] Merged: {len(current_toc)} Phase 4 + "
            f"{len(new_entries)} new Docling = {len(merged)} total"
        )
        return merged, "merged"

    def _prefer_docling_low_quality(
        self, current_toc, docling_headers, report_id
    ) -> Tuple[List[List], str]:
        """
        Low quality Phase 4 TOC (<40): Prefer Docling as primary.
        
        Falls back to current_toc only if Docling produces fewer entries.
        """
        docling_toc = [
            [h["level"], h["title"], h["page"]]
            for h in docling_headers
        ]
        
        if len(docling_toc) >= len(current_toc):
            logger.info(
                f"[{report_id}] Replacing low-quality TOC with "
                f"{len(docling_toc)} Docling headers"
            )
            return docling_toc, "docling_primary"
        else:
            # Docling found fewer — keep existing but supplement
            logger.info(
                f"[{report_id}] Low quality but Docling has fewer entries — "
                f"falling back to merge strategy"
            )
            return self._merge_medium_quality(current_toc, docling_headers, report_id)
```

### Part 5: Heading Positions & Quality Assessment

```python
    def _update_heading_positions(
        self, heading_positions: Dict, docling_headers: List[Dict], toc: List[List]
    ) -> Dict:
        """
        Update heading_positions with Y-coordinates from Docling bboxes.
        
        CRITICAL: Key format must be f"{page}_{title[:30]}" to match
        chunking_service.py line 301.
        """
        for header in docling_headers:
            # Match to TOC entries by title similarity
            for toc_entry in toc:
                toc_title = toc_entry[1]
                similarity = SequenceMatcher(
                    None, 
                    header["title"].lower().strip(),
                    toc_title.lower().strip()
                ).ratio()
                
                if similarity >= self.similarity_threshold:
                    # Use the TOC title (not Docling title) for the key
                    # to ensure compatibility with chunking_service
                    position_key = f"{toc_entry[2]}_{toc_title[:30]}"
                    heading_positions[position_key] = header["y_position"]
                    break
            else:
                # No TOC match — use Docling title directly
                position_key = f"{header['page']}_{header['title'][:30]}"
                heading_positions[position_key] = header["y_position"]
        
        return heading_positions

    def _assess_reconciled_quality(
        self, toc: List[List], docling_headers: List[Dict]
    ) -> int:
        """
        Assess quality of reconciled TOC (0-100).
        
        Factors:
        - Number of entries (more = likely more complete)
        - Multiple hierarchy levels
        - Sequential page numbers
        - Proportion validated by Docling
        """
        if not toc:
            return 0
        
        score = 40  # Base for having any TOC
        
        # Entry count bonus
        if len(toc) >= 10:
            score += 10
        elif len(toc) >= 5:
            score += 5
        
        # Multiple levels
        levels = set(entry[0] for entry in toc)
        if len(levels) >= 3:
            score += 15
        elif len(levels) >= 2:
            score += 10
        
        # Sequential pages
        pages = [entry[2] for entry in toc]
        if len(pages) >= 2:
            sequential = sum(1 for i in range(len(pages) - 1) if pages[i] <= pages[i+1])
            seq_ratio = sequential / (len(pages) - 1)
            score += int(seq_ratio * 15)
        
        # Docling validation ratio
        if docling_headers:
            docling_pages = {h["page"] for h in docling_headers}
            toc_pages = {entry[2] for entry in toc}
            overlap = len(docling_pages & toc_pages) / max(len(toc_pages), 1)
            score += int(overlap * 20)
        
        return min(100, score)
```

---

### Part 6: main.py Integration

Insert a new phase loop between Phase 5 and Phase 6 in `main.py`.

**Add import at top:**
```python
from src.parsing_pipeline.modules.toc_reconciliation_service import TOCReconciliationService
```

**Insert after Phase 5 loop (around line 259), before Phase 6:**
```python
    # Phase 5.5: TOC Reconciliation
    print("\n\nPHASE 5.5: TOC RECONCILIATION")
    print("-" * 40)
    reconciliation_service = TOCReconciliationService()
    reconciled_count = 0
    
    print(f"Reconciling TOC with Docling headers for {len(layout_complete)} documents...")
    
    for i, task in enumerate(layout_complete, 1):
        prev_toc_count = len(task.scaffold.get("toc", [])) if task.scaffold else 0
        result = reconciliation_service.reconcile(task)
        new_toc_count = len(result.scaffold.get("toc", [])) if result.scaffold else 0
        
        if new_toc_count != prev_toc_count:
            reconciled_count += 1
            print(
                f"  [{i:2d}/{len(layout_complete)}] {task.report_id}: "
                f"{prev_toc_count} → {new_toc_count} TOC entries"
            )
    
    print(f"\nReconciliation Results:")
    print(f"  Documents reconciled: {reconciled_count}/{len(layout_complete)}")
```

---

## Testing

### Unit tests: Create `tests/test_toc_reconciliation.py`

```python
"""Tests for Phase 5.5 TOC Reconciliation Service."""

import pytest
from src.parsing_pipeline.modules.toc_reconciliation_service import TOCReconciliationService


class TestTOCReconciliation:
    
    def setup_method(self):
        self.service = TOCReconciliationService()
    
    def test_supplement_high_quality(self):
        """High quality TOC gains new entries from Docling."""
        current_toc = [
            [1, "Chapter I Introduction", 5],
            [1, "Chapter II Findings", 15],
        ]
        docling_headers = [
            {"title": "Chapter I Introduction", "page": 5, "y_position": 72.0, 
             "confidence": 0.9, "bbox": [50, 72, 500, 90], "level": 1},
            {"title": "1.1 Background", "page": 7, "y_position": 100.0,
             "confidence": 0.85, "bbox": [50, 100, 400, 115], "level": 2},
            {"title": "Chapter II Findings", "page": 15, "y_position": 72.0,
             "confidence": 0.9, "bbox": [50, 72, 500, 90], "level": 1},
        ]
        result, method = self.service._supplement_high_quality(
            current_toc, docling_headers, "test_report"
        )
        assert len(result) == 3  # Added "1.1 Background"
        assert method == "supplemented"
    
    def test_heading_positions_format(self):
        """Verify heading_positions key format matches chunking_service."""
        docling_headers = [
            {"title": "Chapter I Introduction", "page": 5, "y_position": 72.5,
             "confidence": 0.9, "bbox": [50, 72, 500, 90], "level": 1},
        ]
        toc = [[1, "Chapter I Introduction", 5]]
        
        positions = self.service._update_heading_positions({}, docling_headers, toc)
        
        # Key must be f"{page}_{title[:30]}"
        expected_key = "5_Chapter I Introduction"
        assert expected_key in positions
        assert positions[expected_key] == 72.5
    
    def test_no_layout_graceful_skip(self):
        """Service handles missing layout data gracefully."""
        from src.core.data_contracts import DocumentTask
        task = DocumentTask(
            report_id="test",
            source_url="",
            local_pdf_path="",
            initial_metadata={},
            layout=None,
            scaffold={"toc": [[1, "Test", 0]], "toc_quality": 50},
        )
        result = self.service.reconcile(task)
        assert result.scaffold["toc"] == [[1, "Test", 0]]  # Unchanged
    
    def test_similarity_matching(self):
        """Fuzzy title matching handles minor differences."""
        service = TOCReconciliationService(similarity_threshold=0.6)
        # "Chapter I: Introduction" vs "Chapter I Introduction" should match
        from difflib import SequenceMatcher
        sim = SequenceMatcher(
            None,
            "chapter i: introduction",
            "chapter i introduction"
        ).ratio()
        assert sim >= 0.6
```

---

## Verification Checklist

- [ ] `toc_reconciliation_service.py` created in correct location
- [ ] Import added to `main.py`
- [ ] Phase 5.5 loop inserted between Phase 5 and Phase 6
- [ ] Heading positions use exact format: `f"{page}_{title[:30]}"`
- [ ] PyMuPDF text clipping handles edge cases (empty bbox, page out of range)
- [ ] Fallback: if reconciliation degrades quality, original TOC preserved
- [ ] Quality score only increases, never decreases (line: `max(current_quality, new_quality)`)
- [ ] All blocks with confidence < threshold are skipped
- [ ] All existing tests pass: `python -m pytest tests/ -v`
- [ ] New tests pass: `python -m pytest tests/test_toc_reconciliation.py -v`
- [ ] Logging shows reconciliation stats for every document
