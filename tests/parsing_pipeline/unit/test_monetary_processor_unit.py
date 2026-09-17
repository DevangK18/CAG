"""
P0-01: Unit tests for MonetaryProcessor fixes.

Tests:
- Indian comma grouping (e.g., ₹2,41,220.26 crore)
- Year-like pattern rejection (e.g., Rs 2003)
- Amount-based deduplication with 5% tolerance
- Explicit-total preference heuristic
- Unit validation at boundaries
"""

import pytest
from src.parsing_pipeline.modules.enrichment.monetary_processor import (
    MonetaryProcessor,
    MonetaryValue,
)


@pytest.fixture
def processor():
    """Create MonetaryProcessor instance."""
    return MonetaryProcessor()


class TestIndianCommaGrouping:
    """Test Indian comma grouping support (P0-01.D)."""

    def test_indian_format_crore(self, processor):
        """Test ₹2,41,220.26 crore format."""
        text = "The expenditure was ₹2,41,220.26 crore during the period."
        values = processor.extract_monetary_values(text)
        assert len(values) == 1
        assert values[0].amount == 241220.26
        assert values[0].unit == "crore"

    def test_western_format_crore(self, processor):
        """Test standard Western comma format ₹241,220.26 crore."""
        text = "The total was ₹241,220.26 crore."
        values = processor.extract_monetary_values(text)
        assert len(values) == 1
        assert values[0].amount == 241220.26

    def test_indian_format_lakh(self, processor):
        """Test ₹5,00,000 (5 lakh) format."""
        text = "Payment of Rs. 5,00,000 lakh was made."
        values = processor.extract_monetary_values(text)
        assert len(values) == 1
        assert values[0].amount == 500000


class TestYearRejection:
    """Test year-like pattern rejection (P0-01.E)."""

    def test_reject_rs_year(self, processor):
        """Test rejection of Rs 2003 as year."""
        text = "In the year Rs 2003 was significant."
        values = processor.extract_monetary_values(text)
        assert len(values) == 0

    def test_reject_rupee_year(self, processor):
        """Test rejection of ₹2024 as year."""
        text = "As per ₹2024 guidelines."
        values = processor.extract_monetary_values(text)
        assert len(values) == 0

    def test_accept_valid_amount(self, processor):
        """Test acceptance of valid amounts near year range."""
        text = "The amount of ₹2003.50 crore was spent."
        values = processor.extract_monetary_values(text)
        assert len(values) == 1
        assert values[0].amount == 2003.50


class TestAmountBasedDedup:
    """Test amount-based deduplication (P0-01.B)."""

    def test_dedup_same_amount_different_format(self, processor):
        """Test dedup of ₹62.76 crore and 62.76 crore."""
        text = "The loss of ₹62.76 crore (Rs. 62.76 crore) was observed."
        values = processor.extract_monetary_values(text)
        # Should only extract one value
        assert len(values) == 1
        assert values[0].amount == pytest.approx(62.76, rel=0.05)

    def test_dedup_within_tolerance(self, processor):
        """Test dedup of amounts within 5% tolerance."""
        text = "The amount was ₹100 crore (approximately ₹102 crore)."
        values = processor.extract_monetary_values(text)
        # 102 is within 5% of 100, should dedup
        assert len(values) == 1

    def test_keep_different_amounts(self, processor):
        """Test keeping distinct amounts."""
        text = "₹10 crore for construction and ₹50 crore for equipment."
        values = processor.extract_monetary_values(text)
        assert len(values) == 2

    def test_keep_same_amount_different_units(self, processor):
        """Test keeping same numeric amount with different units."""
        text = "₹10 crore and ₹10 lakh were allocated."
        values = processor.extract_monetary_values(text)
        assert len(values) == 2


class TestExplicitTotalPreference:
    """Test explicit-total preference heuristic (P0-01.C)."""

    def test_prefer_explicit_total(self, processor):
        """Test preference for explicit total over per-unit amounts."""
        text = (
            "Payment of ₹20,000 per beneficiary was made to 27,801 beneficiaries, "
            "totalling ₹55.60 crore."
        )
        values = processor.extract_monetary_values_with_preference(text)
        # Should prefer the explicit total
        amounts_crore = [v.amount for v in values if v.unit == "crore"]
        assert any(a == pytest.approx(55.60, rel=0.01) for a in amounts_crore)

    def test_identify_per_unit_pattern(self, processor):
        """Test identification of per-unit amounts."""
        text = "₹500 per month per beneficiary"
        # Check that PER_UNIT_PATTERN matches
        assert processor.PER_UNIT_PATTERN.search(text) is not None

    def test_identify_explicit_total(self, processor):
        """Test identification of explicit total amounts."""
        text = "total of ₹100 crore"
        match = processor.EXPLICIT_TOTAL_PATTERN.search(text)
        assert match is not None
        assert match.group(1) == "100"


class TestNormalization:
    """Test normalization to paise."""

    def test_normalize_crore_to_paise(self, processor):
        """Test 1 crore = 10^9 paise."""
        # 1 crore = 10^7 rupees = 10^9 paise
        paise = processor.normalize_to_paise(1.0, "crore")
        assert paise == 1_000_000_000

    def test_normalize_lakh_to_paise(self, processor):
        """Test 1 lakh = 10^7 paise."""
        # 1 lakh = 10^5 rupees = 10^7 paise
        paise = processor.normalize_to_paise(1.0, "lakh")
        assert paise == 10_000_000

    def test_normalize_rupees_to_paise(self, processor):
        """Test 1 rupee = 100 paise."""
        paise = processor.normalize_to_paise(1.0, None)
        assert paise == 100


class TestValidation:
    """Test unit validation at boundaries (P0-01.F)."""

    def test_validate_negative_raises(self, processor):
        """Test that negative values raise assertion."""
        with pytest.raises(AssertionError):
            processor._validate_monetary_value(-100, "test")

    def test_validate_non_int_raises(self, processor):
        """Test that non-integer values raise assertion."""
        with pytest.raises(AssertionError):
            processor._validate_monetary_value(100.5, "test")

    def test_validate_large_value_logs_warning(self, processor, caplog):
        """Test that implausibly large values log warning."""
        import logging
        caplog.set_level(logging.WARNING)
        # This is larger than ₹1 lakh crore in paise
        processor._validate_monetary_value(int(1e18), "test")
        assert "Implausibly large" in caplog.text


class TestIntegration:
    """Integration tests for monetary extraction."""

    def test_real_finding_text(self, processor):
        """Test extraction from realistic CAG finding text."""
        text = """
        Audit observed that the department made payment of ₹20,000 per beneficiary
        to 27,801 beneficiaries during 2021-22, amounting to ₹55.60 crore. However,
        verification revealed that only 15,000 beneficiaries were eligible, resulting
        in excess payment of ₹25.60 crore.
        """
        values = processor.extract_monetary_values_with_preference(text)

        # Should extract crore amounts
        crore_amounts = sorted([v.amount for v in values if v.unit == "crore"])
        assert 25.60 in crore_amounts or any(
            a == pytest.approx(25.60, rel=0.01) for a in crore_amounts
        )
        assert 55.60 in crore_amounts or any(
            a == pytest.approx(55.60, rel=0.01) for a in crore_amounts
        )

    def test_multiple_units(self, processor):
        """Test extraction of amounts in different units."""
        text = "₹50 crore for infrastructure and ₹25 lakh for maintenance."
        values = processor.extract_monetary_values(text)
        assert len(values) == 2

        units = {v.unit for v in values}
        assert "crore" in units
        assert "lakh" in units
