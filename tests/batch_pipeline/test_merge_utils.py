"""
Overview merge by exact report ID (D-10a-05).

The old lookup fell back to report-ID prefixes, so a report whose LLM overview
failed was given another report's audit scope and entities, for example
OD_2025_05_... took OD_2025_07_..._overview_llm.json.
"""

import json

import pytest

from src.batch_pipeline.merge_utils import (
    RUN_MARKER_KEY,
    find_llm_overview_file,
    merge_llm_overview_data,
)

OD_05 = "OD_2025_05_School_Education_in_Odisha_School_and_Mass_Education_Department"
OD_07 = "OD_2025_07_Compliance_Audit_on_Irrigation"
UNION_04 = "2025_04_CAG_Report_on_Union_Government_Accounts_202223_Financial_Audit"


def _write_overview(overviews_dir, report_id, scope, run=None):
    data = {"audit_scope": {"description": scope}, "audit_objectives": [f"{scope} objective"]}
    if run:
        data[RUN_MARKER_KEY] = run
    path = overviews_dir / f"{report_id}_overview_llm.json"
    path.write_text(json.dumps(data))
    return path


@pytest.fixture
def dirs(tmp_path):
    overviews, summaries = tmp_path / "overviews", tmp_path / "summaries"
    overviews.mkdir()
    summaries.mkdir()
    return overviews, summaries


@pytest.mark.parametrize(
    "report_id, others",
    [
        (OD_05, [OD_07, "OD_2025_05_Another_Report", "OD_2025_05"]),
        ("2025_04_Some_Other_Report", [UNION_04]),
        (OD_05, [OD_05 + "_v2", "X_" + OD_05]),  # IDs containing this one
    ],
)
def test_never_picks_another_reports_file(dirs, report_id, others):
    overviews, summaries = dirs
    for other in others:
        _write_overview(overviews, other, f"scope of {other}")

    assert find_llm_overview_file(report_id, overviews) is None

    overview, stats = merge_llm_overview_data(report_id, {}, overviews, summaries)
    assert stats["llm_file_found"] is False
    assert "audit_scope" not in overview
    assert overview["_metadata"]["llm_extraction_available"] is False
    assert overview["_metadata"]["llm_extraction_path"] is None


def test_exact_file_is_merged_among_similar_ones(dirs):
    overviews, summaries = dirs
    _write_overview(overviews, OD_07, "irrigation")
    own = _write_overview(overviews, OD_05, "school education")
    (summaries / f"{OD_05}_summaries.json").write_text("{}")

    assert find_llm_overview_file(OD_05, overviews) == own
    overview, stats = merge_llm_overview_data(OD_05, {}, overviews, summaries)
    assert overview["audit_scope"] == {"description": "school education"}
    assert stats["fields_merged"] == 2
    assert overview["_metadata"]["llm_extraction_available"] is True
    assert overview["_metadata"]["summaries_available"] is True


def test_missing_overviews_dir(tmp_path):
    assert find_llm_overview_file(OD_05, tmp_path / "nope") is None


def test_stale_file_from_earlier_run_is_not_merged(dirs):
    overviews, summaries = dirs
    _write_overview(overviews, OD_05, "old scope", run="20260901_101010")

    overview, stats = merge_llm_overview_data(
        OD_05, {}, overviews, summaries, run_marker="20261004_120000"
    )
    assert stats["stale"] is True
    assert stats["fields_merged"] == 0
    assert "audit_scope" not in overview
    assert overview["_metadata"]["llm_extraction_available"] is False
    assert overview["_metadata"]["llm_extraction_stale"] is True


def test_file_from_this_run_is_merged(dirs):
    overviews, summaries = dirs
    _write_overview(overviews, OD_05, "school education", run="20261004_120000")

    overview, stats = merge_llm_overview_data(
        OD_05, {}, overviews, summaries, run_marker="20261004_120000"
    )
    assert stats["stale"] is False
    assert overview["audit_scope"] == {"description": "school education"}
    assert overview["_metadata"]["llm_extraction_run"] == "20261004_120000"
    assert RUN_MARKER_KEY not in overview


@pytest.mark.parametrize("file_run, run_marker", [(None, "20261004_120000"), ("20260901_101010", None)])
def test_without_both_markers_the_file_is_merged(dirs, file_run, run_marker):
    """Files written before the marker existed, and manual merges, still work."""
    overviews, summaries = dirs
    _write_overview(overviews, OD_05, "school education", run=file_run)

    overview, stats = merge_llm_overview_data(OD_05, {}, overviews, summaries, run_marker=run_marker)
    assert stats["fields_merged"] == 2
    assert overview["audit_scope"] == {"description": "school education"}
