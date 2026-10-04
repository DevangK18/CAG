import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
import statistics
import fitz  # PyMuPDF
from src.core.data_contracts import DocumentTask
from src.parsing_pipeline.config import get_config, TriageConfig
from src.parsing_pipeline.instrumentation import get_noop_emitter

logger = logging.getLogger(__name__)


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
    # A scan whose pages carry only a running header must not pass as native (A-1-06)
    IMAGE_PAGE_COVERAGE = 0.8  # Images cover at least this share of the page...
    IMAGE_PAGE_MAX_CHARS = 300  # ...and the page has fewer chars: count it as 0

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

                # A page image with a little text (header, page number) is a scan
                image_only = (
                    self.BLANK_PAGE_THRESHOLD <= char_count < self.IMAGE_PAGE_MAX_CHARS
                    and self._image_coverage(page) >= self.IMAGE_PAGE_COVERAGE
                )

                page_char_counts.append({
                    "page": page_num,
                    "char_count": char_count,
                    "is_blank": char_count < self.BLANK_PAGE_THRESHOLD,
                    "image_only": image_only,
                })

                if image_only:
                    # Counted as an empty page, but kept in the sample (not skipped as blank)
                    sampled_char_counts.append(0)
                # P0-05: Skip blank pages for the char count sample
                elif self.skip_blank_pages:
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

    @staticmethod
    def _image_coverage(page) -> float:
        """Share of the page area covered by images (0.0 if it can't be measured)."""
        try:
            rect = page.rect
            area = rect.width * rect.height
            if area <= 0:
                return 0.0
            covered = 0.0
            for info in page.get_image_info():
                bbox = fitz.Rect(info["bbox"]) & rect
                if not bbox.is_empty:
                    covered += bbox.width * bbox.height
            return min(covered / area, 1.0)
        except Exception:
            return 0.0


class TriageCache:
    """
    Phase 2-3 cache markers ({report_id}_triage.json / _ocr.json), valid only
    for the same PDF content and triage settings (A-1-04, C-R-10).

    A scanned report is a hit only if its OCR'd PDF is still there and complete,
    so a hit can never fall back to the image-only original.
    """

    def __init__(
        self,
        cache_dir,
        text_threshold: Optional[int] = None,
        sample_pages: Optional[int] = None,
        config: Optional[TriageConfig] = None,
    ):
        if config is None:
            config = get_config().triage
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.text_threshold = text_threshold if text_threshold is not None else config.text_threshold
        self.sample_pages = sample_pages if sample_pages is not None else config.sample_pages
        self._hashes: Dict[Tuple[str, int, float], str] = {}

    def pdf_sha256(self, pdf_path) -> str:
        """Content hash, memoised per (path, size, mtime) within this run."""
        path = Path(pdf_path)
        stat = path.stat()
        key = (str(path.resolve()), stat.st_size, stat.st_mtime)
        if key not in self._hashes:
            digest = hashlib.sha256()
            with open(path, "rb") as f:
                for block in iter(lambda: f.read(1 << 20), b""):
                    digest.update(block)
            self._hashes[key] = digest.hexdigest()
        return self._hashes[key]

    def _triage_file(self, report_id: str) -> Path:
        return self.cache_dir / f"{report_id}_triage.json"

    def _ocr_file(self, report_id: str) -> Path:
        return self.cache_dir / f"{report_id}_ocr.json"

    def _fingerprint(self, task: DocumentTask) -> Dict[str, Any]:
        return {
            "pdf_sha256": self.pdf_sha256(task.local_pdf_path),
            "text_threshold": self.text_threshold,
            "sample_pages": self.sample_pages,
        }

    @staticmethod
    def _read(path: Path) -> Optional[Dict[str, Any]]:
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return None

    def load(self, task: DocumentTask) -> Optional[DocumentTask]:
        """
        Restore classification (and the OCR'd path) from the cache.

        Returns the updated task on a hit, None on a miss. A miss leaves the
        task untouched, so it can go through triage and OCR as new.
        """
        if not task.local_pdf_path or not Path(task.local_pdf_path).exists():
            return None
        triage = self._read(self._triage_file(task.report_id))
        if not triage:
            return None
        fingerprint = self._fingerprint(task)
        if any(triage.get(k) != v for k, v in fingerprint.items()):
            logger.info(f"[{task.report_id}] Triage cache is stale (PDF or settings changed)")
            return None

        classification = triage.get("classification")
        if classification == "native_text":
            task.classification = classification
            task.processing_status = "triage_complete"
            return task
        if classification != "scanned":
            return None

        ocr = self._read(self._ocr_file(task.report_id))
        ocred_path = (ocr or {}).get("ocred_pdf_path")
        if not ocr or ocr.get("pdf_sha256") != fingerprint["pdf_sha256"] or not ocred_path:
            return None
        # Imported here: ocr_service is only needed for scanned hits
        from src.parsing_pipeline.modules.ocr_service import OCRService

        if not OCRService.is_complete_output(task.local_pdf_path, ocred_path):
            logger.warning(
                f"[{task.report_id}] OCR cache points to a missing or incomplete file "
                f"({ocred_path}); re-running OCR"
            )
            return None
        task.classification = classification
        task.ocred_pdf_path = str(ocred_path)
        task.processing_status = "ocr_complete"
        return task

    def store_triage(self, task: DocumentTask) -> None:
        with open(self._triage_file(task.report_id), "w") as f:
            json.dump(
                {
                    "classification": task.classification,
                    **self._fingerprint(task),
                    "timestamp": datetime.now().isoformat(),
                },
                f,
            )

    def store_ocr(self, task: DocumentTask) -> None:
        with open(self._ocr_file(task.report_id), "w") as f:
            json.dump(
                {
                    "status": "ocr_complete",
                    "ocred_pdf_path": task.ocred_pdf_path,
                    "pdf_sha256": self.pdf_sha256(task.local_pdf_path),
                    "timestamp": datetime.now().isoformat(),
                },
                f,
            )
