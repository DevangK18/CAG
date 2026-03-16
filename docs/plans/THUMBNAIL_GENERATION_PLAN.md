# Chart Thumbnail Generation — Implementation Plan

## Context from Data Analysis

**Coordinate system:** BBoxes are in PDF points (72 DPI). A4 page = ~595×842pt. Coordinates are `[x0, y0, x1, y1]`.

**Quality issues across reports:**
- Most figures tagged `visual_subtype: "unknown"` (not just `"chart"`) — must include these, not filter to charts only
- ~10% of bboxes are **tiny** (<50pt dimension) — misdetections from the layout analyzer, skip these
- ~5% are **full-page** (width >550pt) — scanned page halves treated as figures, crop but flag for review
- Valid figures average ~440×200pt (wide charts/diagrams)

**Tool:** PyMuPDF (`fitz`) — renders pages at target DPI and supports bbox cropping in a single operation. Already a common Python PDF lib, likely in your stack.

---

## Part 1: Standalone Backfill Script

**File:** `src/scripts/generate_thumbnails.py`

**What it does:**
1. Scans `data/processed/*_chunks.json` for all reports
2. For each report, reads `visual_asset_registry.figures`
3. Opens the source PDF (path from `report_metadata.source_filename`)
4. For each valid figure: renders the page, crops to bbox, saves as JPEG
5. Output: `data/processed/thumbnails/{report_id}/fig_{figure_id}.jpg`

**Core logic:**

```
for each report chunks.json:
    load visual_asset_registry.figures
    open PDF via fitz.open(pdf_path)
    
    for each figure:
        # FILTER: skip tiny bboxes
        w, h = x1-x0, y1-y0
        if w < 60 or h < 60: skip
        
        # RENDER page at 150 DPI (2.08x scale from 72 DPI points)
        page = pdf.load_page(figure.page_physical)
        
        # BBOX to fitz.Rect (fitz uses same coordinate system as PDF points)
        rect = fitz.Rect(x0, y0, x1, y1)
        
        # ADD PADDING: 10pt on each side (prevents tight crops)
        rect.x0 = max(0, rect.x0 - 10)
        rect.y0 = max(0, rect.y0 - 10)
        rect.x1 = min(page.rect.width, rect.x1 + 10)
        rect.y1 = min(page.rect.height, rect.y1 + 10)
        
        # RENDER cropped region at 150 DPI
        mat = fitz.Matrix(150/72, 150/72)
        pix = page.get_pixmap(matrix=mat, clip=rect)
        
        # SAVE as JPEG (quality 85 — good balance of size/clarity)
        pix.save(output_path, "jpeg")
```

**Thumbnail sizing:**
- Render at 150 DPI — produces ~300-600px wide images for typical chart bboxes
- After rendering, if width > 400px, resize down to 400px max width (keeps file size <50KB)
- Use Pillow for the resize step if needed (`pix.tobytes()` → PIL → resize → save)

**Edge case handling:**
- **Tiny bbox** (w<60 or h<60 pt): Skip entirely, log as `skipped_tiny`
- **Full-page bbox** (w>550pt): Still crop but save — these are often full-page charts in scanned reports. Log as `fullpage_crop` for manual review
- **PDF not found**: Log error, continue to next report
- **Page index out of range**: Log error, skip figure

**CLI interface:**
```bash
# Process all reports
python src/scripts/generate_thumbnails.py --all

# Process single report
python src/scripts/generate_thumbnails.py --report-id 2025_16_CAG_Report_on_...

# Dry run (count figures, check PDFs exist, no rendering)
python src/scripts/generate_thumbnails.py --all --dry-run
```

**Output structure:**
```
data/processed/thumbnails/
├── 2025_16_CAG_Report_.../
│   ├── fig_p24_7.jpg      # 400x210px, ~35KB
│   ├── fig_p26_8.jpg
│   └── ...
├── 2023_07_CAGs_Compliance.../
│   ├── fig_p30_3.jpg
│   └── ...
└── manifest.json           # { report_id: { figure_id: { path, width, height, size_kb } } }
```

**`manifest.json`** — written after each run. Tracks what was generated, useful for the API to know which thumbnails exist without hitting the filesystem.

**PDF source path resolution:**
- PDF path: check `data/processed/ocred/{source_filename}` first (OCR'd version), fall back to original PDF location
- The script should accept a `--pdf-dir` argument to specify where PDFs live

---

## Part 2: Pipeline Integration

**Where it plugs in:** After `visual_asset_extractor.py` populates `visual_asset_registry.figures` and before `assembly_service.py` writes the final chunks JSON.

**File:** `src/modules/thumbnail_service.py`

**Service interface:**
```python
class ThumbnailService:
    def __init__(self, output_base_dir: str = "data/processed/thumbnails"):
        ...
    
    def generate_for_report(
        self, 
        pdf_path: str, 
        report_id: str, 
        figures: list[dict]  # visual_asset_registry.figures
    ) -> dict:
        """
        Returns: { figure_id: { path, width, height } } for successfully generated thumbs
        """
```

**Integration point in `assembly_service.py`:**
- After visual asset registry is built, call `thumbnail_service.generate_for_report()`
- Store the returned thumbnail metadata back into each figure entry in the registry:
  ```
  figure.thumbnail_path = "thumbnails/{report_id}/fig_{figure_id}.jpg"
  figure.thumbnail_dimensions = { width: 400, height: 210 }
  ```
- This way the chunks JSON is self-contained — the API doesn't need the separate manifest.

**Filtering logic (same as backfill script):**
- Min bbox: 60×60pt
- Max width for resize: 400px
- Render DPI: 150
- Padding: 10pt

**The `ThumbnailService` is shared** between the pipeline and the backfill script. The backfill script is essentially:
```python
svc = ThumbnailService()
for report in all_reports:
    svc.generate_for_report(pdf_path, report_id, figures)
```

This avoids code duplication.

---

## API Serving Layer

**Endpoint:** `GET /api/assets/{report_id}/thumbnail/{figure_id}`

**In `services/api/routes/assets.py`:**
- Resolve path: `data/processed/thumbnails/{report_id}/fig_{figure_id}.jpg`
- Return `FileResponse` with `media_type="image/jpeg"`, appropriate cache headers (`Cache-Control: max-age=86400`)
- 404 if thumbnail doesn't exist

**In the charts listing response** (wherever charts are served to the frontend):
- Add `thumbnail_url: "/api/assets/{report_id}/thumbnail/{figure_id}"` to each chart entry
- Set to `null` if thumbnail doesn't exist (check `thumbnail_path` in the figure registry, or hit filesystem)

---

## Implementation Order

1. **`ThumbnailService`** class in `src/modules/thumbnail_service.py` — core rendering + cropping + saving logic
2. **Backfill script** in `src/scripts/generate_thumbnails.py` — uses ThumbnailService, run on all existing reports
3. **API endpoint** in `services/api/routes/assets.py` — serve thumbnails
4. **Pipeline integration** — wire ThumbnailService into `assembly_service.py`
5. **Frontend** — update `ArtifactCard.tsx` to use thumbnail URL (covered in the frontend plan)
