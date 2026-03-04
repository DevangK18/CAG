"""Utilities for table name deduplication and preview generation."""
import re
from typing import Optional
from collections import Counter


def clean_table_caption(caption: str) -> str:
    """
    Clean up table caption:
    - Remove generic "Data Table:" prefix if caption starts with section number
    - Strip whitespace
    """
    if not caption:
        return "Untitled Table"

    caption = caption.strip()

    # If starts with "Data Table:" followed by a number, remove the prefix
    # Pattern: "Data Table: 2.3 Title" -> "2.3 Title"
    if caption.lower().startswith("data table:"):
        rest = caption[11:].strip()
        # Check if it starts with a section number (e.g., "2.3", "12.1.2")
        if re.match(r'^\d+\.', rest):
            return rest

    return caption


def disambiguate_table_names(tables: list[dict]) -> list[dict]:
    """
    Add disambiguators to tables with duplicate titles.

    Priority:
    1. Use structured_data.title if unique
    2. Append page number: "Title (Page 24)"
    3. Append dimensions: "Title (7×3)"
    """
    # First pass: clean all titles and count duplicates
    for table in tables:
        table["_clean_caption"] = clean_table_caption(table.get("title", ""))

    caption_counts = Counter(t["_clean_caption"] for t in tables)

    # Second pass: disambiguate duplicates
    seen_captions: dict[str, int] = {}

    for table in tables:
        clean_cap = table["_clean_caption"]

        if caption_counts[clean_cap] > 1:
            # This caption has duplicates, need to disambiguate

            # Try 1: Use structured_data.title if different and unique
            struct_title = (table.get("structured_data") or {}).get("title", "")
            if struct_title and struct_title != clean_cap:
                # Check if this title would be unique
                other_titles = [
                    (t.get("structured_data") or {}).get("title", "")
                    for t in tables if t["_clean_caption"] == clean_cap and t is not table
                ]
                if struct_title not in other_titles:
                    table["display_caption"] = clean_table_caption(struct_title)
                    continue

            # Try 2: Append page number
            page = table.get("page")
            if page:
                disambiguated = f"{clean_cap} (Page {page})"
                if disambiguated not in seen_captions:
                    table["display_caption"] = disambiguated
                    seen_captions[disambiguated] = 1
                    continue

            # Try 3: Append dimensions
            rows = table.get("rows", 0)
            cols = table.get("columns", 0)
            if rows and cols:
                disambiguated = f"{clean_cap} ({rows}×{cols})"
                if disambiguated not in seen_captions:
                    table["display_caption"] = disambiguated
                    seen_captions[disambiguated] = 1
                    continue

            # Fallback: append index
            idx = seen_captions.get(clean_cap, 0) + 1
            seen_captions[clean_cap] = idx
            table["display_caption"] = f"{clean_cap} ({idx})"
        else:
            # Unique caption, use as-is
            table["display_caption"] = clean_cap

    # Clean up temp field
    for table in tables:
        del table["_clean_caption"]

    return tables


def extract_table_preview(
    structured_data: Optional[dict],
    max_rows: int = 3,
    max_cols: int = 4,
    max_cell_chars: int = 12
) -> Optional[dict]:
    """
    Extract a mini-preview from structured_data for card display.

    Returns:
        {
            "headers": ["Col1", "Col2", ...],  # Up to max_cols
            "rows": [["val1", "val2", ...], ...],  # Up to max_rows
            "truncated": {"rows": bool, "cols": bool}
        }
    """
    if not structured_data:
        return None

    columns = structured_data.get("columns", [])
    rows = structured_data.get("rows", [])

    if not columns or not rows:
        return None

    # Extract headers (first max_cols columns)
    headers = []
    for col in columns[:max_cols]:
        header = col.get("header_text", "") or f"Col {col.get('col_idx', 0) + 1}"
        # Truncate long headers
        if len(header) > max_cell_chars:
            header = header[:max_cell_chars - 1] + "…"
        headers.append(header)

    # Extract data rows (skip header rows, take first max_rows data rows)
    preview_rows = []
    data_row_count = 0

    for row in rows:
        if row.get("row_type") == "header":
            continue

        if data_row_count >= max_rows:
            break

        cells = row.get("cells", [])
        row_data = []

        for cell in cells[:max_cols]:
            text = cell.get("cleaned_text") or cell.get("raw_text", "")
            # Truncate long cell values
            if len(text) > max_cell_chars:
                text = text[:max_cell_chars - 1] + "…"
            row_data.append(text)

        # Pad row if needed
        while len(row_data) < len(headers):
            row_data.append("")

        preview_rows.append(row_data)
        data_row_count += 1

    if not preview_rows:
        return None

    return {
        "headers": headers,
        "rows": preview_rows,
        "truncated": {
            "rows": len(rows) > max_rows + 1,  # +1 for header row
            "cols": len(columns) > max_cols
        }
    }
