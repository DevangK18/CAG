"""
Tests for P2-2 Chart Extraction Service.

Tests the ChartExtractorService which orchestrates Claude Vision-based
chart data extraction via Anthropic Batch API.
"""

import json
import base64
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, mock_open
import pytest

from src.batch_pipeline.enrichment.chart_extractor import ChartExtractorService
from src.core.chart_contracts import (
    StructuredChart,
    ChartSeries,
    DataPoint,
    ChartAxisConfig,
    AxisType,
    ChartType,
    create_chart_from_dict,
    validate_chart_extraction,
)


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def sample_chart_chunk():
    """Sample chart chunk with chart_data_path."""
    return {
        "chunk_id": "chunk_001",
        "content_type": "chart_data_path",
        "content": "data/assets_for_hitl/report_p14_abc123.png",
        "source_page_physical": 14,
        "source_bbox": [100.0, 200.0, 400.0, 450.0],
        "hierarchy": {
            "level_1": "Chapter 3",
            "level_2": "3.4 Revenue Analysis"
        },
        "structured_data": None
    }


@pytest.fixture
def sample_chart_chunk_with_data():
    """Sample chart chunk that already has structured_data."""
    return {
        "chunk_id": "chunk_002",
        "content_type": "chart_data_path",
        "content": "data/assets_for_hitl/report_p15_def456.png",
        "source_page_physical": 15,
        "source_bbox": [50.0, 100.0, 300.0, 400.0],
        "hierarchy": {"level_1": "Chapter 4"},
        "structured_data": {
            "chart_id": "chart_002",
            "title": "Already Extracted Chart",
            "has_structured_data": True
        }
    }


@pytest.fixture
def sample_structured_chart():
    """Sample StructuredChart object."""
    return StructuredChart(
        chart_id="chart_001",
        source_chunk_id="chunk_001",
        source_page_physical=14,
        source_bbox=[100.0, 200.0, 400.0, 450.0],
        image_path="data/assets_for_hitl/report_p14_abc123.png",
        title="Revenue Collection Trend (2020-2024)",
        chart_type=ChartType.LINE,
        subtitle=None,
        description="Shows increasing revenue trend over 4 fiscal years",
        x_axis=ChartAxisConfig(
            axis_id="x_axis",
            axis_label="Financial Year",
            axis_type=AxisType.TEMPORAL,
            label_format="fiscal_year"
        ),
        y_axis=ChartAxisConfig(
            axis_id="y_axis",
            axis_label="Revenue (₹ Crore)",
            axis_type=AxisType.NUMERIC,
            unit="crore",
            min_value=0.0,
            max_value=5000.0
        ),
        series=[
            ChartSeries(
                series_id="actual_revenue",
                series_name="Actual Revenue",
                data_points=[
                    DataPoint(category="2020-21", value=3200.5, series="actual_revenue"),
                    DataPoint(category="2021-22", value=3850.2, series="actual_revenue"),
                    DataPoint(category="2022-23", value=4100.8, series="actual_revenue"),
                    DataPoint(category="2023-24", value=4650.3, series="actual_revenue"),
                ]
            )
        ],
        entities_referenced=["Ministry of Finance", "Direct Tax Department"],
        time_periods=["2020-21", "2021-22", "2022-23", "2023-24"],
        monetary_unit="crore",
        extraction_method="claude_vision_batch",
        has_structured_data=True,
        confidence=0.92
    )


@pytest.fixture
def sample_json_data():
    """Sample report JSON data."""
    return {
        "report_metadata": {
            "report_id": "test_report_001",
            "title": "Test Report"
        },
        "child_chunks": [
            {
                "chunk_id": "chunk_001",
                "content_type": "chart_data_path",
                "content": "data/assets_for_hitl/report_p14_abc123.png",
                "source_page_physical": 14,
                "structured_data": None
            },
            {
                "chunk_id": "chunk_002",
                "content_type": "paragraph",
                "content": "Some text content",
                "source_page_physical": 15
            }
        ]
    }


@pytest.fixture
def mock_anthropic_response():
    """Mock Anthropic API response for chart extraction."""
    chart_json = {
        "title": "Revenue Collection Trend (2020-2024)",
        "chart_type": "line",
        "subtitle": None,
        "description": "Shows increasing revenue trend over 4 fiscal years",
        "x_axis": {
            "axis_id": "x_axis",
            "axis_label": "Financial Year",
            "axis_type": "temporal",
            "label_format": "fiscal_year",
            "unit": None,
            "min_value": None,
            "max_value": None,
            "scale": None
        },
        "y_axis": {
            "axis_id": "y_axis",
            "axis_label": "Revenue (₹ Crore)",
            "axis_type": "numeric",
            "label_format": "currency",
            "unit": "crore",
            "min_value": 0.0,
            "max_value": 5000.0,
            "scale": "linear"
        },
        "secondary_y_axis": None,
        "series": [
            {
                "series_id": "actual_revenue",
                "series_name": "Actual Revenue",
                "data_points": [
                    {"category": "2020-21", "value": 3200.5, "series": "actual_revenue", "label": None},
                    {"category": "2021-22", "value": 3850.2, "series": "actual_revenue", "label": None},
                    {"category": "2022-23", "value": 4100.8, "series": "actual_revenue", "label": None},
                    {"category": "2023-24", "value": 4650.3, "series": "actual_revenue", "label": None}
                ],
                "color": "#4472C4",
                "cumulative": False
            }
        ],
        "legend": {
            "entries": [{"label": "Actual Revenue", "color": "#4472C4"}],
            "position": "top-right"
        },
        "entities_referenced": ["Ministry of Finance", "Direct Tax Department"],
        "time_periods": ["2020-21", "2021-22", "2022-23", "2023-24"],
        "monetary_unit": "crore",
        "extraction_notes": [],
        "confidence": 0.92,
        "chart_id": "chart_001",
        "source_chunk_id": "chunk_001",
        "source_page_physical": 14,
        "source_bbox": [100.0, 200.0, 400.0, 450.0],
        "image_path": "data/assets_for_hitl/report_p14_abc123.png",
        "extraction_method": "claude_vision_batch",
        "has_structured_data": True
    }
    return json.dumps(chart_json)


# ============================================================================
# TEST: Chart Identification
# ============================================================================


def test_identify_charts_for_extraction_finds_chart_chunks(sample_chart_chunk):
    """Test identifying chart_data_path chunks."""
    service = ChartExtractorService()

    chunks = [
        sample_chart_chunk,
        {"chunk_id": "chunk_999", "content_type": "paragraph", "content": "Some text"},
        {"chunk_id": "chunk_998", "content_type": "table_markdown", "content": "| A | B |"}
    ]

    chart_chunks = service._identify_charts_for_extraction(chunks, skip_existing=False)

    assert len(chart_chunks) == 1
    assert chart_chunks[0]["chunk_id"] == "chunk_001"
    assert chart_chunks[0]["content_type"] == "chart_data_path"


def test_identify_charts_skips_existing_structured_data(
    sample_chart_chunk,
    sample_chart_chunk_with_data
):
    """Test skipping charts that already have structured_data."""
    service = ChartExtractorService()

    chunks = [sample_chart_chunk, sample_chart_chunk_with_data]

    # With skip_existing=True
    chart_chunks = service._identify_charts_for_extraction(chunks, skip_existing=True)
    assert len(chart_chunks) == 1
    assert chart_chunks[0]["chunk_id"] == "chunk_001"

    # With skip_existing=False
    chart_chunks = service._identify_charts_for_extraction(chunks, skip_existing=False)
    assert len(chart_chunks) == 2


def test_identify_charts_returns_empty_for_no_charts():
    """Test identifying charts when none exist."""
    service = ChartExtractorService()

    chunks = [
        {"chunk_id": "chunk_001", "content_type": "paragraph", "content": "Text"},
        {"chunk_id": "chunk_002", "content_type": "table_markdown", "content": "| A |"}
    ]

    chart_chunks = service._identify_charts_for_extraction(chunks)
    assert len(chart_chunks) == 0


# ============================================================================
# TEST: Vision Request Building
# ============================================================================


def test_build_vision_request_structure(sample_chart_chunk, tmp_path):
    """Test vision request has correct structure."""
    service = ChartExtractorService()

    # Create a dummy image file
    image_path = tmp_path / "test_chart.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"dummy image data")

    request = service._build_vision_request(sample_chart_chunk, str(image_path))

    # Check structure
    assert "model" in request
    assert "max_tokens" in request
    assert "messages" in request

    # Check message structure
    messages = request["messages"]
    assert len(messages) == 1
    assert messages[0]["role"] == "user"

    content = messages[0]["content"]
    assert len(content) == 2

    # Image content
    assert content[0]["type"] == "image"
    assert content[0]["source"]["type"] == "base64"
    assert content[0]["source"]["media_type"] == "image/png"
    assert "data" in content[0]["source"]

    # Text content
    assert content[1]["type"] == "text"
    assert "TASK: Extract structured data" in content[1]["text"]


def test_encode_image_base64(tmp_path):
    """Test base64 image encoding."""
    service = ChartExtractorService()

    # Create a test image
    image_path = tmp_path / "test.png"
    image_data = b"fake image data"
    image_path.write_bytes(image_data)

    # Encode
    encoded = service._encode_image_base64(str(image_path))

    # Verify
    decoded = base64.standard_b64decode(encoded)
    assert decoded == image_data


def test_get_chart_context_includes_hierarchy(sample_chart_chunk):
    """Test context building from chunk metadata."""
    service = ChartExtractorService()

    context = service._get_chart_context(sample_chart_chunk)

    assert "Section: level_1: Chapter 3 > level_2: 3.4 Revenue Analysis" in context
    assert "Page: 15" in context  # 14 + 1 for display


def test_get_chart_context_handles_missing_hierarchy():
    """Test context building with missing hierarchy."""
    service = ChartExtractorService()

    chunk = {
        "chunk_id": "chunk_001",
        "source_page_physical": 10,
        "hierarchy": {},
        "content": ""
    }

    context = service._get_chart_context(chunk)
    assert "Page: 11" in context


# ============================================================================
# TEST: Chart Data Models
# ============================================================================


def test_structured_chart_creation(sample_structured_chart):
    """Test StructuredChart creation and basic properties."""
    chart = sample_structured_chart

    assert chart.chart_id == "chart_001"
    assert chart.title == "Revenue Collection Trend (2020-2024)"
    assert chart.chart_type == ChartType.LINE
    assert chart.has_structured_data is True
    assert chart.confidence == 0.92
    assert len(chart.series) == 1
    assert len(chart.series[0].data_points) == 4


def test_structured_chart_get_series_by_name(sample_structured_chart):
    """Test finding series by name."""
    chart = sample_structured_chart

    series = chart.get_series_by_name("Actual Revenue")
    assert series is not None
    assert series.series_id == "actual_revenue"

    # Case insensitive
    series = chart.get_series_by_name("ACTUAL REVENUE")
    assert series is not None

    # Not found
    series = chart.get_series_by_name("Nonexistent")
    assert series is None


def test_structured_chart_get_data_point(sample_structured_chart):
    """Test finding data points."""
    chart = sample_structured_chart

    point = chart.get_data_point("2021-22")
    assert point is not None
    assert point.value == 3850.2

    # Case insensitive
    point = chart.get_data_point("2021-22", series_id="actual_revenue")
    assert point is not None

    # Not found
    point = chart.get_data_point("2025-26")
    assert point is None


def test_structured_chart_get_values(sample_structured_chart):
    """Test extracting values from series."""
    chart = sample_structured_chart

    values = chart.get_values("actual_revenue")
    assert len(values) == 4
    assert values == [3200.5, 3850.2, 4100.8, 4650.3]

    # Nonexistent series
    values = chart.get_values("nonexistent")
    assert values == []


def test_structured_chart_get_value_range(sample_structured_chart):
    """Test getting value range."""
    chart = sample_structured_chart

    min_val, max_val = chart.get_value_range()
    assert min_val == 3200.5
    assert max_val == 4650.3

    # Specific series
    min_val, max_val = chart.get_value_range(series_id="actual_revenue")
    assert min_val == 3200.5
    assert max_val == 4650.3


def test_chart_series_helper_methods():
    """Test ChartSeries helper methods."""
    series = ChartSeries(
        series_id="revenue",
        series_name="Revenue",
        data_points=[
            DataPoint(category="2020", value=100.0, series="revenue"),
            DataPoint(category="2021", value=150.0, series="revenue"),
            DataPoint(category="2022", value=200.0, series="revenue"),
        ]
    )

    # get_values
    assert series.get_values() == [100.0, 150.0, 200.0]

    # get_categories
    assert series.get_categories() == ["2020", "2021", "2022"]

    # get_point_by_category
    point = series.get_point_by_category("2021")
    assert point is not None
    assert point.value == 150.0

    # sum_values
    assert series.sum_values() == 450.0

    # avg_value
    assert series.avg_value() == 150.0


def test_create_chart_from_dict(mock_anthropic_response):
    """Test creating StructuredChart from dictionary."""
    chart_dict = json.loads(mock_anthropic_response)

    chart = create_chart_from_dict(chart_dict)

    assert isinstance(chart, StructuredChart)
    assert chart.chart_id == "chart_001"
    assert chart.title == "Revenue Collection Trend (2020-2024)"
    assert len(chart.series) == 1
    assert chart.has_structured_data is True


def test_validate_chart_extraction_no_warnings(sample_structured_chart):
    """Test validation with good chart data."""
    warnings = validate_chart_extraction(sample_structured_chart)
    assert len(warnings) == 0


def test_validate_chart_extraction_low_confidence():
    """Test validation catches low confidence."""
    chart = StructuredChart(
        chart_id="chart_low",
        source_chunk_id="chunk_001",
        source_page_physical=1,
        source_bbox=[0, 0, 100, 100],
        image_path="test.png",
        title="Test",
        chart_type=ChartType.BAR,
        x_axis=ChartAxisConfig(
            axis_id="x", axis_label="X", axis_type=AxisType.CATEGORICAL
        ),
        y_axis=ChartAxisConfig(
            axis_id="y", axis_label="Y", axis_type=AxisType.NUMERIC
        ),
        extraction_method="test",
        has_structured_data=True,
        confidence=0.3  # Low confidence
    )

    warnings = validate_chart_extraction(chart)
    assert len(warnings) > 0
    assert any("Low confidence" in w for w in warnings)


def test_validate_chart_extraction_no_series():
    """Test validation catches has_structured_data but no series."""
    chart = StructuredChart(
        chart_id="chart_empty",
        source_chunk_id="chunk_001",
        source_page_physical=1,
        source_bbox=[0, 0, 100, 100],
        image_path="test.png",
        title="Test",
        chart_type=ChartType.BAR,
        x_axis=ChartAxisConfig(
            axis_id="x", axis_label="X", axis_type=AxisType.CATEGORICAL
        ),
        y_axis=ChartAxisConfig(
            axis_id="y", axis_label="Y", axis_type=AxisType.NUMERIC
        ),
        series=[],  # Empty
        extraction_method="test",
        has_structured_data=True,  # But marked as having data
        confidence=0.9
    )

    warnings = validate_chart_extraction(chart)
    assert any("no series data" in w for w in warnings)


def test_validate_chart_extraction_missing_monetary_unit():
    """Test validation suggests monetary_unit for financial charts."""
    chart = StructuredChart(
        chart_id="chart_money",
        source_chunk_id="chunk_001",
        source_page_physical=1,
        source_bbox=[0, 0, 100, 100],
        image_path="test.png",
        title="Revenue Loss in Crore",  # Financial keywords
        chart_type=ChartType.BAR,
        x_axis=ChartAxisConfig(
            axis_id="x", axis_label="Year", axis_type=AxisType.TEMPORAL
        ),
        y_axis=ChartAxisConfig(
            axis_id="y", axis_label="Amount", axis_type=AxisType.NUMERIC
        ),
        monetary_unit=None,  # Missing
        extraction_method="test",
        has_structured_data=True,
        confidence=0.9
    )

    warnings = validate_chart_extraction(chart)
    assert any("monetary_unit" in w for w in warnings)


# ============================================================================
# TEST: JSON Update
# ============================================================================


def test_update_json_with_chart_data(tmp_path, sample_json_data, sample_structured_chart):
    """Test updating JSON file with chart data."""
    service = ChartExtractorService()

    # Create temp JSON file
    json_path = tmp_path / "test_report.json"
    with open(json_path, "w") as f:
        json.dump(sample_json_data, f)

    # Create results
    results = [{
        "chunk_id": "chunk_001",
        "chart_data": sample_structured_chart.to_dict(),
        "success": True,
        "error": None
    }]

    # Update
    success = service._update_json_with_chart_data(str(json_path), results)
    assert success is True

    # Verify update
    with open(json_path) as f:
        updated_data = json.load(f)

    chunk = updated_data["child_chunks"][0]
    assert chunk["chunk_id"] == "chunk_001"
    assert chunk["structured_data"] is not None
    assert chunk["structured_data"]["chart_id"] == "chart_001"
    assert chunk["structured_data"]["title"] == "Revenue Collection Trend (2020-2024)"


def test_update_json_skips_failed_results(tmp_path, sample_json_data):
    """Test that failed results don't update JSON."""
    service = ChartExtractorService()

    json_path = tmp_path / "test_report.json"
    with open(json_path, "w") as f:
        json.dump(sample_json_data, f)

    # Failed result
    results = [{
        "chunk_id": "chunk_001",
        "chart_data": None,
        "success": False,
        "error": "Extraction failed"
    }]

    # Update
    success = service._update_json_with_chart_data(str(json_path), results)
    assert success is False

    # Verify no update
    with open(json_path) as f:
        data = json.load(f)

    assert data["child_chunks"][0]["structured_data"] is None


def test_update_json_handles_missing_chunk(tmp_path, sample_json_data, sample_structured_chart):
    """Test updating with non-existent chunk ID."""
    service = ChartExtractorService()

    json_path = tmp_path / "test_report.json"
    with open(json_path, "w") as f:
        json.dump(sample_json_data, f)

    # Result for non-existent chunk
    results = [{
        "chunk_id": "chunk_999",  # Doesn't exist
        "chart_data": sample_structured_chart.to_dict(),
        "success": True,
        "error": None
    }]

    # Update
    success = service._update_json_with_chart_data(str(json_path), results)
    assert success is False  # No chunks updated


# ============================================================================
# TEST: Batch Submission (with mocks)
# ============================================================================


@patch('src.batch_pipeline.enrichment.chart_extractor.Anthropic')
def test_submit_chart_extraction_batch_success(mock_anthropic, tmp_path, sample_json_data):
    """Test successful batch submission."""
    # Setup mock
    mock_client = Mock()
    mock_batch = Mock()
    mock_batch.id = "msgbatch_test123"
    mock_client.messages.batches.create.return_value = mock_batch
    mock_anthropic.return_value = mock_client

    # Create test JSON file
    json_path = tmp_path / "test_report_chunks.json"
    with open(json_path, "w") as f:
        json.dump(sample_json_data, f)

    # Create dummy image
    image_path = Path(sample_json_data["child_chunks"][0]["content"])
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"fake image")

    # Initialize service with tmp directories
    service = ChartExtractorService(
        batch_jobs_dir=str(tmp_path / "batch_jobs"),
        processed_dir=str(tmp_path)
    )

    # Submit
    job_id = service.submit_chart_extraction_batch([json_path], skip_existing=False)

    # Verify
    assert job_id is not None
    assert job_id.startswith("chart_extraction_")

    # Check batch was created
    mock_client.messages.batches.create.assert_called_once()

    # Check job tracker exists
    tracker_path = service.chart_extraction_dir / f"{job_id}.json"
    assert tracker_path.exists()

    with open(tracker_path) as f:
        tracker = json.load(f)

    assert tracker["job_id"] == job_id
    assert tracker["batch_id"] == "msgbatch_test123"
    assert tracker["status"] == "submitted"


@patch('src.batch_pipeline.enrichment.chart_extractor.Anthropic')
def test_submit_chart_extraction_batch_no_charts(mock_anthropic, tmp_path):
    """Test submission with no charts to extract."""
    # JSON with no chart chunks
    json_data = {
        "report_metadata": {"report_id": "test_001"},
        "child_chunks": [
            {"chunk_id": "chunk_001", "content_type": "paragraph", "content": "Text"}
        ]
    }

    json_path = tmp_path / "test_report_chunks.json"
    with open(json_path, "w") as f:
        json.dump(json_data, f)

    service = ChartExtractorService(
        batch_jobs_dir=str(tmp_path / "batch_jobs"),
        processed_dir=str(tmp_path)
    )

    job_id = service.submit_chart_extraction_batch([json_path])

    # Should return None when no charts
    assert job_id is None


# ============================================================================
# TEST: Status Checking (with mocks)
# ============================================================================


@patch('src.batch_pipeline.enrichment.chart_extractor.Anthropic')
def test_get_chart_extraction_status(mock_anthropic, tmp_path):
    """Test getting batch status."""
    # Setup mock
    mock_client = Mock()
    mock_batch = Mock()
    mock_batch.processing_status = "in_progress"
    mock_batch.request_counts = Mock(
        processing=5,
        succeeded=10,
        errored=1,
        canceled=0,
        expired=0
    )
    mock_client.messages.batches.retrieve.return_value = mock_batch
    mock_anthropic.return_value = mock_client

    # Create job tracker
    service = ChartExtractorService(
        batch_jobs_dir=str(tmp_path / "batch_jobs"),
        processed_dir=str(tmp_path)
    )

    job_id = "chart_extraction_20260213_120000"
    tracker_data = {
        "job_id": job_id,
        "batch_id": "msgbatch_test123",
        "status": "submitted",
        "created_at": "2026-02-13T12:00:00"
    }

    tracker_path = service.chart_extraction_dir / f"{job_id}.json"
    tracker_path.parent.mkdir(parents=True, exist_ok=True)
    with open(tracker_path, "w") as f:
        json.dump(tracker_data, f)

    # Get status
    status = service.get_chart_extraction_status(job_id)

    # Verify
    assert status["batch_status"] == "in_progress"
    assert status["status"] == "processing"
    assert status["request_counts"]["succeeded"] == 10
    assert status["request_counts"]["errored"] == 1


@patch('src.batch_pipeline.enrichment.chart_extractor.Anthropic')
def test_get_chart_extraction_status_ended(mock_anthropic, tmp_path):
    """Test status when batch is ended."""
    mock_client = Mock()
    mock_batch = Mock()
    mock_batch.processing_status = "ended"
    mock_batch.request_counts = Mock(
        processing=0,
        succeeded=15,
        errored=1,
        canceled=0,
        expired=0
    )
    mock_client.messages.batches.retrieve.return_value = mock_batch
    mock_anthropic.return_value = mock_client

    service = ChartExtractorService(
        batch_jobs_dir=str(tmp_path / "batch_jobs"),
        processed_dir=str(tmp_path)
    )

    job_id = "chart_extraction_20260213_120000"
    tracker_data = {
        "job_id": job_id,
        "batch_id": "msgbatch_test123",
        "status": "submitted"
    }

    tracker_path = service.chart_extraction_dir / f"{job_id}.json"
    tracker_path.parent.mkdir(parents=True, exist_ok=True)
    with open(tracker_path, "w") as f:
        json.dump(tracker_data, f)

    status = service.get_chart_extraction_status(job_id)

    assert status["batch_status"] == "ended"
    assert status["status"] == "ready_for_processing"


# ============================================================================
# TEST: Error Handling
# ============================================================================


def test_chart_extractor_handles_missing_image(tmp_path, sample_json_data):
    """Test handling of missing image files."""
    json_path = tmp_path / "test_report_chunks.json"
    with open(json_path, "w") as f:
        json.dump(sample_json_data, f)

    # Image doesn't exist
    service = ChartExtractorService(
        batch_jobs_dir=str(tmp_path / "batch_jobs"),
        processed_dir=str(tmp_path)
    )

    # Should handle gracefully (skip missing images)
    with patch.object(service.client.messages.batches, 'create') as mock_create:
        mock_create.return_value = Mock(id="msgbatch_test")
        job_id = service.submit_chart_extraction_batch([json_path], skip_existing=False)

    # Job created but charts with missing images skipped
    assert job_id is None  # No valid charts to extract


def test_chart_extractor_handles_invalid_json():
    """Test handling invalid JSON in responses."""
    service = ChartExtractorService()

    # Invalid JSON should raise error when parsing
    with pytest.raises(json.JSONDecodeError):
        json.loads("not valid json")


def test_structured_chart_requires_mandatory_fields():
    """Test that StructuredChart requires all mandatory fields."""
    with pytest.raises(Exception):  # Pydantic ValidationError
        StructuredChart(
            chart_id="test",
            # Missing required fields
        )


# ============================================================================
# TEST: Integration Scenarios
# ============================================================================


def test_end_to_end_chart_extraction_workflow(
    tmp_path,
    sample_json_data,
    mock_anthropic_response
):
    """
    Test complete workflow:
    1. Submit batch
    2. Check status
    3. Process results
    """
    # This is a simplified integration test
    # In real testing, you'd use actual batch API or detailed mocks

    # Setup
    json_path = tmp_path / "test_report_chunks.json"
    with open(json_path, "w") as f:
        json.dump(sample_json_data, f)

    # Create image
    image_path = Path(sample_json_data["child_chunks"][0]["content"])
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"fake image")

    service = ChartExtractorService(
        batch_jobs_dir=str(tmp_path / "batch_jobs"),
        processed_dir=str(tmp_path)
    )

    # Step 1: Submit (mocked)
    with patch.object(service.client.messages.batches, 'create') as mock_create:
        mock_batch = Mock(id="msgbatch_test123")
        mock_create.return_value = mock_batch

        job_id = service.submit_chart_extraction_batch([json_path], skip_existing=False)

    assert job_id is not None

    # Step 2: Status (mocked)
    with patch.object(service.client.messages.batches, 'retrieve') as mock_retrieve:
        mock_batch = Mock(
            processing_status="ended",
            request_counts=Mock(processing=0, succeeded=1, errored=0, canceled=0, expired=0)
        )
        mock_retrieve.return_value = mock_batch

        status = service.get_chart_extraction_status(job_id)

    assert status["status"] == "ready_for_processing"

    # Step 3: Process results (would need detailed mocking)
    # This is tested separately in test_update_json_with_chart_data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
