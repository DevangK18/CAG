"""
Unit tests for ChunkFilterService: what the garbage filter keeps and drops.
"""

import logging

import pytest

from src.core.data_contracts import ExtractedContent
from src.parsing_pipeline.modules.chunk_filter_service import (
    ChunkFilterService,
    collapse_table_padding,
    protected_kind,
)

PAGE_HEIGHTS = {p: 842.0 for p in range(200)}


def _item(
    text,
    page=10,
    y=300.0,
    content_type="paragraph",
    x0=72.0,
    x1=520.0,
    height=12.0,
    **kw,
):
    return ExtractedContent(
        content_type=content_type,
        content=text,
        source_page_physical=page,
        source_bbox=[x0, y, x1, y + height],
        model_used="test",
        layout_label="Text",
        **kw,
    )


def _filter(items):
    return ChunkFilterService().filter_extracted_content(
        items, page_heights=PAGE_HEIGHTS
    )


class TestShortMeaningfulLines:
    @pytest.mark.parametrize(
        "text",
        [
            "(₹ in crore)",
            "(₹ in lakh)",
            "(Rs. in crore)",
            "(Amount in ₹)",
            "(In numbers)",
            "(Qty in million tonne)",
            "(Figures denote percentage)",
            "(Source: UDISE+ database)",
            "Source:",
            "Note: Figures are rounded",
            "Source of GSDP figures: MoSPI",
            "Figure 5: Argo Float Density",
            "Annexure I (Refer Para 4.1)",
            "Appendix 5.1",
            "Picture 6.1; dated 14-08-2023",
            "Table 3.2: Details of grants",
            "Chapter - IV Data Management",
            "CHAPTER-II",
            "PART-A",
            "Executive Summary",
            "Preface",
            "Glossary of terms",
            "Appendices",
        ],
    )
    def test_kept_however_short(self, text):
        valid, filtered = _filter([_item(text)])
        assert [v.content for v in valid] == [text] and not filtered

    @pytest.mark.parametrize(
        "text", ["Report No. 8 of 2025", "ii", "12", "Shimla Dated:"]
    )
    def test_garbage_still_dropped(self, text):
        valid, filtered = _filter([_item(text)])
        assert not valid and len(filtered) == 1

    def test_roman_banner_kept_as_header_only(self):
        assert protected_kind("IV", "header") == "chapter"
        assert protected_kind("IV", "paragraph") is None

    def test_unit_line_not_merged_into_short_run(self):
        items = [
            _item("Table 1.2: Results", y=100),
            _item("(₹ in crore)", y=115),
            _item("Sl. No.", y=130),
            _item("Particulars", y=145),
        ]
        valid, _ = _filter(items)
        assert "(₹ in crore)" in [v.content for v in valid]

    def test_split_unit_line_rejoined_in_any_order(self):
        # Docling's blocks for "(₹ in crore)", sorted by y: "(" , "in crore)", "₹"
        items = [
            _item("(", y=406, x0=496, x1=500, height=8),
            _item("in crore)", y=406, x0=505, x1=541, height=8),
            _item("₹", y=406.5, x0=500, x1=505, height=6),
        ]
        valid, filtered = _filter(items)
        assert [v.content for v in valid] == ["(₹ in crore)"] and not filtered
        assert valid[0].source_bbox == [496, 406, 541, 414]


class TestNewContentTypes:
    def test_short_footnote_kept(self):
        valid, _ = _filter([_item("1 Source: UDISE+", content_type="footnote")])
        assert len(valid) == 1

    def test_short_list_item_kept(self):
        valid, _ = _filter([_item("(a) Roads", content_type="list")])
        assert len(valid) == 1

    def test_caption_never_dropped_for_length(self):
        # model_construct: "caption" joins the content_type Literal with the label work
        item = _item("Map")
        caption = ExtractedContent.model_construct(
            **{**item.model_dump(), "content_type": "caption"}
        )
        valid, _ = _filter([caption])
        assert len(valid) == 1


class TestDuplicates:
    def test_repeated_section_headings_kept(self):
        items = []
        for page in (20, 35, 50, 70):
            items.append(
                _item("Recommendations", page=page, y=400, content_type="header")
            )
            items.append(
                _item(
                    "The Department should ensure that funds are released on time.",
                    page=page,
                    y=420,
                )
            )
        valid, filtered = _filter(items)
        assert len(valid) == 8 and not filtered

    def test_repeated_plain_heading_kept_when_not_page_furniture(self):
        items = [
            _item("Gram Panchayats", page=p, y=150 + 40 * p, content_type="header")
            for p in range(88, 96)
        ]
        valid, filtered = _filter(items)
        assert len(valid) == 8 and not filtered

    def test_running_header_dropped(self):
        title = "Audit Report (Local Government) for the year ended March 2022"
        items = [_item(title, page=p, y=30) for p in range(10, 16)]
        valid, filtered = _filter(items)
        assert not valid
        assert len(filtered) == 6

    def test_running_footer_with_page_number_dropped(self):
        items = [
            _item(f"Report No. 19 of 2023 Performance Audit {p}", page=p, y=805)
            for p in range(30, 34)
        ]
        valid, filtered = _filter(items)
        assert not valid and len(filtered) == 4

    def test_text_at_different_heights_is_not_a_running_header(self):
        title = "Audit Report (Local Government) for the year ended March 2022"
        items = [
            _item(title, page=p, y=30 + 10 * i) for i, p in enumerate(range(10, 16))
        ]
        valid, _ = _filter(items)
        assert len(valid) == 6

    def test_heading_with_body_needs_more_pages(self):
        items = []
        for page in (20, 35, 50):
            items.append(
                _item(
                    "Audit findings in Phase I", page=page, y=60, content_type="header"
                )
            )
            items.append(
                _item(
                    "The audit observed that the works were delayed by two years.",
                    page=page,
                    y=80,
                )
            )
        valid, _ = _filter(items)
        assert len(valid) == 6

    def test_running_chapter_banner_keeps_first(self):
        banner = "Chapter-I An overview of the functioning of PRIs"
        items = [_item(banner, page=p, y=30) for p in range(19, 25)]
        valid, filtered = _filter(items)
        assert [v.source_page_physical for v in valid] == [19]
        assert len(filtered) == 5

    def test_repeated_unit_line_on_every_table_page_kept(self):
        items = [_item("(₹ in lakh)", page=p, y=40) for p in range(100, 106)]
        valid, _ = _filter(items)
        assert len(valid) == 6

    def test_numbered_captions_not_grouped(self):
        items = [
            _item(f"Appendix-{n}", page=90 + n, y=40, content_type="header")
            for n in range(1, 8)
        ]
        valid, _ = _filter(items)
        assert len(valid) == 7

    def test_page_height_estimated_without_page_heights(self):
        title = "Audit Report (Local Government) for the year ended March 2022"
        items = [_item(title, page=p, y=30) for p in range(10, 16)]
        items.append(
            _item(
                "A body paragraph that reaches the bottom of the page.", page=10, y=780
            )
        )
        valid, _ = ChunkFilterService().filter_extracted_content(items)
        assert [v.content for v in valid] == [
            "A body paragraph that reaches the bottom of the page."
        ]


class TestTables:
    PADDED = (
        "| Sl. | Observation" + " " * 300 + "|\n"
        "|-----|" + "-" * 311 + "|\n"
        "| 1   | Scheduled completion date was not met and the works were delayed |\n"
        "| 2   | Short" + " " * 306 + "|"
    )

    def test_padded_docling_table_kept_and_collapsed(self):
        table = _item(self.PADDED, content_type="table_markdown")
        valid, filtered = _filter([table])
        assert len(valid) == 1 and not filtered
        assert "  " not in valid[0].content

    def test_collapse_keeps_separator_and_non_table_lines(self):
        md = "Table 1\n|  a  |  b  |\n|---|---|"
        assert collapse_table_padding(md) == "Table 1\n| a | b |\n|---|---|"

    def test_dropped_table_logged(self, caplog):
        with caplog.at_level(logging.WARNING):
            valid, filtered = _filter([_item("| a |", content_type="table_markdown")])
        assert not valid and filtered
        assert "dropped a table on page 10" in caplog.text


class TestImages:
    def _image(self, content, page=10, **data):
        return _item(
            content,
            page=page,
            content_type="image_caption",
            structured_data=data or None,
        )

    def test_dedup_uses_image_path(self):
        items = [
            self._image("", page=p, image_path=f"img/p{p}.png", visual_subtype="chart")
            for p in range(5)
        ]
        valid, _ = _filter(items)
        assert len(valid) == 5

    def test_same_file_repeated_is_duplicate(self):
        items = [self._image("Chart 1", image_path="img/a.png") for _ in range(3)]
        valid, filtered = _filter(items)
        assert len(valid) == 2 and len(filtered) == 1

    @pytest.mark.parametrize("subtype", ["chart", "map", "diagram", "table_as_image"])
    def test_uncaptioned_data_visual_kept(self, subtype):
        valid, _ = _filter(
            [self._image("", image_path="img/a.png", visual_subtype=subtype)]
        )
        assert len(valid) == 1

    @pytest.mark.parametrize("subtype", ["photo", "non_data", None])
    def test_uncaptioned_photo_dropped(self, subtype):
        item = self._image("", image_path="img/a.png", visual_subtype=subtype)
        service = ChunkFilterService()
        valid, filtered = service.filter_extracted_content([item])
        assert not valid
        assert service._validate_image(item)[1] in ("empty_image", "duplicate_content")

    def test_no_whitespace_or_garbage_rules_for_images(self):
        items = [
            self._image("12", image_path="img/a.png", visual_subtype="photo"),
            self._image("Fig  1      2      3      4      5", image_path="img/b.png"),
        ]
        valid, _ = _filter(items)
        assert len(valid) == 2

    def test_old_shape_path_in_content_kept(self):
        item = self._image("data/visuals/report/page_10_img_1.png")
        valid, _ = _filter([item])
        assert len(valid) == 1


class TestLeadInsAndBanners:
    @pytest.mark.parametrize(
        "text",
        [
            "Audit observed the following.",
            "It is recommended that:",
            "Audit noticed that:",
            "(Source",
        ],
    )
    def test_lead_in_and_source_label_kept(self, text):
        valid, _ = _filter([_item(text)])
        assert len(valid) == 1

    def test_year_banner_is_not_a_running_header(self):
        items = [
            _item("2018-19", page=p, y=75, content_type="header")
            for p in (99, 102, 128)
        ]
        valid, _ = _filter(items)
        assert len(valid) == 3


@pytest.mark.parametrize("text", ["(Zin crore)", "(% in crore)", "'Amount in @)"])
def test_ocr_garbled_unit_lines_kept(text):
    valid, _ = _filter([_item(text)])
    assert len(valid) == 1
