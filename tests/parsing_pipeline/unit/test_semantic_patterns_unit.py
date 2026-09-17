"""
Unit tests for P1-2: Enhanced Semantic Patterns (semantic_patterns.py)

Tests pattern matching, confidence scoring, and finding detection.
"""

import pytest
from src.parsing_pipeline.modules import semantic_patterns


class TestExplicitPatternMatching:
    """Test explicit finding pattern matching."""

    def setup_method(self):
        """Set up test fixtures."""
        self.matcher = semantic_patterns.SemanticPatternMatcher()

    def test_audit_revealed_pattern(self):
        """Test matching of 'audit revealed' patterns."""
        text = "Audit revealed that expenditure of ₹847.71 crore was irregular."
        matches = self.matcher.match_patterns(text)

        assert len(matches) > 0
        audit_matches = [m for m in matches if m.pattern_type == "audit_revealed"]
        assert len(audit_matches) > 0
        assert audit_matches[0].category == "explicit"

    def test_non_compliance_pattern(self):
        """Test matching of non-compliance patterns."""
        text = "The payment was made in violation of GFR Rule 123."
        matches = self.matcher.match_patterns(text)

        assert len(matches) > 0
        nc_matches = [m for m in matches if m.pattern_type == "non_compliance"]
        assert len(nc_matches) > 0
        assert nc_matches[0].category == "explicit"

    def test_loss_damage_pattern(self):
        """Test matching of loss/damage patterns."""
        text = "This resulted in loss of ₹45.23 lakh due to avoidable expenditure."
        matches = self.matcher.match_patterns(text)

        assert len(matches) > 0
        loss_matches = [m for m in matches if m.pattern_type == "loss_damage"]
        assert len(loss_matches) > 0


class TestImplicitPatternMatching:
    """Test implicit finding pattern matching."""

    def setup_method(self):
        """Set up test fixtures."""
        self.matcher = semantic_patterns.SemanticPatternMatcher()

    def test_variance_issue_pattern(self):
        """Test matching of variance issue patterns."""
        text = "The actual expenditure was higher than budget by ₹25.5 crore, showing a variance of 15%."
        matches = self.matcher.match_patterns(text)

        variance_matches = [m for m in matches if m.pattern_type == "variance_issue"]
        assert len(variance_matches) > 0
        assert variance_matches[0].category == "implicit"

    def test_target_miss_pattern(self):
        """Test matching of target miss patterns."""
        text = "Against the target of 1000 units, achievement was only 450 units (45%)."
        matches = self.matcher.match_patterns(text)

        target_matches = [m for m in matches if m.pattern_type == "target_miss"]
        assert len(target_matches) > 0
        assert target_matches[0].category == "implicit"

    def test_procedural_lapse_pattern(self):
        """Test matching of procedural lapse patterns."""
        text = "Payment was made without proper approval from competent authority."
        matches = self.matcher.match_patterns(text)

        proc_matches = [m for m in matches if m.pattern_type == "procedural_lapse"]
        assert len(proc_matches) > 0
        assert proc_matches[0].category == "implicit"

    def test_pending_issue_pattern(self):
        """Test matching of pending issue patterns."""
        text = "The case has been pending for more than 3 years without resolution."
        matches = self.matcher.match_patterns(text)

        pending_matches = [m for m in matches if m.pattern_type == "pending_issue"]
        assert len(pending_matches) > 0

    def test_delay_issue_pattern(self):
        """Test matching of delay issue patterns."""
        text = "The project was delayed by 18 months, resulting in cost overruns."
        matches = self.matcher.match_patterns(text)

        delay_matches = [m for m in matches if m.pattern_type == "delay_issue"]
        assert len(delay_matches) > 0

    def test_system_weakness_pattern(self):
        """Test matching of system weakness patterns."""
        text = "Absence of monitoring mechanism led to systemic deficiencies in the process."
        matches = self.matcher.match_patterns(text)

        system_matches = [m for m in matches if m.pattern_type == "system_weakness"]
        assert len(system_matches) > 0


class TestConfidenceScoring:
    """Test confidence score calculation."""

    def setup_method(self):
        """Set up test fixtures."""
        self.matcher = semantic_patterns.SemanticPatternMatcher()

    def test_high_confidence_explicit_with_monetary(self):
        """Test high confidence for explicit pattern + monetary value."""
        text = "Audit revealed irregular expenditure of ₹847.71 crore in violation of GFR Rule 123."
        matches = self.matcher.match_patterns(text)
        confidence = self.matcher.calculate_finding_confidence(text, matches, "compliance")

        assert confidence >= 0.7, f"Expected high confidence, got {confidence}"

    def test_medium_confidence_implicit_with_monetary(self):
        """Test medium confidence for implicit pattern + monetary value."""
        text = "The audit revealed a variance of ₹25.5 crore which was higher than the approved budget allocation for the scheme implementation during fiscal year 2022-23."
        matches = self.matcher.match_patterns(text)
        confidence = self.matcher.calculate_finding_confidence(text, matches, "compliance")

        assert 0.4 <= confidence, f"Expected medium confidence (>= 0.4), got {confidence}"

    def test_lower_confidence_implicit_without_monetary(self):
        """Test lower confidence for implicit pattern without monetary value."""
        text = "The target was not achieved and remained below expectations."
        matches = self.matcher.match_patterns(text)
        confidence = self.matcher.calculate_finding_confidence(text, matches, "performance")

        assert confidence < 0.6, f"Expected lower confidence, got {confidence}"

    def test_report_type_boost_compliance(self):
        """Test that compliance report type boosts confidence."""
        text = "Audit revealed non-compliance with Rule 123, involving ₹10 crore."
        matches = self.matcher.match_patterns(text)

        confidence_compliance = self.matcher.calculate_finding_confidence(
            text, matches, "compliance"
        )
        confidence_general = self.matcher.calculate_finding_confidence(
            text, matches, "general"
        )

        assert confidence_compliance > confidence_general, (
            f"Compliance boost not applied: {confidence_compliance} vs {confidence_general}"
        )

    def test_supporting_context_boost(self):
        """Test that supporting context increases confidence."""
        # Text with rule reference and ministry mention
        text_with_context = (
            "Ministry of Railways violated GFR Rule 123, "
            "resulting in loss of ₹847.71 crore as per Para 3.2 and Table 4.5."
        )

        # Text without context
        text_without_context = "There was a loss of ₹847.71 crore."

        matches_with = self.matcher.match_patterns(text_with_context)
        matches_without = self.matcher.match_patterns(text_without_context)

        confidence_with = self.matcher.calculate_finding_confidence(
            text_with_context, matches_with, "compliance"
        )
        confidence_without = self.matcher.calculate_finding_confidence(
            text_without_context, matches_without, "compliance"
        )

        # Context should provide boost
        assert confidence_with > confidence_without + 0.05, (
            f"Context boost not applied: {confidence_with} vs {confidence_without}"
        )

    def test_short_text_penalty(self):
        """Test that very short text gets penalized."""
        short_text = "Audit revealed loss."
        long_text = "Audit revealed that there was an irregular loss of ₹25 crore due to violation of Rule 123 by the department."

        matches_short = self.matcher.match_patterns(short_text)
        matches_long = self.matcher.match_patterns(long_text)

        confidence_short = self.matcher.calculate_finding_confidence(
            short_text, matches_short, "compliance"
        )
        confidence_long = self.matcher.calculate_finding_confidence(
            long_text, matches_long, "compliance"
        )

        # Longer text should have higher confidence
        assert confidence_long > confidence_short

    def test_zero_confidence_for_very_short(self):
        """Test zero confidence for text below minimum length."""
        text = "Loss"
        matches = self.matcher.match_patterns(text)
        confidence = self.matcher.calculate_finding_confidence(
            text, matches, "compliance", min_text_length=50
        )

        assert confidence == 0.0


class TestFindingDetection:
    """Test is_finding method."""

    def setup_method(self):
        """Set up test fixtures."""
        self.matcher = semantic_patterns.SemanticPatternMatcher()

    def test_is_finding_explicit_high_confidence(self):
        """Test that explicit findings are detected."""
        text = "Audit revealed that expenditure of ₹847.71 crore was irregular and violated GFR Rule 56."
        is_finding, confidence, matches = self.matcher.is_finding(text, "compliance", 0.5)

        assert is_finding, f"Should detect as finding (confidence: {confidence})"
        assert confidence >= 0.5
        assert len(matches) > 0

    def test_is_finding_implicit_medium_confidence(self):
        """Test that implicit findings with good confidence are detected."""
        text = "The actual expenditure was ₹125 crore against budget of ₹100 crore, showing an excess of ₹25 crore."
        is_finding, confidence, matches = self.matcher.is_finding(text, "compliance", 0.4)

        assert is_finding, f"Should detect as finding (confidence: {confidence})"
        assert len(matches) > 0

    def test_not_finding_low_confidence(self):
        """Test that low confidence text is not detected as finding."""
        text = "The department submitted their report on time."
        is_finding, confidence, matches = self.matcher.is_finding(text, "general", 0.5)

        assert not is_finding, f"Should not detect as finding (confidence: {confidence})"

    def test_threshold_customization(self):
        """Test custom confidence threshold."""
        text = "There was a minor variance in the accounts."
        matches = self.matcher.match_patterns(text)
        confidence = self.matcher.calculate_finding_confidence(text, matches, "financial")

        # Should pass with low threshold
        is_finding_low, _, _ = self.matcher.is_finding(text, "financial", 0.2)
        # Should fail with high threshold
        is_finding_high, _, _ = self.matcher.is_finding(text, "financial", 0.8)

        if confidence < 0.8:
            assert is_finding_low or confidence < 0.2
            assert not is_finding_high


class TestPatternCategories:
    """Test pattern category helpers."""

    def setup_method(self):
        """Set up test fixtures."""
        self.matcher = semantic_patterns.SemanticPatternMatcher()

    def test_get_pattern_categories(self):
        """Test pattern category counting."""
        text = "Audit revealed non-compliance. The variance of ₹25 crore was not explained."
        matches = self.matcher.match_patterns(text)

        categories = self.matcher.get_pattern_categories(matches)

        assert "explicit" in categories
        assert "implicit" in categories
        assert categories["explicit"] >= 1  # "audit revealed", "non-compliance"
        assert categories["implicit"] >= 1  # "variance"


class TestConvenienceFunctions:
    """Test convenience functions."""

    def test_create_matcher(self):
        """Test matcher creation."""
        matcher = semantic_patterns.create_matcher()
        assert isinstance(matcher, semantic_patterns.SemanticPatternMatcher)

    def test_is_finding_convenience(self):
        """Test convenience is_finding function."""
        text = "Audit revealed irregular expenditure of ₹100 crore."
        is_finding_bool, confidence = semantic_patterns.is_finding(text, "compliance", 0.5)

        assert isinstance(is_finding_bool, bool)
        assert isinstance(confidence, float)
        assert 0.0 <= confidence <= 1.0


class TestEdgeCases:
    """Test edge cases and error handling."""

    def setup_method(self):
        """Set up test fixtures."""
        self.matcher = semantic_patterns.SemanticPatternMatcher()

    def test_empty_text(self):
        """Test handling of empty text."""
        matches = self.matcher.match_patterns("")
        assert len(matches) == 0

        confidence = self.matcher.calculate_finding_confidence("", [], "general")
        assert confidence == 0.0

    def test_very_long_text(self):
        """Test handling of very long text."""
        long_text = "Audit revealed irregular expenditure. " * 100
        matches = self.matcher.match_patterns(long_text)
        confidence = self.matcher.calculate_finding_confidence(
            long_text, matches, "compliance"
        )

        assert confidence > 0.0
        assert confidence <= 1.0

    def test_unicode_text(self):
        """Test handling of Unicode text with Indian currency symbols."""
        text = "ऑडिट में पाया गया कि ₹847.71 करोड़ का अनियमित व्यय था।"
        matches = self.matcher.match_patterns(text)
        # Should still match monetary pattern
        confidence = self.matcher.calculate_finding_confidence(text, matches, "compliance")
        assert confidence >= 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
