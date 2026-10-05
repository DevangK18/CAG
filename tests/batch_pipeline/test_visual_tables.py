"""
Phase 10b/10c tables: the contents filter flags only front-matter contents lists, table
captions reach searchable text, and Tier-3 table crops go to the table prompt.
"""

import asyncio
import json
from types import SimpleNamespace

from src.batch_pipeline.enrichment.gemini_visual_extractor import (
    CHART_EXTRACTION_PROMPT,
    TABLE_EXTRACTION_PROMPT,
    GeminiVisualExtractor,
)
from src.batch_pipeline.enrichment.visual_post_processor import VisualPostProcessor

CONTENTS = """| Particulars | Paragraph | Page No. |
| --- | --- | --- |
| Preface | - | v |
| Overview | - | vii-x |
| Chapter-1 Profile of PRIs | 1.1 | 1 |
| Audit mandate | 1.2 | 1 |
| Financial profile | 1.4 | 3-6 |
| Results of audit | 2.1 | 11-17 |"""

STAFF = """| Sl No | Post | Sanctioned | In position | Vacancy |
| --- | --- | --- | --- | --- |
| 1 | Executive Officer | 12 | 9 | 3 |
| 2 | Accountant | 40 | 22 | 18 |
| 3 | Clerk | 75 | 61 | 14 |
| 4 | Driver | 20 | 18 | 2 |"""


def _chunk(chunk_id, content_type, content, page, bbox, **extra):
    return {
        "chunk_id": chunk_id,
        "content_type": content_type,
        "content": content,
        "source_page_physical": page,
        "metadata": {"location": {"bbox": list(bbox)}},
        **extra,
    }


def _report(chunks, pages=60):
    filler = [
        _chunk(f"p{i}", "paragraph", "Text.", i, (70, 700, 520, 720))
        for i in range(pages)
    ]
    heading = _chunk("h", "header", "CHAPTER-1", 10, (70, 80, 520, 100))
    return {
        "report_metadata": {"report_id": "R"},
        "parent_chunks": [],
        "child_chunks": filler + [heading] + chunks,
    }


# ---------- contents filter ----------


def test_contents_table_flagged_only_in_front_matter():
    vp = VisualPostProcessor()
    data = _report([])
    ctx = vp._report_context(data)
    assert ctx == {"front_matter_end": 10, "page_count": 60}

    toc = _chunk("t", "table_markdown", CONTENTS, 4, (70, 100, 520, 600))
    assert vp._is_toc_table(toc, ctx)
    late = _chunk("l", "table_markdown", CONTENTS, 30, (70, 100, 520, 600))
    assert not vp._is_toc_table(late, ctx)


def test_data_tables_with_small_numbers_are_not_contents():
    vp = VisualPostProcessor()
    ctx = {"front_matter_end": 10, "page_count": 60}
    staff = _chunk("s", "table_markdown", STAFF, 5, (70, 100, 520, 400))
    assert not vp._is_toc_table(staff, ctx)  # last column goes down
    beyond = CONTENTS.replace("11-17", "611")
    assert not vp._is_toc_table(
        _chunk("b", "table_markdown", beyond, 4, (70, 100, 520, 600)), ctx
    )


def test_front_matter_falls_back_to_page_share():
    vp = VisualPostProcessor()
    data = _report([], pages=200)
    data["child_chunks"] = [c for c in data["child_chunks"] if c["chunk_id"] != "h"]
    assert vp._report_context(data)["front_matter_end"] == 24


def test_flag_writes_postprocess_confidence_not_extraction_confidence(tmp_path):
    toc = _chunk(
        "t",
        "table_markdown",
        CONTENTS,
        4,
        (70, 100, 520, 600),
        extraction_confidence=0.9,
        structured_data={"rows": []},
    )
    staff = _chunk(
        "s",
        "table_markdown",
        STAFF,
        30,
        (70, 100, 520, 400),
        extraction_confidence=0.8,
        structured_data={"rows": [], "_filtered_reason": "toc_detected"},
    )
    path = tmp_path / "R_chunks.json"
    path.write_text(json.dumps(_report([toc, staff])))
    VisualPostProcessor().process_file(path)
    out = {c["chunk_id"]: c for c in json.loads(path.read_text())["child_chunks"]}
    assert out["t"]["extraction_confidence"] == 0.9
    assert out["t"]["postprocess_confidence"] == 0.05
    assert out["t"]["structured_data"]["_filtered_reason"] == "toc_detected"
    assert out["s"]["extraction_confidence"] == 0.8
    assert "postprocess_confidence" in out["s"]
    assert "_filtered_reason" not in out["s"]["structured_data"]  # stale flag cleared


# ---------- table captions ----------


def _caption_case(*above):
    table = _chunk(
        "tbl",
        "table_markdown",
        STAFF,
        30,
        (70, 300, 520, 500),
        structured_data={"rows": [], "title": None},
    )
    by_page = {30: [table, *above]}
    return table, by_page


def test_printed_table_caption_reaches_content():
    vp = VisualPostProcessor()
    caption = _chunk(
        "c", "paragraph", "Table 3.2: Staff position", 30, (70, 250, 520, 265)
    )
    unit = _chunk("u", "paragraph", "(₹ in crore)", 30, (400, 270, 520, 285))
    table, by_page = _caption_case(caption, unit)
    assert vp._needs_title(table)
    found = vp._infer_title(table, by_page)
    assert found == "Table 3.2: Staff position"
    vp._apply_caption(table, found)
    assert table["content"].startswith("Table 3.2: Staff position\n\n| Sl No")
    assert table["structured_data"]["caption"] == found
    assert table["structured_data"]["title"] == found


def test_loose_paragraph_or_earlier_table_caption_is_not_a_title():
    vp = VisualPostProcessor()
    para = _chunk("p", "paragraph", "Details are given below.", 30, (70, 280, 520, 295))
    table, by_page = _caption_case(para)
    assert vp._infer_title(table, by_page) is None

    # "Table 3.1" belongs to the table above, not to this one
    first_caption = _chunk(
        "c1", "paragraph", "Table 3.1: Grants", 30, (70, 60, 520, 75)
    )
    first_table = _chunk("t1", "table_markdown", STAFF, 30, (70, 80, 520, 290))
    table, by_page = _caption_case(first_caption, first_table)
    assert vp._infer_title(table, by_page) is None


def test_table_with_phase6_caption_needs_no_title():
    vp = VisualPostProcessor()
    table = _chunk(
        "t",
        "table_markdown",
        STAFF,
        30,
        (70, 300, 520, 500),
        structured_data={"caption": "Table 3.2: Staff", "table_number": "3.2"},
    )
    assert not vp._needs_title(table)


# ---------- Tier-3 table crops ----------


def test_table_crop_goes_to_table_prompt_and_is_hydrated(tmp_path):
    ext = GeminiVisualExtractor(
        model="gemini-test-flash",
        batch_jobs_dir=str(tmp_path / "jobs"),
        images_dir=str(tmp_path / "images"),
    )
    ext.retry_pause_s = None
    crop_png = tmp_path / "crop.png"
    crop_png.write_bytes(b"png")
    old_png = tmp_path / "old.png"
    old_png.write_bytes(b"png")

    crop = _chunk(
        "crop",
        "image_caption",
        "Table 4.1: Pending utilisation certificates",
        30,
        (70, 300, 520, 500),
        structured_data={
            "image_path": str(crop_png),
            "visual_subtype": "table_as_image",
            "caption": "Table 4.1: Pending utilisation certificates",
        },
    )
    # Old output: crop saved as image_caption with layout label Table, path in content
    old = _chunk(
        "old",
        "image_caption",
        str(old_png),
        31,
        (70, 300, 520, 500),
        structured_data={"visual_subtype": "unknown"},
    )
    old["metadata"]["extraction"] = {"layout_label": "Table"}
    text_table = _chunk(
        "pdfplumber",
        "table_markdown",
        STAFF,
        32,
        (70, 300, 520, 500),
        structured_data={"rows": [{"cells": []}]},
    )
    path = tmp_path / "R_chunks.json"
    path.write_text(
        json.dumps(
            {
                "report_metadata": {"report_id": "R", "source_filename": "R.pdf"},
                "processing_stats": {},
                "child_chunks": [crop, old, text_table],
            }
        )
    )

    sent = []
    reply = {
        "title": None,
        "markdown": "| Year | UCs due |\n| --- | --- |\n| 2019-20 | 1,234 |\n| 2020-21 | 2,345 |",
        "monetary_unit": "crore",
        "extraction_notes": [],
    }

    async def fake_generate(tag="", **kwargs):
        sent.append(kwargs["contents"][1].text)
        return SimpleNamespace(text=json.dumps(reply))

    ext._generate = fake_generate
    asyncio.run(ext.submit_visual_extraction_job([path], pdf_dir=str(tmp_path)))

    assert len(sent) == 2  # the two crops; text-layer tables are never re-extracted
    assert all(p.startswith(TABLE_EXTRACTION_PROMPT) for p in sent)
    assert not any(p.startswith(CHART_EXTRACTION_PROMPT) for p in sent)

    out = {c["chunk_id"]: c for c in json.loads(path.read_text())["child_chunks"]}
    table = out["crop"]
    assert table["content_type"] == "table_markdown"
    assert table["content"].startswith(
        "Table 4.1: Pending utilisation certificates\n\n| Year"
    )
    assert table["structured_data"]["visual_subtype"] == "table_as_image"
    assert table["extraction_method"] == "gemini-test-flash"
    assert out["old"]["content_type"] == "table_markdown"
    assert out["old"]["structured_data"]["image_path"] == str(old_png)

    VisualPostProcessor().process_file(path)
    out = {c["chunk_id"]: c for c in json.loads(path.read_text())["child_chunks"]}
    hydrated = out["crop"]["structured_data"]
    assert hydrated["num_rows"] >= 2 and hydrated["rows"]
    assert hydrated["title"] == "Table 4.1: Pending utilisation certificates"
    assert hydrated["caption"] == "Table 4.1: Pending utilisation certificates"
    assert hydrated["image_path"] == str(crop_png)
    assert hydrated["monetary_unit"] == "₹ in crore"
    assert hydrated["_extraction_method"] == "gemini-test-flash"
    assert out["crop"]["content"].startswith("Table 4.1: Pending")


def test_pdf_resolved_under_tier_directory(tmp_path):
    tier_dir = tmp_path / "state"
    tier_dir.mkdir()
    (tier_dir / "R.pdf").write_bytes(b"%PDF")
    meta = {"source_filename": "R.pdf", "government_body_type": "state"}
    assert GeminiVisualExtractor._resolve_pdf(str(tmp_path), meta) == str(
        tier_dir / "R.pdf"
    )
    assert GeminiVisualExtractor._resolve_pdf(str(tier_dir), meta) == str(
        tier_dir / "R.pdf"
    )
    assert (
        GeminiVisualExtractor._resolve_pdf(str(tmp_path), {"source_filename": "X.pdf"})
        is None
    )
