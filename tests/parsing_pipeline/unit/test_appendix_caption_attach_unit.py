"""Phase 6: appendix captions separated from their table by a title and a reference line.

For the main session: add to tests/parsing_pipeline/unit/ together with the
content_extraction_service.patch (needs captions.appendix_caption_above, PR 9 tables).
"""

from unittest.mock import patch

import pytest

from src.core.data_contracts import ExtractedContent
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


def _table(service, page=3, y=200.0, table_id="t1"):
    sd = service.structured_table_extractor.extract(
        markdown_table=TABLE_MD,
        table_id=table_id,
        source_chunk_id=f"p{page:03d}_{table_id}",
        source_page_physical=page,
        source_bbox=[50, y, 500, y + 100],
    ).model_dump()
    return _item("table_markdown", TABLE_MD, page, y, sd)


def test_appendix_caption_reference_and_title_above(service):
    items = [
        _item("caption", "Appendix 1.4", y=60),
        _item("caption", "(Reference: Paragraph 1.4.2.4/Page 9)", y=80),
        _item("header", "Statement showing amount under PWD cheques", y=100),
        _table(service),
    ]
    out = service._attach_to_tables_and_figures(items)
    assert [i.content_type for i in out] == ["table_markdown"]
    sd = out[0].structured_data
    assert sd["caption"] == (
        "Appendix 1.4 (Reference: Paragraph 1.4.2.4/Page 9) "
        "Statement showing amount under PWD cheques"
    )
    assert sd["table_number"] is None  # an appendix number is not a table number
    assert out[0].content.startswith("Appendix 1.4 (Reference")


def test_sideways_appendix_caption_below(service):
    # Sideways page: the heading sorts after the table
    items = [
        _table(service, y=90),
        _item("header", "Appendix-5.2 (Refer: Paragraph-5.2.1, Page - 46)", y=350),
    ]
    out = service._attach_to_tables_and_figures(items)
    assert len(out) == 1
    assert out[0].structured_data["caption"].startswith("Appendix-5.2")


def test_caption_below_heading_the_next_table_left_alone(service):
    items = [
        _table(service, y=100, table_id="t1"),
        _item("caption", "Table 2.2: Details of grants", y=320),
        _table(service, y=350, table_id="t2"),
    ]
    out = service._attach_to_tables_and_figures(items)
    assert out[0].structured_data.get("caption") is None
    assert out[1].structured_data["caption"] == "Table 2.2: Details of grants"
