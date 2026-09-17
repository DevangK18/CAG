from pathlib import Path
from typing import Optional, List, Dict, Any
import statistics
import fitz  # PyMuPDF
from src.core.data_contracts import DocumentTask
from src.parsing_pipeline.config import get_config, TriageConfig
from src.parsing_pipeline.instrumentation import get_noop_emitter


class TriageService:
    """
    Service to classify PDF documents as either 'native_text' or 'scanned'
    based on statistical text density sampling.
    """

    # P0-05: Configurable constants for triage improvements
    BLANK_PAGE_THRESHOLD = 20  # Pages with fewer chars are considered blank
    BORDERLINE_BAND_LOW = 0.4  # Widened from 0.7
    BORDERLINE_BAND_HIGH = 1.5  # Widened from 1.3
    MID_DOCUMENT_START_PAGE = 10  # Start sampling from page 10 for heavy front-matter skip

    def __init__(
        self,
        sample_pages: Optional[int] = None,
        text_threshold: Optional[int] = None,
        config: Optional[TriageConfig] = None,
        trace_emitter=None,
        skip_blank_pages: bool = True,
        use_median: bool = True,
        sample_mid_document: bool = True,
    ):
        """
        Initialize the triage service.

        Args:
            sample_pages: Maximum number of pages to sample (overrides config)
            text_threshold: Minimum avg non-whitespace chars/page for native_text (overrides config)
            config: TriageConfig instance (default: load from global config)
            trace_emitter: Optional TraceEmitter for instrumentation
            skip_blank_pages: Skip pages with <20 chars when sampling (P0-05)
            use_median: Use median instead of mean for robustness to outliers (P0-05)
            sample_mid_document: Sample from mid-document to avoid heavy front-matter (P0-05)
        """
        # Load from config if not provided
        if config is None:
            config = get_config().triage

        # Allow direct parameter overrides for backward compatibility
        self.sample_pages = sample_pages if sample_pages is not None else config.sample_pages
        self.text_threshold = text_threshold if text_threshold is not None else config.text_threshold
        self._trace_emitter = trace_emitter or get_noop_emitter()

        # P0-05: New options for improved triage
        self.skip_blank_pages = skip_blank_pages
        self.use_median = use_median
        self.sample_mid_document = sample_mid_document

    def triage_document(self, task: DocumentTask, trace_emitter=None) -> DocumentTask:
        """
        Classify a PDF document as native_text or scanned.

        Args:
            task: DocumentTask with local_pdf_path set
            trace_emitter: Optional TraceEmitter for instrumentation

        Returns:
            Updated DocumentTask with classification field set
        """
        emitter = trace_emitter or self._trace_emitter

        if not task.local_pdf_path or not Path(task.local_pdf_path).exists():
            task.error_log.append(f"PDF path does not exist: {task.local_pdf_path}")
            task.processing_status = "failed_triage"
            return task

        try:
            # Open the PDF
            doc = fitz.Document(task.local_pdf_path)

            if doc.page_count == 0:
                task.error_log.append("PDF has no pages")
                task.processing_status = "failed_triage"
                return task

            # P0-05: Determine sampling start page (skip heavy front-matter)
            if self.sample_mid_document and doc.page_count > self.MID_DOCUMENT_START_PAGE + self.sample_pages:
                start_page = self.MID_DOCUMENT_START_PAGE
            else:
                # Fall back to beginning if document is too short
                start_page = 0

            # Trace: Sampling setup
            emitter.emit_io(
                "2",
                {
                    "total_pages": doc.page_count,
                    "target_sample_pages": self.sample_pages,
                    "start_page": start_page,
                    "skip_blank_pages": self.skip_blank_pages,
                    "use_median": self.use_median,
                },
                {},
            )

            # P0-05: Sample text density with blank-page skipping
            page_char_counts: List[Dict[str, Any]] = []
            sampled_char_counts: List[int] = []  # Only non-blank pages for median/mean

            # Iterate through pages starting from start_page
            pages_examined = 0
            for page_num in range(start_page, doc.page_count):
                if len(sampled_char_counts) >= self.sample_pages:
                    break  # Collected enough non-blank samples

                page = doc.load_page(page_num)
                text = page.get_text()
                # Count non-whitespace characters
                char_count = sum(1 for char in text if not char.isspace())
                pages_examined += 1

                page_char_counts.append({
                    "page": page_num,
                    "char_count": char_count,
                    "is_blank": char_count < self.BLANK_PAGE_THRESHOLD,
                })

                # P0-05: Skip blank pages for the char count sample
                if self.skip_blank_pages:
                    if char_count >= self.BLANK_PAGE_THRESHOLD:
                        sampled_char_counts.append(char_count)
                else:
                    sampled_char_counts.append(char_count)

            # Handle edge case: no non-blank pages found in sample range
            if not sampled_char_counts:
                # Fall back to including all pages examined (even blank ones)
                sampled_char_counts = [p["char_count"] for p in page_char_counts]

            # Trace: Per-page char counts sample
            emitter.emit_sample("2", "per_page_char_density", page_char_counts)

            # Close document
            doc.close()

            # P0-05: Use median for robustness to outliers, or mean as fallback
            if self.use_median and len(sampled_char_counts) >= 1:
                avg_chars_per_page = statistics.median(sampled_char_counts)
            elif sampled_char_counts:
                avg_chars_per_page = sum(sampled_char_counts) / len(sampled_char_counts)
            else:
                avg_chars_per_page = 0

            if avg_chars_per_page >= self.text_threshold:
                task.classification = "native_text"
                task.processing_status = "triaged_native"
                # Trace: Classification decision
                emitter.emit_decision(
                    "2",
                    "classification",
                    "native_text",
                    ["native_text", "scanned"],
                    f"avg_chars={avg_chars_per_page:.0f} >= threshold={self.text_threshold}",
                )
            else:
                task.classification = "scanned"
                task.processing_status = "triaged_scanned"
                # Trace: Classification decision
                emitter.emit_decision(
                    "2",
                    "classification",
                    "scanned",
                    ["native_text", "scanned"],
                    f"avg_chars={avg_chars_per_page:.0f} < threshold={self.text_threshold}",
                )

            # P0-05: Widened borderline band (0.4-1.5) to catch more edge cases
            ratio = avg_chars_per_page / self.text_threshold if self.text_threshold > 0 else 0
            blank_count = len(page_char_counts) - len(sampled_char_counts) if self.skip_blank_pages else 0

            # P1-15: Emit output data with classification results
            emitter.emit_io(
                "2",
                {},  # Input already emitted at phase start
                {
                    "classification": task.classification,
                    "avg_chars": round(avg_chars_per_page, 1),
                    "ratio": round(ratio, 2),
                    "blank_pages_skipped": blank_count,
                    "effective_sample_size": len(sampled_char_counts),
                },
            )

            if self.BORDERLINE_BAND_LOW <= ratio <= self.BORDERLINE_BAND_HIGH:
                emitter.emit_red_flag(
                    "2",
                    "borderline_classification",
                    {
                        "avg_chars": round(avg_chars_per_page, 1),
                        "threshold": self.text_threshold,
                        "ratio": round(ratio, 2),
                        "classification": task.classification,
                        "sampled_pages": len(sampled_char_counts),
                        "blank_pages_skipped": blank_count,
                    },
                )

        except Exception as e:
            task.error_log.append(f"Triage failed with error: {str(e)}")
            task.processing_status = "failed_triage"

        return task
