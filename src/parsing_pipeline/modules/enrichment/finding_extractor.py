"""
FindingExtractor: Extracts audit findings with monetary values, severity classification,
and finding-type detection from CAG audit reports.

Supports tier-specific severity thresholds for Union, State, and Local Body reports.
"""

import re
from typing import List, Dict, Optional
from enum import Enum

from src.core.data_contracts import Finding
from src.parsing_pipeline.modules.enrichment.monetary_processor import (
    MonetaryProcessor,
    MonetaryValue,
)
from src.parsing_pipeline.modules import report_type_profiles
from src.parsing_pipeline.modules import semantic_patterns
from src.parsing_pipeline.config import get_config, SemanticEnrichmentConfig


class FindingType(Enum):
    """Classification of audit finding types."""

    IRREGULAR_EXPENDITURE = "irregular_expenditure"
    LOSS_OF_REVENUE = "loss_of_revenue"
    WASTEFUL_EXPENDITURE = "wasteful_expenditure"
    NON_COMPLIANCE = "non_compliance"
    SYSTEM_DEFICIENCY = "system_deficiency"
    PERFORMANCE_SHORTFALL = "performance_shortfall"
    FRAUD_MISAPPROPRIATION = "fraud_misappropriation"
    PROCEDURAL_LAPSE = "procedural_lapse"
    # State/Local Body finding types
    IDLE_ASSETS = "idle_assets"
    NON_REALIZATION_OF_DUES = "non_realization_of_dues"
    INCOMPLETE_INFRASTRUCTURE = "incomplete_infrastructure"
    ACCOUNTING_IRREGULARITY = "accounting_irregularity"
    FUND_UTILIZATION_FAILURE = "fund_utilization_failure"
    OTHER = "other"


class Severity(Enum):
    """Severity classification based on monetary value and impact."""

    CRITICAL = "critical"  # > ₹100 crore or systemic issues
    HIGH = "high"  # ₹10-100 crore or significant impact
    MEDIUM = "medium"  # ₹1-10 crore or moderate impact
    LOW = "low"  # < ₹1 crore or minor issues


class FindingExtractor:
    """
    Extracts audit findings from child chunks with monetary impact analysis.

    Features:
    - Report-type aware extraction using type-specific patterns
    - Tier-specific severity thresholds (Union/State/Local Body)
    - Enhanced semantic pattern matching for implicit findings
    - P0-07: Umbrella pattern detection with deficiency keyword extraction
    - P0-07: Tier-specific finding type taxonomy gates
    """

    # P0-07: Umbrella pattern - "Audit observed/noticed/found that..." with deficiency keywords
    # This captures the dominant CAG linguistic pattern for findings
    # C4: Extended with more observation verbs and deficiency keywords for Union reports
    AUDIT_OBSERVATION_PATTERN = re.compile(
        r"\b(?:[Aa]udit|[Ss]crutiny|[Rr]eview|[Ee]xamination|[Tt]est[\s-]?check)\s+"
        r"(?:observed|noticed|found|compared|verified|disclosed|revealed|indicated|showed)\s+that\b.*?"
        r"(not\s+maintained|not\s+done|not\s+adhered|not\s+prepared|deficient|"
        r"inadequate|shortfall|failed|non[\s-]?compliance|irregularity|loss|avoidable|"
        r"not\s+recovered|not\s+collected|not\s+established|not\s+functioning|"
        r"not\s+operational|pending|outstanding|non[\s-]?realization|not\s+utilized|"
        r"unspent|unutilized|diversion|misuse|discrepancy|violation|contravention|"
        r"excess|short|under[\s-]?assessment|under[\s-]?recovery|"
        # C4: Additional deficiency keywords common in Union reports
        r"resulted\s+in|led\s+to|contrary\s+to|in\s+violation|"
        r"without\s+proper|without\s+adequate|extra\s+expenditure|undue\s+benefit|"
        r"overpayment|non[\s-]?deduction|non[\s-]?imposition|delayed|inordinate\s+delay|"
        r"despite|lapsed|irregular|unwarranted|unjustified|infructuous)",
        re.IGNORECASE | re.DOTALL
    )

    # P0-07: Map deficiency keywords to finding types
    DEFICIENCY_TO_TYPE_MAP = {
        "not maintained": FindingType.ACCOUNTING_IRREGULARITY,
        "not done": FindingType.PERFORMANCE_SHORTFALL,
        "not adhered": FindingType.NON_COMPLIANCE,
        "not prepared": FindingType.ACCOUNTING_IRREGULARITY,
        "deficient": FindingType.SYSTEM_DEFICIENCY,
        "inadequate": FindingType.SYSTEM_DEFICIENCY,
        "shortfall": FindingType.PERFORMANCE_SHORTFALL,
        "failed": FindingType.PERFORMANCE_SHORTFALL,
        "non-compliance": FindingType.NON_COMPLIANCE,
        "non compliance": FindingType.NON_COMPLIANCE,
        "noncompliance": FindingType.NON_COMPLIANCE,
        "irregularity": FindingType.ACCOUNTING_IRREGULARITY,
        "loss": FindingType.LOSS_OF_REVENUE,
        "avoidable": FindingType.WASTEFUL_EXPENDITURE,
        "not recovered": FindingType.NON_REALIZATION_OF_DUES,
        "not collected": FindingType.NON_REALIZATION_OF_DUES,
        "not established": FindingType.SYSTEM_DEFICIENCY,
        "not functioning": FindingType.SYSTEM_DEFICIENCY,
        "not operational": FindingType.IDLE_ASSETS,
        "pending": FindingType.NON_REALIZATION_OF_DUES,
        "outstanding": FindingType.NON_REALIZATION_OF_DUES,
        "non-realization": FindingType.NON_REALIZATION_OF_DUES,
        "non realization": FindingType.NON_REALIZATION_OF_DUES,
        "not utilized": FindingType.FUND_UTILIZATION_FAILURE,
        "unspent": FindingType.FUND_UTILIZATION_FAILURE,
        "unutilized": FindingType.FUND_UTILIZATION_FAILURE,
        "diversion": FindingType.FUND_UTILIZATION_FAILURE,
        "misuse": FindingType.FRAUD_MISAPPROPRIATION,
        "discrepancy": FindingType.ACCOUNTING_IRREGULARITY,
        "violation": FindingType.NON_COMPLIANCE,
        "contravention": FindingType.NON_COMPLIANCE,
        "excess": FindingType.WASTEFUL_EXPENDITURE,
        "short": FindingType.PERFORMANCE_SHORTFALL,
        "under-assessment": FindingType.LOSS_OF_REVENUE,
        "under assessment": FindingType.LOSS_OF_REVENUE,
        "under-recovery": FindingType.LOSS_OF_REVENUE,
        "under recovery": FindingType.LOSS_OF_REVENUE,
        # C4: Additional deficiency keywords for Union reports
        "resulted in": FindingType.PERFORMANCE_SHORTFALL,  # Context-dependent, default to performance
        "led to": FindingType.PERFORMANCE_SHORTFALL,
        "contrary to": FindingType.NON_COMPLIANCE,
        "in violation": FindingType.NON_COMPLIANCE,
        "without proper": FindingType.PROCEDURAL_LAPSE,
        "without adequate": FindingType.SYSTEM_DEFICIENCY,
        "extra expenditure": FindingType.WASTEFUL_EXPENDITURE,
        "undue benefit": FindingType.FRAUD_MISAPPROPRIATION,
        "overpayment": FindingType.WASTEFUL_EXPENDITURE,
        "non-deduction": FindingType.LOSS_OF_REVENUE,
        "non deduction": FindingType.LOSS_OF_REVENUE,
        "non-imposition": FindingType.LOSS_OF_REVENUE,
        "non imposition": FindingType.LOSS_OF_REVENUE,
        "delayed": FindingType.PERFORMANCE_SHORTFALL,
        "inordinate delay": FindingType.PERFORMANCE_SHORTFALL,
        "despite": FindingType.NON_COMPLIANCE,
        "lapsed": FindingType.FUND_UTILIZATION_FAILURE,
        "irregular": FindingType.IRREGULAR_EXPENDITURE,
        "unwarranted": FindingType.WASTEFUL_EXPENDITURE,
        "unjustified": FindingType.WASTEFUL_EXPENDITURE,
        "infructuous": FindingType.WASTEFUL_EXPENDITURE,
    }

    # P0-07: Tier-specific allowed finding types
    # Union findings should not use certain State/Local-specific types
    TIER_ALLOWED_TYPES = {
        "union": [
            FindingType.LOSS_OF_REVENUE,
            FindingType.ACCOUNTING_IRREGULARITY,
            FindingType.NON_REALIZATION_OF_DUES,
            FindingType.SYSTEM_DEFICIENCY,
            FindingType.WASTEFUL_EXPENDITURE,
            FindingType.PERFORMANCE_SHORTFALL,
            FindingType.PROCEDURAL_LAPSE,
            FindingType.FRAUD_MISAPPROPRIATION,
            FindingType.NON_COMPLIANCE,
            FindingType.IRREGULAR_EXPENDITURE,
            FindingType.INCOMPLETE_INFRASTRUCTURE,
            FindingType.FUND_UTILIZATION_FAILURE,
            FindingType.OTHER,
        ],
        "state": [
            # All types allowed for state
            FindingType.IRREGULAR_EXPENDITURE,
            FindingType.LOSS_OF_REVENUE,
            FindingType.WASTEFUL_EXPENDITURE,
            FindingType.NON_COMPLIANCE,
            FindingType.SYSTEM_DEFICIENCY,
            FindingType.PERFORMANCE_SHORTFALL,
            FindingType.FRAUD_MISAPPROPRIATION,
            FindingType.PROCEDURAL_LAPSE,
            FindingType.IDLE_ASSETS,
            FindingType.NON_REALIZATION_OF_DUES,
            FindingType.INCOMPLETE_INFRASTRUCTURE,
            FindingType.ACCOUNTING_IRREGULARITY,
            FindingType.FUND_UTILIZATION_FAILURE,
            FindingType.OTHER,
        ],
        "local_body": [
            # All types allowed for local body
            FindingType.IRREGULAR_EXPENDITURE,
            FindingType.LOSS_OF_REVENUE,
            FindingType.WASTEFUL_EXPENDITURE,
            FindingType.NON_COMPLIANCE,
            FindingType.SYSTEM_DEFICIENCY,
            FindingType.PERFORMANCE_SHORTFALL,
            FindingType.FRAUD_MISAPPROPRIATION,
            FindingType.PROCEDURAL_LAPSE,
            FindingType.IDLE_ASSETS,
            FindingType.NON_REALIZATION_OF_DUES,
            FindingType.INCOMPLETE_INFRASTRUCTURE,
            FindingType.ACCOUNTING_IRREGULARITY,
            FindingType.FUND_UTILIZATION_FAILURE,
            FindingType.OTHER,
        ],
    }

    # P0-07: Non-finding rejection patterns
    # These patterns indicate content that looks like findings but isn't
    NON_FINDING_PATTERNS = [
        re.compile(r"^\s*Brief\s+Snapshot\b", re.IGNORECASE),
        re.compile(r"^\s*[\d.]+\s+denotes\b", re.IGNORECASE),  # Footnote/definition
        re.compile(r"^(?:In\s+)?(?:the\s+)?(?:year|period)\s+\d{4}", re.IGNORECASE),  # Background context
        re.compile(r"^\s*(?:Source|Note|Reference)[\s:]*", re.IGNORECASE),  # Source citations
        re.compile(r"^\s*\*\s*(?:denotes|indicates|represents)", re.IGNORECASE),  # Footnote markers
        re.compile(r"^\s*Table\s+[\d.]+[\s:]+", re.IGNORECASE),  # Table captions
        re.compile(r"^\s*Chart\s+[\d.]+[\s:]+", re.IGNORECASE),  # Chart captions
        re.compile(r"^\s*Figure\s+[\d.]+[\s:]+", re.IGNORECASE),  # Figure captions
        re.compile(r"^\s*Box\s+[\d.]+[\s:]+", re.IGNORECASE),  # Box captions
        # R1: Multi-year span patterns (statistical data, not findings)
        # These capture historical aggregate data like "released ₹60,000 crore during 2003-2022"
        re.compile(r"during\s+(?:the\s+)?(?:FYs?\s+)?\d{4}[-–]\d{2,4}\s+to\s+\d{4}", re.IGNORECASE),
        re.compile(r"during\s+(?:the\s+)?(?:financial\s+)?years?\s+\d{4}\s*[-–]\s*\d{4}", re.IGNORECASE),
        re.compile(r"from\s+(?:FYs?\s+)?\d{4}[-–]\d{2,4}\s+to\s+\d{4}", re.IGNORECASE),
        re.compile(r"(?:for|during)\s+the\s+period\s+(?:from\s+)?(?:FYs?\s+)?\d{4}", re.IGNORECASE),
        # R1: Table reference patterns (presenting data, not findings)
        re.compile(r"as\s+(?:depicted|shown|given|detailed)\s+in\s+Table\s+[\d.]+", re.IGNORECASE),
        re.compile(r"(?:details?\s+(?:is|are)\s+)?(?:given|shown|depicted)\s+in\s+(?:the\s+)?(?:following\s+)?Table", re.IGNORECASE),
        # R1: Source compilation patterns (data from external sources)
        re.compile(r"compiled\s+by\s+(?:the\s+)?(?:office\s+of\s+)?(?:the\s+)?(?:AG|Accountant\s+General)", re.IGNORECASE),
        re.compile(r"\(Source:\s*(?:Office|AG|Data|Department)", re.IGNORECASE),
        re.compile(r"(?:as\s+per|based\s+on)\s+(?:the\s+)?(?:data|information|records?)\s+(?:provided|compiled|furnished)\s+by", re.IGNORECASE),
        # R1: Background release/allocation patterns (grants/funds released over periods)
        # These capture "PRD had released grants amounting to ₹59,995 crore during 2003-2022"
        re.compile(
            r"(?:had\s+)?(?:released|allocated|sanctioned|disbursed)\s+(?:grants?|funds?|GIA|amount)"
            r"(?:\s+(?:amounting\s+to|of))?\s*[₹Rs.\s]*[\d,]+(?:\.\d+)?\s*(?:crore|lakh)"
            r"(?:\s*,)?\s*(?:under|during|to|for)\s+(?:different|various|the)",
            re.IGNORECASE
        ),
        # R1: UC/adjustment pending context (multi-year aggregate data)
        re.compile(
            r"(?:UCs?|Utilisation\s+Certificates?)\s+(?:for\s+)?(?:an?\s+)?(?:amount\s+of\s+)?"
            r"[₹Rs.\s]*[\d,]+(?:\.\d+)?\s*(?:crore|lakh)?\s*(?:\(.{0,20}per\s*cent\))?(?:\s+only)?"
            r"(?:\s*,)?\s*(?:\()?as\s+(?:of|on)\s+(?:March|April|January)",
            re.IGNORECASE
        ),
    ]

    FINDING_TYPE_PATTERNS = {
        FindingType.IRREGULAR_EXPENDITURE: [
            r"irregular\s+expenditure",
            r"irregularly\s+(spent|incurred|paid)",
            r"unauthorized\s+expenditure",
            r"expenditure\s+not\s+sanctioned",
            # C4: Union-specific irregular expenditure patterns
            r"(?:irregular|unauthorized|unjustified)\s+(?:payment|release|sanction|expenditure)\s+.{0,30}(?:of|amounting)",
            r"(?:expenditure|payment)\s+.{0,30}(?:incurred|made|released)\s+.{0,30}(?:in\s+violation|contrary\s+to|without\s+approval)",
            r"(?:Ministry|Department|PSU|Company)\s+.{0,40}(?:incurred|made|released)\s+.{0,30}(?:irregular|unauthorized|unjustified)",
        ],
        FindingType.LOSS_OF_REVENUE: [
            r"loss\s+of\s+revenue",
            r"revenue\s+loss",
            r"short\s+(levy|collection|realization)",
            r"non-?recovery\s+of",
            r"tax\s+evasion",
            # C4: Union-specific revenue loss patterns
            r"resulted\s+in\s+(?:a\s+)?(?:short|non|under)[\s-]?(?:recovery|realization|collection)\s+of",
            r"(?:short|non|under)[\s-]?(?:recovery|realization|collection)\s+.{0,30}amounting\s+to",
            r"non[\s-]?imposition\s+of\s+(?:penalty|interest|liquidated\s+damages)",
            r"non[\s-]?levy\s+of\s+(?:penalty|interest|royalty|cess|duty)",
            r"non[\s-]?deduction\s+of\s+(?:TDS|income\s+tax|GST|tax|duty)",
            # State/Local: GST/tax assessment mismatches
            r"mismatch\s+(?:amounting\s+to|of)\s+.{0,20}(?:crore|lakh)",
            r"(?:short|non|under)[\s-]?(?:determination|assessment|levy|collection)\s+of\s+(?:tax|duty|cess|revenue)",
            r"excess\s+(?:ITC|Input\s+Tax\s+Credit|credit)\s+(?:availed|claimed|utili[sz]ed)",
            r"(?:ineligible|inadmissible|incorrect)\s+(?:ITC|Input\s+Tax\s+Credit|claim|deduction)",
            r"tax\s+.{0,30}not\s+(?:levied|collected|imposed)\s+at\s+(?:the\s+)?prescribed\s+rate",
            r"loss\s+(?:of|to)\s+.{0,20}(?:exchequer|revenue|government)",
            # State/Local: Penalty/interest not collected
            r"(?:penalty|interest)\s+.{0,30}not\s+(?:imposed|levied|collected|charged)",
            r"non[\s-]?collection\s+of\s+(?:service\s+charge|user\s+charge|fee|cess|tax|penalty)",
            r"under[\s-]?recovery\s+of\s+(?:user\s+charges?|fees?|revenue|tax)",
            # State/Local: Arrears and tax liability
            r"arrears\s+.{0,30}not\s+(?:collected|recovered|reali[sz]ed)",
            r"tax\s+liability\s+.{0,30}(?:not\s+discharged|not\s+paid|outstanding)",
            r"prescribed\s+service\s+charge\s+was\s+not\s+collected",
            # GST/ITC-specific patterns (Kerala revenue reports)
            r"irregular\s+claim(?:ing)?\s+of\s+(?:ITC|Input\s+Tax\s+Credit)",
            r"mismatch\s+(?:of|in)\s+ITC\s+(?:availed|available)",
            r"mismatch\s+(?:of|in)\s+(?:ITC|tax\s+liability)\s+amounting\s+to",
            r"unreconciled\s+(?:ITC|payment\s+of\s+tax)",
            r"turnover\s+(?:escape|mismatch|difference)",
            r"(?:compliance\s+)?(?:discrepanc|deficienc)(?:y|ies)\s+.{0,30}(?:tax|ITC|GST|GSTR|liability)",
            r"tax\s+effect\s+of\s+₹",
            r"short\s+(?:determination|payment)\s+of\s+(?:tax|interest)",
            r"(?:not\s+adhering|non-?adherence)\s+to\s+(?:provisions?\s+(?:of|on))?\s*(?:interest|tax|time\s+of\s+supply)",
            r"(?:house|trade|show)\s+tax\s+.{0,30}(?:outstanding|pending|not\s+recovered|not\s+imposed)",
            r"rental\s+charges?\s+.{0,20}(?:pending|outstanding|not\s+recovered)",
            r"(?:electricity|mobile\s+tower)\s+.{0,30}(?:cess|charges?|fees?)\s+.{0,20}not\s+(?:recovered|collected)",
            r"installation\s+and\s+renewal\s+(?:charges?|fees?)\s+.{0,20}not\s+(?:recovered|collected)",
            # More flexible patterns for outstanding fees/charges
            r"(?:fees?|charges?)\s+.{0,20}(?:had\s+)?not\s+been\s+(?:recovered|collected)",
            r"(?:fees?|charges?)\s+.{0,20}(?:amounting|of)\s+.{0,20}not\s+(?:recovered|collected)",
            # Mobile tower fees
            r"mobile\s+towers?\s+.{0,60}(?:fees?|charges?)\s+.{0,30}(?:had\s+)?not\s+been\s+(?:recovered|collected)",
            r"(?:installation|renewal)\s+.{0,20}(?:fees?|charges?)\s+.{0,30}(?:had\s+)?not\s+been\s+(?:recovered|collected)",
        ],
        FindingType.WASTEFUL_EXPENDITURE: [
            r"wasteful\s+expenditure",
            r"infructuous\s+expenditure",
            r"unfruitful\s+expenditure",
            r"idle\s+(investment|expenditure|machinery|equipment)",
            r"blocking\s+of\s+funds",
            # C4: Union-specific wasteful expenditure patterns
            r"resulted\s+in\s+(?:an?\s+)?(?:avoidable|extra|additional|wasteful|infructuous)\s+expenditure",
            r"(?:avoidable|extra|additional|wasteful|infructuous)\s+expenditure\s+.{0,30}(?:of|amounting)",
            r"undue\s+(?:benefit|favour|financial\s+benefit)\s+(?:of|to|amounting)",
            r"unwarranted\s+(?:expenditure|payment|benefit)",
            r"unjustified\s+(?:expenditure|payment|release)",
            # State/Local: Avoidable/excess payment patterns
            r"avoidable\s+(?:payment|expenditure|cost|interest|penalty)\s+.{0,20}(?:of|amounting)",
            r"excess\s+(?:payment|expenditure)\s+.{0,20}(?:of|amounting|to\s+the\s+tune)",
            r"overpayment\s+.{0,20}(?:of|amounting|to)",
            r"(?:unfruitful|infructuous|unproductive)\s+expenditure",
            r"expenditure\s+.{0,30}without\s+(?:any|adequate)\s+(?:result|outcome|benefit|purpose)",
            r"payment\s+.{0,30}(?:made|released)\s+.{0,30}without\s+(?:any|proper|adequate)\s+(?:justification|verification|utili[sz]ation)",
            # State/Local: Delayed payment penalties
            r"avoidable\s+(?:payment\s+of\s+)?(?:penal\s+interest|penalty|interest\s+charges?)",
            r"(?:penal\s+interest|penalty|damages?)\s+.{0,20}(?:of|amounting\s+to)\s+.{0,10}(?:₹|Rs|crore|lakh)",
            r"(?:delayed|late)\s+(?:payment|remittance)\s+.{0,30}(?:penalty|interest|damages?)",
            r"failure\s+.{0,30}(?:timely\s+)?(?:repayment|remittance)\s+.{0,30}(?:penal|interest|penalty)",
            r"defaulted\s+in\s+(?:repaying|paying)",
            r"avoidable\s+expenditure\s+towards?\s+(?:penalty|interest|damages?)",
            r"resulted\s+in\s+.{0,20}avoidable\s+expenditure",
            r"failure\s+.{0,50}resulted\s+in\s+.{0,20}(?:avoidable|penalty|interest)",
            # State/Local: Excess wages/payments
            r"excess\s+wages?\s+.{0,20}(?:paid|amounting)",
            r"(?:wages?|payment)\s+.{0,20}(?:paid|made)\s+.{0,20}(?:after\s+)?delay",
            r"irregular\s+payment\s+.{0,20}without",
            # State/Local: Uneconomical purchases
            r"uneconomical\s+(?:purchases?|procurement)",
            r"might\s+have\s+led\s+to\s+uneconomical",
        ],
        FindingType.NON_COMPLIANCE: [
            r"non-?compliance",
            r"violation\s+of",
            r"contrary\s+to\s+(rules|guidelines|provisions)",
            r"in\s+contravention\s+of",
            r"failed\s+to\s+comply",
            # State/Local: Broader compliance violation patterns
            r"(?:not\s+in\s+conformity|in\s+violation|in\s+contravention|contrary\s+to)\s+.{0,30}(?:with|of)\s+.{0,30}(?:rules?|guidelines?|norms?|provisions?|orders?|instructions?|standards?)",
            r"in\s+(?:violation|breach|contravention)\s+of\s+.{0,30}(?:Section|Rule|Clause|Order|Circular|Notification)",
            r"(?:violat|breach|contravent)(?:ed|ing|ion)\s+.{0,30}(?:provisions?|rules?|guidelines?|norms?|conditions?)",
            r"despite\s+(?:instructions?|directions?|guidelines?|provisions?|orders?)",
            r"without\s+(?:approval|sanction|permission|authori[sz]ation)\s+of",
            r"in\s+(?:excess|disregard)\s+of\s+.{0,30}(?:sanction|limit|authority|provision)",
            # P0-07: Additional NON_COMPLIANCE patterns
            r"\bwas\s+not\s+(?:maintained|done|adhered|prepared|established)",
            r"\bUC[s]?\s+(?:non[\s-]?submission|not\s+furnished)",
            r"\bunreconciled\s+accounts?\b",
            r"not\s+in\s+accordance\s+with",
            r"deviat(?:ed|ing|ion)\s+from",
            r"did\s+not\s+adhere\s+to",
            # C4: Union-specific non-compliance patterns
            r"(?:provisions?\s+of|as\s+per)\s+(?:Section|Rule|Clause|Para|GFR|CVC)\s+.{0,30}(?:not\s+followed|not\s+adhered|violated|contravened)",
            r"(?:Ministry|Department|PSU|Company)\s+.{0,40}(?:failed\s+to\s+comply|did\s+not\s+adhere|violated|contravened)",
            r"(?:terms?\s+and\s+)?conditions?\s+of\s+(?:the\s+)?(?:contract|agreement|sanction|approval)\s+.{0,30}(?:not\s+followed|violated|breached)",
        ],
        FindingType.SYSTEM_DEFICIENCY: [
            r"system(ic)?\s+deficien",
            r"internal\s+control\s+(weakness|deficiency)",
            r"lack\s+of\s+(monitoring|oversight|control)",
            r"absence\s+of\s+(mechanism|system|procedure)",
            # State/Local: Monitoring/oversight gaps
            r"no\s+.{0,20}(?:meetings?|committee)\s+.{0,20}(?:were|was)\s+held",
            r"(?:meetings?|committee)\s+.{0,20}(?:were|was)\s+not\s+held",
            r"internal\s+audit\s+.{0,20}not\s+(?:planned|conducted|carried\s+out)",
            r"internal\s+audit\s+.{0,30}(?:had|was)\s+not\s+(?:planned|conducted)",
            r"(?:had|has)\s+not\s+planned\s+internal\s+audit",
            r"(?:Proper\s+Officers?|officials?)\s+.{0,20}(?:had|have)\s+not\s+initiated\s+(?:any\s+)?action",
            r"(?:no|not\s+any)\s+(?:effective\s+)?(?:action|steps?)\s+.{0,20}(?:taken|initiated)",
            r"(?:MC|municipal|ULB|PRI)\s+.{0,20}had\s+not\s+(?:conducted|imposed|initiated)",
            r"(?:survey|inspection|verification)\s+.{0,20}not\s+(?:conducted|carried\s+out|done)",
            r"(?:inspection|verification)\s+.{0,20}(?:were|was)\s+not\s+(?:done|conducted)",
            # State/Local: Inadequate mechanisms
            r"(?:no|not\s+any)\s+(?:penal\s+)?mechanism\s+.{0,20}(?:built|established|in\s+place)",
            r"(?:oversight|supervision|monitoring)\s+.{0,20}(?:was|were)\s+(?:deficient|inadequate|absent|lacking)",
            r"(?:capacity\s+building|training)\s+.{0,20}(?:was|were)\s+(?:deficient|not\s+(?:done|organized))",
            # State/Local: Compliance/follow-up gaps
            r"(?:compliance|follow[\s-]?up)\s+.{0,20}(?:was|were)\s+not\s+(?:ensured|done|pursued)",
            r"audit\s+(?:paragraphs?|observations?)\s+.{0,20}(?:remained|pending)\s+.{0,20}(?:unsettled|outstanding)",
            r"IRs?\s+.{0,20}(?:outstanding|pending)\s+.{0,20}(?:for|since)",
            # P0-07: Additional SYSTEM_DEFICIENCY patterns
            r"\bno\s+\w+\s+(?:in\s+any|established|constituted)\b",
            r"\bno\s+(?:committee|mechanism|policy|system)\s+.{0,20}(?:established|in\s+place)",
            r"\bweak(?:ness(?:es)?)\s+in\s+.{0,20}(?:internal|control|system|oversight)",
            r"(?:IT|MIS|monitoring)\s+system\s+.{0,20}(?:not|absent|lacking|deficient)",
            r"(?:register|records?)\s+.{0,20}(?:not|were\s+not)\s+(?:maintained|kept|updated)",
            # C4: Union-specific system deficiency patterns
            r"(?:Ministry|Department|PSU|Company)\s+.{0,40}(?:did\s+not\s+have|lacked|had\s+no)\s+(?:proper|adequate|effective)\s+(?:mechanism|system|procedure|policy)",
            r"(?:internal\s+controls?|risk\s+management|MIS|IT\s+system)\s+.{0,30}(?:weak|deficient|inadequate|absent|lacking)",
            r"(?:monitoring|supervision|oversight)\s+.{0,30}(?:was|were)\s+(?:deficient|inadequate|absent|lacking|not\s+in\s+place)",
        ],
        FindingType.PERFORMANCE_SHORTFALL: [
            r"performance\s+(shortfall|gap|deficiency)",
            r"target\s+not\s+(achieved|met)",
            r"underperformance",
            r"below\s+(target|benchmark|standard)",
            r"delay\s+in\s+(completion|implementation|execution)",
            # P0-07: Additional PERFORMANCE_SHORTFALL patterns
            r"\bshortfall\b.*\btarget\b",
            r"\b(\d+)\s*%\s+(?:vs|against|as\s+against)\s+(\d+)?\s*%",
            r"\bagainst\s+the\s+target\s+of\b",
            r"\bonly\s+\d+(?:\.\d+)?\s*(?:per\s*cent|%)\s+.{0,30}(?:achieved|completed|utilized)",
            r"\bfailed\s+to\s+achieve\b",
            # State/Local: Audit observation openers + negative outcomes
            r"audit\s+(?:observed|noticed)\s+that\s+.{0,60}(?:had\s+not|did\s+not|was\s+not|were\s+not)",
            r"scrutiny\s+revealed\s+that\s+.{0,60}(?:had\s+not|did\s+not|was\s+not|were\s+not|failed)",
            r"it\s+was\s+(?:observed|noticed|found)\s+that\s+.{0,60}(?:had\s+not|did\s+not|was\s+not|were\s+not)",
            # State/Local: Direct deficiency statements
            r"(?:was|were)\s+(?:deficient|inadequate|insufficient|absent)",
            r"did\s+not\s+(?:provide|ensure|organize|carry\s+out|initiate|follow|adhere|prepare|comply)",
            r"had\s+not\s+(?:taken|carried|organized|initiated|conducted|prepared|submitted|adhered)",
            r"failure\s+to\s+(?:provide|ensure|carry\s+out|adhere|comply|maintain|submit)",
            r"(?:not\s+adhered\s+to|non-?adherence\s+to)",
            # State/Local: Shortfall/target patterns
            r"short(?:fall|age)\s+(?:in|of)\s+(?:achievement|target|performance|delivery)",
            r"target\s+.{0,30}(?:not\s+achieved|not\s+met|shortfall)",
            # State/Local: Percentage-based shortfalls
            r"only\s+\d+[\.\d]*\s*per\s*cent\s+.{0,40}(?:achieved|completed|covered|functional)",
            r"ranged\s+from\s+(?:zero|nil|\d+)\s+to\s+\d+\s*per\s*cent",
            r"\d+\s*per\s*cent\s+.{0,30}(?:less\s+than|below|short\s+of|against)",
            # State/Local: Scheme/benefit patterns
            r"scheme\s+.{0,40}(?:not\s+implemented|not\s+operationali[sz]ed|not\s+functional)",
            r"benefits?\s+.{0,30}not\s+(?:provided|extended|released|disbursed)",
            r"beneficiar(?:y|ies)\s+.{0,30}not\s+(?:identified|selected|covered|provided)",
            # State/Local: Benefit deprivation patterns
            r"(?:were|was)\s+deprived\s+of\s+(?:this\s+)?(?:benefit|allowance|stipend|entitlement)",
            r"eligible\s+.{0,30}(?:were|was)\s+(?:not\s+provided|deprived|denied)",
            r"(?:CwSN|children|students?|beneficiar(?:y|ies))\s+.{0,30}(?:deprived|not\s+provided|denied)",
            r"failed\s+transactions?\s+.{0,30}(?:bank\s+accounts?|beneficiar)",
            r"transferred\s+.{0,30}(?:dormant|wrong|incorrect)\s+.{0,15}(?:bank\s+)?accounts?",
            # State/Local: Objective non-achievement
            r"objective(?:s)?\s+.{0,30}(?:was\s+not|were\s+not|had\s+not\s+been)\s+achieved",
            r"(?:had|has)\s+not\s+(?:reached|achieved|met)\s+(?:the\s+)?target",
            r"(?:enrolment|enrollment|retention)\s+.{0,30}(?:declined|decreased|dropped|fell)",
            r"(?:decline|decrease|drop)\s+.{0,20}(?:in|of)\s+.{0,30}(?:enrolment|enrollment|retention|attendance)",
            r"dropout\s+.{0,30}(?:increased|rose|was\s+higher)",
            # State/Local: Utilization shortfall
            r"utili[sz]ation\s+.{0,30}(?:ranged|was\s+only|was\s+merely)\s+.{0,20}(?:between|\d+)",
            r"only\s+\d+\s*(?:per\s*cent|%)\s+.{0,30}(?:utili[sz]ed|spent|expended)",
            # State/Local: Survey/planning failures
            r"(?:survey|assessment|study)\s+.{0,30}not\s+(?:conducted|carried\s+out|done|undertaken)",
            r"(?:plan|planning)\s+.{0,30}not\s+(?:prepared|undertaken|done)",
            r"bottom[\s-]?up\s+approach\s+.{0,20}not\s+(?:followed|adopted)",
            # State/Local: Adverse ratios/conditions
            r"adverse\s+(?:PTR|Pupil[\s-]?Teacher\s+Ratio|ratio)",
            r"(?:PTR|ratio)\s+.{0,30}(?:adverse|worse|unfavourable)",
            # C4: Union-specific performance shortfall patterns
            r"resulted\s+in\s+(?:delay|inordinate\s+delay|time\s+overrun|cost\s+overrun)",
            r"(?:delay|time\s+overrun|cost\s+overrun)\s+.{0,30}(?:of|amounting\s+to|ranging)",
            r"(?:project|work|contract)\s+.{0,30}(?:could\s+not\s+be\s+completed|remained\s+incomplete|was\s+abandoned)",
            r"(?:Ministry|Department|PSU|Company|Corporation)\s+.{0,40}(?:failed\s+to|could\s+not|did\s+not)\s+(?:achieve|complete|execute|implement)",
            r"physical\s+progress\s+.{0,20}(?:was\s+only|ranged\s+from|stood\s+at)\s+.{0,10}(?:\d+\s*%|\d+\s+per\s+cent)",
        ],
        FindingType.FRAUD_MISAPPROPRIATION: [
            r"fraud",
            r"misappropriation",
            r"embezzlement",
            r"fictitious",
            r"bogus\s+(claim|bill|payment)",
            # State/Local: Suspected/doubtful cases
            r"doubtful\s+(?:payment|deployment|expenditure|transaction)",
            r"suspected\s+misappropriation",
            r"possibility\s+of\s+(?:misuse|pilferage|loss|embezzlement)",
            r"indicat(?:ed|ive|ing)\s+.{0,20}(?:misuse|pilferage|embezzlement|fraud)",
            r"double\s+payment\s+of\s+wages",
            r"same\s+labourers?\s+.{0,30}(?:deployed|shown)\s+on\s+different\s+works?\s+.{0,20}same\s+period",
            r"(?:works?|execution)\s+.{0,20}not\s+(?:executed|done|carried\s+out)\s+.{0,30}(?:payment|paid)",
            r"payment\s+.{0,20}made\s+.{0,30}(?:work|execution)\s+.{0,20}not\s+(?:done|executed)",
            r"advances?\s+.{0,30}(?:pending|not\s+(?:adjusted|settled))\s+.{0,20}(?:for|since)\s+.{0,15}(?:\d+\s+)?(?:years?|months?)",
            r"(?:temporary\s+)?advances?\s+.{0,20}(?:misuse|pending\s+for\s+adjustment)",
        ],
        FindingType.PROCEDURAL_LAPSE: [
            r"procedural\s+(lapse|irregularity|deviation)",
            r"without\s+(approval|sanction|authorization)",
            r"non-?adherence\s+to\s+(procedure|norm|guideline)",
            # State/Local: Procurement irregularities
            r"purchased\s+.{0,30}without\s+(?:inviting\s+)?(?:quotations?|tenders?)",
            r"without\s+inviting\s+(?:quotations?|tenders?)",
            r"(?:quotations?|tenders?)\s+.{0,20}not\s+(?:invited|obtained|called)",
            r"(?:stores?|materials?|items?)\s+.{0,30}purchased\s+.{0,20}without",
            # State/Local: Payment irregularities
            r"payment\s+.{0,30}without\s+(?:deducting|recovering)\s+(?:TDS|tax)",
            r"TDS\s+.{0,20}not\s+(?:deducted|recovered)",
            r"(?:was\s+)?(?:made|paid)\s+.{0,20}(?:to\s+)?(?:contractors?|firms?)\s+.{0,30}without\s+deducting\s+TDS",
            r"(?:made\s+)?(?:payment|paid)\s+.{0,30}contractors?\s+.{0,20}without\s+(?:deducting\s+)?TDS",
            r"payment\s+.{0,30}without\s+(?:obtaining\s+)?(?:receipt|acknowledgement|voucher)",
            r"vouchers?\s+.{0,20}not\s+(?:obtained|verified|attached)",
            r"irregular\s+(?:manner|payment|practice)",
            # State/Local: Administrative lapses
            r"administrative\s+approval\s+.{0,20}not\s+(?:obtained|taken)",
            r"technical\s+sanction\s+.{0,20}not\s+(?:obtained|taken)",
            r"estimates?\s+.{0,20}not\s+(?:prepared|obtained)",
            r"codal\s+formalities?\s+.{0,20}not\s+(?:completed|followed)",
            r"resolution\s+.{0,20}not\s+(?:passed|obtained)",
            # C4: Union-specific procedural lapse patterns
            r"(?:Ministry|Department|PSU|Company)\s+.{0,40}(?:released|paid|sanctioned)\s+.{0,30}without\s+(?:proper|adequate|necessary)\s+(?:verification|approval|sanction|scrutiny)",
            r"(?:work|contract|payment)\s+.{0,30}(?:executed|awarded|released)\s+.{0,30}without\s+(?:proper|due|necessary)\s+(?:approval|sanction|tender|verification)",
            r"(?:advance|payment)\s+.{0,30}(?:released|paid)\s+.{0,30}without\s+(?:obtaining|ensuring|verifying)\s+(?:bank\s+guarantee|security|performance)",
        ],
        FindingType.IDLE_ASSETS: [
            r"lying\s+idle\s+for\s+\d+\s+(?:months?|years?)",
            r"not\s+put\s+to\s+(?:use|productive\s+use)",
            r"not\s+made\s+operational",
            r"low\s+occupancy",
            r"poor\s+occupancy",
            r"remained\s+non-?functional",
            r"assets?\s+created\s+(?:were|was)\s+not\s+util[iz]ed",
            r"not\s+been\s+put\s+to\s+use",
            r"properties?\s+lying\s+idle",
            r"equipment\s+lying\s+idle",
            r"remained\s+idle",
            r"remained\s+unutili[sz]ed",
            r"lying\s+unused",
            # State/Local: Equipment/facility not in use patterns
            r"(?:equipment|machinery|vehicle|building|facility|plant)\s+.{0,30}not\s+(?:in\s+use|functional|operational|working)",
            r"(?:not\s+been\s+put\s+to\s+use|not\s+being\s+used|not\s+put\s+to\s+any\s+use)",
            r"(?:purchased|procured|constructed|installed)\s+.{0,30}but\s+.{0,30}(?:not|never)\s+(?:used|operational|functional|commissioned)",
            r"houses?\s+.{0,30}(?:not\s+in\s+use|not\s+.{0,20}habitation)",
            r"(?:vacant|unoccupied)\s+.{0,30}(?:building|premise|ward|bed|seat)",
        ],
        FindingType.NON_REALIZATION_OF_DUES: [
            r"non-?reali[sz]ation\s+of\s+dues",
            r"non-?recovery\s+of\s+dues",
            r"non-?collection\s+of\s+dues",
            r"non-?reali[sz]ation\s+of\s+rent",
            r"non-?recovery\s+of\s+revenue",
            r"non-?collection\s+of\s+revenue",
            r"outstanding\s+dues\s+amounting\s+to",
            r"unreali[sz]ed\s+dues",
            r"unrecovered\s+dues",
            r"dues\s+remained\s+unreali[sz]ed",
            r"dues\s+remained\s+unrecovered",
            r"arrears\s+of\s+revenue",
            r"arrears\s+amounting\s+to",
        ],
        FindingType.INCOMPLETE_INFRASTRUCTURE: [
            r"work\s+was\s+(?:stopped|stalled|abandoned)",
            r"could\s+not\s+be\s+completed",
            r"remained\s+incomplete",
            r"not\s+yet\s+completed",
            r"only\s+\d+%?\s+of\s+work\s+(?:executed|completed)",
            r"balance\s+works?\s+not\s+(?:taken\s+up|completed)",
            r"project\s+remained\s+incomplete",
            r"construction\s+remained\s+incomplete",
            r"inordinate\s+delay\s+in\s+completion",
            r"time\s+overrun",
            r"cost\s+overrun",
            # State/Local: Facility/infrastructure deficiency patterns
            r"without\s+(?:dedicated\s+space|proper|adequate|basic)\s+.{0,30}(?:facility|facilities|infrastructure)",
            r"not\s+(?:equipped|functional|operational|commissioned)\s+.{0,30}(?:as\s+required|as\s+envisaged|as\s+prescribed)",
            r"(?:toilets?|bathrooms?|kitchens?|drainage|water\s+supply)\s+.{0,30}not\s+(?:constructed|provided|available)",
            r"(?:building|facility|centre|hospital|school)\s+.{0,30}not\s+(?:constructed|completed|functional)",
            r"infrastructure\s+.{0,30}(?:deficien|inadequa|not\s+available|not\s+provided|lacking)",
            r"quality\s+(?:of\s+construction|of\s+work|of\s+material)\s+.{0,30}(?:deficient|sub[\s-]?standard|poor|below)",
            r"physical\s+verification\s+.{0,30}(?:revealed|disclosed|showed)\s+.{0,30}not\s+(?:completed|constructed|functional)",
        ],
        FindingType.ACCOUNTING_IRREGULARITY: [
            r"accounts?\s+not\s+(?:maintained|prepared|finali[sz]ed)",
            r"non-?reconciliation\s+of",
            r"unreconciled\s+balances?",
            r"differences?\s+in\s+balances?",
            r"PRIASoft\s+not\s+(?:maintained|updated|implemented)",
            r"non-?submission\s+of\s+utili[sz]ation\s+certificates?",
            r"UCs?\s+not\s+submitted",
            r"UCs?\s+pending",
            r"discrepanc(?:y|ies)\s+in\s+(?:figures?|records?|accounts?|books?|balances?)",
            r"non-?preparation\s+of\s+(?:accounts?|annual\s+accounts?|balance\s+sheet)",
            r"cash\s+book\s+not\s+maintained",
            r"stock\s+register\s+not\s+maintained",
            # State/Local: Broader record-keeping failures
            r"(?:records?|registers?|accounts?|books?|cash\s+book)\s+.{0,30}not\s+(?:maintained|updated|kept|prepared)",
            r"not\s+(?:maintained|kept|available)\s+.{0,30}(?:records?|registers?|log\s+book|stock\s+register)",
            r"data\s+.{0,30}not\s+(?:recorded|captured|available|maintained|entered)",
            r"no\s+(?:record|evidence|documentation)\s+.{0,30}(?:maintained|kept|available)",
            r"(?:discrepan|differen)(?:cy|ce|cies)\s+.{0,30}(?:between|in)\s+.{0,30}(?:records?|figures?|data|accounts?|statements?)",
            r"information\s+.{0,30}not\s+(?:made\s+available|furnished|provided|recorded)",
            r"(?:reconciliation|verification)\s+.{0,30}not\s+(?:carried\s+out|done|conducted)",
            r"separate\s+.{0,30}(?:cash\s+book|accounts?|register)\s+.{0,30}not\s+maintained",
            # State/Local: Stock/material accounting
            r"items?\s+.{0,30}not\s+accounted\s+for\s+in\s+(?:the\s+)?(?:stock\s+)?register",
            r"stores?\s+.{0,30}not\s+accounted\s+for\s+in\s+(?:stock\s+)?registers?",
            r"items?\s+of\s+stores?\s+.{0,60}not\s+accounted\s+for",
            r"(?:were|was)\s+not\s+accounted\s+for\s+in\s+(?:the\s+)?(?:stock\s+)?registers?",
            r"figures?\s+.{0,30}did\s+not\s+match",
            r"figures?\s+.{0,30}(?:were|was)\s+not\s+in\s+agreement",
            r"difference\s+.{0,20}(?:of|ranging)",
            # State/Local: Budget/estimates not prepared
            r"budget\s+estimates?\s+.{0,20}(?:not\s+prepared|not\s+passed)",
            r"(?:not\s+prepar|non-?prepar)(?:ed|ing|ation)\s+.{0,30}(?:budget|estimates?|accounts?)",
            r"important\s+registers?\s+.{0,30}not\s+maintained",
            # State/Local: UC submission gaps
            r"UCs?\s+.{0,20}(?:for\s+)?(?:an\s+)?amount\s+.{0,30}(?:only|pending)",
            r"submitted\s+UCs?\s+for\s+.{0,30}only",
            r"(?:\d+\s*per\s*cent|\d+%)\s+.{0,20}(?:UCs?|utili[sz]ation\s+certificates?)",
            # State/Local: Data upload/reporting failures
            r"(?:uploaded|reported)\s+.{0,30}(?:incorrect|wrong|erroneous|inflated|excess)",
            r"NAD\s+application\s+.{0,20}not\s+(?:being\s+)?(?:updated|uploaded)",
            r"claimed\s+.{0,30}(?:higher|excess|inflated)\s+.{0,20}(?:efficiency|percentage|per\s*cent)",
        ],
        FindingType.FUND_UTILIZATION_FAILURE: [
            r"funds?\s+remained\s+(?:unspent|unutili[sz]ed)",
            r"non-?release\s+of\s+funds?",
            r"non-?utili[sz]ation\s+of\s+funds?",
            r"blocking\s+of\s+funds?",
            r"Finance\s+Commission\s+funds?\s+(?:unspent|unutili[sz]ed|blocked|not\s+released)",
            r"grants?\s+remained\s+unutili[sz]ed",
            r"grants?\s+not\s+released",
            r"funds?\s+(?:were|was)\s+not\s+utili[sz]ed",
            r"funds?\s+could\s+not\s+be\s+utili[sz]ed",
            r"short\s+release\s+of\s+(?:funds?|grants?)",
            r"delayed\s+release\s+of\s+(?:funds?|grants?)",
            # State/Local: Additional fund utilization patterns
            r"expenditure\s+.{0,30}(?:confined|limited)\s+(?:mainly|only)\s+to",
            r"had\s+not\s+utili[sz]ed\s+any\s+amount\s+on",
            r"amount\s+.{0,30}(?:made\s+available|released)\s+.{0,30}not\s+(?:utili[sz]ed|spent)",
            r"(?:grant|grants|funds|amount)\s+.{0,30}not\s+(?:released|disbursed|transferred)",
            r"under[\s-]?utili[sz]ation\s+of\s+.{0,30}(?:funds?|grants?|resources?|allocation)",
            r"diversion\s+of\s+.{0,30}(?:funds?|grants?)\s+.{0,20}(?:from|to)",
            r"parking\s+of\s+.{0,30}(?:funds?|amount)\s+.{0,20}(?:in|with)",
            r"(?:savings?|surrender)\s+of\s+.{0,20}(?:crore|lakh)\s+.{0,20}(?:due\s+to|on\s+account\s+of)",
        ],
    }

    # Finding indicators for initial detection
    # C4: Extended with Union-specific observation patterns
    FINDING_INDICATORS = [
        r"audit\s+observed",
        r"audit\s+noticed",
        r"audit\s+found",
        r"it\s+was\s+observed",
        r"it\s+was\s+noticed",
        r"scrutiny\s+revealed",
        r"examination\s+revealed",
        r"review\s+revealed",
        r"test\s+check\s+revealed",
        # C4: Additional Union-specific indicators
        r"audit\s+disclosed",
        r"audit\s+examination\s+revealed",
        r"scrutiny\s+of\s+records\s+revealed",
        r"(?:the\s+)?(?:Ministry|Department|PSU|Company)\s+(?:failed|did\s+not)",
        r"resulted\s+in\s+(?:loss|short|non|extra|avoidable|irregular|wasteful)",
        r"this\s+resulted\s+in",
        r"the\s+above\s+(?:resulted|led)\s+to",
    ]

    # R4: Executive summary page thresholds by tier
    # Findings on early pages in overview/summary sections are flagged
    # to avoid double-counting with detailed findings later in the report
    EXEC_SUMMARY_PAGE_THRESHOLDS = {
        "union": 25,       # Union reports have longer prelims
        "state": 20,       # State reports
        "local_body": 15,  # Local body reports tend to be shorter
    }

    # R4: Keywords indicating executive summary/overview sections
    EXEC_SUMMARY_KEYWORDS = [
        "overview",
        "executive summary",
        "executive-summary",
        "preface",
        "summary of findings",
        "highlights",
        "at a glance",
        "key findings",
        "significant findings",
        "brief snapshot",
    ]

    def __init__(self, config: Optional[SemanticEnrichmentConfig] = None):
        """Initialize with compiled patterns and dependencies."""
        # Load from config if not provided
        if config is None:
            config = get_config().semantic_enrichment

        self.severity_thresholds = config.severity_thresholds
        self.finding_confidence_threshold = config.finding_confidence_threshold

        # Compile finding type patterns
        self._finding_type_patterns = {
            ft: [re.compile(p, re.IGNORECASE) for p in patterns]
            for ft, patterns in self.FINDING_TYPE_PATTERNS.items()
        }

        # Compile finding indicators
        self._finding_indicators = [
            re.compile(p, re.IGNORECASE) for p in self.FINDING_INDICATORS
        ]

        # Initialize monetary processor
        self._monetary_processor = MonetaryProcessor()

        # Initialize semantic pattern matcher
        self._semantic_matcher = semantic_patterns.SemanticPatternMatcher()

        # Current report type (set per document)
        self._current_report_type = "general"

    def set_report_type(self, report_type: str) -> None:
        """Set the current report type for type-aware extraction."""
        self._current_report_type = report_type

    def extract_findings(
        self,
        report_id: str,
        child_chunks: List[Dict],
        government_body_type: str = "union",
        parent_chunks: Optional[List[Dict]] = None,
    ) -> List[Finding]:
        """
        Extract audit findings from child chunks.

        Args:
            report_id: Unique report identifier
            child_chunks: List of child chunk dicts
            government_body_type: "union", "state", or "local_body"
            parent_chunks: Optional list of parent chunk dicts for source attribution

        Returns:
            List of Finding objects
        """
        findings = []
        finding_counter = 0

        # P1-13: Build parent lookup for source attribution
        # REMEDIATION §3.1: Handle both dict and Pydantic ParentChunk objects
        parent_lookup: Dict[str, Dict] = {}
        if parent_chunks:
            for p in parent_chunks:
                # Handle Pydantic objects (have chunk_id attribute)
                if hasattr(p, 'chunk_id'):
                    pid = p.chunk_id
                    # Convert to dict for uniform access
                    pdict = p.model_dump() if hasattr(p, 'model_dump') else p.dict()
                else:
                    # Handle dict
                    pid = p.get("chunk_id") or p.get("parent_chunk_id")
                    pdict = p

                if pid:
                    parent_lookup[pid] = pdict

        for chunk in child_chunks:
            # Only process paragraphs and lists
            if chunk.get("content_type") not in ("paragraph", "list"):
                continue

            content = chunk.get("content", "")

            # Skip very short content
            if len(content) < 50:
                continue

            # P0-07: Skip non-findings (Brief Snapshot, footnotes, etc.)
            if self._is_non_finding(content):
                continue

            # Use enhanced semantic pattern matcher
            patterns_matched = self._semantic_matcher.match_patterns(content)
            confidence_score = self._semantic_matcher.calculate_finding_confidence(
                content, patterns_matched, self._current_report_type
            )

            # Check if this looks like a finding
            # P0-07: Pass government_body_type for tier-specific taxonomy gates
            finding_type = self._detect_finding_type(content, government_body_type)
            # P0-01: Use extract_monetary_values_with_preference to apply
            # explicit-total preference heuristic
            monetary_values = self._monetary_processor.extract_monetary_values_with_preference(content)

            # Decision logic: Use confidence score from semantic matcher
            is_finding_by_confidence = confidence_score >= self.finding_confidence_threshold

            # Legacy indicators (for backward compatibility)
            has_monetary = len(monetary_values) > 0
            has_finding_type = finding_type != FindingType.OTHER
            has_indicator = any(p.search(content) for p in self._finding_indicators)

            # Decide if this is a finding (enhanced logic)
            is_finding = (
                is_finding_by_confidence
                or (has_monetary and (has_finding_type or has_indicator))
                or (has_finding_type and has_indicator)
            )

            if not is_finding:
                continue

            finding_counter += 1

            # Calculate total monetary value
            total_amount = sum(mv.normalized_inr for mv in monetary_values)

            # Determine severity based on amount (tier-specific thresholds)
            severity = self._calculate_severity(
                total_amount, finding_type, government_body_type
            )

            # P1-13: Extract source attribution from chunk and parent
            hierarchy = chunk.get("hierarchy", {})  # Direct field, not under metadata
            chapter = hierarchy.get("level_1") or hierarchy.get("level_2")

            # P1-13: Get section from parent's toc_entry for human-navigable location
            parent_id = chunk.get("parent_chunk_id")
            parent = parent_lookup.get(parent_id, {}) if parent_id else {}
            section = parent.get("toc_entry") or hierarchy.get("level_3") or hierarchy.get("level_4")

            # Generate summary
            summary = self._generate_summary(content)

            # Extract entities mentioned (deferred to entity extractor in orchestrator)
            entities: List[str] = []

            # Extract pattern types from matches
            pattern_types = [match.pattern_type for match in patterns_matched]

            # P0-01: Calculate max single monetary value for severity computation
            # monetary_value = max single amount (in paise)
            # monetary_value_crore = monetary_value / 1e9 (derived)
            max_monetary_value = (
                max(mv.normalized_inr for mv in monetary_values)
                if monetary_values
                else None
            )
            max_monetary_crore = (
                round(max_monetary_value / 1_000_000_000, 2)
                if max_monetary_value
                else None
            )

            # R4: Detect if finding is from executive summary section
            page = chunk.get("source_page_physical", 0)
            is_exec_summary = self._is_executive_summary_section(
                page=page,
                chapter=chapter,
                section=section,
                government_body_type=government_body_type,
            )

            finding = Finding(
                finding_id=f"{report_id}_finding_{finding_counter:03d}",
                report_id=report_id,
                text=content,
                summary=summary,
                finding_type=finding_type.value,
                severity=severity.value,
                monetary_values=[mv.to_dict() for mv in monetary_values],
                total_amount_inr=total_amount,
                # P0-01: Single monetary value fields (max amount from monetary_values)
                monetary_value=max_monetary_value,
                monetary_value_crore=max_monetary_crore,
                confidence=confidence_score,
                pattern_types=pattern_types,
                chapter=chapter,
                section=section,
                # P1-13: Direct field access for page (not under metadata)
                page=page,
                source_chunk_id=chunk.get("chunk_id", ""),
                entities_mentioned=entities,
                # R4: Executive summary flag
                is_executive_summary=is_exec_summary,
            )

            findings.append(finding)

        return findings

    def _detect_finding_type(
        self, text: str, government_body_type: str = "state"
    ) -> FindingType:
        """
        Detect the type of finding based on text patterns.

        P0-07 Enhancements:
        - Umbrella pattern detection ("Audit observed that...")
        - Tier-specific taxonomy gates
        - Falls back to existing pattern matching

        Args:
            text: The text to analyze
            government_body_type: "union", "state", or "local_body" for tier gates

        Returns:
            FindingType enum value
        """
        text_lower = text.lower()

        # P0-07: First try umbrella pattern with deficiency keyword extraction
        umbrella_type = self._detect_via_umbrella_pattern(text)
        if umbrella_type != FindingType.OTHER:
            # Apply tier-specific gate
            allowed_types = self.TIER_ALLOWED_TYPES.get(
                government_body_type, self.TIER_ALLOWED_TYPES["state"]
            )
            if umbrella_type in allowed_types:
                return umbrella_type

        # Fall back to existing pattern matching
        for finding_type, patterns in self._finding_type_patterns.items():
            for pattern in patterns:
                if pattern.search(text_lower):
                    # P0-07: Apply tier-specific gate
                    allowed_types = self.TIER_ALLOWED_TYPES.get(
                        government_body_type, self.TIER_ALLOWED_TYPES["state"]
                    )
                    if finding_type in allowed_types:
                        return finding_type
                    # If not allowed for this tier, continue searching
                    # for another pattern that is allowed
                    break

        return FindingType.OTHER

    def _detect_via_umbrella_pattern(self, text: str) -> FindingType:
        """
        P0-07: Detect finding type via "Audit observed/noticed that..." umbrella pattern.

        This captures the dominant CAG linguistic pattern where the finding type
        is indicated by a deficiency keyword following the observation phrase.

        Args:
            text: The text to analyze

        Returns:
            FindingType if detected via umbrella pattern, OTHER otherwise
        """
        match = self.AUDIT_OBSERVATION_PATTERN.search(text)
        if match:
            deficiency_keyword = match.group(1).lower().strip()

            # Try to map deficiency keyword to finding type
            for keyword, finding_type in self.DEFICIENCY_TO_TYPE_MAP.items():
                if keyword in deficiency_keyword:
                    return finding_type

        return FindingType.OTHER

    def _is_non_finding(self, text: str) -> bool:
        """
        P0-07 + R1: Check if text matches non-finding rejection patterns.

        These patterns identify content that looks like findings but isn't:
        - Brief Snapshot, footnotes, table/chart captions (P0-07)
        - Multi-year statistical data, background allocations (R1)

        R1 Enhancement: Check first 300 chars for contextual patterns that
        indicate the entire chunk is statistical/background data, not a finding.

        Args:
            text: The text to check

        Returns:
            True if text is a non-finding, False otherwise
        """
        # R1: Check intro context (first 300 chars) for statistical patterns
        # These patterns indicate the entire chunk is background data
        intro_text = text[:300] if len(text) > 300 else text

        for pattern in self.NON_FINDING_PATTERNS:
            # Check intro for R1 contextual patterns (multi-year spans, source data)
            if pattern.search(intro_text):
                return True

        return False

    def _is_executive_summary_section(
        self,
        page: int,
        chapter: Optional[str],
        section: Optional[str],
        government_body_type: str = "union",
    ) -> bool:
        """
        R4: Detect if a finding is from an executive summary/overview section.

        Executive summary findings typically appear on early pages and duplicate
        detailed findings that appear later in the report. Flagging them allows
        downstream processing to exclude them from totals to avoid double-counting.

        Detection criteria (both must be true):
        1. Page is below tier-specific threshold (union: 25, state: 20, local: 15)
        2. Chapter OR section contains executive summary keywords

        Args:
            page: Source page number (0-indexed physical page)
            chapter: Chapter heading (level_1 or level_2)
            section: Section heading (from parent's toc_entry)
            government_body_type: "union", "state", or "local_body"

        Returns:
            True if finding is from an executive summary section
        """
        # Get page threshold for this tier
        page_threshold = self.EXEC_SUMMARY_PAGE_THRESHOLDS.get(
            government_body_type, 20  # Default to state threshold
        )

        # First check: must be on an early page
        if page >= page_threshold:
            return False

        # Second check: chapter or section must contain exec summary keywords
        chapter_lower = (chapter or "").lower()
        section_lower = (section or "").lower()
        combined_text = f"{chapter_lower} {section_lower}"

        for keyword in self.EXEC_SUMMARY_KEYWORDS:
            if keyword in combined_text:
                return True

        return False

    def _calculate_severity(
        self,
        total_amount_inr: int,
        finding_type: FindingType,
        government_body_type: str = "union",
    ) -> Severity:
        """
        Calculate severity based on amount and finding type using tier-specific thresholds.

        Args:
            total_amount_inr: Total monetary amount in paise
            finding_type: Type of finding
            government_body_type: "union", "state", or "local_body"

        Returns:
            Severity level
        """
        # Convert paise to crore for comparison
        amount_crore = total_amount_inr / 10_000_000_00

        # Get tier-specific thresholds from config
        thresholds = self.severity_thresholds.get(
            government_body_type, self.severity_thresholds["union"]
        )

        # Amount-based severity using tier-specific thresholds
        if amount_crore >= thresholds["critical"]:
            return Severity.CRITICAL
        elif amount_crore >= thresholds["high"]:
            return Severity.HIGH
        elif amount_crore >= thresholds["medium"]:
            return Severity.MEDIUM

        # Type-based severity for low-amount findings
        if finding_type == FindingType.FRAUD_MISAPPROPRIATION:
            return Severity.HIGH
        elif finding_type in (
            FindingType.SYSTEM_DEFICIENCY,
            FindingType.NON_COMPLIANCE,
        ):
            return Severity.MEDIUM

        return Severity.LOW

    def _generate_summary(self, text: str, max_length: int = 200) -> str:
        """Generate a summary from text (first sentence or truncated)."""
        # Try to get first sentence
        sentence_end = re.search(r"[.!?]\s", text)
        if sentence_end and sentence_end.start() < max_length:
            return text[: sentence_end.start() + 1]

        # Otherwise truncate
        if len(text) <= max_length:
            return text

        # Find a good break point
        truncated = text[:max_length]
        last_space = truncated.rfind(" ")
        if last_space > max_length * 0.7:
            return truncated[:last_space] + "..."

        return truncated + "..."

    def _get_report_type_patterns(self) -> List[re.Pattern]:
        """Get compiled patterns for the current report type."""
        profile = report_type_profiles.get_profile(self._current_report_type)
        patterns = profile.get("finding_patterns", [])
        return [re.compile(p, re.IGNORECASE) for p in patterns]

    def _has_report_type_indicator(self, text: str) -> bool:
        """Check if text matches report-type specific finding patterns."""
        patterns = self._get_report_type_patterns()
        for pattern in patterns:
            if pattern.search(text):
                return True
        return False
