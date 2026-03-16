"""
LLM-based TOC Validator (Phase 5.7)

For reports where Phase 4 + Phase 5.5 still produce low-quality TOCs
(quality < 50), uses Claude Haiku to validate and correct the TOC
by analyzing the first ~15 pages of raw text.

This is a LAST RESORT — only called for ~10-20% of reports.
Cost: ~$0.01-0.02 per report via Claude Haiku.
"""

import json
import logging
import re
from typing import Dict, List, Optional, Tuple

import fitz  # PyMuPDF

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger(__name__)


class TOCLLMValidator:
    """
    Uses Claude Haiku to validate/correct low-quality TOCs.

    Strategy:
    - Extract raw text from first 15 pages
    - Send existing TOC (if any) + raw text to Claude Haiku
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
        model: str = "claude-haiku-4-5-20251001",
        max_input_chars: int = 8000,
        quality_threshold: int = 50,
    ):
        """
        Args:
            model: Claude model to use (Haiku for cost efficiency)
            max_input_chars: Max chars of document text to send
            quality_threshold: Only validate TOCs with quality below this
        """
        self.model = model
        self.max_input_chars = max_input_chars
        self.quality_threshold = quality_threshold
        self._client = None

    def _get_client(self):
        """Lazy-initialize Anthropic client."""
        if self._client is None:
            try:
                from anthropic import Anthropic
                self._client = Anthropic()  # Uses ANTHROPIC_API_KEY env var
            except ImportError:
                raise ImportError("Install anthropic: pip install anthropic")
        return self._client

    def should_validate(self, task) -> bool:
        """Check if this task's TOC needs LLM validation."""
        if not task.scaffold:
            return True
        quality = task.scaffold.get("toc_quality", 0)
        toc = task.scaffold.get("toc", [])
        return quality < self.quality_threshold or len(toc) < 3

    def validate_toc(self, task) -> dict:
        """
        Validate and potentially correct the TOC using Claude Haiku.

        Args:
            task: DocumentTask with scaffold and PDF path

        Returns:
            Updated scaffold dict
        """
        if not self.should_validate(task):
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

        # Call Claude Haiku
        try:
            client = self._get_client()
            response = client.messages.create(
                model=self.model,
                max_tokens=2000,
                temperature=0,
                system=self.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )

            response_text = response.content[0].text.strip()

            # Parse JSON response
            llm_toc = self._parse_llm_response(response_text, task.report_id)

            if llm_toc and len(llm_toc) >= 3:
                # Convert logical page numbers to physical
                llm_toc = self._convert_page_numbers(llm_toc, task)

                # Update scaffold
                scaffold = task.scaffold or {"toc": [], "page_map": {}, "heading_positions": {}}
                scaffold["toc"] = llm_toc
                scaffold["toc_method"] = f"{scaffold.get('toc_method', 'unknown')}+llm_validated"
                scaffold["toc_quality"] = min(85, max(scaffold.get("toc_quality", 0), 70))

                logger.info(
                    f"[{task.report_id}] LLM validation: {len(llm_toc)} entries "
                    f"(was {len(existing_toc)})"
                )
                return scaffold
            else:
                logger.warning(
                    f"[{task.report_id}] LLM validation returned insufficient entries "
                    f"({len(llm_toc) if llm_toc else 0})"
                )
                return task.scaffold

        except Exception as e:
            logger.error(f"[{task.report_id}] LLM validation failed: {e}")
            return task.scaffold

    def _extract_early_pages_text(self, task) -> str:
        """Extract raw text from first ~15 pages of the PDF."""
        pdf_path = task.ocred_pdf_path or task.local_pdf_path
        if not pdf_path:
            return ""

        try:
            doc = fitz.open(pdf_path)
            text_parts = []
            max_pages = min(15, len(doc))

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
