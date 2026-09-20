"""
LLM-based TOC Validator (Phase 5.7)

For reports where Phase 4 + Phase 5.5 still produce low-quality TOCs
(quality < 50), uses Google Gemini to validate and correct the TOC
by analyzing the first ~15 pages of raw text.

This is a LAST RESORT — only called for ~10-20% of reports.
Cost: ~$0.015 per report via Gemini 3.6 Flash.

Uses the google-genai SDK (not the deprecated google-generativeai).
"""

import json
import logging
import re
from typing import Dict, List, Optional, Tuple

import fitz  # PyMuPDF

from src.parsing_pipeline.config import get_config, LLMValidationConfig
from src.parsing_pipeline.instrumentation import get_noop_emitter

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger(__name__)


class TOCLLMValidator:
    """
    Uses Google Gemini to validate/correct low-quality TOCs.

    Strategy:
    - Extract raw text from first 15 pages
    - Send existing TOC (if any) + raw text to Gemini
    - Ask it to return a corrected TOC in structured format
    - Parse response and use as validated TOC
    """

    # Prompt template for TOC extraction/validation
    SYSTEM_PROMPT = """You are a document structure analyzer specializing in Indian government audit reports (CAG reports).

Your task: Extract or validate the Table of Contents from the provided text.

Rules:
1. Each TOC entry has: level (1=chapter, 2=section, 3=subsection), title, and page number
2. Common Level 1 entries: Preface, Executive Summary, Chapter I/II/III, Annexure, Glossary
3. Common Level 2 entries: numbered sections like 1.1, 2.3, or lettered like A. Karnataka
4. Common Level 3 entries: sub-sections like 1.1.1, 2.3.2
5. Page numbers in the TOC refer to PRINTED page numbers (not PDF page numbers)
6. Ignore table captions, figure numbers, headers/footers"""

    USER_PROMPT_TEMPLATE = """Here is text from the first pages of a CAG audit report.
{existing_toc_section}
Extract the complete Table of Contents. Return ONLY a JSON array where each entry is:
[level, "title", page_number]

Example:
[
  [1, "Preface", 1],
  [1, "Executive Summary", 3],
  [1, "Chapter I Introduction", 7],
  [2, "1.1 Background", 8],
  [2, "1.2 Audit Objectives", 10],
  [1, "Chapter II Compliance Audit", 15],
  [2, "2.1 Tax Assessment Issues", 16],
  [3, "2.1.1 Short Levy of Tax", 17]
]

Document text (first ~15 pages):
---
{document_text}
---

Return ONLY the JSON array, no explanations."""

    def __init__(
        self,
        model: Optional[str] = None,
        max_input_chars: Optional[int] = None,
        quality_threshold: Optional[int] = None,
        config: Optional[LLMValidationConfig] = None,
        trace_emitter=None,
    ):
        """
        Args:
            model: Gemini model to use (overrides config)
            max_input_chars: Max chars of document text to send (overrides config)
            quality_threshold: Only validate TOCs with quality below this (overrides config)
            config: LLMValidationConfig instance (default: load from global config)
            trace_emitter: Optional TraceEmitter for instrumentation
        """
        # Load from config if not provided
        if config is None:
            config = get_config().llm_validation

        self.enabled = config.enabled
        self.model = model if model is not None else config.model
        self.max_input_chars = (
            max_input_chars if max_input_chars is not None
            else config.max_input_chars
        )
        self.quality_threshold = (
            quality_threshold if quality_threshold is not None
            else config.quality_threshold
        )
        self.max_pages = config.max_pages_to_extract
        self._client = None
        self._trace_emitter = trace_emitter or get_noop_emitter()

    def _get_client(self):
        """Lazy-initialize Google Gemini client using Vertex AI or API key fallback."""
        if self._client is None:
            try:
                import os
                from google import genai

                project = os.getenv("GOOGLE_CLOUD_PROJECT")
                location = os.getenv("VERTEX_AI_REGION", "us-central1")
                api_key = os.getenv("GOOGLE_API_KEY")

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
                        logger.info(f"TOC LLM Validator using Vertex AI (project={project}, model={self.model})")
                    except Exception as e:
                        logger.warning(f"Vertex AI init failed: {e}, trying API key fallback...")
                        if api_key:
                            self._client = genai.Client(api_key=api_key)
                            logger.info(f"TOC LLM Validator using Gemini API key (model={self.model})")
                        else:
                            raise
                elif api_key:
                    self._client = genai.Client(api_key=api_key)
                    logger.info(f"TOC LLM Validator using Gemini API key (model={self.model})")
                else:
                    raise ValueError(
                        "No Gemini credentials found. Set GOOGLE_CLOUD_PROJECT for Vertex AI "
                        "or GOOGLE_API_KEY for direct API access."
                    )
            except ImportError:
                raise ImportError(
                    "google-genai package required. Install: pip install google-genai"
                )
        return self._client

    def should_validate(self, task, trace_emitter=None) -> bool:
        """Check if this task's TOC needs LLM validation."""
        emitter = trace_emitter or self._trace_emitter

        quality = task.scaffold.get("toc_quality", 0) if task.scaffold else 0
        toc_count = len(task.scaffold.get("toc", [])) if task.scaffold else 0

        # Check if disabled in config
        if not self.enabled:
            # Trace: Red flag if disabled but would have needed validation
            would_need = quality < self.quality_threshold or toc_count < 3
            if would_need:
                emitter.emit_red_flag(
                    "5.7",
                    "llm_disabled_but_needed",
                    {
                        "quality": quality,
                        "threshold": self.quality_threshold,
                        "toc_count": toc_count,
                    },
                )
            emitter.emit_decision(
                "5.7",
                "eligibility",
                "skipped",
                ["will_fire", "skipped"],
                "disabled_in_config",
            )
            return False

        if not task.scaffold:
            emitter.emit_decision(
                "5.7",
                "eligibility",
                "will_fire",
                ["will_fire", "skipped"],
                "no_scaffold",
            )
            return True

        needs_validation = quality < self.quality_threshold or toc_count < 3
        if needs_validation:
            reason = f"quality={quality} < {self.quality_threshold}" if quality < self.quality_threshold else f"toc_count={toc_count} < 3"
            emitter.emit_decision(
                "5.7",
                "eligibility",
                "will_fire",
                ["will_fire", "skipped"],
                reason,
            )
        else:
            emitter.emit_decision(
                "5.7",
                "eligibility",
                "skipped",
                ["will_fire", "skipped"],
                f"quality={quality} >= {self.quality_threshold} and toc_count={toc_count} >= 3",
            )
        return needs_validation

    def validate_toc(self, task, trace_emitter=None) -> dict:
        """
        Validate and potentially correct the TOC using Google Gemini.

        Args:
            task: DocumentTask with scaffold and PDF path
            trace_emitter: Optional TraceEmitter for instrumentation

        Returns:
            Updated scaffold dict
        """
        emitter = trace_emitter or self._trace_emitter

        if not self.should_validate(task, trace_emitter=emitter):
            return task.scaffold

        # Extract raw text from first pages
        document_text = self._extract_early_pages_text(task)
        if not document_text or len(document_text) < 100:
            logger.warning(f"[{task.report_id}] Insufficient text for LLM validation")
            return task.scaffold

        # Build prompt
        existing_toc = task.scaffold.get("toc", []) if task.scaffold else []
        existing_toc_section = ""
        if existing_toc:
            toc_preview = json.dumps(existing_toc[:10], indent=2)
            existing_toc_section = (
                f"\nExisting TOC (may be incomplete or incorrect, please verify and correct):\n"
                f"{toc_preview}\n"
            )

        prompt = self.USER_PROMPT_TEMPLATE.format(
            existing_toc_section=existing_toc_section,
            document_text=document_text[:self.max_input_chars],
        )

        prev_quality = task.scaffold.get("toc_quality", 0) if task.scaffold else 0

        # Call Google Gemini using google-genai SDK
        try:
            from google.genai import types

            client = self._get_client()
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=self.SYSTEM_PROMPT,
                    max_output_tokens=2000,
                    temperature=0,
                ),
            )

            response_text = response.text.strip()

            # Parse JSON response
            llm_toc = self._parse_llm_response(response_text, task.report_id)

            if llm_toc and len(llm_toc) >= 3:
                # Convert logical page numbers to physical
                llm_toc = self._convert_page_numbers(llm_toc, task)

                # Update scaffold
                scaffold = task.scaffold or {"toc": [], "page_map": {}, "heading_positions": {}}
                scaffold["toc"] = llm_toc
                scaffold["toc_method"] = f"{scaffold.get('toc_method', 'unknown')}+llm_validated"
                new_quality = min(85, max(scaffold.get("toc_quality", 0), 70))
                scaffold["toc_quality"] = new_quality

                # Trace: LLM call result - success
                emitter.emit_io(
                    "5.7",
                    {
                        "model": self.model,
                        "input_chars": len(document_text[:self.max_input_chars]),
                        "entries_before": len(existing_toc),
                        "quality_before": prev_quality,
                    },
                    {
                        "entries_after": len(llm_toc),
                        "quality_after": new_quality,
                    },
                )

                # Trace: Sample of TOC changes
                if existing_toc or llm_toc:
                    changes_sample = []
                    for i, entry in enumerate(llm_toc[:5]):
                        before = existing_toc[i] if i < len(existing_toc) else None
                        changes_sample.append({
                            "index": i,
                            "before": before[1][:40] if before else None,
                            "after": entry[1][:40],
                        })
                    emitter.emit_sample("5.7", "toc_changes", changes_sample)

                logger.info(
                    f"[{task.report_id}] LLM validation: {len(llm_toc)} entries "
                    f"(was {len(existing_toc)})"
                )
                return scaffold
            else:
                # Trace: Red flag - LLM returned insufficient entries
                emitter.emit_red_flag(
                    "5.7",
                    "llm_no_effect",
                    {
                        "entries_returned": len(llm_toc) if llm_toc else 0,
                        "reason": "insufficient_entries",
                        "report_id": task.report_id,
                    },
                )
                logger.warning(
                    f"[{task.report_id}] LLM validation returned insufficient entries "
                    f"({len(llm_toc) if llm_toc else 0})"
                )
                return task.scaffold

        except Exception as e:
            # Trace: Error in Gemini LLM call
            emitter.emit_error("5.7", "gemini_api_error", {"message": str(e)[:200]})
            logger.error(f"[{task.report_id}] Gemini LLM validation failed: {e}")
            return task.scaffold

    def _extract_early_pages_text(self, task) -> str:
        """Extract raw text from first pages of the PDF (configured max_pages)."""
        pdf_path = task.ocred_pdf_path or task.local_pdf_path
        if not pdf_path:
            return ""

        try:
            doc = fitz.open(pdf_path)
            text_parts = []
            max_pages = min(self.max_pages, len(doc))

            for page_num in range(max_pages):
                page = doc[page_num]
                text = page.get_text("text")
                if text.strip():
                    text_parts.append(f"--- Page {page_num + 1} ---\n{text}")

            doc.close()
            return "\n\n".join(text_parts)

        except Exception as e:
            logger.warning(f"[{task.report_id}] Failed to extract text for LLM: {e}")
            return ""

    def _parse_llm_response(self, response: str, report_id: str) -> List[List]:
        """Parse LLM response into TOC format."""
        # Try to extract JSON from response
        # Handle cases where LLM wraps in markdown code blocks
        response = response.strip()
        if response.startswith("```"):
            # Remove markdown code fences
            response = re.sub(r'^```(?:json)?\s*', '', response)
            response = re.sub(r'\s*```$', '', response)

        try:
            parsed = json.loads(response)

            if not isinstance(parsed, list):
                logger.warning(f"[{report_id}] LLM response is not a list")
                return []

            # Validate each entry
            valid_entries = []
            for entry in parsed:
                if (isinstance(entry, list) and len(entry) >= 3
                    and isinstance(entry[0], int) and isinstance(entry[1], str)
                    and isinstance(entry[2], (int, float))):
                    valid_entries.append([
                        entry[0],           # level
                        entry[1].strip(),   # title
                        int(entry[2]),      # page
                    ])

            return valid_entries

        except json.JSONDecodeError as e:
            logger.warning(f"[{report_id}] Failed to parse LLM JSON: {e}")
            return []

    def _convert_page_numbers(self, toc: List[List], task) -> List[List]:
        """
        Convert logical (printed) page numbers to physical (0-indexed).

        The LLM returns page numbers as they appear printed in the report.
        We need 0-indexed physical page numbers for the pipeline.
        """
        page_map = task.scaffold.get("page_map", {}) if task.scaffold else {}

        if not page_map:
            # No page map — assume logical page N = physical page N-1
            return [[level, title, max(0, page - 1)] for level, title, page in toc]

        # Invert page_map: logical → physical
        logical_to_physical = {}
        for physical, logical in page_map.items():
            physical_int = int(physical) if isinstance(physical, str) else physical
            logical_str = str(logical)
            logical_to_physical[logical_str] = physical_int

        converted = []
        for level, title, page in toc:
            page_str = str(page)
            if page_str in logical_to_physical:
                physical = logical_to_physical[page_str]
            else:
                # Fallback: assume logical ≈ physical - 1
                physical = max(0, page - 1)
            converted.append([level, title, physical])

        return converted
