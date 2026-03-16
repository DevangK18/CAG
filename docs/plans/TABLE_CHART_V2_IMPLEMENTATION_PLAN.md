# Table & Chart Extraction v2 — Implementation Plan

## Overview

Replace the broken TATR+Tesseract+Florence-2 pipeline with a 3-tier hybrid strategy:
- **Tier 1**: pdfplumber (native PDFs) — direct text-stream extraction, no OCR
- **Tier 2**: Docling TableFormer ACCURATE (scanned PDFs) — already in pipeline, needs config tweak
- **Tier 3**: Gemini 2.5 Flash Vision (fallback) — for failed tables + all charts

**Three new drop-in files are provided** (no modifications needed):
1. `pdfplumber_table_extractor.py` — replaces `table_extractor.py`
2. `gemini_visual_extractor.py` — new Phase 10b service
3. `visual_post_processor.py` — new Phase 10c service

**This plan covers the 8 existing files Claude Code must modify.**

---

## Step 1: Install Dependencies

```bash
pip install pdfplumber google-genai
```

Ensure `GOOGLE_API_KEY` is in `.env` (free tier or API key for Gemini).

---

## Step 2: Place the 3 New Files

```
# Tier 1: pdfplumber extractor (drop-in replacement for table_extractor.py)
cp pdfplumber_table_extractor.py  src/parsing_pipeline/extractors/pdfplumber_table_extractor.py

# Tier 3: Gemini visual extractor (new batch service)
cp gemini_visual_extractor.py  src/batch_pipeline/enrichment/gemini_visual_extractor.py

# Phase 10c: Post-processor
cp visual_post_processor.py  src/batch_pipeline/enrichment/visual_post_processor.py
```

Make sure `src/batch_pipeline/enrichment/` exists and has an `__init__.py`.

---

## Step 3: Modify `content_extraction_service.py`

**File**: `src/parsing_pipeline/modules/content_extraction_service.py`

### 3a. Replace the TableExtractor import and initialization

Change the import:
```python
# OLD
from src.parsing_pipeline.extractors.table_extractor import TableExtractor

# NEW
from src.parsing_pipeline.extractors.pdfplumber_table_extractor import PdfplumberTableExtractor
```

In `__init__()`, replace:
```python
# OLD
self.table_extractor = TableExtractor(conf_threshold=0.75, ocr_psm=6)

# NEW
self.table_extractor = PdfplumberTableExtractor()
```

### 3b. Add image-saving for Figure/Picture blocks

The current `visual_asset_extractor.py` uses Florence-2 for captioning, which is heavyweight and unnecessary for the new pipeline. We need Figure/Picture blocks to:
1. Save the cropped image to `data/extraction_images/charts/`
2. Return an `ExtractedContent` with `content_type="image_caption"` and `content=<image_path>`

Add a new method to ContentExtractionService:

```python
def _extract_and_save_visual(
    self, pdf_path: str, page_num: int, bbox: List[float], **kwargs
) -> Optional[ExtractedContent]:
    """
    Save visual block (Figure/Picture) as PNG for downstream Gemini extraction.
    Replaces Florence-2 captioning with simple image persistence.
    """
    from src.batch_pipeline.enrichment.gemini_visual_extractor import save_block_image
    
    report_id = kwargs.get("report_id", "unknown")
    label = kwargs.get("label", "Picture")
    
    image_path = save_block_image(
        pdf_path=pdf_path,
        page_num=page_num,
        bbox=bbox,
        output_dir="data/extraction_images/charts",
        report_id=report_id,
        block_type="chart" if label == "Figure" else "picture",
        dpi=200,
    )
    
    if not image_path:
        return None
    
    return ExtractedContent(
        content_type="image_caption",  # Keep existing content_type for compatibility
        content=image_path,            # Store image path (same pattern as chart_data_path)
        source_page_physical=page_num,
        source_bbox=bbox,
        model_used="image-crop-for-gemini",
        layout_label=label,
        layout_confidence=kwargs.get("confidence"),
    )
```

### 3c. Update the router map

Replace the Picture/Figure routes:
```python
# OLD
"Picture": self.visual_asset_extractor.extract,
"Figure": self.visual_asset_extractor.extract,

# NEW  
"Picture": self._extract_and_save_visual,
"Figure": self._extract_and_save_visual,
```

### 3d. Remove the VisualAssetExtractor import and initialization

```python
# REMOVE this import:
from src.parsing_pipeline.extractors.visual_asset_extractor import VisualAssetExtractor

# REMOVE from __init__():
self.visual_asset_extractor = VisualAssetExtractor()

# UPDATE shutdown() — remove the visual_asset_extractor shutdown block
```

### 3e. Full diff summary for content_extraction_service.py

| Line/Section | Change |
|---|---|
| Import section | Replace `TableExtractor` → `PdfplumberTableExtractor`, remove `VisualAssetExtractor` import |
| `__init__` | Replace `TableExtractor(...)` → `PdfplumberTableExtractor()`, remove `VisualAssetExtractor()` |
| Router map | Replace `Picture`/`Figure` routes → `self._extract_and_save_visual` |
| New method | Add `_extract_and_save_visual()` method (code above) |
| `shutdown()` | Remove `visual_asset_extractor.shutdown()` block |

---

## Step 4: Modify `layout_analysis_service.py`

**File**: `src/parsing_pipeline/modules/layout_analysis_service.py`

### 4a. Enable ACCURATE TableFormer mode

In `__init__()`, update the pipeline options:

```python
# OLD
pipeline_options = PdfPipelineOptions(
    accelerator_options={"device": "cpu"},
    do_layout_analysis=True,
    generate_parsed_pages=True,
    do_ocr=False,
    do_table_structure=True,
)

# NEW
from docling.datamodel.pipeline_options import TableFormerMode

pipeline_options = PdfPipelineOptions(
    accelerator_options={"device": "cpu"},
    do_layout_analysis=True,
    generate_parsed_pages=True,
    do_ocr=False,
    do_table_structure=True,
    table_structure_options={
        "mode": TableFormerMode.ACCURATE,  # Higher accuracy for scanned PDFs
        "do_cell_matching": True,           # Match cells to text
    },
)
```

**Note**: If `TableFormerMode` is not available in your Docling version, check `docling.datamodel.pipeline_options` for the correct import. The option may be `TableStructureOptions(mode="accurate")` depending on version. Test with:
```python
from docling.datamodel.pipeline_options import TableStructureOptions, TableFormerMode
```

---

## Step 5: Modify `data_contracts.py`

**File**: `src/core/data_contracts.py`

### 5a. Add extraction metadata fields to ExtractedContent

Add after the `structured_data` field:

```python
class ExtractedContent(BaseModel):
    # ... existing fields ...
    
    structured_data: Optional[Dict[str, Any]] = Field(None, ...)
    
    # V2 ADDITION: Extraction provenance
    extraction_method: Optional[str] = Field(
        default=None,
        description="Extraction tier: 'pdfplumber-lines_strict', 'pdfplumber-text_fallback', "
                    "'docling-tableformer', 'gemini-2.5-flash', 'image-crop-for-gemini'"
    )
    extraction_confidence: Optional[float] = Field(
        default=None,
        description="Extraction confidence score 0.0-1.0 from the extractor"
    )
```

### 5b. Add same fields to ChildChunk

ChildChunk already has `extraction_confidence`. Add `extraction_method`:

```python
class ChildChunk(BaseModel):
    # ... existing fields ...
    
    # V2 ADDITION: Extraction provenance (after existing extraction_confidence)
    extraction_method: Optional[str] = Field(
        default=None,
        description="V2: Which extraction tier produced this chunk"
    )
```

---

## Step 6: Modify `table_contracts.py`

**File**: `src/core/table_contracts.py`

### 6a. Update TableExtractionMetadata

Replace the `extraction_method` description and add new fields:

```python
class TableExtractionMetadata(BaseModel):
    extraction_method: str = Field(
        ..., 
        description="'pdfplumber-lines_strict', 'pdfplumber-text_fallback', "
                    "'docling-tableformer', 'gemini-2.5-flash'"
    )
    # ... existing fields ...
    
    # V2 ADDITIONS
    needs_review: bool = Field(
        default=False,
        description="True if extraction confidence < 0.5 or quality issues detected"
    )
    original_image_path: Optional[str] = Field(
        default=None,
        description="Path to source image if extracted via vision (Gemini)"
    )
```

---

## Step 7: Modify `main.py`

**File**: `src/parsing_pipeline/main.py`

### 7a. Remove Florence-2 / VisualAssetExtractor references

The Florence-2 model is no longer loaded. The `ContentExtractionService.__init__()` change (Step 3) handles this. No changes needed in main.py for this.

### 7b. Add Phase 10b and 10c orchestration

Find the Phase 10 section (near line 640-690) and add Phase 10b/10c AFTER Phase 10.

Add this block after the existing Phase 10 submission code:

```python
    # Phase 10b: Visual Extraction via Gemini (tables + charts)
    print("\n\nPHASE 10b: VISUAL EXTRACTION (Gemini)")
    print("-" * 40)
    
    phase10b_completed = False
    try:
        from src.batch_pipeline.enrichment.gemini_visual_extractor import GeminiVisualExtractor
        
        # Find all chunk files for visual extraction
        chunk_files = sorted(Path("data/processed").glob("*_chunks.json"))
        
        if chunk_files:
            gemini_extractor = GeminiVisualExtractor()
            job_id = await gemini_extractor.submit_visual_extraction_job(
                json_files=chunk_files,
                pdf_dir="data/raw",
                skip_existing=True,
            )
            phase10b_completed = True
            print(f"✅ Phase 10b complete: {job_id}")
        else:
            print("No chunk files found for visual extraction.")
            
    except ImportError as e:
        print(f"⚠️  Gemini extraction not available: {e}")
        print("   Install: pip install google-genai")
        print("   Set GOOGLE_API_KEY in .env")
    except Exception as e:
        print(f"⚠️  Phase 10b failed: {e}")
        import traceback
        traceback.print_exc()
    
    # Phase 10c: Visual Post-Processing
    if phase10b_completed:
        print("\n\nPHASE 10c: VISUAL POST-PROCESSING")
        print("-" * 40)
        
        try:
            from src.batch_pipeline.enrichment.visual_post_processor import VisualPostProcessor
            
            processor = VisualPostProcessor()
            stats = processor.process_all(chunk_files)
            
            print(f"✅ Post-processing complete:")
            print(f"   Tables processed: {stats.get('tables_processed', 0)}")
            print(f"   TOC tables filtered: {stats.get('tables_filtered_toc', 0)}")
            print(f"   Tables hydrated: {stats.get('tables_hydrated', 0)}")
            print(f"   Charts hydrated: {stats.get('charts_hydrated', 0)}")
            print(f"   Titles enriched: {stats.get('titles_enriched', 0)}")
            
        except Exception as e:
            print(f"⚠️  Phase 10c failed: {e}")
```

**IMPORTANT**: Phase 10b uses `await` because `submit_visual_extraction_job` is async. The main pipeline's `run_full_pipeline` is already `async def`, so this works.

---

## Step 8: Modify `multi_page_table_handler.py`

**File**: `src/parsing_pipeline/modules/multi_page_table_handler.py`

### 8a. Simplify to grouping-only

The current merge logic in `_merge_fragments()` does programmatic row merging. This works for Tier 1/2 output (where we have StructuredTable objects). For Tier 3, Gemini handles merging natively (all page images sent in one request).

**No changes needed for now** — the existing handler works with StructuredTable objects from pdfplumber. Gemini multi-page merging is handled inside `gemini_visual_extractor.py`.

If you want to add Gemini-aware grouping later, add a method:

```python
def group_for_gemini(self, tables: List[StructuredTable]) -> List[List[StructuredTable]]:
    """Group table fragments for Gemini multi-page extraction (detection only, no merge)."""
    # Same logic as detect_and_merge but returns groups instead of merging
    groups = []
    i = 0
    sorted_tables = sorted(tables, key=lambda t: t.source_page_physical)
    
    while i < len(sorted_tables):
        group = [sorted_tables[i]]
        j = i + 1
        while j < len(sorted_tables) and self._should_merge(group[-1], sorted_tables[j]):
            group.append(sorted_tables[j])
            j += 1
        groups.append(group)
        i = j
    
    return groups
```

---

## Step 9: Archive Old Files

```bash
# Create archive directory
mkdir -p src/parsing_pipeline/extractors/_archived_v1

# Move old extractors (don't delete — keep for reference)
mv src/parsing_pipeline/extractors/table_extractor.py \
   src/parsing_pipeline/extractors/_archived_v1/table_extractor.py

mv src/parsing_pipeline/extractors/visual_asset_extractor.py \
   src/parsing_pipeline/extractors/_archived_v1/visual_asset_extractor.py
```

---

## Execution Sequence

Run these steps in order:

| # | Action | Type |
|---|--------|------|
| 1 | `pip install pdfplumber google-genai` | Shell |
| 2 | Place 3 new files (Step 2) | Copy |
| 3 | Modify `content_extraction_service.py` (Step 3) | Edit |
| 4 | Modify `layout_analysis_service.py` (Step 4) | Edit |
| 5 | Modify `data_contracts.py` (Step 5) | Edit |
| 6 | Modify `table_contracts.py` (Step 6) | Edit |
| 7 | Modify `main.py` (Step 7) | Edit |
| 8 | Archive old files (Step 9) | Shell |
| 9 | Test with one native PDF report | Verify |
| 10 | Test with one scanned PDF report | Verify |

---

## Verification Checklist

After implementation, verify:

- [ ] `PdfplumberTableExtractor` produces markdown + StructuredTable for native PDFs
- [ ] Figure/Picture blocks save PNG images to `data/extraction_images/charts/`
- [ ] No Florence-2 or TATR models are loaded (check startup logs — should be much faster)
- [ ] Phase 10b runs Gemini extraction on saved images (if API key configured)
- [ ] Phase 10c post-processes: TOC filtering, title enrichment, hydration
- [ ] Existing downstream pipeline (chunking, assembly, enrichment) works unchanged
- [ ] `model_used` field correctly reflects extraction method in output JSONs

---

## What's NOT Changed

These files remain untouched:
- `structured_table_extractor.py` — still converts markdown → StructuredTable JSON
- `chart_contracts.py` — StructuredChart model unchanged
- `batch_service.py` — Phase 10 Anthropic batch unchanged
- `phase10_service.py` — Overview/summary generation unchanged
- `chunk_filter_service.py` — Garbage filtering unchanged
- `text_extractor.py` — Text extraction unchanged
- `chunking_service.py` — Chunking logic unchanged
- `assembly_service.py` — Assembly unchanged

---

## Cost Estimate

- **Tier 1 (pdfplumber)**: $0 — pure CPU text parsing
- **Tier 2 (Docling ACCURATE)**: $0 — local model
- **Tier 3 (Gemini 2.5 Flash)**: ~$0-1 for 14 reports using free tier (15 RPM, 1M tokens/day)
- **Total per pipeline run**: $0-1 vs previous $0 (but previous produced 0% usable output)
