# CAG/services/parsing_pipeline/src/modules/layout_analysis_service.py

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional

from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
from docling.datamodel.base_models import InputFormat

from src.core.data_contracts import DocumentTask

logger = logging.getLogger(__name__)


class LayoutAnalysisService:
    """
    Service to perform AI-powered document layout analysis using Docling.
    Updated for Docling v2 compatibility (Provenance & Coordinate systems).
    """

    def __init__(self, confidence_threshold: float = 0.65):
        """
        Initialize Docling with CPU-forced options.
        Note: Lowered default threshold to 0.65 to ensure we catch more items.
        """
        self.confidence_threshold = confidence_threshold

        logger.info("Initializing Docling DocumentConverter...")

        # Configure pipeline options
        # We allow Docling to handle model downloading automatically via HF_HOME
        # V2: Enable TableFormer ACCURATE mode for better scanned PDF table detection
        pipeline_options = PdfPipelineOptions(
            accelerator_options={"device": "cpu"},
            do_layout_analysis=True,
            generate_parsed_pages=True,  # Critical for coordinate conversion
            do_ocr=False,  # You handle OCR in Phase 3
            do_table_structure=True,  # Required for high-quality table blocks
        )
        pipeline_options.table_structure_options.mode = TableFormerMode.ACCURATE
        pipeline_options.table_structure_options.do_cell_matching = True

        try:
            self.converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
                }
            )
            logger.info("✅ Successfully initialized Docling DocumentConverter.")
        except Exception as e:
            logger.error(f"FATAL: Failed to initialize DocumentConverter: {e}")
            raise RuntimeError("Could not initialize Docling.") from e

    def analyze_layout(self, task: DocumentTask) -> DocumentTask:
        """Analyze the full document layout using the DocumentConverter."""
        pdf_path = self._get_pdf_path(task)
        if not pdf_path:
            task.error_log.append("PDF path not available for layout analysis.")
            task.processing_status = "failed_layout"
            return task

        try:
            # Run the conversion
            conversion_result = self.converter.convert(source=pdf_path)
            docling_doc = conversion_result.document

            # Convert to our standard format
            all_blocks = self._convert_docling_doc_to_standard_format(docling_doc)

            if not all_blocks:
                logger.warning(
                    f"⚠️ Docling returned 0 blocks for {task.report_id}. Check model or PDF."
                )

            task.layout = self._validate_and_sort_results(all_blocks)
            task.processing_status = "layout_complete"

            block_count = sum(len(b) for b in task.layout.values())
            task.error_log.append(
                f"Layout analysis completed: {block_count} blocks detected."
            )

        except Exception as e:
            task.error_log.append(f"Layout analysis failed: {str(e)}")
            task.processing_status = "failed_layout"
            logger.exception(f"Critical error in layout analysis for {task.report_id}")

        return task

    def _get_pdf_path(self, task: DocumentTask) -> Optional[str]:
        """Select the correct PDF path to use (OCR'd or original)."""
        if task.ocred_pdf_path and Path(task.ocred_pdf_path).exists():
            return task.ocred_pdf_path
        if task.local_pdf_path and Path(task.local_pdf_path).exists():
            return task.local_pdf_path
        return None

    def _convert_docling_doc_to_standard_format(self, doc) -> Dict[int, List[Dict]]:
        """Convert the rich DoclingDocument object into our pipeline's layout format."""
        all_blocks: Dict[int, List[Dict]] = {}

        # Iterate over all items in the document
        for item, _ in doc.iterate_items():
            # 1. Validation: Skip items without provenance (geometry)
            if not hasattr(item, "prov") or not item.prov:
                continue

            # 2. Extract Page Number (Docling is 1-based, we want 0-based for PyMuPDF)
            # We use the first provenance item as the primary location
            prov = item.prov[0]
            page_no_1based = prov.page_no
            page_idx = page_no_1based - 1  # Convert to 0-based index

            # 3. Coordinate Conversion (Bottom-Left -> Top-Left)
            # Get the page size to flip the Y-axis if necessary
            page_item = doc.pages.get(page_no_1based)
            if not page_item:
                continue

            page_height = page_item.size.height

            # Convert bbox to Top-Left origin [x0, y0, x1, y1] for PyMuPDF compatibility
            # Docling v2 BoundingBox usually has .to_top_left_origin()
            if hasattr(prov.bbox, "to_top_left_origin"):
                tl_bbox = prov.bbox.to_top_left_origin(page_height)
                bbox = [tl_bbox.l, tl_bbox.t, tl_bbox.r, tl_bbox.b]
            else:
                # Fallback: assume it's already list-like or simple object
                # This path is risky if origin is BL, but serves as safety
                b = prov.bbox
                bbox = [b.l, b.t, b.r, b.b]

            # 4. Filter by Confidence
            # Some items might not have a score, default to high confidence if missing
            confidence = getattr(item, "score", 1.0)
            if confidence is None:
                confidence = 1.0

            if float(confidence) < self.confidence_threshold:
                continue

            # 5. Map Label
            original_label = type(item).__name__.replace("Item", "")
            mapped_label = self._map_docling_label(original_label)

            block = {
                "bbox": bbox,
                "label": mapped_label,
                "confidence": float(confidence),
                "content_type": original_label,
            }

            # V2: Extract Docling TableFormer data (Tier 2 in 3-tier strategy)
            if original_label == "Table" and hasattr(item, "export_to_markdown"):
                try:
                    table_markdown = item.export_to_markdown(doc)
                    if table_markdown and len(table_markdown.strip()) > 0:
                        # Quality gate: Reject tables with <3 non-empty cells
                        non_empty_cells = self._count_non_empty_cells(table_markdown)
                        if non_empty_cells >= 3:
                            block["docling_table_markdown"] = table_markdown
                            block["docling_table_available"] = True
                        else:
                            logger.debug(
                                f"Docling table on page {page_no_1based} rejected: "
                                f"only {non_empty_cells} non-empty cells (min: 3)"
                            )
                            block["docling_table_available"] = False
                    else:
                        block["docling_table_available"] = False
                except Exception as e:
                    # If export fails, we'll fall back to pdfplumber or Gemini
                    logger.warning(
                        f"Docling table export failed on page {page_no_1based}: {e}"
                    )
                    block["docling_table_available"] = False
            else:
                block["docling_table_available"] = False

            if page_idx not in all_blocks:
                all_blocks[page_idx] = []
            all_blocks[page_idx].append(block)

        return all_blocks

    def _map_docling_label(self, docling_label: str) -> str:
        """Map the docling item type name to our router keys."""
        mapping = {
            "PageHeader": "Page-header",
            "PageFooter": "Page-footer",
            "SectionHeader": "Section-header",
            "Title": "Title",
            "Text": "Text",
            "Table": "Table",
            "Figure": "Figure",
            "Picture": "Picture",
            "ListItem": "List-item",
            "Footnote": "Footnote",
            "Caption": "Text",
            "Code": "Text",
            "Formula": "Text",
        }
        return mapping.get(docling_label, "Text")

    def _count_non_empty_cells(self, markdown_table: str) -> int:
        """
        Count non-empty cells in a markdown table.

        Used as quality gate: tables with <3 non-empty cells are rejected.
        """
        non_empty_count = 0

        for line in markdown_table.strip().split("\n"):
            # Skip separator lines (e.g., |---|---|)
            if re.match(r"^\s*\|[\s\-:]+\|\s*$", line):
                continue

            # Extract cell contents between pipes
            cells = [cell.strip() for cell in line.split("|")]
            # Filter empty cells (first/last are often empty due to leading/trailing |)
            cells = [c for c in cells if c]

            # Count non-empty cells
            non_empty_count += sum(1 for cell in cells if cell and cell.strip())

        return non_empty_count

    def _validate_and_sort_results(
        self, raw_results: Dict[int, List[Dict]]
    ) -> Dict[int, List[Dict]]:
        """Sorts blocks on each page by reading order (Top-Down, Left-Right)."""
        sorted_results = {}
        for page_num, blocks in raw_results.items():
            # Sort by Y0 (top) then X0 (left)
            sorted_blocks = sorted(blocks, key=lambda b: (b["bbox"][1], b["bbox"][0]))
            sorted_results[page_num] = sorted_blocks
        return sorted_results
