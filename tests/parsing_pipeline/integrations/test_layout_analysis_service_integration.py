import pytest
from pathlib import Path
import fitz
from PIL import Image
from ..src.modules.layout_analysis_service import LayoutAnalysisService
from ..src.modules.data_contracts import DocumentTask


@pytest.fixture
def layout_service(tmp_path):
    """LayoutAnalysisService fixture with temporary directories."""
    return LayoutAnalysisService(model_cache_dir=str(tmp_path / "models"))


@pytest.fixture
def real_pdf_path(tmp_path):
    """Create a real minimal PDF file for testing."""
    pdf_path = tmp_path / "test_real.pdf"

    # Create a simple PDF with PyMuPDF
    doc = fitz.open()
    page = doc.new_page()

    # Add some content
    page.insert_text((50, 50), "Test Report Title", fontsize=16)
    page.insert_text((50, 100), "This is a sample paragraph of text content.")
    page.insert_text((50, 120), "It contains multiple lines and different content.")

    # Save and close
    doc.save(str(pdf_path))
    doc.close()

    return pdf_path


@pytest.fixture
def document_task_with_real_pdf(real_pdf_path):
    """Create a DocumentTask with a real PDF file."""
    return DocumentTask(
        report_id="report_real_pdf_test",
        source_url="file://" + str(real_pdf_path),
        local_pdf_path=str(real_pdf_path),
        initial_metadata={"Title": "Real PDF Test Report"},
        scaffold={"pages": [0]},  # One page
    )


def test_analyze_layout_real_pdf_integration(
    layout_service, document_task_with_real_pdf
):
    """Integration test: Analyze a real PDF file end-to-end."""
    result = layout_service.analyze_layout(document_task_with_real_pdf)

    # Should complete successfully with placeholder pipeline
    assert result.processing_status == "layout_complete"
    assert isinstance(result.layout, dict)

    # Should have layout data for page 0
    assert 0 in result.layout
    assert isinstance(result.layout[0], list)

    # Should have at least one layout block
    assert len(result.layout[0]) > 0

    # Verify block structure
    for block in result.layout[0]:
        assert "bbox" in block
        assert "label" in block
        assert "confidence" in block
        assert "content_type" in block

        # bbox should be a list of 4 coordinates
        assert isinstance(block["bbox"], list)
        assert len(block["bbox"]) == 4
        assert all(isinstance(coord, float) for coord in block["bbox"])

        # confidence should be reasonable
        assert 0.0 <= block["confidence"] <= 1.0

    # Check that completion message was logged
    completion_logs = [
        msg for msg in result.error_log if "Layout analysis completed" in msg
    ]
    assert len(completion_logs) == 1
    assert "blocks detected across 1 pages" in completion_logs[0]


def test_analyze_layout_with_scaffolding_data_integration(
    layout_service, document_task_with_real_pdf
):
    """Integration test: Layout analysis with scaffolding data."""
    # Add more detailed scaffold
    document_task_with_real_pdf.scaffold = {
        "pages": [0],
        "toc": [
            {"title": "Executive Summary", "page": 0, "level": 1},
            {"title": "Introduction", "page": 0, "level": 1},
        ],
    }

    result = layout_service.analyze_layout(document_task_with_real_pdf)

    assert result.processing_status == "layout_complete"
    assert result.scaffold is not None  # Should preserve scaffold


@pytest.mark.parametrize(
    "confidence_threshold,expected_blocks",
    [
        (0.5, 1),  # Low threshold - all blocks (placeholder returns 0.85 > 0.5)
        (
            0.9,
            0,
        ),  # High threshold - blocks filtered out (placeholder returns 0.85 < 0.9)
    ],
)
def test_analyze_layout_confidence_filtering_integration(
    tmp_path, real_pdf_path, confidence_threshold, expected_blocks
):
    """Integration test: Test confidence threshold filtering."""
    service = LayoutAnalysisService(
        model_cache_dir=str(tmp_path / "models"),
        confidence_threshold=confidence_threshold,
    )

    task = DocumentTask(
        report_id="report_confidence_test",
        source_url="file://" + str(real_pdf_path),
        local_pdf_path=str(real_pdf_path),
        initial_metadata={"Title": "Confidence Test"},
        scaffold={"pages": [0]},
    )

    result = service.analyze_layout(task)

    assert result.processing_status == "layout_complete"

    # If blocks are expected, check they meet the confidence threshold
    if expected_blocks > 0:
        assert 0 in result.layout
        assert len(result.layout[0]) == expected_blocks

        # All returned blocks should meet confidence threshold
        for block in result.layout[0]:
            assert block["confidence"] >= confidence_threshold
    else:
        # For high thresholds, blocks may be filtered out
        # Just ensure processing completed successfully
        assert isinstance(result.layout, dict)


def test_multiple_pages_integration(layout_service, tmp_path):
    """Integration test: Handle multi-page PDF."""
    # Create a multi-page PDF
    pdf_path = tmp_path / "multi_page.pdf"
    doc = fitz.open()

    for page_num in range(3):
        page = doc.new_page()
        page.insert_text((50, 50), f"Page {page_num + 1} Content", fontsize=14)
        page.insert_text((50, 100), f"This is content on page {page_num + 1}.")

    doc.save(str(pdf_path))
    doc.close()

    task = DocumentTask(
        report_id="report_multi_page",
        source_url="file://" + str(pdf_path),
        local_pdf_path=str(pdf_path),
        initial_metadata={"Title": "Multi-Page Test"},
        scaffold={"pages": [0, 1, 2]},
    )

    result = layout_service.analyze_layout(task)

    assert result.processing_status == "layout_complete"
    assert len(result.layout) == 3  # All pages processed
    assert all(page_num in result.layout for page_num in [0, 1, 2])


def test_pdf_path_preference_integration(layout_service, tmp_path):
    """Integration test: Test PDF path preference logic."""
    base_pdf = tmp_path / "base.pdf"
    ocred_pdf = tmp_path / "ocred.pdf"

    # Create base PDF
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Base content")
    doc.save(str(base_pdf))
    doc.close()

    # Create OCR'd PDF (slightly different content)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "OCR'd content")
    doc.save(str(ocred_pdf))
    doc.close()

    task = DocumentTask(
        report_id="report_path_preference",
        source_url="file://" + str(base_pdf),
        local_pdf_path=str(base_pdf),
        ocred_pdf_path=str(ocred_pdf),  # Should be preferred
        initial_metadata={"Title": "Path Preference Test"},
        scaffold={"pages": [0]},
    )

    result = layout_service.analyze_layout(task)

    assert result.processing_status == "layout_complete"
    assert result.layout is not None


@pytest.mark.parametrize(
    "dpi,expected_processing",
    [
        (150, True),  # Lower DPI should work
        (600, True),  # Higher DPI should work
    ],
)
def test_different_dpi_settings_integration(
    tmp_path, real_pdf_path, dpi, expected_processing
):
    """Integration test: Different DPI settings."""
    service = LayoutAnalysisService(model_cache_dir=str(tmp_path / "models"), dpi=dpi)

    task = DocumentTask(
        report_id="report_dpi_test",
        source_url="file://" + str(real_pdf_path),
        local_pdf_path=str(real_pdf_path),
        initial_metadata={"Title": "DPI Test"},
        scaffold={"pages": [0]},
    )

    result = service.analyze_layout(task)

    if expected_processing:
        assert result.processing_status == "layout_complete"
        assert result.layout is not None
        assert len(result.layout) > 0
    else:
        assert result.processing_status == "failed_layout"


def test_layout_service_error_handling_integration(layout_service, tmp_path):
    """Integration test: Comprehensive error handling."""
    # Test with non-existent PDF
    task = DocumentTask(
        report_id="report_error_test",
        source_url="file://nonexistent.pdf",
        local_pdf_path=str(tmp_path / "nonexistent.pdf"),
        initial_metadata={"Title": "Error Test"},
        scaffold={"pages": [0]},
    )

    result = layout_service.analyze_layout(task)

    assert result.processing_status == "failed_layout"
    assert "PDF path not available" in result.error_log[0]


def test_pipeline_reuse_integration(layout_service, document_task_with_real_pdf):
    """Integration test: Pipeline reuse across multiple calls."""
    # First call
    result1 = layout_service.analyze_layout(document_task_with_real_pdf)
    assert result1.processing_status == "layout_complete"

    # Second call with different task
    task2 = DocumentTask(
        report_id="report_second_call",
        source_url="file://" + document_task_with_real_pdf.local_pdf_path,
        local_pdf_path=document_task_with_real_pdf.local_pdf_path,
        initial_metadata={"Title": "Second Call Test"},
        scaffold={"pages": [0]},
    )

    result2 = layout_service.analyze_layout(task2)
    assert result2.processing_status == "layout_complete"

    # Pipeline should be reused (lazy initialization)
    assert hasattr(layout_service, "_docling_pipeline")
    assert layout_service._docling_pipeline is not None


def test_layout_service_with_empty_scaffolding(layout_service, real_pdf_path):
    """Integration test: Handle PDF with no scaffolding data."""
    task = DocumentTask(
        report_id="report_no_scaffold",
        source_url="file://" + str(real_pdf_path),
        local_pdf_path=str(real_pdf_path),
        initial_metadata={"Title": "Empty Scaffold Test"},
        scaffold={},  # Empty scaffold
    )

    result = layout_service.analyze_layout(task)

    # Should still process successfully even with empty scaffold
    assert result.processing_status == "layout_complete"
    assert result.layout is not None


def test_placeholder_pipeline_behavior_integration(
    layout_service, document_task_with_real_pdf
):
    """Integration test: Verify placeholder pipeline produces consistent results."""
    result1 = layout_service.analyze_layout(document_task_with_real_pdf)
    assert result1.processing_status == "layout_complete"

    # Run again to verify placeholder produces same result
    task2 = DocumentTask(
        report_id="report_consistency",
        source_url=document_task_with_real_pdf.source_url,
        local_pdf_path=document_task_with_real_pdf.local_pdf_path,
        initial_metadata={"Title": "Consistency Test"},
        scaffold=document_task_with_real_pdf.scaffold,
    )

    result2 = layout_service.analyze_layout(task2)
    assert result2.processing_status == "layout_complete"

    # Results should be identical (placeholder produces deterministic output)
    assert result1.layout == result2.layout
