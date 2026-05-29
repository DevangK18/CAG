from pathlib import Path
from typing import Optional, List, Dict, Any
import fitz  # PyMuPDF
from src.core.data_contracts import DocumentTask
from src.parsing_pipeline.config import get_config, TriageConfig
from src.parsing_pipeline.instrumentation import get_noop_emitter


class TriageService:
    """
    Service to classify PDF documents as either 'native_text' or 'scanned'
    based on statistical text density sampling.
    """

    def __init__(
        self,
        sample_pages: Optional[int] = None,
        text_threshold: Optional[int] = None,
        config: Optional[TriageConfig] = None,
        trace_emitter=None,
    ):
        """
        Initialize the triage service.

        Args:
            sample_pages: Maximum number of pages to sample (overrides config)
            text_threshold: Minimum avg non-whitespace chars/page for native_text (overrides config)
            config: TriageConfig instance (default: load from global config)
            trace_emitter: Optional TraceEmitter for instrumentation
        """
        # Load from config if not provided
        if config is None:
            config = get_config().triage

        # Allow direct parameter overrides for backward compatibility
        self.sample_pages = sample_pages if sample_pages is not None else config.sample_pages
        self.text_threshold = text_threshold if text_threshold is not None else config.text_threshold
        self._trace_emitter = trace_emitter or get_noop_emitter()

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

            # Determine number of pages to sample
            num_sample_pages = min(self.sample_pages, doc.page_count)
            if num_sample_pages == 0:
                task.error_log.append("PDF has no pages")
                task.processing_status = "failed_triage"
                return task

            # Trace: Sampling setup
            emitter.emit_io(
                "2",
                {"total_pages": doc.page_count, "sample_pages": num_sample_pages},
                {},
            )

            # Sample text density across pages - collect per-page data for tracing
            page_char_counts: List[Dict[str, Any]] = []
            total_chars = 0
            for page_num in range(num_sample_pages):
                page = doc.load_page(page_num)
                text = page.get_text()
                # Count non-whitespace characters
                char_count = sum(1 for char in text if not char.isspace())
                total_chars += char_count
                page_char_counts.append({"page": page_num, "char_count": char_count})

            # Trace: Per-page char counts sample
            emitter.emit_sample("2", "per_page_char_density", page_char_counts)

            # Close document
            doc.close()

            # Classify based on average characters per page
            avg_chars_per_page = total_chars / num_sample_pages

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

            # Trace: Red flag for borderline classification (within 30% of threshold)
            ratio = avg_chars_per_page / self.text_threshold if self.text_threshold > 0 else 0
            if 0.7 <= ratio <= 1.3:
                emitter.emit_red_flag(
                    "2",
                    "borderline_classification",
                    {
                        "avg_chars": round(avg_chars_per_page, 1),
                        "threshold": self.text_threshold,
                        "ratio": round(ratio, 2),
                        "classification": task.classification,
                    },
                )

        except Exception as e:
            task.error_log.append(f"Triage failed with error: {str(e)}")
            task.processing_status = "failed_triage"

        return task
