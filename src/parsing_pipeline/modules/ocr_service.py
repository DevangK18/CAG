import subprocess
import shutil
import time
from pathlib import Path
from typing import List, Optional, Dict, Any
from src.core.data_contracts import DocumentTask
from src.parsing_pipeline.config import get_config, OCRConfig
from src.parsing_pipeline.instrumentation import get_noop_emitter


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
    ):
        """
        Initialize the OCR service.

        Args:
            output_dir: Directory to store OCR'd PDFs
            language: OCR language(s) (overrides config)
            timeout: Timeout in seconds (overrides config)
            output_type: Output format (overrides config)
            force_ocr: Force OCR even if text exists (overrides config)
            config: OCRConfig instance (default: load from global config)
            trace_emitter: Optional TraceEmitter for instrumentation
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
        self._trace_emitter = trace_emitter or get_noop_emitter()

    def ocr_document(self, task: DocumentTask, trace_emitter=None) -> DocumentTask:
        """
        Apply OCR to a scanned document if classified as such.

        Args:
            task: DocumentTask to process
            trace_emitter: Optional TraceEmitter for instrumentation

        Returns:
            Updated DocumentTask with OCR results
        """
        emitter = trace_emitter or self._trace_emitter

        # Only process scanned documents
        if task.classification != "scanned":
            task.error_log.append("Document not classified as scanned, skipping OCR")
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
            task.error_log.append(
                f"PDF path does not exist for OCR: {task.local_pdf_path}"
            )
            task.processing_status = "failed_ocr"
            return task

        # Generate output path
        input_path = Path(task.local_pdf_path)
        output_filename = f"{task.report_id}_ocred.pdf"
        output_path = self.output_dir / output_filename

        # Trace: OCR config
        emitter.emit(
            "3",
            "ocr_config",
            {
                "force_ocr": self.force_ocr,
                "language": self.language,
                "output_type": self.output_type,
                "timeout": self.timeout,
            },
        )

        # Construct and execute OCR command
        try:
            command = self._construct_ocr_command(str(input_path), str(output_path))
            start_time = time.perf_counter()
            result = self._execute_ocr_command(command)
            duration = time.perf_counter() - start_time

            # Trace: Subprocess result
            stderr_snippet = ""
            if result.stderr:
                stderr_snippet = result.stderr.decode("utf-8", errors="replace")[:500]

            emitter.emit_io(
                "3",
                {"input_path": str(input_path), "timeout": self.timeout},
                {
                    "exit_status": result.returncode,
                    "duration_seconds": round(duration, 2),
                    "output_path": str(output_path) if result.returncode == 0 else None,
                    "stderr_snippet": stderr_snippet if result.returncode != 0 else None,
                },
            )

            if result.returncode == 0:
                # OCR successful
                task.ocred_pdf_path = str(output_path)
                task.processing_status = "ocr_complete"
                task.error_log.append("OCR processing completed successfully")

                # Validate the output
                if self._validate_ocr_output(str(output_path), task):
                    task.error_log.append("OCR output validation passed")
                else:
                    task.error_log.append(
                        "OCR output validation failed - file may be corrupted"
                    )
            else:
                # OCR failed
                task.processing_status = "failed_ocr"
                error_msg = f"OCR command failed with return code {result.returncode}"
                if result.stderr:
                    error_msg += f": {result.stderr.decode('utf-8', errors='replace')}"
                task.error_log.append(error_msg)

                # Trace: Red flag for OCR failure
                emitter.emit_red_flag(
                    "3",
                    "ocr_failed",
                    {
                        "exit_status": result.returncode,
                        "stderr": stderr_snippet,
                        "report_id": task.report_id,
                    },
                )

        except subprocess.TimeoutExpired:
            task.processing_status = "failed_ocr"
            task.error_log.append(f"OCR processing timed out after {self.timeout}s")
            # Trace: Red flag for timeout
            emitter.emit_red_flag(
                "3",
                "ocr_timeout",
                {"timeout_seconds": self.timeout, "report_id": task.report_id},
            )

        except Exception as e:
            task.processing_status = "failed_ocr"
            task.error_log.append(f"OCR processing failed with exception: {str(e)}")

        return task

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

        # Add output type
        command.extend(["--output-type", self.output_type])

        # Add input and output paths
        command.extend([input_path, output_path])

        return command

    def _execute_ocr_command(self, command: List[str]) -> subprocess.CompletedProcess:
        """
        Execute the OCR command using subprocess.

        Args:
            command: OCR command to execute

        Returns:
            CompletedProcess object with result
        """
        return subprocess.run(
            command,
            capture_output=True,
            text=False,  # Keep as bytes for better encoding handling
            timeout=self.timeout,  # Configurable timeout from config
        )

    def _validate_ocr_output(self, output_path: str, task: DocumentTask) -> bool:
        """
        Validate that the OCR output is a valid PDF.

        Args:
            output_path: Path to the OCR'd PDF
            task: DocumentTask for logging

        Returns:
            True if valid, False otherwise
        """
        try:
            output_file = Path(output_path)

            # Check if file exists and has reasonable size
            if not output_file.exists():
                task.error_log.append("OCR output file does not exist")
                return False

            # Minimum size check (PDF header + content should be at least ~1KB)
            if output_file.stat().st_size < 1000:
                task.error_log.append(
                    f"OCR output file too small: {output_file.stat().st_size} bytes"
                )
                return False

            # Check if it looks like a PDF (starts with %PDF-)
            with open(output_file, "rb") as f:
                header = f.read(8)
                if not header.startswith(b"%PDF-"):
                    task.error_log.append(
                        "OCR output does not appear to be a valid PDF"
                    )
                    return False

            return True

        except Exception as e:
            task.error_log.append(f"OCR output validation failed: {str(e)}")
            return False
