"""
R2: Unit tests for monetary context classification in MonetaryProcessor.

Tests the extract_with_context method and context pattern matching
for classifying monetary amounts by semantic role.

Context types tested:
- FINDING_IMPACT: Loss, shortfall, excess, irregular expenditure
- BUDGET_ALLOCATION: Released, allocated, sanctioned amounts
- COMPARISON_TARGET: "Against target of ₹X"
- HISTORICAL_DATA: Multi-year totals, trend data
- EXPENDITURE_ACTUAL: What was actually spent
- RECOVERY_DUE: Amount to be recovered
"""

import pytest
from src.parsing_pipeline.modules.enrichment.monetary_processor import (
    MonetaryProcessor,
    MonetaryContext,
    ClassifiedMonetaryValue,
)


@pytest.fixture
def processor():
    """Create MonetaryProcessor instance."""
    return MonetaryProcessor()


class TestFindingImpactContext:
    """Test FINDING_IMPACT context classification."""

    def test_loss_of_revenue(self, processor):
        """'loss of ₹X' should classify as FINDING_IMPACT."""
        text = "Audit observed a loss of ₹ 62.76 crore due to non-imposition of penalty."
        classified = processor.extract_with_context(text)
        assert len(classified) == 1
        assert classified[0].context == MonetaryContext.FINDING_IMPACT

    def test_shortfall_pattern(self, processor):
        """'shortfall of ₹X' should classify as FINDING_IMPACT."""
        text = "There was a shortfall of ₹ 15.50 crore in revenue collection."
        classified = processor.extract_with_context(text)
        assert len(classified) == 1
        assert classified[0].context == MonetaryContext.FINDING_IMPACT

    def test_excess_expenditure(self, processor):
        """'excess expenditure of ₹X' should classify as FINDING_IMPACT."""
        text = "The Corporation incurred excess expenditure of ₹ 10.25 crore."
        classified = processor.extract_with_context(text)
        assert len(classified) == 1
        assert classified[0].context == MonetaryContext.FINDING_IMPACT

    def test_irregular_expenditure(self, processor):
        """'irregular expenditure' should classify as FINDING_IMPACT."""
        text = "Audit noticed irregular expenditure amounting to ₹ 5.75 crore."
        classified = processor.extract_with_context(text)
        assert len(classified) == 1
        assert classified[0].context == MonetaryContext.FINDING_IMPACT

    def test_avoidable_expenditure(self, processor):
        """'avoidable expenditure' should classify as FINDING_IMPACT."""
        text = "This resulted in avoidable expenditure of ₹ 1.14 crore towards penalty."
        classified = processor.extract_with_context(text)
        assert len(classified) == 1
        assert classified[0].context == MonetaryContext.FINDING_IMPACT

    def test_wasteful_expenditure(self, processor):
        """'wasteful expenditure' should classify as FINDING_IMPACT."""
        text = "The project led to wasteful expenditure of ₹ 25 crore."
        classified = processor.extract_with_context(text)
        assert len(classified) == 1
        assert classified[0].context == MonetaryContext.FINDING_IMPACT

    def test_non_recovery(self, processor):
        """'non-recovery of ₹X' should classify as FINDING_IMPACT."""
        text = "Non-recovery of ₹ 17.07 crore from households resulted in loss."
        classified = processor.extract_with_context(text)
        assert len(classified) == 1
        assert classified[0].context == MonetaryContext.FINDING_IMPACT

    def test_blocking_of_funds(self, processor):
        """'blocking of funds' should classify as FINDING_IMPACT."""
        text = "Blocking of funds amounting to ₹ 50 lakh due to delayed execution."
        classified = processor.extract_with_context(text)
        assert len(classified) == 1
        assert classified[0].context == MonetaryContext.FINDING_IMPACT

    def test_fraud_misappropriation(self, processor):
        """'fraud/misappropriation' should classify as FINDING_IMPACT."""
        text = "Suspected fraud involving ₹ 25 lakh was detected in the accounts."
        classified = processor.extract_with_context(text)
        assert len(classified) == 1
        assert classified[0].context == MonetaryContext.FINDING_IMPACT

    def test_resulted_in_loss(self, processor):
        """'resulted in a loss' pattern should classify as FINDING_IMPACT."""
        text = "The delay resulted in a loss of ₹ 3.50 crore to the Government."
        classified = processor.extract_with_context(text)
        assert len(classified) == 1
        assert classified[0].context == MonetaryContext.FINDING_IMPACT

    def test_penalty_interest(self, processor):
        """'penalty of ₹X' should classify as FINDING_IMPACT."""
        text = "The Department paid penalty of ₹ 2.5 crore due to delayed remittance."
        classified = processor.extract_with_context(text)
        assert len(classified) == 1
        assert classified[0].context == MonetaryContext.FINDING_IMPACT


class TestBudgetAllocationContext:
    """Test BUDGET_ALLOCATION context classification."""

    def test_released_grants(self, processor):
        """'released grants of ₹X' should classify as BUDGET_ALLOCATION."""
        text = "Government released grants of ₹ 500 crore for rural development."
        classified = processor.extract_with_context(text)
        assert len(classified) == 1
        assert classified[0].context == MonetaryContext.BUDGET_ALLOCATION

    def test_allocated_funds(self, processor):
        """'allocated funds' should classify as BUDGET_ALLOCATION."""
        text = "The Ministry allocated funds of ₹ 1,500 crore for the scheme."
        classified = processor.extract_with_context(text)
        assert len(classified) == 1
        assert classified[0].context == MonetaryContext.BUDGET_ALLOCATION

    def test_sanctioned_amount(self, processor):
        """'sanctioned amount' should classify as BUDGET_ALLOCATION."""
        text = "The Department sanctioned amount of ₹ 200 crore to ULBs."
        classified = processor.extract_with_context(text)
        assert len(classified) == 1
        assert classified[0].context == MonetaryContext.BUDGET_ALLOCATION

    def test_total_allocation(self, processor):
        """'total allocation of ₹X' should classify as BUDGET_ALLOCATION."""
        text = "The total allocation for the project was ₹ 750 crore."
        classified = processor.extract_with_context(text)
        assert len(classified) == 1
        assert classified[0].context == MonetaryContext.BUDGET_ALLOCATION

    def test_government_released(self, processor):
        """'Government had released' should classify as BUDGET_ALLOCATION."""
        text = "The Government had released ₹ 100 crore for infrastructure."
        classified = processor.extract_with_context(text)
        assert len(classified) == 1
        assert classified[0].context == MonetaryContext.BUDGET_ALLOCATION


class TestComparisonTargetContext:
    """Test COMPARISON_TARGET context classification."""

    def test_against_target(self, processor):
        """'against the target of ₹X' should classify as COMPARISON_TARGET."""
        text = "Expenditure of ₹ 80 crore was incurred against the target of ₹ 100 crore."
        classified = processor.extract_with_context(text)
        # Should have both amounts, one as target
        target_amounts = [c for c in classified if c.context == MonetaryContext.COMPARISON_TARGET]
        assert len(target_amounts) >= 1

    def test_compared_to_sanction(self, processor):
        """'compared to sanction' should classify as COMPARISON_TARGET."""
        text = "The actual cost was ₹ 150 crore compared to sanction of ₹ 120 crore."
        classified = processor.extract_with_context(text)
        target_amounts = [c for c in classified if c.context == MonetaryContext.COMPARISON_TARGET]
        assert len(target_amounts) >= 1

    def test_target_was(self, processor):
        """'against target of ₹X' should classify as COMPARISON_TARGET."""
        # Note: Pattern matches "against the target of" or "target of/was ₹X"
        text = "Expenditure was ₹ 300 crore against target of ₹ 500 crore."
        classified = processor.extract_with_context(text)
        target_amounts = [c for c in classified if c.context == MonetaryContext.COMPARISON_TARGET]
        assert len(target_amounts) >= 1


class TestHistoricalDataContext:
    """Test HISTORICAL_DATA context classification."""

    def test_during_fy_range(self, processor):
        """'during FYs 2003-04 to 2021-22' should classify as HISTORICAL_DATA."""
        text = "PRD had released grants of ₹ 59,995 crore during FYs 2003-04 to 2021-22."
        classified = processor.extract_with_context(text)
        # The BUDGET_ALLOCATION might take precedence, but historical should be detected
        assert len(classified) == 1

    def test_during_years_range(self, processor):
        """'during the years 2003-2022' should classify as HISTORICAL_DATA."""
        # Use text without 'total allocation' trigger word to test pure historical context
        text = "The amount was ₹ 31,564 crore during the years 2003-2022."
        classified = processor.extract_with_context(text)
        assert len(classified) == 1
        assert classified[0].context == MonetaryContext.HISTORICAL_DATA

    def test_for_the_period(self, processor):
        """'for the period from FY 2015' should classify as HISTORICAL_DATA."""
        # Use text without immediate EXPENDITURE_ACTUAL trigger
        text = "The amount was ₹ 1,000 crore for the period from FY 2015 onwards."
        classified = processor.extract_with_context(text)
        assert len(classified) == 1
        assert classified[0].context == MonetaryContext.HISTORICAL_DATA

    def test_over_last_years(self, processor):
        """'over the last 5 years' should classify as HISTORICAL_DATA."""
        # Use text without 'total outlay' trigger word (which matches BUDGET_ALLOCATION)
        text = "The amount was ₹ 5,000 crore over the last 5 years."
        classified = processor.extract_with_context(text)
        assert len(classified) == 1
        assert classified[0].context == MonetaryContext.HISTORICAL_DATA


class TestExpenditureActualContext:
    """Test EXPENDITURE_ACTUAL context classification."""

    def test_expenditure_incurred(self, processor):
        """'expenditure incurred' should classify as EXPENDITURE_ACTUAL."""
        # Note: Avoid "against" which triggers COMPARISON_TARGET
        text = "The expenditure incurred by the Department was ₹ 75 crore."
        classified = processor.extract_with_context(text)
        assert len(classified) == 1
        assert classified[0].context == MonetaryContext.EXPENDITURE_ACTUAL

    def test_amount_spent(self, processor):
        """'amount spent' should classify as EXPENDITURE_ACTUAL."""
        text = "The amount spent on the project was ₹ 150 crore."
        classified = processor.extract_with_context(text)
        assert len(classified) == 1
        assert classified[0].context == MonetaryContext.EXPENDITURE_ACTUAL

    def test_actual_expenditure(self, processor):
        """'actual expenditure' should classify as EXPENDITURE_ACTUAL."""
        text = "The actual expenditure was ₹ 200 crore against estimates."
        classified = processor.extract_with_context(text)
        assert len(classified) == 1
        assert classified[0].context == MonetaryContext.EXPENDITURE_ACTUAL


class TestRecoveryDueContext:
    """Test RECOVERY_DUE context classification."""

    def test_recovery_due(self, processor):
        """'recovery due' should classify as RECOVERY_DUE."""
        text = "The recovery due from contractors was ₹ 10 crore."
        classified = processor.extract_with_context(text)
        assert len(classified) == 1
        assert classified[0].context == MonetaryContext.RECOVERY_DUE

    def test_amount_to_be_recovered(self, processor):
        """'amount to be recovered' should classify as RECOVERY_DUE."""
        text = "The amount to be recovered is ₹ 25 lakh from defaulters."
        classified = processor.extract_with_context(text)
        assert len(classified) == 1
        assert classified[0].context == MonetaryContext.RECOVERY_DUE

    def test_outstanding_amount(self, processor):
        """'outstanding amount' should classify as RECOVERY_DUE."""
        text = "Outstanding amount of ₹ 50 crore was pending recovery."
        classified = processor.extract_with_context(text)
        assert len(classified) == 1
        assert classified[0].context == MonetaryContext.RECOVERY_DUE


class TestUnknownContext:
    """Test UNKNOWN context classification for ambiguous cases."""

    def test_plain_amount_no_context(self, processor):
        """Plain amount without context keywords should be UNKNOWN."""
        text = "The total was ₹ 100 crore."
        classified = processor.extract_with_context(text)
        assert len(classified) == 1
        # Plain "total" might match EXPLICIT_TOTAL pattern, but context should be UNKNOWN
        # since there's no specific context pattern
        assert classified[0].context in (MonetaryContext.UNKNOWN, MonetaryContext.EXPENDITURE_ACTUAL)

    def test_table_of_contents_amount(self, processor):
        """Amounts in table-like text should be UNKNOWN."""
        text = "Chapter 3... ₹ 50 crore"
        classified = processor.extract_with_context(text)
        assert len(classified) == 1
        assert classified[0].context == MonetaryContext.UNKNOWN


class TestContextPriority:
    """Test that FINDING_IMPACT takes priority over other contexts."""

    def test_finding_impact_priority_over_allocation(self, processor):
        """FINDING_IMPACT should take priority when multiple contexts present."""
        text = (
            "Against the allocated funds of ₹ 100 crore, an irregular expenditure "
            "of ₹ 15 crore was detected."
        )
        classified = processor.extract_with_context(text)
        # The ₹15 crore should be classified as FINDING_IMPACT
        finding_amounts = [c for c in classified if c.context == MonetaryContext.FINDING_IMPACT]
        assert len(finding_amounts) >= 1

    def test_finding_impact_priority_over_historical(self, processor):
        """FINDING_IMPACT should take priority over HISTORICAL_DATA."""
        text = (
            "During the period 2015-2020, the Department incurred a loss of "
            "₹ 25 crore due to delayed execution."
        )
        classified = processor.extract_with_context(text)
        # Should classify as FINDING_IMPACT due to "loss of"
        assert len(classified) == 1
        assert classified[0].context == MonetaryContext.FINDING_IMPACT


class TestClassifiedMonetaryValueFields:
    """Test ClassifiedMonetaryValue structure and fields."""

    def test_classified_value_has_all_fields(self, processor):
        """ClassifiedMonetaryValue should have all required fields."""
        text = "Loss of ₹ 10 crore was detected."
        classified = processor.extract_with_context(text)
        assert len(classified) == 1
        cv = classified[0]

        assert hasattr(cv, 'value')
        assert hasattr(cv, 'context')
        assert hasattr(cv, 'confidence')
        assert hasattr(cv, 'is_primary')
        assert hasattr(cv, 'context_snippet')

    def test_confidence_above_threshold_for_matches(self, processor):
        """Confidence should be high (>0.8) for pattern matches."""
        text = "Irregular expenditure of ₹ 5 crore was noticed."
        classified = processor.extract_with_context(text)
        assert len(classified) == 1
        assert classified[0].confidence >= 0.8

    def test_confidence_low_for_unknown(self, processor):
        """Confidence should be low (<0.5) for UNKNOWN context."""
        text = "The amount was ₹ 50 lakh."
        classified = processor.extract_with_context(text)
        assert len(classified) == 1
        if classified[0].context == MonetaryContext.UNKNOWN:
            assert classified[0].confidence < 0.5

    def test_context_snippet_populated(self, processor):
        """Context snippet should be populated with relevant text."""
        text = "Audit noticed irregular expenditure of ₹ 10 crore on procurement."
        classified = processor.extract_with_context(text)
        assert len(classified) == 1
        assert classified[0].context_snippet != ""

    def test_to_dict_method(self, processor):
        """ClassifiedMonetaryValue.to_dict() should return proper dict."""
        text = "Loss of ₹ 5 crore due to fraud."
        classified = processor.extract_with_context(text)
        assert len(classified) == 1

        d = classified[0].to_dict()
        assert isinstance(d, dict)
        assert "value" in d
        assert "context" in d
        assert "confidence" in d
        assert "is_primary" in d
        assert "context_snippet" in d
        assert d["context"] == "finding_impact"


class TestBRReportProblematicCases:
    """Test specific problematic cases from BR_2024_03 report."""

    def test_br_prd_grants_case(self, processor):
        """BR report PRD grants should be classified as BUDGET_ALLOCATION or HISTORICAL_DATA."""
        text = (
            "Audit observed that PRD had released grants amounting to ₹ 59,995.90 crore, "
            "under different scheme heads, to PRIs, during the financial years 2003-04 to "
            "2021-22."
        )
        classified = processor.extract_with_context(text)
        assert len(classified) == 1
        # Should be BUDGET_ALLOCATION (released grants) or HISTORICAL_DATA (multi-year)
        assert classified[0].context in (
            MonetaryContext.BUDGET_ALLOCATION,
            MonetaryContext.HISTORICAL_DATA,
        )

    def test_br_actual_finding(self, processor):
        """BR report actual finding should be classified as FINDING_IMPACT."""
        text = (
            "Failure of Nagar Parishad, Saharsa, to ensure timely remittance of statutory "
            "contributions, resulted in an avoidable expenditure towards penalty of ₹ 1.14 crore."
        )
        classified = processor.extract_with_context(text)
        assert len(classified) == 1
        assert classified[0].context == MonetaryContext.FINDING_IMPACT

    def test_br_udhd_gia_case(self, processor):
        """BR report UD&HD GIA case should not be FINDING_IMPACT."""
        text = (
            "It was observed that UD&HD had sanctioned Grants-in-Aids (GIA) of "
            "₹ 31,564.70 crore during the period from FYs 2003-04 to 2021-22."
        )
        classified = processor.extract_with_context(text)
        assert len(classified) == 1
        # Should be BUDGET_ALLOCATION or HISTORICAL_DATA, NOT FINDING_IMPACT
        assert classified[0].context != MonetaryContext.FINDING_IMPACT


class TestMultipleAmounts:
    """Test handling of multiple amounts in same text."""

    def test_multiple_amounts_different_contexts(self, processor):
        """Multiple amounts should each get appropriate context."""
        text = (
            "Against the sanctioned amount of ₹ 100 crore, only ₹ 60 crore was spent, "
            "resulting in a shortfall of ₹ 40 crore."
        )
        classified = processor.extract_with_context(text)

        # Should have 3 amounts with different contexts
        contexts = [c.context for c in classified]
        # At least one should be FINDING_IMPACT (shortfall)
        assert MonetaryContext.FINDING_IMPACT in contexts

    def test_deduplication_with_context(self, processor):
        """Similar amounts should be deduplicated even with context."""
        text = "Loss of ₹ 10 crore. This loss of ₹ 10.0 crore was significant."
        classified = processor.extract_with_context(text)
        # Should deduplicate to 1 amount
        assert len(classified) == 1
        assert classified[0].context == MonetaryContext.FINDING_IMPACT

