"""
ContentExtractionService: Router-Dispatcher Orchestrator
Coordinates specialized extractors (Table, Visual, Text) using router-dispatcher pattern.
Transforms layout-recognized blocks into structured content for downstream processing.

PHASE 2 FIXES IMPLEMENTED:
- Integrated ChunkFilterService for garbage filtering

PHASE 3 FIXES IMPLEMENTED:
- Cross-page paragraph merging for split paragraphs
"""

import sys
from pathlib import Path
from typing import Dict, Callable, Optional, List
import time
import logging
import re
from PIL import Image
import io
import hashlib

from src.core.data_contracts import DocumentTask, ExtractedContent
from src.parsing_pipeline.extractors.pdfplumber_table_extractor import PdfplumberTableExtractor
from src.parsing_pipeline.extractors.text_extractor import TextExtractor
from src.parsing_pipeline.modules.chunk_filter_service import ChunkFilterService

logger = logging.getLogger(__name__)


class ContentExtractionService:
    """
    Orchestrator service that routes content blocks to appropriate specialized extractors.

    Uses router-dispatcher pattern:
    - Router: Maps DocLayNet labels to extraction functions
    - Dispatcher: Routes each layout block to its specialized extractor
    - Results: Aggregates extracted content into DocumentTask.extracted_content

    PHASE 3: Includes cross-page paragraph merging for improved RAG retrieval.
    """

    # Patterns indicating paragraph continuation
    CONTINUATION_START_PATTERNS = [
        r"^[a-z]",  # Starts with lowercase
        r"^[,;:]",  # Starts with continuation punctuation
        r"^\d+\s+(?:per\s+)?cent",  # Continues a percentage
        r"^and\s",  # Starts with conjunction
        r"^or\s",
        r"^but\s",
        r"^which\s",
        r"^that\s",
        r"^of\s",
        r"^in\s",
        r"^to\s",
        r"^for\s",
    ]

    # Patterns indicating incomplete paragraph ending
    INCOMPLETE_END_PATTERNS = [
        r"[a-z]$",  # Ends with lowercase letter (no punctuation)
        r"[,;:\-]$",  # Ends with continuation punctuation
        r"\b(the|a|an|and|or|of|in|to|for|with|by|as|at|from)$",  # Ends with preposition/article
    ]

    def __init__(self, trace_emitter=None):
        """Initialize extractor instances and build routing map.

        Args:
            trace_emitter: Optional TraceEmitter for instrumentation. If None,
                          tracing calls are no-ops.
        """
        logger.info("Initializing ContentExtractionService...")

        # Store trace emitter for per-table instrumentation
        self._trace_emitter = trace_emitter

        # Initialize specialized extractors
        # V2: PdfplumberTableExtractor replaces TATR+Tesseract TableExtractor
        self.table_extractor = PdfplumberTableExtractor()
        self.text_extractor = TextExtractor()

        # V2: Cache structured table extractor (used by Docling Tier 2 and pdfplumber)
        from src.parsing_pipeline.modules.structured_table_extractor import StructuredTableExtractor
        self.structured_table_extractor = StructuredTableExtractor()

        # Build router map: layout label → extraction function
        self.router: Dict[str, Callable] = {
            # Table extraction (V2: pdfplumber for native PDFs)
            "Table": self.table_extractor.extract,
            # Visual asset extraction (V2: save image for downstream Gemini extraction)
            "Picture": self._extract_and_save_visual,
            "Figure": self._extract_and_save_visual,
            # Text extraction (various content types)
            "Text": self.text_extractor.extract,
            "Section-header": self.text_extractor.extract,
            "Title": self.text_extractor.extract,
            "List-item": self.text_extractor.extract,
            "Footnote": self._extract_footnote,
            "Page-header": None,  # Skip noise elements
            "Page-footer": None,  # Skip noise elements
        }
        self.filter_service = ChunkFilterService()

        # Compile continuation patterns
        self._continuation_start = [
            re.compile(p, re.IGNORECASE) for p in self.CONTINUATION_START_PATTERNS
        ]
        self._incomplete_end = [re.compile(p) for p in self.INCOMPLETE_END_PATTERNS]

        logger.info(
            f"Router configured with {len([r for r in self.router.values() if r is not None])} active extractors"
        )
        logger.info("ContentExtractionService ready!")

    def _select_pdf_source(self, task: DocumentTask) -> str:
        """
        Select appropriate PDF path: OCR'd version for scanned docs, raw for native text.

        Args:
            task: DocumentTask with processing metadata

        Returns:
            Path to PDF file to use for extraction
        """
        if task.classification == "scanned" and task.ocred_pdf_path:
            return task.ocred_pdf_path
        else:
            return task.local_pdf_path

    def _crop_block_image(
        self, pdf_path: str, page_num: int, bbox: List[float]
    ) -> Optional[Image.Image]:
        """
        Crop image of a block for dead letter queue storage.

        Args:
            pdf_path: Path to PDF document
            page_num: Page number
            bbox: Bounding box coordinates

        Returns:
            PIL Image of the cropped block, or None if cropping fails
        """
        try:
            import fitz

            doc = fitz.open(pdf_path)
            page = doc.load_page(page_num)

            # Convert page to image at 200 DPI (reasonable for debugging)
            pixmap = page.get_pixmap(dpi=200)

            # Calculate pixel coordinates from PDF coordinates
            page_width, page_height = page.rect.width, page.rect.height
            scale_x = pixmap.width / page_width
            scale_y = pixmap.height / page_height

            pixel_bbox = [
                bbox[0] * scale_x,  # x0
                bbox[1] * scale_y,  # y0
                bbox[2] * scale_x,  # x1
                bbox[3] * scale_y,  # y1
            ]

            # Crop the image
            img_data = pixmap.tobytes("png")
            full_image = Image.open(io.BytesIO(img_data))

            # Ensure bbox is within image bounds
            pixel_bbox = [
                max(0, int(pixel_bbox[0])),
                max(0, int(pixel_bbox[1])),
                min(pixmap.width, int(pixel_bbox[2])),
                min(pixmap.height, int(pixel_bbox[3])),
            ]

            # Crop image
            cropped = full_image.crop(pixel_bbox)

            doc.close()
            return cropped

        except Exception as e:
            # If cropping fails, we don't want to crash the pipeline
            return None

    def _save_failed_extraction(
        self,
        report_id: str,
        page_num: int,
        label: str,
        bbox: List[float],
        pdf_path: str,
    ):
        """
        Save failed extraction information for debugging (Dead Letter Queue pattern).

        Args:
            report_id: Report identifier
            page_num: Page number
            label: Block label type
            bbox: Bounding box coordinates
            pdf_path: Source PDF path
        """
        try:
            # Create dead letter queue directory structure
            dlq_dir = Path("data/dead_letter_queue")
            content_type_dir = dlq_dir / label.lower()
            content_type_dir.mkdir(parents=True, exist_ok=True)

            # Generate unique filename using bbox hash
            bbox_str = "_".join(f"{coord:.1f}" for coord in bbox)
            unique_hash = hashlib.md5(
                f"{report_id}_{page_num}_{bbox_str}".encode()
            ).hexdigest()[:8]
            basename = f"{report_id}_p{page_num}_{unique_hash}"

            # Save metadata to text file
            metadata_path = content_type_dir / f"{basename}.txt"
            with open(metadata_path, "w") as f:
                f.write(f"Report ID: {report_id}\n")
                f.write(f"Page: {page_num}\n")
                f.write(f"Label: {label}\n")
                f.write(f"BBox: {bbox}\n")
                f.write(f"Source PDF: {pdf_path}\n")
                f.write(f"Timestamp: {time.time()}\n")

            # Save cropped image
            cropped_image = self._crop_block_image(pdf_path, page_num, bbox)
            if cropped_image:
                image_path = content_type_dir / f"{basename}.png"
                cropped_image.save(image_path)
                logger.error(f"SAVED FAILED EXTRACTION: {label} → {image_path}")

        except Exception as e:
            # Don't let DLQ saving fail break the pipeline
            logger.error(f"Warning: Failed to save failed extraction info: {e}")

    def _route_block(
        self, block: Dict, pdf_path: str, page_num: int, report_id: str, is_scanned: bool,
        trace_emitter=None
    ) -> Optional[ExtractedContent]:
        """
        Route individual layout block to appropriate extractor.

        V2: 3-tier table extraction strategy with PDF-type routing:
          Scanned PDFs: Tier 2 (Docling) → Tier 3 (Gemini)
          Native PDFs:  Tier 1 (pdfplumber) → Tier 2 (Docling) → Tier 3 (Gemini)

        Args:
            block: Layout block dict with 'label', 'bbox', 'confidence' keys
            pdf_path: Path to PDF document
            page_num: Physical page number
            report_id: Report identifier for logging/tracing
            is_scanned: True if PDF is scanned (from task.classification)
            trace_emitter: Optional TraceEmitter for per-table instrumentation

        Returns:
            ExtractedContent object or None if extraction failed/skipped
        """
        label = block.get("label", "Unknown")
        bbox = block.get("bbox", [])
        confidence = block.get("confidence")
        emitter = trace_emitter or self._trace_emitter

        # Special routing for Table blocks (3-tier strategy)
        if label == "Table":
            if is_scanned:
                # SCANNED PDFs: Tier 2 → Tier 3 (skip pdfplumber)
                if block.get("docling_table_markdown"):
                    logger.info(f"  Scanned PDF: Using Docling TableFormer (page {page_num}) - Tier 2")
                    # Trace: Scanned PDF uses Docling directly (Tier 2)
                    if emitter:
                        emitter.emit_decision(
                            "6",
                            "table_extraction_tier",
                            "tier2_docling",
                            ["tier1_pdfplumber", "tier2_docling", "tier3_gemini"],
                            f"Scanned PDF skips Tier 1, Docling markdown available (page {page_num})",
                        )
                    return self._use_docling_table(
                        markdown=block["docling_table_markdown"],
                        page_num=page_num,
                        bbox=bbox,
                        confidence=confidence,
                    )
                else:
                    # Docling failed, go straight to Tier 3
                    logger.info(f"  Scanned PDF: No Docling table, saving for Gemini (page {page_num}) - Tier 3")
                    # Trace: Scanned PDF falls back to Gemini (Tier 3)
                    if emitter:
                        emitter.emit_fallback(
                            "6",
                            "tier2_docling",
                            "tier3_gemini",
                            f"Scanned PDF, no Docling markdown available (page {page_num})",
                        )
                    return self._extract_and_save_visual(
                        pdf_path=pdf_path,
                        page_num=page_num,
                        bbox=bbox,
                        label="Table",
                        confidence=confidence,
                        report_id=report_id,
                    )
            else:
                # NATIVE PDFs: Tier 1 → Tier 2 → Tier 3
                # Try pdfplumber first
                try:
                    result = self.table_extractor.extract(
                        pdf_path=pdf_path,
                        page_num=page_num,
                        bbox=bbox,
                        label=label,
                        confidence=confidence,
                        report_id=report_id,
                    )

                    if result:
                        # Trace: Tier 1 success
                        if emitter:
                            emitter.emit_decision(
                                "6",
                                "table_extraction_tier",
                                "tier1_pdfplumber",
                                ["tier1_pdfplumber", "tier2_docling", "tier3_gemini"],
                                f"Native PDF, pdfplumber extraction successful (page {page_num})",
                            )
                        return result  # Tier 1 success

                    # Tier 1 failed, try Tier 2 (Docling)
                    if block.get("docling_table_markdown"):
                        logger.error(f"  Native PDF: pdfplumber failed, using Docling (page {page_num}) - Tier 2")
                        # Trace: Fallback from Tier 1 to Tier 2
                        if emitter:
                            emitter.emit_fallback(
                                "6",
                                "tier1_pdfplumber",
                                "tier2_docling",
                                f"pdfplumber returned None (page {page_num})",
                            )
                        return self._use_docling_table(
                            markdown=block["docling_table_markdown"],
                            page_num=page_num,
                            bbox=bbox,
                            confidence=confidence,
                        )

                    # Both Tier 1 and 2 failed, use Tier 3
                    logger.error(f"  Native PDF: pdfplumber + Docling failed, saving for Gemini (page {page_num}) - Tier 3")
                    # Trace: Fallback to Tier 3
                    if emitter:
                        emitter.emit_fallback(
                            "6",
                            "tier1_pdfplumber + tier2_docling",
                            "tier3_gemini",
                            f"Both pdfplumber and Docling failed (page {page_num})",
                        )
                    return self._extract_and_save_visual(
                        pdf_path=pdf_path,
                        page_num=page_num,
                        bbox=bbox,
                        label="Table",
                        confidence=confidence,
                        report_id=report_id,
                    )

                except Exception as e:
                    # pdfplumber crashed, try Tier 2 or 3
                    logger.error(f"  pdfplumber error: {e}")
                    if block.get("docling_table_markdown"):
                        # Trace: pdfplumber crashed, fallback to Tier 2
                        if emitter:
                            emitter.emit_fallback(
                                "6",
                                "tier1_pdfplumber",
                                "tier2_docling",
                                f"pdfplumber exception: {str(e)[:100]} (page {page_num})",
                            )
                        return self._use_docling_table(
                            markdown=block["docling_table_markdown"],
                            page_num=page_num,
                            bbox=bbox,
                            confidence=confidence,
                        )
                    else:
                        # Trace: pdfplumber crashed, fallback to Tier 3
                        if emitter:
                            emitter.emit_fallback(
                                "6",
                                "tier1_pdfplumber",
                                "tier3_gemini",
                                f"pdfplumber exception, no Docling available: {str(e)[:100]} (page {page_num})",
                            )
                        return self._extract_and_save_visual(
                            pdf_path=pdf_path,
                            page_num=page_num,
                            bbox=bbox,
                            label="Table",
                            confidence=confidence,
                            report_id=report_id,
                        )

        # Non-table blocks: use standard router
        extractor_fn = self.router.get(
            label, self.text_extractor.extract
        )  # Default to text

        if extractor_fn is None:
            # Explicitly configured to skip this block type (noise elements)
            return None

        # Dispatch to extractor
        try:
            return extractor_fn(
                pdf_path=pdf_path,
                page_num=page_num,
                bbox=bbox,
                label=label,
                confidence=confidence,
                report_id=report_id,
            )

        except Exception as e:
            # --- GRANULAR FAILURE LOGGING ---
            error_msg = (
                f"EXTRACTION FAILURE: {report_id} | Page {page_num} | Label '{label}' | "
                f"BBox {bbox} | Error: {str(e)}"
            )
            logger.error(error_msg)

            # --- DEAD LETTER QUEUE: Save failed block image ---
            self._save_failed_extraction(
                report_id=report_id,
                page_num=page_num,
                label=label,
                bbox=bbox,
                pdf_path=pdf_path,
            )

            return None

    def _extract_footnote(
        self, pdf_path: str, page_num: int, bbox: List[float], **kwargs
    ) -> Optional[ExtractedContent]:
        """
        Extract footnote with number detection.
        P4-1: Delegates text extraction to TextExtractor, then overrides content_type
        and prepends footnote number if detectable.

        Args:
            pdf_path: Path to PDF document
            page_num: Page number
            bbox: Bounding box coordinates
            **kwargs: Additional parameters (label, confidence, report_id)

        Returns:
            ExtractedContent with content_type="footnote" or None if extraction failed
        """
        # Delegate to TextExtractor for base text extraction
        result = self.text_extractor.extract(pdf_path, page_num, bbox, **kwargs)
        if not result:
            return None

        content = result.content.strip()

        # Detect footnote number: "7 FSSAI standards..." or "¹ FSSAI..." or superscript
        footnote_num = None

        # Pattern 1: Plain digit at start (most common in CAG reports)
        num_match = re.match(r'^(\d{1,3})\s+', content)
        if num_match:
            footnote_num = num_match.group(1)
        else:
            # Pattern 2: Unicode superscript numbers
            sup_match = re.match(r'^([¹²³⁴⁵⁶⁷⁸⁹⁰]+)\s*', content)
            if sup_match:
                # Convert superscript to normal digits
                sup_map = str.maketrans('¹²³⁴⁵⁶⁷⁸⁹⁰', '1234567890')
                footnote_num = sup_match.group(1).translate(sup_map)

        # Override content_type to "footnote"
        result.content_type = "footnote"

        # Prefix with [Footnote X] for RAG context if number detected
        if footnote_num:
            result.content = f"[Footnote {footnote_num}] {content}"
        else:
            # No number detected, but still tag as footnote
            result.content = f"[Footnote] {content}"

        return result

    def _classify_visual_subtype(
        self, caption: str, hierarchy: Dict, layout_label: str
    ) -> str:
        """
        P4-6: Classify a visual element's subtype based on caption and context.

        Args:
            caption: Image caption text
            hierarchy: Chunk hierarchy dict
            layout_label: Docling layout label

        Returns:
            Subtype: "chart", "map", "flowchart", "diagram", "photo", "data_visualization", "unknown"
        """
        # Subtype classification keywords
        VISUAL_SUBTYPE_KEYWORDS = {
            "chart": ["chart", "graph", "trend", "bar chart", "pie chart", "line graph", "histogram"],
            "map": ["map", "geographical", "district-wise", "state-wise map", "location"],
            "flowchart": ["flow chart", "flowchart", "process flow", "workflow", "decision tree"],
            "diagram": ["diagram", "schematic", "structure", "organization", "org chart"],
            "photo": ["photograph", "photo", "image of", "construction site", "physical verification"],
            "table_as_image": ["table", "statement", "annexure"],
        }

        context = (caption + " " + " ".join(str(v) for v in hierarchy.values())).lower()

        for subtype, keywords in VISUAL_SUBTYPE_KEYWORDS.items():
            if any(kw in context for kw in keywords):
                return subtype

        # Fallback: if layout_label is "Figure" it's more likely a chart/diagram
        # If "Picture" it's more likely a photo
        if layout_label == "Figure":
            return "data_visualization"
        elif layout_label == "Picture":
            return "photo"

        return "unknown"

    def _use_docling_table(
        self,
        markdown: str,
        page_num: int,
        bbox: List[float],
        confidence: Optional[float],
    ) -> Optional[ExtractedContent]:
        """
        V2 Tier 2: Use Docling TableFormer's extracted table markdown.

        Args:
            markdown: Table markdown from Docling's export_to_markdown()
            page_num: Page number
            bbox: Bounding box coordinates
            confidence: Layout confidence

        Returns:
            ExtractedContent with table markdown and structured_data
        """
        from src.parsing_pipeline.modules.structured_table_extractor import StructuredTableExtractor

        # Generate StructuredTable JSON from markdown
        structured_extractor = StructuredTableExtractor()
        table_id = f"table_{page_num}_{int(bbox[0])}_{int(bbox[1])}"

        try:
            structured_table = structured_extractor.extract(
                markdown_table=markdown,
                table_id=table_id,
                source_chunk_id="temp",
                source_page_physical=page_num,
                source_bbox=bbox,
            )

            structured_data = structured_table.model_dump() if structured_table else None

        except Exception as e:
            logger.error(f"    Warning: Structured extraction failed for Docling table: {e}")
            structured_data = None

        return ExtractedContent(
            content_type="table_markdown",
            content=markdown,
            source_page_physical=page_num,
            source_bbox=bbox,
            model_used="docling-tableformer",
            layout_label="Table",
            layout_confidence=confidence,
            structured_data=structured_data,
        )

    def _extract_and_save_visual(
        self, pdf_path: str, page_num: int, bbox: List[float], **kwargs
    ) -> Optional[ExtractedContent]:
        """
        V2: Save visual block (Figure/Picture) as PNG for downstream Gemini extraction.
        Replaces Florence-2 captioning with simple image persistence.

        Args:
            pdf_path: Path to PDF document
            page_num: Page number
            bbox: Bounding box coordinates
            **kwargs: Additional parameters (label, confidence, report_id)

        Returns:
            ExtractedContent with image path, or None if extraction failed
        """
        from src.batch_pipeline.enrichment.gemini_visual_extractor import save_block_image

        report_id = kwargs.get("report_id", "unknown")
        label = kwargs.get("label", "Picture")

        image_path = save_block_image(
            pdf_path=pdf_path,
            page_num=page_num,
            bbox=bbox,
            output_dir="data/extraction_images/charts",
            report_id=report_id,
            block_type="chart" if label == "Figure" else "picture",
            dpi=200,
        )

        if not image_path:
            return None

        # Classify visual subtype for downstream processing
        visual_subtype = self._classify_visual_subtype(
            caption="",  # No caption yet — Gemini will generate one
            hierarchy={},
            layout_label=label,
        )

        return ExtractedContent(
            content_type="image_caption",  # Keep existing content_type for compatibility
            content=image_path,            # Store image path for Phase 10b
            source_page_physical=page_num,
            source_bbox=bbox,
            model_used="image-crop-for-gemini",
            layout_label=label,
            layout_confidence=kwargs.get("confidence"),
            structured_data={"visual_subtype": visual_subtype},
        )

    def _is_continuation_start(self, text: str) -> bool:
        """Check if text starts like a paragraph continuation."""
        if not text or len(text.strip()) < 2:
            return False
        text = text.strip()
        for pattern in self._continuation_start:
            if pattern.match(text):
                return True
        return False

    def _is_incomplete_end(self, text: str) -> bool:
        """Check if text ends incompletely (mid-sentence)."""
        if not text or len(text.strip()) < 10:
            return False
        text = text.strip()
        # Don't merge if it ends with proper sentence punctuation
        if text[-1] in ".!?:":
            # Check if it's a real sentence end, not an abbreviation
            # Abbreviations like "etc." "Dr." "No." shouldn't trigger merge
            if len(text) > 3 and text[-2].isupper():
                return True  # Likely abbreviation, could continue
            return False
        for pattern in self._incomplete_end:
            if pattern.search(text):
                return True
        return False

    def _merge_cross_page_paragraphs(
        self, content_list: List[ExtractedContent]
    ) -> List[ExtractedContent]:
        """
        PHASE 3 FIX: Merge paragraphs that are split across page boundaries.

        Detection heuristics:
        1. Last paragraph on page N ends without proper punctuation
        2. First paragraph on page N+1 starts with lowercase or continuation word
        3. Both are 'paragraph' content type

        Args:
            content_list: List of ExtractedContent objects sorted by page

        Returns:
            List with merged paragraphs
        """
        if len(content_list) < 2:
            return content_list

        # Sort by page, then by vertical position (y0 of bbox)
        sorted_content = sorted(
            content_list,
            key=lambda c: (
                c.source_page_physical,
                c.source_bbox[1] if c.source_bbox else 0,
            ),
        )

        merged = []
        skip_next = set()  # Indices to skip because they were merged
        merge_count = 0

        for i, content in enumerate(sorted_content):
            if i in skip_next:
                continue

            # Only merge paragraphs
            if content.content_type != "paragraph":
                merged.append(content)
                continue

            # Check if this paragraph should merge with the next
            if i + 1 < len(sorted_content):
                next_content = sorted_content[i + 1]

                # Merge conditions:
                # 1. Next content is on the next page
                # 2. Next content is also a paragraph
                # 3. Current ends incompletely
                # 4. Next starts like a continuation
                should_merge = (
                    next_content.source_page_physical
                    == content.source_page_physical + 1
                    and next_content.content_type == "paragraph"
                    and self._is_incomplete_end(content.content)
                    and self._is_continuation_start(next_content.content)
                )

                if should_merge:
                    # Create merged content
                    merged_text = (
                        content.content.rstrip() + " " + next_content.content.lstrip()
                    )

                    # Create new ExtractedContent with merged data
                    merged_content = ExtractedContent(
                        content_type="paragraph",
                        content=merged_text,
                        source_page_physical=content.source_page_physical,  # Keep original page
                        source_bbox=content.source_bbox,  # Keep original bbox
                        model_used=content.model_used,
                        layout_label=content.layout_label,
                        layout_confidence=min(
                            content.layout_confidence or 1.0,
                            next_content.layout_confidence or 1.0,
                        ),
                    )

                    merged.append(merged_content)
                    skip_next.add(i + 1)
                    merge_count += 1
                    continue

            # No merge needed
            merged.append(content)

        if merge_count > 0:
            logger.info(f"  Cross-page merge: Combined {merge_count} split paragraphs")

        return merged

    def extract_content(
        self,
        task: DocumentTask,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        trace_emitter=None
    ) -> DocumentTask:
        """
        Main service entry point: extract content from all layout blocks.

        PHASE 3 FIX: Now includes cross-page paragraph merging.

        Args:
            task: DocumentTask with populated layout field
            progress_callback: Optional callback function (current, total) for progress updates
            trace_emitter: Optional TraceEmitter for per-table instrumentation

        Returns:
            Updated DocumentTask with extracted_content field populated
        """
        start_time = time.time()

        # Store trace_emitter for use by _route_block
        if trace_emitter:
            self._trace_emitter = trace_emitter

        # Validation: Check for required layout data
        if not task.layout:
            task.processing_status = "failed_content_extraction"
            task.error_log.append(
                "Layout analysis data missing - cannot perform content extraction."
            )
            return task

        # Prepare PDF source
        try:
            pdf_path = self._select_pdf_source(task)
            if not pdf_path:
                raise ValueError("No valid PDF path available")
        except Exception as e:
            task.processing_status = "failed_content_extraction"
            task.error_log.append(f"PDF preparation failed: {str(e)}")
            return task

        # Process each page and block
        extracted_elements: List[ExtractedContent] = []
        total_blocks = sum(len(blocks) for blocks in task.layout.values())

        # Determine if this is a scanned PDF (for tier routing)
        is_scanned = task.classification == "scanned"

        # Log initial progress message only if no callback provided
        if not progress_callback:
            logger.info(
                f"Processing {total_blocks} layout blocks from {len(task.layout)} pages..."
            )
            if is_scanned:
                logger.info(f"  PDF type: SCANNED - will prioritize Docling TableFormer (Tier 2)")
            else:
                logger.info(f"  PDF type: NATIVE - will prioritize pdfplumber (Tier 1)")

        processed_blocks = 0
        successful_extractions = 0

        # Iterate through pages in order
        for page_num in sorted(task.layout.keys()):
            blocks = task.layout[page_num]

            for block in blocks:
                processed_blocks += 1

                # Route block to appropriate extractor
                result = self._route_block(
                    block=block,
                    pdf_path=pdf_path,
                    page_num=page_num,
                    report_id=task.report_id,
                    is_scanned=is_scanned,
                    trace_emitter=self._trace_emitter,
                )

                if result:
                    extracted_elements.append(result)
                    successful_extractions += 1

                # Progress indicator (every 10 blocks or major milestones)
                if processed_blocks % 10 == 0 or processed_blocks == total_blocks:
                    if progress_callback:
                        progress_callback(processed_blocks, total_blocks)
                    else:
                        # Fallback for backward compatibility
                        progress_pct = (processed_blocks / total_blocks) * 100
                        logger.info(
                            f"Processed {processed_blocks}/{total_blocks} blocks ({progress_pct:.1f}%)"
                        )

        # Apply cross-page paragraph merging to rejoin split paragraphs
        merged_elements = self._merge_cross_page_paragraphs(extracted_elements)

        # PHASE 2: Apply garbage filtering
        valid_content, filtered_content = self.filter_service.filter_extracted_content(
            merged_elements
        )

        # Log filtering stats
        if filtered_content:
            filter_msg = (
                f"Filtered {len(filtered_content)}/{len(merged_elements)} "
                f"garbage chunks ({len(filtered_content) / len(merged_elements) * 100:.1f}%)"
            )
            logger.info(filter_msg)
            task.error_log.append(filter_msg)

        # PHASE 2 BUG FIX: Use filtered content (not raw extracted_elements)
        task.extracted_content = valid_content

        # Calculate processing time and success rate
        processing_time = time.time() - start_time
        success_rate = (
            (successful_extractions / processed_blocks * 100)
            if processed_blocks > 0
            else 0
        )
        failed_count = processed_blocks - successful_extractions

        # Set final status based on extraction failures (not error_log which includes non-fatal warnings)
        # Bug fix: error_log contains garbage filtering messages which are normal cleanup, not failures
        if failed_count == 0 and valid_content:
            task.processing_status = "completed_content_extraction"
        elif valid_content:
            task.processing_status = "partial_content_extraction"
        else:
            task.processing_status = "failed_content_extraction"

        # Add summary to error log (even on success for metrics)
        summary_msg = (
            f"Content extraction completed: {successful_extractions}/{processed_blocks} blocks "
            f"({success_rate:.2f}% success) in {processing_time:.1f}s"
        )
        task.error_log.append(summary_msg)

        # Fix 5: Emit Phase 6 completion summary with diagnostic info
        emitter = self._trace_emitter
        if emitter and hasattr(emitter, "emit"):
            filtered_count = len(filtered_content) if filtered_content else 0

            # Emit diagnostic summary for partial status
            emitter.emit(
                "6",
                "extraction_summary",
                {
                    "total_blocks": total_blocks,
                    "processed_blocks": processed_blocks,
                    "successful_extractions": successful_extractions,
                    "failed_extractions": failed_count,
                    "filtered_garbage": filtered_count,
                    "valid_content_count": len(valid_content) if valid_content else 0,
                    "success_rate_pct": round(success_rate, 1),
                    "status": task.processing_status,
                    "has_errors": bool(task.error_log),
                },
            )

            # Red flag for high failure rate
            if failed_count > 0 and processed_blocks > 0:
                failure_rate = failed_count / processed_blocks
                if failure_rate > 0.2:  # More than 20% failures
                    emitter.emit_red_flag(
                        "6",
                        f"High content extraction failure rate ({failure_rate*100:.1f}%)",
                        {
                            "failed_count": failed_count,
                            "total_blocks": processed_blocks,
                            "failure_rate_pct": round(failure_rate * 100, 1),
                        },
                    )

        logger.info(f"Content extraction complete: {summary_msg}")
        return task

    def shutdown(self):
        """Clean up all extractor resources."""
        logger.info("Shutting down ContentExtractionService...")

        try:
            if hasattr(self.table_extractor, "shutdown"):
                self.table_extractor.shutdown()
        except Exception as e:
            logger.error(f"Warning: TableExtractor shutdown failed: {e}")

        # V2: VisualAssetExtractor removed — no Florence-2 cleanup needed
        # TextExtractor doesn't need special cleanup
        logger.info("ContentExtractionService shutdown complete.")
