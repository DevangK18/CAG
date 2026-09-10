"""
Unit tests for tier-specific summary and overview prompts.

Tests verify that:
1. Each tier gets appropriate audience references
2. Financial scales are tier-appropriate
3. Legal frameworks are correctly referenced
4. No Union-specific content appears in State/Local prompts
"""

import pytest
from src.batch_pipeline.prompts.summary_variants import (
    TIER_CONTEXT,
    VARIANTS,
    get_summary_prompt,
    _get_executive_prompt,
    _get_journalist_prompt,
    _get_deep_dive_prompt,
    _get_simple_prompt,
    _get_policy_prompt,
)
from src.batch_pipeline.prompts.overview_extraction import (
    build_overview_prompt,
    _get_glossary_guidance,
    _get_topic_guidance,
    _get_entity_guidance,
)


# ═══════════════════════════════════════════════════════════════════════════════
# TIER CONTEXT TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestTierContext:
    """Tests for TIER_CONTEXT dictionary."""

    def test_all_tiers_present(self):
        """All three tiers should be defined."""
        assert "union" in TIER_CONTEXT
        assert "state" in TIER_CONTEXT
        assert "local_body" in TIER_CONTEXT

    def test_union_context_has_required_fields(self):
        """Union context should have all required fields."""
        union = TIER_CONTEXT["union"]
        assert "submitted_to" in union
        assert "legislature" in union
        assert "primary_audience" in union
        assert "legal_framework" in union
        assert "financial_scale" in union

    def test_union_financial_scale(self):
        """Union should have appropriate financial scale."""
        union = TIER_CONTEXT["union"]
        assert "₹100 Crore" in union["financial_scale"]["critical"]

    def test_local_body_financial_scale(self):
        """Local body should have smaller financial scale."""
        local = TIER_CONTEXT["local_body"]
        assert "₹10 Crore" in local["financial_scale"]["critical"]


# ═══════════════════════════════════════════════════════════════════════════════
# EXECUTIVE PROMPT TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestExecutivePrompt:
    """Tests for tier-specific executive prompts."""

    def test_union_contains_ministry_references(self):
        """Union executive prompt should reference ministries and PAC."""
        prompt = _get_executive_prompt("union")
        assert "Ministry" in prompt
        assert "PAC" in prompt or "Parliamentary" in prompt

    def test_union_contains_gfr_reference(self):
        """Union executive prompt should reference GFR."""
        prompt = _get_executive_prompt("union")
        assert "GFR" in prompt

    def test_state_contains_state_references(self):
        """State executive prompt should reference state-level entities."""
        prompt = _get_executive_prompt("state", "Himachal Pradesh")
        assert "Chief Secretary" in prompt or "Department Secretar" in prompt
        assert "State PAC" in prompt or "State Assembly" in prompt
        assert "Himachal Pradesh" in prompt

    def test_state_contains_state_fr_reference(self):
        """State executive prompt should reference State Financial Rules."""
        prompt = _get_executive_prompt("state", "Karnataka")
        assert "State Financial Rules" in prompt or "Treasury Code" in prompt

    def test_local_contains_local_references(self):
        """Local body executive prompt should reference local entities."""
        prompt = _get_executive_prompt("local_body", "Bihar")
        assert "District Collector" in prompt or "BDO" in prompt
        assert "Gram Panchayat" in prompt or "Municipal" in prompt or "PRI" in prompt

    def test_local_contains_panchayat_act_reference(self):
        """Local body executive prompt should reference Panchayat Act."""
        prompt = _get_executive_prompt("local_body", "Chhattisgarh")
        assert "Panchayat Act" in prompt or "Municipal Act" in prompt or "73rd" in prompt

    def test_union_no_state_specific_content(self):
        """Union prompt should not have state-specific content."""
        prompt = _get_executive_prompt("union")
        assert "State PAC" not in prompt
        assert "Government Order" not in prompt
        assert "Chief Secretary" not in prompt


# ═══════════════════════════════════════════════════════════════════════════════
# JOURNALIST PROMPT TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestJournalistPrompt:
    """Tests for tier-specific journalist prompts."""

    def test_union_references_national_papers(self):
        """Union journalist prompt should reference national newspapers."""
        prompt = _get_journalist_prompt("union")
        assert "Hindu" in prompt or "Indian Express" in prompt or "Times of India" in prompt

    def test_state_references_regional_papers(self):
        """State journalist prompt should reference regional newspapers."""
        prompt = _get_journalist_prompt("state", "Uttar Pradesh")
        assert "regional" in prompt.lower() or "state edition" in prompt.lower()

    def test_local_has_grassroots_framing(self):
        """Local body journalist prompt should have grassroots framing."""
        prompt = _get_journalist_prompt("local_body", "Maharashtra", "atir")
        assert "village" in prompt.lower() or "grassroots" in prompt.lower()
        assert "your" in prompt.lower()  # Personal framing

    def test_local_mentions_gram_panchayat(self):
        """Local body journalist prompt should mention Gram Panchayat."""
        prompt = _get_journalist_prompt("local_body", "Odisha")
        assert "Gram Panchayat" in prompt or "GP" in prompt


# ═══════════════════════════════════════════════════════════════════════════════
# SIMPLE PROMPT TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestSimplePrompt:
    """Tests for tier-specific simple prompts."""

    def test_union_has_national_scale_examples(self):
        """Union simple prompt should have national-scale financial examples."""
        prompt = _get_simple_prompt("union")
        # Should have large amounts typical of Union
        assert "₹12,000 Crore" in prompt or "₹10,000 Crore" in prompt or "crore families" in prompt.lower()

    def test_state_has_state_scale_examples(self):
        """State simple prompt should have state-scale financial examples."""
        prompt = _get_simple_prompt("state", "Karnataka")
        assert "state" in prompt.lower()
        # Should reference state-level services
        assert "state hospital" in prompt.lower() or "state" in prompt.lower()

    def test_local_has_local_scale_examples(self):
        """Local body simple prompt should have local-scale financial examples."""
        prompt = _get_simple_prompt("local_body", "Chhattisgarh", "atir")
        # Should have smaller amounts or lakh references
        assert "Lakh" in prompt or "village" in prompt.lower() or "Panchayat" in prompt

    def test_local_explains_abbreviations(self):
        """Local body simple prompt should explain local governance abbreviations."""
        prompt = _get_simple_prompt("local_body", "Bihar")
        assert "GP" in prompt or "Gram Panchayat" in prompt
        assert "BDO" in prompt or "Block Development" in prompt


# ═══════════════════════════════════════════════════════════════════════════════
# DEEP DIVE PROMPT TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeepDivePrompt:
    """Tests for tier-specific deep dive prompts."""

    def test_union_references_cag_act(self):
        """Union deep dive should reference CAG DPC Act."""
        prompt = _get_deep_dive_prompt("union")
        assert "CAG" in prompt
        assert "Article 151" in prompt or "DPC Act" in prompt

    def test_state_references_state_ag(self):
        """State deep dive should reference state AG office."""
        prompt = _get_deep_dive_prompt("state", "Uttarakhand")
        assert "AG" in prompt or "Accountant General" in prompt.lower() or "State" in prompt

    def test_local_references_constitutional_amendments(self):
        """Local body deep dive should reference 73rd/74th amendments."""
        prompt = _get_deep_dive_prompt("local_body", "Mizoram")
        assert "73rd" in prompt or "74th" in prompt or "Constitutional Amendment" in prompt


# ═══════════════════════════════════════════════════════════════════════════════
# POLICY PROMPT TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestPolicyPrompt:
    """Tests for tier-specific policy prompts."""

    def test_union_references_gfr_cvc(self):
        """Union policy prompt should reference GFR/CVC."""
        prompt = _get_policy_prompt("union")
        assert "GFR" in prompt or "CVC" in prompt

    def test_union_references_atn(self):
        """Union policy prompt should reference Action Taken Notes."""
        prompt = _get_policy_prompt("union")
        assert "ATN" in prompt or "Action Taken" in prompt

    def test_state_references_government_orders(self):
        """State policy prompt should reference Government Orders."""
        prompt = _get_policy_prompt("state", "Himachal Pradesh")
        assert "Government Order" in prompt or "GO" in prompt

    def test_local_references_district_collector(self):
        """Local body policy prompt should reference District Collector."""
        prompt = _get_policy_prompt("local_body", "Chhattisgarh")
        assert "District Collector" in prompt or "Collector" in prompt

    def test_local_has_panchayat_resolution_template(self):
        """Local body policy prompt should have Panchayat resolution guidance."""
        prompt = _get_policy_prompt("local_body", "Bihar")
        assert "resolution" in prompt.lower() or "Gram Sabha" in prompt


# ═══════════════════════════════════════════════════════════════════════════════
# OVERVIEW EXTRACTION TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestOverviewExtraction:
    """Tests for tier-specific overview extraction guidance."""

    def test_union_glossary_has_central_terms(self):
        """Union glossary guidance should have central government terms."""
        guidance = _get_glossary_guidance("union")
        assert "CBDT" in guidance or "Ministry" in guidance
        assert "GFR" in guidance

    def test_state_glossary_has_state_terms(self):
        """State glossary guidance should have state-specific terms."""
        guidance = _get_glossary_guidance("state")
        assert "SPSE" in guidance or "GoAP" in guidance or "State" in guidance

    def test_local_glossary_has_local_terms(self):
        """Local body glossary guidance should have local governance terms."""
        guidance = _get_glossary_guidance("local_body")
        assert "GP" in guidance or "Gram Panchayat" in guidance
        assert "ZP" in guidance or "Zilla Parishad" in guidance
        assert "SFC" in guidance

    def test_union_topic_guidance_has_examples(self):
        """Union topic guidance should have appropriate examples."""
        guidance = _get_topic_guidance("union")
        assert "Tax Assessment" in guidance or "Revenue Collection" in guidance

    def test_local_topic_guidance_has_examples(self):
        """Local body topic guidance should have appropriate examples."""
        guidance = _get_topic_guidance("local_body")
        assert "PRI" in guidance or "ULB" in guidance or "Gram Sabha" in guidance

    def test_entity_guidance_varies_by_tier(self):
        """Entity guidance should be different for each tier."""
        union_guidance = _get_entity_guidance("union")
        state_guidance = _get_entity_guidance("state")
        local_guidance = _get_entity_guidance("local_body")

        # Each should have tier-specific content
        assert "Central Ministries" in union_guidance or "PSU" in union_guidance
        assert "State Department" in state_guidance or "SPSE" in state_guidance
        assert "local bodies" in local_guidance.lower() or "PRI" in local_guidance


# ═══════════════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetSummaryPromptIntegration:
    """Integration tests for get_summary_prompt with tier routing."""

    @pytest.fixture
    def union_json_data(self):
        return {
            "report_metadata": {
                "report_title": "Test Union Report",
                "government_body_type": "union",
                "state_name": None,
                "audit_category": "performance",
            }
        }

    @pytest.fixture
    def state_json_data(self):
        return {
            "report_metadata": {
                "report_title": "Test State Report",
                "government_body_type": "state",
                "state_name": "Karnataka",
                "audit_category": "compliance",
            }
        }

    @pytest.fixture
    def local_json_data(self):
        return {
            "report_metadata": {
                "report_title": "Test Local Body Report",
                "government_body_type": "local_body",
                "state_name": "Bihar",
                "audit_category": "atir",
            }
        }

    def test_union_executive_prompt_integration(self, union_json_data):
        """get_summary_prompt should return Union executive prompt for Union report."""
        prompt = get_summary_prompt("executive", "test input", union_json_data)
        assert "Ministry" in prompt or "Central Government" in prompt

    def test_state_executive_prompt_integration(self, state_json_data):
        """get_summary_prompt should return State executive prompt for State report."""
        prompt = get_summary_prompt("executive", "test input", state_json_data)
        assert "Karnataka" in prompt or "State" in prompt

    def test_local_executive_prompt_integration(self, local_json_data):
        """get_summary_prompt should return Local executive prompt for Local report."""
        prompt = get_summary_prompt("executive", "test input", local_json_data)
        assert "Bihar" in prompt or "local" in prompt.lower()

    def test_all_variants_work_for_all_tiers(self, union_json_data, state_json_data, local_json_data):
        """All variants should work for all tiers without errors."""
        for variant in VARIANTS:
            for json_data in [union_json_data, state_json_data, local_json_data]:
                prompt = get_summary_prompt(variant, "test input", json_data)
                assert len(prompt) > 100  # Should return substantial prompt
                assert "{input}" not in prompt  # Should have substituted the input


# ═══════════════════════════════════════════════════════════════════════════════
# REGRESSION TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestNoUnionContentInOtherTiers:
    """Regression tests to ensure Union-specific content doesn't leak."""

    def test_state_executive_no_ministry_secretaries(self):
        """State executive should not reference Ministry secretaries."""
        prompt = _get_executive_prompt("state", "Karnataka")
        assert "Ministry secretaries" not in prompt
        assert "Ministry Secretaries" not in prompt

    def test_local_executive_no_parliamentary(self):
        """Local body executive should not reference Parliamentary committees."""
        prompt = _get_executive_prompt("local_body", "Bihar")
        assert "parliamentary" not in prompt.lower()
        assert "Parliament" not in prompt

    def test_local_simple_no_crore_families(self):
        """Local body simple should not use national-scale '12 crore families' example."""
        prompt = _get_simple_prompt("local_body", "Chhattisgarh", "atir")
        assert "12 crore families" not in prompt

    def test_state_policy_no_gfr(self):
        """State policy should not reference GFR (Central rules)."""
        prompt = _get_policy_prompt("state", "Karnataka")
        # GFR is Union-specific
        assert "GFR 2017" not in prompt
