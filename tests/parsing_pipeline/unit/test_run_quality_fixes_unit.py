"""
Unit tests for defects found in the Sep 2026 Union run:
- Reversed-text detector flagged normal text ("tonne" matched "toN", "profit" matched "rof")
- Headline monetary total summed every amount in every finding
- manifest.json kept failed reports as "completed"
"""

import json

import pytest

from src.core.data_contracts import Finding
from src.parsing_pipeline.extractors.text_extractor import TextExtractor
from src.parsing_pipeline.modules.assembly_service import AssemblyService
from src.parsing_pipeline.modules.semantic_enrichment_service import SemanticEnrichmentService

CRORE = 1_000_000_000  # paise


def _reverse_words(text: str) -> str:
    return " ".join(word[::-1] for word in text.split(" "))


class TestReversedTextDetection:
    @pytest.fixture
    def extractor(self):
        return TextExtractor.__new__(TextExtractor)

    @pytest.mark.parametrize(
        "text",
        [
            "SAIL produced 18.73 million tonne of hot metal during 2020-21",
            "Net profit for the year stood at 5,000 crore",
            "Steel Authority of India Limited (SAIL) blast furnace production",
            "The Ministry did not reply to the audit observation",
        ],
    )
    def test_normal_text_not_flagged(self, extractor, text):
        assert not extractor._detect_reversed_content(text)

    @pytest.mark.parametrize(
        "text",
        [
            "SAIL produced 18.73 million tonne of hot metal during 2020-21",
            "The Department did not furnish the records for the period under audit",
            "Funds released to the district were not utilised by the school",
        ],
    )
    def test_reversed_text_flagged(self, extractor, text):
        assert extractor._detect_reversed_content(_reverse_words(text))

    def test_single_reversed_heading_flagged(self, extractor):
        assert extractor._detect_reversed_content("tnemtrapeD 2.3 : weivrevO lareneG")


class TestMonetaryStatistics:
    def _finding(self, idx, amounts, page=10):
        values = [{"raw_text": f"{a} crore", "normalized_inr": a * CRORE} for a in amounts]
        return Finding(
            finding_id=f"r_finding_{idx:03d}",
            report_id="r",
            text="text",
            summary="text",
            finding_type="other",
            severity="low",
            monetary_values=values,
            total_amount_inr=sum(a * CRORE for a in amounts),
            monetary_value=max(amounts) * CRORE,
            monetary_value_crore=float(max(amounts)),
            page=page,
        )

    def test_total_uses_largest_distinct_amount_per_finding(self):
        service = SemanticEnrichmentService.__new__(SemanticEnrichmentService)
        service._current_report_type = None
        findings = [
            self._finding(1, [500, 120], page=10),
            self._finding(2, [500, 40], page=60),  # same headline figure repeated later
            self._finding(3, [7], page=90),
        ]
        stats = service._calculate_statistics({}, findings, [], [])
        # 500 counted once + 7; the old sum was 500+120+500+40+7 = 1167
        assert stats["findings"]["total_monetary_crore"] == 507.0


class TestManifestFailures:
    def test_failed_report_not_listed_as_completed(self, tmp_path):
        out = tmp_path / "processed"
        out.mkdir()
        (out / "manifest.json").write_text(json.dumps({
            "corpus_version": "1.0",
            "reports": [
                {"report_id": "old", "status": "completed", "parent_chunks": 407,
                 "child_chunks": 1902, "output_file": "old_chunks.json"},
                {"report_id": "ok", "status": "completed", "parent_chunks": 10,
                 "child_chunks": 50, "output_file": "ok_chunks.json"},
            ],
        }))
        service = AssemblyService(output_dir=str(out))
        service.mark_failed("old", "layout_analysis", "Docling conversion timed out")
        service.mark_failed("new", "triage", "bad pdf")

        manifest = json.loads((out / "manifest.json").read_text())
        entries = {r["report_id"]: r for r in manifest["reports"]}
        assert entries["old"]["status"] == "failed"
        assert entries["old"]["stale_output"] is True
        assert entries["new"]["status"] == "failed"
        assert entries["new"]["stale_output"] is False
        assert manifest["completed_reports"] == 1
        assert manifest["total_parent_chunks"] == 10


# ==================== Second audit: A-M ====================

from src.core.data_contracts import DocumentTask, ExtractedContent
from src.core.table_contracts import (
    CellDataType, CellSemanticType, ColumnType, StructuredTable, TableCell, TableColumn, TableRow,
)
from src.parsing_pipeline.extractors.pdfplumber_table_extractor import PdfplumberTableExtractor
from src.parsing_pipeline.extractors.text_repair import repair_font_shift
from src.parsing_pipeline.modules.chunking_service import ChunkingService
from src.parsing_pipeline.modules.hierarchy_enricher import should_enrich_hierarchy
from src.parsing_pipeline.modules.toc_reconciliation_service import TOCReconciliationService


def _table(table_id, page, rows, header=("Sl. No.", "Minor head", "Savings")):
    def row(idx, values, row_type):
        cells = [
            TableCell(row_idx=idx, col_idx=i, raw_text=v, cleaned_text=v,
                      data_type=CellDataType.TEXT, semantic_type=CellSemanticType.DATA)
            for i, v in enumerate(values)
        ]
        return TableRow(row_idx=idx, cells=cells, row_type=row_type)

    table_rows = [row(0, header, "header")] + [row(i + 1, r, "data") for i, r in enumerate(rows)]
    columns = [
        TableColumn(col_idx=i, header_text=h, column_type=ColumnType.OTHER,
                    dominant_data_type=CellDataType.TEXT)
        for i, h in enumerate(header)
    ]
    table = StructuredTable(
        table_id=table_id, source_chunk_id="x", source_page_physical=page,
        source_bbox=[50, 100, 500, 700], columns=columns, rows=table_rows,
        num_rows=len(table_rows), num_cols=len(header), num_header_rows=1,
        markdown_representation="",
    )
    return ExtractedContent(
        content_type="table_markdown", content=f"| table {table_id} |", source_page_physical=page,
        source_bbox=[50, 100, 500, 700], model_used="pdfplumber", layout_label="Table",
        structured_data=table.model_dump(),
    )


def _text(content_type, text, page, y=50):
    return ExtractedContent(
        content_type=content_type, content=text, source_page_physical=page,
        source_bbox=[50, y, 500, y + 20], model_used="pymupdf", layout_label="Text",
    )


def _task(content):
    return DocumentTask(
        report_id="r", source_url="x", local_pdf_path="r.pdf", initial_metadata={}, extracted_content=content
    )


class TestFontShiftRepair:
    def test_shifted_line_decoded(self):
        assert repair_font_shift("5HSRUW RI WKH &RPSWUROOHU DQG $XGLWRU *HQHUDO") == (
            "Report of the Comptroller and Auditor General"
        )

    def test_table_row_left_alone(self):
        row = "| AP & TS |  |  | 56 |  | 21 | 1 | 25 |"
        assert repair_font_shift(row) == row


class TestTableExtraction:
    def test_empty_columns_and_rows_dropped(self):
        raw = [[None, "Sl.", "", "Head", None], [None, None, None, None, None], ["", "1", "", "3601", ""]]
        assert PdfplumberTableExtractor._drop_empty_lines(raw) == [["Sl.", "Head"], ["1", "3601"]]

    def test_split_words_and_years_stitched(self):
        vocab = {"activity", "type", "of", "non", "filer"}
        rows = [["Activity Typ", "e of Non-", "Filer"], [None, "20", "17-18 20", "18-19"]]
        assert PdfplumberTableExtractor._stitch_split_cells(rows, vocab) == [
            ["Activity Type", "of Non-", "Filer"], [None, None, "2017-18", "2018-19"],
        ]

    def test_profit_header_does_not_reverse_table(self):
        extractor = PdfplumberTableExtractor.__new__(PdfplumberTableExtractor)
        raw = [["Year", "Turnover", "Profit Before Tax"], ["2017-18", "58,297", "(-)759"]]
        assert extractor._clean_raw_table(raw)[1] == ["2017-18", "58,297", "(-)759"]


class TestMultiPageTables:
    def test_annexure_heading_between_tables_blocks_merge(self):
        service = ChunkingService()
        content = [
            _table("t1", 10, [("1", "Head A", "5")]),
            _text("paragraph", "Annexure 4.4 {Refer to paragraph 4.2.2.1}", 11, y=40),
            _table("t2", 11, [("1", "Head B", "7")]),
        ]
        task = _task(content)
        service._merge_multi_page_tables(task)
        assert sum(c.content_type == "table_markdown" for c in task.extracted_content) == 2

    def test_continuation_merges_and_rows_keep_their_page(self):
        service = ChunkingService()
        task = _task([
            _table("t1", 10, [("1", "Head A", "5")]),
            _table("t2", 11, [("2", "Head B", "7")]),
        ])
        service._merge_multi_page_tables(task)
        tables = [c for c in task.extracted_content if c.content_type == "table_markdown"]
        assert len(tables) == 1
        rows = tables[0].structured_data["rows"]
        assert [r["source_page_physical"] for r in rows if r["row_type"] == "data"] == [10, 11]

    def test_unrelated_table_on_merged_page_kept(self):
        service = ChunkingService()
        task = _task([
            _table("t1", 10, [("1", "Head A", "5")]),
            _table("t2", 11, [("2", "Head B", "7")]),
            _text("header", "Table 2.3: Other data", 11, y=400),
            _table("t3", 11, [("x", "y", "z")], header=("State", "Count", "Share")),
        ])
        task.extracted_content[3].source_bbox = [50, 450, 500, 700]
        service._merge_multi_page_tables(task)
        assert sum(c.content_type == "table_markdown" for c in task.extracted_content) == 2

    def test_statistics_reset_between_reports(self):
        service = ChunkingService()
        for _ in range(2):
            task = _task([_table("t1", 10, [("1", "A", "5")]), _table("t2", 11, [("2", "B", "7")])])
            service._merge_multi_page_tables(task)
        assert service.multi_page_handler.get_statistics()["tables_merged"] == 1


class TestOversizedChunks:
    def test_long_table_split_with_header_and_pages(self):
        service = ChunkingService()
        service.max_child_chars = 400
        rows = [(str(i), f"Minor head description number {i}", "1,234.56") for i in range(40)]
        item = _table("big", 20, rows)
        table = StructuredTable(**item.structured_data)
        for i, row in enumerate(table.rows[1:]):
            row.source_page_physical = 20 + i // 20
        item.structured_data = table.model_dump()

        pieces = service._split_oversized_content([item.model_copy(update={"content": "x" * 5000})])
        assert len(pieces) > 1
        assert all(len(p.content) <= 400 for p in pieces)
        assert all(p.content.startswith("| Sl. No. | Minor head | Savings |") for p in pieces)
        assert pieces[-1].source_page_physical == 21

    def test_long_paragraph_split_at_sentences(self):
        service = ChunkingService()
        service.max_child_chars = 100
        text = " ".join(f"Sentence number {i} ends here." for i in range(20))
        pieces = service._split_oversized_content([_text("paragraph", text, 3)])
        assert len(pieces) > 1
        assert all(p.content.endswith(".") for p in pieces)


class TestTocNormalization:
    def test_sections_demoted_and_junk_dropped(self):
        service = TOCReconciliationService()
        toc = [
            [1, "Report of the Comptroller and Auditor General", 0],
            [1, "Union Government Department of Revenue", 1],
            [1, "Contents", 4],
            [1, "Chapter I: Direct Taxes Administration", 14],
            [1, "1.3 Resources of the Union Government", 16],
            [1, "&KDSWHU $ZDUGRI3URMHFWV", 30],
        ]
        result = service._normalize_toc(toc)
        titles = [t for _, t, _ in result]
        assert "Contents" not in titles
        assert "Union Government Department of Revenue" not in titles
        assert [1, "Chapter AwardofProjects", 30] in result  # font-shifted title decoded
        assert [2, "1.3 Resources of the Union Government", 16] in result

    def test_supplement_level_from_numbering_and_context(self):
        service = TOCReconciliationService()
        toc = [[1, "Chapter I Introduction", 5], [2, "1.1 Background", 6]]
        assert service._supplement_level({"title": "1.1.2 Scope", "page": 6}, toc) == 3
        assert service._supplement_level({"title": "Milestone payment= 8 per cent", "page": 6}, toc) == 3


class TestHierarchyTrigger:
    def test_oversized_parent_triggers_enrichment(self):
        parents = [{"chunk_id": f"p{i}"} for i in range(20)]
        children = [{"parent_chunk_id": "p0", "hierarchy": {"level_1": "a", "level_2": "b"}} for _ in range(90)]
        children += [{"parent_chunk_id": f"p{i % 19 + 1}", "hierarchy": {"level_1": "a", "level_2": "b"}} for i in range(200)]
        assert should_enrich_hierarchy(parents, children) == (True, "oversized_parent")


class TestLateFixes:
    def test_tables_with_same_header_are_not_duplicates(self):
        from src.parsing_pipeline.modules.chunk_filter_service import ChunkFilterService

        header = "| Sl. No. | Minor/Sub-head | Sanctioned | Actual | Savings |\n| --- | --- | --- | --- | --- |\n"
        pages = [
            _text("table_markdown", header + f"| {i} | 3601.07.{i} - Scheme {i} | 1,{i}00.00 | 900.00 | 4{i}.00 |", i)
            for i in range(5)
        ]
        valid, filtered = ChunkFilterService().filter_extracted_content(pages)
        assert len(valid) == 5 and not filtered

    def test_cid_glyphs_decoded(self):
        from src.parsing_pipeline.extractors.text_repair import decode_cid_shift, has_cid_shift

        text = "(cid:54)(cid:17)(cid:49)(cid:82)(cid:17)(cid:3)(cid:38)(cid:82)(cid:80)(cid:83)(cid:82)(cid:81)(cid:72)(cid:81)(cid:87)(cid:86)(cid:3)(cid:82)(cid:73)"
        assert has_cid_shift(text)
        assert decode_cid_shift(text) == "S.No. Components of"

    def test_letter_spaced_text_rejoined(self):
        from src.parsing_pipeline.extractors.text_repair import (
            build_vocabulary, is_letter_spaced, respace_letter_spaced,
        )

        vocab = build_vocabulary("monitoring and evaluation help organizations to extract relevant " * 3)
        spaced = "M o nit ori n g a n d e v al uati o n hel p or ga nizati o ns"
        assert is_letter_spaced(spaced)
        assert respace_letter_spaced(spaced, vocab) == "Monitoring and evaluation help organizations"
        assert not is_letter_spaced("a) Violation of EC norms in Mine-I")

    def test_case_header_labels_kept_as_one_block(self):
        from src.parsing_pipeline.modules.chunk_filter_service import ChunkFilterService

        labels = ["Case I CIT Charge:", "Pr. CIT-6, Mumbai", "Assessee Name:", "M/s G5 Ltd.",
                  "Assessment Year:", "2017-18"]
        blocks = [_text("paragraph", t, 40, y=100 + 15 * i) for i, t in enumerate(labels)]
        blocks.append(_text("paragraph", "ii", 41))
        valid, _ = ChunkFilterService().filter_extracted_content(blocks)
        assert [v.content for v in valid] == [
            "Case I CIT Charge: Pr. CIT-6, Mumbai Assessee Name: M/s G5 Ltd. Assessment Year: 2017-18"
        ]

    def test_repeated_sentences_kept(self):
        from src.parsing_pipeline.modules.chunk_filter_service import ChunkFilterService

        reply = "Reply of the Ministry is awaited (April 2024)."
        valid, _ = ChunkFilterService().filter_extracted_content(
            [_text("paragraph", reply, page) for page in range(5)]
        )
        assert len(valid) == 5
