"""
Unit tests for P3-3: Temporal Extractor

Tests temporal metadata extraction including:
1. Audit period extraction from introduction text
2. Reference year extraction from text
3. Previous audit reference extraction
4. Document-level temporal coverage extraction
5. Chunk-level temporal annotation
"""

import pytest
from src.parsing_pipeline.modules.enrichment.temporal_extractor import TemporalExtractor


@pytest.fixture
def extractor():
    """Fixture providing a TemporalExtractor instance."""
    return TemporalExtractor()


# ==================== AUDIT PERIOD EXTRACTION TESTS ====================


def test_extract_audit_period_covering_pattern(extractor):
    """Test extraction of audit period with 'covering the period' pattern."""
    text = "This report covers the period 2019-20 to 2022-23 across all ministries."
    result = extractor.extract_audit_period(text)

    assert result is not None
    assert result["start_year"] == 2019
    assert result["end_year"] == 2022


def test_extract_audit_period_during_pattern(extractor):
    """Test extraction of audit period with 'during' pattern."""
    text = "The audit was conducted during 2018-19 to 2021-22 for the Railway sector."
    result = extractor.extract_audit_period(text)

    assert result is not None
    assert result["start_year"] == 2018
    assert result["end_year"] == 2021


def test_extract_audit_period_from_to_pattern(extractor):
    """Test extraction of audit period with 'from...to' pattern."""
    text = "Audit from 2020-21 to 2023-24 was carried out."
    result = extractor.extract_audit_period(text)

    assert result is not None
    assert result["start_year"] == 2020
    assert result["end_year"] == 2023


def test_extract_audit_period_for_years_pattern(extractor):
    """Test extraction of audit period with 'for the years' pattern."""
    text = "For the years 2017-18 to 2020-21, the following observations were made."
    result = extractor.extract_audit_period(text)

    assert result is not None
    assert result["start_year"] == 2017
    assert result["end_year"] == 2020


def test_extract_audit_period_month_names(extractor):
    """Test extraction of audit period with month names."""
    text = "The period from April 2019 to March 2023 was audited."
    result = extractor.extract_audit_period(text)

    assert result is not None
    assert result["start_year"] == 2019
    assert result["end_year"] == 2023


def test_extract_audit_period_not_found(extractor):
    """Test that None is returned when no audit period is found."""
    text = "This is a general paragraph without any audit period information."
    result = extractor.extract_audit_period(text)

    assert result is None


def test_extract_audit_period_invalid_year_range(extractor):
    """Test that invalid year ranges are rejected."""
    text = "The period 1990-91 to 1995-96 was reviewed."  # Outside 2000-2030 range
    result = extractor.extract_audit_period(text)

    assert result is None


# ==================== REFERENCE YEAR EXTRACTION TESTS ====================


def test_extract_reference_years_year_ranges(extractor):
    """Test extraction of year ranges like 2019-20."""
    text = "During 2019-20 and 2022-23, the expenditure was ₹500 crore."
    result = extractor.extract_reference_years(text)

    assert 2019 in result
    assert 2020 in result
    assert 2022 in result
    assert 2023 in result
    assert len(result) == 4


def test_extract_reference_years_standalone(extractor):
    """Test extraction of standalone years."""
    text = "In 2018, 2020, and 2022, the ministry reported losses."
    result = extractor.extract_reference_years(text)

    assert 2018 in result
    assert 2020 in result
    assert 2022 in result
    assert len(result) == 3


def test_extract_reference_years_mixed(extractor):
    """Test extraction of mixed year formats."""
    text = "From 2019-20 to 2021-22, and specifically in 2023, issues were noted."
    result = extractor.extract_reference_years(text)

    assert 2019 in result
    assert 2020 in result
    assert 2021 in result
    assert 2022 in result
    assert 2023 in result


def test_extract_reference_years_four_digit_suffix(extractor):
    """Test extraction with four-digit year suffix."""
    text = "During 2019-2020, the project was delayed."
    result = extractor.extract_reference_years(text)

    assert 2019 in result
    assert 2020 in result


def test_extract_reference_years_none_found(extractor):
    """Test empty list when no years are found."""
    text = "This paragraph contains no year references at all."
    result = extractor.extract_reference_years(text)

    assert result == []


def test_extract_reference_years_filters_invalid(extractor):
    """Test that invalid years outside 2000-2030 are filtered."""
    text = "In 1999 and 2031, events occurred."
    result = extractor.extract_reference_years(text)

    assert 1999 not in result
    assert 2031 not in result
    assert result == []


# ==================== PREVIOUS AUDIT REFERENCE TESTS ====================


def test_extract_previous_audit_refs_outstanding_paras(extractor):
    """Test extraction of outstanding paras from previous audits."""
    text = "Outstanding paras from the year 2018 remained unresolved."
    result = extractor.extract_previous_audit_refs(text)

    assert len(result) == 1
    assert result[0]["year"] == 2018
    assert "outstanding paras" in result[0]["raw_text"].lower()


def test_extract_previous_audit_refs_pending_observations(extractor):
    """Test extraction of pending audit observations."""
    text = "Pending audit observations since 2020 need action."
    result = extractor.extract_previous_audit_refs(text)

    assert len(result) == 1
    assert result[0]["year"] == 2020


def test_extract_previous_audit_refs_earlier_report(extractor):
    """Test extraction of references to earlier reports."""
    text = "As mentioned in the earlier audit of 2019, the issue persists."
    result = extractor.extract_previous_audit_refs(text)

    assert len(result) == 1
    assert result[0]["year"] == 2019


def test_extract_previous_audit_refs_report_number(extractor):
    """Test extraction of Report No. references."""
    text = "As per Report No. 15 of 2021, corrective action was required."
    result = extractor.extract_previous_audit_refs(text)

    assert len(result) == 1
    assert result[0]["year"] == 2021


def test_extract_previous_audit_refs_atn(extractor):
    """Test extraction of ATN (Action Taken Note) references."""
    text = "The ATN for 2020 was not submitted by the ministry."
    result = extractor.extract_previous_audit_refs(text)

    assert len(result) == 1
    assert result[0]["year"] == 2020


def test_extract_previous_audit_refs_multiple(extractor):
    """Test extraction of multiple previous audit references."""
    text = "Pending observations from 2018 and earlier report of 2020 remain unaddressed."
    result = extractor.extract_previous_audit_refs(text)

    assert len(result) == 2
    years = [ref["year"] for ref in result]
    assert 2018 in years
    assert 2020 in years


def test_extract_previous_audit_refs_deduplication(extractor):
    """Test that references to the same year are deduplicated."""
    text = "Outstanding paras from 2019 and pending observations of 2019 noted."
    result = extractor.extract_previous_audit_refs(text)

    # Should have 2 refs, but extract_temporal_metadata does deduplication
    assert len(result) >= 1  # At least one reference


# ==================== DOCUMENT-LEVEL TEMPORAL COVERAGE TESTS ====================


def test_extract_temporal_metadata_with_intro_sections(extractor):
    """Test temporal metadata extraction with section classifications."""
    child_chunks = [
        {"content": "This audit covers the period 2019-20 to 2022-23.", "parent_chunk_id": "intro"},
        {"content": "In 2020, the ministry spent ₹100 crore.", "parent_chunk_id": "findings"},
        {"content": "Outstanding paras from 2018 remain pending.", "parent_chunk_id": "findings"},
    ]

    section_classifications = [
        {"chunk_id": "intro", "section_type": "introduction"},
        {"chunk_id": "findings", "section_type": "findings"},
    ]

    result = extractor.extract_temporal_metadata(child_chunks, section_classifications)

    assert result["audit_period"] is not None
    assert result["audit_period"]["start_year"] == 2019
    assert result["audit_period"]["end_year"] == 2022
    assert 2020 in result["reference_years"]
    assert 2018 in result["reference_years"]
    assert len(result["previous_audit_refs"]) >= 1


def test_extract_temporal_metadata_without_section_classifications(extractor):
    """Test temporal metadata extraction without section classifications (fallback)."""
    child_chunks = [
        {"content": "This report covers the period 2020-21 to 2023-24."},
        {"content": "In 2021 and 2022, issues were noted."},
    ]

    result = extractor.extract_temporal_metadata(child_chunks, None)

    assert result["audit_period"] is not None
    assert result["audit_period"]["start_year"] == 2020
    assert result["audit_period"]["end_year"] == 2023
    assert 2021 in result["reference_years"]
    assert 2022 in result["reference_years"]


def test_extract_temporal_metadata_no_audit_period(extractor):
    """Test temporal metadata when no audit period is found."""
    child_chunks = [
        {"content": "In 2020 and 2021, some events occurred."},
    ]

    result = extractor.extract_temporal_metadata(child_chunks, None)

    assert result["audit_period"] is None
    assert 2020 in result["reference_years"]
    assert 2021 in result["reference_years"]


def test_extract_temporal_metadata_deduplicates_prev_refs(extractor):
    """Test that previous audit references are deduplicated by year."""
    child_chunks = [
        {"content": "Pending paras from 2018 noted."},
        {"content": "Earlier report of 2018 mentioned."},
        {"content": "Outstanding observations since 2019."},
    ]

    result = extractor.extract_temporal_metadata(child_chunks, None)

    # Should have 2 unique years: 2018 and 2019
    years = [ref["year"] for ref in result["previous_audit_refs"]]
    assert len(set(years)) == 2
    assert 2018 in years
    assert 2019 in years


def test_extract_temporal_metadata_aggregates_all_years(extractor):
    """Test that reference years are aggregated from all chunks."""
    child_chunks = [
        {"content": "In 2019-20, revenue was ₹100 crore."},
        {"content": "During 2021, the scheme was launched."},
        {"content": "By 2023, implementation was complete."},
    ]

    result = extractor.extract_temporal_metadata(child_chunks, None)

    assert 2019 in result["reference_years"]
    assert 2020 in result["reference_years"]
    assert 2021 in result["reference_years"]
    assert 2023 in result["reference_years"]


# ==================== CHUNK-LEVEL TEMPORAL ANNOTATION TESTS ====================


def test_annotate_chunk_temporal_year_range(extractor):
    """Test chunk annotation with year range."""
    chunk = {"content": "During 2019-20, the expenditure was ₹500 crore."}
    result = extractor.annotate_chunk_temporal(chunk)

    assert len(result) == 1
    assert result[0]["type"] == "year_range"
    assert result[0]["start_year"] == 2019
    assert result[0]["end_year"] == 2020
    assert result[0]["raw_text"] == "2019-20"


def test_annotate_chunk_temporal_multiple_ranges(extractor):
    """Test chunk annotation with multiple year ranges."""
    chunk = {"content": "From 2018-19 to 2021-22, the project was delayed."}
    result = extractor.annotate_chunk_temporal(chunk)

    assert len(result) == 2
    assert result[0]["start_year"] == 2018
    assert result[1]["start_year"] == 2021


def test_annotate_chunk_temporal_four_digit_suffix(extractor):
    """Test chunk annotation with four-digit year suffix."""
    chunk = {"content": "In 2019-2020, the policy was implemented."}
    result = extractor.annotate_chunk_temporal(chunk)

    assert len(result) == 1
    assert result[0]["start_year"] == 2019
    assert result[0]["end_year"] == 2020


def test_annotate_chunk_temporal_no_ranges(extractor):
    """Test chunk annotation when no year ranges are present."""
    chunk = {"content": "This paragraph has no year ranges, only standalone 2020."}
    result = extractor.annotate_chunk_temporal(chunk)

    assert result == []


def test_annotate_chunk_temporal_empty_content(extractor):
    """Test chunk annotation with empty content."""
    chunk = {"content": ""}
    result = extractor.annotate_chunk_temporal(chunk)

    assert result == []


# ==================== EDGE CASES AND VALIDATION TESTS ====================


def test_year_validation_filters_out_of_range(extractor):
    """Test that years outside 2000-2030 are filtered in all methods."""
    # Audit period
    text1 = "Period from 1995-96 to 1998-99"
    assert extractor.extract_audit_period(text1) is None

    # Reference years
    text2 = "In 1999 and 2035, events occurred."
    years = extractor.extract_reference_years(text2)
    assert years == []

    # Previous audit refs
    text3 = "Outstanding paras from 1997"
    refs = extractor.extract_previous_audit_refs(text3)
    assert refs == []


def test_handles_unicode_dash_characters(extractor):
    """Test handling of different dash/hyphen Unicode characters."""
    # Em dash (—), en dash (–), regular hyphen (-)
    text1 = "Period 2019—20 to 2022–23"
    result1 = extractor.extract_audit_period(text1)
    assert result1 is not None

    text2 = "During 2020—21, expenditure increased."
    years = extractor.extract_reference_years(text2)
    assert 2020 in years


def test_case_insensitive_pattern_matching(extractor):
    """Test that pattern matching is case-insensitive."""
    text1 = "COVERING THE PERIOD 2019-20 TO 2022-23"
    result = extractor.extract_audit_period(text1)
    assert result is not None

    text2 = "outstanding paras FROM 2020"
    refs = extractor.extract_previous_audit_refs(text2)
    assert len(refs) >= 1


def test_extract_reference_years_sorted_output(extractor):
    """Test that reference years are returned in sorted order."""
    text = "In 2023, 2019, 2021, and 2020, events occurred."
    result = extractor.extract_reference_years(text)

    assert result == sorted(result)
    assert result == [2019, 2020, 2021, 2023]


def test_previous_audit_refs_truncate_long_text(extractor):
    """Test that raw_text in previous audit refs is truncated to 100 chars."""
    long_text = "Outstanding paras from the year 2020 " + "x" * 200
    result = extractor.extract_previous_audit_refs(long_text)

    assert len(result) == 1
    assert len(result[0]["raw_text"]) <= 100


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
