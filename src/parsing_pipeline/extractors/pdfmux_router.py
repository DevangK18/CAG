"""
PdfmuxRouter: Intelligent PDF extraction routing using pdfmux.

Option D Enhancement: Wraps pdfmux for smart routing between extraction methods.
pdfmux benchmarks: 0.911 TEDS (table accuracy) vs Docling 0.887, 0.905 overall.

Key features:
- Self-healing extraction: classifies each PDF, routes to best extractor
- Automatic fallback and re-extraction on low confidence
- CPU-optimized (no GPU required)
- Integrates with existing Tier 1/2/3 pipeline
"""

import logging
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass

from src.core.data_contracts import ExtractedContent

logger = logging.getLogger(__name__)

# Lazy import pdfmux to avoid import errors if not installed
_pdfmux_available = None
_pdfmux_module = None


def _check_pdfmux_available() -> bool:
    """Check if pdfmux is installed and importable."""
    global _pdfmux_available, _pdfmux_module
    if _pdfmux_available is None:
        try:
            import pdfmux
            _pdfmux_module = pdfmux
            _pdfmux_available = True
            logger.info("pdfmux library loaded successfully")
        except ImportError:
            _pdfmux_available = False
            logger.warning(
                "pdfmux not installed. Install with: pip install pdfmux[tables]"
            )
    return _pdfmux_available


@dataclass
class PdfmuxTableResult:
    """Result from pdfmux table extraction."""
    markdown: str
    confidence: float
    extraction_method: str
    page_num: int
    bbox: List[float]
    was_rerouted: bool = False
    reroute_reason: Optional[str] = None


class PdfmuxRouter:
    """
    Intelligent routing layer for PDF extraction using pdfmux.

    Replaces manual Tier 1/2/3 routing with pdfmux's self-healing pipeline:
    - Classifies PDF type (native vs scanned)
    - Routes tables to optimal extractor (pdfplumber, Docling, or OCR)
    - Audits extraction confidence and re-routes on failure
    - Provides unified interface for table extraction
    """

    def __init__(
        self,
        quality: str = "standard",
        min_confidence: float = 0.85,
        on_low_confidence: str = "reroute",
        trace_emitter=None,
    ):
        """
        Initialize pdfmux router.

        Args:
            quality: Extraction quality level ("fast", "standard", "high")
            min_confidence: Minimum confidence to accept extraction
            on_low_confidence: Action for low confidence ("reroute" or "flag")
            trace_emitter: Optional TraceEmitter for instrumentation
        """
        self.quality = quality
        self.min_confidence = min_confidence
        self.on_low_confidence = on_low_confidence
        self._trace_emitter = trace_emitter
        self._initialized = False
        self._pdfmux = None

        # Track routing statistics
        self._stats = {
            "total_extractions": 0,
            "pdfmux_routed": 0,
            "reroutes": 0,
            "fallback_to_legacy": 0,
        }

    def _ensure_initialized(self) -> bool:
        """Lazy initialization of pdfmux."""
        if self._initialized:
            return self._pdfmux is not None

        self._initialized = True

        if not _check_pdfmux_available():
            logger.warning("PdfmuxRouter: pdfmux not available, will use legacy routing")
            return False

        self._pdfmux = _pdfmux_module
        logger.info(
            f"PdfmuxRouter initialized: quality={self.quality}, "
            f"min_confidence={self.min_confidence}"
        )
        return True

    def is_available(self) -> bool:
        """Check if pdfmux routing is available."""
        return self._ensure_initialized()

    def extract_table(
        self,
        pdf_path: str,
        page_num: int,
        bbox: List[float],
        is_scanned: bool = False,
        docling_markdown: Optional[str] = None,
        report_id: str = "unknown",
    ) -> Optional[PdfmuxTableResult]:
        """
        Extract table using pdfmux intelligent routing.

        This method routes the table extraction through pdfmux's self-healing
        pipeline, which:
        1. Classifies the page content
        2. Routes to optimal extractor (pdfplumber for native, Docling for complex)
        3. Audits the result and re-routes if confidence is low

        Args:
            pdf_path: Path to PDF file
            page_num: Page number (0-indexed)
            bbox: Bounding box [x0, y0, x1, y1]
            is_scanned: Whether the PDF is scanned (from triage)
            docling_markdown: Pre-extracted Docling markdown (if available)
            report_id: Report identifier for logging

        Returns:
            PdfmuxTableResult with extracted markdown and metadata, or None if failed
        """
        self._stats["total_extractions"] += 1

        if not self._ensure_initialized():
            self._stats["fallback_to_legacy"] += 1
            return None  # Signal to caller to use legacy extraction

        try:
            # Use pdfmux v1.x extract_json API for table extraction
            # pdfmux internally routes to best extractor based on content
            result = self._pdfmux.extract_json(
                pdf_path,
                quality=self.quality,
            )

            if not result:
                logger.debug(
                    f"pdfmux: No result for {report_id}"
                )
                return None

            # pdfmux v1.x: tables are at top level, not inside pages
            # Filter tables by page number (pdfmux uses 1-indexed pages)
            all_tables = result.get("tables", [])
            page_tables = [
                t for t in all_tables
                if t.get("page") == page_num + 1  # Convert 0-indexed to 1-indexed
            ]

            if not page_tables:
                logger.debug(
                    f"pdfmux: No tables found on page {page_num} of {report_id}"
                )
                return None

            # Find table matching our bbox (pdfmux may return multiple per page)
            best_table = self._find_matching_table(page_tables, bbox, page_num)

            if not best_table:
                logger.debug(
                    f"pdfmux: No table matching bbox {bbox} on page {page_num}"
                )
                return None

            # Extract confidence from document level (page-level not always available)
            confidence = result.get("confidence", 0.9)

            # Convert ExtractedTable dict to markdown
            markdown = self._table_to_markdown(best_table)
            extractor = result.get("extractor", "auto")
            extraction_method = f"pdfmux-{extractor}"

            self._stats["pdfmux_routed"] += 1

            # Check confidence threshold
            was_rerouted = False
            reroute_reason = None

            if confidence < self.min_confidence:
                if self.on_low_confidence == "reroute" and docling_markdown:
                    # Use Docling markdown as fallback
                    logger.info(
                        f"pdfmux: Low confidence ({confidence:.2f}), "
                        f"rerouting to Docling for page {page_num}"
                    )
                    markdown = docling_markdown
                    extraction_method = "pdfmux-rerouted-docling"
                    was_rerouted = True
                    reroute_reason = f"confidence {confidence:.2f} < {self.min_confidence}"
                    self._stats["reroutes"] += 1
                else:
                    # Flag but accept
                    logger.warning(
                        f"pdfmux: Low confidence ({confidence:.2f}) on page {page_num}, "
                        f"flagging for review"
                    )

            # Emit trace decision if available
            if self._trace_emitter:
                self._trace_emitter.emit_decision(
                    "6",
                    "pdfmux_table_routing",
                    extraction_method,
                    ["pdfmux-auto", "pdfmux-rerouted-docling", "legacy-tier1", "legacy-tier2"],
                    f"Page {page_num}, confidence={confidence:.2f}, rerouted={was_rerouted}",
                )

            # Get bbox from table if available
            table_bbox = best_table.get("bbox")
            result_bbox = list(table_bbox) if table_bbox else bbox

            return PdfmuxTableResult(
                markdown=markdown,
                confidence=confidence,
                extraction_method=extraction_method,
                page_num=page_num,
                bbox=result_bbox,
                was_rerouted=was_rerouted,
                reroute_reason=reroute_reason,
            )

        except Exception as e:
            logger.error(f"pdfmux extraction failed on page {page_num}: {e}")
            self._stats["fallback_to_legacy"] += 1

            if self._trace_emitter:
                self._trace_emitter.emit_fallback(
                    "6",
                    "pdfmux",
                    "legacy_extraction",
                    f"pdfmux exception: {str(e)[:100]}",
                )

            return None  # Signal to caller to use legacy extraction

    def _table_to_markdown(self, table: Dict[str, Any]) -> str:
        """
        Convert pdfmux ExtractedTable dict to markdown format.

        Args:
            table: Dict with 'headers', 'rows', 'label' keys

        Returns:
            Markdown table string
        """
        headers = table.get("headers", [])
        rows = table.get("rows", [])
        label = table.get("label", "")

        if not headers and not rows:
            return ""

        lines = []

        # Add label if present
        if label:
            lines.append(f"**{label}**\n")

        # Build header row
        if headers:
            lines.append("| " + " | ".join(str(h) for h in headers) + " |")
            lines.append("| " + " | ".join("---" for _ in headers) + " |")
        elif rows:
            # No headers, use first row length for separator
            num_cols = len(rows[0]) if rows else 0
            lines.append("| " + " | ".join("---" for _ in range(num_cols)) + " |")

        # Build data rows
        for row in rows:
            lines.append("| " + " | ".join(str(cell) for cell in row) + " |")

        return "\n".join(lines)

    def _find_matching_table(
        self,
        tables: List[Dict[str, Any]],
        target_bbox: List[float],
        page_num: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Find the table that best matches the target bounding box.

        pdfmux v1.x tables may not have bbox info. In that case, we use
        heuristics like table size (rows * cols) to pick the best match.

        Args:
            tables: List of table dicts from pdfmux (v1.x API), pre-filtered by page
            target_bbox: Target bounding box [x0, y0, x1, y1]
            page_num: Page number (for logging)

        Returns:
            Best matching table dict or None
        """
        if not tables:
            return None

        # If only one table on this page, return it
        if len(tables) == 1:
            return tables[0]

        best_match = None
        best_iou = 0.0
        best_size = 0

        for table in tables:
            # Try bbox matching first (pdfmux may include bbox)
            table_bbox = table.get("bbox")

            if table_bbox and target_bbox:
                iou = self._calculate_iou(target_bbox, list(table_bbox))
                if iou > best_iou:
                    best_iou = iou
                    best_match = table
            else:
                # No bbox - use table size as heuristic (larger table = more likely match)
                rows = table.get("rows", [])
                headers = table.get("headers", [])
                table_size = len(rows) * max(len(headers), len(rows[0]) if rows else 0)
                if table_size > best_size:
                    best_size = table_size
                    if best_match is None or best_iou == 0.0:
                        best_match = table

        # Return best IoU match if significant, otherwise best size match
        if best_iou > 0.5:
            return best_match
        elif best_match:
            return best_match

        return tables[0] if tables else None

    def _calculate_iou(self, bbox1: List[float], bbox2: List[float]) -> float:
        """Calculate Intersection over Union for two bounding boxes."""
        x1 = max(bbox1[0], bbox2[0])
        y1 = max(bbox1[1], bbox2[1])
        x2 = min(bbox1[2], bbox2[2])
        y2 = min(bbox1[3], bbox2[3])

        if x2 < x1 or y2 < y1:
            return 0.0

        intersection = (x2 - x1) * (y2 - y1)
        area1 = (bbox1[2] - bbox1[0]) * (bbox1[3] - bbox1[1])
        area2 = (bbox2[2] - bbox2[0]) * (bbox2[3] - bbox2[1])
        union = area1 + area2 - intersection

        return intersection / union if union > 0 else 0.0

    def get_stats(self) -> Dict[str, int]:
        """Get routing statistics."""
        return self._stats.copy()

    def reset_stats(self):
        """Reset routing statistics."""
        self._stats = {
            "total_extractions": 0,
            "pdfmux_routed": 0,
            "reroutes": 0,
            "fallback_to_legacy": 0,
        }


def create_pdfmux_router(config: Dict[str, Any], trace_emitter=None) -> Optional[PdfmuxRouter]:
    """
    Factory function to create PdfmuxRouter from config.

    Args:
        config: Configuration dict (from parsing_config.yaml content_extraction.pdfmux)
        trace_emitter: Optional TraceEmitter

    Returns:
        PdfmuxRouter instance or None if disabled
    """
    if not config.get("enabled", False):
        logger.info("pdfmux routing disabled in config")
        return None

    return PdfmuxRouter(
        quality=config.get("quality", "standard"),
        min_confidence=config.get("min_confidence", 0.85),
        on_low_confidence=config.get("on_low_confidence", "reroute"),
        trace_emitter=trace_emitter,
    )
