"""Phase 6: Docling labels, block IDs, bound captions, and caption/unit/source folding."""

from unittest.mock import patch

import pytest

from src.core.data_contracts import ExtractedContent
from src.parsing_pipeline.modules.captions import is_source_note, parse_caption, unit_of
from src.parsing_pipeline.modules.content_extraction_service import (
    ContentExtractionService,
)

MODULE = "src.parsing_pipeline.modules.content_extraction_service"
TABLE_MD = "| District | Amount |\n| --- | --- |\n| Kullu | 847.71 |\n| Mandi | 12.50 |"


@pytest.fixture
def service():
    with patch(f"{MODULE}.PdfplumberTableExtractor"), patch(f"{MODULE}.TextExtractor"):
        return ContentExtractionService()


def _item(content_type, content, page=3, y=100.0, sd=None):
    return ExtractedContent(
        content_type=content_type,
        content=content,
        source_page_physical=page,
        source_bbox=[50.0, y, 500.0, y + 20],
        model_used="t",
        layout_label="Text",
        structured_data=sd,
    )


def _table(service, page=3, y=200.0):
    sd = service.structured_table_extractor.extract(
        markdown_table=TABLE_MD,
        table_id="t1",
        source_chunk_id="p003_b002",
        source_page_physical=page,
        source_bbox=[50, y, 500, y + 100],
    ).model_dump()
    return _item("table_markdown", TABLE_MD, page, y, sd)


@pytest.mark.parametrize(
    "text,kind,number",
    [
        ("Table 3.2: Details of grants", "table", "3.2"),
        ("Chart 1.1: Budget vs expenditure", "chart", "1.1"),
        ("Figure 5: Argo Float Density", "figure", "5"),
        ("Statement-2.4 Funds released", "statement", "2.4"),
    ],
)
def test_parse_caption(text, kind, number):
    parsed = parse_caption(text)
    assert parsed["kind"] == kind and parsed["number"] == number


@pytest.mark.parametrize(
    "text", ["Report No. 8 of 2025", "The table below shows", "Tables were checked"]
)
def test_not_captions(text):
    assert parse_caption(text) is None


def test_unit_and_source_lines():
    assert unit_of("(₹ in crore)") == "₹ in crore"
    assert unit_of("(Rs. in lakh)") == "₹ in lakh"
    assert unit_of("(₹ in crore) of which 20 per cent was spent") is None
    assert is_source_note("(Source: UDISE+ database)")
    assert is_source_note("Note: Figures are provisional")
    assert not is_source_note("Sources of funds for PRIs are grants")


def test_caption_unit_and_source_join_their_table(service):
    items = [
        _item("paragraph", "The position is shown below.", y=100),
        _item("caption", "Table 2.1: Grants released to ULBs", y=150),
        _item("paragraph", "(₹ in crore)", y=180),
        _table(service, y=200),
        _item("paragraph", "(Source: Finance Accounts)", y=320),
        _item("paragraph", "Audit noticed that ...", y=360),
    ]
    out = service._attach_to_tables_and_figures(items)

    assert [i.content_type for i in out] == ["paragraph", "table_markdown", "paragraph"]
    table = out[1]
    sd = table.structured_data
    assert sd["caption"] == "Table 2.1: Grants released to ULBs"
    assert sd["table_number"] == "2.1"
    assert sd["footnotes"] == ["(Source: Finance Accounts)"]
    assert sd["monetary_unit"] == "₹ in crore"
    assert sd["source_chunk_id"] == "p003_b002"
    assert table.content.startswith(
        "Table 2.1: Grants released to ULBs\n(₹ in crore)\n| District"
    )


def test_caption_below_figure_and_other_page_untouched(service):
    figure = _item(
        "image_caption",
        "data/extraction_images/charts/x.png",
        y=100,
        sd={"visual_subtype": None},
    )
    items = [
        _item("caption", "Table 9.9: on another page", page=2, y=700),
        figure,
        _item("paragraph", "Chart 1.1: Budget and expenditure", y=400),
    ]
    out = service._attach_to_tables_and_figures(items)
    assert len(out) == 2
    assert out[1].structured_data["caption"] == "Chart 1.1: Budget and expenditure"
    assert out[1].structured_data["figure_number"] == "1.1"
    assert out[0].content_type == "caption"


def test_finish_block_ids_types_and_docling_caption(service):
    caption = _item("paragraph", "Table 1.1: Grants")
    service._finish_block(caption, {"label": "Caption"}, page_num=12, index=3)
    assert caption.block_id == "p012_b003" and caption.content_type == "caption"

    item = _item("paragraph", "(i) first point")
    service._finish_block(
        item, {"label": "List-item", "prov_index": 1}, page_num=12, index=4
    )
    assert item.block_id == "p012_b004_1" and item.content_type == "list"

    table = _table(service)
    table.structured_data["source_chunk_id"] = "temp"
    service._finish_block(
        table,
        {
            "label": "Table",
            "docling_caption": "Table 4.2: Pending UCs",
            "docling_footnotes": ["Source: Departmental records"],
        },
        page_num=3,
        index=2,
    )
    sd = table.structured_data
    assert sd["source_chunk_id"] == "p003_b002"
    assert sd["caption"] == "Table 4.2: Pending UCs" and sd["table_number"] == "4.2"
    assert sd["footnotes"] == ["Source: Departmental records"]


def test_bound_caption_block_is_skipped(service):
    block = {"label": "Caption", "bbox": [0, 0, 1, 1], "bound_to": "#/tables/0"}
    assert (
        service._skip_reason(block, "x.pdf", 0, is_scanned=False)
        == "bound_to_table_or_picture"
    )


def test_cross_page_merge_skips_footnotes_between_halves(service):
    first = _item("paragraph", "The department released funds to the", page=4, y=600)
    first.block_id = "p004_b010"
    note = _item("footnote", "[Footnote 3] As per GO dated 1.4.2021", page=4, y=780)
    second = _item("paragraph", "municipal bodies during 2021-22.", page=5, y=80)
    out = service._merge_cross_page_paragraphs([first, note, second])
    assert [i.content_type for i in out] == ["paragraph", "footnote"]
    assert out[0].content.endswith("bodies during 2021-22.")
    assert out[0].block_id == "p004_b010"


def test_non_money_unit_line_between_caption_and_table(service):
    items = [
        _item("caption", "Table 3: Norm and consumption of iron ore lump", y=150),
        _item("paragraph", "(unit: kg/tonne of hot metal)", y=180),
        _table(service, y=200),
        _item("footnote", "[Footnote] $ Borrowings and other liabilities: net", y=320),
        _item("paragraph", "* Includes amounts received during 2022-23", y=330),
    ]
    out = service._attach_to_tables_and_figures(items)
    assert [i.content_type for i in out] == ["table_markdown"]
    sd = out[0].structured_data
    assert sd["table_number"] == "3"
    assert sd["unit_line"] == "(unit: kg/tonne of hot metal)"
    assert sd["footnotes"] == ["$ Borrowings and other liabilities: net",
                               "* Includes amounts received during 2022-23"]


def test_source_line_labelled_footnote_is_not_a_footnote(service):
    service.text_extractor.extract.return_value = _item("paragraph", "Source: Finance Accounts")
    result = service._extract_footnote("x.pdf", 3, [0, 0, 1, 1])
    assert result.content_type == "paragraph" and result.content == "Source: Finance Accounts"
