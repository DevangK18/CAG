"""
Chart Extraction Prompt for P2-2 Chart Data Extraction.

This prompt template guides Claude Vision to extract structured data from
CAG audit report chart images, producing JSON output that matches the
StructuredChart model.
"""

CHART_EXTRACTION_PROMPT = """You are analyzing a chart from a CAG (Comptroller and Auditor General of India) audit report.

TASK: Extract structured data from the chart image provided.

Provide a JSON response with the following structure:

{
  "title": "Chart title (extract from image or infer from context)",
  "chart_type": "One of: bar, line, pie, scatter, area, combo, table_chart, unknown",
  "subtitle": "Subtitle if present, else null",
  "description": "Brief 1-2 sentence description of what the chart shows",

  "x_axis": {
    "axis_id": "x_axis",
    "axis_label": "X-axis label from chart",
    "axis_type": "categorical | numeric | temporal",
    "label_format": "e.g., fiscal_year, states, categories, percentage",
    "unit": "Unit if applicable (null otherwise)",
    "min_value": null,
    "max_value": null,
    "scale": null
  },

  "y_axis": {
    "axis_id": "y_axis",
    "axis_label": "Y-axis label from chart",
    "axis_type": "numeric (usually)",
    "label_format": "e.g., currency, percentage, count",
    "unit": "crore | lakh | percentage | count | null",
    "min_value": "Minimum value if visible",
    "max_value": "Maximum value if visible",
    "scale": "linear | logarithmic | null"
  },

  "secondary_y_axis": null or {same structure as y_axis} for dual-axis charts,

  "series": [
    {
      "series_id": "programmatic_id (e.g., actual_revenue, budgeted_revenue)",
      "series_name": "Human-readable name shown in legend",
      "data_points": [
        {
          "category": "X-axis value (e.g., 2021-22, Maharashtra, Q1)",
          "value": "numeric Y-axis value",
          "series": "series_id",
          "label": "optional label shown on point"
        },
        ...
      ],
      "color": "#hex_color if detectable",
      "cumulative": true/false/null
    },
    ...
  ],

  "legend": {
    "entries": [
      {"label": "...", "color": "#..."},
      ...
    ],
    "position": "top-right | bottom-left | top | right | etc."
  } or null if no legend,

  "entities_referenced": ["List of ministries, departments, states, schemes, PSUs mentioned"],
  "time_periods": ["Years or fiscal years covered: e.g., 2021-22, 2022-23"],
  "monetary_unit": "crore | lakh | null (if chart shows monetary data)",

  "extraction_notes": ["Any issues: blurry text, missing labels, partial OCR, unclear values"],
  "confidence": "Your confidence in extraction accuracy: 0.0-1.0"
}

EXTRACTION GUIDELINES:

1. **Chart Type Classification:**
   - bar: Vertical or horizontal bars for comparison
   - line: Line graph showing trends over time
   - pie: Circular chart showing composition/distribution
   - scatter: Points showing correlation between variables
   - area: Area under a line, often stacked
   - combo: Combination of types (e.g., bar + line)
   - table_chart: Data presented in tabular format within chart
   - unknown: If type is unclear

2. **Axis Identification:**
   - Extract exact axis labels from the image
   - Infer axis_type based on data nature:
     * categorical: Discrete categories (states, departments, schemes)
     * numeric: Continuous numbers (amounts, percentages, counts)
     * temporal: Time-based (years, quarters, months)
   - For monetary values, identify unit (crore/lakh) from axis label or values

3. **Data Point Extraction:**
   - Extract ALL visible data points with their exact values
   - For bar charts: Read bar heights/lengths carefully
   - For line charts: Trace each line and extract points at each category
   - For pie charts: Extract percentages or values for each slice
   - If exact values are unclear, estimate from visual scale but note in extraction_notes

4. **Indian Monetary Units:**
   - Recognize "Crore" (10 million) and "Lakh" (100 thousand)
   - Common formats: "₹ Crore", "Rs. in Lakh", "Amount (₹ Cr.)"
   - Convert all to numeric: "2.5 Crore" → 2.5

5. **Fiscal Year Format:**
   - Indian fiscal years: April-March
   - Formats: "2021-22", "FY 2021-22", "2021-2022"
   - Normalize to "YYYY-YY" format (e.g., "2021-22")

6. **Entity Recognition:**
   - Identify: Ministries (e.g., "Ministry of Finance")
   - States (e.g., "Maharashtra", "Tamil Nadu")
   - Schemes (e.g., "Pradhan Mantri Awas Yojana", "NREGA")
   - PSUs (e.g., "NHAI", "Indian Railways")
   - Departments (e.g., "Department of Revenue")

7. **Confidence Scoring:**
   - 0.9-1.0: Crystal clear chart, all labels readable, all values precise
   - 0.7-0.9: Good quality, minor OCR uncertainties or small values hard to read
   - 0.5-0.7: Moderate quality, some values estimated, axis labels partially unclear
   - 0.3-0.5: Poor quality, significant estimation, multiple uncertainties
   - 0.0-0.3: Very poor quality, mostly guesswork, recommend HITL

8. **Extraction Notes:**
   - Document any issues encountered:
     * "Blurry axis labels, partially estimated"
     * "Small values hard to read precisely"
     * "Missing legend, series names inferred from context"
     * "Y-axis scale unclear, values approximated"
     * "Overlapping text, some labels unreadable"

9. **Multi-Series Charts:**
   - Extract each series separately
   - Match series to legend entries
   - Use consistent series_id across data_points

10. **Complex Charts:**
    - For dual-axis charts: Identify which series uses which axis
    - For stacked charts: Extract individual series, not cumulative totals
    - For combo charts: Specify chart_type as "combo" and extract all series

CHART CONTEXT (from document):
{context}

IMPORTANT OUTPUT REQUIREMENTS:
- Return ONLY valid JSON, no markdown formatting
- Use null for missing/unclear fields
- Include extraction_notes for any uncertainties
- Be conservative with confidence scores
- If chart is completely illegible (confidence < 0.3), return minimal structure with extraction_notes

EXAMPLE OUTPUT (simplified):

{{
  "title": "Revenue Collection Trend (2020-2024)",
  "chart_type": "line",
  "subtitle": null,
  "description": "Shows increasing revenue collection trend over 4 fiscal years",
  "x_axis": {{
    "axis_id": "x_axis",
    "axis_label": "Financial Year",
    "axis_type": "temporal",
    "label_format": "fiscal_year",
    "unit": null,
    "min_value": null,
    "max_value": null,
    "scale": null
  }},
  "y_axis": {{
    "axis_id": "y_axis",
    "axis_label": "Revenue (₹ Crore)",
    "axis_type": "numeric",
    "label_format": "currency",
    "unit": "crore",
    "min_value": 0,
    "max_value": 5000,
    "scale": "linear"
  }},
  "secondary_y_axis": null,
  "series": [
    {{
      "series_id": "actual_revenue",
      "series_name": "Actual Revenue",
      "data_points": [
        {{"category": "2020-21", "value": 3200.5, "series": "actual_revenue", "label": null}},
        {{"category": "2021-22", "value": 3850.2, "series": "actual_revenue", "label": null}},
        {{"category": "2022-23", "value": 4100.8, "series": "actual_revenue", "label": null}},
        {{"category": "2023-24", "value": 4650.3, "series": "actual_revenue", "label": null}}
      ],
      "color": "#4472C4",
      "cumulative": false
    }}
  ],
  "legend": {{
    "entries": [{{"label": "Actual Revenue", "color": "#4472C4"}}],
    "position": "top-right"
  }},
  "entities_referenced": ["Ministry of Finance", "Direct Tax Department"],
  "time_periods": ["2020-21", "2021-22", "2022-23", "2023-24"],
  "monetary_unit": "crore",
  "extraction_notes": [],
  "confidence": 0.92
}}

Now analyze the provided chart image and extract the structured data following these guidelines."""


def build_chart_prompt(chunk: dict, context_text: str) -> str:
    """
    Build the chart extraction prompt with context.

    Args:
        chunk: ChildChunk dict with chart metadata
        context_text: Context string from hierarchy and adjacent text

    Returns:
        Complete prompt string
    """
    return CHART_EXTRACTION_PROMPT.format(context=context_text)
