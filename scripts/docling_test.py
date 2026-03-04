from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
from docling.datamodel.base_models import InputFormat

opts = PdfPipelineOptions(do_table_structure=True)
opts.table_structure_options.mode = TableFormerMode.ACCURATE
converter = DocumentConverter(
    format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
)

# Use one of the 5 scanned reports
result = converter.convert(
    source="data/raw/2025_04_CAG_Report_on_Union_Government_Accounts_202223_Financial_Audit.pdf"
)
doc = result.document

import re


def count_non_empty_cells(markdown_table: str) -> int:
    """Quality gate logic from layout_analysis_service.py"""
    non_empty_count = 0
    for line in markdown_table.strip().split("\n"):
        if re.match(r"^\s*\|[\s\-:]+\|\s*$", line):
            continue
        cells = [cell.strip() for cell in line.split("|")]
        cells = [c for c in cells if c]
        non_empty_count += sum(1 for cell in cells if cell and cell.strip())
    return non_empty_count


table_count = 0
passed_quality_gate = 0
failed_quality_gate = 0

for item, _ in doc.iterate_items():
    if "Table" in type(item).__name__:
        table_count += 1
        if hasattr(item, "export_to_markdown"):
            md = item.export_to_markdown(doc)  # Fix deprecation warning
            cell_count = count_non_empty_cells(md)

            if cell_count >= 3:
                passed_quality_gate += 1
                if passed_quality_gate == 1:  # Show first passing table
                    print(f"\n✅ PASSING TABLE #{table_count}:")
                    print(f"   Non-empty cells: {cell_count}")
                    print(f"   Markdown:\n{md[:300]}\n")
            else:
                failed_quality_gate += 1
                if failed_quality_gate == 1:  # Show first failing table
                    print(f"\n❌ FAILING TABLE #{table_count} (quality gate):")
                    print(f"   Non-empty cells: {cell_count} (min: 3)")
                    print(f"   Markdown:\n{md}\n")

print(f"\n📊 SUMMARY:")
print(f"   Total tables: {table_count}")
print(f"   Passed quality gate (≥3 cells): {passed_quality_gate}")
print(f"   Failed quality gate (<3 cells): {failed_quality_gate}")
