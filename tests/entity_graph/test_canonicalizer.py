"""
Tests for entity canonicalization (Phase 12).

Test cases:
1. pre_bucket groups records with same lowercase canonical
2. collapse_buckets merges aliases and picks longest canonical
3. _final_alias_merge collapses cross-batch overlaps
4. End-to-end with mocked OpenAI client
"""

import json
import pytest
from unittest.mock import Mock, patch

pytest.importorskip("src.entity_graph.canonicalizer")

from src.entity_graph.canonicalizer import (
    pre_bucket,
    collapse_buckets,
    _final_alias_merge,
    canonicalize_via_llm,
)


class TestPreBucket:
    """Test pre_bucket groups records with same lowercase canonical."""

    def test_groups_by_lowercase_canonical(self):
        """Records with same canonical (case-insensitive) are grouped."""
        records = [
            {
                "canonical_form_in_report": "NHAI",
                "entity_type": "psu",
                "aliases_seen": ["NHAI"],
            },
            {
                "canonical_form_in_report": "nhai",
                "entity_type": "psu",
                "aliases_seen": ["NHAI", "National Highways Authority"],
            },
            {
                "canonical_form_in_report": "Ministry of Railways",
                "entity_type": "ministry",
                "aliases_seen": ["MoR"],
            },
        ]

        buckets = pre_bucket(records)

        assert len(buckets) == 2
        assert "nhai" in buckets
        assert "ministry of railways" in buckets
        assert len(buckets["nhai"]) == 2
        assert len(buckets["ministry of railways"]) == 1

    def test_filters_short_canonicals(self):
        """Records with canonical < 3 chars are filtered out."""
        records = [
            {"canonical_form_in_report": "AB", "entity_type": "org", "aliases_seen": []},
            {
                "canonical_form_in_report": "ABC",
                "entity_type": "org",
                "aliases_seen": [],
            },
        ]

        buckets = pre_bucket(records)

        assert "ab" not in buckets
        assert "abc" in buckets


class TestCollapseBuckets:
    """Test collapse_buckets merges aliases and picks longest canonical."""

    def test_picks_longest_canonical(self):
        """Within a bucket, the longest canonical_form_in_report is selected."""
        buckets = {
            "nhai": [
                {
                    "canonical_form_in_report": "NHAI",
                    "entity_type": "psu",
                    "aliases_seen": ["NHAI"],
                    "tier_context": "union",
                },
                {
                    "canonical_form_in_report": "National Highways Authority of India",
                    "entity_type": "psu",
                    "aliases_seen": ["NHAI", "National Highways Authority"],
                    "tier_context": "union",
                },
            ]
        }

        consolidated = collapse_buckets(buckets)

        assert len(consolidated) == 1
        assert (
            consolidated[0]["canonical_form_in_report"]
            == "National Highways Authority of India"
        )

    def test_merges_all_aliases(self):
        """All aliases from all records in the bucket are merged."""
        buckets = {
            "mor": [
                {
                    "canonical_form_in_report": "MoR",
                    "entity_type": "ministry",
                    "aliases_seen": ["MoR", "Ministry of Railways"],
                    "tier_context": "union",
                },
                {
                    "canonical_form_in_report": "Min. of Railways",
                    "entity_type": "ministry",
                    "aliases_seen": ["Min. of Railways"],
                    "tier_context": "union",
                },
            ]
        }

        consolidated = collapse_buckets(buckets)

        aliases = consolidated[0]["aliases_seen"]
        assert "MoR" in aliases
        assert "Ministry of Railways" in aliases
        assert "Min. of Railways" in aliases

    def test_most_common_entity_type(self):
        """The most common entity_type across records is selected."""
        buckets = {
            "foo": [
                {
                    "canonical_form_in_report": "Foo",
                    "entity_type": "psu",
                    "aliases_seen": [],
                    "tier_context": "union",
                },
                {
                    "canonical_form_in_report": "Foo",
                    "entity_type": "psu",
                    "aliases_seen": [],
                    "tier_context": "union",
                },
                {
                    "canonical_form_in_report": "Foo",
                    "entity_type": "organization",
                    "aliases_seen": [],
                    "tier_context": "union",
                },
            ]
        }

        consolidated = collapse_buckets(buckets)

        assert consolidated[0]["entity_type"] == "psu"


class TestFinalAliasMerge:
    """Test _final_alias_merge collapses cross-batch overlaps."""

    def test_merges_entities_with_overlapping_aliases(self):
        """Entities with any overlapping alias are merged."""
        entities = [
            {
                "canonical_name": "NHAI",
                "entity_type": "psu",
                "aliases": ["NHAI", "National Highways Authority"],
                "primary_tier": "union",
            },
            {
                "canonical_name": "National Highways Authority of India",
                "entity_type": "psu",
                "aliases": ["NHAI", "NH Authority"],
                "primary_tier": "union",
            },
        ]

        merged = _final_alias_merge(entities)

        # Should merge into 1 entity (both have "NHAI" alias)
        assert len(merged) == 1
        assert (
            merged[0]["canonical_name"] == "National Highways Authority of India"
        )  # longer
        assert "NHAI" in merged[0]["aliases"]
        assert "National Highways Authority" in merged[0]["aliases"]
        assert "NH Authority" in merged[0]["aliases"]

    def test_keeps_separate_entities_without_overlap(self):
        """Entities with no overlapping aliases remain separate."""
        entities = [
            {
                "canonical_name": "NHAI",
                "entity_type": "psu",
                "aliases": ["NHAI"],
                "primary_tier": "union",
            },
            {
                "canonical_name": "Ministry of Railways",
                "entity_type": "ministry",
                "aliases": ["MoR"],
                "primary_tier": "union",
            },
        ]

        merged = _final_alias_merge(entities)

        assert len(merged) == 2


class TestCanonicalizeViaLLM:
    """Test end-to-end canonicalization with mocked OpenAI."""

    @patch("src.entity_graph.canonicalizer.OpenAI")
    def test_end_to_end_canonicalization(self, mock_openai_class):
        """Full canonicalization pipeline with mocked LLM."""
        # Mock OpenAI client
        mock_client = Mock()
        mock_openai_class.return_value = mock_client

        # Mock streaming response
        response_json = json.dumps({
            "merged_entities": [
                {
                    "canonical_name": "National Highways Authority of India",
                    "entity_type": "psu",
                    "aliases": ["NHAI", "National Highways Authority"],
                    "primary_tier": "union",
                }
            ]
        })

        # Create mock chunks for streaming
        mock_chunks = [
            Mock(choices=[Mock(delta=Mock(content=response_json), finish_reason=None)]),
            Mock(choices=[Mock(delta=Mock(content=None), finish_reason="stop")]),
        ]
        mock_client.chat.completions.create.return_value = iter(mock_chunks)

        # Input: pre-bucketed records
        consolidated = [
            {
                "canonical_form_in_report": "NHAI",
                "entity_type": "psu",
                "aliases_seen": ["NHAI", "National Highways Authority"],
                "tier_context": "union",
                "_occurrence_count": 10,
            }
        ]

        result = canonicalize_via_llm(consolidated, model="gpt-4o-mini", batch_size=80)

        # Verify LLM was called
        assert mock_client.chat.completions.create.called

        # Verify result
        assert len(result) == 1
        assert result[0]["canonical_name"] == "National Highways Authority of India"
        assert "NHAI" in result[0]["aliases"]

    @patch("src.entity_graph.canonicalizer.OpenAI")
    def test_handles_llm_failure_gracefully(self, mock_openai_class):
        """When LLM call fails, the batch is skipped but process continues."""
        mock_client = Mock()
        mock_openai_class.return_value = mock_client

        # First call succeeds with streaming chunks
        success_json = json.dumps({
            "merged_entities": [
                {
                    "canonical_name": "Entity A",
                    "entity_type": "org",
                    "aliases": ["A"],
                    "primary_tier": "union",
                }
            ]
        })
        mock_success_chunks = [
            Mock(choices=[Mock(delta=Mock(content=success_json), finish_reason=None)]),
            Mock(choices=[Mock(delta=Mock(content=None), finish_reason="stop")]),
        ]

        # Second call fails
        mock_client.chat.completions.create.side_effect = [
            iter(mock_success_chunks),
            Exception("API error"),
            Exception("API error"),
            Exception("API error"),  # All 3 retries fail
        ]

        consolidated = [
            {
                "canonical_form_in_report": "Entity A",
                "entity_type": "org",
                "aliases_seen": ["A"],
                "tier_context": "union",
                "_occurrence_count": 5,
            },
            {
                "canonical_form_in_report": "Entity B",
                "entity_type": "org",
                "aliases_seen": ["B"],
                "tier_context": "union",
                "_occurrence_count": 3,
            },
        ]

        result = canonicalize_via_llm(
            consolidated, model="gpt-4o-mini", batch_size=1
        )  # batch_size=1 to force 2 batches

        # First batch should have succeeded
        assert len(result) >= 1
        assert result[0]["canonical_name"] == "Entity A"
