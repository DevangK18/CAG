"""
ScaffoldingService: Document structure extraction for CAG RAG Pipeline.
Builds ToC and page mappings from PDF documents.

PHASE 1 FIXES IMPLEMENTED:
- Fix 1.1: TOC validation with reject/accept patterns to filter false positives
- Fix 1.2: TOC rejection logging to logs/rejected_toc.log with alert threshold
- Fix 1.3: Lower embedded TOC threshold from 5 to 3 entries
- Fix 1.4: Clean TOC titles by removing trailing page numbers

PHASE 2 FIXES IMPLEMENTED (2025-12-23):
- Fix 2.1: Structural checks BEFORE pattern matching (pipes, number density)
- Fix 2.2: Enhanced reject patterns for OCR'd table content
- Fix 2.3: Pipe character detection for table data
- Fix 2.4: Multi-number sequence detection
- Fix 2.5: Year-range data patterns
- Fix 2.6: Comma-formatted number sequences
- Fix 2.7: Devanagari script (Hindi OCR) detection
- Fix 2.8: Accept patterns now require exact match (no trailing content)
"""

from pathlib import Path
import fitz  # PyMuPDF
from typing import TYPE_CHECKING, Any, List, Tuple, Dict, Optional
from dataclasses import dataclass
import numpy as np
from collections import Counter
import re
import logging
from datetime import datetime

from src.core.data_contracts import DocumentTask, TOCQualityMetrics
from src.parsing_pipeline.modules.toc_table_parser import TOCTableParser, TOCEntry
from src.parsing_pipeline.config import get_config, ScaffoldingConfig

if TYPE_CHECKING:
    from src.parsing_pipeline.instrumentation import TraceEmitter

logger = logging.getLogger(__name__)


# =============================================================================
# PHASE 1: TOC REJECTION LOGGER
# =============================================================================


@dataclass
class RejectedTOCEntry:
    """Tracks a rejected TOC entry for logging and review."""

    report_id: str
    page_num: int
    text: str
    rejection_reason: str
    pattern_matched: Optional[str] = None
    font_size: Optional[float] = None
    timestamp: Optional[str] = None


class TOCRejectionLogger:
    """
    Logs rejected TOC entries for review and raises alerts if rejection rate is high.

    Purpose: During pilot phase, we need to ensure we're not accidentally
    rejecting legitimate chapter headings. This logger:
    1. Writes all rejections to logs/rejected_toc.log
    2. Raises alerts if rejection rate > threshold
    3. Provides summary statistics per report
    """

    ALERT_THRESHOLD = 0.25  # Alert if >25% of candidates rejected

    def __init__(self, log_dir: str = "logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / "rejected_toc.log"
        self.rejected_entries: List[RejectedTOCEntry] = []
        self.accepted_count = 0
        self.total_candidates = 0
        self.current_report_id: Optional[str] = None

        # Set up file logger
        self.logger = logging.getLogger("TOCRejection")
        self.logger.setLevel(logging.INFO)

        # Remove existing handlers to avoid duplicates
        self.logger.handlers = []

        # File handler for rejected_toc.log
        file_handler = logging.FileHandler(self.log_file, mode="a")
        file_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
        self.logger.addHandler(file_handler)

    def start_report(self, report_id: str):
        """Start tracking for a new report."""
        self.current_report_id = report_id
        self.rejected_entries = []
        self.accepted_count = 0
        self.total_candidates = 0
        self.logger.info(f"\n{'=' * 60}")
        self.logger.info(f"REPORT: {report_id}")
        self.logger.info(f"{'=' * 60}")

    def log_rejection(
        self,
        text: str,
        page_num: int,
        reason: str,
        pattern_matched: Optional[str] = None,
        font_size: Optional[float] = None,
    ):
        """Log a rejected TOC entry."""
        self.total_candidates += 1

        entry = RejectedTOCEntry(
            report_id=self.current_report_id or "unknown",
            page_num=page_num,
            text=text[:100],  # Truncate for readability
            rejection_reason=reason,
            pattern_matched=pattern_matched,
            font_size=font_size,
            timestamp=datetime.now().isoformat(),
        )
        self.rejected_entries.append(entry)

        # Write to log file
        pattern_str = pattern_matched[:20] if pattern_matched else "N/A"
        log_msg = (
            f"REJECTED | Page {page_num:3d} | {reason:25s} | "
            f"Pattern: {pattern_str:20s} | Text: {text[:80]}"
        )
        self.logger.info(log_msg)

    def log_acceptance(self, text: str, page_num: int):
        """Track accepted entry (for statistics)."""
        self.total_candidates += 1
        self.accepted_count += 1

    def finalize_report(self) -> Tuple[bool, Dict]:
        """
        Finalize report processing and check for alerts.

        Returns:
            Tuple of (alert_raised, statistics_dict)
        """
        total_rejected = len(self.rejected_entries)

        # Calculate rejection rate
        rejection_rate = (
            total_rejected / self.total_candidates if self.total_candidates > 0 else 0
        )

        # Build statistics
        stats = {
            "report_id": self.current_report_id,
            "total_candidates": self.total_candidates,
            "total_accepted": self.accepted_count,
            "total_rejected": total_rejected,
            "rejection_rate": rejection_rate,
            "rejection_reasons": self._count_rejection_reasons(),
        }

        # Log summary
        self.logger.info(f"\n--- SUMMARY: {self.current_report_id} ---")
        self.logger.info(f"Total candidates: {self.total_candidates}")
        self.logger.info(f"Accepted: {self.accepted_count}")
        self.logger.info(f"Rejected: {total_rejected} ({rejection_rate * 100:.1f}%)")

        # Check for alert condition
        alert_raised = False
        if rejection_rate > self.ALERT_THRESHOLD:
            alert_raised = True
            alert_msg = (
                f"\n{'!' * 60}\n"
                f"⚠️  ALERT: High TOC rejection rate for {self.current_report_id}\n"
                f"    Rejection rate: {rejection_rate * 100:.1f}% (threshold: {self.ALERT_THRESHOLD * 100}%)\n"
                f"    Rejected: {total_rejected} / {self.total_candidates} candidates\n"
                f"    Review logs/rejected_toc.log to ensure legitimate chapters aren't being filtered\n"
                f"{'!' * 60}"
            )
            self.logger.warning(alert_msg)

        return (alert_raised, stats)

    def _count_rejection_reasons(self) -> Dict[str, int]:
        """Count rejections by reason."""
        reasons: Dict[str, int] = {}
        for entry in self.rejected_entries:
            reason = entry.rejection_reason
            reasons[reason] = reasons.get(reason, 0) + 1
        return reasons


# =============================================================================
# TEXT BLOCK DATA STRUCTURES
# =============================================================================


@dataclass(unsafe_hash=True)
class TextBlock:
    """
    Rich text block features extracted from PDF for heuristic analysis.
    """

    page_num: int
    bbox: Tuple[float, float, float, float]
    text: str
    font_name: str
    font_size: float
    font_flags: int
    line_height: float
    position: Tuple[float, float]
    word_count: int
    char_count: int


@dataclass
class StyleProfile:
    """Statistical profile of document's typography and layout."""

    body_font_size_baseline: float
    body_font_families: List[str]
    body_text_flags: set
    page_stats: Dict[str, float]


# =============================================================================
# SCAFFOLDING SERVICE
# =============================================================================


class ScaffoldingService:
    """
    Service to build the document's structural scaffold: unified Table of Contents
    and logical-to-physical page number mappings.

    Implements hybrid ToC strategy: embedded extraction with heuristic fallback.

    PHASE 1 FIXES:
    - TOC validation with comprehensive reject/accept patterns
    - Rejection logging with alert threshold for pilot monitoring
    - Lower embedded TOC threshold (3 entries instead of 5)
    - Clean TOC titles by removing trailing page numbers

    PHASE 2 FIXES (2025-12-23):
    - Structural checks (pipes, number density) BEFORE pattern matching
    - Enhanced OCR table content rejection
    - Devanagari script detection
    """

    # =========================================================================
    # PHASE 1 + PHASE 2: Comprehensive patterns for FALSE POSITIVE TOC entries
    # =========================================================================
    TOC_REJECT_PATTERNS = [
        # === ORIGINAL PHASE 1 PATTERNS ===
        r"^Report No\.?\s+\d+",  # Page header: "Report No. 14 of 2025"
        r"^Table\s+\d+[\.:]\s",  # Table captions: "Table 1.3: Growth..."
        r"^Figure\s+\d+[\.:]\s",  # Figure captions
        r"^Chart\s+\d+[\.:]\s",  # Chart captions
        r"^Graph\s+\d+[\.:]\s",  # Graph captions
        r"^Box\s+\d+[\.:]\s",  # Box captions
        r"^\(₹",  # Currency units: "(₹ in crore)"
        r"^₹\s*[\d,]+",  # Currency values
        r"^Total\s+[\d,\.]+",  # Data rows: "Total 633.2 100.0"
        r"^\d+\s+\d+\s+\d+\s+\d+",  # Column numbers: "1 2 3 4 5 6 7 8 9 10"
        r"^Case\s+[IVX]+\s",  # Case headers: "Case I CIT..."
        r"^\d+[\d,\.]+\s+\d+[\d,\.]+",  # Numeric data rows
        r"^Sl\.?\s*No",  # Serial number headers
        r"^Source\s*:",  # Source attributions
        r"^Note\s*:",  # Notes
        r"^[ivxlc]+$",  # Roman numerals only
        r"^\d{1,3}$",  # Just page numbers
        r"^\(.*\)$",  # Just parenthetical content
        r"^[a-z]",  # Starts with lowercase
        r"^\W",  # Starts with non-word char
        r".*\.{4,}.*",  # Dots leader: "Introduction......"
        r"(?i)^balance\s",  # Accounting noise
        r"(?i)in\s+(crore|lakh)\)?$",  # Unit indicators
        r"^\d{4}-\d{2,4}\s+\d{4}-\d{2,4}",  # Year range data
        # === PHASE 2 NEW PATTERNS: OCR'd Table Content (2025-12-23) ===
        # Pattern: Pipe characters indicate table cells
        r".*\|.*\|",  # Contains 2+ pipe characters: "5 | 6 | Pune |"
        # Pattern: City/Place followed by numbers (infrastructure table rows)
        r"^[\d\s]*[A-Z][a-z]+[-\s][A-Z][a-z]+\s+\d{2,}",  # "Agra-Mumbai 964 24329"
        r"^\d+\s+[A-Z][a-z]+[-\s]",  # "5 Agra-Mumbai" at start
        # Pattern: Multiple comma-formatted numbers (financial data)
        r"[\d,]{4,}\s+[\d,]{4,}\s+[\d,]{4,}",  # "24,329 25,000 30,000"
        r"\d{1,3}(,\d{3})+.*\d{1,3}(,\d{3})+",  # Two+ comma-separated numbers
        # Pattern: Year followed by numbers (annual data rows)
        r"^\d{4}[-–]\d{2,4}\s+\d{2,}",  # "2019-20 412 24,15,492"
        r"\d{4}[-–]\d{2}\s+\d{3,}",  # Year-YY followed by large number
        # Pattern: Multiple consecutive number groups (table columns)
        r"(\d{2,}\s+){4,}",  # 4+ consecutive number groups: "964 24329 25 6"
        r"^\d{1,2}\s+\d{2,}[\s,]+\d{2,}",  # "5 964 24329" at start
        # Pattern: Table-like mixed alphanumeric rows
        r"^[A-Z][a-z]+\s+\d{2,}\s+\d{2,}",  # "Mumbai 964 24329"
        r"\d{2,}\s+[A-Z][a-z]+\s+\d{2,}",  # "964 Mumbai 24329"
        # Pattern: Percentage symbols in data
        r"\d+\s*%\s+\d+\s*%",  # Multiple percentages: "25% 30%"
        r"^\d+\s*%",  # Starts with percentage
        # Pattern: Directors/Board table content (CPSE reports)
        r"Directors?\s+Directors?\s+",  # "Directors Directors" repeated
        r"Executive\s+Executive\s+",  # Repeated table headers
        r"Non[-\s]*Executive.*Executive",  # Table header fragments
        # Pattern: OCR artifacts - repeated words/fragments
        r"(\b\w{3,}\b).*\1.*\1",  # Same word 3+ times
        # Pattern: Financial table indicators
        r"^(?:Cr|Dr)\.?\s+\d",  # Credit/Debit indicators
        r"^[-–]\s*\d",  # Negative numbers in data
        r"^\+\s*\d",  # Positive indicators
        # Pattern: State/region table rows with numbers
        r"^(?:Assam|Bihar|Gujarat|Haryana|Karnataka|Maharashtra|Rajasthan|Tamil Nadu|Uttar Pradesh).*\d{3,}",
        # Pattern: Connectivity/Infrastructure table rows
        r"(?:Connectivity|Corridor|Highway|Road).*\d{3,}.*\d{3,}",
        # Pattern: Devanagari script (Hindi OCR garbage)
        r"[\u0900-\u097F]{3,}",  # 3+ consecutive Devanagari characters
        # Pattern: Long alphanumeric sequences (OCR garbage)
        r"[A-Za-z]{1,3}\d{3,}[A-Za-z]{1,3}",  # "abc123def" patterns
    ]

    # =========================================================================
    # Patterns for HIGH CONFIDENCE valid TOC entries
    # Many patterns require exact match ($ anchor) to avoid false positives
    # like "Executive Summary | Vv |" type garbage
    # =========================================================================
    TOC_ACCEPT_PATTERNS = [
        # Chapter patterns (Roman and Arabic numerals)
        r"^Chapter\s+[IVX\d]+[:\s]",  # "Chapter I: Introduction"
        r"^Chapter\s+[IVXivx]+[\s:\-]",  # Chapter I, Chapter IV, etc.
        r"^Chapter\s+\d+[\s:\-]",  # Chapter 1, Chapter 2, etc.
        # Section/Part patterns
        r"^Section\s+[IVX\d]+[:\s]",  # "Section 1: Overview"
        r"^Part\s+[IVX\d]+[:\s]",  # "Part I: Background"
        # Annexure/Appendix
        r"^Annexure\s+[IVX\d\-A-Z]+$",  # "Annexure I", "Annexure A-1" (exact)
        r"^Appendix\s+[IVX\d\-A-Z]+$",  # "Appendix I" (exact)
        r"^Appendices$",  # "Appendices" (exact)
        r"^Annexures?$",  # "Annexure" or "Annexures" (exact)
        # Numbered sections: "1.1 Introduction", "2.3.1 Overview"
        r"^\d+\.\d+(\.\d+)?\s+[A-Z]",
        # Common front matter (EXACT MATCH to avoid "Preface | ii |")
        r"^Preface$",
        r"^Foreword$",
        r"^Preamble$",
        r"^Executive\s+Summary$",  # EXACT match only
        r"^Contents$",
        r"^Table\s+of\s+Contents$",
        r"^Abbreviations?$",
        r"^Glossary$",
        r"^Acknowledgements?$",
        # Common sections (exact match)
        r"^Introduction$",
        r"^Conclusion$",
        r"^Recommendations?$",
        r"^Findings?$",
        # CAG-specific sections
        r"^Audit\s+Objectives?$",
        r"^Audit\s+Scope$",
        r"^Audit\s+Criteria$",
        r"^Audit\s+Methodology$",
        r"^Key\s+Audit\s+Findings$",
        r"^Introduction\s+and\s+Background$",
        r"^Good\s+Practices$",
        r"^Summary\s+of\s+Findings$",
        # Lettered subsections (A. Karnataka, B. Rajasthan, etc.)
        # ONLY accept if NOT followed by numbers (to avoid table rows)
        r"^[A-Z]\.\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*$",  # "A. Himachal Pradesh" (exact)
        # Numbered roman subsections in parentheses
        r"^\([ivx]+\)\s+[A-Z]",  # (i) Delay in..., (ii) Non achievement...
    ]

    def __init__(
        self,
        embed_toc_min_entries: int = 5,
        body_text_percentile: float = 80.0,
        heading_size_ratio: float = 1.4,
        heading_min_length: int = 10,
        config: Optional[ScaffoldingConfig] = None,
    ):
        """
        Initialize the scaffolding service.

        Args:
            embed_toc_min_entries: Minimum entries required to accept embedded ToC
            body_text_percentile: Percentile used to determine baseline body font size
            heading_size_ratio: Minimum size ratio above baseline for heading detection
            heading_min_length: Minimum character length for potential headings
            config: Optional ScaffoldingConfig for bookmark quality settings
        """
        # Load config (with fallback to global config)
        if config is None:
            config = get_config().scaffolding
        self._config = config

        self.embed_toc_min_entries = embed_toc_min_entries
        self.body_text_percentile = body_text_percentile
        self.heading_size_ratio = heading_size_ratio
        self.heading_min_length = heading_min_length

        # Bookmark quality threshold (0-1 range, default 0.6)
        self.bookmark_quality_threshold = config.bookmark_quality_threshold

        # Compile patterns for efficiency
        self._reject_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.TOC_REJECT_PATTERNS
        ]
        self._accept_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.TOC_ACCEPT_PATTERNS
        ]

        # Compile bookmark quality patterns (from config for hot-reload support)
        self._assembly_patterns = [
            re.compile(p, re.IGNORECASE) for p in config.assembly_bookmark_patterns
        ]
        self._cag_patterns = [
            re.compile(p, re.IGNORECASE) for p in config.cag_quality_patterns
        ]

        # Initialize rejection logger
        self.toc_rejection_logger = TOCRejectionLogger()

        # Store last alert info for pipeline integration
        self._last_toc_alert: Optional[Dict] = None

    def build_scaffold(
        self,
        task: DocumentTask,
        trace_emitter: Optional["TraceEmitter"] = None,
    ) -> DocumentTask:
        """
        Build the complete document scaffold: ToC and page mappings.

        Args:
            task: DocumentTask with processed PDF path
            trace_emitter: Optional trace emitter for instrumentation

        Returns:
            Updated DocumentTask with scaffold field populated
        """
        # Use no-op emitter if none provided
        if trace_emitter is None:
            from src.parsing_pipeline.instrumentation import get_noop_emitter
            trace_emitter = get_noop_emitter()

        pdf_path = self._get_pdf_path(task)
        if not pdf_path:
            task.error_log.append("No valid PDF path found for scaffolding")
            task.processing_status = "failed_scaffold"
            trace_emitter.set_phase_status("4", "failed")
            return task

        # Initialize scaffold with heading_positions dict for Y-coordinate tracking
        task.scaffold = {"toc": [], "page_map": {}, "heading_positions": {}}

        # Track TOC extraction method for tracing
        toc_method = "none"
        toc_entries_before_filter = 0

        with trace_emitter.phase_timer("4"):
            try:
                doc = fitz.Document(pdf_path)

                # P1-15: Emit page_count at phase entry
                trace_emitter.emit_io(
                    "4",
                    {"pdf_path": pdf_path, "page_count": doc.page_count},
                    {},  # Output will be emitted at phase completion
                )

                # Phase 1: Extract ToC via bookmarks/embedded outlines
                task = self._extract_embedded_toc(task, doc, trace_emitter=trace_emitter)

                if task.scaffold["toc"]:
                    toc_method = task.scaffold.get("toc_method", "embedded_bookmarks")

                # Phase 2: Fallback to heuristic ToC generation if none found
                if not task.scaffold["toc"]:
                    heuristic_toc, heading_positions = self._generate_heuristic_toc(doc, task.report_id)
                    if heuristic_toc:
                        task.scaffold["toc"] = heuristic_toc
                        task.scaffold["heading_positions"] = heading_positions
                        toc_method = "heuristic"
                        task.error_log.append(
                            f"Heuristic ToC generated with {len(heuristic_toc)} entries"
                        )
                        trace_emitter.emit_fallback(
                            "4",
                            "embedded_bookmarks",
                            "heuristic_toc",
                            "No embedded bookmarks found or quality too low",
                        )

                    # Check if there was a high rejection alert
                    if self._last_toc_alert:
                        task.error_log.append(
                            f"⚠️ TOC ALERT: {self._last_toc_alert['message']} - "
                            f"Review logs/rejected_toc.log"
                        )
                        # Fix 3: Extract rejection_rate from stats dict (not "rate" key)
                        stats = self._last_toc_alert.get("stats", {})
                        rejection_rate = stats.get("rejection_rate", 0) if stats else 0
                        trace_emitter.emit_red_flag(
                            "4",
                            "High TOC rejection rate",
                            {
                                "rejection_rate_pct": f"{rejection_rate * 100:.1f}%",
                                "rejected_count": stats.get("total_rejected", 0),
                                "total_count": stats.get("total_candidates", 0),
                            },
                        )
                        self._last_toc_alert = None

                # Phase 2.5: Try printed TOC pre-pass as supplementary signal
                printed_toc, printed_confidence = self._extract_printed_toc(pdf_path, task.report_id)

                if printed_toc and printed_confidence > 0.5:
                    current_toc = task.scaffold.get("toc", [])
                    current_quality = task.scaffold.get("toc_quality", 0)

                    # Infer quality if not explicitly set but TOC exists
                    # Embedded/heuristic TOCs don't set quality, but if they have entries they're likely decent
                    if current_toc and current_quality == 0:
                        # Infer quality based on entry count and structure
                        if len(current_toc) >= 5:
                            current_quality = 70  # Assume decent quality if has multiple entries
                        else:
                            current_quality = 50  # Medium quality for fewer entries

                    if not current_toc or current_quality < 40:
                        # No existing TOC or very low quality — use printed TOC as primary
                        task.scaffold["toc"] = printed_toc
                        task.scaffold["toc_method"] = "printed_toc_prepass"
                        task.scaffold["toc_quality"] = int(printed_confidence * 100)
                        toc_method = "printed_toc"
                        logger.info(f"[{task.report_id}] Using printed TOC pre-pass as primary ({len(printed_toc)} entries)")
                        task.error_log.append(
                            f"Printed TOC pre-pass used as primary: {len(printed_toc)} entries"
                        )
                        trace_emitter.emit_decision(
                            "4",
                            "toc_source",
                            "printed_toc_prepass",
                            ["embedded_bookmarks", "heuristic", "printed_toc"],
                            f"Current quality {current_quality} < 40, printed confidence {printed_confidence:.2f}",
                        )

                    elif current_quality < 70 and len(printed_toc) > len(current_toc):
                        # Medium quality existing TOC but printed has more entries — supplement
                        # Merge: keep existing, add any printed entries not already present
                        existing_titles = {entry[1].lower().strip() for entry in current_toc}
                        new_entries = [
                            entry for entry in printed_toc
                            if entry[1].lower().strip() not in existing_titles
                        ]
                        if new_entries:
                            merged = current_toc + new_entries
                            # Re-sort by page number
                            merged.sort(key=lambda e: e[2])
                            task.scaffold["toc"] = merged
                            task.scaffold["toc_method"] = f"{task.scaffold.get('toc_method', 'unknown')}+printed_supplement"
                            toc_method = f"{toc_method}+printed_supplement"
                            logger.info(f"[{task.report_id}] Supplemented TOC with {len(new_entries)} printed entries")
                            task.error_log.append(
                                f"TOC supplemented with {len(new_entries)} printed entries"
                            )

                # Phase 3: Generate page number mappings (always done)
                task = self._build_page_mappings(task, doc)

                # Track entries before filtering
                toc_entries_before_filter = len(task.scaffold.get("toc", []))

                # Phase 4: Filter/dedupe ToC for quality
                if task.scaffold["toc"]:
                    filtered = self._filter_and_dedupe_toc(task.scaffold["toc"])
                    task.scaffold["toc"] = filtered
                    task.error_log.append(
                        f"Filtered ToC entries: {len(filtered)} remaining"
                    )

                doc.close()

                # Validate results and set status
                task = self._validate_and_set_status(task)

                # Emit Phase 4 I/O and decisions
                final_toc_count = len(task.scaffold.get("toc", []))
                final_quality = task.scaffold.get("toc_quality", 0)

                trace_emitter.emit_io(
                    "4",
                    {"pdf_path": pdf_path, "page_count": task.scaffold.get("page_map", {}).get("total_pages", 0)},
                    {
                        "toc_entries": final_toc_count,
                        "toc_quality": final_quality,
                        "toc_method": toc_method,
                        "heading_positions": len(task.scaffold.get("heading_positions", {})),
                    },
                )

                if toc_entries_before_filter > final_toc_count:
                    trace_emitter.emit(
                        "4",
                        "toc_filtering",
                        {
                            "entries_before": toc_entries_before_filter,
                            "entries_after": final_toc_count,
                            "filtered_out": toc_entries_before_filter - final_toc_count,
                        },
                    )

                trace_emitter.emit_decision(
                    "4",
                    "toc_method_final",
                    toc_method,
                    ["embedded_bookmarks", "heuristic", "printed_toc", "none"],
                    f"Quality: {final_quality}, entries: {final_toc_count}",
                )

                trace_emitter.set_phase_status(
                    "4",
                    "success" if final_toc_count > 0 else "partial",
                )

            except Exception as e:
                task.error_log.append(f"Scaffolding failed with error: {str(e)}")
                task.processing_status = "failed_scaffold"
                trace_emitter.emit_error("4", str(e))
                trace_emitter.set_phase_status("4", "failed")

        return task

    def _get_pdf_path(self, task: DocumentTask) -> Optional[str]:
        """Determine which PDF path to use (OCR'd or original)."""
        if task.ocred_pdf_path and Path(task.ocred_pdf_path).exists():
            return task.ocred_pdf_path
        elif task.local_pdf_path and Path(task.local_pdf_path).exists():
            return task.local_pdf_path
        return None

    def _extract_printed_toc(self, pdf_path: str, report_id: str = "unknown") -> Tuple[List[List], float]:
        """
        Pre-pass: Extract TOC by parsing raw text from early pages.

        Opens the PDF directly and feeds lines through TOCTableParser's
        regex patterns. This runs BEFORE any chunking, solving the
        chicken-egg problem where the table parser needed chunks that
        don't exist yet.

        Args:
            pdf_path: Path to the PDF file
            report_id: Report identifier for logging

        Returns:
            Tuple of (toc_entries: List[List], confidence: float)
            toc_entries format: [[level, title, page_num], ...]
        """
        parser = TOCTableParser()
        entries = []
        toc_started = False
        toc_ended = False

        try:
            doc = fitz.open(pdf_path)
            max_page = min(15, len(doc))  # Only scan first 15 pages

            for page_num in range(max_page):
                if toc_ended:
                    break

                page = doc[page_num]
                text = page.get_text("text")
                lines = text.split("\n")

                for line in lines:
                    line = line.strip()
                    if not line or len(line) < 3:
                        continue

                    # Detect TOC header
                    if not toc_started:
                        line_lower = line.lower().strip()
                        if line_lower in ("contents", "table of contents", "index", "list of contents"):
                            toc_started = True
                            continue

                    # Try to parse as TOC entry
                    entry = parser._parse_toc_line(line)
                    if entry:
                        entries.append(entry)
                    elif toc_started and len(entries) >= 3:
                        # If we had a TOC going and hit non-TOC content,
                        # check if TOC has ended
                        if parser._is_toc_end(line):
                            toc_ended = True
                            break

            doc.close()

        except Exception as e:
            logger.warning(f"[{report_id}] Printed TOC pre-pass failed: {e}")
            return [], 0.0

        if len(entries) < 3:
            logger.debug(f"[{report_id}] Printed TOC pre-pass: only {len(entries)} entries (min 3)")
            return [], 0.0

        # Convert TOCEntry objects to standard format
        toc = [[e.level, e.title, e.page_num] for e in entries]

        # Calculate confidence
        confidence = parser._calculate_confidence(entries, [])

        logger.info(
            f"[{report_id}] Printed TOC pre-pass: {len(entries)} entries, "
            f"confidence={confidence:.2f}"
        )

        return toc, confidence

    def _extract_embedded_toc(
        self,
        task: DocumentTask,
        doc: fitz.Document,
        trace_emitter: Optional["TraceEmitter"] = None,
    ) -> DocumentTask:
        """
        Attempt to extract embedded Table of Contents from PDF bookmarks.

        Uses scored validation to catch garbage PDF-merger bookmarks that
        pass entry count checks but aren't real TOC entries (e.g., "01 Cover",
        "05 Final_Report", "p001").
        """
        # Use no-op emitter if none provided
        if trace_emitter is None:
            from src.parsing_pipeline.instrumentation import get_noop_emitter
            trace_emitter = get_noop_emitter()

        try:
            toc = doc.get_toc(simple=False)

            # Score the bookmarks (replaces binary validation)
            metrics = self._score_embedded_toc(toc, doc.page_count)
            score = metrics.score()

            # Threshold check: score() returns 0-100, threshold is 0-1
            threshold_score = self.bookmark_quality_threshold * 100

            # Trace the bookmark quality scoring decision
            trace_emitter.emit_decision(
                "4",
                "bookmark_quality",
                "accept" if score >= threshold_score else "reject",
                ["accept", "reject"],
                f"Score {score:.1f} vs threshold {threshold_score:.1f}, "
                f"confidence={metrics.confidence:.2f}, entries={metrics.entry_count}",
            )

            # Emit sample of bookmark titles for inspection
            if toc and len(toc) > 0:
                sample_titles = [
                    {"level": entry[0], "title": str(entry[1])[:60], "page": entry[2]}
                    for entry in toc[:5]  # First 5 entries
                ]
                trace_emitter.emit_sample("4", "bookmark_entries", sample_titles)

            if score >= threshold_score:
                # Clean the embedded TOC entries
                cleaned_toc = []
                for entry in toc:
                    if len(entry) >= 3:
                        level, title, page = entry[:3]
                        cleaned_title = self._clean_toc_title(title)
                        if cleaned_title:  # Skip empty titles
                            cleaned_toc.append([level, cleaned_title, page])

                task.scaffold["toc"] = cleaned_toc
                task.scaffold["toc_quality_metrics"] = {
                    "source": metrics.source,
                    "entry_count": metrics.entry_count,
                    "level_count": metrics.level_count,
                    "has_chapters": metrics.has_chapters,
                    "has_sections": metrics.has_sections,
                    "page_coverage": metrics.page_coverage,
                    "confidence": metrics.confidence,
                    "score": score,
                }
                task.scaffold["toc_quality"] = int(score)
                task.scaffold["toc_method"] = "embedded_bookmarks"
                task.error_log.append(
                    f"Embedded ToC extracted: {len(cleaned_toc)} entries, "
                    f"score={score:.1f}, confidence={metrics.confidence:.2f}"
                )
            else:
                task.error_log.append(
                    f"Embedded ToC rejected: {len(toc)} entries, score={score:.1f} "
                    f"(threshold={threshold_score:.1f}), confidence={metrics.confidence:.2f}, "
                    f"proceeding to heuristic generation"
                )
                task.scaffold["toc"] = []
                # Store metrics even for rejected TOC (useful for debugging)
                task.scaffold["rejected_bookmark_metrics"] = {
                    "source": metrics.source,
                    "entry_count": metrics.entry_count,
                    "score": score,
                    "confidence": metrics.confidence,
                }

        except Exception as e:
            task.error_log.append(
                f"Embedded ToC extraction failed: {str(e)}, proceeding to heuristic generation"
            )
            task.scaffold["toc"] = []
            trace_emitter.emit_error("4", f"Embedded TOC extraction failed: {str(e)}")

        return task

    def _score_embedded_toc(self, toc: List[List], total_pages: int) -> TOCQualityMetrics:
        """
        Score embedded TOC quality with assembly/CAG pattern detection.

        Replaces the binary _validate_embedded_toc() with structured scoring.
        Catches garbage PDF-merger bookmarks ("01 Cover", "p001") that pass
        entry count/level checks but aren't real TOC entries.

        Args:
            toc: List of TOC entries [level, title, page]
            total_pages: Total number of pages in the document

        Returns:
            TOCQualityMetrics with score() method for threshold comparison
        """
        if not toc:
            return TOCQualityMetrics(
                source="bookmarks",
                entry_count=0,
                level_count=0,
                has_chapters=False,
                has_sections=False,
                page_coverage=0.0,
                confidence=0.0,
            )

        # Calculate structural metrics
        levels = {entry[0] for entry in toc}
        level_count = len(levels)

        # Check for chapters
        has_chapters = any(
            "chapter" in entry[1].lower()
            for entry in toc
        )

        # Check for numbered sections (e.g., "2.3 Section Title")
        has_sections = any(
            re.match(r"^\d+\.\d+", entry[1])
            for entry in toc
        )

        # Calculate page coverage
        pages_covered = set()
        for entry in toc:
            if len(entry) >= 3 and isinstance(entry[2], int) and entry[2] > 0:
                pages_covered.add(entry[2])
        page_coverage = len(pages_covered) / max(total_pages, 1)

        # Start with base confidence
        confidence = 1.0

        # Penalty for file-assembly patterns (garbage PDF-merger bookmarks)
        assembly_count = sum(
            1 for entry in toc
            if any(p.match(entry[1]) for p in self._assembly_patterns)
        )
        if assembly_count > 0:
            confidence -= (assembly_count / len(toc)) * 0.5

        # Bonus for CAG-specific patterns (Chapter, Annexure, Executive Summary, etc.)
        cag_count = sum(
            1 for entry in toc
            if any(p.match(entry[1]) for p in self._cag_patterns)
        )
        if cag_count > 0:
            confidence += min(0.2, cag_count * 0.05)

        # Penalty for very few entries
        if len(toc) < 5:
            confidence -= 0.3

        # Penalty for single hierarchy level (need depth)
        if level_count < 2:
            confidence -= 0.3

        # Penalty for low page coverage
        if page_coverage < 0.1:
            confidence -= 0.2

        # Clamp confidence to valid range
        confidence = max(0.1, min(1.0, confidence))

        return TOCQualityMetrics(
            source="bookmarks",
            entry_count=len(toc),
            level_count=level_count,
            has_chapters=has_chapters,
            has_sections=has_sections,
            page_coverage=page_coverage,
            confidence=confidence,
        )

    def _is_valid_toc_entry(
        self,
        text: str,
        page_num: int,
        seen_entries: set,
        font_size: Optional[float] = None,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Validate if text block is a legitimate TOC entry.

        PHASE 1 FIX: Comprehensive validation with logging support.
        PHASE 2 FIX (2025-12-23):
        - Structural checks BEFORE pattern matching
        - Pipe character detection for table content
        - Number density checks
        - Devanagari script rejection
        - Word/number ratio analysis

        Args:
            text: Cleaned heading text
            page_num: Page number where found
            seen_entries: Set of already-seen entries (for deduplication)
            font_size: Font size of the text block (for logging)

        Returns:
            Tuple of (is_valid, rejection_reason, matched_pattern)
        """
        # Skip empty or very short
        if not text or len(text.strip()) < 3:
            return (False, "too_short", None)

        cleaned = text.strip()

        # =====================================================================
        # Perform structural checks BEFORE pattern matching (order dependency)
        # These indicate table content regardless of what words are present
        # =====================================================================

        # Check 1: Pipe characters (clear table indicator)
        # This catches: "Executive Summary | Vv |", "5 | Pune |"
        if cleaned.count("|") >= 2:
            return (False, "contains_pipe_chars", "table_cell_dividers")

        # Check 2: Single pipe with mixed content is also suspicious
        if "|" in cleaned and re.search(r"[A-Za-z]+\s+\|\s+[A-Za-z0-9]", cleaned):
            return (False, "pipe_in_content", "likely_table_fragment")

        # Check 3: Excessive numbers (table data) - 5 or more number groups
        number_matches = re.findall(r"\d+", cleaned)
        if len(number_matches) >= 5:
            return (False, "too_many_numbers", f"found_{len(number_matches)}_numbers")

        # Check 4: Multiple comma-formatted numbers (financial data)
        comma_numbers = re.findall(r"\d{1,3}(?:,\d{3})+", cleaned)
        if len(comma_numbers) >= 2:
            return (False, "comma_formatted_numbers", "financial_data")

        # Check 5: Year-number patterns (annual data rows)
        year_patterns = re.findall(r"\d{4}[-–]\d{2,4}\s+\d{3,}", cleaned)
        if year_patterns:
            return (False, "year_data_pattern", year_patterns[0][:20])

        # Check 6: Devanagari script (Hindi OCR garbage)
        if re.search(r"[\u0900-\u097F]{3,}", cleaned):
            return (False, "devanagari_text", "hindi_ocr_artifact")

        # Check 7: High number/word ratio suggests table data
        words = re.findall(r"[a-zA-Z]{2,}", cleaned)
        numbers = re.findall(r"\d+", cleaned)
        if numbers and len(numbers) > len(words) and len(numbers) >= 3:
            return (
                False,
                "high_number_ratio",
                f"nums:{len(numbers)}_words:{len(words)}",
            )

        # =====================================================================
        # Check for acceptance patterns (high confidence valid entries)
        # These are checked AFTER structural issues to avoid false accepts
        # =====================================================================

        for i, pattern in enumerate(self._accept_patterns):
            if pattern.match(cleaned):
                # But still check for duplicates
                entry_key = cleaned.lower()[:50]
                if entry_key in seen_entries:
                    return (False, "duplicate_accepted_pattern", None)
                return (True, None, None)

        # =====================================================================
        # Check against rejection patterns
        # =====================================================================

        for i, pattern in enumerate(self._reject_patterns):
            if pattern.match(cleaned) or pattern.search(cleaned):
                pattern_str = self.TOC_REJECT_PATTERNS[i][:30]
                return (False, "reject_pattern_match", pattern_str)

        # =====================================================================
        # Deduplication check
        # =====================================================================

        entry_key = cleaned.lower()[:50]
        if entry_key in seen_entries:
            return (False, "duplicate_entry", None)

        # =====================================================================
        # Content heuristics for borderline cases
        # =====================================================================

        # Reject if it looks like table data (multiple numbers with spaces)
        if re.match(r"^[\d\s,\.%]+$", cleaned):
            return (False, "numeric_data_only", None)

        # Reject if too long (likely a paragraph, not a heading)
        if len(cleaned) > 200:
            return (False, "too_long_for_heading", None)

        # Reject if more than 20 words
        if len(cleaned.split()) > 20:
            return (False, "too_many_words", None)

        return (True, None, None)

    def _filter_and_dedupe_toc(self, toc: List[List]) -> List[List]:
        """
        Apply heuristics to reduce false positives and deduplicate ToC entries.

        Uses comprehensive validation patterns from _is_valid_toc_entry.
        """
        filtered: List[List] = []
        seen: set = set()

        for entry in toc:
            if len(entry) < 3:
                continue
            level, raw_title, page = entry[:3]
            title = self._clean_toc_title(raw_title)

            # Use the validation method
            is_valid, reason, pattern = self._is_valid_toc_entry(title, page, seen)

            if not is_valid:
                continue

            # Track seen entries
            entry_key = title.lower()[:50]
            seen.add(entry_key)

            filtered.append([level, title, page])

        return filtered

    def _normalize_title(self, title: str) -> str:
        """Normalize ToC titles for comparison."""
        cleaned = " ".join(title.replace("…", ".").split())
        cleaned = cleaned.strip(". ")
        if len(cleaned) > 0 and cleaned[0] == "(" and cleaned[-1] == ")":
            cleaned = cleaned[1:-1]
        return cleaned.strip()

    def _is_rejected_toc_entry(self, title: str) -> bool:
        """
        DEPRECATED: Use _is_valid_toc_entry instead.
        Kept for backward compatibility.
        """
        is_valid, _, _ = self._is_valid_toc_entry(title, 0, set())
        return not is_valid

    def _clean_toc_title(self, text: str) -> str:
        """
        Clean and normalize heading text for ToC entry.

        Handles:
        - Trailing page numbers and ranges
        - Hyphenation artifacts
        - Excessive whitespace
        - Trailing punctuation
        """
        if not text:
            return ""

        # Step 1: Normalize whitespace
        title = " ".join(text.split())

        # Step 2: Handle line-ending hyphens
        title = title.replace("-\n", "").replace("-\r", "")

        # Step 3: Remove trailing page numbers/ranges
        # Pattern: title followed by space and page number(s)
        # Examples: "Chapter IV 77-99", "Appendix 101", "Contents i-xii"
        title = re.sub(r"\s+\d+[-–]\d+\s*$", "", title)  # "77-99"
        title = re.sub(r"\s+\d+\s*$", "", title)  # "77"
        title = re.sub(
            r"\s+[ivxlc]+[-–][ivxlc]+\s*$", "", title, flags=re.IGNORECASE
        )  # "i-xii"
        title = re.sub(r"\s+[ivxlc]+\s*$", "", title, flags=re.IGNORECASE)  # "xii"

        # Step 4: Remove dots/leaders before page numbers (if any remain)
        title = re.sub(r"\.{2,}\s*\d*\s*$", "", title)  # "Chapter I..........12"

        # Step 5: Clean trailing punctuation artifacts
        title = title.rstrip(".:;")
        while title.endswith("..") or title.endswith("--"):
            title = title[:-1]

        return title.strip()

    # =========================================================================
    # HEURISTIC TOC GENERATION
    # =========================================================================

    def _generate_heuristic_toc(
        self, doc: fitz.Document, report_id: str, max_sample_pages: int = 100
    ) -> Tuple[List[List], Dict[str, float]]:
        """
        Generate ToC using heuristic analysis of document structure.

        Includes rejection logging for pilot monitoring.

        P0-2: Now also returns heading Y-positions for accurate child chunk assignment.

        Args:
            doc: Opened PDF document
            report_id: Report identifier for logging
            max_sample_pages: Maximum pages to analyze

        Returns:
            Tuple of (toc_entries, heading_positions)
            where toc is [[level, title, page_physical], ...]
            and heading_positions is {"page_title[:30]": y_coordinate}
        """
        try:
            # Phase 1: Comprehensive text block extraction
            text_blocks = self._extract_text_blocks(doc, max_sample_pages)

            if len(text_blocks) < 20:
                return [], {}

            # Phase 2: Statistical style profiling
            style_profile = self._build_style_profile(text_blocks)

            # Phase 3: Advanced heading detection WITH LOGGING
            heading_candidates = self._detect_headings(
                text_blocks, style_profile, report_id
            )

            # Phase 4: Intelligent hierarchy inference
            hierarchy_map = self._infer_hierarchy(heading_candidates)

            # Phase 5: Synthetic ToC construction with Y-positions
            toc, heading_positions = self._construct_toc(heading_candidates, hierarchy_map)

            return toc, heading_positions

        except Exception as e:
            self.logger.error(f"Heuristic ToC generation failed: {e}")
            return [], {}

    def _extract_text_blocks(
        self, doc: fitz.Document, max_pages: int = 100
    ) -> List[TextBlock]:
        """Extract rich text blocks from PDF pages."""
        text_blocks = []
        pages_to_process = min(len(doc), max_pages)

        for page_num in range(pages_to_process):
            page = doc[page_num]
            blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)[
                "blocks"
            ]

            for block in blocks:
                if block.get("type") != 0:  # Text blocks only
                    continue

                lines = block.get("lines", [])
                if not lines:
                    continue

                # Aggregate text and font info from spans
                full_text = ""
                font_sizes = []
                font_names = []
                font_flags_list = []

                for line in lines:
                    for span in line.get("spans", []):
                        full_text += span.get("text", "")
                        font_sizes.append(span.get("size", 12.0))
                        font_names.append(span.get("font", "Unknown"))
                        font_flags_list.append(span.get("flags", 0))

                if not full_text.strip():
                    continue

                # Use most common/dominant font characteristics
                dominant_size = (
                    max(set(font_sizes), key=font_sizes.count) if font_sizes else 12.0
                )
                dominant_font = (
                    max(set(font_names), key=font_names.count)
                    if font_names
                    else "Unknown"
                )
                dominant_flags = (
                    max(set(font_flags_list), key=font_flags_list.count)
                    if font_flags_list
                    else 0
                )

                bbox = block.get("bbox", (0, 0, 0, 0))
                text_block = TextBlock(
                    page_num=page_num,
                    bbox=tuple(bbox),
                    text=full_text.strip(),
                    font_name=dominant_font,
                    font_size=dominant_size,
                    font_flags=dominant_flags,
                    line_height=bbox[3] - bbox[1] if len(bbox) >= 4 else 12.0,
                    position=(bbox[0], bbox[1]),
                    word_count=len(full_text.split()),
                    char_count=len(full_text),
                )
                text_blocks.append(text_block)

        return text_blocks

    def _build_style_profile(self, text_blocks: List[TextBlock]) -> StyleProfile:
        """Build statistical profile of document typography."""
        if not text_blocks:
            return StyleProfile(12.0, [], set(), {})

        font_sizes = [block.font_size for block in text_blocks]

        # Remove extreme outliers using IQR
        if len(font_sizes) > 10:
            Q1, Q3 = np.percentile(font_sizes, [25, 75])
            IQR = Q3 - Q1
            lower_bound = Q1 - 1.5 * IQR
            upper_bound = Q3 + 1.5 * IQR
            filtered_sizes = [s for s in font_sizes if lower_bound <= s <= upper_bound]
        else:
            filtered_sizes = font_sizes

        body_baseline = np.percentile(filtered_sizes, self.body_text_percentile)

        font_families_raw = [
            self._normalize_font_family(block.font_name) for block in text_blocks
        ]
        font_family_counts = Counter(font_families_raw)
        body_font_families = [family for family, _ in font_family_counts.most_common(3)]

        flags_counts = Counter([block.font_flags for block in text_blocks])
        common_flags = {
            flags
            for flags, count in flags_counts.most_common(3)
            if count > len(text_blocks) * 0.1
        }

        return StyleProfile(
            body_font_size_baseline=body_baseline,
            body_font_families=body_font_families,
            body_text_flags=common_flags,
            page_stats={"width": 595.0, "height": 842.0, "left_margin": 72.0},
        )

    def _normalize_font_family(self, font_name: str) -> str:
        """Normalize font family name by removing weight suffixes."""
        suffixes = ["-Bold", "-Regular", "-Italic", "-BoldItalic", ",Bold", ",Regular"]
        normalized = font_name
        for suffix in suffixes:
            normalized = normalized.replace(suffix, "")
        return normalized.split(",")[0].strip()

    def _detect_headings(
        self, text_blocks: List[TextBlock], style_profile: StyleProfile, report_id: str
    ) -> List[TextBlock]:
        """
        Detect heading candidates using multi-factor analysis with validation and logging.

        Now logs all rejections for pilot monitoring.
        """
        # Start logging for this report
        self.toc_rejection_logger.start_report(report_id)

        heading_candidates = []
        seen_entries: set = set()

        for block in text_blocks:
            # Calculate style-based score
            heading_score = self._calculate_heading_score(block, style_profile)

            # Must meet minimum score threshold
            if heading_score < 75:
                continue  # Not a heading candidate, don't log

            # Clean the text for validation
            cleaned_text = self._clean_toc_title(block.text)

            # Apply content validation with detailed rejection tracking
            is_valid, rejection_reason, matched_pattern = self._is_valid_toc_entry(
                cleaned_text, block.page_num, seen_entries, block.font_size
            )

            if not is_valid:
                self.toc_rejection_logger.log_rejection(
                    text=cleaned_text,
                    page_num=block.page_num,
                    reason=rejection_reason or "unknown",
                    pattern_matched=matched_pattern,
                    font_size=block.font_size,
                )
                continue

            # Track this entry
            entry_key = cleaned_text.lower()[:50]
            seen_entries.add(entry_key)

            # Log acceptance
            self.toc_rejection_logger.log_acceptance(cleaned_text, block.page_num)

            heading_candidates.append(block)

        # Finalize and check for alerts
        alert_raised, stats = self.toc_rejection_logger.finalize_report()

        if alert_raised:
            self._last_toc_alert = {
                "report_id": report_id,
                "stats": stats,
                "message": f"High TOC rejection rate: {stats['rejection_rate'] * 100:.1f}%",
            }

        return heading_candidates

    def _calculate_heading_score(
        self, block: TextBlock, style_profile: StyleProfile
    ) -> float:
        """Calculate composite heading score for a text block."""
        score = 0.0

        # Factor 1: Font Size Deviation (0-100 points)
        size_ratio = block.font_size / style_profile.body_font_size_baseline
        if size_ratio >= self.heading_size_ratio:
            score += min(100.0, (size_ratio - 1.0) * 50.0)

        # Factor 2: Font Style Change (0-25 points)
        bold_flags = 16
        if (
            block.font_flags & bold_flags
            and bold_flags not in style_profile.body_text_flags
        ):
            score += 20.0

        # Factor 3: Position Analysis (0-50 points)
        left_margin = style_profile.page_stats.get("left_margin", 72.0)
        if block.position[0] <= left_margin + 20:
            score += 30.0
        elif (
            abs(block.position[0] - style_profile.page_stats.get("width", 595.0) / 2)
            < 50
        ):
            score += 10.0

        # Factor 4: Text Characteristics (0-25 points)
        if block.char_count >= self.heading_min_length:
            score += 15.0
        if block.word_count <= 15:
            score += 10.0

        return min(200.0, score)

    def _assign_heading_levels_quantile(
        self, font_sizes: List[float], n_levels: int = 3
    ) -> List[int]:
        """
        Assign heading levels using quantile-based bucketing.

        Replaces K-Means clustering with deterministic quantile boundaries.
        Largest fonts → level 1, smallest → level n_levels.

        Args:
            font_sizes: List of font sizes from detected headings
            n_levels: Number of hierarchy levels to create (default 3)

        Returns:
            List of level assignments (1-based, 1=highest/largest)
        """
        if not font_sizes:
            return []

        unique_sizes = sorted(set(font_sizes), reverse=True)

        # If fewer unique sizes than levels, map directly
        if len(unique_sizes) <= n_levels:
            size_to_level = {size: i + 1 for i, size in enumerate(unique_sizes)}
            return [size_to_level[fs] for fs in font_sizes]

        # Quantile boundaries: split into n_levels buckets
        boundaries = np.percentile(
            unique_sizes, [100 * i / n_levels for i in range(1, n_levels)]
        )

        levels = []
        for fs in font_sizes:
            level = n_levels  # Default to deepest
            for i, boundary in enumerate(boundaries):
                if fs >= boundary:
                    level = i + 1
                    break
            levels.append(level)

        return levels

    def _infer_hierarchy(
        self, heading_candidates: List[TextBlock]
    ) -> Dict[TextBlock, int]:
        """
        Infer document hierarchy for heading candidates using quantile bucketing.

        Replaced K-Means clustering with deterministic quantile-based approach
        for more predictable and efficient level assignment.
        """
        if len(heading_candidates) < 3:
            return {block: 1 for block in heading_candidates}

        # Extract font sizes
        font_sizes = [block.font_size for block in heading_candidates]

        # Determine optimal number of levels based on unique font sizes
        unique_sizes = len(set(font_sizes))
        n_levels = min(unique_sizes, 5)

        # Assign levels using quantile bucketing
        levels = self._assign_heading_levels_quantile(font_sizes, n_levels)

        # Build hierarchy map
        hierarchy_map = {}
        for block, level in zip(heading_candidates, levels):
            hierarchy_map[block] = level

        return hierarchy_map

    def _construct_toc(
        self, heading_candidates: List[TextBlock], hierarchy_map: Dict[TextBlock, int]
    ) -> Tuple[List[List], Dict[str, float]]:
        """
        Construct synthetic Table of Contents from heading candidates.

        P0-2: Now also returns heading Y-positions for accurate child chunk assignment.

        Returns:
            Tuple of (toc_entries, heading_positions)
            where heading_positions = {"page_title[:30]": y_coordinate}
        """
        sorted_candidates = sorted(
            heading_candidates, key=lambda x: (x.page_num, x.position[1])
        )

        toc = []
        heading_positions = {}

        for candidate in sorted_candidates:
            level = hierarchy_map[candidate]
            title = self._clean_toc_title(candidate.text)
            page_physical = candidate.page_num

            toc_entry = [level, title, page_physical]
            toc.append(toc_entry)

            # Store Y-coordinate of heading (y0 from bbox) for multi-section page handling
            # Key format: "page_title[:30]" for matching in chunking
            key = f"{page_physical}_{title[:30]}"
            y_position = candidate.bbox[1]  # y0 coordinate (top of heading)
            heading_positions[key] = y_position

        return toc, heading_positions

    # =========================================================================
    # PAGE MAPPINGS & VALIDATION
    # =========================================================================

    def _build_page_mappings(
        self, task: DocumentTask, doc: fitz.Document
    ) -> DocumentTask:
        """Build physical to logical page number mappings."""
        page_map = {}

        for page_num in range(len(doc)):
            page = doc[page_num]
            label = page.get_label()
            if label:
                page_map[page_num] = label
            else:
                page_map[page_num] = str(page_num + 1)

        task.scaffold["page_map"] = page_map
        return task

    def _validate_and_set_status(self, task: DocumentTask) -> DocumentTask:
        """Validate scaffold results and set appropriate status."""
        toc = task.scaffold.get("toc", [])
        page_map = task.scaffold.get("page_map", {})

        if not toc and not page_map:
            task.processing_status = "failed_scaffold"
            task.error_log.append("Scaffolding produced no usable output")
        elif not toc:
            task.processing_status = "scaffold_partial"
            task.error_log.append("No ToC generated, using page map only")
        else:
            task.processing_status = "scaffold_complete"
            task.error_log.append(
                f"Scaffolding complete: {len(toc)} ToC entries, {len(page_map)} page mappings"
            )

        return task
