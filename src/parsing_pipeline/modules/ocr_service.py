import subprocess
import shutil
from pathlib import Path
from typing import List, Optional
from src.core.data_contracts import DocumentTask


class OCRService:
    """
    Service to apply Optical Character Recognition to scanned PDF documents,
    converting them to text-selectable PDFs using OCRmyPDF.
    """

    def __init__(self, output_dir: str = "data/processed/ocred"):
        """
        Initialize the OCR service.

        Args:
            output_dir: Directory to store OCR'd PDFs
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def ocr_document(self, task: DocumentTask) -> DocumentTask:
        """
        Apply OCR to a scanned document if classified as such.

        Args:
            task: DocumentTask to process

        Returns:
            Updated DocumentTask with OCR results
        """
        # Only process scanned documents
        if task.classification != "scanned":
            task.error_log.append("Document not classified as scanned, skipping OCR")
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

        # Construct and execute OCR command
        try:
            command = self._construct_ocr_command(str(input_path), str(output_path))
            result = self._execute_ocr_command(command)

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
        return [
            "ocrmypdf",
            "--force-ocr",  # Force OCR even if text layer exists
            "--invalidate-digital-signatures",  # Allow OCR on signed PDFs
            "--language",
            "eng",  # English only (Hindi language pack not installed)
            "--output-type",
            "pdfa",  # PDF-A output format for archival
            input_path,
            output_path,
        ]

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
            timeout=600,  # 10 minute timeout for processing
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
