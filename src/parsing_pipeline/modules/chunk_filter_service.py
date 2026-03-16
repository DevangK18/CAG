"""
ChunkFilterService: Filter garbage and noise chunks before assembly.
Implements filtering rules from diagnostic report.
"""

import re
from typing import List, Tuple
from src.core.data_contracts import ExtractedContent


class ChunkFilterService:
    """
    Filters extracted content to remove garbage, noise, and invalid chunks.

    Filtering rules:
    - Minimum content length
    - Pattern-based rejection (page numbers, section numbers, etc.)
    - Duplicate content removal
    - Content type validation
    """

    # Garbage patterns to reject
    GARBAGE_PATTERNS = [
        r"^[ivxlc]+$",  # Roman numerals only
        r"^\d{1,3}$",  # Page numbers only (1-3 digits)
        r"^\d+\.\d+(\.\d+)?$",  # Section numbers only
        r"^\(\d+\)$",  # Numbered markers
        r"^\(Paragraph\s+\d+\.\d+\)$",  # Cross-references
        r"^\(Para\s+\d+\.\d+\)$",  # Short cross-references
        r"^[A-Z]\.$",  # Single letter markers
        r"^\*+$",  # Asterisks only
        r"^[-–—]+$",  # Dashes only
        r"^\d+\s+\d+\s+\d+\s+\d+",  # Number sequences (table data)
        r"^(Source|Note|Notes)\s*:\s*$",  # Empty citations
    ]

    # Minimum length thresholds by content type
    MIN_LENGTH = {
        "paragraph": 30,
        "header": 3,
        "list": 10,
        "table_markdown": 20,
        "image_caption": 10,
        "chart_data_path": 5,
    }

    def __init__(
        self,
        min_paragraph_length: int = 30,
        max_duplicate_ratio: float = 0.8,
    ):
        self.min_paragraph_length = min_paragraph_length
        self.max_duplicate_ratio = max_duplicate_ratio

        # Compile patterns for efficiency
        self._garbage_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.GARBAGE_PATTERNS
        ]

    def filter_extracted_content(
        self,
        content_list: List[ExtractedContent],
    ) -> Tuple[List[ExtractedContent], List[ExtractedContent]]:
        """
        Filter extracted content, separating valid from garbage.

        Args:
            content_list: List of ExtractedContent objects

        Returns:
            Tuple of (valid_content, filtered_content)
        """
        valid = []
        filtered = []
        seen_content = {}  # For deduplication

        for content in content_list:
            is_valid, reason = self._validate_content(content, seen_content)

            if is_valid:
                # Track content for deduplication
                content_key = self._get_content_key(content)
                seen_content[content_key] = seen_content.get(content_key, 0) + 1
                valid.append(content)
            else:
                filtered.append(content)

        return (valid, filtered)

    def _validate_content(
        self,
        content: ExtractedContent,
        seen_content: dict,
    ) -> Tuple[bool, str]:
        """
        Validate a single content item.

        Returns:
            Tuple of (is_valid, rejection_reason)
        """
        text = content.content.strip()
        content_type = content.content_type

        # Check 1: Empty content
        if not text:
            return (False, "empty_content")

        # Check 2: Minimum length by type
        min_length = self.MIN_LENGTH.get(content_type, 20)
        if len(text) < min_length:
            return (False, f"too_short_{len(text)}_chars")

        # Check 3: Pattern-based rejection (for paragraph/text types)
        if content_type in ("paragraph", "header", "list"):
            for pattern in self._garbage_patterns:
                if pattern.match(text):
                    return (False, f"matches_garbage_pattern")

        # Check 4: Deduplication
        content_key = self._get_content_key(content)
        if content_key in seen_content and seen_content[content_key] >= 2:
            return (False, "duplicate_content")

        # Check 5: Whitespace ratio (mostly whitespace = garbage)
        if len(text) > 10:
            non_whitespace = len(text.replace(" ", "").replace("\n", ""))
            whitespace_ratio = 1 - (non_whitespace / len(text))
            if whitespace_ratio > 0.7:
                return (False, "excessive_whitespace")

        return (True, "")

    def _get_content_key(self, content: ExtractedContent) -> str:
        """Generate a key for content deduplication."""
        # For image_caption (which now stores file paths), use full path for uniqueness
        # V2 fix: Image paths can be very long and share common prefixes
        if content.content_type in ("image_caption", "chart_data_path"):
            # Use full content for images (file paths must be unique)
            return f"{content.content_type}:{content.content.strip().lower()}"

        # For text content, normalize and truncate for comparison
        text = content.content.strip().lower()[:100]
        return f"{content.content_type}:{text}"
