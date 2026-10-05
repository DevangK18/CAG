"""
Money parsing harness (PR 6, section 4: M1-M17, P9-04, P9-05).

- HARNESS: the 27 edge cases from the Step 2 monetary deep dive. "Rs 50 thousand"
  is 0.005 crore (the original harness expected 0.0005, which was wrong).
- Real strings from the gold labels (docs/pipeline-review/gold-labels/*.json,
  `impact_amount` / `other_amounts`) and from the review corpus, where the old
  parser read quantities, footnote digits or "lakh crore" wrongly, or picked the
  wrong impact amount.
"""

import pytest

from src.core.data_contracts import Finding, MonetaryValue as MonetaryValueModel
from src.parsing_pipeline.modules.enrichment.finding_extractor import FindingExtractor
from src.parsing_pipeline.modules.enrichment.monetary_processor import (
    MonetaryContext,
    MonetaryProcessor,
    MonetaryValue,
)

CRORE = 10**9  # paise


@pytest.fixture(scope="module")
def mp():
    return MonetaryProcessor()


def crores(values):
    """Rupee amounts in crore; dollar amounts have no rupee value."""
    return sorted(round(v.normalized_paise / CRORE, 6) for v in values if v.currency == "INR")


# (text, expected amounts in crore)
HARNESS = [
    ("₹847.71 crore", [847.71]),
    ("Rs. 5,00,000", [0.05]),
    ("₹ 2,41,220.26 crore", [241220.26]),
    ("₹1.5 lakh crore", [150000]),
    ("₹ 2.25 lakh crore was borrowed", [225000]),
    ("USD 5 million (₹ 41 crore)", [41]),
    ("a grant of $2 million", []),
    ("₹ 3 billion", [300]),
    ("1.73 lakh (six per cent) students", []),
    ("24.53 lakh certified candidates", []),
    ("65.71 lakh sqm of space", []),
    ("4.98 lakh sq. ft.", []),
    ("The members 25 said", []),
    ("in 12 years 1,500 teachers", []),
    ("for 3 hours 45 minutes", []),
    ("ranging from ₹5 to ₹10 crore", [5, 10]),
    ("between ₹ 2.5 and 4.0 crore", [2.5, 4.0]),
    ("` 15.25 crore", [15.25]),
    ("₹10.2 crore and ₹10.5 crore were paid", [10.2, 10.5]),
    ("₹ 1,00,000 and ₹1 lakh", [0.01, 0.01]),
    ("₹ 25,208.86 crore, of which ₹15,668.71 crore", [25208.86, 15668.71]),
    ("Rs.2003 crore", [2003]),
    ("₹2024 crore were released in 2024", [2024]),
    ("₹ in crore", []),
    ("expenditure of ₹ 45.67 lakh", [0.4567]),
    ("INR 300 crore", [300]),
    ("Rs 50 thousand", [0.005]),
]


@pytest.mark.parametrize("text,expected", HARNESS, ids=[t for t, _ in HARNESS])
def test_harness(mp, text, expected):
    assert crores(mp.extract_monetary_values(text)) == sorted(expected)


def test_harness_has_27_cases():
    assert len(HARNESS) == 27


class TestRealStrings:
    """Strings from the gold labels and the review corpus that the old parser got wrong."""

    @pytest.mark.parametrize("text", [
        # OD_2025_05 F013 / F015 / F056 / F205 / F143 (gold): counts, not rupees (M3)
        "3.51 lakh eligible students were deprived of free uniforms",
        "1.73 lakh (six per cent) students were deprived of bicycle incentives in the State.",
        "of 23.61 lakh students enrolled in Class X, 2.74 lakh (12 per cent) students did not appear",
        "TBP&M printed 1,228.26 lakh books and supplied 1,223.54 lakh books with a shortfall of "
        "94.46 lakh (seven per cent) against the requirement",
        "against the target of providing in-service trainings to 7.47 lakh teachers, "
        "6.41 lakh teachers could be provided trainings",
        "During 2018-23, 1.50 lakh to 5.47 lakh children enrolled in Classes I to XII",
        # BR_2024_03 F192 / F193 (gold): tonnes and cubic metres
        "a total of 14.04 lakh tonnes of legacy waste had been",
        "generated in the ULB, was 10.08 lakh cubic metres. Out of this, 6.88 lakh (68 per cent) "
        "cubic metres had",
        # 2025_20 / 2023_19 (corpus findings)
        "were successful for only 17.69 lakh candidates (18.44 per cent)",
        "only a negligible quantity of 0.28 lakh cubic meter of fly ash was used",
        # Footnote digits glued to words read as "Rs <n>" (M4): 2025_08 F077,
        # OD F049 / F163 (gold), 2020_16 / 2025_18 (corpus)
        "a wide range of parameters42 and capable of transmitting",
        "as discussed in Chapters 5 and 6 of this Report",
        "trainings to 7.47 lakh teachers44, 6.41 lakh teachers could be provided",
        "data of Income Tax Returns (ITRs9) assessed during FYs 2014-15",
        "the corresponding years17 carried a Statement",
    ])
    def test_no_amount(self, mp, text):
        assert mp.extract_monetary_values(text) == []

    @pytest.mark.parametrize("text,expected", [
        # 2024_01 / 2025_03 (corpus findings): "lakh crore" read as lakh (M1)
        ("the Central Government Debt (₹138.65 lakh crore) as of 31 March 2022", [13865000]),
        ("debt, however, increased by ₹17.48 lakh crore or 12.61 per cent over", [1748000]),
        # gold impact_amount raw strings
        ("₹ 75,45,928", [0.7545928]),
        ("₹ 10,48,516", [0.1048516]),
        ("₹0.24 lakh", [0.0024]),
        # OD_2025_05 F032 (gold): a range with both units
        ("ranging from ₹ 199.37 crore to ₹ 694.30 crore, during 2018-23", [199.37, 694.30]),
        # OD_2025_05 F223 (gold): a count beside money
        ("against the target of 1.83 lakh students, 1.20 lakh (66 per cent) were provided "
         "with assistance of ₹155.77 lakh", [1.5577]),
    ])
    def test_amounts(self, mp, text, expected):
        assert crores(mp.extract_monetary_values(text)) == pytest.approx(sorted(expected), rel=1e-5)

    # (gold report/id, text, gold impact_amount in crore)
    PRIMARY = [
        ("BR_2024_03 F003",
         "Failure of Nagar Parishad, Sheikhpura, in exercising checks while making payment to a "
         "private firm, which had not participated in the tender process, for supply of Solar "
         "Power Plants (Roof Top), led to fraudulent payment of ₹ 91.14 lakh. In addition, the "
         "Nagar Parishad sustained a loss of ₹ 1.37 crore, due to irregular disqualification of an "
         "eligible firm, in the technical bid.", 0.9114),
        ("BR_2024_03 F110",
         "Moreover, out of the expenditure of ₹ 68.38 crore so incurred, these ULBs had not "
         "furnished Utilisation Certificates for ₹ 36.03 crore (as of January 2023).", 36.03),
        ("HP_2022 F061",
         "(iii) Out of ₹1.02 crore received during 2006-17 under 13th FC by six test-checked PRIs, "
         "₹0.71 crore was further released to various executing agencies while ₹0.31 crore "
         "remained unutilized12 with these PRIs.", 0.31),
        ("HP_2022 F104",
         "During 2018-19, it was noticed in MCorp. Shimla that show tax of ₹11.94 lakh (including "
         "interest of ₹6.41 lakh) was outstanding from the owners of two cinema halls (Ritz and "
         "Shahi) running in MC jurisdiction for the period of 2012-18.", 0.1194),
        ("JH_2025_02 F046",
         "There was a difference of ₹ 40.50 crore (net credit) between the figures reflected in the "
         "accounts {₹ 86.66 crore (credit)} and that intimated by the RBI {(₹ 46.16 crore (debit)} "
         "as on 31 March 2024.", 40.50),
        ("JH_2025_02 F052",
         "Further, it was observed that, out of the total savings of ₹ 32,744.35 crore during FY "
         "2023-24, savings of ₹ 22,386.79 crore had occurred under 101 grants, the reasons for "
         "which have not been appropriately explained in the Appropriation Accounts.", 22386.79),
        ("JH_2025_02 F081",
         "Audit of records of the Department revealed that against the budget provision of "
         "₹ 1,820.20 crore (₹ 35.00 crore under the capital head and ₹ 1,785.20 crore under the "
         "revenue head), ₹ 657.36 crore (under the revenue head), was surrendered by the "
         "Department at the fag end of the financial year.", 657.36),
        ("JH_2025_02 F084",
         "Scrutiny revealed that, out of the savings of ₹ 657.36 crore under the revenue section, "
         "₹ 584.09 crore had been surrendered, while the remaining amount of ₹ 73.27 crore had "
         "lapsed at the end of the financial year.", 73.27),
        ("JH_2025_02 F103",
         "Test check of records of the State Urban Development Agency revealed that the closing "
         "balance as on 31 March 2024, as per bank statement, was ₹ 554.37 crore whereas the "
         "closing balance, as per cash book, was ₹ 535.03 crore. The difference of ₹ 19.34 crore, "
         "as shown in Table 3.22, has not been reconciled (November 2024).", 19.34),
        ("OD_2025_05 F028",
         "Surrender of provision under Capital head, amounting to ₹1,159.31 crore by the "
         "Department in FY 2019-22, indicated inability of the Department to create tangible "
         "educational assets.", 1159.31),
    ]

    @pytest.mark.parametrize("gold_id,text,impact", PRIMARY, ids=[p[0] for p in PRIMARY])
    def test_primary_is_gold_impact(self, mp, gold_id, text, impact):
        primary = mp.get_primary_amount(text)
        assert primary is not None
        assert primary.value.normalized_paise / CRORE == pytest.approx(impact, rel=0.01)


class TestUnits:
    """M2: million/billion multipliers; lakh crore added."""

    @pytest.mark.parametrize("unit,paise", [
        ("thousand", 10**5), ("lakh", 10**7), ("million", 10**8), ("crore", 10**9),
        ("billion", 10**11), ("thousand crore", 10**12), ("lakh crore", 10**14), (None, 100),
    ])
    def test_multiplier(self, mp, unit, paise):
        assert mp.normalize_to_paise(1, unit) == paise

    def test_no_float_truncation(self, mp):
        # 847.71 * 1e9 is 847709999999.99 in floating point
        assert mp.normalize_to_paise(847.71, "crore") == 847_710_000_000

    @pytest.mark.parametrize("text,crore", [
        ("₹ 5 lakhs", 0.05), ("₹ 5 lacs", 0.05), ("₹ 3 crores", 3), ("₹ 3 Cr.", 3),
        ("₹ 2 thousand crore", 2000),
    ])
    def test_unit_spellings(self, mp, text, crore):
        assert crores(mp.extract_monetary_values(text)) == [pytest.approx(crore)]


class TestTokenizer:
    def test_unit_only_amount_with_currency_in_clause(self, mp):
        """A unit-only amount counts when the clause is about money."""
        values = mp.extract_monetary_values("Expenditure of ₹ 24.30 crore and 5.6 crore was incurred.")
        assert crores(values) == [5.6, 24.3]

    def test_unit_only_amount_without_currency_is_not_money(self, mp):
        assert mp.extract_monetary_values("0.59 lakh was transferred from the general cash book") == []

    def test_unit_only_followed_by_noun_is_not_money(self, mp):
        assert mp.extract_monetary_values("₹ 5 crore was spent on 2.5 lakh households") != []
        assert crores(mp.extract_monetary_values("₹ 5 crore was spent on 2.5 lakh households")) == [5]

    def test_word_boundary_rs(self, mp):
        assert crores(mp.extract_monetary_values("(Rs. 62.76 crore)")) == [62.76]
        assert mp.extract_monetary_values("hours 45") == []

    def test_spans_and_order(self, mp):
        text = "A loss of ₹5 crore and ₹2 lakh."
        values = mp.extract_monetary_values(text)
        assert [text[v.start:v.end] for v in values] == ["₹5 crore", "₹2 lakh"]

    def test_usd_kept_as_usd(self, mp):
        (v,) = mp.extract_monetary_values("a grant of $2 million")
        assert v.currency == "USD"
        assert v.to_dict()["currency"] == "USD"
        # Not converted: no paise value and no crore figure
        assert v.normalized_paise is None and v.to_dict()["normalized_paise"] is None
        assert v.crore == 0

    def test_usd_only_text_has_no_impact_total(self, mp):
        classified = mp.extract_with_context("a loss of $2 million was suffered")
        assert mp.impact_total_paise(classified) == 0


class TestNestedAndTotal:
    TEXT = (
        "Audit noticed irregular expenditure of ₹ 25.00 crore, of which ₹ 15.00 crore "
        "and ₹ 4.00 crore were paid without sanction. A further loss of ₹ 3.00 crore occurred."
    )

    def test_nested_parts_flagged(self, mp):
        values = mp.extract_monetary_values(self.TEXT)
        assert [v.nested for v in values] == [False, True, True, False]

    def test_impact_total_excludes_nested(self, mp):
        classified = mp.extract_with_context(self.TEXT)
        assert mp.impact_total_paise(classified) == 28 * CRORE

    def test_primary_is_not_nested(self, mp):
        assert mp.get_primary_amount(self.TEXT).value.amount == 25.0


class TestAliases:
    """M13: paise fields carry the old names as aliases with the same value."""

    def test_monetary_value_dict(self):
        v = MonetaryValue(raw_text="₹1 crore", amount=1.0, unit="crore", normalized_paise=CRORE)
        d = v.to_dict()
        assert d["normalized_paise"] == d["normalized_inr"] == CRORE

    def test_monetary_value_old_constructor(self):
        v = MonetaryValue(raw_text="₹1 crore", amount=1.0, unit="crore", normalized_inr=CRORE)
        assert v.normalized_paise == CRORE

    def test_contract_reads_old_names(self):
        f = Finding(finding_id="f", report_id="r", text="t", summary="s", finding_type="other",
                    severity="low", total_amount_inr=5 * CRORE, monetary_value=2 * CRORE)
        assert f.total_amount_paise == 5 * CRORE
        assert f.monetary_value_paise == 2 * CRORE

    def test_contract_reads_new_names(self):
        f = Finding(finding_id="f", report_id="r", text="t", summary="s", finding_type="other",
                    severity="low", total_amount_paise=5 * CRORE, monetary_value_paise=2 * CRORE)
        assert f.total_amount_inr == 5 * CRORE
        assert f.monetary_value == 2 * CRORE

    def test_monetary_value_model(self):
        m = MonetaryValueModel(raw_text="x", amount=1, unit="crore", normalized_paise=CRORE)
        assert m.normalized_inr == CRORE


class TestFindingMoneyFields:
    """M9/M10/P9-04: monetary_value and severity come from the primary amount."""

    @pytest.fixture(scope="class")
    def finding(self):
        text = (
            "Audit observed that against the budget provision of ₹ 500.00 crore, the Department "
            "incurred avoidable expenditure of ₹ 2.00 crore on penal interest, of which ₹ 1.50 crore "
            "related to 2022-23."
        )
        fx = FindingExtractor()
        chunks = [{"chunk_id": "c1", "content": text, "content_type": "paragraph",
                   "source_page_physical": 40, "hierarchy": {}}]
        (f,) = fx.extract_findings("r", chunks, "state")
        return f

    def test_primary_not_max_or_sum(self, finding):
        assert finding.monetary_value_paise == 2 * CRORE
        assert finding.monetary_value_crore == 2.0

    def test_total_is_impact_only(self, finding):
        # the ₹500 crore budget and the nested ₹1.50 crore are not added
        assert finding.total_amount_paise == 2 * CRORE

    def test_aliases_equal(self, finding):
        assert finding.monetary_value == finding.monetary_value_paise
        assert finding.total_amount_inr == finding.total_amount_paise
        for mv in finding.monetary_values:
            assert mv["normalized_inr"] == mv["normalized_paise"]

    def test_one_primary_in_values(self, finding):
        assert sum(mv["is_primary"] for mv in finding.monetary_values) == 1

    def test_severity_from_primary(self, finding):
        # ₹2 crore is "medium"/"low" for a state report, not "critical" from ₹503.5 crore
        assert finding.severity != "critical"

    def test_small_amount_not_rounded_to_zero(self):
        fx = FindingExtractor()
        text = "Audit observed that excess payment of ₹ 12,000 was made to the contractor without sanction."
        chunks = [{"chunk_id": "c1", "content": text, "content_type": "paragraph",
                   "source_page_physical": 40, "hierarchy": {}}]
        (f,) = fx.extract_findings("r", chunks, "local_body")
        assert f.monetary_value_crore == pytest.approx(0.0012)

    def test_quantity_chunk_still_a_candidate_but_without_money(self):
        """A lakh quantity keeps its acceptance signal but gets no rupee value."""
        fx = FindingExtractor()
        text = ("3.51 lakh eligible students were deprived of free uniforms during 2018-23 "
                "as the scheme was not implemented in the district.")
        chunks = [{"chunk_id": "c1", "content": text, "content_type": "paragraph",
                   "source_page_physical": 40, "hierarchy": {}}]
        findings = fx.extract_findings("r", chunks, "state")
        assert len(findings) == 1
        assert findings[0].monetary_values == []
        assert findings[0].monetary_value is None


def test_context_classification_uses_own_window(mp):
    """A cue before an earlier amount does not classify a later one."""
    classified = mp.extract_with_context(
        "There was a loss of ₹ 5 crore against the target of ₹ 10 crore."
    )
    assert [c.context for c in classified] == [
        MonetaryContext.FINDING_IMPACT, MonetaryContext.COMPARISON_TARGET,
    ]


def test_footnote_marker_between_amount_and_unit(mp):
    """B-6-19 markers never split an amount from its unit."""
    values = mp.extract_monetary_values("a loss of ₹ 25[^2] crore and ₹ 1.14 crore[^36] was noticed")
    assert crores(values) == [1.14, 25.0]
