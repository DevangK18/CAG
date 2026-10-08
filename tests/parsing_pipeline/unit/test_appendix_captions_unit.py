"""
Appendix captions (PR 9): "Appendix 4.3", a reference line and a title printed above
an appendix table are its caption; a caption of its own starts a new table.
"""

import pytest

from src.core.table_contracts import (
    CellDataType,
    CellSemanticType,
    ColumnType,
    StructuredTable,
    TableCell,
    TableColumn,
    TableRow,
)
from src.parsing_pipeline.modules.captions import (
    TABLE_KINDS,
    appendix_caption_above,
    is_continued_caption,
    is_reference_line,
    parse_caption,
)
from src.parsing_pipeline.modules.multi_page_table_handler import MultiPageTableHandler


class TestParseAppendixCaption:
    @pytest.mark.parametrize(
        "text,label",
        [
            (
                "Appendix 4.3 (Reference: Paragraph 4.3/Page 27) Statement showing details",
                "appendix 4.3",
            ),
            ("Appendix-4.1 Statement showing purchase of goods", "appendix 4.1"),
            ("Annexure 3.1", "annexure 3.1"),
            ("Annexure-II", "annexure II"),
            ("Annex 2", "annex 2"),
        ],
    )
    def test_appendix_is_a_table_caption_without_table_number(self, text, label):
        parsed = parse_caption(text)
        assert parsed["kind"] in TABLE_KINDS
        assert parsed["label"] == label
        # "Appendix 4.3" is not "Table 4.3"
        assert parsed["number"] is None

    def test_table_caption_keeps_its_number(self):
        parsed = parse_caption("Table 3.2: Details of grants")
        assert parsed["number"] == "3.2" and parsed["label"] == "table 3.2"

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("(Reference: Paragraph 4.3/Page 27)", True),
            ("(Refer Paragraph 2.1.1)", True),
            ("(Reference Paragraph: 4.1.3.1)", True),
            ("(₹ in crore)", False),
            (
                "Reference to the Department was made in June 2023 and the reply is awaited "
                "from the Government of the State even after repeated reminders.",
                False,
            ),
        ],
    )
    def test_reference_lines(self, text, expected):
        assert is_reference_line(text) is expected

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Appendix 4.3 (contd.)", True),
            ("Appendix 4.3 (concld.)", True),
            ("Table 2.1 (Continued)", True),
            ("Appendix 4.4", False),
        ],
    )
    def test_continued_captions(self, text, expected):
        assert is_continued_caption(text) is expected


class TestAppendixCaptionAbove:
    """Blocks above the table, nearest first (KA ATIR 2018 appendix pages)."""

    def test_caption_then_title(self):
        # p.57: "Appendix 1.2 (Reference: …)" / title header / table
        found = appendix_caption_above(
            [
                "Statement showing Inspection Reports and Paragraphs outstanding",
                "Appendix 1.2 (Reference: Paragraph 1.3.2.3/Page 3)",
            ]
        )
        assert found == (
            2,
            "Appendix 1.2 (Reference: Paragraph 1.3.2.3/Page 3) "
            "Statement showing Inspection Reports and Paragraphs outstanding",
        )

    def test_caption_reference_and_title(self):
        # p.59: "Appendix 1.4" / "(Reference: …)" / title header / table
        found = appendix_caption_above(
            [
                "Statement showing amount under 'II PWD cheques'",
                "(Reference: Paragraph 1.4.2.4/Page 9)",
                "Appendix 1.4",
            ]
        )
        assert found == (
            3,
            "Appendix 1.4 (Reference: Paragraph 1.4.2.4/Page 9) "
            "Statement showing amount under 'II PWD cheques'",
        )

    def test_reference_inside_title(self):
        # p.73: "Appendix 4.5" / "(Reference: …) Statement showing …" header / table
        found = appendix_caption_above(
            [
                "(Reference: Paragraph 4.4/Page 30) Statement showing power factor surcharge",
                "Appendix 4.5",
            ]
        )
        assert found[0] == 2
        assert found[1].startswith("Appendix 4.5 (Reference: Paragraph 4.4/Page 30)")

    @pytest.mark.parametrize(
        "texts",
        [
            # directly above: the plain caption rule attaches it
            ["Appendix 4.3 (contd.)"],
            # no appendix caption within reach
            ["Statement showing details", "1.2 Organisational set-up"],
            # two titles between: not one caption block
            ["Statement showing details", "Another heading", "Appendix 2.1"],
            # a table caption, not an appendix
            ["Details of grants", "Table 3.2"],
            # a unit line is not a title
            ["(₹ in crore)", "Appendix 2.1"],
            [],
        ],
    )
    def test_no_caption(self, texts):
        assert appendix_caption_above(texts) is None


def _table(table_id, page, caption=None, values=("1.", "Gaya", "12.50")):
    header = ["Sl. No.", "Name", "Amount"]
    rows = []
    for idx, cells in enumerate([header, list(values)]):
        rows.append(
            TableRow(
                row_idx=idx,
                row_type="header" if idx == 0 else "data",
                cells=[
                    TableCell(
                        row_idx=idx,
                        col_idx=i,
                        raw_text=v,
                        cleaned_text=v,
                        data_type=CellDataType.TEXT,
                        semantic_type=CellSemanticType.DATA,
                    )
                    for i, v in enumerate(cells)
                ],
            )
        )
    columns = [
        TableColumn(
            col_idx=i,
            header_text=h,
            column_type=ColumnType.OTHER,
            dominant_data_type=CellDataType.TEXT,
        )
        for i, h in enumerate(header)
    ]
    return StructuredTable(
        table_id=table_id,
        source_chunk_id=f"b_{table_id}",
        source_page_physical=page,
        source_bbox=[0, 0, 100, 100],
        columns=columns,
        rows=rows,
        num_rows=2,
        num_cols=3,
        num_header_rows=1,
        title=caption,
        caption=caption,
        markdown_representation="",
    )


class TestCaptionStartsNewTable:
    def _merged(self, a, b):
        handler = MultiPageTableHandler()
        return handler.detect_and_merge(
            [a, b], contiguous_pairs={(a.table_id, b.table_id)}
        )

    def test_next_appendix_on_facing_page_not_merged(self):
        a = _table(
            "t1", 59, "Appendix 1.4 (Reference: Paragraph 1.4.2.4/Page 9) Statement A"
        )
        b = _table(
            "t2", 60, "Appendix 1.5 (Reference: Paragraph 1.4.2.4/Page 10) Statement B"
        )
        assert len(self._merged(a, b)) == 2

    def test_new_table_caption_after_uncaptioned_table_not_merged(self):
        a = _table("t1", 10)
        b = _table("t2", 11, "Table 2.2: Details of grants")
        assert len(self._merged(a, b)) == 2

    @pytest.mark.parametrize(
        "first,second",
        [
            (
                "Appendix 4.3 (Reference: Paragraph 4.3/Page 27) Statement",
                "Appendix 4.3 (contd.)",
            ),
            (
                "Appendix 4.3 (Reference: Paragraph 4.3/Page 27) Statement",
                "Appendix 4.3 (concld.)",
            ),
            ("Table 2.1: Details of grants", "Table 2.1: Details of grants"),
            ("Table 2.1: Details of grants", "Table 2.1"),
            ("Table 2.1: Details of grants", None),
            (None, None),
        ],
    )
    def test_continuations_still_merge(self, first, second):
        a = _table("t1", 66, first)
        b = _table("t2", 67, second, values=("2.", "Patna", "300.75"))
        merged = self._merged(a, b)
        assert len(merged) == 1
        assert merged[0].caption == first
