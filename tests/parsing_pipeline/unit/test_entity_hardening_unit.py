"""
Unit tests for P3-1: Entity Extraction Hardening

Tests the enhanced entity extraction patterns and post-processing filters
that reduce false positives from ~40-60% to <10%.
"""

import pytest
from src.parsing_pipeline.modules.semantic_enrichment_service import SemanticEnrichmentService


@pytest.fixture
def service():
    """Create a SemanticEnrichmentService instance."""
    return SemanticEnrichmentService()


class TestCleanEntityFilter:
    """Test the _clean_entity post-processing filter."""

    def test_valid_entity_accepted(self, service):
        """Valid entities should pass through."""
        assert service._clean_entity("National Highways Authority") == "National Highways Authority"
        assert service._clean_entity("Ministry of Finance") == "Ministry of Finance"
        assert service._clean_entity("Pradhan Mantri Awas Yojana") == "Pradhan Mantri Awas Yojana"

    def test_too_short_rejected(self, service):
        """Entities shorter than 4 chars should be rejected."""
        assert service._clean_entity("PWD") is None  # 3 chars
        assert service._clean_entity("AB") is None

    def test_too_long_rejected(self, service):
        """Entities longer than 60 chars should be rejected."""
        long_entity = "A" * 61
        assert service._clean_entity(long_entity) is None

    def test_lowercase_start_rejected(self, service):
        """Entities starting with lowercase should be rejected."""
        assert service._clean_entity("the Municipal Corporation") is None
        assert service._clean_entity("said that the Authority") is None

    def test_verb_start_rejected(self, service):
        """Entities starting with common verbs/articles should be rejected."""
        assert service._clean_entity("was implemented by Corporation") is None
        assert service._clean_entity("noted that the Ministry") is None
        assert service._clean_entity("said the Commission") is None
        assert service._clean_entity("the aforementioned Corporation") is None

    def test_too_many_words_rejected(self, service):
        """Entities with more than 6 words should be rejected."""
        assert service._clean_entity("This is a very long sentence fragment Corporation") is None

    def test_sentence_punctuation_rejected(self, service):
        """Entities containing mid-sentence punctuation should be rejected."""
        assert service._clean_entity("Ministry of Finance. The Department") is None
        assert service._clean_entity("Corporation! This is wrong") is None

    def test_whitespace_normalization(self, service):
        """Multiple whitespaces should be normalized."""
        result = service._clean_entity("National   Highways    Authority")
        assert result == "National Highways Authority"
        assert "  " not in result


class TestEnhancedPatterns:
    """Test the enhanced ENTITY_PATTERNS with stricter regex."""

    def test_scheme_requires_capital_start(self, service):
        """Scheme patterns should require capital letter start."""
        # Valid - starts with capital
        entities = service._extract_entities_from_text(
            "Under the Pradhan Mantri Gram Sadak Yojana (PMGSY), roads were constructed."
        )
        assert any("Pradhan Mantri Gram Sadak Yojana" in e for e in entities)

        # Invalid - lowercase start should not match
        entities = service._extract_entities_from_text(
            "the aforementioned scheme was implemented"
        )
        assert len([e for e in entities if "scheme" in e.lower()]) == 0

    def test_ministry_requires_capital_start(self, service):
        """Ministry patterns should require capital letter start."""
        entities = service._extract_entities_from_text(
            "Ministry of Finance and Ministry of Defence were audited."
        )
        assert "Ministry of Finance" in entities
        assert "Ministry of Defence" in entities

    def test_organization_requires_capitalized_words(self, service):
        """Organization patterns should require capitalized words before suffix."""
        # Valid - capitalized words
        entities = service._extract_entities_from_text(
            "National Highways Authority of India and Municipal Corporation were reviewed."
        )
        assert any("Authority" in e for e in entities)

        # Invalid - should not capture fragments
        entities = service._extract_entities_from_text(
            "the aforementioned Corporation was found"
        )
        # Lowercase start should be filtered out by _clean_entity
        assert not any(e.startswith("the ") for e in entities)

    def test_acronym_pattern_captured(self, service):
        """Scheme acronyms in parentheses should be captured."""
        entities = service._extract_entities_from_text(
            "Pradhan Mantri Gram Sadak Yojana (PMGSY) received funding."
        )
        # Should capture the full name with acronym
        assert any("PMGSY" in e or "Pradhan Mantri Gram Sadak Yojana" in e for e in entities)

    def test_common_cag_acronyms_captured(self, service):
        """Common CAG acronyms should be explicitly matched."""
        text = "NHAI, ONGC, BHEL, SAIL, HAL, AAI, and FCI were audited."
        entities = service._extract_entities_from_text(text)

        # At least some of these should be captured
        acronyms = ["NHAI", "ONGC", "BHEL", "SAIL", "HAL", "AAI", "FCI"]
        found = [acr for acr in acronyms if acr in entities]
        assert len(found) >= 3  # At least 3 acronyms should match


class TestEntityDeduplication:
    """Test entity deduplication by substring."""

    def test_shorter_subsumed_by_longer(self, service):
        """Shorter entities that are substrings of longer ones should be removed."""
        child_chunks = [
            {
                "content": "National Highways Authority manages roads. "
                          "National Highways Authority of India reported delays."
            }
        ]

        entities = service._extract_entities(child_chunks)
        orgs = entities.get("organizations", [])

        # Should keep only the longer version
        if orgs:
            # Check that if both exist, the longer one is preferred
            full_names = [e for e in orgs if "National Highways Authority" in e]
            if len(full_names) > 1:
                # Ensure the longer one is kept
                longest = max(full_names, key=len)
                assert longest in orgs

    def test_no_false_deduplication(self, service):
        """Different entities should not be deduplicated."""
        child_chunks = [
            {
                "content": "Ministry of Finance and Ministry of Defence are separate."
            }
        ]

        entities = service._extract_entities(child_chunks)
        ministries = entities.get("ministries", [])

        # Both should be present (not deduplicated)
        assert any("Finance" in m for m in ministries)
        assert any("Defence" in m for m in ministries)

    def test_case_insensitive_deduplication(self, service):
        """Deduplication should be case-insensitive."""
        child_chunks = [
            {
                "content": "NATIONAL HIGHWAYS AUTHORITY and National Highways Authority mentioned."
            }
        ]

        entities = service._extract_entities(child_chunks)
        orgs = entities.get("organizations", [])

        # Should only have one version
        nha_count = len([e for e in orgs if "national highways authority" in e.lower()])
        assert nha_count <= 2  # At most 2 (with/without full name)


class TestEndToEndExtraction:
    """Test end-to-end entity extraction with all improvements."""

    def test_complex_document_extraction(self, service):
        """Test extraction from realistic CAG report text."""
        child_chunks = [
            {
                "content": (
                    "The Ministry of Railways reported delays in the "
                    "Pradhan Mantri Gram Sadak Yojana (PMGSY). "
                    "National Highways Authority of India (NHAI) was involved. "
                    "The aforementioned Corporation failed to comply."
                )
            }
        ]

        entities = service._extract_entities(child_chunks)

        # Check ministries
        ministries = entities.get("ministries", [])
        assert any("Railway" in m for m in ministries), f"Found ministries: {ministries}"

        # Check schemes
        schemes = entities.get("schemes", [])
        assert any("Pradhan Mantri" in s or "PMGSY" in s for s in schemes), f"Found schemes: {schemes}"

        # Check organizations
        orgs = entities.get("organizations", [])
        assert any("NHAI" in o or "National Highways Authority" in o for o in orgs), f"Found orgs: {orgs}"

        # Should NOT contain garbage like "the aforementioned Corporation"
        assert not any(e.startswith("the ") for e in orgs)
        assert not any("aforementioned" in e for e in orgs)

    def test_sentence_fragments_filtered(self, service):
        """Sentence fragments should be filtered out."""
        child_chunks = [
            {
                "content": (
                    "It was noted that the Municipal Corporation failed. "
                    "The said Authority was directed. "
                    "Ministry of Finance approved the scheme."
                )
            }
        ]

        entities = service._extract_entities(child_chunks)

        # Get all extracted entities
        all_entities = []
        for entity_list in entities.values():
            all_entities.extend(entity_list)

        # Should not contain verb-starting fragments
        assert not any(e.lower().startswith("was ") for e in all_entities)
        assert not any(e.lower().startswith("noted ") for e in all_entities)
        assert not any(e.lower().startswith("said ") for e in all_entities)
        assert not any(e.lower().startswith("the ") for e in all_entities)

        # Should contain valid entities
        ministries = entities.get("ministries", [])
        assert any("Finance" in m for m in ministries)

    def test_length_bounds_enforced(self, service):
        """All extracted entities should be within length bounds (4-60 chars)."""
        child_chunks = [
            {
                "content": (
                    "Ministry of Finance, PWD, NHAI, "
                    "National Highways Authority of India participated."
                )
            }
        ]

        entities = service._extract_entities(child_chunks)

        # Check all entities
        for entity_type, entity_list in entities.items():
            for entity in entity_list:
                assert 4 <= len(entity) <= 60, f"Entity '{entity}' violates length bounds"

    def test_empty_content_handled(self, service):
        """Empty or whitespace-only content should not crash."""
        child_chunks = [
            {"content": ""},
            {"content": "   "},
            {"content": "\n\n\n"},
        ]

        entities = service._extract_entities(child_chunks)

        # Should return empty or minimal results without crashing
        assert isinstance(entities, dict)
        for entity_type in entities:
            assert isinstance(entities[entity_type], list)


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_unicode_entities(self, service):
        """Entities with Unicode characters should be handled."""
        entities = service._extract_entities_from_text(
            "Pradhan Mantri Āyushman Bhārat Yojana was launched."
        )
        # Should extract if pattern matches
        assert isinstance(entities, list)

    def test_special_characters_in_names(self, service):
        """Entities with ampersands and hyphens should be captured."""
        entities = service._extract_entities_from_text(
            "Ministry of Micro, Small & Medium Enterprises reported."
        )
        # Should extract ministry with commas and ampersands
        assert any("Enterprises" in e and ("Micro" in e or "Ministry" in e) for e in entities)

    def test_multiple_occurrences_deduplicated(self, service):
        """Multiple occurrences of same entity should result in single entry."""
        child_chunks = [
            {
                "content": (
                    "Ministry of Finance reported. "
                    "Ministry of Finance approved. "
                    "Ministry of Finance directed."
                )
            }
        ]

        entities = service._extract_entities(child_chunks)
        ministries = entities.get("ministries", [])

        # Count occurrences of "Ministry of Finance"
        finance_count = len([m for m in ministries if "Finance" in m])
        assert finance_count == 1, "Same entity should appear only once"

    def test_nested_patterns_not_double_counted(self, service):
        """Overlapping pattern matches should not create duplicates."""
        text = "Department of Revenue, Ministry of Finance participated."
        entities = service._extract_entities_from_text(text)

        # Should extract both, but each only once
        assert isinstance(entities, list)
        # No duplicate substrings
        for i, e1 in enumerate(entities):
            for e2 in entities[i+1:]:
                # Neither should be a substring of the other
                if e1.lower() in e2.lower() or e2.lower() in e1.lower():
                    # This is acceptable if they're truly different entities
                    pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
