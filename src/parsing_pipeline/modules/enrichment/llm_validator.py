"""
LLM Validator: Validates low-confidence extractions via LLM.

P3: Implements hybrid validation approach - regex extracts everything,
LLM validates only uncertain extractions (confidence 0.4-0.7).

Uses Gemini via Vertex AI for GCP credit billing (cost-effective validation).
Fallback: Direct Gemini API via GOOGLE_API_KEY.

Usage:
    from src.parsing_pipeline.modules.enrichment.llm_validator import LLMValidator

    validator = LLMValidator()

    # Check if extraction needs validation
    if validator.needs_validation(extraction.confidence):
        result = validator.validate_finding(extraction)
        if result.verdict == "VALID":
            # Accept extraction
        elif result.verdict == "INVALID":
            # Reject extraction
"""

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Dict, Optional, Any
from pathlib import Path
from enum import Enum

logger = logging.getLogger(__name__)

# Pattern refinement data directory
DEFAULT_REFINEMENT_PATH = Path("logs/pattern_refinement")


class ValidationVerdict(Enum):
    """Possible LLM validation outcomes."""
    VALID = "valid"
    INVALID = "invalid"
    UNCERTAIN = "uncertain"


@dataclass
class ValidationRequest:
    """Request for LLM validation of an extraction."""
    extraction_id: str
    extraction_type: str  # "finding", "section", "recommendation"
    chunk_text: str
    extracted_value: Dict[str, Any]  # The extracted data
    confidence: float
    context: Optional[str] = None  # Additional context (parent section, etc.)


@dataclass
class ValidationResult:
    """Result of LLM validation."""
    extraction_id: str
    verdict: ValidationVerdict
    reasoning: str
    corrected_value: Optional[Dict[str, Any]] = None  # If LLM suggests correction
    llm_confidence: float = 0.0  # LLM's confidence in its verdict


@dataclass
class ValidationBatchResult:
    """Result of batch validation."""
    results: List[ValidationResult] = field(default_factory=list)
    total_validated: int = 0
    valid_count: int = 0
    invalid_count: int = 0
    uncertain_count: int = 0
    total_cost_usd: float = 0.0


# System prompts for different extraction types
VALIDATION_PROMPTS = {
    "finding": """You are validating audit finding extractions from CAG (Comptroller and Auditor General) reports.

Given a text chunk and extracted finding metadata, determine if the extraction is correct.

Evaluation criteria:
1. Is this actually an audit finding (not just background/context/reference data)?
2. Is the finding type classification accurate for the content?
3. Is the monetary value correctly associated with this finding (not reference data)?
4. Does the text describe an audit observation of irregularity/deficiency?

Respond with EXACTLY one of:
- "VALID: [brief reason]" if the extraction is correct
- "INVALID: [brief reason]" if the extraction is wrong
- "UNCERTAIN: [brief reason]" if you cannot confidently determine

Be conservative - only mark INVALID if clearly wrong.""",

    "section": """You are validating section classification from CAG audit reports.

Given a section title and the assigned section type, determine if the classification is correct.

Section types: executive_summary, introduction, findings, recommendations, conclusion, annexure, etc.

Respond with EXACTLY one of:
- "VALID: [brief reason]" if the section type is correct
- "INVALID: [correct_type] - [reason]" if wrong, include the correct type
- "UNCERTAIN: [brief reason]" if unclear

Consider that CAG reports follow standard structures.""",

    "recommendation": """You are validating recommendation extractions from CAG audit reports.

Determine if the extracted text is actually an audit recommendation.

Recommendations typically:
- Start with action verbs (recommend, suggest, advise)
- Address specific entities (Ministry, Department)
- Propose specific actions to address audit findings

Respond with EXACTLY one of:
- "VALID: [brief reason]" if this is a genuine recommendation
- "INVALID: [brief reason]" if not a recommendation
- "UNCERTAIN: [brief reason]" if unclear"""
}


class LLMValidator:
    """
    Validates low-confidence extractions via LLM.

    Uses a selective validation approach:
    - Confidence < lower_bound: Rejected by regex, no LLM needed
    - lower_bound <= Confidence < upper_bound: Send to LLM
    - Confidence >= upper_bound: Accepted by regex, no LLM needed

    Default: Uses Gemini via Vertex AI for GCP credit billing.
    Fallback: GOOGLE_API_KEY for direct Gemini API access.
    """

    def __init__(
        self,
        confidence_lower_bound: float = 0.5,
        confidence_upper_bound: float = 0.7,
        model: str = "gemini-3.8-flash",
        use_batch_api: bool = True,
        api_key: Optional[str] = None,
        collect_refinement_data: bool = True,
        refinement_data_path: Optional[Path] = None,
    ):
        """
        Initialize LLM validator.

        Args:
            confidence_lower_bound: Minimum confidence to consider for validation.
                                   Below this, extraction is rejected without LLM.
            confidence_upper_bound: Maximum confidence to send to LLM.
                                   Above this, extraction is accepted without LLM.
            model: Gemini model to use for validation (default: gemini-3.8-flash).
            use_batch_api: Reserved for future batch API support.
            api_key: Google API key. If None, uses Vertex AI ADC or GOOGLE_API_KEY env var.
            collect_refinement_data: Whether to log invalid findings for pattern refinement.
            refinement_data_path: Directory to save refinement data.
        """
        self.lower_bound = confidence_lower_bound
        self.upper_bound = confidence_upper_bound
        self.model = model
        self.use_batch_api = use_batch_api
        self._api_key = api_key or os.getenv("GOOGLE_API_KEY")

        # Data collection for pattern refinement
        self.collect_refinement_data = collect_refinement_data
        self.refinement_data_path = refinement_data_path or DEFAULT_REFINEMENT_PATH

        # Lazy-load Gemini client
        self._client = None

        # Load config from pattern_loader if available
        try:
            from src.parsing_pipeline.modules.enrichment.pattern_loader import get_pattern_loader
            loader = get_pattern_loader()

            # Load thresholds
            thresholds = loader.get_confidence_thresholds()
            self.lower_bound = thresholds.get("llm_validation_lower", confidence_lower_bound)
            self.upper_bound = thresholds.get("llm_validation_upper", confidence_upper_bound)

            # Load LLM validation config
            llm_config = loader.get_llm_validation_config()
            self.model = llm_config.get("model", model)
            self.collect_refinement_data = llm_config.get("collect_refinement_data", collect_refinement_data)
            if llm_config.get("refinement_data_path"):
                self.refinement_data_path = Path(llm_config["refinement_data_path"])
        except Exception as e:
            logger.debug(f"Could not load config from pattern_loader: {e}")

        # Ensure refinement data directory exists
        if self.collect_refinement_data:
            self.refinement_data_path.mkdir(parents=True, exist_ok=True)

        logger.info(
            f"LLMValidator initialized: model={self.model}, "
            f"confidence_band=[{self.lower_bound}, {self.upper_bound}), "
            f"collect_refinement_data={self.collect_refinement_data}"
        )

    @property
    def client(self):
        """Lazy-load Gemini client using Vertex AI or API key fallback."""
        if self._client is None:
            try:
                from google import genai

                project = os.getenv("GOOGLE_CLOUD_PROJECT")
                location = os.getenv("VERTEX_AI_REGION", "us-central1")

                # Try Vertex AI first (GCP project billing), fall back to API key
                if project:
                    try:
                        import google.auth
                        credentials, auth_project = google.auth.default(
                            scopes=["https://www.googleapis.com/auth/cloud-platform"]
                        )
                        project = project or auth_project

                        self._client = genai.Client(
                            vertexai=True,
                            project=project,
                            location=location,
                            credentials=credentials
                        )
                        logger.info(f"LLMValidator using Vertex AI (project={project})")
                    except Exception as e:
                        logger.warning(f"Vertex AI init failed: {e}, trying API key fallback...")
                        if self._api_key:
                            self._client = genai.Client(api_key=self._api_key)
                            logger.info("LLMValidator using Gemini API key")
                        else:
                            raise
                elif self._api_key:
                    self._client = genai.Client(api_key=self._api_key)
                    logger.info("LLMValidator using Gemini API key")
                else:
                    raise ValueError(
                        "No Gemini credentials found. Set GOOGLE_CLOUD_PROJECT for Vertex AI "
                        "or GOOGLE_API_KEY for direct API access."
                    )
            except ImportError:
                logger.error("google-genai package not installed. Run: pip install google-genai")
                raise
        return self._client

    def needs_validation(self, confidence: float) -> bool:
        """
        Check if an extraction needs LLM validation.

        Args:
            confidence: Extraction confidence score (0.0-1.0)

        Returns:
            True if extraction should be sent to LLM for validation
        """
        return self.lower_bound <= confidence < self.upper_bound

    def validate_single(
        self,
        request: ValidationRequest,
        timeout: int = 30,
    ) -> ValidationResult:
        """
        Validate a single extraction synchronously.

        Args:
            request: ValidationRequest with extraction details
            timeout: API timeout in seconds (not used for Gemini, kept for API compat)

        Returns:
            ValidationResult with verdict and reasoning
        """
        system_prompt = VALIDATION_PROMPTS.get(
            request.extraction_type,
            VALIDATION_PROMPTS["finding"]
        )

        user_message = self._format_validation_request(request)

        # Combine system prompt and user message for Gemini
        full_prompt = f"{system_prompt}\n\n---\n\n{user_message}"

        try:
            from google.genai import types

            response = self.client.models.generate_content(
                model=self.model,
                contents=[types.Part.from_text(text=full_prompt)],
                config=types.GenerateContentConfig(
                    temperature=0.1,  # Low temperature for consistent validation
                    max_output_tokens=150,
                ),
            )

            return self._parse_response(
                request.extraction_id,
                response.text
            )

        except Exception as e:
            logger.warning(f"LLM validation failed for {request.extraction_id}: {e}")
            return ValidationResult(
                extraction_id=request.extraction_id,
                verdict=ValidationVerdict.UNCERTAIN,
                reasoning=f"API error: {str(e)}",
            )

    def validate_batch(
        self,
        requests: List[ValidationRequest],
        output_dir: Optional[Path] = None,
    ) -> ValidationBatchResult:
        """
        Validate multiple extractions via Batch API.

        This is the cost-efficient method (~50% savings vs synchronous).

        Args:
            requests: List of ValidationRequest objects
            output_dir: Directory to save batch results

        Returns:
            ValidationBatchResult with all results and statistics
        """
        if not requests:
            return ValidationBatchResult()

        # Filter to only those needing validation
        to_validate = [r for r in requests if self.needs_validation(r.confidence)]

        if not to_validate:
            logger.info("No extractions need LLM validation")
            return ValidationBatchResult()

        logger.info(f"Submitting {len(to_validate)} extractions for LLM validation")

        # Synchronous validation (Gemini doesn't have batch API like Anthropic)
        results = []
        for request in to_validate:
            result = self.validate_single(request)
            results.append(result)

        # Calculate statistics
        valid_count = sum(1 for r in results if r.verdict == ValidationVerdict.VALID)
        invalid_count = sum(1 for r in results if r.verdict == ValidationVerdict.INVALID)
        uncertain_count = sum(1 for r in results if r.verdict == ValidationVerdict.UNCERTAIN)

        # Estimate cost (Gemini 3.5 Flash pricing via Vertex AI)
        # Input: ~850 tokens/request, Output: ~60 tokens/request
        # $0.50/1M input, $3.00/1M output (Gemini 3.5 Flash)
        input_tokens = len(to_validate) * 850
        output_tokens = len(to_validate) * 60
        cost = (input_tokens * 0.50 / 1_000_000) + (output_tokens * 3.00 / 1_000_000)

        return ValidationBatchResult(
            results=results,
            total_validated=len(to_validate),
            valid_count=valid_count,
            invalid_count=invalid_count,
            uncertain_count=uncertain_count,
            total_cost_usd=cost,
        )

    def _format_validation_request(self, request: ValidationRequest) -> str:
        """Format a validation request for the LLM."""
        parts = [
            f"## Extraction Type: {request.extraction_type}",
            f"## Confidence Score: {request.confidence:.2f}",
            "",
            "## Text Chunk:",
            "```",
            request.chunk_text[:1500],  # Limit to ~1500 chars
            "```",
            "",
            "## Extracted Data:",
            json.dumps(request.extracted_value, indent=2, ensure_ascii=False),
        ]

        if request.context:
            parts.extend([
                "",
                "## Context:",
                request.context
            ])

        return "\n".join(parts)

    def _parse_response(
        self,
        extraction_id: str,
        response_text: str,
    ) -> ValidationResult:
        """Parse LLM response into ValidationResult."""
        text = response_text.strip().upper()

        if text.startswith("VALID"):
            verdict = ValidationVerdict.VALID
            reasoning = response_text.split(":", 1)[-1].strip() if ":" in response_text else ""
        elif text.startswith("INVALID"):
            verdict = ValidationVerdict.INVALID
            reasoning = response_text.split(":", 1)[-1].strip() if ":" in response_text else ""
        else:
            verdict = ValidationVerdict.UNCERTAIN
            reasoning = response_text.split(":", 1)[-1].strip() if ":" in response_text else response_text

        return ValidationResult(
            extraction_id=extraction_id,
            verdict=verdict,
            reasoning=reasoning,
        )

    def _save_refinement_data(
        self,
        request: ValidationRequest,
        result: ValidationResult,
        report_id: Optional[str] = None,
    ) -> None:
        """
        Save invalid extraction data for pattern refinement.

        Creates JSONL files organized by date for analysis.
        """
        if not self.collect_refinement_data:
            return

        if result.verdict != ValidationVerdict.INVALID:
            return

        try:
            # Create daily file
            date_str = datetime.now().strftime("%Y-%m-%d")
            refinement_file = self.refinement_data_path / f"invalid_extractions_{date_str}.jsonl"

            # Build refinement record
            record = {
                "timestamp": datetime.now().isoformat(),
                "report_id": report_id,
                "extraction_id": request.extraction_id,
                "extraction_type": request.extraction_type,
                "confidence": request.confidence,
                "extracted_value": request.extracted_value,
                "chunk_text_preview": request.chunk_text[:500],  # First 500 chars
                "llm_reasoning": result.reasoning,
                "context": request.context,
            }

            # Append to JSONL file
            with open(refinement_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

            logger.debug(f"Saved refinement data for {request.extraction_id}")

        except Exception as e:
            logger.warning(f"Failed to save refinement data: {e}")

    def validate_and_collect(
        self,
        request: ValidationRequest,
        report_id: Optional[str] = None,
        timeout: int = 30,
    ) -> ValidationResult:
        """
        Validate extraction and collect data for pattern refinement.

        This is the main method to use in the pipeline.

        Args:
            request: ValidationRequest with extraction details
            report_id: Optional report ID for tracking
            timeout: API timeout in seconds

        Returns:
            ValidationResult with verdict and reasoning
        """
        result = self.validate_single(request, timeout)

        # Save refinement data for invalid extractions
        if result.verdict == ValidationVerdict.INVALID:
            self._save_refinement_data(request, result, report_id)

        return result


# Convenience functions
def create_finding_validation_request(
    finding: Dict,
    chunk_text: str,
    parent_section: Optional[str] = None,
) -> ValidationRequest:
    """Create a ValidationRequest for a finding extraction."""
    return ValidationRequest(
        extraction_id=finding.get("finding_id", "unknown"),
        extraction_type="finding",
        chunk_text=chunk_text,
        extracted_value={
            "finding_type": finding.get("finding_type"),
            "monetary_value_crore": finding.get("monetary_value_crore"),
            "severity": finding.get("severity"),
        },
        confidence=finding.get("confidence", 0.5),
        context=f"Parent section: {parent_section}" if parent_section else None,
    )


def create_section_validation_request(
    classification: Dict,
    section_title: str,
) -> ValidationRequest:
    """Create a ValidationRequest for a section classification."""
    return ValidationRequest(
        extraction_id=classification.get("chunk_id", "unknown"),
        extraction_type="section",
        chunk_text=section_title,
        extracted_value={
            "section_type": classification.get("section_type"),
        },
        confidence=classification.get("confidence", 0.5),
    )
