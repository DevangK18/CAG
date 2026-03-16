from pathlib import Path
import fitz  # PyMuPDF
from src.core.data_contracts import DocumentTask


class TriageService:
    """
    Service to classify PDF documents as either 'native_text' or 'scanned'
    based on statistical text density sampling.
    """

    def __init__(self, sample_pages: int = 10, text_threshold: int = 150):
        """
        Initialize the triage service.

        Args:
            sample_pages: Maximum number of pages to sample for classification
            text_threshold: Minimum average non-whitespace characters per page to classify as native_text
        """
        self.sample_pages = sample_pages
        self.text_threshold = text_threshold

    def triage_document(self, task: DocumentTask) -> DocumentTask:
        """
        Classify a PDF document as native_text or scanned.

        Args:
            task: DocumentTask with local_pdf_path set

        Returns:
            Updated DocumentTask with classification field set
        """
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

            # Sample text density across pages
            total_chars = 0
            for page_num in range(num_sample_pages):
                page = doc.load_page(page_num)
                text = page.get_text()
                # Count non-whitespace characters
                total_chars += sum(1 for char in text if not char.isspace())

            # Close document
            doc.close()

            # Classify based on average characters per page
            avg_chars_per_page = total_chars / num_sample_pages

            if avg_chars_per_page >= self.text_threshold:
                task.classification = "native_text"
                task.processing_status = "triaged_native"
            else:
                task.classification = "scanned"
                task.processing_status = "triaged_scanned"

        except Exception as e:
            task.error_log.append(f"Triage failed with error: {str(e)}")
            task.processing_status = "failed_triage"

        return task
