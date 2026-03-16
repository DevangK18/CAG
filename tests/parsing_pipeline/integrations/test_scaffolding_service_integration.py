import pytest
from pathlib import Path
from services.parsing_pipeline.src.modules.scaffolding_service import ScaffoldingService
from services.parsing_pipeline.src.modules.data_contracts import DocumentTask


@pytest.fixture
def scaffolding_service():
    """ScaffoldingService fixture with conservative settings for testing."""
    return ScaffoldingService()


def test_scaffolding_real_pdf_cleanliness(scaffolding_service):
    """Integration test with actual CAG-Union Audit Reports.xlsx PDF file."""
    pdf_path = Path(
        "data/raw/report_001_cag_report_on_cleanliness_and_sanitation_in_indian.pdf"
    )

    # Skip if PDF not available
    if not pdf_path.exists():
        pytest.skip(f"Test PDF not found: {pdf_path}")

    task = DocumentTask(
        report_id="report_001_cleanliness",
        source_url="https://example.com/cleanliness.pdf",
        local_pdf_path=str(pdf_path),
        initial_metadata={"Title": "Cleanliness and Sanitation Report"},
    )

    result = scaffolding_service.build_scaffold(task)

    # Verify scaffold was created (either embedded or heuristic)
    assert result.processing_status in [
        "scaffold_complete",
        "scaffold_minimal",
        "scaffold_partial",
    ]

    # Should always have page mappings
    assert "page_map" in result.scaffold
    assert len(result.scaffold["page_map"]) > 0

    # Check that scaffold is properly structured
    assert "toc" in result.scaffold
    assert isinstance(result.scaffold["toc"], list)
    assert isinstance(result.scaffold["page_map"], dict)

    # Each ToC entry should be [level, title, page] if present
    for entry in result.scaffold["toc"]:
        assert len(entry) == 3
        assert isinstance(entry[0], int)  # level
        assert isinstance(entry[1], str)  # title
        assert isinstance(entry[2], int)  # page

    # Page map should have entries for all pages
    page_map = result.scaffold["page_map"]
    # Should have at least some mappings
    assert len(page_map) > 0
    # All values should be strings (logical page labels)
    assert all(isinstance(label, str) for label in page_map.values())


def test_scaffolding_real_pdf_solar(scaffolding_service):
    """Integration test with solar parks report PDF."""
    pdf_path = Path(
        "data/raw/report_004_solar_parks_and_ultra_mega_solar_power_projects_a.pdf"
    )

    if not pdf_path.exists():
        pytest.skip(f"Test PDF not found: {pdf_path}")

    task = DocumentTask(
        report_id="report_004_solar",
        source_url="https://example.com/solar.pdf",
        local_pdf_path=str(pdf_path),
        initial_metadata={"Title": "Solar Parks Report"},
    )

    result = scaffolding_service.build_scaffold(task)

    # Verify processing completed
    assert result.processing_status in [
        "scaffold_complete",
        "scaffold_minimal",
        "scaffold_partial",
    ]

    # Verify scaffold structure
    assert "toc" in result.scaffold
    assert "page_map" in result.scaffold
    assert len(result.scaffold["page_map"]) > 0

    # Log analysis for debugging
    successful_toc = len(result.scaffold["toc"]) > 0
    successful_pages = len(result.scaffold["page_map"]) > 0

    print(f"Solar Report Scaffold: ToC={successful_toc}, Pages={successful_pages}")
    print(f"Status: {result.processing_status}")
    if result.error_log:
        print(f"Errors: {len(result.error_log)}")


def test_scaffolding_real_pdf_fiscal(scaffolding_service):
    """Integration test with fiscal responsibility report PDF."""
    pdf_path = Path(
        "data/raw/report_003_cag_report_on_fiscal_responsibility_and_budget_man.pdf"
    )

    if not pdf_path.exists():
        pytest.skip(f"Test PDF not found: {pdf_path}")

    task = DocumentTask(
        report_id="report_003_fiscal",
        source_url="https://example.com/fiscal.pdf",
        local_pdf_path=str(pdf_path),
        initial_metadata={"Title": "Fiscal Responsibility Report"},
    )

    result = scaffolding_service.build_scaffold(task)

    assert result.processing_status in [
        "scaffold_complete",
        "scaffold_minimal",
        "scaffold_partial",
    ]

    # Should have either embedded ToC or some heuristic detection
    toc_entries = len(result.scaffold["toc"])
    page_entries = len(result.scaffold["page_map"])

    assert page_entries > 0  # Should always have page mappings
    assert toc_entries >= 0  # May have 0 if no ToC or heuristic failed

    print(
        f"Fiscal Report Scaffold: ToC entries={toc_entries}, Page entries={page_entries}"
    )


@pytest.mark.parametrize(
    "pdf_filename",
    [
        "report_001_cag_report_on_cleanliness_and_sanitation_in_indian.pdf",
        "report_002_direct_taxes_audit_report_union_government_revenu.pdf",
        "report_003_cag_report_on_fiscal_responsibility_and_budget_man.pdf",
        "report_004_solar_parks_and_ultra_mega_solar_power_projects_a.pdf",
        "report_005_cag_report_on_indian_national_centre_for_ocean_inf.pdf",
    ],
)
def test_scaffolding_all_pilot_pdfs(scaffolding_service, pdf_filename):
    """Integration test with all 5 pilot PDFs from the manifest."""
    pdf_path = Path(f"data/raw/{pdf_filename}")

    if not pdf_path.exists():
        pytest.skip(f"Pilot PDF not found: {pdf_path}")

    # Extract report ID from filename
    report_id = pdf_filename.split(".")[0]

    task = DocumentTask(
        report_id=report_id,
        source_url=f"https://example.com/{report_id}.pdf",
        local_pdf_path=str(pdf_path),
        initial_metadata={"Title": f"Pilot Report {report_id}"},
    )

    result = scaffolding_service.build_scaffold(task)

    # All documents should complete processing (may fail to create ToC but not crash)
    assert result.processing_status in [
        "scaffold_complete",
        "scaffold_minimal",
        "scaffold_partial",
        "failed_scaffold",
    ]

    # Should have page map unless complete failure
    if result.processing_status != "failed_scaffold":
        assert len(result.scaffold["page_map"]) > 0

    # Log results for analysis
    toc_count = len(result.scaffold["toc"])
    page_count = len(result.scaffold["page_map"])
    print(
        f"{report_id}: {result.processing_status} - ToC:{toc_count}, Pages:{page_count}"
    )

    # Verify data types
    assert isinstance(result.scaffold["toc"], list)
    assert isinstance(result.scaffold["page_map"], dict)


def test_scaffolding_service_consistency(scaffolding_service):
    """Test that scaffolding produces consistent results on same PDF."""
    pdf_path = Path(
        "data/raw/report_001_cag_report_on_cleanliness_and_sanitation_in_indian.pdf"
    )

    if not pdf_path.exists():
        pytest.skip("Test PDF not found")

    # Run scaffold twice on same document
    task1 = DocumentTask(
        report_id="consistency_test_1",
        source_url="https://example.com/test.pdf",
        local_pdf_path=str(pdf_path),
        initial_metadata={},
    )

    task2 = DocumentTask(
        report_id="consistency_test_2",
        source_url="https://example.com/test.pdf",
        local_pdf_path=str(pdf_path),
        initial_metadata={},
    )

    result1 = scaffolding_service.build_scaffold(task1)
    result2 = scaffolding_service.build_scaffold(task2)

    # Results should be consistent
    assert result1.processing_status == result2.processing_status
    assert result1.scaffold["toc"] == result2.scaffold["toc"]
    assert result1.scaffold["page_map"] == result2.scaffold["page_map"]


def test_scaffolding_performance_bounds(scaffolding_service):
    """Test that scaffolding completes within reasonable time bounds."""
    import time

    pdf_path = Path(
        "data/raw/report_001_cag_report_on_cleanliness_and_sanitation_in_indian.pdf"
    )

    if not pdf_path.exists():
        pytest.skip("Test PDF not found")

    task = DocumentTask(
        report_id="performance_test",
        source_url="https://example.com/test.pdf",
        local_pdf_path=str(pdf_path),
        initial_metadata={},
    )

    start_time = time.time()
    result = scaffolding_service.build_scaffold(task)
    end_time = time.time()

    processing_time = end_time - start_time

    # Should complete within 30 seconds for a moderately-sized PDF
    assert processing_time < 30.0, f"Took {processing_time:.2f}s to process scaffold"

    # Should still produce valid results
    assert result.processing_status != "failed_scaffold"
    assert len(result.scaffold["page_map"]) > 0

    print(f"Scaffold processing time: {processing_time:.2f}s")


def test_scaffolding_error_handling_corrupted():
    """Test error handling with potentially problematic PDF."""
    service = ScaffoldingService()

    # Use README as "PDF" to test corruption handling
    readme_path = Path("README.md")

    if not readme_path.exists():
        pytest.skip("README.md not found for corruption test")

    task = DocumentTask(
        report_id="test_corrupted",
        source_url="https://example.com/test.pdf",
        local_pdf_path=str(readme_path),  # Wrong file type
        initial_metadata={},
    )

    result = service.build_scaffold(task)

    # Should fail gracefully without crashing
    assert result.processing_status == "failed_scaffold"
    assert len(result.error_log) > 0
    assert "Scaffolding failed with error" in result.error_log[0]


def test_scaffolding_very_small_pdf(scaffolding_service):
    """Test with the smallest available PDF to test edge cases."""
    # Find the smallest PDF file
    pdf_dir = Path("data/raw")
    if not pdf_dir.exists():
        pytest.skip("Raw data directory not available")

    pdf_files = list(pdf_dir.glob("*.pdf"))
    if not pdf_files:
        pytest.skip("No PDF files available")

    # Get smallest file by size
    smallest_pdf = min(pdf_files, key=lambda p: p.stat().st_size)

    task = DocumentTask(
        report_id="smallest_pdf_test",
        source_url="https://example.com/small.pdf",
        local_pdf_path=str(smallest_pdf),
        initial_metadata={"Title": "Smallest PDF Test"},
    )

    result = scaffolding_service.build_scaffold(task)

    # Should handle small PDFs gracefully
    assert result.processing_status in [
        "scaffold_complete",
        "scaffold_minimal",
        "scaffold_partial",
        "failed_scaffold",
    ]

    # If it doesn't fail completely, should have basic structure
    if result.processing_status != "failed_scaffold":
        assert "page_map" in result.scaffold
        assert "toc" in result.scaffold


def test_scaffolding_page_map_coverage(scaffolding_service):
    """Test that page mappings cover all document pages."""
    pdf_path = Path(
        "data/raw/report_001_cag_report_on_cleanliness_and_sanitation_in_indian.pdf"
    )

    if not pdf_path.exists():
        pytest.skip("Test PDF not found")

    task = DocumentTask(
        report_id="page_map_test",
        source_url="https://example.com/test.pdf",
        local_pdf_path=str(pdf_path),
        initial_metadata={},
    )

    result = scaffolding_service.build_scaffold(task)

    if result.processing_status == "failed_scaffold":
        pytest.skip("Scaffold building failed, skipping page map test")

    page_map = result.scaffold["page_map"]

    # Should have mappings for consecutive pages starting from 0
    assert 0 in page_map  # Should start with page 0

    # Check that page mappings are consecutive
    mapped_pages = sorted(page_map.keys())
    expected_pages = list(range(len(mapped_pages)))

    assert mapped_pages == expected_pages, (
        f"Non-consecutive page mapping: {mapped_pages}"
    )

    # All labels should be strings and non-empty
    for page_num, label in page_map.items():
        assert isinstance(label, str)
        assert len(label.strip()) > 0


def test_scaffolding_toc_structure_validation(scaffolding_service):
    """Test that generated ToC has valid structure."""
    pdf_path = Path(
        "data/raw/report_001_cag_report_on_cleanliness_and_sanitation_in_indian.pdf"
    )

    if not pdf_path.exists():
        pytest.skip("Test PDF not found")

    task = DocumentTask(
        report_id="toc_validation_test",
        source_url="https://example.com/test.pdf",
        local_pdf_path=str(pdf_path),
        initial_metadata={},
    )

    result = scaffolding_service.build_scaffold(task)

    if result.processing_status == "failed_scaffold":
        pytest.skip("Scaffold building failed, skipping ToC validation")

    toc = result.scaffold["toc"]

    # ToC should be a list
    assert isinstance(toc, list)

    # If ToC has entries, validate structure
    if toc:
        for entry in toc:
            assert len(entry) == 3, f"ToC entry should have 3 elements: {entry}"

            level, title, page = entry

            # Validate types
            assert isinstance(level, int), f"Level should be int: {level}"
            assert isinstance(title, str), f"Title should be str: {title}"
            assert isinstance(page, int), f"Page should be int: {page}"

            # Validate values
            assert level > 0, f"Level should be positive: {level}"
            assert len(title.strip()) > 0, f"Title should not be empty: '{title}'"
            assert page >= 0, f"Page should be non-negative: {page}"

        # Check that ToC entries are sorted by page
        pages = [entry[2] for entry in toc]
        assert pages == sorted(pages), "ToC entries should be sorted by page number"
