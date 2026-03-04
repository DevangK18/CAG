"""
Chart Data Contracts for P2-2 Chart Data Extraction.

This module defines Pydantic models for representing structured chart data
extracted from CAG audit reports using Claude Vision via batch API.

Models follow the pattern established in table_contracts.py for consistency
with P0-1 structured table extraction.
"""

from typing import List, Dict, Optional, Literal
from pydantic import BaseModel, Field
from enum import Enum


class ChartType(str, Enum):
    """Chart type classification."""
    BAR = "bar"
    LINE = "line"
    PIE = "pie"
    SCATTER = "scatter"
    AREA = "area"
    COMBO = "combo"  # Combination charts (e.g., bar + line)
    TABLE_CHART = "table_chart"  # Tabular visualizations
    UNKNOWN = "unknown"


class AxisType(str, Enum):
    """Axis data type classification."""
    CATEGORICAL = "categorical"  # Discrete categories (states, departments)
    NUMERIC = "numeric"  # Continuous numbers
    TEMPORAL = "temporal"  # Time-based (years, dates)


class ChartAxisConfig(BaseModel):
    """Configuration for a single chart axis."""

    axis_id: str = Field(
        ...,
        description="Unique axis identifier (e.g., 'x_axis', 'y_axis', 'secondary_y')"
    )

    axis_label: str = Field(
        ...,
        description="Human-readable axis label (e.g., 'Financial Year', 'Revenue (₹ Crore)')"
    )

    axis_type: AxisType = Field(
        ...,
        description="Type of data on this axis"
    )

    label_format: Optional[str] = Field(
        default=None,
        description="Format hint for values (e.g., 'fiscal_year', 'percentage', 'currency')"
    )

    unit: Optional[str] = Field(
        default=None,
        description="Unit of measurement (e.g., 'crore', 'lakh', '%', 'count')"
    )

    min_value: Optional[float] = Field(
        default=None,
        description="Minimum value on axis (for numeric axes)"
    )

    max_value: Optional[float] = Field(
        default=None,
        description="Maximum value on axis (for numeric axes)"
    )

    scale: Optional[str] = Field(
        default=None,
        description="Scale type: 'linear', 'logarithmic', etc."
    )


class DataPoint(BaseModel):
    """A single data point in a chart series."""

    category: str = Field(
        ...,
        description="X-axis value (e.g., '2021-22', 'Maharashtra', 'Q1')"
    )

    value: float = Field(
        ...,
        description="Y-axis value (numeric)"
    )

    series: Optional[str] = Field(
        default=None,
        description="Series identifier (for multi-series charts)"
    )

    label: Optional[str] = Field(
        default=None,
        description="Optional label shown on the data point"
    )

    def __str__(self) -> str:
        series_str = f"[{self.series}] " if self.series else ""
        return f"{series_str}{self.category}: {self.value}"


class ChartSeries(BaseModel):
    """A data series in the chart (for single or multi-series charts)."""

    series_id: str = Field(
        ...,
        description="Programmatic series identifier (e.g., 'revenue', 'expenses', 'budget')"
    )

    series_name: str = Field(
        ...,
        description="Human-readable series name shown in legend"
    )

    data_points: List[DataPoint] = Field(
        default_factory=list,
        description="All data points in this series"
    )

    color: Optional[str] = Field(
        default=None,
        description="Hex color code if detected from chart"
    )

    cumulative: Optional[bool] = Field(
        default=None,
        description="True if this is a cumulative series"
    )

    def get_values(self) -> List[float]:
        """Extract all values from this series."""
        return [p.value for p in self.data_points]

    def get_categories(self) -> List[str]:
        """Extract all categories from this series."""
        return [p.category for p in self.data_points]

    def get_point_by_category(self, category: str) -> Optional[DataPoint]:
        """Find a data point by category name."""
        for point in self.data_points:
            if point.category.lower() == category.lower():
                return point
        return None

    def sum_values(self) -> float:
        """Sum all values in this series."""
        return sum(p.value for p in self.data_points)

    def avg_value(self) -> float:
        """Calculate average value in this series."""
        if not self.data_points:
            return 0.0
        return sum(p.value for p in self.data_points) / len(self.data_points)


class ChartLegend(BaseModel):
    """Chart legend information."""

    entries: List[Dict[str, str]] = Field(
        default_factory=list,
        description="Legend entries: [{'label': '...', 'color': '#...'}, ...]"
    )

    position: Optional[str] = Field(
        default=None,
        description="Legend position: 'top-right', 'bottom-left', 'top', 'right', etc."
    )


class StructuredChart(BaseModel):
    """
    Complete structured representation of a chart with extracted data.

    This model captures all metadata and data points from a chart image,
    enabling direct querying without re-parsing the image. Similar to
    StructuredTable from P0-1 but adapted for chart/graph data.
    """

    # ========== Identifiers ==========

    chart_id: str = Field(
        ...,
        description="Unique chart identifier within the report"
    )

    source_chunk_id: str = Field(
        ...,
        description="ID of the parent ChildChunk containing this chart"
    )

    # ========== Source Location ==========

    source_page_physical: int = Field(
        ...,
        description="0-indexed physical page number in PDF"
    )

    source_bbox: List[float] = Field(
        ...,
        description="Bounding box coordinates [x0, y0, x1, y1]"
    )

    image_path: str = Field(
        ...,
        description="Path to extracted chart image (e.g., data/assets_for_hitl/...png)"
    )

    # ========== Semantic Metadata ==========

    title: str = Field(
        ...,
        description="Chart title extracted from image or adjacent text"
    )

    chart_type: ChartType = Field(
        ...,
        description="Chart type classification"
    )

    subtitle: Optional[str] = Field(
        default=None,
        description="Chart subtitle if present"
    )

    description: Optional[str] = Field(
        default=None,
        description="AI-generated description of chart content and trends"
    )

    caption: Optional[str] = Field(
        default=None,
        description="Chart caption from PDF text (if available)"
    )

    # ========== Axes Configuration ==========

    x_axis: ChartAxisConfig = Field(
        ...,
        description="X-axis configuration and metadata"
    )

    y_axis: ChartAxisConfig = Field(
        ...,
        description="Primary Y-axis configuration and metadata"
    )

    secondary_y_axis: Optional[ChartAxisConfig] = Field(
        default=None,
        description="Secondary Y-axis for dual-axis charts"
    )

    # ========== Data ==========

    series: List[ChartSeries] = Field(
        default_factory=list,
        description="Chart data series (empty for HITL/manual extraction charts)"
    )

    legend: Optional[ChartLegend] = Field(
        default=None,
        description="Legend information if present"
    )

    # ========== Semantic Context ==========

    entities_referenced: List[str] = Field(
        default_factory=list,
        description="Entities mentioned: states, ministries, departments, schemes, PSUs"
    )

    time_periods: List[str] = Field(
        default_factory=list,
        description="Time periods covered: years, fiscal years, quarters (e.g., ['2021-22', '2022-23'])"
    )

    monetary_unit: Optional[str] = Field(
        default=None,
        description="Monetary unit if chart shows financial data: 'crore', 'lakh', etc."
    )

    # ========== Extraction Status ==========

    extraction_method: str = Field(
        ...,
        description="Extraction method: 'claude_vision_batch', 'hitl', 'manual'"
    )

    has_structured_data: bool = Field(
        default=False,
        description="True if data points were successfully extracted (not HITL placeholder)"
    )

    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Extraction confidence score (0.0-1.0)"
    )

    extraction_notes: List[str] = Field(
        default_factory=list,
        description="Issues encountered: blurry text, missing labels, OCR errors, etc."
    )

    # ========== Helper Methods ==========

    def get_series_by_name(self, name: str) -> Optional[ChartSeries]:
        """
        Find a series by name (case-insensitive).

        Args:
            name: Series name to search for

        Returns:
            ChartSeries if found, None otherwise
        """
        for s in self.series:
            if s.series_name.lower() == name.lower():
                return s
        return None

    def get_series_by_id(self, series_id: str) -> Optional[ChartSeries]:
        """
        Find a series by ID (case-insensitive).

        Args:
            series_id: Series ID to search for

        Returns:
            ChartSeries if found, None otherwise
        """
        for s in self.series:
            if s.series_id.lower() == series_id.lower():
                return s
        return None

    def get_data_point(
        self,
        category: str,
        series_id: Optional[str] = None
    ) -> Optional[DataPoint]:
        """
        Get a specific data point by category and optionally series.

        Args:
            category: Category (x-axis value) to find
            series_id: Optional series ID to narrow search

        Returns:
            DataPoint if found, None otherwise
        """
        for s in self.series:
            if series_id and s.series_id != series_id:
                continue
            for p in s.data_points:
                if p.category.lower() == category.lower():
                    return p
        return None

    def get_values(self, series_id: str) -> List[float]:
        """
        Extract all values from a specific series.

        Args:
            series_id: Series ID to extract values from

        Returns:
            List of values, or empty list if series not found
        """
        series = self.get_series_by_id(series_id)
        if series:
            return series.get_values()
        return []

    def get_all_categories(self) -> List[str]:
        """
        Get all unique categories across all series.

        Returns:
            List of unique category names
        """
        categories = set()
        for s in self.series:
            categories.update(s.get_categories())
        return sorted(list(categories))

    def get_value_range(self, series_id: Optional[str] = None) -> tuple[float, float]:
        """
        Get min and max values across series.

        Args:
            series_id: Optional series ID to limit to one series

        Returns:
            Tuple of (min_value, max_value)
        """
        values = []

        if series_id:
            values = self.get_values(series_id)
        else:
            for s in self.series:
                values.extend(s.get_values())

        if not values:
            return (0.0, 0.0)

        return (min(values), max(values))

    def get_total_across_series(self, category: str) -> float:
        """
        Sum values across all series for a given category.

        Useful for stacked bar charts or comparing totals.

        Args:
            category: Category to sum across

        Returns:
            Total value across all series
        """
        total = 0.0
        for s in self.series:
            point = s.get_point_by_category(category)
            if point:
                total += point.value
        return total

    def get_series_count(self) -> int:
        """Get number of data series in chart."""
        return len(self.series)

    def get_data_point_count(self) -> int:
        """Get total number of data points across all series."""
        return sum(len(s.data_points) for s in self.series)

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return self.model_dump()

    def __str__(self) -> str:
        series_str = f"{len(self.series)} series" if len(self.series) != 1 else "1 series"
        points_str = f"{self.get_data_point_count()} points"
        return f"StructuredChart(id={self.chart_id}, type={self.chart_type}, {series_str}, {points_str})"


# ========== Utility Functions ==========

def create_chart_from_dict(data: Dict) -> StructuredChart:
    """
    Create a StructuredChart from a dictionary.

    This is useful when deserializing from JSON or batch API responses.

    Args:
        data: Dictionary with chart data

    Returns:
        StructuredChart instance
    """
    return StructuredChart(**data)


def validate_chart_extraction(chart: StructuredChart) -> List[str]:
    """
    Validate chart extraction quality and return warnings.

    Args:
        chart: StructuredChart to validate

    Returns:
        List of validation warnings (empty if all good)
    """
    warnings = []

    # Check confidence
    if chart.confidence < 0.5:
        warnings.append(f"Low confidence score: {chart.confidence:.2f}")

    # Check for data
    if chart.has_structured_data and not chart.series:
        warnings.append("marked has_structured_data=True but no series data")

    # Check series data completeness
    for s in chart.series:
        if not s.data_points:
            warnings.append(f"Series '{s.series_name}' has no data points")

    # Check axis labels
    if not chart.x_axis.axis_label or chart.x_axis.axis_label.strip() == "":
        warnings.append("Missing or empty X-axis label")

    if not chart.y_axis.axis_label or chart.y_axis.axis_label.strip() == "":
        warnings.append("Missing or empty Y-axis label")

    # Check for monetary unit if chart seems financial
    if any(keyword in chart.title.lower() for keyword in ["revenue", "expense", "budget", "loss", "crore", "lakh"]):
        if not chart.monetary_unit:
            warnings.append("Chart appears financial but no monetary_unit specified")

    return warnings
