"""
GeminiVisualExtractor: Vision-based extraction for tables and charts using Gemini 2.5 Flash.

Tier 3 in the hybrid extraction strategy — processes:
1. Tables that failed Tier 1 (pdfplumber) and Tier 2 (Docling TableFormer)
2. Multi-page table groups (all page images in one request)
3. All chart/figure images for structured data extraction

Uses google-genai SDK with async processing and rate limiting.
Follows the batch pattern established by chart_extractor.py.

Folder Structure:
    data/batch_jobs/
    └── visual_extraction/
        ├── visual_extraction_YYYYMMDD_HHMMSS.json      (job tracker)
        ├── visual_extraction_YYYYMMDD_HHMMSS_mapping.json
        └── {report_id}_visual_results.json              (per-report results)
"""

import json
import time
import base64
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Literal

import fitz  # PyMuPDF — for cropping table/chart images from PDF

logger = logging.getLogger(__name__)


# ============================================================
# IMAGE HELPERS (used by both the extractor and the pipeline)
# ============================================================

def crop_image_from_pdf(
    pdf_path: str,
    page_num: int,
    bbox: List[float],
    dpi: int = 200,
) -> Optional[bytes]:
    """
    Crop a region from a PDF page and return PNG bytes.

    Args:
        pdf_path: Path to PDF file
        page_num: 0-indexed page number
        bbox: [x0, y0, x1, y1] in PDF coordinates
        dpi: Resolution for rendering

    Returns:
        PNG image bytes, or None on failure
    """
    try:
        doc = fitz.open(pdf_path)
        if page_num >= len(doc):
            doc.close()
            return None

        page = doc.load_page(page_num)
        clip_rect = fitz.Rect(bbox)
        zoom = dpi / 72
        mat = fitz.Matrix(zoom, zoom)
        pixmap = page.get_pixmap(matrix=mat, clip=clip_rect)
        png_bytes = pixmap.tobytes("png")
        doc.close()
        return png_bytes
    except Exception as e:
        logger.error(f"Failed to crop image from page {page_num}: {e}")
        return None


def save_block_image(
    pdf_path: str,
    page_num: int,
    bbox: List[float],
    output_dir: str,
    report_id: str,
    block_type: str = "table",
    dpi: int = 200,
) -> Optional[str]:
    """
    Crop and save a block image from PDF. Returns the saved file path.

    Args:
        pdf_path: Source PDF path
        page_num: 0-indexed page number
        bbox: [x0, y0, x1, y1]
        output_dir: Directory to save images
        report_id: Report identifier for filename
        block_type: "table" or "chart" for filename prefix
        dpi: Rendering resolution

    Returns:
        Path to saved PNG file, or None on failure
    """
    png_bytes = crop_image_from_pdf(pdf_path, page_num, bbox, dpi)
    if not png_bytes:
        return None

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{report_id}_{block_type}_p{page_num}_{int(bbox[0])}_{int(bbox[1])}.png"
    filepath = out_dir / filename

    with open(filepath, "wb") as f:
        f.write(png_bytes)

    return str(filepath)


# ============================================================
# PROMPTS
# ============================================================

TABLE_EXTRACTION_PROMPT = """You are an expert at extracting structured data from Indian government audit report tables.

Analyze this table image and extract ALL data into a clean markdown table.

CRITICAL RULES:
1. Preserve EVERY row and column — do not skip or summarize
2. Indian number formats: use commas as-is (e.g., 1,23,456.78)
3. Fiscal years: preserve format exactly (e.g., 2021-22)
4. Currency: preserve units (crore, lakh) if shown in headers
5. Merged cells: repeat the value in each spanned cell
6. Multi-level headers: flatten into single header row with combined labels
7. "(continued)" or "Contd." markers: this is a continuation table, include all data rows
8. Empty cells: leave blank (don't write "N/A" or "-" unless that's what's printed)

OUTPUT FORMAT — respond with ONLY a JSON object, no markdown fences:
{
  "title": "Table title if visible, or null",
  "markdown": "| Header1 | Header2 |\\n| --- | --- |\\n| data | data |",
  "monetary_unit": "crore/lakh/null — if indicated in header or caption",
  "extraction_notes": ["any issues encountered"],
  "row_count": 10,
  "col_count": 5
}"""

CHART_EXTRACTION_PROMPT = """You are an expert at extracting structured data from charts in Indian government audit reports.

Analyze this chart image and extract ALL visible data points.

CRITICAL RULES:
1. Read EVERY data point — use axis gridlines to estimate values
2. Indian number formats: preserve commas (1,23,456)  
3. Fiscal years: preserve format (2021-22, FY2023)
4. Percentage values: include % symbol
5. For bar/line charts: read each bar/point against the Y-axis
6. For pie charts: extract label + percentage/value for each slice
7. Multi-series: identify each series by its legend label

OUTPUT FORMAT — respond with ONLY a JSON object, no markdown fences:
{
  "title": "Chart title",
  "chart_type": "bar|line|pie|scatter|area|combo|unknown",
  "x_axis_label": "X axis label",
  "y_axis_label": "Y axis label",
  "monetary_unit": "crore/lakh/null",
  "series": [
    {
      "name": "Series name from legend",
      "data_points": [
        {"category": "2021-22", "value": 1234.56},
        {"category": "2022-23", "value": 2345.67}
      ]
    }
  ],
  "extraction_notes": ["any issues: blurry text, estimated values, etc."],
  "description": "One-sentence summary of what the chart shows"
}"""

MULTI_PAGE_TABLE_PROMPT = """You are an expert at extracting structured data from multi-page tables in Indian government audit reports.

The following images show a SINGLE TABLE that spans multiple pages. Extract ALL data into one unified markdown table.

CRITICAL RULES:
1. The table continues across pages — merge all data rows into one table
2. Headers may repeat on each page — include them only ONCE in the output
3. Preserve EVERY data row from ALL pages
4. Indian number formats: use commas as-is (e.g., 1,23,456.78)
5. Fiscal years: preserve format exactly (e.g., 2021-22)
6. Page {page_num} images are provided in order — merge top to bottom
7. "(continued)" or "Contd." markers indicate continuation — include the data, not the marker

OUTPUT FORMAT — respond with ONLY a JSON object, no markdown fences:
{
  "title": "Table title from first page",
  "markdown": "| Header1 | Header2 |\\n| --- | --- |\\n| all rows merged |",
  "monetary_unit": "crore/lakh/null",
  "extraction_notes": ["any issues encountered"],
  "row_count": 25,
  "col_count": 5,
  "pages_merged": [1, 2, 3]
}"""


# ============================================================
# GEMINI VISUAL EXTRACTOR SERVICE
# ============================================================

class GeminiVisualExtractor:
    """
    Extracts structured data from table and chart images using Gemini 2.5 Flash.

    Supports:
    - Single table images (Tier 3 fallback)
    - Multi-page table groups (all pages in one request)
    - Chart/figure images
    - Batch processing with rate limiting

    Usage:
        extractor = GeminiVisualExtractor()

        # Process a batch of items
        results = await extractor.process_batch(items)

        # Or process single items
        result = await extractor.extract_table(image_path)
        result = await extractor.extract_chart(image_path, context)
    """

    def __init__(
        self,
        model: str = "gemini-1.5-flash",  # Vertex AI stable Flash model for visual extraction
        batch_jobs_dir: str = "data/batch_jobs",
        processed_dir: str = "data/processed",
        images_dir: str = "data/extraction_images",
        requests_per_minute: int = 15,
        trace_emitter=None,
    ):
        """
        Initialize Gemini Visual Extractor.

        Args:
            model: Gemini model ID
            batch_jobs_dir: Directory for job tracking files
            processed_dir: Directory with processed report JSONs
            images_dir: Directory for saved extraction images
            requests_per_minute: Rate limit for Gemini API
            trace_emitter: Optional TraceEmitter for Phase 10b instrumentation
        """
        self.model = model
        self.batch_jobs_dir = Path(batch_jobs_dir)
        self.processed_dir = Path(processed_dir)
        self.images_dir = Path(images_dir)
        self.visual_extraction_dir = self.batch_jobs_dir / "visual_extraction"
        self._trace_emitter = trace_emitter

        # Create directories
        self.visual_extraction_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir.mkdir(parents=True, exist_ok=True)

        # Rate limiting
        self.rpm_limit = requests_per_minute
        self._request_times: List[float] = []

        # Initialize Gemini client (lazy — created on first use)
        self._client = None

    @property
    def client(self):
        """Lazy-initialize Gemini client using Vertex AI or API key fallback."""
        if self._client is None:
            try:
                import os
                from google import genai

                project = os.getenv("GOOGLE_CLOUD_PROJECT")
                location = os.getenv("VERTEX_AI_REGION", "us-central1")
                api_key = os.getenv("GOOGLE_API_KEY")

                # Try Vertex AI first (GCP project billing), fall back to API key
                if project:
                    try:
                        # Explicitly get ADC credentials for Vertex AI
                        import google.auth
                        credentials, auth_project = google.auth.default(
                            scopes=["https://www.googleapis.com/auth/cloud-platform"]
                        )
                        # Use auth_project if GOOGLE_CLOUD_PROJECT not set
                        project = project or auth_project

                        self._client = genai.Client(
                            vertexai=True,
                            project=project,
                            location=location,
                            credentials=credentials
                        )
                        logger.info(f"Gemini client initialized with Vertex AI (project={project}, model={self.model})")
                    except Exception as e:
                        logger.warning(f"Vertex AI init failed: {e}, trying API key fallback...")
                        if api_key:
                            self._client = genai.Client(api_key=api_key)
                            logger.info(f"Gemini client initialized with API key (model={self.model})")
                        else:
                            raise
                elif api_key:
                    # Direct API key mode
                    self._client = genai.Client(api_key=api_key)
                    logger.info(f"Gemini client initialized with API key (model={self.model})")
                else:
                    raise ValueError(
                        "No Gemini credentials found. Set GOOGLE_CLOUD_PROJECT for Vertex AI "
                        "or GOOGLE_API_KEY for direct API access."
                    )
            except ImportError:
                raise ImportError(
                    "google-genai package required. Install: pip install google-genai"
                )
        return self._client

    # ========== RATE LIMITING ==========

    async def _wait_for_rate_limit(self):
        """
        Enforce rate limiting (RPM).
        Waits if we've hit the per-minute limit.
        """
        now = time.time()
        # Remove timestamps older than 60 seconds
        self._request_times = [t for t in self._request_times if now - t < 60]

        if len(self._request_times) >= self.rpm_limit:
            # Wait until the oldest request is >60s old
            sleep_time = 60 - (now - self._request_times[0]) + 0.5
            if sleep_time > 0:
                logger.info(f"Rate limit reached, waiting {sleep_time:.1f}s...")
                await asyncio.sleep(sleep_time)

        self._request_times.append(time.time())

    # ========== SINGLE ITEM EXTRACTION ==========

    async def extract_table(
        self,
        image_path: str,
        context: str = "",
    ) -> Dict:
        """
        Extract table data from a single image.

        Args:
            image_path: Path to table image PNG
            context: Optional context (section, page info)

        Returns:
            Dict with extracted data or error
        """
        await self._wait_for_rate_limit()

        try:
            from google.genai import types

            # Read image
            image_bytes = Path(image_path).read_bytes()

            prompt = TABLE_EXTRACTION_PROMPT
            if context:
                prompt += f"\n\nCONTEXT:\n{context}"

            response = self.client.models.generate_content(
                model=self.model,
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
                    types.Part.from_text(text=prompt),
                ],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=8192,
                ),
            )

            return self._parse_json_response(response.text, "table")

        except Exception as e:
            logger.error(f"Gemini table extraction failed for {image_path}: {e}")
            return {"success": False, "error": str(e)}

    async def extract_chart(
        self,
        image_path: str,
        context: str = "",
    ) -> Dict:
        """
        Extract chart data from a single image.

        Args:
            image_path: Path to chart image PNG
            context: Optional context (section, page info)

        Returns:
            Dict with extracted data or error
        """
        await self._wait_for_rate_limit()

        try:
            from google.genai import types

            image_bytes = Path(image_path).read_bytes()

            prompt = CHART_EXTRACTION_PROMPT
            if context:
                prompt += f"\n\nCONTEXT:\n{context}"

            response = self.client.models.generate_content(
                model=self.model,
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
                    types.Part.from_text(text=prompt),
                ],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=4096,
                ),
            )

            return self._parse_json_response(response.text, "chart")

        except Exception as e:
            logger.error(f"Gemini chart extraction failed for {image_path}: {e}")
            return {"success": False, "error": str(e)}

    async def extract_multi_page_table(
        self,
        image_paths: List[str],
        context: str = "",
    ) -> Dict:
        """
        Extract a multi-page table by sending all page images in one request.

        Args:
            image_paths: List of PNG paths, one per page (in order)
            context: Optional context

        Returns:
            Dict with unified table data or error
        """
        await self._wait_for_rate_limit()

        try:
            from google.genai import types

            # Build multi-image content
            parts = []
            for i, path in enumerate(image_paths):
                image_bytes = Path(path).read_bytes()
                parts.append(
                    types.Part.from_bytes(data=image_bytes, mime_type="image/png")
                )
                parts.append(
                    types.Part.from_text(text=f"[Page {i + 1} of {len(image_paths)}]")
                )

            prompt = MULTI_PAGE_TABLE_PROMPT.replace(
                "{page_num}", str(len(image_paths))
            )
            if context:
                prompt += f"\n\nCONTEXT:\n{context}"

            parts.append(types.Part.from_text(text=prompt))

            response = self.client.models.generate_content(
                model=self.model,
                contents=parts,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=16384,  # Larger for multi-page tables
                ),
            )

            return self._parse_json_response(response.text, "table")

        except Exception as e:
            logger.error(f"Gemini multi-page extraction failed: {e}")
            return {"success": False, "error": str(e)}

    # ========== BATCH PROCESSING ==========

    async def process_batch(
        self,
        items: List[Dict],
        trace_emitter=None,
    ) -> List[Dict]:
        """
        Process a batch of extraction items.

        Each item dict should have:
            - type: "table" | "chart" | "multi_page_table"
            - image_path: str (or image_paths: List[str] for multi-page)
            - context: str (optional)
            - report_id: str
            - chunk_id: str

        Args:
            items: List of extraction item dicts
            trace_emitter: Optional TraceEmitter for per-item instrumentation

        Returns:
            List of result dicts with extracted data
        """
        results = []
        total = len(items)
        emitter = trace_emitter or self._trace_emitter

        for i, item in enumerate(items, 1):
            item_type = item.get("type", "table")
            context = item.get("context", "")

            logger.info(
                f"Processing {i}/{total}: {item_type} for "
                f"{item.get('report_id', '?')}/{item.get('chunk_id', '?')}"
            )

            if item_type == "multi_page_table":
                result = await self.extract_multi_page_table(
                    item["image_paths"], context
                )
            elif item_type == "chart":
                result = await self.extract_chart(item["image_path"], context)
            else:
                result = await self.extract_table(item["image_path"], context)

            # Attach metadata
            result["report_id"] = item.get("report_id", "")
            result["chunk_id"] = item.get("chunk_id", "")
            result["item_type"] = item_type
            result["image_path"] = item.get("image_path", item.get("image_paths", ""))
            result["json_file"] = item.get("json_file", "")

            # Trace: Per-item extraction decision
            if emitter:
                if result.get("success"):
                    emitter.emit_decision(
                        "10b",
                        f"gemini_extraction_{item_type}",
                        "success",
                        ["success", "failed"],
                        f"{item_type} extraction successful (chunk {item.get('chunk_id', '?')})",
                    )
                else:
                    emitter.emit_decision(
                        "10b",
                        f"gemini_extraction_{item_type}",
                        "failed",
                        ["success", "failed"],
                        f"Error: {result.get('error', 'unknown')[:100]}",
                    )

            results.append(result)

        return results

    # ========== JOB ORCHESTRATION ==========

    async def submit_visual_extraction_job(
        self,
        json_files: List[Path],
        pdf_dir: str = "data/raw",
        skip_existing: bool = True,
        trace_emitter=None,
    ) -> str:
        """
        Full orchestration: identify items needing extraction, process them,
        and update the chunk JSON files.

        Args:
            json_files: List of *_chunks.json file paths
            pdf_dir: Directory where source PDFs are stored
            skip_existing: Skip chunks that already have good structured_data
            trace_emitter: Optional TraceEmitter for Phase 10b instrumentation

        Returns:
            Job ID string
        """
        job_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        job_id = f"visual_extraction_{job_timestamp}"
        emitter = trace_emitter or self._trace_emitter

        logger.info(f"\n{'='*60}")
        logger.info(f"PHASE 10b: Visual Extraction via Gemini")
        logger.info(f"{'='*60}")

        # Step 1: Identify items needing extraction
        items = []
        for json_path in json_files:
            file_items = self._identify_extraction_items(
                json_path, pdf_dir, skip_existing
            )
            items.extend(file_items)

        if not items:
            logger.info("✅ No items need visual extraction")
            # Trace: Phase 10b skipped
            if emitter:
                emitter.emit_io(
                    "10b",
                    {"json_files": len(json_files)},
                    {"items_identified": 0, "skipped": True},
                )
                emitter.set_phase_status("10b", "skipped")
            return job_id

        logger.info(f"📊 Found {len(items)} items for Gemini extraction")
        tables = [i for i in items if i["type"] == "table"]
        charts = [i for i in items if i["type"] == "chart"]
        multi = [i for i in items if i["type"] == "multi_page_table"]
        logger.info(f"   Tables: {len(tables)}, Charts: {len(charts)}, Multi-page: {len(multi)}")

        # Trace: Items identified
        if emitter:
            emitter.emit_io(
                "10b",
                {"json_files": len(json_files), "skip_existing": skip_existing},
                {"tables": len(tables), "charts": len(charts), "multi_page": len(multi)},
            )

        # Step 2: Process batch
        results = await self.process_batch(items, trace_emitter=emitter)

        # Step 3: Update JSON files
        updates = self._apply_results_to_jsons(results, json_files)

        # Step 4: Save job tracker
        success_count = sum(1 for r in results if r.get("success", False))
        error_count = sum(1 for r in results if not r.get("success", False))
        tracker = {
            "job_id": job_id,
            "created_at": datetime.now().isoformat(),
            "model": self.model,
            "total_items": len(items),
            "tables": len(tables),
            "charts": len(charts),
            "multi_page": len(multi),
            "success_count": success_count,
            "error_count": error_count,
            "files_updated": updates,
        }

        tracker_path = self.visual_extraction_dir / f"{job_id}.json"
        with open(tracker_path, "w") as f:
            json.dump(tracker, f, indent=2, ensure_ascii=False)

        # Trace: Final Phase 10b summary
        if emitter:
            emitter.emit_io(
                "10b",
                {"total_items": len(items)},
                {
                    "success_count": success_count,
                    "error_count": error_count,
                    "files_updated": updates,
                    "job_id": job_id,
                },
            )
            if error_count > 0:
                emitter.emit_red_flag(
                    "10b",
                    f"Gemini extraction failed for {error_count} items",
                    {"error_rate": f"{error_count/len(items)*100:.1f}%"},
                )
                emitter.set_phase_status("10b", "partial" if success_count > 0 else "failed")
            else:
                emitter.set_phase_status("10b", "success")

        logger.info(f"\n✅ Visual extraction complete: {success_count}/{len(items)} succeeded")
        return job_id

    def _identify_extraction_items(
        self,
        json_path: Path,
        pdf_dir: str,
        skip_existing: bool,
    ) -> List[Dict]:
        """
        Scan a chunks JSON file and identify tables/charts needing Gemini extraction.

        Items to extract:
        1. table_markdown chunks where model_used indicates pdfplumber failure
           OR where structured_data is None/low quality
        2. image_caption / chart_data_path chunks without structured_data
        3. Figure/Picture blocks that are likely charts (via visual_subtype)

        Args:
            json_path: Path to *_chunks.json
            pdf_dir: Directory with source PDFs
            skip_existing: Skip chunks with existing structured_data

        Returns:
            List of extraction item dicts
        """
        with open(json_path) as f:
            data = json.load(f)

        report_id = data["report_metadata"]["report_id"]
        chunks = data.get("child_chunks", [])
        items = []

        # Find PDF path
        pdf_filename = data.get("report_metadata", {}).get("source_filename", "")
        pdf_path = str(Path(pdf_dir) / pdf_filename) if pdf_filename else None

        for chunk in chunks:
            chunk_id = chunk.get("chunk_id", "")
            content_type = chunk.get("content_type", "")

            # TABLES: extract if no structured_data or low-quality extraction
            if content_type == "table_markdown":
                # C1 fix: Check for Gemini-specific hydration, not just presence of structured_data
                # Phase 6 may set structured_data with visual_subtype, but that's not Gemini hydration
                structured = chunk.get("structured_data") or {}
                is_gemini_hydrated = (
                    chunk.get("extraction_method") == "gemini-2.5-flash-vision"
                    or structured.get("gemini_extracted", False)
                    or "rows" in structured  # Gemini table extraction includes rows
                )
                if skip_existing and is_gemini_hydrated:
                    continue

                # Need to crop image from PDF
                if pdf_path and Path(pdf_path).exists():
                    image_path = save_block_image(
                        pdf_path=pdf_path,
                        page_num=chunk.get("source_page_physical", 0),
                        bbox=chunk.get("source_bbox", [0, 0, 100, 100]),
                        output_dir=str(self.images_dir / "tables"),
                        report_id=report_id,
                        block_type="table",
                    )
                    if image_path:
                        items.append({
                            "type": "table",
                            "image_path": image_path,
                            "report_id": report_id,
                            "chunk_id": chunk_id,
                            "json_file": str(json_path),
                            "context": self._build_context(chunk),
                        })

            # CHARTS: extract if not yet hydrated by Gemini
            elif content_type in ("chart_data_path", "image_caption"):
                # C1 fix: Check for actual Gemini hydration, not just presence of structured_data
                # Phase 6 sets structured_data={"visual_subtype": ...} which should NOT skip hydration
                structured = chunk.get("structured_data") or {}
                content = chunk.get("content", "")

                # Check if already hydrated by Gemini:
                # 1. extraction_method indicates Gemini processing
                # 2. structured_data has Gemini-specific fields (description)
                # 3. content is NOT a file path (has been replaced with description)
                is_file_path = (
                    content.startswith("data/extraction_images/")
                    or content.startswith("/")
                    or content.endswith(".png")
                    or content.endswith(".jpg")
                )
                is_gemini_hydrated = (
                    chunk.get("extraction_method") == "gemini-2.5-flash-vision"
                    or structured.get("description") is not None
                    or (not is_file_path and len(content) > 50)  # Description text, not path
                )
                if skip_existing and is_gemini_hydrated:
                    continue

                # Check if image exists at the content path
                content_path = chunk.get("content", "")
                visual_subtype = chunk.get("visual_subtype", "")

                # For image_caption: only extract if it looks like a chart
                if content_type == "image_caption":
                    if visual_subtype not in ("chart", "data_visualization", ""):
                        continue

                # Try to find or create the image
                image_path = None
                if content_path and Path(content_path).exists():
                    image_path = content_path
                elif pdf_path and Path(pdf_path).exists():
                    image_path = save_block_image(
                        pdf_path=pdf_path,
                        page_num=chunk.get("source_page_physical", 0),
                        bbox=chunk.get("source_bbox", [0, 0, 100, 100]),
                        output_dir=str(self.images_dir / "charts"),
                        report_id=report_id,
                        block_type="chart",
                    )

                if image_path:
                    items.append({
                        "type": "chart",
                        "image_path": image_path,
                        "report_id": report_id,
                        "chunk_id": chunk_id,
                        "json_file": str(json_path),
                        "context": self._build_context(chunk),
                    })

        return items

    def _build_context(self, chunk: Dict) -> str:
        """Build context string from chunk metadata for prompts."""
        lines = []
        hierarchy = chunk.get("hierarchy", {})
        if hierarchy:
            lines.append(
                "Section: " + " > ".join(f"{v}" for v in hierarchy.values() if v)
            )
        page = chunk.get("source_page_physical")
        if page is not None:
            lines.append(f"Page: {page + 1}")
        return "\n".join(lines)

    def _apply_results_to_jsons(
        self,
        results: List[Dict],
        json_files: List[Path],
    ) -> int:
        """
        Write extraction results back into chunk JSON files.

        Args:
            results: Extraction results from process_batch
            json_files: Original JSON file paths

        Returns:
            Number of files updated
        """
        # Group results by JSON file
        results_by_file: Dict[str, List[Dict]] = {}
        for r in results:
            json_file = r.get("json_file", "")
            if json_file:
                results_by_file.setdefault(json_file, []).append(r)

        files_updated = 0
        for json_file, file_results in results_by_file.items():
            try:
                with open(json_file) as f:
                    data = json.load(f)

                updated = 0
                # REMEDIATION §3.2: Track failed and unmatched results for debugging
                failed_results = 0
                unmatched_chunks = []

                for result in file_results:
                    if not result.get("success", False):
                        # REMEDIATION §3.2: Log failed results
                        failed_results += 1
                        logger.warning(f"  Skipping failed result for chunk_id={result.get('chunk_id', '?')}: {result.get('error', 'unknown error')}")
                        continue

                    chunk_id = result["chunk_id"]
                    result_data = result.get("data", {})

                    # REMEDIATION §3.2: Log what keys we got from Gemini
                    logger.debug(f"  Applying result for chunk_id={chunk_id}, data_keys={list(result_data.keys())}")

                    matched = False
                    for chunk in data.get("child_chunks", []):
                        if chunk.get("chunk_id") == chunk_id:
                            matched = True
                            # Store the Gemini extraction result as structured_data
                            chunk["structured_data"] = result_data
                            # Update model_used to indicate Gemini extraction
                            if "model_used" in chunk:
                                chunk["model_used"] = f"gemini-2.5-flash-vision"
                            # P1-14b: Set extraction_method for visual asset registry
                            chunk["extraction_method"] = "gemini-2.5-flash-vision"

                            # P1-14a: Hydrate image_caption content with description
                            # Replace file path (data/extraction_images/...) with description
                            if chunk.get("content_type") == "image_caption":
                                description = result_data.get("description", "")
                                old_content = chunk.get("content", "")[:50]
                                if description:
                                    chunk["content"] = description
                                    logger.info(f"  Hydrated {chunk_id}: '{old_content}...' -> '{description[:50]}...'")
                                else:
                                    # REMEDIATION §3.2: Log when description is missing
                                    logger.warning(f"  No description for image_caption {chunk_id}, data_keys={list(result_data.keys())}")

                            updated += 1
                            break

                    # REMEDIATION §3.2: Track chunks that weren't found
                    if not matched:
                        unmatched_chunks.append(chunk_id)

                # REMEDIATION §3.2: Log summary of issues
                if failed_results > 0:
                    logger.warning(f"  {Path(json_file).name}: {failed_results} failed results skipped")
                if unmatched_chunks:
                    logger.warning(f"  {Path(json_file).name}: {len(unmatched_chunks)} chunks not found: {unmatched_chunks[:5]}{'...' if len(unmatched_chunks) > 5 else ''}")

                if updated > 0:
                    # B5 fix: Set phase_10b_complete flag truthfully
                    if "processing_stats" in data:
                        data["processing_stats"]["phase_10b_complete"] = True
                    with open(json_file, "w") as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                    files_updated += 1
                    logger.info(f"✅ Updated {updated} chunks in {Path(json_file).name}")

            except Exception as e:
                logger.error(f"❌ Failed to update {json_file}: {e}")

        return files_updated

    # ========== RESPONSE PARSING ==========

    def _parse_json_response(self, text: str, item_type: str) -> Dict:
        """
        Parse Gemini's JSON response, handling common formatting issues.

        Args:
            text: Raw response text from Gemini
            item_type: "table" or "chart"

        Returns:
            Dict with parsed data + success flag
        """
        try:
            # Strip markdown fences if present
            cleaned = text.strip()
            if cleaned.startswith("```"):
                # Remove ```json or ``` prefix and ``` suffix
                lines = cleaned.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                cleaned = "\n".join(lines)

            parsed = json.loads(cleaned)
            # Copy pure Gemini response before adding metadata
            data_copy = parsed.copy()
            parsed["success"] = True
            parsed["data"] = data_copy  # data contains only Gemini fields
            return parsed

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse Gemini JSON response: {e}")
            logger.debug(f"Raw response: {text[:500]}")

            # Attempt to extract markdown table from free-text response
            if item_type == "table" and "|" in text:
                # Find the markdown table in the response
                lines = text.split("\n")
                table_lines = [l for l in lines if "|" in l]
                if len(table_lines) >= 2:
                    markdown = "\n".join(table_lines)
                    return {
                        "success": True,
                        "markdown": markdown,
                        "extraction_notes": ["Parsed from free-text response"],
                        "data": {"markdown": markdown},
                    }

            return {
                "success": False,
                "error": f"JSON parse error: {e}",
                "raw_response": text[:1000],
            }
