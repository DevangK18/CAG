"""
MonetaryProcessor: Extracts and normalizes monetary values from CAG audit report text.

Handles Indian currency formats:
- ₹847.71 crore, Rs. 5,00,000, `123.45 lakh, ₹1.5 lakh crore
- Normalizes all amounts to paise for precision comparisons

One tokenizer pass finds every amount: an optional currency prefix, a number with
Indian or Western grouping, and an optional (compound) unit. Amounts without a
currency prefix are only kept when they cannot be a quantity (see _accept_unit_only).

R2: Adds semantic context classification (FINDING_IMPACT, BUDGET_ALLOCATION, etc.)
R5: Primary amount identification for single-value reporting
"""

import re
import logging
from enum import Enum
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

PAISE_PER_CRORE = 1_000_000_000


class MonetaryContext(Enum):
    """
    R2: Semantic classification of monetary amounts.

    Helps distinguish between actual audit finding impacts vs background/reference data.
    """

    FINDING_IMPACT = "finding_impact"  # Loss, shortfall, excess, irregular expenditure
    BUDGET_ALLOCATION = "budget_allocation"  # Released, allocated, sanctioned amounts
    COMPARISON_TARGET = "comparison_target"  # "Against target of ₹X"
    HISTORICAL_DATA = "historical_data"  # Multi-year totals, trend data
    EXPENDITURE_ACTUAL = "expenditure_actual"  # What was actually spent
    RECOVERY_DUE = "recovery_due"  # Amount to be recovered
    UNKNOWN = "unknown"  # Could not determine context


FOOTNOTE_MARKER_RE = re.compile(r"\[\^\d{1,3}\]")

@dataclass
class MonetaryValue:
    """Structured representation of monetary amounts.

    normalized_paise is the canonical field; normalized_inr is the old name for the
    same paise value, kept as an alias until consumers move over.
    """

    raw_text: str  # Original text: "₹847.71 crore"
    amount: float  # Numeric value: 847.71
    unit: str  # Unit: "lakh crore", "crore", "lakh", "thousand", "rupees", ...
    normalized_paise: Optional[int] = None  # 847.71 crore -> 847710000000
    normalized_inr: Optional[int] = None  # alias of normalized_paise (paise, not rupees)
    currency: str = "INR"  # "USD" for $ amounts, which are not converted
    start: int = field(default=-1, repr=False, compare=False)
    end: int = field(default=-1, repr=False, compare=False)
    # Part of an earlier amount ("₹X crore, of which ₹Y crore ...")
    nested: bool = field(default=False, compare=False)

    def __post_init__(self):
        if self.normalized_paise is None:
            self.normalized_paise = self.normalized_inr
        if self.normalized_inr is None:
            self.normalized_inr = self.normalized_paise

    @property
    def crore(self) -> float:
        return (self.normalized_paise or 0) / PAISE_PER_CRORE

    def to_dict(self) -> Dict:
        d = {
            "raw_text": self.raw_text,
            "amount": self.amount,
            "unit": self.unit,
            "normalized_paise": self.normalized_paise,
            "normalized_inr": self.normalized_paise,
        }
        if self.currency != "INR":
            d["currency"] = self.currency
        if self.nested:
            d["nested"] = True
        return d


@dataclass
class ClassifiedMonetaryValue:
    """
    R2: Monetary value with semantic context classification.

    Wraps a MonetaryValue with additional context about its role
    in the finding (impact vs background data).
    """

    value: MonetaryValue
    context: MonetaryContext = MonetaryContext.UNKNOWN
    confidence: float = 0.5  # Confidence in classification (0-1)
    is_primary: bool = False  # R5: True if this is the primary finding amount
    context_snippet: str = ""  # Text snippet that determined the context

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "value": self.value.to_dict(),
            "context": self.context.value,
            "confidence": self.confidence,
            "is_primary": self.is_primary,
            "context_snippet": self.context_snippet,
        }


@dataclass
class _Token:
    start: int
    end: int
    currency: Optional[str]
    number: str
    unit: Optional[str]
    range_partner: bool = False


class MonetaryProcessor:
    """
    Extracts and normalizes monetary values from text.

    Used by FindingExtractor to identify financial impact of audit findings.
    """

    # Currency prefixes. Rs/INR/USD need a non-letter before them so that
    # "members 25", "ITRs9" and "years17" are not rupees (M4).
    _CURRENCY = (
        r"(?P<cur>₹|`|US\$|\$"
        r"|(?<![A-Za-z])(?:Rs|RS|rs)\.?(?![A-Za-z])"
        r"|(?<![A-Za-z])(?:INR|USD|Rupees?)(?![A-Za-z]))"
    )
    _NUMBER = r"(?P<num>\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    # Compound units first so "lakh crore" is not read as lakh (M1)
    _UNIT = (
        r"(?P<unit>(?:lakh|lac)s?\s+crores?|thousand\s+crores?|crores?|cr\.?"
        r"|(?:lakh|lac)s?|thousand|million|billion)(?![A-Za-z])"
    )
    TOKEN_PATTERN = re.compile(
        _CURRENCY + r"?\s*(?<![\d,])(?<!\d\.)" + _NUMBER + r"(?![\d])(?:\s*" + _UNIT + r")?",
        re.IGNORECASE,
    )

    # Any currency marker; used to decide whether a clause talks about money
    CURRENCY_MARKER = re.compile(
        r"₹|`\s*\d|(?<![A-Za-z])(?:Rs|INR)\.?(?![A-Za-z])|\brupees?\b", re.IGNORECASE
    )
    # Clause boundaries: ";", newline, or a full stop that ends a sentence
    CLAUSE_BOUNDARY = re.compile(r"[;\n]|(?<!Rs)(?<!No)\.(?=\s+[A-Z(])")
    RANGE_GAP = re.compile(r"\s*(?:to|-|–|—)\s*", re.IGNORECASE)
    # Words that may follow a unit-only amount; anything else is taken as the
    # noun being counted ("24.53 lakh candidates", "4.98 lakh sq. ft.") (M3)
    UNIT_ONLY_FOLLOWERS = frozenset(
        """was were is are has had have and or to in on at for from during by of
        towards toward against being been which that as only each per remained with
        out under over would could will may might shall should respectively while
        whereas but also till until up upto since after before into than so not
        still lying due paid spent released incurred received sanctioned allocated
        utilised utilized collected recovered deposited transferred available
        pending outstanding unspent unutilised unutilized approximately i.e viz""".split()
    )
    NESTED_CUE = re.compile(
        r"\b(?:of\s+which|out\s+of\s+which|which\s+includ\w*|includ(?:ing|es|ed)|"
        r"comprising|consisting\s+of)\b",
        re.IGNORECASE,
    )

    DENOMINATOR_CUE = re.compile(
        r"\b(?:out\s+of|against)\s+(?:the\s+|a\s+|an\s+)?(?:total\s+)?"
        r"(?:[A-Za-z/&()\-]+\s+){0,4}?(?:of\s+)?$",
        re.IGNORECASE,
    )

    # Year-like patterns to reject (e.g., "Rs 2003", "₹2024") when no unit follows
    YEAR_LIKE = re.compile(r"(?:19|20)\d{2}")

    # P0-01: Per-unit patterns to identify amounts that should be deprioritized
    # when an explicit total exists (e.g., "₹20,000 per beneficiary")
    PER_UNIT_PATTERN = re.compile(
        r"(?:₹|rs\.?)\s*[\d,]+(?:\.\d+)?\s*(?:crore|lakh)?\s*"
        r"(?:per|each|@)\s*(?:beneficiary|unit|person|head|month|year|day|kg|quintal|hectare|acre)",
        re.IGNORECASE
    )

    # P0-01: Explicit total patterns (e.g., "total of ₹X", "aggregating ₹X")
    EXPLICIT_TOTAL_PATTERN = re.compile(
        r"(?:total(?:ing|ling)?|aggregat(?:ing|e)|sum(?:ming)?)\s*(?:to|of)?\s*"
        r"(?:₹|rs\.?)\s*([\d,]+(?:\.\d+)?)\s*(crore|lakh)?",
        re.IGNORECASE
    )

    # R2: Context patterns for classifying monetary amounts.
    # The cue closest to an amount (within its own clause) decides its context.
    CONTEXT_PATTERNS: Dict[MonetaryContext, List[re.Pattern]] = {
        MonetaryContext.FINDING_IMPACT: [
            # Loss patterns
            re.compile(
                r"(?:loss|shortfall|short[\s-]?(?:fall|recovery|collection|realization|realisation|"
                r"assessment|levy|payment|deduction|release|deposit))"
                r"(?:\s+of\s+(?:revenue|interest|tax|royalty|duty|cess|stamp\s+duty))?\s+"
                r"(?:of|amounting\s+to|to\s+the\s+(?:extent|tune)\s+of|worth)",
                re.IGNORECASE
            ),
            # Excess/irregular patterns
            re.compile(
                r"(?:excess|irregular|avoidable|wasteful|infructuous|unfruitful|undue|unjustified|"
                r"inadmissible|unauthori[sz]ed|unadjusted|doubtful|extra|idle|unproductive|"
                r"over|double|fraudulent)[\s-]*"
                r"(?:expenditure|payment|advance|outgo|benefit|release|claim|investment|liability|"
                r"burden|cost|interest|amount)s?"
                # take the "of" too, so "expenditure of" (EXPENDITURE_ACTUAL) is not nearer
                r"(?:\s+(?:of|amounting\s+to|to\s+the\s+tune\s+of|worth))?",
                re.IGNORECASE
            ),
            # Result patterns
            re.compile(
                r"(?:resulted|resulting)\s+in\s+(?:a\s+|an\s+)?(?:loss|extra|avoidable|wasteful|excess|"
                r"short|non|under|blocking|idling|undue)",
                re.IGNORECASE
            ),
            # Non-recovery patterns
            re.compile(
                r"(?:non|under)[\s-]?(?:recovery|realization|collection|realisation|levy|deduction|"
                r"imposition|deposit|remittance|utili[sz]ation|submission\s+of\s+UCs?)\s+"
                r"(?:of|amounting)",
                re.IGNORECASE
            ),
            # Blocking/idle patterns
            re.compile(
                r"(?:blocking|locking|idle|idling|parking)\s+(?:of\s+)?(?:funds?|amount|capital|money)",
                re.IGNORECASE
            ),
            # Fraud/misappropriation patterns
            re.compile(
                r"(?:fraud|misappropriation|embezzlement|suspected\s+fraud|defalcation|diversion|"
                r"misutili[sz]ation|pilferage)",
                re.IGNORECASE
            ),
            # Penalty/interest burden
            re.compile(
                r"(?:penalty|penal\s+interest|interest|damages?)\s+(?:of|amounting\s+to|to\s+the\s+tune\s+of)",
                re.IGNORECASE
            ),
            # Unspent / unutilised / not recovered funds
            re.compile(
                r"(?:remained|remaining|lying|kept)\s+(?:unspent|unutili[sz]ed|idle|unadjusted|"
                r"unrecovered|unreali[sz]ed|outstanding|un-?reconciled)",
                re.IGNORECASE
            ),
            re.compile(
                r"(?:unspent|unutili[sz]ed|unreconciled|unadjusted|unrecovered|unreali[sz]ed)\s+"
                r"(?:balance|amount|funds?|grants?)",
                re.IGNORECASE
            ),
            # Differences, savings and lapses that are the finding themselves
            re.compile(
                r"(?:difference|discrepanc(?:y|ies)|mismatch|variance|savings?|surrender(?:ed)?|lapsed|"
                r"overstate[sd]|understate[sd]|overpaid|overpayment|unspent\s+balances?)\s+"
                r"(?:of|by|amounting\s+to|to\s+the\s+tune\s+of)",
                re.IGNORECASE
            ),
            # "₹X had lapsed", "₹X was blocked"; "the remaining amount of ₹X"
            re.compile(
                r"(?:had|has|have|was|were)\s+(?:been\s+)?(?:lapsed|blocked|diverted|"
                r"misutili[sz]ed|parked|written\s+off|wasted)",
                re.IGNORECASE
            ),
            re.compile(
                r"(?:remaining|unspent|leaving\s+a)\s+(?:amount|balance)\s+of|balance\s+amount\s+of",
                re.IGNORECASE
            ),
            re.compile(
                r"not\s+(?:been\s+)?(?:recovered|realised|realized|collected|deposited|remitted|"
                r"utili[sz]ed|adjusted|accounted|refunded|levied|imposed|deducted)",
                re.IGNORECASE
            ),
        ],
        MonetaryContext.BUDGET_ALLOCATION: [
            # Money received, released or invested by an entity (background)
            re.compile(
                r"\b(?:released|received|invested|provided|allotted|transferred|drawn)\b"
                r"(?:\s+(?:funds?|grants?|GIA|an?\s+amount|amounting\s+to|of|only))*",
                re.IGNORECASE
            ),
            # Released/allocated patterns
            re.compile(
                r"(?:released|allocated|sanctioned|budgeted|earmarked|provided)\s+"
                r"(?:grants?|funds?|amount|GIA|budget)",
                re.IGNORECASE
            ),
            # Passive release patterns
            re.compile(
                r"(?:grants?|funds?|GIA|budget)\s+(?:of\s+)?[₹Rs.]*[\d,]+\s*(?:crore|lakh)?\s+"
                r"(?:was|were)\s+(?:released|allocated|sanctioned)",
                re.IGNORECASE
            ),
            # Total allocation patterns
            re.compile(
                r"total\s+(?:allocation|budget|sanctioned\s+amount|outlay)",
                re.IGNORECASE
            ),
            # Government/department releases
            re.compile(
                r"(?:government|department|ministry)\s+(?:had\s+)?(?:released|allocated|sanctioned)",
                re.IGNORECASE
            ),
        ],
        MonetaryContext.COMPARISON_TARGET: [
            # Against target patterns
            re.compile(
                r"(?:against|compared\s+to|as\s+against|vis[\s-]?[aà][\s-]?vis)\s+"
                r"(?:the\s+)?(?:target|sanction|approved|budgeted|estimated)",
                re.IGNORECASE
            ),
            # Target / reference amounts: "estimated cost of ₹X", "budget provision of ₹X"
            re.compile(
                r"(?:target|sanction|(?:approved|estimated|tendered|project|revised|awarded\s+at\s+a|"
                r"contract|order|total)\s+(?:cost|value|amount)|value\s+of\s+the\s+order|"
                r"budget(?:\s+provision)?|provision|closing\s+balance|opening\s+balance)\s+"
                r"(?:of|was|being|as\s+per\s+[\w\s]{0,25}was)",
                re.IGNORECASE
            ),
            # Shortfall against patterns
            re.compile(
                r"(?:shortfall|deficit|gap)\s+(?:against|compared\s+to|vis[\s-]?[aà][\s-]?vis)",
                re.IGNORECASE
            ),
        ],
        MonetaryContext.HISTORICAL_DATA: [
            # Multi-year span patterns
            re.compile(
                r"during\s+(?:the\s+)?(?:FYs?\s+)?\d{4}[-–]\d{2,4}\s+to\s+\d{4}",
                re.IGNORECASE
            ),
            re.compile(
                r"during\s+(?:the\s+)?(?:financial\s+)?years?\s+\d{4}\s*[-–]\s*\d{4}",
                re.IGNORECASE
            ),
            re.compile(
                r"from\s+(?:FYs?\s+)?\d{4}[-–]\d{2,4}\s+to\s+\d{4}",
                re.IGNORECASE
            ),
            re.compile(
                r"(?:for|during)\s+the\s+period\s+(?:from\s+)?(?:FYs?\s+)?\d{4}",
                re.IGNORECASE
            ),
            # Over years pattern
            re.compile(
                r"over\s+(?:the\s+)?(?:last|past|previous)\s+\d+\s+(?:years?|FYs?)",
                re.IGNORECASE
            ),
        ],
        MonetaryContext.EXPENDITURE_ACTUAL: [
            # Expenditure incurred patterns
            re.compile(
                r"(?:expenditure|spending|outlay)\s+(?:incurred|made|of)",
                re.IGNORECASE
            ),
            # Amount spent patterns
            re.compile(
                r"(?:amount|funds?)\s+(?:spent|utilized|utilised|expended)",
                re.IGNORECASE
            ),
            # Actual expenditure patterns
            re.compile(
                r"actual\s+(?:expenditure|spending|cost)",
                re.IGNORECASE
            ),
        ],
        MonetaryContext.RECOVERY_DUE: [
            # Recovery due patterns
            re.compile(
                r"(?:recovery|amount)\s+(?:due|pending|recoverable|to\s+be\s+recovered)",
                re.IGNORECASE
            ),
            # Needs to be recovered patterns
            re.compile(
                r"(?:needs?|required)\s+to\s+be\s+recovered",
                re.IGNORECASE
            ),
            # Outstanding amount patterns
            re.compile(
                r"(?:outstanding|pending|recoverable)\s+(?:amount|dues?|recovery|arrears|tax|rent|fees?)",
                re.IGNORECASE
            ),
            re.compile(r"arrears\s+(?:of|amounting)", re.IGNORECASE),
        ],
    }

    # Contexts in priority order, used to break ties between equally close cues
    CONTEXT_PRIORITY = [
        MonetaryContext.FINDING_IMPACT,
        MonetaryContext.RECOVERY_DUE,
        MonetaryContext.COMPARISON_TARGET,
        MonetaryContext.BUDGET_ALLOCATION,
        MonetaryContext.HISTORICAL_DATA,
        MonetaryContext.EXPENDITURE_ACTUAL,
    ]
    BEFORE_CUE_BIAS = 15  # chars
    IMPACT_CONTEXTS = (MonetaryContext.FINDING_IMPACT, MonetaryContext.RECOVERY_DUE)

    # Multipliers for normalization (to paise for precision)
    UNIT_MULTIPLIERS = {
        "lakh crore": 10**14,  # 1 lakh crore = 10^12 rupees
        "thousand crore": 10**12,  # 1 thousand crore = 10^10 rupees
        "billion": 10**11,  # 1 billion = 10^9 rupees = 100 crore
        "crore": 10**9,  # 1 crore = 10^7 rupees
        "million": 10**8,  # 1 million = 10^6 rupees = 10 lakh
        "lakh": 10**7,  # 1 lakh = 10^5 rupees
        "thousand": 10**5,  # 1 thousand = 10^3 rupees
        None: 100,  # Default: assume rupees, convert to paise
        "": 100,
        "rupees": 100,
    }

    def extract_monetary_values(
        self, text: str, dedup_tolerance: Optional[float] = None
    ) -> List[MonetaryValue]:
        """
        Extract all monetary values from text, in order of appearance.

        Distinct mentions are all kept, even when equal: only one value per text span
        exists (M6). dedup_tolerance is accepted for backward compatibility and ignored.
        """
        if not text:
            return []
        # Footnote markers ("₹ 25[^2] crore") are blanked, keeping offsets (B-6-19)
        text = FOOTNOTE_MARKER_RE.sub(lambda m: " " * len(m.group()), text)
        tokens = [self._token(m) for m in self.TOKEN_PATTERN.finditer(text)]
        tokens = [t for t in tokens if t.currency or t.unit]
        self._share_range_units(text, tokens)

        values: List[MonetaryValue] = []
        for i, tok in enumerate(tokens):
            if not self._accept(text, tok, tokens[i + 1] if i + 1 < len(tokens) else None):
                continue
            try:
                amount = float(tok.number.replace(",", ""))
            except ValueError:
                continue
            unit = self._canonical_unit(tok.unit)
            usd = self._is_usd(tok.currency)
            # Dollar amounts are not converted: they carry no paise value
            paise = None if usd else self.normalize_to_paise(amount, unit)
            if paise is not None:
                self._validate_monetary_value(paise, text[tok.start:tok.end])
            values.append(
                MonetaryValue(
                    raw_text=text[tok.start:tok.end].strip(),
                    amount=amount,
                    unit=unit or ("dollars" if usd else "rupees"),
                    normalized_paise=paise,
                    currency="USD" if usd else "INR",
                    start=tok.start,
                    end=tok.end,
                )
            )
        self._mark_nested(text, values)
        return values

    @staticmethod
    def _token(m: re.Match) -> _Token:
        return _Token(
            start=m.start("cur") if m.group("cur") else m.start("num"),
            end=m.end(),
            currency=m.group("cur"),
            number=m.group("num"),
            unit=m.group("unit"),
        )

    @staticmethod
    def _is_usd(currency: Optional[str]) -> bool:
        return bool(currency) and ("$" in currency or currency.upper() == "USD")

    def _share_range_units(self, text: str, tokens: List[_Token]) -> None:
        """M5: "₹5 to ₹10 crore" and "between ₹2.5 and 4.0 crore" share the unit."""
        for a, b in zip(tokens, tokens[1:]):
            if a.unit or not b.unit or not (a.currency or b.currency):
                continue
            gap = text[a.end:b.start]
            is_range = bool(self.RANGE_GAP.fullmatch(gap)) or (
                re.fullmatch(r"\s*and\s*", gap, re.IGNORECASE)
                and re.search(r"\bbetween\s*$", text[max(0, a.start - 20):a.start], re.IGNORECASE)
            )
            if not is_range:
                continue
            try:
                lo = float(a.number.replace(",", ""))
                hi = float(b.number.replace(",", ""))
            except ValueError:
                continue
            if lo <= hi:
                a.unit = b.unit
                b.range_partner = True

    def _accept(self, text: str, tok: _Token, nxt: Optional[_Token]) -> bool:
        cur = (tok.currency or "").upper()
        if cur:
            if cur == "`" and not tok.unit:
                return False  # backticks are formatting unless a unit follows
            if not tok.unit and "," not in tok.number and "." not in tok.number \
                    and self.YEAR_LIKE.fullmatch(tok.number):
                return False
            if self._is_usd(cur):
                # "USD 5 million (₹ 41 crore)": the rupee figure is the same amount
                if re.match(r"\s*\(\s*(?:₹|Rs|INR)", text[tok.end:tok.end + 12], re.IGNORECASE):
                    return False
            return True
        if tok.range_partner:
            return True
        return self._accept_unit_only(text, tok)

    def _accept_unit_only(self, text: str, tok: _Token) -> bool:
        """M3: "45.67 crore" without ₹ is money only if it cannot be a quantity."""
        if tok.start > 0 and text[tok.start - 1].isalpha():
            return False  # footnote digits glued to a word
        follow = re.match(r"(?:\s*\([^()]{0,60}\))?\s*([A-Za-z][A-Za-z.\-]*)", text[tok.end:tok.end + 80])
        if follow and follow.group(1).lower().rstrip(".") not in self.UNIT_ONLY_FOLLOWERS:
            return False
        # The clause must already be about money: "₹ 24.30 crore and 5.6 crore", but
        # not "1.20 lakh (66 per cent) were provided with assistance of ₹155.77 lakh"
        start, _ = self._clause_bounds(text, tok.start, tok.end)
        return bool(self.CURRENCY_MARKER.search(text[start:tok.start]))

    def _clause_bounds(self, text: str, start: int, end: int) -> Tuple[int, int]:
        lo = 0
        for m in self.CLAUSE_BOUNDARY.finditer(text, 0, start):
            lo = m.end()
        m = self.CLAUSE_BOUNDARY.search(text, end)
        return lo, (m.start() if m else len(text))

    def _mark_nested(self, text: str, values: List[MonetaryValue]) -> None:
        """Flag parts of an earlier amount ("₹X crore, of which ₹Y crore")."""
        for prev, cur in zip(values, values[1:]):
            gap = text[prev.end:cur.start]
            if len(gap) <= 80 and not self.CLAUSE_BOUNDARY.search(gap) and self.NESTED_CUE.search(gap):
                cur.nested = True
            elif prev.nested and len(gap) <= 30 and re.fullmatch(r"[\s,]*(?:and\s*)?", gap):
                cur.nested = True  # "of which ₹A crore and ₹B crore"

    @staticmethod
    def _canonical_unit(unit: Optional[str]) -> Optional[str]:
        if not unit:
            return None
        u = re.sub(r"\s+", " ", unit.lower()).rstrip(".")
        u = re.sub(r"\blacs?\b", "lakh", u)
        u = re.sub(r"\blakhs\b", "lakh", u)
        u = re.sub(r"\bcrores\b", "crore", u)
        return "crore" if u == "cr" else u

    def normalize_to_paise(self, amount: float, unit: Optional[str]) -> int:
        """
        Normalize a monetary amount to paise (1/100 of a rupee).

        Args:
            amount: Numeric amount
            unit: Unit string (crore, lakh, thousand, etc.) or None

        Returns:
            Amount in paise as integer
        """
        multiplier = self.UNIT_MULTIPLIERS.get(self._canonical_unit(unit), 100)
        # round, not int(): 847.71 * 1e9 is 847709999999.99 in floating point
        return int(round(amount * multiplier))

    def _validate_monetary_value(self, normalized_paise: int, source: str) -> None:
        """
        Validate a monetary value for correctness.

        Raises:
            TypeError: if the value is not an int
            ValueError: if the value is negative
        """
        # M17: real checks, not assert (asserts vanish under python -O)
        if not isinstance(normalized_paise, int) or isinstance(normalized_paise, bool):
            raise TypeError(f"normalized_paise must be int, got {type(normalized_paise)}")
        if normalized_paise < 0:
            raise ValueError(f"normalized_paise must be non-negative, got {normalized_paise}")

        # Sanity check: ₹10 lakh crore in paise = 1e17, several times a Union budget
        if normalized_paise > 1e17:
            logger.warning(
                f"Implausibly large normalized_paise={normalized_paise} from '{source}'"
            )

    def _apply_explicit_total_preference(
        self, text: str, monetary_values: List[MonetaryValue]
    ) -> List[MonetaryValue]:
        """
        P0-01: When text has per-unit amounts and an explicit total ("₹20,000 per
        beneficiary ... totalling ₹55.60 crore"), drop the per-unit amounts.
        """
        if len(monetary_values) <= 1 or not self.PER_UNIT_PATTERN.search(text):
            return monetary_values

        per_unit_spans = [m.span() for m in self.PER_UNIT_PATTERN.finditer(text)]
        if not self.EXPLICIT_TOTAL_PATTERN.search(text):
            return monetary_values
        kept = [
            mv for mv in monetary_values
            if not any(s <= mv.start < e for s, e in per_unit_spans)
        ]
        return kept or monetary_values

    def extract_monetary_values_with_preference(
        self, text: str, dedup_tolerance: Optional[float] = None
    ) -> List[MonetaryValue]:
        """
        P0-01: Extract monetary values with explicit-total preference.

        Args:
            text: Text to search for monetary values
            dedup_tolerance: ignored (kept for backward compatibility)

        Returns:
            List of MonetaryValue objects with preference applied
        """
        values = self.extract_monetary_values(text)
        return self._apply_explicit_total_preference(text, values)

    def _classify_context(
        self, text: str, mv: MonetaryValue, window_chars: int = 150,
        prev_end: int = 0, next_start: Optional[int] = None,
    ) -> Tuple[MonetaryContext, float, str]:
        """
        R2: Classify the semantic context of a monetary value.

        The cue nearest the amount wins. Cues are searched only between the previous
        and the next amount in the same clause, so "loss of ₹5 crore against the
        target of ₹10 crore" does not call ₹10 crore a loss. "Out of ₹X" and
        "against ... of ₹X" mark a denominator.

        Returns:
            Tuple of (context, confidence, snippet)
        """
        pos = mv.start if mv.start >= 0 else text.find(mv.raw_text)
        if pos < 0:
            return MonetaryContext.UNKNOWN, 0.3, ""
        end = mv.end if mv.end >= 0 else pos + len(mv.raw_text)
        clause_lo, clause_hi = self._clause_bounds(text, pos, end)
        lo = max(prev_end, clause_lo, pos - window_chars)
        before = text[lo:pos]

        # "out of (the total) ₹X", "against the budget provision of ₹X": a denominator
        denom = self.DENOMINATOR_CUE.search(before)
        if denom:
            return MonetaryContext.COMPARISON_TARGET, 0.90, denom.group(0)

        hi = min(clause_hi, end + window_chars)
        if next_start is not None and next_start > end:
            hi = min(hi, next_start)  # the next amount's cue is not ours
        after = text[end:hi]

        # The nearest cue wins; a cue before the amount gets a small head start
        # ("loss of ₹X" vs "₹X remained unspent")
        b = self._nearest_cue(before, from_end=True)
        a = self._nearest_cue(after, from_end=False)
        b_dist = len(before) - b[1].end() if b else None
        a_dist = a[1].start() if a else None
        if b and (a is None or b_dist <= a_dist + self.BEFORE_CUE_BIAS):
            conf = 0.90 if b_dist <= 50 else 0.75
            return b[0], conf, b[1].group(0)
        if a:
            return a[0], 0.60, a[1].group(0)

        snippet = text[max(0, pos - 50):end + 50]
        return MonetaryContext.UNKNOWN, 0.3, snippet[:50]

    def _nearest_cue(self, window: str, from_end: bool):
        best = None
        for rank, context in enumerate(self.CONTEXT_PRIORITY):
            for pattern in self.CONTEXT_PATTERNS.get(context, []):
                for match in pattern.finditer(window):
                    dist = len(window) - match.end() if from_end else match.start()
                    key = (dist, rank)
                    if best is None or key < best[0]:
                        best = (key, context, match)
        return (best[1], best[2]) if best else None

    def extract_with_context(
        self, text: str, dedup_tolerance: Optional[float] = None
    ) -> List[ClassifiedMonetaryValue]:
        """
        R2: Extract monetary values with semantic context classification.

        Returns:
            List of ClassifiedMonetaryValue objects with context, one marked primary
        """
        raw_values = self.extract_monetary_values_with_preference(text)
        if not raw_values:
            return []

        classified = []
        prev_end = 0
        for i, mv in enumerate(raw_values):
            next_start = raw_values[i + 1].start if i + 1 < len(raw_values) else None
            context, confidence, snippet = self._classify_context(
                text, mv, prev_end=prev_end, next_start=next_start
            )
            prev_end = mv.end
            classified.append(
                ClassifiedMonetaryValue(
                    value=mv,
                    context=context,
                    confidence=confidence,
                    is_primary=False,  # Will be set by _identify_primary
                    context_snippet=snippet,
                )
            )

        self._identify_primary(classified, text)
        return classified

    def _identify_primary(
        self, classified: List[ClassifiedMonetaryValue], text: str
    ) -> None:
        """
        R5: Mark the primary finding amount (one per text), instead of summing.

        Selection priority (rupee amounts only; nested "of which" parts last):
        1. Explicit totals ("total of ₹X", "aggregating to ₹X")
        2. FINDING_IMPACT context amounts (strongest cue, then earliest mention)
        3. RECOVERY_DUE amounts
        4. Maximum non-historical/non-budget amount
        5. Fallback: maximum overall amount
        """
        if not classified:
            return
        pool = [cv for cv in classified if cv.value.currency == "INR"] or classified
        top = [cv for cv in pool if not cv.value.nested] or pool

        def pick(cv: ClassifiedMonetaryValue, why: str) -> None:
            cv.is_primary = True
            logger.debug(f"R5: Primary amount ({why}): {cv.value.raw_text}")

        # Priority 1: explicit total in text
        for m in self.EXPLICIT_TOTAL_PATTERN.finditer(text):
            for cv in top:
                if cv.value.start <= m.end() <= cv.value.end + 1:
                    return pick(cv, "explicit total")

        # Priority 2/3: impact, then recovery
        for context in self.IMPACT_CONTEXTS:
            hits = [cv for cv in top if cv.context == context]
            if hits:
                # strongest cue first, then the earliest mention: CAG states the lead impact first
                hits.sort(key=lambda x: (-x.confidence, x.value.start))
                return pick(hits[0], context.value)

        # Priority 4: max non-historical/non-budget amount
        eligible = [
            cv for cv in top
            if cv.context not in (
                MonetaryContext.HISTORICAL_DATA,
                MonetaryContext.BUDGET_ALLOCATION,
                MonetaryContext.COMPARISON_TARGET,
            )
        ]
        if eligible:
            return pick(max(eligible, key=lambda x: x.value.normalized_paise or 0), "max eligible")

        # Priority 5: max overall
        pick(max(top, key=lambda x: x.value.normalized_paise or 0), "fallback max")

    def get_primary_amount(
        self, text: str, dedup_tolerance: Optional[float] = None
    ) -> Optional[ClassifiedMonetaryValue]:
        """
        R5: Extract and return only the primary monetary amount.

        Returns:
            The primary ClassifiedMonetaryValue, or None if no amounts found
        """
        classified = self.extract_with_context(text)
        for cv in classified:
            if cv.is_primary:
                return cv
        return classified[0] if classified else None

    def impact_total_paise(self, classified: List[ClassifiedMonetaryValue]) -> int:
        """
        Sum of the impact amounts in one text (M9).

        Only impact/recovery-classified rupee amounts count, nested "of which" parts
        are excluded, a repeated figure counts once, and the primary amount is always
        included, so the total is never below the primary amount.
        """
        seen = set()
        total = 0
        for cv in classified:
            mv = cv.value
            if mv.currency != "INR" or mv.nested:
                continue
            if cv.is_primary or cv.context in self.IMPACT_CONTEXTS:
                if mv.normalized_paise not in seen:
                    seen.add(mv.normalized_paise)
                    total += mv.normalized_paise
        if not seen:
            primary = next((cv for cv in classified if cv.is_primary), None)
            total = (primary.value.normalized_paise or 0) if primary else 0
        return total
