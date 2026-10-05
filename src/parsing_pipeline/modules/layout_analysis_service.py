# CAG/services/parsing_pipeline/src/modules/layout_analysis_service.py

import logging
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

import fitz  # PyMuPDF, for page count

from docling.document_converter import DocumentConverter, PdfFormatOption

if TYPE_CHECKING:
    from src.parsing_pipeline.instrumentation import TraceEmitter
from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
from docling.datamodel.base_models import InputFormat

from src.core.data_contracts import DocumentTask
from src.parsing_pipeline.modules.captions import parse_caption
from src.parsing_pipeline.modules.structured_table_extractor import (
    is_markdown_separator,
    split_markdown_cells,
)
from src.parsing_pipeline.config import get_config, LayoutAnalysisConfig

logger = logging.getLogger(__name__)

# A markdown table separator row: only pipes, dashes, colons and spaces, with a dash
SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")


def normalize_table_markdown(markdown: str) -> str:
    """
    Collapse the space padding Docling adds to align columns (B-6-04).

    export_to_markdown pads every cell to its column's widest cell, so one long
    cell fills the table with hundreds of spaces.
    """
    lines = []
    for line in markdown.split("\n"):
        if "|" in line:
            if SEPARATOR_RE.match(line):
                cells = line.strip().strip("|").split("|")
                line = "|" + "|".join(" --- " for _ in cells) + "|"
            else:
                line = re.sub(r" {2,}", " ", line).rstrip()
        lines.append(line)
    return "\n".join(lines)


class LayoutAnalysisService:
    """
    Service to perform AI-powered document layout analysis using Docling.
    Updated for Docling v2 compatibility (Provenance & Coordinate systems).
    """

    def __init__(self, config: Optional[LayoutAnalysisConfig] = None):
        """
        Initialize Docling with configuration.

        Args:
            config: LayoutAnalysisConfig instance (default: load from global config)
        """
        # Load from config if not provided
        if config is None:
            config = get_config().layout

        self.table_min_non_empty_cells = config.table_min_non_empty_cells
        self.conversion_timeout = config.conversion_timeout
        self.conversion_timeout_per_page = config.conversion_timeout_per_page

        # Auto-detect accelerator device if set to "auto"
        self.accelerator_device = self._resolve_accelerator_device(config.accelerator_device)

        # Parse TableFormerMode from string
        tableformer_mode = (
            TableFormerMode.ACCURATE if config.tableformer_mode == "ACCURATE"
            else TableFormerMode.FAST
        )

        logger.info("Initializing Docling DocumentConverter...")

        # Configure pipeline options
        # We allow Docling to handle model downloading automatically via HF_HOME
        # V2: Enable TableFormer with configured mode for table detection
        pipeline_options = PdfPipelineOptions(
            accelerator_options={"device": self.accelerator_device},
            do_layout_analysis=True,
            generate_parsed_pages=True,  # Critical for coordinate conversion
            do_ocr=False,  # You handle OCR in Phase 3
            do_table_structure=True,  # Required for high-quality table blocks
        )
        pipeline_options.table_structure_options.mode = tableformer_mode
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

    def _resolve_accelerator_device(self, device: str) -> str:
        """Resolve 'auto' device to actual accelerator (cuda > mps > cpu)."""
        if device != "auto":
            return device

        # Try CUDA first (NVIDIA GPU)
        try:
            import torch
            if torch.cuda.is_available():
                logger.info(f"🚀 GPU detected: {torch.cuda.get_device_name(0)} - using CUDA")
                return "cuda"
        except ImportError:
            pass

        # Try MPS (Apple Silicon)
        try:
            import torch
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                logger.info("🚀 Apple Silicon detected - using MPS")
                return "mps"
        except ImportError:
            pass

        # Fallback to CPU
        logger.info("Using CPU for layout analysis (no GPU detected)")
        return "cpu"

    def analyze_layout(
        self,
        task: DocumentTask,
        trace_emitter: Optional["TraceEmitter"] = None,
    ) -> DocumentTask:
        """Analyze the full document layout using the DocumentConverter."""
        # Use no-op emitter if none provided
        if trace_emitter is None:
            from src.parsing_pipeline.instrumentation import get_noop_emitter
            trace_emitter = get_noop_emitter()

        pdf_path = self._get_pdf_path(task)
        if not pdf_path:
            task.error_log.append("PDF path not available for layout analysis.")
            task.processing_status = "failed_layout"
            trace_emitter.set_phase_status("5", "failed")
            return task

        with trace_emitter.phase_timer("5"):
            try:
                # Log before conversion starts (helps debug hangs)
                import os
                pdf_size_mb = os.path.getsize(pdf_path) / (1024 * 1024)
                with fitz.open(pdf_path) as pdf:
                    page_count = pdf.page_count
                timeout = max(self.conversion_timeout, page_count * self.conversion_timeout_per_page)
                logger.info(
                    f"[{task.report_id}] Starting Docling conversion... "
                    f"(PDF: {pdf_size_mb:.1f} MB, {page_count} pages, timeout: {timeout}s)"
                )

                # Run the conversion with timeout (prevents CI hangs on large PDFs)
                import time
                start_time = time.time()

                # Use ThreadPoolExecutor with timeout to prevent indefinite hangs
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(self.converter.convert, source=pdf_path)
                    try:
                        conversion_result = future.result(timeout=timeout)
                    except FuturesTimeoutError:
                        elapsed = time.time() - start_time
                        error_msg = (
                            f"Docling conversion timed out after {elapsed:.1f}s "
                            f"(limit: {timeout}s)"
                        )
                        logger.error(f"[{task.report_id}] {error_msg}")
                        task.error_log.append(error_msg)
                        task.processing_status = "failed_layout"
                        trace_emitter.emit_error("5", error_msg)
                        trace_emitter.set_phase_status("5", "failed")
                        return task

                elapsed = time.time() - start_time
                docling_doc = conversion_result.document
                logger.info(
                    f"[{task.report_id}] Docling conversion complete in {elapsed:.1f}s"
                )

                # Convert to our standard format
                all_blocks = self._convert_docling_doc_to_standard_format(docling_doc)

                if not all_blocks:
                    logger.warning(
                        f"⚠️ Docling returned 0 blocks for {task.report_id}. Check model or PDF."
                    )
                    trace_emitter.emit_red_flag(
                        "5",
                        "Docling returned 0 blocks",
                        {"report_id": task.report_id, "pdf_path": pdf_path},
                    )

                task.layout = self._validate_and_sort_results(all_blocks)
                task.processing_status = "layout_complete"

                block_count = sum(len(b) for b in task.layout.values())
                task.error_log.append(
                    f"Layout analysis completed: {block_count} blocks detected."
                )

                # Calculate label distribution for tracing
                label_distribution = {}
                for page_blocks in task.layout.values():
                    for block in page_blocks:
                        label = block.get("label", "unknown")
                        label_distribution[label] = label_distribution.get(label, 0) + 1

                # Emit I/O and decision info
                trace_emitter.emit_io(
                    "5",
                    {"pdf_path": pdf_path, "accelerator": self.accelerator_device},
                    {
                        "total_blocks": block_count,
                        "pages_with_blocks": len(task.layout),
                        "label_distribution": label_distribution,
                    },
                )

                trace_emitter.emit_decision(
                    "5",
                    "docling_config",
                    f"tableformer={self.accelerator_device}",
                    ["cpu", "mps", "cuda"],
                    "Docling labels kept; items carry no layout score",
                )

                trace_emitter.set_phase_status("5", "success")

            except Exception as e:
                task.error_log.append(f"Layout analysis failed: {str(e)}")
                task.processing_status = "failed_layout"
                logger.exception(f"Critical error in layout analysis for {task.report_id}")
                trace_emitter.emit_error("5", str(e))
                trace_emitter.set_phase_status("5", "failed")

        return task

    def _get_pdf_path(self, task: DocumentTask) -> Optional[str]:
        """Select the correct PDF path to use (OCR'd or original)."""
        if task.ocred_pdf_path and Path(task.ocred_pdf_path).exists():
            return task.ocred_pdf_path
        if task.local_pdf_path and Path(task.local_pdf_path).exists():
            return task.local_pdf_path
        return None

    # Docling v2 keeps the element type in item.label (a DocItemLabel); the Python
    # class is TextItem for captions and footnotes, so the class name is not enough
    LABEL_MAP = {
        "page_header": "Page-header",
        "page_footer": "Page-footer",
        "section_header": "Section-header",
        "title": "Title",
        "text": "Text",
        "paragraph": "Text",
        "reference": "Text",
        "code": "Text",
        "formula": "Text",
        "handwritten_text": "Text",
        "list_item": "List-item",
        "footnote": "Footnote",
        "caption": "Caption",
        "table": "Table",
        "document_index": "Table",
        "picture": "Picture",
        "chart": "Picture",
    }

    @staticmethod
    def _label_value(item) -> str:
        label = getattr(item, "label", None)
        return getattr(label, "value", None) or str(label or type(item).__name__)

    @staticmethod
    def _resolve_texts(doc, refs) -> List[tuple]:
        """(self_ref, text) for caption/footnote references bound to a table or picture."""
        out = []
        for ref in refs or []:
            try:
                target = ref.resolve(doc)
            except Exception:
                continue
            text = (getattr(target, "text", "") or "").strip()
            if text:
                out.append((getattr(target, "self_ref", None), text))
        return out

    def _box_of(self, doc, self_ref: Optional[str]) -> Optional[List]:
        """[0-based page, top-left bbox] of an item's first provenance, so Phase 6 can
        re-read a bound caption or footnote from the PDF."""
        item = self._items.get(self_ref) if self_ref else None
        if item is None or not getattr(item, "prov", None):
            return None
        prov = item.prov[0]
        page_item = doc.pages.get(prov.page_no)
        if not page_item or not hasattr(prov.bbox, "to_top_left_origin"):
            return None
        tl = prov.bbox.to_top_left_origin(page_item.size.height)
        return [prov.page_no - 1, [tl.l, tl.t, tl.r, tl.b]]

    def _nearer_visual(self, ref: Optional[str], owner: str, visual_boxes: List[tuple], doc) -> bool:
        """True when another table or picture on the caption's page is nearer to it than
        its owner. Docling sometimes binds the caption printed just above the next table
        to the table above it."""
        box = self._box_of(doc, ref)
        if box is None:
            return False
        page, (_, top, _, bottom) = box
        gaps = {
            other_ref: max(other[1][1] - bottom, top - other[1][3], 0)
            for other_ref, other in visual_boxes
            if other is not None and other[0] == page
        }
        if owner not in gaps:
            return False
        return any(gap < gaps[owner] for other_ref, gap in gaps.items() if other_ref != owner)

    def _convert_docling_doc_to_standard_format(self, doc) -> Dict[int, List[Dict]]:
        """Convert the rich DoclingDocument object into our pipeline's layout format."""
        all_blocks: Dict[int, List[Dict]] = {}
        # Captions and footnotes Docling bound to a table or picture. A bound "caption"
        # is only trusted when it reads like one (Docling sometimes binds a running
        # header, "Report No. 8 of 2025") and no other table or picture is nearer to it
        bound: Dict[str, str] = {}
        bindings: Dict[str, tuple] = {}
        self._items = {getattr(item, "self_ref", None): item for item, _ in doc.iterate_items()}
        owners = [
            item
            for item, _ in doc.iterate_items()
            if self._label_value(item) in ("table", "document_index", "picture", "chart")
        ]
        visual_boxes = [(getattr(item, "self_ref", ""), self._box_of(doc, getattr(item, "self_ref", None)))
                        for item in owners]
        for item in owners:
            owner = getattr(item, "self_ref", "")
            captions = [
                (ref, text)
                for ref, text in self._resolve_texts(doc, getattr(item, "captions", None))
                if parse_caption(text) and not self._nearer_visual(ref, owner, visual_boxes, doc)
            ]
            footnotes = self._resolve_texts(doc, getattr(item, "footnotes", None))
            bindings[owner] = (captions, footnotes)
            for ref, _text in captions + footnotes:
                if ref:
                    bound[ref] = owner

        for item, _ in doc.iterate_items():
            # Skip items without provenance (geometry)
            if not hasattr(item, "prov") or not item.prov:
                continue

            label_value = self._label_value(item)
            mapped_label = self.LABEL_MAP.get(label_value, "Text")
            self_ref = getattr(item, "self_ref", None)

            # Every provenance becomes a block: an item continued in another column
            # or on the next page keeps its second part (B-5-03)
            for prov_index, prov in enumerate(item.prov):
                page_no_1based = prov.page_no
                page_idx = page_no_1based - 1  # 0-based for PyMuPDF
                page_item = doc.pages.get(page_no_1based)
                if not page_item:
                    continue

                # Bottom-left -> top-left origin [x0, y0, x1, y1] for PyMuPDF
                if hasattr(prov.bbox, "to_top_left_origin"):
                    tl_bbox = prov.bbox.to_top_left_origin(page_item.size.height)
                    bbox = [tl_bbox.l, tl_bbox.t, tl_bbox.r, tl_bbox.b]
                else:
                    b = prov.bbox
                    bbox = [b.l, b.t, b.r, b.b]

                # Docling v2 items carry no layout score, so there is no confidence to
                # filter on; None says so instead of a made-up 1.0 (B-5-02)
                block = {
                    "bbox": bbox,
                    "label": mapped_label,
                    "confidence": None,
                    "content_type": label_value,
                    "docling_label": label_value,
                    "docling_ref": self_ref,
                    "prov_index": prov_index,
                }
                if self_ref in bound:
                    block["bound_to"] = bound[self_ref]

                if prov_index == 0 and self_ref in bindings:
                    captions, footnotes = bindings[self_ref]
                    if captions:
                        block["docling_caption"] = " ".join(t for _, t in captions)
                        block["docling_caption_boxes"] = [
                            box for ref, _ in captions for box in [self._box_of(doc, ref)] if box
                        ]
                    if footnotes:
                        block["docling_footnotes"] = [t for _, t in footnotes]
                        block["docling_footnote_boxes"] = [self._box_of(doc, ref) for ref, _ in footnotes]

                block["docling_table_available"] = False
                if mapped_label == "Table" and prov_index == 0 and hasattr(item, "export_to_markdown"):
                    self._attach_table_markdown(item, doc, block, page_no_1based)

                all_blocks.setdefault(page_idx, []).append(block)

        return all_blocks

    def _attach_table_markdown(self, item, doc, block: Dict, page_no_1based: int) -> None:
        """Docling TableFormer markdown for Tier 2, behind the non-empty-cell gate."""
        try:
            table_markdown = item.export_to_markdown(doc)
        except Exception as e:
            # If export fails, we'll fall back to pdfplumber or Gemini
            logger.warning(f"Docling table export failed on page {page_no_1based}: {e}")
            return
        table_markdown = normalize_table_markdown(table_markdown or "")
        if not table_markdown.strip():
            return
        non_empty_cells = self._count_non_empty_cells(table_markdown)
        if non_empty_cells >= self.table_min_non_empty_cells:
            block["docling_table_markdown"] = table_markdown
            block["docling_table_available"] = True
        else:
            logger.debug(
                f"Docling table on page {page_no_1based} rejected: "
                f"only {non_empty_cells} non-empty cells (min: {self.table_min_non_empty_cells})"
            )

    def _map_docling_label(self, docling_label: str) -> str:
        """Map a DocItemLabel value (or a legacy class name) to our router keys."""
        legacy = {"SectionHeader": "section_header", "ListItem": "list_item", "PageHeader": "page_header",
                  "PageFooter": "page_footer", "Figure": "picture"}
        key = legacy.get(docling_label, docling_label).lower()
        return self.LABEL_MAP.get(key, "Text")

    def _count_non_empty_cells(self, markdown_table: str) -> int:
        """
        Count non-empty cells in a markdown table.

        Used as quality gate: tables with <3 non-empty cells are rejected.
        """
        non_empty_count = 0

        for line in markdown_table.strip().split("\n"):
            # Separator lines (|---|---| or | --- | :---: |) are never content
            if is_markdown_separator(line):
                continue
            non_empty_count += sum(1 for cell in split_markdown_cells(line) if cell.strip())

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
