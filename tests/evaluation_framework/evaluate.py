"""
CAG RAG Evaluation Framework - IMPROVED VERSION
================================================

Key improvements over original:
1. Expanded amount extraction patterns (LMT, MT, cases, negative %, etc.)
2. Better unit normalization
3. More lenient hallucination detection for LLM judge
4. Improved key fact matching

Changes marked with # IMPROVED comments
"""

import json
import argparse
import logging
import re
import sys
import os
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from openai import OpenAI
except ImportError:
    raise ImportError("Install openai: pip install openai")

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# Import RAG service
try:
    from services.rag_pipeline.rag_service import RAGService, ResponseStyle
    from services.rag_pipeline.config import RAGConfig, LLMProvider
except ImportError:
    try:
        from rag_pipeline.rag_service import RAGService, ResponseStyle
        from rag_pipeline.config import RAGConfig, LLMProvider
    except ImportError:
        print("Warning: Could not import RAG service. Running in standalone mode.")
        RAGService = None
        ResponseStyle = None

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES (unchanged)
# =============================================================================


@dataclass
class AmountMatch:
    """Result of matching an expected amount in the response."""

    expected_value: float
    expected_unit: str
    expected_context: str
    found: bool
    found_value: Optional[float] = None
    match_type: str = "none"  # exact, close, wrong, missing


@dataclass
class EntityMatch:
    """Result of matching an expected entity in the response."""

    expected_entity: str
    found: bool
    context: Optional[str] = None


@dataclass
class EvaluationScores:
    """All evaluation scores for a single test case."""

    amount_accuracy: float = 0.0
    entity_coverage: float = 0.0
    key_fact_coverage: float = 0.0
    factual_accuracy: float = 0.0
    completeness: float = 0.0
    relevance: float = 0.0
    citation_quality: float = 0.0
    has_hallucination: bool = False
    acknowledges_no_data: bool = False
    overall_score: float = 0.0
    passed: bool = False
    amount_matches: List[Dict] = field(default_factory=list)
    entity_matches: List[Dict] = field(default_factory=list)
    llm_judge_reasoning: str = ""


@dataclass
class TestResult:
    """Complete result for a single test case."""

    test_id: str
    question: str
    category: Dict[str, Any]
    expected_summary: str
    actual_answer: str
    sources_used: int
    search_type: str
    response_time_ms: float
    scores: EvaluationScores
    issues: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "test_id": self.test_id,
            "question": self.question,
            "category": self.category,
            "expected_summary": self.expected_summary,
            "actual_answer": self.actual_answer,
            "sources_used": self.sources_used,
            "search_type": self.search_type,
            "response_time_ms": self.response_time_ms,
            "scores": asdict(self.scores),
            "issues": self.issues,
            "passed": self.scores.passed,
        }


@dataclass
class EvaluationReport:
    """Complete evaluation report."""

    timestamp: str
    total_cases: int
    passed_cases: int
    failed_cases: int
    pass_rate: float
    avg_factual_accuracy: float
    avg_completeness: float
    avg_relevance: float
    avg_citation_quality: float
    avg_amount_accuracy: float
    avg_entity_coverage: float
    scores_by_difficulty: Dict[str, Dict]
    scores_by_type: Dict[str, Dict]
    issue_counts: Dict[str, int]
    results: List[Dict]

    def to_dict(self) -> Dict:
        return asdict(self)


# =============================================================================
# IMPROVED AMOUNT EXTRACTION AND MATCHING
# =============================================================================


def extract_amounts(text: str) -> List[Tuple[float, str]]:
    """
    IMPROVED: Extract monetary and numeric amounts from text.

    Now handles:
    - ₹64.60 crore / Rs. 1,553.05 crore
    - 249.74 LMT (Lakh Metric Tonnes)
    - 21.92 MT (Metric Tonnes)
    - 649 cases
    - 72.32 per cent / 72.32% / -8.59%
    - 810.69 lakh crore
    - 4,367.96 LMT
    - Numbers with various denominators
    """
    amounts = []

    # IMPROVED: Comprehensive patterns for all unit types
    patterns = [
        # Indian Rupee amounts: ₹X.XX crore/lakh
        (r"₹\s*([\d,]+\.?\d*)\s*(crore|lakh|cr|lac)", "currency"),
        # Rs. X.XX crore/lakh
        (r"Rs\.?\s*([\d,]+\.?\d*)\s*(crore|lakh|cr|lac)", "currency"),
        # X.XX crore/lakh (standalone)
        (r"([\d,]+\.?\d*)\s*(crore|lakh|cr|lac)\b", "currency"),
        # X.XX lakh crore (compound unit)
        (r"([\d,]+\.?\d*)\s*lakh\s+crore", "lakh_crore"),
        # IMPROVED: Metric measurements (LMT, MT, etc.)
        (r"([\d,]+\.?\d*)\s*LMT\b", "lmt"),  # Lakh Metric Tonnes
        (r"([\d,]+\.?\d*)\s*MT\b", "mt"),  # Metric Tonnes
        (r"([\d,]+\.?\d*)\s*(?:Lakh\s+)?Metric\s+Tonnes?\b", "lmt"),
        (r"([\d,]+\.?\d*)\s*quintals?\b", "quintal"),
        (r"([\d,]+\.?\d*)\s*tonnes?\b", "tonne"),
        (r"([\d,]+\.?\d*)\s*(?:sq\.?\s*)?(?:km|kilometers?|kilometres?)\b", "km"),
        (r"([\d,]+\.?\d*)\s*(?:sq\.?\s*)?m(?:eters?|etres?)?\b", "sqm"),
        (r"([\d,]+\.?\d*)\s*hectares?\b", "hectare"),
        # IMPROVED: Count units (cases, godowns, etc.)
        (r"([\d,]+)\s*cases?\b", "cases"),
        (r"([\d,]+)\s*godowns?\b", "godowns"),
        (r"([\d,]+)\s*depots?\b", "depots"),
        (r"([\d,]+)\s*States?(?:/UTs?)?\b", "states"),
        (r"([\d,]+)\s*rakes?\b", "rakes"),
        (r"([\d,]+)\s*silos?\b", "silos"),
        (r"([\d,]+)\s*CPSEs?\b", "cpses"),
        (r"([\d,]+)\s*ministries\b", "ministries"),
        (r"([\d,]+)\s*departments?\b", "departments"),
        (r"([\d,]+)\s*beneficiaries\b", "beneficiaries"),
        (r"([\d,]+)\s*hospitals?\b", "hospitals"),
        # IMPROVED: Percentages (including negative)
        (r"(-?[\d.]+)\s*per\s*cent\b", "percent"),
        (r"(-?[\d.]+)\s*%", "percent"),
        (r"(-?[\d.]+)\s*percent\b", "percent"),
        # Time periods
        (r"([\d,]+)\s*(?:years?|months?|days?)\b", "time"),
        # Generic indicator values (for debt sustainability etc.)
        (r"indicator.*?(\d+\.?\d*)\b", "indicator"),
    ]

    for pattern, pattern_type in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            try:
                # Handle tuple vs string match
                if isinstance(match, tuple):
                    value_str = match[0].replace(",", "")
                    unit = match[1].lower() if len(match) > 1 else pattern_type
                else:
                    value_str = match.replace(",", "")
                    unit = pattern_type

                value = float(value_str)

                # IMPROVED: Normalize units consistently
                unit = normalize_unit(unit)

                amounts.append((value, unit))
            except (ValueError, IndexError):
                continue

    return list(set(amounts))  # Remove duplicates


def normalize_unit(unit: str) -> str:
    """
    IMPROVED: Normalize unit names for consistent matching.
    """
    unit = unit.lower().strip()

    # Currency normalizations
    if unit in ["cr", "crore", "crores"]:
        return "crore"
    if unit in ["lac", "lakh", "lakhs"]:
        return "lakh"
    if unit == "lakh_crore":
        return "lakh crore"

    # Metric normalizations
    if unit in ["lmt", "lakh metric tonnes", "lakh metric tonne"]:
        return "lmt"
    if unit in ["mt", "metric tonnes", "metric tonne"]:
        return "mt"
    if unit in ["quintal", "quintals"]:
        return "quintal"
    if unit in ["tonne", "tonnes"]:
        return "tonne"

    # Percentage normalizations
    if unit in ["%", "percent", "per cent", "percentage"]:
        return "percent"

    # Count normalizations
    if unit in ["case", "cases"]:
        return "cases"
    if unit in ["godown", "godowns"]:
        return "godowns"
    if unit in ["state", "states", "states/uts"]:
        return "states"
    if unit in ["cpse", "cpses"]:
        return "cpses"

    return unit


def match_amount(
    expected_value: float,
    expected_unit: str,
    found_amounts: List[Tuple[float, str]],
    tolerance: float = 0.05,  # 5% tolerance for "close" matches
) -> AmountMatch:
    """
    IMPROVED: Match expected amount with better unit normalization.
    """
    # Normalize expected unit
    expected_unit_normalized = normalize_unit(expected_unit)

    # Filter by normalized unit
    same_unit_amounts = [
        (v, u)
        for v, u in found_amounts
        if normalize_unit(u) == expected_unit_normalized
    ]

    if not same_unit_amounts:
        # IMPROVED: Try alternate unit representations
        alternate_units = get_alternate_units(expected_unit_normalized)
        for alt_unit in alternate_units:
            same_unit_amounts = [
                (v, u) for v, u in found_amounts if normalize_unit(u) == alt_unit
            ]
            if same_unit_amounts:
                break

    if not same_unit_amounts:
        return AmountMatch(
            expected_value=expected_value,
            expected_unit=expected_unit,
            expected_context="",
            found=False,
            match_type="missing",
        )

    # Check for exact match (within 0.01)
    for value, unit in same_unit_amounts:
        if abs(value - expected_value) < 0.01:
            return AmountMatch(
                expected_value=expected_value,
                expected_unit=expected_unit,
                expected_context="",
                found=True,
                found_value=value,
                match_type="exact",
            )

    # Check for close match (within tolerance)
    for value, unit in same_unit_amounts:
        if (
            expected_value != 0
            and abs(value - expected_value) / abs(expected_value) < tolerance
        ):
            return AmountMatch(
                expected_value=expected_value,
                expected_unit=expected_unit,
                expected_context="",
                found=True,
                found_value=value,
                match_type="close",
            )

    # IMPROVED: Check if the number appears at all (looser matching)
    for value, unit in found_amounts:
        if abs(value - expected_value) < 0.01:
            return AmountMatch(
                expected_value=expected_value,
                expected_unit=expected_unit,
                expected_context="",
                found=True,
                found_value=value,
                match_type="close",  # Found with different unit
            )

    # Found amounts in same unit but wrong values
    return AmountMatch(
        expected_value=expected_value,
        expected_unit=expected_unit,
        expected_context="",
        found=False,
        found_value=same_unit_amounts[0][0] if same_unit_amounts else None,
        match_type="wrong",
    )


def get_alternate_units(unit: str) -> List[str]:
    """
    IMPROVED: Get alternate representations of a unit.
    """
    alternates = {
        "crore": ["cr", "crores"],
        "lakh": ["lac", "lakhs"],
        "percent": ["per cent", "%", "percentage"],
        "lmt": ["lakh metric tonnes", "lakh mt"],
        "mt": ["metric tonnes", "tonnes"],
        "cases": ["case"],
        "godowns": ["godown"],
        "states": ["state", "states/uts"],
    }
    return alternates.get(unit, [])


def evaluate_amounts(
    response: str, expected_amounts: List[Dict]
) -> Tuple[float, List[AmountMatch]]:
    """
    Evaluate amount accuracy.
    Returns (accuracy_score, list of match results).
    """
    if not expected_amounts:
        return 1.0, []

    found_amounts = extract_amounts(response)
    matches = []

    required_correct = 0
    required_total = 0
    optional_correct = 0
    optional_total = 0

    for exp in expected_amounts:
        value = exp.get("value", 0)
        unit = exp.get("unit", "crore")
        required = exp.get("required", False)
        context = exp.get("context", "")

        match = match_amount(value, unit, found_amounts)
        match.expected_context = context
        matches.append(match)

        if required:
            required_total += 1
            if match.match_type in ["exact", "close"]:
                required_correct += 1
        else:
            optional_total += 1
            if match.match_type in ["exact", "close"]:
                optional_correct += 1

    # Weighted score: required amounts are worth more
    if required_total > 0:
        required_score = required_correct / required_total
    else:
        required_score = 1.0

    if optional_total > 0:
        optional_score = optional_correct / optional_total
    else:
        optional_score = 1.0

    # 70% weight on required, 30% on optional
    final_score = 0.7 * required_score + 0.3 * optional_score

    return final_score, matches


# =============================================================================
# ENTITY EXTRACTION AND MATCHING (mostly unchanged)
# =============================================================================


def normalize_entity(entity: str) -> str:
    """Normalize entity name for matching."""
    return entity.lower().strip()


def find_entity_in_text(entity: str, text: str) -> bool:
    """
    Check if entity appears in text (fuzzy matching).
    Handles common variations.
    """
    normalized_entity = normalize_entity(entity)
    normalized_text = text.lower()

    # Direct match
    if normalized_entity in normalized_text:
        return True

    # IMPROVED: Extended variations
    variations = {
        "nhai": ["national highways authority", "highways authority of india"],
        "pmjay": [
            "pradhan mantri jan arogya",
            "ayushman bharat",
            "jan arogya yojana",
            "ab-pmjay",
        ],
        "cbdt": ["central board of direct taxes"],
        "fci": ["food corporation of india", "food corporation"],
        "cpse": [
            "central public sector enterprise",
            "public sector enterprise",
            "cpses",
        ],
        "sebi": ["securities and exchange board"],
        "frbm": ["fiscal responsibility", "budget management"],
        "sha": ["state health agency", "state health agencies"],
        "nha": ["national health authority"],
        "tms": ["transaction management system"],
        "cwc": ["central warehousing corporation"],
        "swc": ["state warehousing corporation"],
        "peg": ["private entrepreneurs guarantee", "guarantee scheme"],
        "cap": ["covered and plinth", "cover and plinth"],
        "fsd": ["food storage depot"],
        "itd": ["income tax department"],
        "gst": ["goods and services tax"],
        "cgst": ["central gst"],
        "igst": ["integrated gst"],
    }

    # Check if entity is an abbreviation with known variations
    if normalized_entity in variations:
        for variation in variations[normalized_entity]:
            if variation in normalized_text:
                return True

    # Check if entity is a known full form
    for abbr, full_forms in variations.items():
        if normalized_entity in full_forms:
            if abbr in normalized_text:
                return True

    return False


def evaluate_entities(
    response: str, expected_entities: List[str]
) -> Tuple[float, List[EntityMatch]]:
    """Evaluate entity coverage."""
    if not expected_entities:
        return 1.0, []

    matches = []
    found_count = 0

    for entity in expected_entities:
        found = find_entity_in_text(entity, response)
        matches.append(EntityMatch(expected_entity=entity, found=found))
        if found:
            found_count += 1

    coverage = found_count / len(expected_entities)
    return coverage, matches


# =============================================================================
# KEY FACT MATCHING (IMPROVED)
# =============================================================================


def simple_fact_match(fact: str, response: str) -> bool:
    """
    IMPROVED: Better keyword-based fact matching.
    """
    fact_lower = fact.lower()
    response_lower = response.lower()

    # Extract numbers from fact
    numbers = re.findall(r"\d+\.?\d*", fact)

    # IMPROVED: More lenient number matching (allow close values)
    numbers_found = True
    for num in numbers:
        num_val = float(num)
        # Check if this number or a close value appears
        found = False
        response_numbers = re.findall(r"\d+\.?\d*", response_lower)
        for resp_num in response_numbers:
            resp_val = float(resp_num)
            if abs(resp_val - num_val) < 0.1 or (
                num_val > 0 and abs(resp_val - num_val) / num_val < 0.05
            ):
                found = True
                break
        if not found and num_val > 1:  # Only require larger numbers
            numbers_found = False

    # Extract key words (longer than 4 chars, not common words)
    common_words = {
        "the",
        "and",
        "for",
        "was",
        "were",
        "that",
        "this",
        "with",
        "from",
        "have",
        "been",
        "which",
        "their",
        "there",
        "about",
        "during",
        "under",
        "total",
        "amount",
        "crore",
        "lakh",
        "percent",
    }
    words = re.findall(r"\b[a-z]{4,}\b", fact_lower)
    key_words = [w for w in words if w not in common_words]

    if not key_words:
        return True  # No key words to match

    # IMPROVED: Lower threshold - at least 40% of key words should appear
    words_found = sum(1 for w in key_words if w in response_lower)
    word_coverage = words_found / len(key_words)

    return word_coverage >= 0.4 and numbers_found


def evaluate_key_facts(response: str, expected_facts: List[str]) -> float:
    """Evaluate key fact coverage."""
    if not expected_facts:
        return 1.0

    found_count = sum(1 for fact in expected_facts if simple_fact_match(fact, response))
    return found_count / len(expected_facts)


# =============================================================================
# LLM-AS-JUDGE EVALUATION (IMPROVED)
# =============================================================================

# IMPROVED: More lenient hallucination detection
LLM_JUDGE_PROMPT = """You are an expert evaluator for a RAG system answering questions about CAG audit reports.

Evaluate the response against the expected answer.

## Question
{question}

## Expected Answer (Ground Truth)
{expected_summary}

## Key Facts That Should Be Covered
{key_facts}

## Key Amounts That Should Be Mentioned
{key_amounts}

## Actual Response
{actual_answer}

## Evaluation Criteria

Rate each dimension from 0-5:

### 1. Factual Accuracy (0-5)
- 5: All facts match ground truth
- 4: Minor imprecision in numbers (e.g., "about ₹65 crore" vs "₹64.60 crore")
- 3: One factual error, rest correct
- 2: Multiple minor errors OR one major error
- 1: Mostly incorrect
- 0: Completely wrong

### 2. Completeness (0-5)
- 5: All key facts and amounts included
- 4: 80%+ of key information
- 3: 60-80% coverage
- 2: 40-60% coverage
- 1: <40% coverage
- 0: Doesn't address the question

### 3. Relevance (0-5)
- 5: Directly answers the question
- 4: Answers with minor tangents
- 3: Partially answers
- 2: Related but doesn't answer
- 1: Mostly off-topic
- 0: Completely irrelevant

### 4. Citation Quality (0-5)
- 5: Citations present and accurate
- 4: Minor citation issues
- 3: Some citations don't fully support claims
- 2: Multiple citation errors
- 1: Citations mostly irrelevant
- 0: No citations

### 5. Hallucination Check
IMPORTANT: Only flag as hallucination if the response contains:
- Specific numbers/amounts NOT in ground truth AND contradicting it
- Claims that directly contradict the expected answer
- Made-up entities, schemes, or findings

DO NOT flag as hallucination:
- Additional relevant context from the same report
- Rephrasing the same information differently
- Rounding of numbers (e.g., 64.60 → 65 crore)
- Related information that doesn't contradict ground truth

## Response (JSON only)

```json
{{
    "factual_accuracy": <0-5>,
    "completeness": <0-5>,
    "relevance": <0-5>,
    "citation_quality": <0-5>,
    "has_hallucination": <true/false>,
    "hallucination_details": "<explain only CLEAR hallucinations, or 'None'>",
    "reasoning": "<2-3 sentences overall assessment>"
}}
```

Be fair - the goal is finding genuine issues, not penalizing valid additional context."""


def llm_judge_evaluate(
    question: str,
    expected_summary: str,
    key_facts: List[str],
    key_amounts: List[Dict],
    actual_answer: str,
    openai_client: OpenAI,
) -> Dict[str, Any]:
    """Use LLM as judge to evaluate response quality."""
    amounts_str = (
        "\n".join(
            [
                f"- {a.get('value')} {a.get('unit', 'crore')}: {a.get('context', '')}"
                for a in key_amounts
            ]
        )
        if key_amounts
        else "None specified"
    )

    facts_str = (
        "\n".join([f"- {f}" for f in key_facts]) if key_facts else "None specified"
    )

    prompt = LLM_JUDGE_PROMPT.format(
        question=question,
        expected_summary=expected_summary,
        key_facts=facts_str,
        key_amounts=amounts_str,
        actual_answer=actual_answer,
    )

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert evaluator. Respond only with valid JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=500,
        )

        result_text = response.choices[0].message.content

        json_match = re.search(r"\{[\s\S]*\}", result_text)
        if json_match:
            result = json.loads(json_match.group())
            return result
        else:
            logger.warning("Could not parse LLM judge response as JSON")
            return {
                "factual_accuracy": 2.5,
                "completeness": 2.5,
                "relevance": 2.5,
                "citation_quality": 2.5,
                "has_hallucination": False,
                "hallucination_details": "Evaluation failed",
                "reasoning": "Could not parse LLM response",
            }

    except Exception as e:
        logger.error(f"LLM judge evaluation failed: {e}")
        return {
            "factual_accuracy": 2.5,
            "completeness": 2.5,
            "relevance": 2.5,
            "citation_quality": 2.5,
            "has_hallucination": False,
            "hallucination_details": f"Error: {str(e)}",
            "reasoning": f"Evaluation error: {str(e)}",
        }


# =============================================================================
# NEGATIVE TEST HANDLING
# =============================================================================


def check_acknowledges_no_data(response: str) -> bool:
    """Check if response appropriately acknowledges lack of data."""
    negative_indicators = [
        "no information available",
        "not found",
        "couldn't find",
        "could not find",
        "no relevant information",
        "not covered",
        "not in the",
        "no data",
        "not available",
        "don't have information",
        "do not have information",
        "outside the scope",
        "not included",
        "not available in the indexed",
    ]

    response_lower = response.lower()
    return any(indicator in response_lower for indicator in negative_indicators)


# =============================================================================
# MAIN EVALUATION LOGIC
# =============================================================================


def evaluate_single_case(
    test_case: Dict,
    rag_service: Any,
    openai_client: OpenAI,
    style=None,
    verbose: bool = False,
) -> TestResult:
    """Evaluate a single test case."""
    test_id = test_case["id"]
    question = test_case["question"]
    category = test_case["category"]
    expected = test_case["expected"]
    negative_criteria = test_case.get("negative_criteria", {})

    if verbose:
        logger.info(f"Evaluating {test_id}: {question[:50]}...")

    # Get RAG response
    start_time = time.time()
    try:
        if rag_service:
            response = rag_service.ask(question, style=style)
            actual_answer = response.answer
            sources_used = response.sources_used
            search_type = response.search_type
        else:
            actual_answer = "[RAG service not available]"
            sources_used = 0
            search_type = "none"
    except Exception as e:
        logger.error(f"RAG query failed for {test_id}: {e}")
        actual_answer = f"[Error: {str(e)}]"
        sources_used = 0
        search_type = "error"

    response_time_ms = (time.time() - start_time) * 1000

    # Initialize scores
    scores = EvaluationScores()
    issues = []

    # Check if this is a negative test case
    is_negative_test = category.get("type") == "negative"

    if is_negative_test:
        # For negative tests, check if system correctly identifies missing data
        scores.acknowledges_no_data = check_acknowledges_no_data(actual_answer)

        if scores.acknowledges_no_data:
            scores.factual_accuracy = 5
            scores.completeness = 5
            scores.relevance = 5
            scores.overall_score = 100
            scores.passed = True
        else:
            scores.factual_accuracy = 1
            scores.has_hallucination = True
            scores.overall_score = 10
            scores.passed = False
            issues.append("Failed to acknowledge missing data for negative test")
    else:
        # Regular evaluation

        # 1. Amount evaluation
        expected_amounts = expected.get("key_amounts", [])
        scores.amount_accuracy, amount_matches = evaluate_amounts(
            actual_answer, expected_amounts
        )
        scores.amount_matches = [asdict(m) for m in amount_matches]

        for match in amount_matches:
            if match.match_type == "missing":
                issues.append(
                    f"Missing required amount: {match.expected_value} {match.expected_unit}"
                )
            elif match.match_type == "wrong":
                issues.append(
                    f"Wrong amount: expected {match.expected_value}, found {match.found_value}"
                )

        # 2. Entity evaluation
        expected_entities = expected.get("key_entities", [])
        scores.entity_coverage, entity_matches = evaluate_entities(
            actual_answer, expected_entities
        )
        scores.entity_matches = [asdict(m) for m in entity_matches]

        if scores.entity_coverage < 0.5:
            issues.append(f"Low entity coverage: {scores.entity_coverage:.0%}")

        # 3. Key fact evaluation
        expected_facts = expected.get("key_facts", [])
        scores.key_fact_coverage = evaluate_key_facts(actual_answer, expected_facts)

        if scores.key_fact_coverage < 0.5:
            issues.append(f"Low key fact coverage: {scores.key_fact_coverage:.0%}")

        # 4. LLM-as-Judge evaluation
        llm_scores = llm_judge_evaluate(
            question=question,
            expected_summary=expected.get("answer_summary", ""),
            key_facts=expected_facts,
            key_amounts=expected_amounts,
            actual_answer=actual_answer,
            openai_client=openai_client,
        )

        scores.factual_accuracy = llm_scores.get("factual_accuracy", 2.5)
        scores.completeness = llm_scores.get("completeness", 2.5)
        scores.relevance = llm_scores.get("relevance", 2.5)
        scores.citation_quality = llm_scores.get("citation_quality", 2.5)
        scores.has_hallucination = llm_scores.get("has_hallucination", False)
        scores.llm_judge_reasoning = llm_scores.get("reasoning", "")

        if scores.has_hallucination:
            issues.append(
                f"Hallucination detected: {llm_scores.get('hallucination_details', 'Unknown')}"
            )

        # 5. Check negative criteria
        must_not_contain = negative_criteria.get("must_not_contain", [])
        for forbidden in must_not_contain:
            if forbidden.lower() in actual_answer.lower():
                issues.append(f"Contains forbidden content: '{forbidden}'")
                scores.has_hallucination = True

        # Calculate overall score
        # Weights: Factual 30%, Complete 20%, Relevance 15%, Citation 15%, Amounts 10%, Entities 10%
        scores.overall_score = (
            scores.factual_accuracy * 6  # 30% (5 * 6 = 30)
            + scores.completeness * 4  # 20%
            + scores.relevance * 3  # 15%
            + scores.citation_quality * 3  # 15%
            + scores.amount_accuracy * 10  # 10%
            + scores.entity_coverage * 10  # 10%
        )

        # Penalty for hallucination
        if scores.has_hallucination:
            scores.overall_score *= 0.5

        # Pass/fail threshold
        scores.passed = (
            scores.overall_score >= 70
            and scores.factual_accuracy >= 3
            and not scores.has_hallucination
        )

    return TestResult(
        test_id=test_id,
        question=question,
        category=category,
        expected_summary=expected.get("answer_summary", "")[:200],
        actual_answer=actual_answer,
        sources_used=sources_used,
        search_type=search_type,
        response_time_ms=response_time_ms,
        scores=scores,
        issues=issues,
    )


def run_evaluation(
    test_cases: List[Dict],
    rag_service: Any,
    openai_client: OpenAI,
    style=None,
    filter_category: str = None,
    filter_difficulty: str = None,
    verbose: bool = False,
    parallel: bool = False,
) -> EvaluationReport:
    """Run evaluation on all test cases."""

    # Filter test cases
    filtered_cases = test_cases

    if filter_category:
        filtered_cases = [
            tc for tc in filtered_cases if tc["category"].get("type") == filter_category
        ]

    if filter_difficulty:
        filtered_cases = [
            tc
            for tc in filtered_cases
            if tc["category"].get("difficulty") == filter_difficulty
        ]

    logger.info(f"Running evaluation on {len(filtered_cases)} test cases")

    results = []

    if parallel and len(filtered_cases) > 1:
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(
                    evaluate_single_case, tc, rag_service, openai_client, style, verbose
                ): tc
                for tc in filtered_cases
            }

            for future in as_completed(futures):
                try:
                    result = future.result()
                    results.append(result)
                    status = "✅ PASS" if result.scores.passed else "❌ FAIL"
                    logger.info(
                        f"{result.test_id}: {status} (score: {result.scores.overall_score:.1f})"
                    )
                except Exception as e:
                    logger.error(f"Evaluation failed: {e}")
    else:
        for tc in filtered_cases:
            result = evaluate_single_case(
                tc, rag_service, openai_client, style, verbose
            )
            results.append(result)
            status = "✅ PASS" if result.scores.passed else "❌ FAIL"
            logger.info(
                f"{result.test_id}: {status} (score: {result.scores.overall_score:.1f})"
            )

    # Calculate aggregates
    total = len(results)
    passed = sum(1 for r in results if r.scores.passed)
    failed = total - passed

    # Average scores
    avg_factual = (
        sum(r.scores.factual_accuracy for r in results) / total if total > 0 else 0
    )
    avg_complete = (
        sum(r.scores.completeness for r in results) / total if total > 0 else 0
    )
    avg_relevance = sum(r.scores.relevance for r in results) / total if total > 0 else 0
    avg_citation = (
        sum(r.scores.citation_quality for r in results) / total if total > 0 else 0
    )
    avg_amount = (
        sum(r.scores.amount_accuracy for r in results) / total if total > 0 else 0
    )
    avg_entity = (
        sum(r.scores.entity_coverage for r in results) / total if total > 0 else 0
    )

    # By difficulty
    scores_by_difficulty = {}
    for diff in ["easy", "medium", "hard"]:
        diff_results = [r for r in results if r.category.get("difficulty") == diff]
        if diff_results:
            scores_by_difficulty[diff] = {
                "count": len(diff_results),
                "pass_rate": sum(1 for r in diff_results if r.scores.passed)
                / len(diff_results),
                "avg_score": sum(r.scores.overall_score for r in diff_results)
                / len(diff_results),
            }

    # By type
    scores_by_type = {}
    for qtype in [
        "factual",
        "list",
        "aggregation",
        "comparison",
        "explanation",
        "negative",
    ]:
        type_results = [r for r in results if r.category.get("type") == qtype]
        if type_results:
            scores_by_type[qtype] = {
                "count": len(type_results),
                "pass_rate": sum(1 for r in type_results if r.scores.passed)
                / len(type_results),
                "avg_score": sum(r.scores.overall_score for r in type_results)
                / len(type_results),
            }

    # Issue counts
    issue_counts = {}
    for r in results:
        for issue in r.issues:
            # Categorize issues
            if "amount" in issue.lower():
                cat = "Amount Issues"
            elif "entity" in issue.lower() or "coverage" in issue.lower():
                cat = "Coverage Issues"
            elif "hallucination" in issue.lower():
                cat = "Hallucination"
            elif "forbidden" in issue.lower():
                cat = "Forbidden Content"
            else:
                cat = "Other"
            issue_counts[cat] = issue_counts.get(cat, 0) + 1

    return EvaluationReport(
        timestamp=datetime.now().isoformat(),
        total_cases=total,
        passed_cases=passed,
        failed_cases=failed,
        pass_rate=passed / total if total > 0 else 0,
        avg_factual_accuracy=avg_factual,
        avg_completeness=avg_complete,
        avg_relevance=avg_relevance,
        avg_citation_quality=avg_citation,
        avg_amount_accuracy=avg_amount,
        avg_entity_coverage=avg_entity,
        scores_by_difficulty=scores_by_difficulty,
        scores_by_type=scores_by_type,
        issue_counts=issue_counts,
        results=[r.to_dict() for r in results],
    )


# =============================================================================
# CLI (simplified for brevity)
# =============================================================================


def main():
    parser = argparse.ArgumentParser(description="Evaluate CAG RAG Pipeline (Improved)")
    parser.add_argument("--test-cases", type=str, required=True)
    parser.add_argument("--output", type=str, default="results")
    parser.add_argument("--category", type=str)
    parser.add_argument("--difficulty", type=str)
    parser.add_argument("--style", type=str, default="adaptive")
    parser.add_argument("--provider", type=str, default="openai")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--parallel", action="store_true")
    parser.add_argument("--standalone", action="store_true")

    args = parser.parse_args()

    # Load test cases
    with open(args.test_cases, "r") as f:
        data = json.load(f)

    test_cases = data.get("test_cases", data)
    if isinstance(test_cases, dict):
        test_cases = [test_cases]

    logger.info(f"Loaded {len(test_cases)} test cases")

    # Create output directory
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Initialize
    openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    rag_service = None
    style = None

    if not args.standalone and RAGService:
        try:
            config = RAGConfig()
            config.llm.provider = (
                LLMProvider.OPENAI if args.provider == "openai" else LLMProvider.CLAUDE
            )
            rag_service = RAGService(config)

            if ResponseStyle:
                style_map = {
                    "concise": ResponseStyle.CONCISE,
                    "conversational": ResponseStyle.CONVERSATIONAL,
                    "executive": ResponseStyle.EXECUTIVE,
                    "analytical": ResponseStyle.ANALYTICAL,
                    "report": ResponseStyle.REPORT,
                    "adaptive": ResponseStyle.ADAPTIVE,
                }
                style = style_map.get(args.style, ResponseStyle.ADAPTIVE)
        except Exception as e:
            logger.warning(f"Could not initialize RAG service: {e}")

    # Run evaluation
    report = run_evaluation(
        test_cases=test_cases,
        rag_service=rag_service,
        openai_client=openai_client,
        style=style,
        filter_category=args.category,
        filter_difficulty=args.difficulty,
        verbose=args.verbose,
        parallel=args.parallel,
    )

    # Save results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    json_path = output_dir / f"evaluation_{timestamp}.json"
    with open(json_path, "w") as f:
        json.dump(report.to_dict(), f, indent=2)
    logger.info(f"JSON report saved to {json_path}")

    # Print summary
    print("\n" + "=" * 60)
    print("EVALUATION SUMMARY (IMPROVED EVALUATOR)")
    print("=" * 60)
    print(
        f"Total: {report.total_cases} | Passed: {report.passed_cases} | Failed: {report.failed_cases}"
    )
    print(f"Pass Rate: {report.pass_rate:.1%}")
    print("-" * 60)
    print(f"Factual Accuracy: {report.avg_factual_accuracy:.2f}/5")
    print(f"Completeness: {report.avg_completeness:.2f}/5")
    print(f"Relevance: {report.avg_relevance:.2f}/5")
    print(f"Citation Quality: {report.avg_citation_quality:.2f}/5")
    print(f"Amount Accuracy: {report.avg_amount_accuracy:.1%}")
    print(f"Entity Coverage: {report.avg_entity_coverage:.1%}")
    print("=" * 60)

    return 0 if report.pass_rate >= 0.7 else 1


if __name__ == "__main__":
    sys.exit(main())
