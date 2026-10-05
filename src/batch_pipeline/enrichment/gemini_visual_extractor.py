"""
GeminiVisualExtractor: Phase 10b vision extraction for charts, figures and table crops.

Routes each image chunk by its Phase 6 subtype:
1. chart: the chart prompt (series and values)
2. map, diagram, flowchart: a short description-only prompt
3. photo, non_data (signatures, emblems, banners): not sent
4. table_as_image: Tier-3 table crops, where pdfplumber and Docling both failed

Uses google-genai SDK with async processing and rate limiting.

Folder Structure:
    data/batch_jobs/
    └── visual_extraction/
        ├── visual_extraction_YYYYMMDD_HHMMSS.json      (job tracker)
        ├── visual_extraction_YYYYMMDD_HHMMSS_mapping.json
        └── {report_id}_visual_results.json              (per-report results)
"""

import re
import json
import asyncio
import logging
from collections import Counter
from pathlib import Path
from datetime import datetime
from typing import Any, List, Dict, Optional

import fitz  # PyMuPDF — for cropping table/chart images from PDF

logger = logging.getLogger(__name__)


# ============================================================
# IMAGE CHUNK HELPERS (shared with Phase 10c)
# ============================================================

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg")

# Phase 6 fields on an image chunk that 10b and 10c must carry through
PHASE6_IMAGE_KEYS = (
    "visual_subtype",
    "image_path",
    "caption",
    "figure_number",
    "embedded_text",
)

# Cap on the linearised chart values written into searchable content
CHART_VALUES_MAX_CHARS = 1500
CHART_VALUES_HEADER = "Chart values"


def is_image_path(text: Any) -> bool:
    """True when chunk content is a saved image path rather than text (pre-PR 7 output)."""
    if not isinstance(text, str):
        return False
    text = text.strip()
    if not text or any(ch.isspace() for ch in text):
        return False
    return text.startswith("data/extraction_images/") or text.lower().endswith(
        IMAGE_EXTENSIONS
    )


def chunk_image_path(chunk: Dict) -> Optional[str]:
    """Image file of an image chunk: structured_data.image_path, else a path in content."""
    structured = chunk.get("structured_data") or {}
    path = structured.get("image_path")
    if path:
        return path
    content = chunk.get("content")
    return content.strip() if is_image_path(content) else None


def _format_value(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def linearise_chart_values(
    series: List[Dict],
    monetary_unit: Optional[str] = None,
    max_chars: int = CHART_VALUES_MAX_CHARS,
) -> str:
    """
    Series x category values as compact text, one line per series:
    "Budgetary Provision: 2018-19 15737.21; 2019-20 17388.09"

    Accepts Gemini's raw series (name) and StructuredChart series (series_name).
    """
    lines = []
    for i, s in enumerate(series or []):
        if not isinstance(s, dict):
            continue
        name = s.get("name") or s.get("series_name") or f"Series {i + 1}"
        points = []
        for dp in s.get("data_points") or []:
            if not isinstance(dp, dict) or dp.get("value") in (None, ""):
                continue
            category = str(dp.get("category") or "").strip()
            points.append(f"{category} {_format_value(dp['value'])}".strip())
        if points:
            lines.append(f"{name}: " + "; ".join(points))
    if not lines:
        return ""

    unit = (monetary_unit or "").strip()
    header = CHART_VALUES_HEADER
    if unit and unit.lower() not in ("null", "none"):
        header += f" ({unit})"
    text = header + ":"
    added = 0
    for line in lines:
        if len(text) + 1 + len(line) <= max_chars:
            text += "\n" + line
            added += 1
            continue
        # Cut the overflowing series at a value boundary
        cut = line[: max(0, max_chars - len(text) - 3)]
        if "; " in cut:
            text += "\n" + cut.rsplit("; ", 1)[0] + " …"
            added += 1
        break
    return text if added else ""


def build_chart_text(
    head: str,
    description: Optional[str],
    series: Optional[List[Dict]],
    monetary_unit: Optional[str] = None,
) -> str:
    """Searchable chart text: caption or title, description, then the values."""
    head = (head or "").strip()
    parts = [head] if head else []
    description = (description or "").strip()
    if description and description not in head:
        parts.append(description)
    if not has_chart_values(head):
        values = linearise_chart_values(series or [], monetary_unit)
        if values:
            parts.append(values)
    return "\n".join(parts)


_VALUES_BLOCK_RE = re.compile(
    rf"^{CHART_VALUES_HEADER}(?: \([^)\n]*\))?:$", re.MULTILINE | re.IGNORECASE
)


def has_chart_values(text: Optional[str]) -> bool:
    """True when text already carries a linearised values block."""
    return bool(_VALUES_BLOCK_RE.search(text or ""))


# Caption labels that name a figure, e.g. "Chart 1.1:", "Figure 2.10", "Picture 5.3;"
CAPTION_LABEL_RE = re.compile(
    r"^\s*(flow\s*chart|chart|graph|figure|fig\.?|diagram|map|picture|"
    r"photo(?:graph)?|plate|exhibit|image)\s*(?:no\.?\s*)?[\dIVXivx]+(?:[.\-]\d+)*",
    re.IGNORECASE,
)
_PHOTO_WORDS_RE = re.compile(
    r"\b(photo(?:graph)?s?|pictures?|view|courtesy|geo-?tagged|site)\b", re.IGNORECASE
)
_DIAGRAM_WORDS_RE = re.compile(
    r"\b(organi[sz]ation(?:al)?|organogram|structure|set-?up|flow|process|hierarchy|"
    r"diagram|schematic|layout|linkages?|framework|mechanism|snapshot|illustration)\b",
    re.IGNORECASE,
)
_MAP_WORDS_RE = re.compile(r"\bmaps?\b", re.IGNORECASE)
_NUMBER_RE = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?%?(?![\w])")


def classify_caption(caption: str) -> Optional[str]:
    """
    Subtype implied by a figure caption, or None when the caption names no figure.

    "Chart"/"Graph" captions are charts unless they describe an organisation or a
    process; "Figure"/"Exhibit" captions are charts unless they read as a photograph,
    diagram or map; "Picture"/"Photograph" captions are photos.
    """
    match = CAPTION_LABEL_RE.match(caption or "")
    if not match:
        return None
    label = re.sub(r"\s+", " ", match.group(1).lower())
    if label in ("picture", "photo", "photograph", "plate"):
        return "photo"
    if label in ("flow chart", "flowchart", "diagram"):
        return "diagram"
    if label == "map":
        return "map"
    if label in ("chart", "graph"):
        return "diagram" if _DIAGRAM_WORDS_RE.search(caption) else "chart"
    # figure, fig., exhibit, image
    if _PHOTO_WORDS_RE.search(caption):
        return "photo"
    if _MAP_WORDS_RE.search(caption):
        return "map"
    if _DIAGRAM_WORDS_RE.search(caption):
        return "diagram"
    return "chart"


def count_numbers(text: Optional[str]) -> int:
    """Numeric tokens in text (data labels printed on a vector chart)."""
    return len(_NUMBER_RE.findall(text or ""))


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

# Maps, diagrams and flowcharts hold no series; a short description with their
# printed labels is what makes them findable.
DIAGRAM_DESCRIPTION_PROMPT = """This image is a map, diagram, flowchart or organisation chart from an Indian government audit report.

In at most three sentences, say what it shows. Name its main labelled elements (offices, places, steps) using the words printed in the image. Do not guess at anything you cannot read.

OUTPUT FORMAT — respond with ONLY a JSON object, no markdown fences:
{
  "title": "Title if printed in the image, or null",
  "description": "What the figure shows"
}"""


# ============================================================
# GEMINI VISUAL EXTRACTOR SERVICE
# ============================================================


class GeminiVisualExtractor:
    """
    Extracts structured data from chart, figure and table images with Gemini
    (model from Phase10ModelConfig.visual).

    Supports:
    - Chart images (series and values)
    - Maps and diagrams (description only)
    - Single table images (Tier 3 fallback)
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
        model: Optional[str] = None,  # default: Phase10ModelConfig.visual
        batch_jobs_dir: str = "data/batch_jobs",
        processed_dir: str = "data/processed",
        images_dir: str = "data/extraction_images",
        trace_emitter=None,
    ):
        """
        Initialize Gemini Visual Extractor.

        Args:
            model: Gemini model ID
            batch_jobs_dir: Directory for job tracking files
            processed_dir: Directory with processed report JSONs
            images_dir: Directory for saved extraction images
            trace_emitter: Optional TraceEmitter for Phase 10b instrumentation
        """
        if model is None:
            from src.core.phase10_models import Phase10ModelConfig

            model = Phase10ModelConfig().visual
        self.model = model
        self.batch_jobs_dir = Path(batch_jobs_dir)
        self.processed_dir = Path(processed_dir)
        self.images_dir = Path(images_dir)
        self.visual_extraction_dir = self.batch_jobs_dir / "visual_extraction"
        self._trace_emitter = trace_emitter

        # Create directories
        self.visual_extraction_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir.mkdir(parents=True, exist_ok=True)

        # Items still failing after their own retries get one more pass after this pause
        self.retry_pause_s = 60

        # Initialize Gemini client (lazy — created on first use)
        self._client = None

    @property
    def client(self):
        """Lazy-initialize Gemini client (GCP Agent Platform, project billing)."""
        if self._client is None:
            from src.core.gemini_client import get_gemini_client

            self._client = get_gemini_client()
            logger.info(
                f"Gemini client initialized with GCP Agent Platform (model={self.model})"
            )
        return self._client

    # ========== GEMINI CALLS ==========
    # Concurrency, 429 back-off and the phase deadline come from the shared limiter
    # (src/core/gemini_limiter.py) inside generate_with_retry.

    async def _generate(self, tag: str = "phase10b.visual", **kwargs):
        """generate_content with backoff on transient errors (see gemini_client.generate_with_retry)."""
        from src.core.gemini_client import generate_with_retry

        return await asyncio.to_thread(generate_with_retry, tag=tag, **kwargs)

    async def _generate_json(
        self, item_type: str, max_attempts: int = 3, **kwargs
    ) -> Dict:
        """
        Generate in JSON mode and parse, re-asking when the response is not valid JSON
        (truncated or malformed output is non-deterministic and usually succeeds on retry).
        """
        config = kwargs.pop("config")
        config = config.model_copy(update={"response_mime_type": "application/json"})
        result: Dict = {}
        for attempt in range(1, max_attempts + 1):
            response = await self._generate(
                tag=f"phase10b.visual.{item_type}", config=config, **kwargs
            )
            result = self._parse_json_response(response.text, item_type)
            if result.get("success"):
                return result
            if attempt < max_attempts:
                logger.warning(
                    f"Invalid JSON from Gemini ({item_type}), re-requesting {attempt}/{max_attempts - 1}"
                )
        return result

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
        try:
            from google.genai import types

            # Read image
            image_bytes = Path(image_path).read_bytes()

            prompt = TABLE_EXTRACTION_PROMPT
            if context:
                prompt += f"\n\nCONTEXT:\n{context}"

            return await self._generate_json(
                "table",
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
        try:
            from google.genai import types

            image_bytes = Path(image_path).read_bytes()

            prompt = CHART_EXTRACTION_PROMPT
            if context:
                prompt += f"\n\nCONTEXT:\n{context}"

            return await self._generate_json(
                "chart",
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

        except Exception as e:
            logger.error(f"Gemini chart extraction failed for {image_path}: {e}")
            return {"success": False, "error": str(e)}

    async def extract_diagram(
        self,
        image_path: str,
        context: str = "",
    ) -> Dict:
        """Short description of a map, diagram or flowchart (no series)."""
        try:
            from google.genai import types

            image_bytes = Path(image_path).read_bytes()

            prompt = DIAGRAM_DESCRIPTION_PROMPT
            if context:
                prompt += f"\n\nCONTEXT:\n{context}"

            return await self._generate_json(
                "diagram",
                model=self.model,
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
                    types.Part.from_text(text=prompt),
                ],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=1024,
                ),
            )

        except Exception as e:
            logger.error(f"Gemini diagram description failed for {image_path}: {e}")
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
            - type: "table" | "chart" | "diagram"
            - image_path: str
            - context: str (optional)
            - caption: str (optional; Phase 6 or derived caption)
            - report_id: str
            - chunk_id: str

        Args:
            items: List of extraction item dicts
            trace_emitter: Optional TraceEmitter for per-item instrumentation

        Returns:
            List of result dicts with extracted data
        """
        emitter = trace_emitter or self._trace_emitter
        results = await self._run_items(items, emitter)

        # Items that failed transiently (busy model, invalid JSON) get one more pass
        retry = [i for i, r in enumerate(results) if self._worth_retrying(r)]
        if retry and self.retry_pause_s is not None:
            from src.core.gemini_limiter import GeminiDeadlineExceeded, get_limiter

            logger.info(
                f"Retrying {len(retry)} failed visual items in {self.retry_pause_s}s"
            )
            try:
                await asyncio.to_thread(
                    get_limiter().backoff, self.retry_pause_s, "phase10b"
                )
            except GeminiDeadlineExceeded:
                logger.warning(
                    f"Phase 10b time budget used up; {len(retry)} items not retried"
                )
            else:
                retried = await self._run_items([items[i] for i in retry], emitter)
                for i, result in zip(retry, retried):
                    results[i] = result
        return results

    @staticmethod
    def _worth_retrying(result: Dict) -> bool:
        if result.get("success"):
            return False
        from src.core.gemini_client import is_transient

        error = str(result.get("error", ""))
        return is_transient(error) or "JSON" in error or not error

    async def _run_items(self, items: List[Dict], emitter=None) -> List[Dict]:
        """Extract items concurrently; results keep the order of items."""
        from src.core.gemini_limiter import get_limiter

        # Bounds the worker threads; the shared limiter bounds requests in flight
        gate = asyncio.Semaphore(get_limiter().group_caps.get("phase10b", 8))
        total = len(items)

        async def run(i: int, item: Dict) -> Dict:
            async with gate:
                return await self._extract_item(i, total, item, emitter)

        return list(
            await asyncio.gather(*(run(i, item) for i, item in enumerate(items, 1)))
        )

    async def _extract_item(self, i: int, total: int, item: Dict, emitter=None) -> Dict:
        item_type = item.get("type", "table")
        context = item.get("context", "")

        logger.info(
            f"Processing {i}/{total}: {item_type} for "
            f"{item.get('report_id', '?')}/{item.get('chunk_id', '?')}"
        )

        try:
            if item_type == "chart":
                result = await self.extract_chart(item["image_path"], context)
            elif item_type == "diagram":
                result = await self.extract_diagram(item["image_path"], context)
            else:
                result = await self.extract_table(item["image_path"], context)
        except Exception as e:  # one item must never sink the batch
            logger.error(
                f"Visual extraction failed for {item.get('chunk_id', '?')}: {e}"
            )
            result = {"success": False, "error": str(e)}

        # Attach metadata
        result["report_id"] = item.get("report_id", "")
        result["chunk_id"] = item.get("chunk_id", "")
        result["item_type"] = item_type
        result["image_path"] = item.get("image_path", "")
        result["json_file"] = item.get("json_file", "")
        result["caption"] = item.get("caption", "")
        result["visual_subtype"] = item.get("visual_subtype")

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
                    f"Error: {str(result.get('error', 'unknown'))[:100]}",
                )
        return result

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
        # Microseconds: one run submits a job per PDF directory, often in the same second
        job_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        job_id = f"visual_extraction_{job_timestamp}"
        emitter = trace_emitter or self._trace_emitter

        logger.info(f"\n{'='*60}")
        logger.info("PHASE 10b: Visual Extraction via Gemini")
        logger.info(f"{'='*60}")

        # Step 1: Identify items needing extraction
        items = []
        skipped: Counter = Counter()
        for json_path in json_files:
            file_items = self._identify_extraction_items(
                json_path, pdf_dir, skip_existing, skipped=skipped
            )
            items.extend(file_items)
        if skipped:
            logger.info(f"   Images not sent to Gemini: {dict(skipped)}")

        if not items:
            logger.info("✅ No items need visual extraction")
            # Trace: Phase 10b skipped
            if emitter:
                emitter.emit_io(
                    "10b",
                    {"json_files": len(json_files)},
                    {
                        "items_identified": 0,
                        "skipped": True,
                        "images_skipped": dict(skipped),
                    },
                )
                emitter.set_phase_status("10b", "skipped")
            return job_id

        logger.info(f"📊 Found {len(items)} items for Gemini extraction")
        tables = [i for i in items if i["type"] == "table"]
        charts = [i for i in items if i["type"] == "chart"]
        diagrams = [i for i in items if i["type"] == "diagram"]
        logger.info(
            f"   Tables: {len(tables)}, Charts: {len(charts)}, "
            f"Diagrams: {len(diagrams)}"
        )

        # Trace: Items identified
        if emitter:
            emitter.emit_io(
                "10b",
                {"json_files": len(json_files), "skip_existing": skip_existing},
                {
                    "tables": len(tables),
                    "charts": len(charts),
                    "diagrams": len(diagrams),
                    "images_skipped": dict(skipped),
                },
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
            "diagrams": len(diagrams),
            "images_skipped": dict(skipped),
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
                emitter.set_phase_status(
                    "10b", "partial" if success_count > 0 else "failed"
                )
            else:
                emitter.set_phase_status("10b", "success")

        logger.info(
            f"\n✅ Visual extraction complete: {success_count}/{len(items)} succeeded"
        )
        return job_id

    def _identify_extraction_items(
        self,
        json_path: Path,
        pdf_dir: str,
        skip_existing: bool,
        skipped: Optional[Counter] = None,
    ) -> List[Dict]:
        """
        Scan a chunks JSON file and identify tables/charts needing Gemini extraction.

        Items to extract:
        1. table_markdown chunks where model_used indicates pdfplumber failure
           OR where structured_data is None/low quality
        2. image chunks routed by _route_image: charts to the chart prompt, maps and
           diagrams to the description prompt

        Images that are not sent are marked structured_data.skipped=<reason>, and an
        image path left in content (old output) is replaced by the nearest caption.

        Args:
            json_path: Path to *_chunks.json
            pdf_dir: Directory with source PDFs
            skip_existing: Skip chunks with existing structured_data
            skipped: Optional counter of images not sent, by reason

        Returns:
            List of extraction item dicts
        """
        with open(json_path) as f:
            data = json.load(f)

        report_id = data["report_metadata"]["report_id"]
        chunks = data.get("child_chunks", [])
        items = []
        if skipped is None:
            skipped = Counter()
        changed = False
        by_page: Dict[Any, List[Dict]] = {}
        for chunk in chunks:
            by_page.setdefault(chunk.get("source_page_physical"), []).append(chunk)

        # PDF, only needed to re-crop an image whose file is missing
        pdf_path = self._resolve_pdf(pdf_dir, data.get("report_metadata") or {})

        for chunk in chunks:
            chunk_id = chunk.get("chunk_id", "")
            content_type = chunk.get("content_type", "")

            # Text-layer tables (pdfplumber, Docling) are never re-extracted here; only
            # Tier-3 table crops, which reach 10b as image chunks, go to the table prompt.
            # IMAGES: route by subtype; only charts get the chart prompt
            if content_type in ("chart_data_path", "image_caption"):
                if skip_existing and self._already_extracted(chunk):
                    continue

                route = self._route_image(chunk, by_page)
                kind = route["kind"]
                if kind is None:
                    changed |= self._mark_unsent(chunk, route, route["reason"])
                    skipped[route["reason"]] += 1
                    continue

                # Try to find or create the image
                image_path = chunk_image_path(chunk)
                if not (image_path and Path(image_path).exists()):
                    image_path = None
                    if pdf_path and Path(pdf_path).exists():
                        image_path = save_block_image(
                            pdf_path=pdf_path,
                            page_num=chunk.get("source_page_physical", 0),
                            bbox=self._chunk_bbox(chunk) or [0, 0, 100, 100],
                            output_dir=str(self.images_dir / "charts"),
                            report_id=report_id,
                            block_type="table" if kind == "table" else "chart",
                        )
                if not image_path:
                    changed |= self._mark_unsent(chunk, route, "image_missing")
                    skipped["image_missing"] += 1
                    continue

                items.append(
                    {
                        "type": kind,
                        "image_path": image_path,
                        "report_id": report_id,
                        "chunk_id": chunk_id,
                        "json_file": str(json_path),
                        "context": self._build_context(chunk, route["caption"]),
                        "caption": route["caption"],
                        "visual_subtype": route["subtype"],
                    }
                )

        # Images not sent keep (or get) caption text instead of a file path
        if changed:
            with open(json_path, "w") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        return items

    # Signatures (~120x55 pt), emblems on the cover and icons/QR codes are far smaller than
    # any real chart (smallest seen: 196x170 pt); in the Sep 2026 Union run all 93 images
    # under these limits were non-data.
    NON_DATA_MAX_WIDTH = 170
    NON_DATA_MAX_HEIGHT = 105
    # Chapter title banners are page-wide strips ~40 pt high; the flattest chart in 25
    # reports is 109 pt high.
    BANNER_MAX_HEIGHT = 60
    COVER_PAGES = 2  # physical pages 0-1: State Emblem and CAG logo
    # A caption more than this far (pt) above or below an image belongs to something else
    CAPTION_MAX_GAP = 60
    # Numeric tokens in the picture's text layer that mark a chart with data labels
    CHART_MIN_NUMBERS = 6

    @staticmethod
    def _resolve_pdf(pdf_dir: str, metadata: Dict) -> Optional[str]:
        """Source PDF under pdf_dir, pdf_dir/<tier>/ or data/raw/<tier>/."""
        filename = metadata.get("source_filename")
        if not filename:
            return None
        tier = metadata.get("government_body_type") or ""
        candidates = [Path(pdf_dir) / filename]
        if tier:
            candidates += [
                Path(pdf_dir) / tier / filename,
                Path("data/raw") / tier / filename,
            ]
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        return None

    @staticmethod
    def _already_extracted(chunk: Dict) -> bool:
        """True when an earlier 10b run already extracted this image."""
        structured = chunk.get("structured_data") or {}
        method = str(chunk.get("extraction_method") or "")
        return (
            method.startswith("gemini")
            or structured.get("description") is not None
            or bool(structured.get("chart_id"))
        )

    def _route_image(self, chunk: Dict, by_page: Dict[Any, List[Dict]]) -> Dict:
        """
        Decide what Gemini does with an image chunk.

        Returns {"kind": "chart" | "diagram" | "table" | None, "subtype", "caption",
        "reason", "legacy"}. Subtype comes from Phase 6 (structured_data.visual_subtype,
        then the top-level key). Output written before PR 7 (no structured_data.image_path)
        was classified with an empty caption, so its "photo" label carries no information
        (B-6-15) and the nearest printed caption decides instead.
        """
        structured = chunk.get("structured_data") or {}
        legacy = not structured.get("image_path")
        subtype = structured.get("visual_subtype") or chunk.get("visual_subtype")
        if legacy:
            if subtype in ("photo", "unknown", "data_visualization"):
                subtype = None
            layout_label = chunk.get("layout_label") or (
                (chunk.get("metadata") or {}).get("extraction") or {}
            ).get("layout_label")
            if layout_label == "Table":
                subtype = "table_as_image"

        caption = (structured.get("caption") or "").strip()
        if not caption:
            caption = self._nearby_caption(chunk, by_page)
        route = {"subtype": subtype, "caption": caption, "legacy": legacy}

        if subtype == "table_as_image":
            return {**route, "kind": "table", "reason": None}
        if subtype in ("photo", "non_data"):
            return {**route, "kind": None, "reason": subtype}
        if self._is_non_data_image(chunk):
            return {**route, "kind": None, "reason": "non_data"}
        if subtype in ("chart", "data_visualization"):
            return {**route, "kind": "chart", "reason": None}
        if subtype in ("map", "diagram", "flowchart"):
            return {**route, "kind": "diagram", "reason": None}

        # No usable subtype: a figure caption decides, then numbers printed on the image
        implied = classify_caption(caption)
        if implied is None and (
            count_numbers(structured.get("embedded_text")) >= self.CHART_MIN_NUMBERS
        ):
            implied = "chart"
        if legacy:
            route["subtype"] = implied
        if implied == "chart":
            return {**route, "kind": "chart", "reason": None}
        if implied in ("map", "diagram"):
            return {**route, "kind": "diagram", "reason": None}
        if implied == "photo":
            return {**route, "kind": None, "reason": "photo"}
        return {**route, "kind": None, "reason": "unclassified"}

    def _nearby_caption(self, chunk: Dict, by_page: Dict[Any, List[Dict]]) -> str:
        """Closest "Chart/Figure/Picture N.N ..." line just above or below the image."""
        bbox = self._chunk_bbox(chunk)
        if not bbox:
            return ""
        best, best_gap = "", None
        for other in by_page.get(chunk.get("source_page_physical"), []):
            if other is chunk or other.get("content_type") in (
                "image_caption",
                "chart_data_path",
                "table_markdown",
            ):
                continue
            text = (other.get("content") or "").strip()
            if len(text) > 250 or not CAPTION_LABEL_RE.match(text):
                continue
            other_bbox = self._chunk_bbox(other)
            if not other_bbox:
                continue
            gap = max(other_bbox[1] - bbox[3], bbox[1] - other_bbox[3], 0)
            if gap <= self.CAPTION_MAX_GAP and (best_gap is None or gap < best_gap):
                best, best_gap = text, gap
        return best

    @staticmethod
    def _image_fields(chunk: Dict, route: Dict) -> Dict:
        """structured_data with the image path moved out of content (old output)."""
        structured = dict(chunk.get("structured_data") or {})
        path = chunk_image_path(chunk)
        if path:
            structured["image_path"] = path
        if route.get("legacy"):
            structured["visual_subtype"] = route.get("subtype")
        if route.get("caption") and not structured.get("caption"):
            structured["caption"] = route["caption"]
        return structured

    def _mark_unsent(self, chunk: Dict, route: Dict, reason: str) -> bool:
        """Record why an image was not sent; never leave a file path as content."""
        before = (chunk.get("content"), chunk.get("structured_data"))
        structured = self._image_fields(chunk, route)
        structured["skipped"] = reason
        chunk["structured_data"] = structured
        if is_image_path(chunk.get("content")):
            chunk["content"] = route.get("caption") or ""
        return (chunk.get("content"), chunk.get("structured_data")) != before

    @staticmethod
    def _chunk_bbox(chunk: Dict) -> Optional[List[float]]:
        """Block bbox in PDF points, from metadata.location (Phase 8 layout) or source_bbox."""
        bbox = chunk.get("source_bbox") or (chunk.get("metadata") or {}).get(
            "location", {}
        ).get("bbox")
        return bbox if bbox and len(bbox) == 4 else None

    def _is_non_data_image(self, chunk: Dict) -> bool:
        """True for cover emblems, signature-sized images and title banners."""
        if (chunk.get("source_page_physical") or 0) < self.COVER_PAGES:
            return True
        bbox = self._chunk_bbox(chunk)
        if not bbox:
            return False
        width, height = abs(bbox[2] - bbox[0]), abs(bbox[3] - bbox[1])
        if height < self.BANNER_MAX_HEIGHT:
            return True
        return width < self.NON_DATA_MAX_WIDTH and height < self.NON_DATA_MAX_HEIGHT

    def _build_context(self, chunk: Dict, caption: str = "") -> str:
        """Build context string from chunk metadata for prompts."""
        lines = []
        if caption:
            lines.append(f"Caption: {caption}")
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

                by_id = {c.get("chunk_id"): c for c in data.get("child_chunks", [])}
                updated = 0
                failed_results = 0
                unmatched_chunks = []

                for result in file_results:
                    chunk_id = result.get("chunk_id", "")
                    chunk = by_id.get(chunk_id)
                    if chunk is None:
                        unmatched_chunks.append(chunk_id)
                        continue

                    if not result.get("success", False):
                        failed_results += 1
                        logger.warning(
                            f"  Failed result for chunk_id={chunk_id}: "
                            f"{result.get('error', 'unknown error')}"
                        )
                        self._mark_failed(chunk, result)
                        continue

                    result_data = result.get("data") or {}
                    logger.debug(
                        f"  Applying result for chunk_id={chunk_id}, "
                        f"data_keys={list(result_data.keys())}"
                    )
                    if result.get("item_type") == "table":
                        if not self._apply_table_result(chunk, result):
                            failed_results += 1
                            continue
                    else:
                        self._apply_image_result(chunk, result)
                    updated += 1

                if failed_results > 0:
                    logger.warning(
                        f"  {Path(json_file).name}: {failed_results} failed results "
                        "kept their caption text"
                    )
                if unmatched_chunks:
                    more = "..." if len(unmatched_chunks) > 5 else ""
                    logger.warning(
                        f"  {Path(json_file).name}: {len(unmatched_chunks)} chunks "
                        f"not found: {unmatched_chunks[:5]}{more}"
                    )

                if updated > 0 or failed_results > 0:
                    # B5 fix: Set phase_10b_complete flag truthfully
                    if updated > 0 and "processing_stats" in data:
                        data["processing_stats"]["phase_10b_complete"] = True
                    with open(json_file, "w") as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                    files_updated += 1
                    logger.info(
                        f"✅ Updated {updated} chunks in {Path(json_file).name}"
                    )

            except Exception as e:
                logger.error(f"❌ Failed to update {json_file}: {e}")

        return files_updated

    def _apply_image_result(self, chunk: Dict, result: Dict) -> None:
        """
        Merge a chart or diagram result into its chunk. Phase 6 fields are kept, and
        content becomes caption (or the Phase 6 text, which may hold vector-chart
        values), then the description, then the chart values.
        """
        data = result.get("data") or {}
        structured = chunk.get("structured_data") or {}
        route = {
            "legacy": not structured.get("image_path"),
            "subtype": result.get("visual_subtype"),
            "caption": result.get("caption") or "",
        }
        merged = self._image_fields(chunk, route)
        for key in ("skipped", "extraction_error"):
            merged.pop(key, None)
        phase6 = {k: merged[k] for k in PHASE6_IMAGE_KEYS if k in merged}
        merged.update(data)
        merged.update(phase6)
        if result.get("image_path"):
            merged["image_path"] = result["image_path"]

        content = chunk.get("content") or ""
        head = "" if is_image_path(content) else content
        head = head or merged.get("caption") or data.get("title") or ""
        series = data.get("series") if result.get("item_type") == "chart" else None
        chunk["content"] = build_chart_text(
            head, data.get("description"), series, data.get("monetary_unit")
        )
        chunk["structured_data"] = merged
        if "model_used" in chunk:
            chunk["model_used"] = self.model
        chunk["extraction_method"] = self.model

    def _apply_table_result(self, chunk: Dict, result: Dict) -> bool:
        """
        A Tier-3 table crop becomes a table chunk: caption plus Gemini's markdown.
        Phase 10c then parses the markdown into a StructuredTable (rows).
        """
        data = result.get("data") or {}
        markdown = (data.get("markdown") or "").strip()
        if markdown.count("|") < 4:
            self._mark_failed(
                chunk, {**result, "error": "table extraction returned no markdown"}
            )
            return False
        structured = chunk.get("structured_data") or {}
        route = {
            "legacy": not structured.get("image_path"),
            "subtype": "table_as_image",
            "caption": result.get("caption") or "",
        }
        merged = self._image_fields(chunk, route)
        for key in ("skipped", "extraction_error"):
            merged.pop(key, None)
        merged.update(
            {
                k: data[k]
                for k in ("title", "monetary_unit", "extraction_notes")
                if data.get(k)
            }
        )
        merged["markdown"] = markdown
        merged["gemini_extracted"] = True
        if result.get("image_path"):
            merged["image_path"] = result["image_path"]

        caption = merged.get("caption") or ""
        chunk["content_type"] = "table_markdown"
        chunk["content"] = f"{caption}\n\n{markdown}" if caption else markdown
        chunk["structured_data"] = merged
        if "model_used" in chunk:
            chunk["model_used"] = self.model
        chunk["extraction_method"] = self.model
        return True

    def _mark_failed(self, chunk: Dict, result: Dict) -> None:
        """A failed image keeps its caption text and records the error."""
        if chunk.get("content_type") not in ("image_caption", "chart_data_path"):
            return
        structured = chunk.get("structured_data") or {}
        route = {
            "legacy": not structured.get("image_path"),
            "subtype": result.get("visual_subtype"),
            "caption": result.get("caption") or "",
        }
        merged = self._image_fields(chunk, route)
        merged.pop("skipped", None)
        merged["extraction_error"] = str(result.get("error") or "unknown")[:300]
        chunk["structured_data"] = merged
        if is_image_path(chunk.get("content")):
            chunk["content"] = route["caption"]

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
            # JSON mode sometimes wraps the object in a one-element list
            if (
                isinstance(parsed, list)
                and len(parsed) == 1
                and isinstance(parsed[0], dict)
            ):
                parsed = parsed[0]
            if not isinstance(parsed, dict):
                raise json.JSONDecodeError(
                    "Top-level value is not an object", cleaned, 0
                )
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
                table_lines = [line for line in lines if "|" in line]
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
