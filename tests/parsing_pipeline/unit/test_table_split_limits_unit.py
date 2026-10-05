"""Split table pieces stay under the size limit and keep their caption."""

from src.core.data_contracts import ExtractedContent
from src.parsing_pipeline.modules.chunking_service import ChunkingService
from src.parsing_pipeline.modules.structured_table_extractor import StructuredTableExtractor


def test_pieces_under_limit_with_caption():
    rows = "\n".join(f"| {i}. | Gram Panchayat number {i} with a long name | Block {i} | {i * 1.5:.2f} |" for i in range(1, 140))
    md = "| Sl. No. | Name of Gram Panchayat | Block | Amount |\n| --- | --- | --- | --- |\n" + rows
    table = StructuredTableExtractor().extract(md, "t1", "p001_b001", 1, [0, 0, 1, 1], caption="Table 2.1: Grants")
    item = ExtractedContent(
        content_type="table_markdown", content=md, source_page_physical=1, source_bbox=[0, 0, 1, 1],
        model_used="t", layout_label="Table", structured_data={**table.model_dump(), "unit_line": "(₹ in lakh)"},
    )
    service = ChunkingService()
    pieces = service._split_table(item)
    assert len(pieces) > 1
    limit = int(service.max_child_chars * 1.1)
    for piece in pieces:
        assert len(piece.content) <= limit
        assert piece.content.startswith("Table 2.1: Grants\n(₹ in lakh)\n| Sl. No.")
