"""
VisualAssetExtractor: Florence-2 for image content analysis.
Handles qualitative assets (photos/schematics) with detailed captioning
and quantitative assets (charts/graphs) with human-in-the-loop plotting.
"""

import torch
from transformers import AutoModelForCausalLM, AutoProcessor
from PIL import Image
import io
import fitz  # PyMuPDF
from typing import List, Optional
import hashlib
from pathlib import Path

from src.core.data_contracts import ExtractedContent


class VisualAssetExtractor:
    """
    Extractor for visual assets using Florence-2 foundation model
    and HITL workflow for quantitative charts.
    """

    def __init__(self):
        """Initialize Florence-2 model and processor for visual analysis."""
        # Determine device (GPU preferred for transformer models)
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        # Set appropriate precision for GPU/CPU
        self.dtype = torch.float16 if self.device == "cuda" else torch.float32

        # Load Florence-2 large model with trust_remote_code=True (required)
        # Disable SDPA to avoid compatibility issues
        self.model = (
            AutoModelForCausalLM.from_pretrained(
                "microsoft/Florence-2-large",
                trust_remote_code=True,
                dtype=self.dtype,
                attn_implementation="eager",  # Explicitly use eager attention
            )
            .to(self.device)
            .eval()
        )

        # Load Florence-2 processor (includes image processor + tokenizer)
        self.processor = AutoProcessor.from_pretrained(
            "microsoft/Florence-2-large",
            trust_remote_code=True,
        )

        print(f"VisualAssetExtractor initialized with device: {self.device}")
        print(f"Florence-2 model loaded: {self.model.__class__.__name__}")

    def _extract_image_from_pdf(
        self, pdf_path: str, page_num: int, bbox: List[float]
    ) -> Optional[Image.Image]:
        """Extract image from PDF at specified bounding box with fallback."""
        if len(bbox) != 4:
            raise ValueError(
                f"Bounding box must have 4 coordinates, got {len(bbox)}: {bbox}"
            )

        doc = fitz.open(pdf_path)
        try:
            page = doc.load_page(page_num)

            # FIRST ATTEMPT: Find existing images intersecting with the bounding box
            img_list = page.get_images(full=True)
            rect_bbox = fitz.Rect(bbox)

            # Find the largest image that intersects with our bounding box
            best_img_info = None
            best_intersection_area = 0

            for img_info in img_list:
                img_rect = page.get_image_bbox(img_info)
                if rect_bbox.intersects(img_rect):
                    # Calculate intersection area to prefer larger/closer matches
                    intersection = rect_bbox & img_rect
                    intersection_area = intersection.width * intersection.height

                    if intersection_area > best_intersection_area:
                        best_intersection_area = intersection_area
                        best_img_info = img_info

            if best_img_info:
                # Extract image bytes
                # FIX: best_img_info is a tuple, extract the xref (index 0)
                xref = best_img_info[0]
                base_image = doc.extract_image(xref)
                image_bytes = base_image["image"]

                # Convert to PIL Image
                image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
                return image

            # FALLBACK: Render the bounding box region as raster image
            # This captures vector graphics, text, or other visual content within the bbox
            print(
                "No intersecting image found, using render fallback for bbox extraction"
            )

            # Create clip rectangle from bounding box for rendering
            clip_rect = fitz.Rect(bbox)

            # Render page at 200 DPI but only the clipped region
            zoom_matrix = fitz.Matrix(200 / 72, 200 / 72)  # 200 DPI
            pixmap = page.get_pixmap(matrix=zoom_matrix, clip=clip_rect)

            if pixmap.width > 0 and pixmap.height > 0:
                # Convert pixmap to PIL Image
                img_data = pixmap.tobytes("png")
                image = Image.open(io.BytesIO(img_data)).convert("RGB")
                return image

            return None

        except Exception as e:
            doc.close()
            raise ValueError(f"Failed to extract image from PDF: {str(e)}") from e
        finally:
            doc.close()

    def _generate_detailed_caption(self, image: Image.Image) -> str:
        """Generate detailed caption using Florence-2 <DETAILED_CAPTION> task."""
        # Define the captioning task prompt
        task_prompt = "<DETAILED_CAPTION>"

        # Prepare input for Florence-2
        inputs = self.processor(text=task_prompt, images=image, return_tensors="pt").to(
            self.device, self.dtype
        )

        # Generate response
        generated_ids = self.model.generate(
            input_ids=inputs["input_ids"],
            pixel_values=inputs["pixel_values"],
            max_new_tokens=1024,
            num_beams=3,
            use_cache=False,  # Beam search for higher quality
        )

        # Decode and post-process
        generated_text = self.processor.batch_decode(
            generated_ids, skip_special_tokens=False
        )

        # Use Florence-2's built-in post-processing
        parsed_answer = self.processor.post_process_generation(
            generated_text[0], task=task_prompt, image_size=(image.width, image.height)
        )

        return parsed_answer.get(task_prompt, "Caption generation failed.")

    def _handle_quantitative_chart(
        self, pdf_path: str, page_num: int, bbox: List[float], report_id: str
    ) -> str:
        """Handle quantitative charts via HITL workflow."""
        # Extract chart image
        chart_image = self._extract_image_from_pdf(pdf_path, page_num, bbox)

        if chart_image is None:
            raise ValueError("Could not extract chart image from bounding box.")

        # Create HITL directory for manual processing
        hitl_dir = Path("data/assets_for_hitl")
        hitl_dir.mkdir(exist_ok=True)

        # Generate unique filename with BBox hash for traceability
        bbox_str = "".join(map(str, bbox))
        unique_hash = hashlib.md5(bbox_str.encode()).hexdigest()[:8]
        filename = f"{report_id}_p{page_num}_{unique_hash}.png"
        filepath = hitl_dir / filename

        # Save image for manual PlotDigitizer processing
        chart_image.save(filepath)

        return str(filepath)

    def extract(
        self, pdf_path: str, page_num: int, bbox: List[float], **kwargs
    ) -> Optional[ExtractedContent]:
        """Main extraction method for visual assets."""
        try:
            # Determine asset type from layout label
            layout_label = kwargs.get("label", "Picture")

            # Qualitative assets (photos, diagrams) → captioning
            if layout_label in ("Picture", "Figure"):
                # Extract and caption the image
                image = self._extract_image_from_pdf(pdf_path, page_num, bbox)

                if image is None:
                    return None

                caption = self._generate_detailed_caption(image)

                return ExtractedContent(
                    content_type="image_caption",
                    content=caption,
                    source_page_physical=page_num,
                    source_bbox=bbox,
                    model_used="Florence-2-large",
                    layout_label=layout_label,
                    layout_confidence=kwargs.get("confidence"),
                )

            # Quantitative assets (charts) → HITL workflow
            elif layout_label in ("Chart", "Graph"):
                chart_path = self._handle_quantitative_chart(
                    pdf_path, page_num, bbox, kwargs.get("report_id", "unknown")
                )

                return ExtractedContent(
                    content_type="chart_data_path",
                    content=chart_path,
                    source_page_physical=page_num,
                    source_bbox=bbox,
                    model_used="HITL-PlotDigitizer",
                    layout_label=layout_label,
                    layout_confidence=kwargs.get("confidence"),
                )

            # Unknown asset type - skip
            else:
                print(f"Unknown visual asset type: {layout_label}")
                return None

        except Exception as e:
            print(f"Visual asset extraction failed on page {page_num}: {e}")
            import traceback

            traceback.print_exc()
            return None

    def shutdown(self):
        """Clean up model resources (call when done processing)."""
        if hasattr(self, "model"):
            del self.model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
