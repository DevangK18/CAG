import logging
import os
import signal
import json
import subprocess
import time
from pathlib import Path
from typing import List, Optional

import fitz  # PyMuPDF

from src.core.data_contracts import DocumentTask
from src.parsing_pipeline.config import get_config, OCRConfig
from src.parsing_pipeline.instrumentation import get_noop_emitter

logger = logging.getLogger(__name__)

# Measured ~3.4 s/page on an e2-standard-4, plus 1-2 min for the final PDF steps (A-3-01)
DEFAULT_TIMEOUT_PER_PAGE = 8
# A page with fewer non-whitespace chars has no usable text layer
MIN_TEXT_CHARS_PER_PAGE = 20
# Photo pages legitimately stay empty after OCR, so require text on half the pages
MIN_TEXT_PAGE_RATIO = 0.5
STDERR_TAIL_CHARS = 2000


class OCRService:
    """
    Service to apply Optical Character Recognition to scanned PDF documents,
    converting them to text-selectable PDFs using OCRmyPDF.
    """

    def __init__(
        self,
        output_dir: str = "data/processed/ocred",
        language: Optional[str] = None,
        timeout: Optional[int] = None,
        output_type: Optional[str] = None,
        force_ocr: Optional[bool] = None,
        config: Optional[OCRConfig] = None,
        trace_emitter=None,
        timeout_per_page: Optional[int] = None,
    ):
        """
        Initialize the OCR service.

        Args:
            output_dir: Directory to store OCR'd PDFs
            language: OCR language(s) (overrides config)
            timeout: Minimum timeout in seconds (overrides config)
            output_type: Output format (overrides config)
            force_ocr: Force OCR even if text exists (overrides config)
            config: OCRConfig instance (default: load from global config)
            trace_emitter: Optional TraceEmitter for instrumentation
            timeout_per_page: Seconds allowed per page (overrides config)
        """
        # Load from config if not provided
        if config is None:
            config = get_config().ocr

        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Apply config with optional overrides
        self.language = language if language is not None else config.language
        self.timeout = timeout if timeout is not None else config.timeout
        self.output_type = output_type if output_type is not None else config.output_type
        self.force_ocr = force_ocr if force_ocr is not None else config.force_ocr
        # Newer keys: read defensively so an older OCRConfig still works
        self.timeout_per_page = (
            timeout_per_page
            if timeout_per_page is not None
            else getattr(config, "timeout_per_page", DEFAULT_TIMEOUT_PER_PAGE)
        )
        self.optimize = getattr(config, "optimize", None)
        self.rotate_pages = getattr(config, "rotate_pages", False)
        self._trace_emitter = trace_emitter or get_noop_emitter()

    def output_path_for(self, report_id: str) -> Path:
        """Where the OCR'd PDF for a report is written."""
        return self.output_dir / f"{report_id}_ocred.pdf"

    def effective_timeout(self, page_count: int) -> int:
        """Same shape as the Docling limit: a floor, scaled up for long scans."""
        return max(int(self.timeout), int(page_count * self.timeout_per_page))

    def ocr_document(self, task: DocumentTask, trace_emitter=None) -> DocumentTask:
        """
        Apply OCR to a scanned document if classified as such.

        A complete OCR'd PDF already in the output directory is reused, and so
        is one ocrmypdf finished writing before it hit the timeout. Every
        failure sets processing_status="failed_ocr", is logged at ERROR, and
        leaves the reason as the last error_log entry.

        Args:
            task: DocumentTask to process
            trace_emitter: Optional TraceEmitter for instrumentation

        Returns:
            Updated DocumentTask with OCR results
        """
        emitter = trace_emitter or self._trace_emitter

        # Only process scanned documents
        if task.classification != "scanned":
            logger.debug(f"[{task.report_id}] Not scanned, skipping OCR")

            # P1-15: Emit success-path for native_text classification
            emitter.emit_io(
                "3",
                {"classification": task.classification},
                {"status": "skipped", "reason": "native_text - OCR not needed"},
            )

            # Trace: Skip decision for native PDFs
            emitter.emit_decision(
                "3",
                "ocr_skip",
                "skipped",
                ["process", "skipped"],
                f"classification={task.classification}, not scanned",
            )
            return task

        if not task.local_pdf_path or not Path(task.local_pdf_path).exists():
            return self._fail(
                task, f"PDF path does not exist for OCR: {task.local_pdf_path}"
            )

        # Generate output path
        input_path = Path(task.local_pdf_path)
        output_path = self.output_path_for(task.report_id)

        try:
            page_count = self._page_count(input_path)
        except Exception as e:
            return self._fail(task, f"Cannot open PDF for OCR: {e}")

        # Reuse a finished output from an earlier run (ocred/ is synced from GCS on the VM)
        if output_path.exists():
            problem = self.output_problem(output_path, page_count, reuse=True)
            if problem is None:
                logger.info(f"[{task.report_id}] Reusing complete OCR output: {output_path}")
                emitter.emit_decision(
                    "3", "ocr_reuse", "reused", ["reused", "run"],
                    f"{output_path.name} is complete ({page_count} pages)",
                )
                return self._succeed(task, output_path, "OCR output reused from an earlier run")
            logger.info(f"[{task.report_id}] Existing OCR output not reusable ({problem}); re-running OCR")

        timeout = self.effective_timeout(page_count)

        # Trace: OCR config
        emitter.emit(
            "3",
            "ocr_config",
            {
                "force_ocr": self.force_ocr,
                "language": self.language,
                "output_type": self.output_type,
                "timeout": timeout,
                "page_count": page_count,
            },
        )

        logger.info(f"[{task.report_id}] Running OCR ({page_count} pages, timeout {timeout}s)")

        # Construct and execute OCR command
        try:
            ocr_input = input_path
            if self.rotate_pages:
                ocr_input = self._upright_copy(input_path, output_path, task.report_id) or input_path
            command = self._construct_ocr_command(str(ocr_input), str(output_path))
            start_time = time.perf_counter()
            try:
                result = self._execute_ocr_command(command, timeout=timeout)
            finally:
                # The upright copy is only OCR input; it must not be kept or uploaded
                if ocr_input != input_path:
                    Path(ocr_input).unlink(missing_ok=True)
            duration = time.perf_counter() - start_time

            # Trace: Subprocess result
            stderr_tail = self._stderr_tail(result.stderr)

            emitter.emit_io(
                "3",
                {"input_path": str(input_path), "timeout": timeout},
                {
                    "exit_status": result.returncode,
                    "duration_seconds": round(duration, 2),
                    "output_path": str(output_path) if result.returncode == 0 else None,
                    "stderr_snippet": stderr_tail[-500:] if result.returncode != 0 else None,
                },
            )

            if result.returncode == 0:
                if self._validate_ocr_output(str(output_path), task, page_count):
                    return self._succeed(task, output_path, "OCR processing completed successfully")
                return self._fail(
                    task, f"OCR output validation failed: {task.error_log[-1]}"
                )

            # Trace: Red flag for OCR failure
            emitter.emit_red_flag(
                "3",
                "ocr_failed",
                {
                    "exit_status": result.returncode,
                    "stderr": stderr_tail[-500:],
                    "report_id": task.report_id,
                },
            )
            error_msg = f"OCR command failed with return code {result.returncode}"
            if stderr_tail:
                error_msg += f": {stderr_tail}"
            return self._fail(task, error_msg)

        except subprocess.TimeoutExpired:
            # ocrmypdf can write a complete file and still be killed in its last steps
            problem = self.output_problem(output_path, page_count)
            if problem is None:
                logger.warning(
                    f"[{task.report_id}] OCR timed out after {timeout}s but the output "
                    f"is complete; using it"
                )
                return self._succeed(
                    task, output_path, f"OCR timed out after {timeout}s; output was complete"
                )
            # Trace: Red flag for timeout
            emitter.emit_red_flag(
                "3",
                "ocr_timeout",
                {"timeout_seconds": timeout, "report_id": task.report_id},
            )
            return self._fail(
                task,
                f"OCR processing timed out after {timeout}s ({page_count} pages); "
                f"output not usable: {problem}",
            )

        except Exception as e:
            return self._fail(task, f"OCR processing failed with exception: {e}")

    # Tesseract orientation detection, used only for sideways pages: at 150 dpi it
    # finds them reliably, while its 180-degree readings are noise on normal scans
    OSD_DPI = 150
    OSD_MIN_CONFIDENCE = 1.5

    def _upright_copy(self, input_path: Path, output_path: Path, report_id: str) -> Optional[Path]:
        """
        A copy of the scan with sideways pages turned upright (via /Rotate), or None
        when no page needs it. ocrmypdf's own --rotate-pages needs a confidence these
        scans rarely reach, so pages scanned sideways were OCR'd as garbage.
        """
        turned = {}
        try:
            with fitz.open(str(input_path)) as doc:
                for i, page in enumerate(doc):
                    rotate = self._osd_rotation(page)
                    if rotate:
                        turned[i] = rotate
                if not turned:
                    return None
                for i, rotate in turned.items():
                    doc[i].set_rotation((doc[i].rotation + rotate) % 360)
                upright = Path(str(output_path) + ".upright.pdf")
                doc.save(str(upright))
        except Exception as e:
            logger.warning(f"[{report_id}] Page orientation check failed: {e}")
            return None
        logger.info(f"[{report_id}] Turned {len(turned)} sideways pages upright before OCR: {sorted(turned)}")
        return upright

    def _osd_rotation(self, page) -> int:
        """Clockwise degrees (90 or 270) that make a sideways page upright, else 0."""
        import re
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".png") as image:
            page.get_pixmap(dpi=self.OSD_DPI).save(image.name)
            try:
                result = subprocess.run(
                    ["tesseract", image.name, "-", "--psm", "0"],
                    capture_output=True, text=True, timeout=60,
                )
            except (OSError, subprocess.TimeoutExpired):
                return 0
        orientation = re.search(r"Orientation in degrees: (\d+)", result.stdout)
        rotate = re.search(r"Rotate: (\d+)", result.stdout)
        confidence = re.search(r"Orientation confidence: ([\d.]+)", result.stdout)
        if not (orientation and rotate and confidence):
            return 0
        if int(orientation.group(1)) not in (90, 270) or float(confidence.group(1)) < self.OSD_MIN_CONFIDENCE:
            return 0
        return int(rotate.group(1))

    @staticmethod
    def settings_stamp_path(output_path) -> Path:
        return Path(str(output_path) + ".settings.json")

    @staticmethod
    def current_settings() -> dict:
        """OCR settings an output must have been made with to be reused."""
        from src.parsing_pipeline.config import get_config

        return {"rotate_pages": bool(getattr(get_config().ocr, "rotate_pages", False))}

    def _succeed(self, task: DocumentTask, output_path: Path, message: str) -> DocumentTask:
        try:
            self.settings_stamp_path(output_path).write_text(json.dumps(self.current_settings()))
        except OSError as e:
            logger.warning(f"[{task.report_id}] Could not write OCR settings stamp: {e}")
        task.ocred_pdf_path = str(output_path)
        task.processing_status = "ocr_complete"
        task.error_log.append(message)
        return task

    def _fail(self, task: DocumentTask, message: str) -> DocumentTask:
        # main.py reports error_log[-1], so the reason must be the last entry
        logger.error(f"[{task.report_id}] OCR failed: {message}")
        task.processing_status = "failed_ocr"
        task.error_log.append(message)
        return task

    @staticmethod
    def _page_count(pdf_path) -> int:
        with fitz.open(str(pdf_path)) as doc:
            return doc.page_count

    @staticmethod
    def _stderr_tail(stderr) -> str:
        if not stderr:
            return ""
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return stderr.strip()[-STDERR_TAIL_CHARS:]

    @classmethod
    def output_problem(cls, output_path, expected_pages: int, reuse: bool = False) -> Optional[str]:
        """
        Why an OCR'd PDF can't be used, or None if it is complete.

        Complete means it opens, has the same page count as the input, and
        carries a text layer on at least MIN_TEXT_PAGE_RATIO of its pages.
        """
        output_file = Path(output_path)
        if not output_file.exists():
            return "output file does not exist"
        # An earlier output made with other settings (e.g. before pages were turned
        # upright) is redone, not reused
        if reuse:
            try:
                stamp = json.loads(cls.settings_stamp_path(output_file).read_text())
            except (OSError, ValueError):
                stamp = None
            if stamp != cls.current_settings():
                return "made with different OCR settings"
        try:
            # Minimum size check (PDF header + content should be at least ~1KB)
            size = output_file.stat().st_size
            if size < 1000:
                return f"output file too small: {size} bytes"
            with open(output_file, "rb") as f:
                if not f.read(8).startswith(b"%PDF-"):
                    return "output does not appear to be a valid PDF"
            with fitz.open(str(output_file)) as doc:
                if doc.page_count != expected_pages:
                    return f"output has {doc.page_count} pages, input has {expected_pages}"
                text_pages = sum(
                    1
                    for page in doc
                    if sum(not c.isspace() for c in page.get_text()) >= MIN_TEXT_CHARS_PER_PAGE
                )
            if expected_pages and text_pages / expected_pages < MIN_TEXT_PAGE_RATIO:
                return f"only {text_pages}/{expected_pages} pages have a text layer"
        except Exception as e:
            return f"output cannot be read: {e}"
        return None

    @classmethod
    def is_complete_output(cls, input_pdf_path, output_path) -> bool:
        """True if output_path is a complete OCR of input_pdf_path (for cache checks)."""
        try:
            expected = cls._page_count(input_pdf_path)
        except Exception:
            return False
        return cls.output_problem(output_path, expected, reuse=True) is None

    def _construct_ocr_command(self, input_path: str, output_path: str) -> List[str]:
        """
        Construct the OCRmyPDF command line arguments.

        Args:
            input_path: Path to input PDF
            output_path: Path to output OCR'd PDF

        Returns:
            List of command arguments
        """
        command = ["ocrmypdf"]

        # Add force-ocr flag if enabled
        if self.force_ocr:
            command.append("--force-ocr")

        # Allow OCR on signed PDFs
        command.append("--invalidate-digital-signatures")

        # Add language configuration
        command.extend(["--language", self.language])

        # Add output type ('pdf' skips the slow Ghostscript PDF/A pass)
        command.extend(["--output-type", self.output_type])

        if self.optimize is not None:
            command.extend(["--optimize", str(self.optimize)])


        # Add input and output paths
        command.extend([input_path, output_path])

        return command

    def _execute_ocr_command(
        self, command: List[str], timeout: Optional[int] = None
    ) -> subprocess.CompletedProcess:
        """
        Execute the OCR command, killing its whole process group on timeout.

        Args:
            command: OCR command to execute
            timeout: Seconds before the run is killed (default: self.timeout)

        Returns:
            CompletedProcess object with result

        Raises:
            subprocess.TimeoutExpired: if the command runs past the timeout
        """
        timeout = timeout if timeout is not None else self.timeout
        # Own session, so tesseract workers can be killed with ocrmypdf
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
            try:
                proc.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                pass
            raise
        return subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)

    def _validate_ocr_output(
        self, output_path: str, task: DocumentTask, expected_pages: Optional[int] = None
    ) -> bool:
        """
        Validate the OCR output, recording the reason in task.error_log on failure.

        Args:
            output_path: Path to the OCR'd PDF
            task: DocumentTask for logging
            expected_pages: Input page count; when None, the output's own count is used

        Returns:
            True if valid, False otherwise
        """
        if expected_pages is None:
            try:
                expected_pages = self._page_count(output_path)
            except Exception:
                expected_pages = 0
        problem = self.output_problem(output_path, expected_pages)
        if problem:
            task.error_log.append(f"OCR {problem}")
            return False
        return True
