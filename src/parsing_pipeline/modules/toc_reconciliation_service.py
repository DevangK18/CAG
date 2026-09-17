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
from pathlib import Path

import fitz  # PyMuPDF — already a pipeline dependency

from src.core.data_contracts import DocumentTask
from src.parsing_pipeline.config import get_config, TOCReconciliationConfig
from src.parsing_pipeline.instrumentation import get_noop_emitter
from src.parsing_pipeline.modules.ocr_normalizer import get_ocr_normalizer

logger = logging.getLogger(__name__)


class TOCReconciliationService:
    """
    Reconciles Phase 4 scaffold TOC with Docling section headers.

    P0-02 improvements:
    - Empty TOC explicit handling
    - Noise rejection patterns
    - Quality cap at 85 for Phase 5.7 eligibility
    - Parent deduplication

    P0-04 improvements:
    - Chapter pattern promotion to L1
    - L1 count sanity check (≤15)
    - Orphan section detection
    """

    # P0-02: Noise patterns to reject from candidate headers
    NOISE_PATTERNS = [
        r"^\([Pp]aragraphs?\s+[\d.]+\)",  # "(Paragraph 3.2)"
        r"^\([Ss]ource:?\s.*\)$",          # "(Source: Records...)"
        r"^Report\s+No\.\s+\d+\s+of",      # Running header
        r"^Page\s+\d+$",                    # Page number
        r"^[a-z]\.\s+",                     # List item "a. ..."
        r"^\([ivxlcdm]+\)\s+",              # "(i) ...", "(iv) ..."
        r"^\d+$",                            # Just a number
        r"^-+$",                             # Just dashes
    ]

    # P0-04: Chapter patterns for L1 promotion
    CHAPTER_PATTERNS = [
        r"^Chapter\s+(\d+|[IVXivx]+)\b",
        r"^CHAPTER\s+(\d+|[IVXivx]+)\b",
        r"^Annexure\s+[A-Z0-9]+",
        r"^ANNEXURE\s+[A-Z0-9]+",
        r"^Appendix\s+[A-Z0-9]+",
        r"^APPENDIX\s+[A-Z0-9]+",
    ]

    # P0-02: Quality cap for Phase 5.7 eligibility
    QUALITY_CAP = 85

    # P0-04: Maximum expected L1 entries
    # C2 fix: Re-tuned from 15 to 35 based on 37-report corpus distribution
    # 15 flagged 67% of corpus; 35 flags only 9% (4 reports with complex structures)
    MAX_L1_COUNT = 35

    def __init__(
        self,
        similarity_threshold: Optional[float] = None,
        min_docling_headers: Optional[int] = None,
        confidence_threshold: Optional[float] = None,
        config: Optional[TOCReconciliationConfig] = None,
        trace_emitter=None,
    ):
        """
        Args:
            similarity_threshold: Min string similarity for title matching (overrides config)
            min_docling_headers: Min Docling headers to consider usable signal (overrides config)
            confidence_threshold: Min Docling confidence for Section-header block (overrides config)
            config: TOCReconciliationConfig instance (default: load from global config)
            trace_emitter: Optional TraceEmitter for instrumentation
        """
        # Load from config if not provided
        if config is None:
            config = get_config().toc_reconciliation

        self.similarity_threshold = (
            similarity_threshold if similarity_threshold is not None
            else config.similarity_threshold
        )
        self.min_docling_headers = (
            min_docling_headers if min_docling_headers is not None
            else config.min_docling_headers
        )
        self.confidence_threshold = (
            confidence_threshold if confidence_threshold is not None
            else config.section_header_confidence_threshold
        )
        self.quality_high_threshold = config.quality_high_threshold
        self.quality_medium_threshold = config.quality_medium_threshold
        self._trace_emitter = trace_emitter or get_noop_emitter()

    def reconcile(self, task: DocumentTask, trace_emitter=None) -> DocumentTask:
        """
        Main entry point. Reconcile scaffold TOC with Docling headers.

        Args:
            task: DocumentTask with scaffold (Phase 4) and layout (Phase 5)
            trace_emitter: Optional TraceEmitter for instrumentation

        Returns:
            DocumentTask with updated scaffold.toc and scaffold.heading_positions
        """
        emitter = trace_emitter or self._trace_emitter

        if not task.layout:
            logger.debug(f"[{task.report_id}] No layout data — skipping reconciliation")
            return task

        if not task.scaffold:
            task.scaffold = {"toc": [], "page_map": {}, "heading_positions": {}}

        # Step 1: Extract Docling section headers with text
        docling_headers = self._extract_docling_headers(task)

        # Trace: Docling header extraction result
        emitter.emit_io(
            "5.5",
            {"pages_scanned": len(task.layout)},
            {
                "docling_headers_total": len(docling_headers),
                "above_confidence": len([h for h in docling_headers if h.get("confidence", 0) >= self.confidence_threshold]),
            },
        )

        if len(docling_headers) < self.min_docling_headers:
            logger.info(
                f"[{task.report_id}] Only {len(docling_headers)} Docling headers "
                f"(min {self.min_docling_headers}) — skipping reconciliation"
            )
            return task

        # P0-02: Apply noise rejection filter to Docling headers
        docling_headers = self._filter_noise_headers(docling_headers)
        if not docling_headers:
            logger.info(f"[{task.report_id}] All Docling headers filtered as noise — skipping")
            return task

        # P0-04: Promote Chapter patterns to L1
        docling_headers = self._promote_chapters_to_l1(docling_headers)

        # Step 2: Get current Phase 4 TOC
        current_toc = task.scaffold.get("toc", [])
        current_quality = task.scaffold.get("toc_quality", 50)

        # P0-02: Handle empty-TOC explicitly (separate branch)
        if not current_toc:
            # No Phase 4 TOC to preserve — use Docling entirely
            emitter.emit_decision(
                "5.5",
                "quality_tier",
                "empty_toc",
                ["high", "medium", "low", "empty_toc"],
                f"toc_empty=True, quality_score={current_quality}",
            )
            reconciled_toc, method = self._prefer_docling_low_quality(
                current_toc, docling_headers, task.report_id, emitter
            )
        # Step 3: Reconcile based on quality tier (current_toc is non-empty here)
        elif current_quality >= self.quality_high_threshold:
            # Trace: Quality tier decision - high
            emitter.emit_decision(
                "5.5",
                "quality_tier",
                "high",
                ["high", "medium", "low", "empty_toc"],
                f"quality_score={current_quality} >= high_threshold={self.quality_high_threshold}",
            )
            reconciled_toc, method = self._supplement_high_quality(
                current_toc, docling_headers, task.report_id, emitter
            )
        elif current_quality >= self.quality_medium_threshold:
            # Trace: Quality tier decision - medium
            emitter.emit_decision(
                "5.5",
                "quality_tier",
                "medium",
                ["high", "medium", "low", "empty_toc"],
                f"quality_score={current_quality}, medium_threshold={self.quality_medium_threshold}",
            )
            reconciled_toc, method = self._merge_medium_quality(
                current_toc, docling_headers, task.report_id, emitter
            )
        else:
            # Trace: Quality tier decision - low
            emitter.emit_decision(
                "5.5",
                "quality_tier",
                "low",
                ["high", "medium", "low", "empty_toc"],
                f"quality_score={current_quality} < medium_threshold={self.quality_medium_threshold}",
            )
            reconciled_toc, method = self._prefer_docling_low_quality(
                current_toc, docling_headers, task.report_id, emitter
            )

        # Step 4: Update heading_positions with Y-coordinates from Docling
        heading_positions = task.scaffold.get("heading_positions", {})
        heading_positions = self._update_heading_positions(
            heading_positions, docling_headers, reconciled_toc
        )

        # P0-02: Deduplicate parents by (normalized_title, page)
        reconciled_toc = self._deduplicate_parents(reconciled_toc)

        # P0-04: L1 count sanity check
        l1_count = sum(1 for entry in reconciled_toc if entry[0] == 1)
        if l1_count > self.MAX_L1_COUNT:
            emitter.emit_red_flag(
                "5.5",
                "l1_count_excessive",
                {"count": l1_count, "max": self.MAX_L1_COUNT},
            )
            logger.warning(
                f"[{task.report_id}] Excessive L1 entries: {l1_count} > {self.MAX_L1_COUNT}"
            )

        # P0-04: Detect orphan sections (numbered sections without L1 parent)
        orphans = self._detect_orphan_sections(reconciled_toc, emitter)
        if orphans:
            logger.warning(
                f"[{task.report_id}] Orphan sections detected: {len(orphans)} entries"
            )

        # Step 5: Update scaffold
        prev_count = len(current_toc)
        task.scaffold["toc"] = reconciled_toc
        task.scaffold["heading_positions"] = heading_positions
        task.scaffold["toc_method"] = f"{task.scaffold.get('toc_method', 'unknown')}+reconciled_{method}"

        # Update quality score with P0-02 quality cap
        new_quality = self._assess_reconciled_quality(reconciled_toc, docling_headers)
        # P0-02: Cap quality at 85 to allow Phase 5.7 to fire on edge cases
        capped_quality = min(max(current_quality, new_quality), self.QUALITY_CAP)
        task.scaffold["toc_quality"] = capped_quality

        # Trace: TOC mutation result
        emitter.emit_io(
            "5.5",
            {"entries_before": prev_count, "quality_before": current_quality},
            {
                "entries_after": len(reconciled_toc),
                "quality_after": task.scaffold["toc_quality"],
                "method": method,
                "heading_positions_count": len(heading_positions),
            },
        )

        logger.info(
            f"[{task.report_id}] Reconciliation ({method}): "
            f"{prev_count} → {len(reconciled_toc)} entries, "
            f"quality {current_quality} → {task.scaffold['toc_quality']}, "
            f"{len(heading_positions)} heading positions"
        )

        return task

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
            if Path(task.ocred_pdf_path).exists():
                pdf_path = task.ocred_pdf_path
        if not pdf_path and task.local_pdf_path:
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

                    # P2-17: Apply OCR normalization (fixes Roman numeral corruptions)
                    title = get_ocr_normalizer().normalize_toc_entry(title)

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

    def _supplement_high_quality(
        self, current_toc: List[List], docling_headers: List[Dict], report_id: str, emitter=None
    ) -> Tuple[List[List], str]:
        """
        High quality Phase 4 TOC (>=70): Keep existing, add missed headers.

        Only adds Docling headers that don't match any existing TOC entry.
        """
        emitter = emitter or self._trace_emitter
        existing_titles = {entry[1].lower().strip() for entry in current_toc}

        new_entries = []
        match_samples = []  # Collect samples for tracing
        for header in docling_headers:
            # Check if already in TOC (fuzzy title match)
            matched = False
            header_title_lower = header["title"].lower().strip()
            best_match = {"title": None, "similarity": 0}

            for existing_title in existing_titles:
                similarity = SequenceMatcher(
                    None, header_title_lower, existing_title
                ).ratio()
                if similarity > best_match["similarity"]:
                    best_match = {"title": existing_title, "similarity": similarity}
                if similarity >= self.similarity_threshold:
                    matched = True
                    break

            # Collect sample data for first 5 headers
            if len(match_samples) < 5:
                match_samples.append({
                    "docling_title": header["title"][:50],
                    "best_match": best_match["title"][:50] if best_match["title"] else None,
                    "similarity": round(best_match["similarity"], 2),
                    "matched": matched,
                })

            if not matched:
                new_entries.append([
                    header["level"], header["title"], header["page"]
                ])

        # Trace: Similarity match samples
        if match_samples:
            emitter.emit_sample("5.5", "similarity_matches", match_samples)

        if new_entries:
            merged = current_toc + new_entries
            merged.sort(key=lambda e: (e[2], e[0]))  # Sort by page, then level
            logger.info(f"[{report_id}] Supplemented: +{len(new_entries)} headers from Docling")
            return merged, "supplemented"

        return current_toc, "validated"

    def _merge_medium_quality(
        self, current_toc: List[List], docling_headers: List[Dict], report_id: str, emitter=None
    ) -> Tuple[List[List], str]:
        """
        Medium quality Phase 4 TOC (40-69): Merge both signals.

        For entries that exist in both: keep Phase 4's (it has better level info).
        For entries only in Docling: add them.
        For entries only in Phase 4: keep them (Docling may have missed some).
        """
        emitter = emitter or self._trace_emitter

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
        self, current_toc: List[List], docling_headers: List[Dict], report_id: str, emitter=None
    ) -> Tuple[List[List], str]:
        """
        Low quality Phase 4 TOC (<40): Prefer Docling as primary.

        Falls back to current_toc only if Docling produces fewer entries.
        """
        emitter = emitter or self._trace_emitter

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
            return self._merge_medium_quality(current_toc, docling_headers, report_id, emitter)

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

    # ==================== P0-02: Noise Rejection and Deduplication ====================

    def _filter_noise_headers(self, headers: List[Dict]) -> List[Dict]:
        """
        P0-02: Filter out noise entries from Docling headers.

        Rejects headers matching noise patterns (paragraph references, source
        citations, page numbers, list items) and headers with excessive
        non-printable characters (encoded-font garbage).

        Args:
            headers: List of Docling header dicts

        Returns:
            Filtered list with noise entries removed
        """
        filtered = []
        for header in headers:
            title = header.get("title", "")

            # Check against noise patterns
            is_noise = False
            for pattern in self.NOISE_PATTERNS:
                if re.match(pattern, title, re.IGNORECASE):
                    is_noise = True
                    break

            # Check for excessive non-ASCII-printable characters (>30%)
            if not is_noise and title:
                non_printable = sum(1 for c in title if ord(c) < 32 or ord(c) > 126)
                if non_printable / len(title) > 0.3:
                    is_noise = True

            if not is_noise:
                filtered.append(header)

        if len(headers) != len(filtered):
            logger.debug(
                f"Noise filter: {len(headers)} → {len(filtered)} headers "
                f"({len(headers) - len(filtered)} rejected)"
            )

        return filtered

    def _deduplicate_parents(self, toc: List[List]) -> List[List]:
        """
        P0-02: Deduplicate TOC entries by (normalized_title, page).

        When duplicate entries exist, keep the one with the deeper level
        (higher level number = deeper in hierarchy).

        Args:
            toc: List of TOC entries [level, title, page]

        Returns:
            Deduplicated TOC list
        """
        seen = {}
        for entry in toc:
            level, title, page = entry[0], entry[1], entry[2]

            # Normalize title for comparison
            normalized = " ".join(title.lower().split())
            key = (normalized, page)

            if key in seen:
                # Keep deeper level (higher number) or earlier position
                if level > seen[key]["level"]:
                    seen[key] = {"entry": entry, "level": level}
            else:
                seen[key] = {"entry": entry, "level": level}

        return [item["entry"] for item in seen.values()]

    # ==================== P0-04: Chapter Promotion and Orphan Detection ====================

    def _promote_chapters_to_l1(self, headers: List[Dict]) -> List[Dict]:
        """
        P0-04: Promote Chapter/Annexure/Appendix patterns to L1.

        Docling assigns levels based on font size heuristics, not semantic
        patterns. This method ensures that chapter-level headings are always
        promoted to L1 regardless of their detected level.

        Args:
            headers: List of Docling header dicts

        Returns:
            Headers with Chapter patterns promoted to L1
        """
        promoted_count = 0
        for header in headers:
            title = header.get("title", "")
            current_level = header.get("level", 2)

            for pattern in self.CHAPTER_PATTERNS:
                if re.match(pattern, title, re.IGNORECASE):
                    if current_level != 1:
                        header["level"] = 1
                        promoted_count += 1
                    break

        if promoted_count > 0:
            logger.debug(f"P0-04: Promoted {promoted_count} Chapter patterns to L1")

        return headers

    def _detect_orphan_sections(
        self, toc: List[List], emitter=None
    ) -> List[Dict]:
        """
        P0-04: Detect numbered sections that lack a parent chapter at L1.

        Algorithm:
        1. Build set of L1 section numbers (extract leading digit from
           "Chapter 3", "3. Introduction", etc.)
        2. For each L2+ section, extract its chapter number (first digit
           before first dot)
        3. If chapter number not in L1 set, flag as orphan

        Args:
            toc: List of TOC entries [level, title, page]
            emitter: Optional TraceEmitter for red flags

        Returns:
            List of orphan section dicts with title, level, expected_chapter
        """
        emitter = emitter or self._trace_emitter

        # Build set of L1 chapter numbers
        l1_chapter_numbers = set()
        for entry in toc:
            level, title, page = entry[0], entry[1], entry[2]
            if level == 1:
                # Extract chapter number from "Chapter 3", "3. Introduction", etc.
                match = re.match(r"(?:Chapter\s+)?(\d+)", title, re.IGNORECASE)
                if match:
                    l1_chapter_numbers.add(int(match.group(1)))

        # Detect orphan sections
        orphans = []
        for entry in toc:
            level, title, page = entry[0], entry[1], entry[2]
            if level > 1:
                # Extract chapter number from "3.1", "3.2.1", etc.
                match = re.match(r"(\d+)\.", title)
                if match:
                    chapter_num = int(match.group(1))
                    if chapter_num not in l1_chapter_numbers:
                        orphans.append({
                            "title": title,
                            "level": level,
                            "expected_chapter": chapter_num,
                        })

        # D7: Calculate orphan ratio (data-derived threshold: 0.75 → ~13.5% firing)
        ORPHAN_RATIO_THRESHOLD = 0.75

        total_sections = sum(1 for entry in toc if entry[0] >= 2)  # L2+ entries
        orphan_ratio = len(orphans) / total_sections if total_sections > 0 else 0

        if orphan_ratio > ORPHAN_RATIO_THRESHOLD:
            emitter.emit_red_flag(
                "5.5",
                "orphan_sections_detected",
                {
                    "count": len(orphans),
                    "total_sections": total_sections,
                    "ratio": round(orphan_ratio, 3),
                    "threshold": ORPHAN_RATIO_THRESHOLD,
                    "samples": orphans[:5],
                },
            )
        elif orphans:
            logger.info(
                f"[{emitter.report_id}] {len(orphans)} orphan sections "
                f"(ratio {orphan_ratio:.1%}, below threshold)"
            )

        return orphans
