"""
Standardize PDF Filenames from Manifest

Renames PDFs from "Original Title" naming to the pipeline-expected format:
    {Report_No}_{Recommended_Title}.pdf

Usage:
    python scripts/standardize_pdf_names.py <manifest.xlsx> [--pdf-dir data/raw] [--dry-run]

Examples:
    # Preview changes (dry run)
    python scripts/standardize_pdf_names.py State_Examples.xlsx --dry-run

    # Apply renames
    python scripts/standardize_pdf_names.py State_Examples.xlsx
"""

import argparse
import re
import sys
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    print("Error: pandas required. Install with: pip install pandas openpyxl")
    sys.exit(1)


def load_manifest(manifest_path: Path) -> pd.DataFrame:
    """Load and standardize manifest columns."""
    # Try header=1 first (original CAG format), fall back to header=0
    df = pd.read_excel(manifest_path, header=1)
    known_headers = {"SL NO", "Report PDF", "Title", "Original Title", "Date", "Report_No"}
    found_headers = set(str(c).strip() for c in df.columns) & known_headers

    if not found_headers:
        df = pd.read_excel(manifest_path, header=0)

    # Strip whitespace from column names
    df.columns = [str(c).strip() if isinstance(c, str) else c for c in df.columns]

    # Column mapping
    column_mapping = {
        "SL NO": "SL NO",
        "Original Title": "Title",
        "Recommended Title": "Recommended Title",
        "Report_No": "Report No",
        "Report No": "Report No",
    }
    rename_map = {k: v for k, v in column_mapping.items() if k in df.columns}
    df.rename(columns=rename_map, inplace=True)

    return df.dropna(how="all")


def build_report_id(row: pd.Series) -> str:
    """Build standardized report ID (same logic as manifest_ingestion_service)."""
    report_no_raw = row.get("Report No", "")
    if pd.isna(report_no_raw) or report_no_raw == "":
        report_no_raw = f"report_{int(row.get('SL NO', 0)):03d}"
    else:
        report_no_str = str(report_no_raw).strip()

        # Handle "X of YYYY" format -> "YYYY_X"
        of_match = re.match(r"(\d+)\s+of\s+(\d{4})", report_no_str)
        if of_match:
            num, year = of_match.groups()
            report_no_raw = f"{year}_{num}"
        else:
            # Handle "XX_YYYY" format -> "YYYY_XX"
            underscore_match = re.match(r"^(\d{1,2})_(\d{4})$", report_no_str)
            if underscore_match:
                num, year = underscore_match.groups()
                report_no_raw = f"{year}_{num}"
            else:
                # Replace / with _ for filename safety
                report_no_raw = report_no_str.replace("/", "_").replace(" ", "_")

    rec_title = row.get("Recommended Title", "")
    if pd.isna(rec_title) or not rec_title:
        rec_title = ""
    rec_title = str(rec_title).strip()

    # Sanitize for filename
    sanitized = re.sub(r'[^\w\s-]', '', rec_title)
    sanitized = re.sub(r'\s+', '_', sanitized)
    sanitized = sanitized[:80]

    return f"{report_no_raw}_{sanitized}"


def main():
    parser = argparse.ArgumentParser(
        description="Standardize PDF filenames from Original Title to pipeline format",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Preview changes
  python scripts/standardize_pdf_names.py State_Examples.xlsx --dry-run

  # Apply renames
  python scripts/standardize_pdf_names.py State_Examples.xlsx

  # Custom PDF directory
  python scripts/standardize_pdf_names.py State_Examples.xlsx --pdf-dir /path/to/pdfs
        """
    )
    parser.add_argument("manifest", help="Path to Excel manifest file")
    parser.add_argument("--pdf-dir", default="data/raw", help="Directory containing PDFs (default: data/raw)")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without renaming")

    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    pdf_dir = Path(args.pdf_dir)

    if not manifest_path.exists():
        print(f"Error: Manifest not found: {manifest_path}")
        sys.exit(1)

    if not pdf_dir.exists():
        print(f"Error: PDF directory not found: {pdf_dir}")
        sys.exit(1)

    print(f"Loading manifest: {manifest_path}")
    df = load_manifest(manifest_path)
    print(f"Found {len(df)} entries\n")

    renamed = 0
    skipped = 0
    not_found = 0

    for _, row in df.iterrows():
        # Current filename (Original Title)
        original_title = row.get("Title", "")
        if pd.isna(original_title) or not original_title:
            continue

        current_path = pdf_dir / f"{original_title}.pdf"

        # Target filename (standardized)
        report_id = build_report_id(row)
        target_path = pdf_dir / f"{report_id}.pdf"

        if target_path.exists():
            print(f"SKIP (already exists): {target_path.name[:60]}...")
            skipped += 1
            continue

        if not current_path.exists():
            print(f"NOT FOUND: {current_path.name[:60]}...")
            not_found += 1
            continue

        print(f"RENAME:")
        print(f"  FROM: {current_path.name[:70]}...")
        print(f"  TO:   {target_path.name[:70]}...")

        if not args.dry_run:
            current_path.rename(target_path)
            print(f"  DONE")
        else:
            print(f"  (dry run)")

        renamed += 1
        print()

    print(f"\n{'='*60}")
    print(f"Summary:")
    print(f"  Renamed:   {renamed}")
    print(f"  Skipped:   {skipped} (already standardized)")
    print(f"  Not found: {not_found}")

    if args.dry_run and renamed > 0:
        print(f"\nThis was a dry run. Run without --dry-run to apply changes.")


if __name__ == "__main__":
    main()
