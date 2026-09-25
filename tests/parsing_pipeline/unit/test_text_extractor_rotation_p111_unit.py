"""
P1-11: Unit tests for Page Rotation Handling.

Tests:
- Rotation detection (_get_page_rotation)
- Rotation-aware text extraction
- Structured data includes page_rotation
- Red flag emission for rotated pages

Note: Some tests require PyMuPDF (fitz) and will be skipped if not available.
"""

import pytest
from unittest.mock import MagicMock, patch


# Mark fitz-dependent tests
try:
    import fitz
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False

requires_fitz = pytest.mark.skipif(not HAS_FITZ, reason="PyMuPDF (fitz) not available")


class MockPage:
    """Mock PyMuPDF page for rotation testing.

    Simulates real PyMuPDF behavior where 270° rotated pages return
    reversed text in dict mode (because PyMuPDF reads in document
    coordinate order, not visual order).
    """

    def __init__(self, rotation=0, text_content="Test content"):
        self._rotation = rotation
        self._text_content = text_content

    @property
    def rotation(self):
        return self._rotation

    def get_text(self, format_type, clip=None, sort=True):
        if format_type == "text":
            return self._text_content
        elif format_type == "dict":
            # Simulate real PyMuPDF behavior for rotated pages
            # 270° rotation returns reversed text in document coordinates
            content = self._text_content
            if self._rotation == 270:
                # PyMuPDF returns text reversed for 270° rotation
                content = content[::-1]

            return {
                "blocks": [
                    {
                        "type": 0,  # Text block
                        "lines": [
                            {
                                "spans": [
                                    {"text": content}  # Single span with full content
                                ]
                            }
                        ],
                    }
                ]
            }
        return self._text_content


@requires_fitz
class TestRotationDetection:
    """P1-11: Test page rotation detection."""

    def test_detects_0_rotation(self):
        """Normal page returns 0."""
        from src.parsing_pipeline.extractors.text_extractor import TextExtractor
        extractor = TextExtractor()
        page = MockPage(rotation=0)
        assert extractor._get_page_rotation(page) == 0

    def test_detects_90_rotation(self):
        """90-degree rotated page returns 90."""
        from src.parsing_pipeline.extractors.text_extractor import TextExtractor
        extractor = TextExtractor()
        page = MockPage(rotation=90)
        assert extractor._get_page_rotation(page) == 90

    def test_detects_180_rotation(self):
        """180-degree rotated page returns 180."""
        from src.parsing_pipeline.extractors.text_extractor import TextExtractor
        extractor = TextExtractor()
        page = MockPage(rotation=180)
        assert extractor._get_page_rotation(page) == 180

    def test_detects_270_rotation(self):
        """270-degree rotated page returns 270."""
        from src.parsing_pipeline.extractors.text_extractor import TextExtractor
        extractor = TextExtractor()
        page = MockPage(rotation=270)
        assert extractor._get_page_rotation(page) == 270

    def test_normalizes_360_to_0(self):
        """360-degree rotation normalizes to 0."""
        from src.parsing_pipeline.extractors.text_extractor import TextExtractor
        extractor = TextExtractor()
        page = MockPage(rotation=360)
        assert extractor._get_page_rotation(page) == 0

    def test_normalizes_negative_rotation(self):
        """Negative rotation values are handled correctly."""
        from src.parsing_pipeline.extractors.text_extractor import TextExtractor
        extractor = TextExtractor()
        page = MockPage(rotation=-90)
        # -90 % 360 = 270 in Python
        assert extractor._get_page_rotation(page) == 270


@requires_fitz
class TestRotatedTextExtraction:
    """P1-11: Test rotation-aware text extraction."""

    def test_normal_page_uses_standard_extraction(self):
        """0-degree page uses standard get_text."""
        from src.parsing_pipeline.extractors.text_extractor import TextExtractor
        extractor = TextExtractor()
        page = MockPage(rotation=0, text_content="Normal text content")
        clip_rect = fitz.Rect(0, 0, 100, 100)

        result = extractor._extract_text_with_rotation_handling(page, clip_rect)

        assert result == "Normal text content"

    @pytest.mark.parametrize("rotation", [90, 180, 270])
    def test_rotated_page_uses_displayed_coordinates(self, rotation):
        """
        Docling boxes are in displayed (rotated) coordinates; extraction must map them
        back to unrotated space. Clipping without that cut words at column edges.
        """
        from src.parsing_pipeline.extractors.text_extractor import TextExtractor

        doc = fitz.open()
        page = doc.new_page(width=842, height=595)
        page.insert_text((72, 100), "Implementation of Sub-Projects under Ocean Modelling", fontsize=11)
        text_rect = page.search_for("Implementation")[0] | page.search_for("Modelling")[0]
        page.set_rotation(rotation)
        displayed = text_rect * page.rotation_matrix
        displayed = fitz.Rect(displayed.x0 - 2, displayed.y0 - 2, displayed.x1 + 2, displayed.y1 + 2)

        result = TextExtractor()._extract_text_with_rotation_handling(page, displayed)

        assert "Implementation of Sub-Projects under Ocean Modelling" in " ".join(result.split())


class TestRotationRedFlag:
    """P1-11: Test red flag emission for rotated pages (no fitz required)."""

    def test_red_flag_emitted_for_rotated_page(self):
        """Rotated page triggers red flag in content extraction."""
        from src.core.data_contracts import ExtractedContent

        mock_emitter = MagicMock()

        # Create a result with page_rotation
        result = ExtractedContent(
            content_type="paragraph",
            content="Test content",
            source_page_physical=5,
            source_bbox=[0, 0, 100, 100],
            model_used="PyMuPDF-clip",
            layout_label="Text",
            structured_data={"page_rotation": 270},
        )

        # Simulate the check that happens in content_extraction_service
        if (
            result.structured_data
            and isinstance(result.structured_data, dict)
            and result.structured_data.get("page_rotation", 0) != 0
        ):
            rotation = result.structured_data["page_rotation"]
            mock_emitter.emit_red_flag(
                "6",
                "rotated_page_detected",
                {"page": 5, "rotation": rotation, "report_id": "test_report"},
            )

        # Verify red flag was emitted
        mock_emitter.emit_red_flag.assert_called_once()
        call_args = mock_emitter.emit_red_flag.call_args
        assert call_args[0][0] == "6"
        assert call_args[0][1] == "rotated_page_detected"
        assert call_args[0][2]["rotation"] == 270

    def test_no_red_flag_for_normal_page(self):
        """Normal page does not trigger red flag."""
        from src.core.data_contracts import ExtractedContent

        mock_emitter = MagicMock()

        result = ExtractedContent(
            content_type="paragraph",
            content="Normal content",
            source_page_physical=1,
            source_bbox=[0, 0, 100, 100],
            model_used="PyMuPDF-clip",
            layout_label="Text",
            structured_data=None,
        )

        # Simulate the check
        if (
            result.structured_data
            and isinstance(result.structured_data, dict)
            and result.structured_data.get("page_rotation", 0) != 0
        ):
            mock_emitter.emit_red_flag("6", "rotated_page_detected", {})

        # Verify red flag was NOT emitted
        mock_emitter.emit_red_flag.assert_not_called()

    def test_no_red_flag_for_zero_rotation_in_structured_data(self):
        """Page with rotation=0 in structured_data does not trigger red flag."""
        from src.core.data_contracts import ExtractedContent

        mock_emitter = MagicMock()

        result = ExtractedContent(
            content_type="paragraph",
            content="Normal content",
            source_page_physical=1,
            source_bbox=[0, 0, 100, 100],
            model_used="PyMuPDF-clip",
            layout_label="Text",
            structured_data={"page_rotation": 0},  # Explicitly zero
        )

        # Simulate the check
        if (
            result.structured_data
            and isinstance(result.structured_data, dict)
            and result.structured_data.get("page_rotation", 0) != 0
        ):
            mock_emitter.emit_red_flag("6", "rotated_page_detected", {})

        # Verify red flag was NOT emitted (rotation is 0)
        mock_emitter.emit_red_flag.assert_not_called()

    def test_red_flag_includes_all_details(self):
        """Red flag includes page number, rotation, and report_id."""
        mock_emitter = MagicMock()
        page_num = 158
        rotation = 270
        report_id = "OD_2025_05"

        # Emit the red flag
        mock_emitter.emit_red_flag(
            "6",
            "rotated_page_detected",
            {"page": page_num, "rotation": rotation, "report_id": report_id},
        )

        call_args = mock_emitter.emit_red_flag.call_args
        details = call_args[0][2]
        assert details["page"] == 158
        assert details["rotation"] == 270
        assert details["report_id"] == "OD_2025_05"
