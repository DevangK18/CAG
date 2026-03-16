"""
TableExtractor: Microsoft's Table-Transformer (TATR) for table structure recognition.
Combines TATR model for identifying table cells with Tesseract OCR for text extraction.

PHASE 1 - P0-1: Now includes structured table extraction for queryable JSON output.
"""

import torch
from transformers import TableTransformerForObjectDetection, DetrImageProcessor
from PIL import Image
import fitz  # PyMuPDF
from typing import List, Optional, Dict, Any, Tuple
import pytesseract
from pathlib import Path

from src.core.data_contracts import ExtractedContent
from src.parsing_pipeline.modules.structured_table_extractor import StructuredTableExtractor


class TableExtractor:
    """
    Extracts tabular content using Table-Transformer (TATR) for structure recognition
    followed by Tesseract OCR for cell content extraction.
    """

    def __init__(self, conf_threshold: float = 0.75, ocr_psm: int = 6):
        """Initialize the Table-Transformer model and processors.

        Args:
            conf_threshold: Confidence threshold for model detections (0.0-1.0)
            ocr_psm: Tesseract PSM mode for OCR (6 = uniform block of text)
        """
        self.conf_threshold = max(0.1, min(1.0, conf_threshold))  # Clamp to valid range
        self.ocr_psm = ocr_psm

        # Determine device (GPU preferred for performance)
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        # Load pre-trained Table-Transformer for structure recognition
        self.model = (
            TableTransformerForObjectDetection.from_pretrained(
                "microsoft/table-transformer-structure-recognition"
            )
            .to(self.device)
            .eval()
        )

        # Image processor for input preparation
        self.processor = DetrImageProcessor.from_pretrained(
            "microsoft/table-transformer-structure-recognition"
        )

        # P0-1: Initialize structured table extractor
        self.structured_extractor = StructuredTableExtractor()

        print(f"TableExtractor initialized with device: {self.device}")
        print(
            f"Model loaded: {self.model.__class__.__name__} (conf: {self.conf_threshold})"
        )

    def shutdown(self):
        """Clean up model resources (call when done processing)."""
        if hasattr(self, "model"):
            del self.model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def _prepare_table_image(
        self, pdf_path: str, page_num: int, bbox: List[float]
    ) -> Image.Image:
        """
        Renders a specific page of a PDF and crops the image to the table's bounding box.

        Args:
            pdf_path: Path to the source PDF document.
            page_num: The 0-indexed physical page number containing the table.
            bbox: The [x0, y0, x1, y1] bounding box coordinates in PDF space.

        Returns:
            A PIL Image object of the cropped table at 300 DPI.

        Raises:
            ValueError: If the bounding box is invalid or cropping fails.
        """
        if len(bbox) != 4:
            raise ValueError(
                f"Bounding box must have 4 coordinates, got {len(bbox)}: {bbox}"
            )

        # Open PDF document
        doc = fitz.open(pdf_path)

        try:
            # Load the specified page
            page = doc.load_page(page_num)

            # Render page at 300 DPI (a common standard for OCR accuracy)
            zoom_matrix = fitz.Matrix(
                300 / 72, 300 / 72
            )  # Convert from PDF units (72 DPI) to 300 DPI
            pix = page.get_pixmap(matrix=zoom_matrix)

            # Convert to PIL Image
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

            # Scale bounding box from PDF coordinates to pixel coordinates
            scale_x = pix.width / page.rect.width
            scale_y = pix.height / page.rect.height

            # Apply scaling transformation to bbox coordinates
            scaled_bbox = (
                bbox[0] * scale_x,  # x0
                bbox[1] * scale_y,  # y0
                bbox[2] * scale_x,  # x1
                bbox[3] * scale_y,  # y1
            )

            # Crop the image to the table bounding box
            cropped_img = img.crop(scaled_bbox)

            return cropped_img

        except Exception as e:
            doc.close()
            raise ValueError(f"Failed to prepare table image: {str(e)}") from e
        finally:
            doc.close()

    def _get_table_structure(self, table_image: Image.Image) -> Dict[str, Any]:
        """
        Uses the Table-Transformer model to detect table structure (rows, columns, headers).

        Args:
            table_image: PIL Image of the isolated table.

        Returns:
            Dictionary containing detected bounding boxes and their classes.
        """
        # Prepare image for model inference
        inputs = self.processor(images=table_image, return_tensors="pt")

        # Move inputs to the same device as the model
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        # Perform inference without gradient computation
        with torch.no_grad():
            outputs = self.model(**inputs)

        # Post-process detections
        # Create target_sizes as required by the post-processing function
        target_sizes = [table_image.size[::-1]]  # [height, width] format

        # Post-process object detection results
        results = self.processor.post_process_object_detection(
            outputs,
            threshold=self.conf_threshold,  # Use configurable confidence threshold
            target_sizes=target_sizes,
        )

        return results[0]  # Return results for the single image

    def _reconstruct_cell_grid(
        self, structure_results: Dict[str, Any], table_image: Image.Image
    ) -> Optional[List[List[Dict]]]:
        """
        Reconstructs a logical 2D grid of cells from TATR model detections.

        Args:
            structure_results: Output from post-process_object_detection.
            table_image: PIL Image (used for image bounds checking).

        Returns:
            2D list representing table rows → cells, or None if no valid structure.
        """
        # Access label mapping from processor (more reliable than model.config)
        try:
            id2label = self.processor.id2label
        except AttributeError:
            # Fallback to model config if processor doesn't have it
            id2label = getattr(self.model.config, "id2label", {})

        # Extract raw detections
        boxes = structure_results["boxes"].cpu().numpy().tolist()
        labels = structure_results["labels"].cpu().numpy().tolist()

        # Separate detections by class
        detected_elements = {}
        for box, label_id in zip(boxes, labels):
            label_id_int = int(label_id)  # Ensure integer key
            label_name = id2label.get(label_id_int, f"class_{label_id_int}")
            if label_name not in detected_elements:
                detected_elements[label_name] = []
            detected_elements[label_name].append(box)

        # Extract rows and columns (ignore other elements for now)
        # Be more flexible with label names
        rows = []
        columns = []

        for label_name, boxes_list in detected_elements.items():
            if "row" in label_name.lower():
                rows.extend(boxes_list)
            elif "column" in label_name.lower():
                columns.extend(boxes_list)

        # Must have both rows and columns to proceed
        if not rows or not columns:
            return None

        # Sort rows by Y-coordinate (top to bottom)
        rows.sort(key=lambda r: r[1])  # r[1] is Y0

        # Sort columns by X-coordinate (left to right)
        columns.sort(key=lambda c: c[0])  # c[0] is X0

        # Build cell grid by calculating intersections
        cell_grid = []
        for row_box in rows:
            row_cells = []
            for col_box in columns:
                # Calculate intersection rectangle
                cell_bbox = [
                    max(row_box[0], col_box[0]),  # max X0
                    max(row_box[1], col_box[1]),  # max Y0
                    min(row_box[2], col_box[2]),  # min X1
                    min(row_box[3], col_box[3]),  # min Y1
                ]

                # Validate intersection has positive area
                if cell_bbox[2] > cell_bbox[0] and cell_bbox[3] > cell_bbox[1]:
                    row_cells.append({"bbox": cell_bbox})

            # Sort cells in row by X-coordinate (left to right)
            row_cells.sort(key=lambda c: c["bbox"][0])

            cell_grid.append(row_cells)

        return cell_grid if cell_grid else None

    def _apply_ocr_to_cells(
        self, cell_grid: List[List[Dict]], table_image: Image.Image
    ) -> List[List[str]]:
        """
        Applies OCR to each cell in the reconstructed grid to extract text content.

        Args:
            cell_grid: 2D list of cell dictionaries with 'bbox' keys.
            table_image: PIL Image of the full table.

        Returns:
            2D list of strings representing the table's text content.
        """
        reconstructed_data = []

        for row in cell_grid:
            row_data = []
            for cell in row:
                cell_bbox = cell["bbox"]
                try:
                    # Crop cell image from full table image
                    cell_image = table_image.crop(cell_bbox)

                    # Apply OCR with configurable PSM mode
                    cell_text = pytesseract.image_to_string(
                        cell_image,
                        config=f"--psm {self.ocr_psm}",
                    )

                    # Normalize text: remove extra whitespace and normalize line breaks
                    cell_text = " ".join(cell_text.split())
                    row_data.append(cell_text)

                except pytesseract.TesseractError as e:
                    # On OCR failure, add empty string but continue processing
                    print(f"OCR failed for cell bbox {cell_bbox}: {e}")
                    row_data.append("")
                except Exception as e:
                    # Handle other image processing errors
                    print(f"Cell processing failed for bbox {cell_bbox}: {e}")
                    row_data.append("")

            reconstructed_data.append(row_data)

        return reconstructed_data

    def _serialize_to_markdown(self, data: List[List[str]]) -> str:
        """
        Converts a 2D list of strings into GitHub-flavored Markdown table format.

        Args:
            data: 2D list representing table rows and cells.

        Returns:
            String containing the GitHub-flavored Markdown table.
        """
        if not data or not any(len(row) > 0 for row in data):
            return ""

        # Calculate maximum column count
        num_columns = max(len(row) for row in data) if data else 0

        # Pad shorter rows to ensure consistent column count
        padded_data = []
        for row in data:
            while len(row) < num_columns:
                row.append("")
            padded_data.append(row)

        # Create header row (first row)
        header = " | ".join(str(cell) for cell in padded_data[0])

        # Create separator row
        separator = " | ".join(["---"] * num_columns)

        # Create data rows (remaining rows)
        body_rows = []
        for row in padded_data[1:]:
            body_row = " | ".join(str(cell) for cell in row)
            body_rows.append(body_row)

        # Combine components with proper formatting
        if body_rows:
            return f"| {header} |\n| {separator} |\n" + "\n".join(
                f"| {row} |" for row in body_rows
            )
        else:
            return f"| {header} |\n| {separator} |"

    def _extract_table_with_florence_fallback(
        self, table_image: Image.Image
    ) -> Optional[str]:
        """
        Fallback table extraction using Florence-2 multimodal LLM for structured OCR.

        Args:
            table_image: PIL Image of the isolated table.

        Returns:
            Markdown table string or None if extraction fails.
        """
        try:
            # Import Florence-2 components (avoid circular imports)
            from visual_asset_extractor import VisualAssetExtractor

            # Initialize a temporary Florence-2 instance for this task
            florence_extractor = VisualAssetExtractor()

            # Create a mock ExtractedContent to use Florence-2's processing
            mock_result = florence_extractor.extract(
                pdf_path="",  # Not used for this task
                page_num=0,  # Not used
                bbox=[0, 0, table_image.width, table_image.height],  # Image bounds
                label="Table",
                confidence=0.85,
            )

            # If Florence-2 succeeded, process the text result
            if mock_result and mock_result.content:
                table_text = mock_result.content

                # Try to parse the LLM output into table structure
                # For simplicity, attempt to extract tabular data from generated text
                if "table" in table_text.lower() or "|" in table_text:
                    # Basic heuristic: if response contains table-like structure, use it
                    return (
                        f"```\nTable Content (Florence-2 Analysis):\n{table_text}\n```"
                    )

                # Fallback: return the LLM's description
                return f"```\nTable Analysis:\n{table_text}\n```"

            # Shut down to free resources
            florence_extractor.shutdown()
            return None

        except Exception as e:
            print(f"Florence-2 fallback failed: {e}")
            return None

    def extract(
        self, pdf_path: str, page_num: int, bbox: List[float], **kwargs
    ) -> Optional[ExtractedContent]:
        """
        Main extraction method orchestrating the full table extraction pipeline.

        Args:
            pdf_path: Path to the source PDF document.
            page_num: Zero-indexed page number containing the table.
            bbox: [x0, y0, x1, y1] bounding box in PDF coordinates.
            **kwargs: Additional parameters (label, confidence from layout analysis).

        Returns:
            ExtractedContent object with markdown table, or None if extraction fails.
        """
        try:
            # Step 1: Prepare table image
            table_image = self._prepare_table_image(pdf_path, page_num, bbox)

            # Step 2: Detect table structure
            structure_results = self._get_table_structure(table_image)

            # Step 3: Reconstruct cell grid
            cell_grid = self._reconstruct_cell_grid(structure_results, table_image)
            if cell_grid is None:
                # FALLBACK: Use Florence-2 multimodal LLM for structured table extraction
                print(
                    f"Table-Transformer failed, trying Florence-2 fallback for page {page_num}"
                )
                markdown_table = self._extract_table_with_florence_fallback(table_image)
                if markdown_table:
                    # P0-1: Attempt structured extraction even for Florence-2 fallback
                    structured_data = None
                    try:
                        table_id = f"table_{page_num}_{int(bbox[0])}_{int(bbox[1])}"
                        structured_table = self.structured_extractor.extract(
                            markdown_table=markdown_table,
                            table_id=table_id,
                            source_chunk_id="temp",
                            source_page_physical=page_num,
                            source_bbox=bbox,
                        )
                        if structured_table:
                            structured_data = structured_table.model_dump()
                    except Exception as e:
                        print(f"Structured extraction failed for Florence-2 table: {e}")

                    return ExtractedContent(
                        content_type="table_markdown",
                        content=markdown_table,
                        source_page_physical=page_num,
                        source_bbox=bbox,
                        model_used="Florence-2-fallback+Tesseract",
                        layout_label=kwargs.get("label", "Table"),
                        layout_confidence=kwargs.get("confidence"),
                        structured_data=structured_data,  # P0-1: Add structured data
                    )
                # If both approaches fail, return None
                return None

            # Step 4: Extract text from each cell via OCR (only if Table-Transformer succeeded)
            reconstructed_data = self._apply_ocr_to_cells(cell_grid, table_image)

            # Step 5: Serialize to Markdown format
            markdown_table = self._serialize_to_markdown(reconstructed_data)

            if not markdown_table:
                return None

            # P0-1 Step 6: Generate structured table data
            structured_data = None
            try:
                # Generate a unique table ID (will be overridden during chunking)
                table_id = f"table_{page_num}_{int(bbox[0])}_{int(bbox[1])}"
                source_chunk_id = "temp"  # Will be set during chunking phase

                # Extract structured representation
                structured_table = self.structured_extractor.extract(
                    markdown_table=markdown_table,
                    table_id=table_id,
                    source_chunk_id=source_chunk_id,
                    source_page_physical=page_num,
                    source_bbox=bbox,
                )

                if structured_table:
                    # Convert to dict for JSON serialization
                    structured_data = structured_table.model_dump()
            except Exception as e:
                print(f"Warning: Structured extraction failed for table on page {page_num}: {e}")
                # Continue with markdown-only output

            # Step 7: Create ExtractedContent object
            return ExtractedContent(
                content_type="table_markdown",
                content=markdown_table,
                source_page_physical=page_num,
                source_bbox=bbox,
                model_used="Table-Transformer-SR+Tesseract",
                layout_label=kwargs.get("label", "Table"),
                layout_confidence=kwargs.get("confidence"),
                structured_data=structured_data,  # P0-1: Add structured representation
            )

        except Exception as e:
            # Log exception details for debugging
            print(f"Table extraction failed on page {page_num}: {e}")
            import traceback

            traceback.print_exc()
            return None
