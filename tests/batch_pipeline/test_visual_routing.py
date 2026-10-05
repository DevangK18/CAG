"""
Phase 10b routing and write-back: only charts reach the chart prompt, no image chunk
keeps a file path as its text, and chart values land in searchable content.
"""

import asyncio
import copy
import json
from types import SimpleNamespace

import pytest

from src.batch_pipeline.enrichment.gemini_visual_extractor import (
    CHART_EXTRACTION_PROMPT,
    DIAGRAM_DESCRIPTION_PROMPT,
    GeminiVisualExtractor,
    build_chart_text,
    chunk_image_path,
    classify_caption,
    has_chart_values,
    is_image_path,
    linearise_chart_values,
)
from src.batch_pipeline.enrichment.visual_post_processor import VisualPostProcessor

MODEL = "gemini-test-flash"
CHART_BBOX = [70, 300, 520, 520]


def _extractor(tmp_path):
    ext = GeminiVisualExtractor(
        model=MODEL,
        batch_jobs_dir=str(tmp_path / "jobs"),
        images_dir=str(tmp_path / "images"),
    )
    ext.retry_pause_s = None
    return ext


def _image(chunk_id, page=10, bbox=CHART_BBOX, content="", **structured):
    return {
        "chunk_id": chunk_id,
        "content_type": "image_caption",
        "content": content,
        "source_page_physical": page,
        "metadata": {"location": {"bbox": bbox}},
        "extraction_method": "image-crop-for-gemini",
        "model_used": "image-crop-for-gemini",
        "structured_data": structured,
    }


def _text(chunk_id, text, page=10, bbox=(70, 525, 520, 540)):
    return {
        "chunk_id": chunk_id,
        "content_type": "paragraph",
        "content": text,
        "source_page_physical": page,
        "metadata": {"location": {"bbox": list(bbox)}},
    }


# ---------- helpers ----------


def test_caption_classification():
    assert classify_caption("Chart 1.1: Budgetary provision and expenditure") == "chart"
    assert classify_caption("Figure 2.10: Components of Gross Tax Revenue") == "chart"
    assert classify_caption("Graph 4.1: Release of funds under PMKVY") == "chart"
    assert classify_caption("Chart 1.1: Organisational setup of CBDT") == "diagram"
    assert classify_caption("Flow Chart 3.1: Progress of NHDP") == "diagram"
    assert classify_caption("Picture 5.3; dated 23.09.2023") == "photo"
    assert classify_caption("Figure 8: Picture of Potholes on NH 32") == "photo"
    assert classify_caption("Exhibit 1.1 Geographical map of sample") == "map"
    assert classify_caption("The chart below shows the trend") is None
    assert classify_caption("") is None


def test_image_path_detection():
    assert is_image_path("data/extraction_images/charts/R_picture_p3_10_20.png")
    assert is_image_path("/abs/dir/R_chart_p3_1_2.jpg")
    assert not is_image_path("Chart 1.1: Budget and expenditure")
    assert not is_image_path("")
    new = _image("a", content="Chart 1.1", image_path="x/a.png")
    old = _image("b", content="data/extraction_images/charts/b.png")
    assert chunk_image_path(new) == "x/a.png"
    assert chunk_image_path(old) == "data/extraction_images/charts/b.png"
    assert chunk_image_path(_image("c", content="Chart 1.1")) is None


def test_values_are_linearised_and_capped():
    series = [
        {
            "name": "Budgetary Provision",
            "data_points": [
                {"category": "2018-19", "value": 15737.21},
                {"category": "2019-20", "value": 17388.0},
                {"category": "2020-21", "value": None},
            ],
        },
        {
            "series_name": "Expenditure",
            "data_points": [{"category": "2018-19", "value": "14,161.88"}],
        },
    ]
    text = linearise_chart_values(series, "crore")
    assert text.splitlines() == [
        "Chart values (crore):",
        "Budgetary Provision: 2018-19 15737.21; 2019-20 17388",
        "Expenditure: 2018-19 14,161.88",
    ]
    assert has_chart_values(text)

    long = [
        {
            "name": "S",
            "data_points": [{"category": f"c{i}", "value": i} for i in range(500)],
        }
    ]
    capped = linearise_chart_values(long, max_chars=200)
    assert len(capped) <= 200 and capped.endswith(" …")
    assert linearise_chart_values([]) == ""


def test_chart_text_keeps_head_and_skips_duplicate_values():
    head = "Chart 1.1: Budget\nChart values:\nBudget: 2019-20 10"
    assert build_chart_text(
        head,
        "Bars by year",
        [{"name": "x", "data_points": [{"category": "a", "value": 1}]}],
    ) == (head + "\nBars by year")


# ---------- routing ----------


def _route(ext, chunk, *others):
    by_page = {}
    for c in (chunk, *others):
        by_page.setdefault(c["source_page_physical"], []).append(c)
    return ext._route_image(chunk, by_page)


@pytest.mark.parametrize(
    "subtype,kind,reason",
    [
        ("chart", "chart", None),
        ("map", "diagram", None),
        ("diagram", "diagram", None),
        ("flowchart", "diagram", None),
        ("photo", None, "photo"),
        ("non_data", None, "non_data"),
        ("table_as_image", "table", None),
    ],
)
def test_new_shape_routes_by_subtype(tmp_path, subtype, kind, reason):
    ext = _extractor(tmp_path)
    chunk = _image(
        "a", content="Chart 1.1: X", image_path="a.png", visual_subtype=subtype
    )
    route = _route(ext, chunk)
    assert (route["kind"], route["reason"]) == (kind, reason)


def test_unknown_subtype_needs_chart_caption_or_printed_numbers(tmp_path):
    ext = _extractor(tmp_path)
    captioned = _image(
        "a",
        content="Figure 2.2: Trends of GDP",
        image_path="a.png",
        caption="Figure 2.2: Trends of GDP",
    )
    numbers = _image(
        "b", image_path="b.png", embedded_text="2019-20 2020-21 12.5 13.1 14.2 15.0"
    )
    bare = _image("c", image_path="c.png", embedded_text="Source: Finance Accounts")
    assert _route(ext, captioned)["kind"] == "chart"
    assert _route(ext, numbers)["kind"] == "chart"
    assert _route(ext, bare)["reason"] == "unclassified"


def test_non_data_images_are_never_sent(tmp_path):
    ext = _extractor(tmp_path)
    signature = _image(
        "s", bbox=[300, 600, 420, 655], image_path="s.png", visual_subtype="chart"
    )
    cover = _image("c", page=0, image_path="c.png", visual_subtype="chart")
    banner = _image(
        "b", bbox=[174, 71, 542, 108], image_path="b.png", visual_subtype="chart"
    )
    for chunk in (signature, cover, banner):
        assert _route(ext, chunk)["reason"] == "non_data"


def test_old_output_photo_label_is_ignored_and_caption_decides(tmp_path):
    ext = _extractor(tmp_path)
    path = "data/extraction_images/charts/R_picture_p10_70_300.png"
    chunk = _image("a", content=path, visual_subtype="photo")
    caption = _text("t", "Chart 1.1: Budgetary provision vis-à-vis expenditure")
    far = _text("f", "Chart 1.2: Something else", bbox=(70, 700, 520, 715))
    route = _route(ext, chunk, caption, far)
    assert route["kind"] == "chart" and route["legacy"]
    assert route["caption"] == caption["content"]
    # Tier-3 table crops in old output carry layout label Table
    crop = _image("t", content=path, visual_subtype="unknown")
    crop["metadata"]["extraction"] = {"layout_label": "Table"}
    assert _route(ext, crop)["kind"] == "table"


# ---------- the 10b item loop with a fake Gemini client ----------

CHART_REPLY = {
    "title": "Budget vs expenditure",
    "chart_type": "bar",
    "monetary_unit": "crore",
    "series": [
        {
            "name": "Budgetary Provision",
            "data_points": [{"category": "2018-19", "value": 15737.21}],
        },
        {
            "name": "Expenditure",
            "data_points": [{"category": "2018-19", "value": 14161.88}],
        },
    ],
    "description": "Budget and expenditure by year.",
}
DIAGRAM_REPLY = {"title": None, "description": "Organisation chart of the department."}


def _write_report(tmp_path, chunks):
    path = tmp_path / "R_chunks.json"
    path.write_text(
        json.dumps(
            {
                "report_metadata": {"report_id": "R", "source_filename": "missing.pdf"},
                "processing_stats": {},
                "child_chunks": chunks,
            }
        )
    )
    return path


def test_item_loop_routes_and_writes_text_not_paths(tmp_path):
    ext = _extractor(tmp_path)
    images = tmp_path / "img"
    images.mkdir()
    for name in ("chart", "vector", "map", "photo", "fail", "old", "oldphoto"):
        (images / f"{name}.png").write_bytes(b"png")
    old_path = str(images / "old.png")
    old_photo_path = str(images / "oldphoto.png")

    chunks = [
        _image(
            "chart",
            content="Chart 1.1: Budget",
            image_path=str(images / "chart.png"),
            visual_subtype="chart",
            caption="Chart 1.1: Budget",
            figure_number="1.1",
        ),
        _image(
            "vector",
            page=11,
            content="Chart 1.2: Grants | 2019-20 2020-21 | Grants 10 12",
            image_path=str(images / "vector.png"),
            visual_subtype="chart",
            caption="Chart 1.2: Grants",
            embedded_text="2019-20 2020-21 Grants 10 12",
        ),
        _image(
            "map",
            page=12,
            content="Map 2.1: Sampled districts",
            image_path=str(images / "map.png"),
            visual_subtype="map",
            caption="Map 2.1: Sampled districts",
        ),
        _image(
            "photo",
            page=13,
            content="Picture 3.1: Site",
            image_path=str(images / "photo.png"),
            visual_subtype="photo",
            caption="Picture 3.1: Site",
        ),
        _image(
            "fail",
            page=14,
            content="Chart 4.1: Arrears",
            image_path=str(images / "fail.png"),
            visual_subtype="chart",
            caption="Chart 4.1: Arrears",
        ),
        # Output written before PR 7: path in content, meaningless "photo" label
        _image("old", page=15, content=old_path, visual_subtype="photo"),
        _text("old_cap", "Figure 5.1: Trend of revenue receipts", page=15),
        _image("oldphoto", page=16, content=old_photo_path, visual_subtype="photo"),
    ]
    json_path = _write_report(tmp_path, chunks)

    sent = []

    async def fake_generate(tag="", **kwargs):
        prompt = kwargs["contents"][1].text
        image = kwargs["contents"][0]
        sent.append((tag, prompt))
        if "fail" in str(image) or "Arrears" in prompt:
            raise RuntimeError("400 INVALID_ARGUMENT")
        reply = (
            DIAGRAM_REPLY
            if prompt.startswith(DIAGRAM_DESCRIPTION_PROMPT)
            else CHART_REPLY
        )
        return SimpleNamespace(text=json.dumps(reply))

    ext._generate = fake_generate
    asyncio.run(ext.submit_visual_extraction_job([json_path], pdf_dir=str(tmp_path)))

    chart_calls = [p for _, p in sent if p.startswith(CHART_EXTRACTION_PROMPT)]
    diagram_calls = [p for _, p in sent if p.startswith(DIAGRAM_DESCRIPTION_PROMPT)]
    assert len(chart_calls) == 4  # chart, vector, fail, old (by its Figure caption)
    assert len(diagram_calls) == 1  # map
    assert len(sent) == 5  # the photos never go out

    out = {c["chunk_id"]: c for c in json.loads(json_path.read_text())["child_chunks"]}
    assert not any(is_image_path(c["content"]) for c in out.values())

    chart = out["chart"]
    assert chart["content"].startswith(
        "Chart 1.1: Budget\nBudget and expenditure by year."
    )
    assert "Budgetary Provision: 2018-19 15737.21" in chart["content"]
    assert chart["structured_data"]["image_path"].endswith("chart.png")
    assert chart["structured_data"]["visual_subtype"] == "chart"
    assert chart["structured_data"]["figure_number"] == "1.1"
    assert chart["structured_data"]["series"]
    assert chart["extraction_method"] == MODEL and chart["model_used"] == MODEL

    # Text-layer values from Phase 6 survive the rewrite
    vector = out["vector"]
    assert vector["content"].startswith(
        "Chart 1.2: Grants | 2019-20 2020-21 | Grants 10 12"
    )
    assert vector["structured_data"]["embedded_text"] == "2019-20 2020-21 Grants 10 12"

    assert (
        out["map"]["content"]
        == "Map 2.1: Sampled districts\nOrganisation chart of the department."
    )
    assert "series" not in out["map"]["structured_data"]

    assert out["photo"]["content"] == "Picture 3.1: Site"
    assert out["photo"]["structured_data"]["skipped"] == "photo"

    failed = out["fail"]
    assert failed["content"] == "Chart 4.1: Arrears"
    assert "INVALID_ARGUMENT" in failed["structured_data"]["extraction_error"]

    old = out["old"]
    assert old["content"].startswith("Figure 5.1: Trend of revenue receipts\n")
    assert old["structured_data"]["image_path"] == old_path
    assert old["structured_data"]["visual_subtype"] == "chart"

    old_photo = out["oldphoto"]
    assert old_photo["content"] == ""
    assert old_photo["structured_data"] == {
        "visual_subtype": None,
        "image_path": old_photo_path,
        "skipped": "unclassified",
    }

    # A second run sends nothing new except the earlier failure
    sent.clear()
    asyncio.run(ext.submit_visual_extraction_job([json_path], pdf_dir=str(tmp_path)))
    assert len(sent) == 1 and "Arrears" in sent[0][1]


# ---------- Phase 10c ----------


def test_chart_hydration_keeps_real_image_path_and_phase6_fields():
    vp = VisualPostProcessor()
    chunk = _image("a", content="Chart 1.1: Budget\n...", extraction_method=None)
    chunk["extraction_method"] = MODEL
    structured = {
        **copy.deepcopy(CHART_REPLY),
        "image_path": "data/extraction_images/charts/a.png",
        "visual_subtype": "chart",
        "caption": "Chart 1.1: Budget",
        "embedded_text": "2018-19",
    }
    structured["series"][0]["data_points"].append(
        {"category": "2019-20", "value": "17,388.09"}
    )
    chart = vp._hydrate_chart(chunk, structured)
    assert chart["image_path"] == "data/extraction_images/charts/a.png"
    assert chart["extraction_method"] == MODEL
    assert (
        chart["visual_subtype"] == "chart" and chart["caption"] == "Chart 1.1: Budget"
    )
    assert [dp["value"] for dp in chart["series"][0]["data_points"]] == [
        15737.21,
        17388.09,
    ]


def test_old_hydrated_charts_get_values_in_content(tmp_path):
    chunk = _image("a", content="Bar chart of budget by year.")
    chunk["extraction_method"] = "gemini-2.5-flash-vision"
    chunk["structured_data"] = {
        "chart_id": "chart_1",
        "series": [
            {
                "series_name": "Budget",
                "data_points": [{"category": "2019-20", "value": 10.0}],
            }
        ],
        "monetary_unit": "crore",
    }
    path = _write_report(tmp_path, [chunk])
    VisualPostProcessor().process_file(path)
    content = json.loads(path.read_text())["child_chunks"][0]["content"]
    assert (
        content
        == "Bar chart of budget by year.\nChart values (crore):\nBudget: 2019-20 10"
    )
    # Idempotent
    VisualPostProcessor().process_file(path)
    assert json.loads(path.read_text())["child_chunks"][0]["content"] == content
