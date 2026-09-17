"""
P2-18: Unit tests for blank-page extraction pre-check.

Layout-detected Table blocks on blank pages (<50 chars) should be skipped
to avoid wasted extraction calls.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from src.parsing_pipeline.modules.content_extraction_service import ContentExtractionService


@pytest.fixture
def service():
    """Create a ContentExtractionService instance."""
    with patch("src.parsing_pipeline.modules.content_extraction_service.PdfplumberTableExtractor"):
        with patch("src.parsing_pipeline.modules.content_extraction_service.TextExtractor"):
            svc = ContentExtractionService()
            return svc


class TestBlankPagePrecheckP218:
    """P2-18: Verify blank page pre-check skips table extraction."""

    def test_blank_page_table_skipped(self, service):
        """P2-18: Table on page with 30 chars should be skipped."""
        # Mock page text length to return 30 chars
        service._get_page_text_length = Mock(return_value=30)

        block = {"label": "Table", "bbox": [0, 0, 100, 100], "confidence": 0.9}

        result = service._route_block(
            block=block,
            pdf_path="/fake/path.pdf",
            page_num=5,
            report_id="test_report",
            is_scanned=False,
        )

        assert result is None
        service._get_page_text_length.assert_called_once_with("/fake/path.pdf", 5)

    def test_normal_page_table_extracted(self, service):
        """P2-18: Table on page with 500 chars should be extracted."""
        # Mock page text length to return 500 chars
        service._get_page_text_length = Mock(return_value=500)

        # Mock table extractor to return a result
        mock_content = Mock()
        mock_content.content_type = "table_markdown"
        service.table_extractor.extract = Mock(return_value=mock_content)

        block = {"label": "Table", "bbox": [0, 0, 100, 100], "confidence": 0.9}

        result = service._route_block(
            block=block,
            pdf_path="/fake/path.pdf",
            page_num=5,
            report_id="test_report",
            is_scanned=False,
        )

        assert result is not None
        service.table_extractor.extract.assert_called_once()

    def test_non_table_block_not_checked(self, service):
        """P2-18: Picture/Figure blocks should not trigger blank page check."""
        service._get_page_text_length = Mock(return_value=30)

        # Mock the router entry for Picture to return a result
        mock_content = Mock()
        mock_content.content_type = "image_caption"
        mock_extractor = Mock(return_value=mock_content)
        service.router["Picture"] = mock_extractor

        block = {"label": "Picture", "bbox": [0, 0, 100, 100], "confidence": 0.9}

        result = service._route_block(
            block=block,
            pdf_path="/fake/path.pdf",
            page_num=5,
            report_id="test_report",
            is_scanned=False,
        )

        # Should not call _get_page_text_length for Picture
        service._get_page_text_length.assert_not_called()
        # Should still extract the Picture via router
        mock_extractor.assert_called_once()

    def test_threshold_boundary_50_chars(self, service):
        """P2-18: Page with exactly 50 chars should be extracted (threshold is <50)."""
        service._get_page_text_length = Mock(return_value=50)

        mock_content = Mock()
        service.table_extractor.extract = Mock(return_value=mock_content)

        block = {"label": "Table", "bbox": [0, 0, 100, 100], "confidence": 0.9}

        result = service._route_block(
            block=block,
            pdf_path="/fake/path.pdf",
            page_num=5,
            report_id="test_report",
            is_scanned=False,
        )

        # Should extract (50 is NOT < 50)
        assert result is not None
        service.table_extractor.extract.assert_called_once()

    def test_threshold_boundary_49_chars(self, service):
        """P2-18: Page with 49 chars should be skipped."""
        service._get_page_text_length = Mock(return_value=49)

        block = {"label": "Table", "bbox": [0, 0, 100, 100], "confidence": 0.9}

        result = service._route_block(
            block=block,
            pdf_path="/fake/path.pdf",
            page_num=5,
            report_id="test_report",
            is_scanned=False,
        )

        # Should skip (49 < 50)
        assert result is None

    def test_multiple_tables_same_blank_page_cached(self, service):
        """P2-18: Multiple tables on same blank page should only check once."""
        # Use a real implementation that we can track
        call_count = [0]

        def mock_get_length(pdf_path, page_num):
            call_count[0] += 1
            # First call populates cache, subsequent calls should use cache
            if pdf_path not in service._page_text_cache:
                service._page_text_cache[pdf_path] = {}
            service._page_text_cache[pdf_path][page_num] = 30
            return 30

        service._get_page_text_length = mock_get_length

        block1 = {"label": "Table", "bbox": [0, 0, 100, 100], "confidence": 0.9}
        block2 = {"label": "Table", "bbox": [0, 100, 100, 200], "confidence": 0.9}

        # First table on page 5
        result1 = service._route_block(
            block=block1,
            pdf_path="/fake/path.pdf",
            page_num=5,
            report_id="test_report",
            is_scanned=False,
        )

        # Reset the mock function to use cache
        service._page_text_cache["/fake/path.pdf"] = {5: 30}
        service._get_page_text_length = lambda p, n: service._page_text_cache.get(p, {}).get(n, 9999)

        # Second table on same page - should use cache
        result2 = service._route_block(
            block=block2,
            pdf_path="/fake/path.pdf",
            page_num=5,
            report_id="test_report",
            is_scanned=False,
        )

        # Both should be skipped
        assert result1 is None
        assert result2 is None
        # Original mock was called only once
        assert call_count[0] == 1

    def test_scanned_vs_native_behavior(self, service):
        """P2-18: Only native PDFs should trigger blank page check.

        Scanned PDFs have 0 native text even when Docling detects tables,
        so blank page check should NOT apply to them.
        """
        service._get_page_text_length = Mock(return_value=30)

        block = {"label": "Table", "bbox": [0, 0, 100, 100], "confidence": 0.9}

        # Native PDF - should be skipped on blank page
        result_native = service._route_block(
            block=block,
            pdf_path="/fake/native.pdf",
            page_num=5,
            report_id="test_report",
            is_scanned=False,
        )

        # Scanned PDF - should NOT be skipped (proceeds to Docling/Gemini extraction)
        # Need to mock the extraction path since we're not actually extracting
        with patch.object(service, '_extract_and_save_visual') as mock_extract:
            mock_extract.return_value = None  # Simulates Gemini fallback path
            result_scanned = service._route_block(
                block=block,
                pdf_path="/fake/scanned.pdf",
                page_num=5,
                report_id="test_report",
                is_scanned=True,
            )

        # Native PDF should be skipped on blank page
        assert result_native is None
        # Scanned PDF should NOT check page text length - it proceeds to extraction
        assert service._get_page_text_length.call_count == 1  # Only called for native

    def test_trace_emitted_on_skip(self, service):
        """P2-18: Trace should be emitted when skipping blank page."""
        service._get_page_text_length = Mock(return_value=30)

        mock_emitter = Mock()

        block = {"label": "Table", "bbox": [0, 0, 100, 100], "confidence": 0.9}

        result = service._route_block(
            block=block,
            pdf_path="/fake/path.pdf",
            page_num=5,
            report_id="test_report",
            is_scanned=False,
            trace_emitter=mock_emitter,
        )

        assert result is None
        mock_emitter.emit_decision.assert_called_once_with(
            "6",
            "blank_page_skip",
            "skipped",
            ["extract", "skipped"],
            "Page 5 has 30 chars < 50",
        )


class TestGetPageTextLengthP218:
    """P2-18: Test the _get_page_text_length caching method."""

    def test_caches_results(self, service):
        """P2-18: Page text length should be cached per PDF."""
        with patch("fitz.open") as mock_fitz:
            mock_doc = MagicMock()
            mock_page = MagicMock()
            mock_page.get_text.return_value = "  Hello world!  "
            mock_doc.load_page.return_value = mock_page
            mock_doc.__len__ = Mock(return_value=10)
            mock_fitz.return_value = mock_doc

            # First call
            length1 = service._get_page_text_length("/fake/path.pdf", 3)

            # Second call should use cache
            length2 = service._get_page_text_length("/fake/path.pdf", 3)

            assert length1 == 12  # "Hello world!" stripped
            assert length2 == 12
            # fitz.open should only be called once
            assert mock_fitz.call_count == 1

    def test_handles_page_out_of_range(self, service):
        """P2-18: Returns 0 for page numbers beyond document length."""
        with patch("fitz.open") as mock_fitz:
            mock_doc = MagicMock()
            mock_doc.__len__ = Mock(return_value=5)
            mock_fitz.return_value = mock_doc

            length = service._get_page_text_length("/fake/path.pdf", 10)

            assert length == 0

    def test_handles_exception_gracefully(self, service):
        """P2-18: Returns high value on error to avoid false positives."""
        with patch("fitz.open") as mock_fitz:
            mock_fitz.side_effect = Exception("PDF error")

            length = service._get_page_text_length("/fake/path.pdf", 3)

            # Should return high value to avoid false skip
            assert length == 9999
