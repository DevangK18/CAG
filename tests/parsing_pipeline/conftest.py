import pytest
import pandas as pd
import tempfile
import sys
from pathlib import Path

# Add project root to sys.path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.core.data_contracts import DocumentTask


@pytest.fixture
def temp_dir():
    """Temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_manifest_df():
    """Sample DataFrame mimicking the expected Excel structure."""
    data = {
        "SL NO": [1.0, 2.0, 3.0],
        "Date": ["2025-08-20", "2025-08-18", "2025-08-12"],
        "Title": [
            "Original Report 1",
            "Original Report 2",
            "Original Report 3",
        ],
        "Recommended Title": [
            "CAG Report 1",
            None,
            "CAG Report 3",
        ],
        "Government Type": ["Union", "Union", "Union"],
        "Union Department": ["Railways", "Civil", "Scientific"],
        "Report Type": ["Performance", "Compliance", "Performance"],
        "Sector": ["Transport", "Finance", "Science"],
        "Report PDF": [
            "https://example.com/report1.pdf",
            "https://example.com/report2.pdf",
            "https://example.com/report3.pdf",
        ],
    }
    df = pd.DataFrame(data)
    # Set Date to datetime for reality
    df["Date"] = pd.to_datetime(df["Date"])
    return df


@pytest.fixture
def mock_manifest_excel(temp_dir, sample_manifest_df):
    """Create a temporary Excel file with sample data."""
    excel_path = temp_dir / "test_manifest.xlsx"
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        sample_manifest_df.to_excel(writer, index=False, startrow=1)  # Headers at row 2
    return excel_path


@pytest.fixture
def test_raw_dir(temp_dir):
    """Test raw data directory."""
    raw_dir = temp_dir / "data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    return raw_dir


@pytest.fixture
def sample_task(tmp_path):
    """Sample DocumentTask fixture with a valid file path."""
    return DocumentTask(
        report_id="report_001_test",
        source_url="https://example.com/test.pdf",
        local_pdf_path=str(tmp_path / "test.pdf"),
        initial_metadata={"Title": "Test Report"},
    )
