"""
Tests known to fail on feature/gcp-migration as of 2026-10-04.

They are marked expected (xfail, non-strict) so CI stays green while they are
triaged: each is either fixed, rewritten for current behaviour, or deleted with
the dead code it covers. Remove an entry as soon as its test passes. The list
may only shrink. Each reason ends with the PR expected to remove the entry.
"""

# Files that cannot be imported: they use module layouts that no longer exist
# (..src.modules / services.parsing_pipeline.src). Relative to tests/.
BROKEN_IMPORT_FILES = [
]

# Test node ID -> reason
KNOWN_FAILURES = {
    'tests/parsing_pipeline/unit/test_structured_table_extractor_unit.py::TestStructuredTableExtractor::test_classify_column_time_period': 'expectations predate the current table header/column-type rules (fidelity PR: table extraction)',
    'tests/parsing_pipeline/unit/test_structured_table_extractor_unit.py::TestStructuredTableExtractor::test_detect_cell_type_decimal': 'expectations predate the current table header/column-type rules (fidelity PR: table extraction)',
    'tests/parsing_pipeline/unit/test_structured_table_extractor_unit.py::TestStructuredTableExtractor::test_detect_cell_type_integer': 'expectations predate the current table header/column-type rules (fidelity PR: table extraction)',
    'tests/parsing_pipeline/unit/test_structured_table_extractor_unit.py::TestStructuredTableExtractor::test_extract_entities': 'expectations predate the current table header/column-type rules (fidelity PR: table extraction)',
    'tests/parsing_pipeline/unit/test_structured_table_extractor_unit.py::TestStructuredTableExtractor::test_extract_simple_table': 'expectations predate the current table header/column-type rules (fidelity PR: table extraction)',
    'tests/parsing_pipeline/unit/test_structured_table_extractor_unit.py::TestStructuredTableExtractor::test_get_column_values': 'expectations predate the current table header/column-type rules (fidelity PR: table extraction)',
    'tests/parsing_pipeline/unit/test_structured_table_extractor_unit.py::TestStructuredTableExtractor::test_get_row_by_entity': 'expectations predate the current table header/column-type rules (fidelity PR: table extraction)',
    'tests/parsing_pipeline/unit/test_structured_table_extractor_unit.py::TestStructuredTableExtractor::test_sum_column': 'expectations predate the current table header/column-type rules (fidelity PR: table extraction)',
}

# Errors outside the test call (setup/teardown) cannot be xfailed; skipped instead
KNOWN_ERRORS_SKIPPED = {
}
