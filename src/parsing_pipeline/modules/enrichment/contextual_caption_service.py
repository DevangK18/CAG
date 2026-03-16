"""
Contextual Caption Service: Replaces generic Florence-2 image captions
with semantically meaningful captions derived from document context.

P3-2 IMPLEMENTATION

Strategy:
1. Find the image chunk's position (page, bbox)
2. Look at surrounding text chunks (same page, ±1 page)
3. Look for explicit figure references (e.g., "as shown in Figure 3.1")
4. Build a caption from: section hierarchy + preceding paragraph + figure reference

This provides RAG-ready captions without requiring additional ML models.
"""

import re
from typing import List, Dict, Optional, Tuple, Any


class ContextualCaptionService:
    """
    Replaces generic Florence-2 image captions with contextual captions
    derived from surrounding document text and hierarchy.
    """

    # Patterns for explicit figure/chart references in body text
    FIGURE_REF_PATTERNS = [
        # "as shown in Figure 3.1", "as depicted in Fig. 4.2"
        r"(?:as\s+)?(?:shown|depicted|illustrated|given|presented)\s+in\s+"
        r"(?:the\s+)?(?:Figure|Fig\.|Chart|Graph|Diagram|Map)\s*[\d.]+",

        # "Figure 3.1 shows the revenue trend"
        r"(?:Figure|Fig\.|Chart|Graph|Diagram|Map)\s*[\d.]+\s+"
        r"(?:shows?|depicts?|illustrates?|presents?|gives?)\s+(.{10,120}?)(?:\.|$)",

        # "refer to Figure 3.1", "see Chart 2.3"
        r"(?:refer|see)\s+(?:to\s+)?(?:Figure|Fig\.|Chart|Graph|Diagram|Map)\s*[\d.]+",

        # "(Figure 3.1)", "[Fig. 2.1]"
        r"[\(\[](?:Figure|Fig\.|Chart|Graph)\s*[\d.]+[\)\]]",
    ]

    # Patterns to extract figure number from caption text
    FIGURE_NUM_PATTERN = re.compile(
        r"(?:Figure|Fig\.|Chart|Graph|Diagram|Map)\s*([\d.]+)", re.IGNORECASE
    )

    # Indicators that a caption is generic Florence-2 output
    GENERIC_CAPTION_INDICATORS = [
        "the image shows",
        "the image contains",
        "the image displays",
        "black background",
        "white background",
        "logo and text",
        "a table with",
        "a chart with",
        "the chart shows",
        "the graph shows",
        "text and numbers",
        "text on a",
        "background with",
    ]

    def __init__(self):
        """Initialize the service with compiled regex patterns."""
        self._ref_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.FIGURE_REF_PATTERNS
        ]

    def is_generic_caption(self, caption: str) -> bool:
        """
        Check if a caption is a generic Florence-2 description.

        Args:
            caption: Caption text to check

        Returns:
            True if caption matches generic indicators
        """
        caption_lower = caption.lower().strip()

        # Empty or very short captions are considered generic
        if len(caption_lower) < 10:
            return True

        return any(indicator in caption_lower for indicator in self.GENERIC_CAPTION_INDICATORS)

    def generate_contextual_caption(
        self,
        image_chunk: Dict,
        all_chunks: List[Dict],
        parent_chunks: List[Dict],
    ) -> str:
        """
        Generate a contextual caption for an image chunk.

        Strategy:
        1. Get section context from hierarchy
        2. Find text chunks on same page
        3. Find closest preceding text chunk
        4. Check for figure references with descriptions
        5. Build composite caption

        Args:
            image_chunk: The image chunk dict
            all_chunks: All child chunks in document
            parent_chunks: All parent chunks in document

        Returns:
            New caption string (or original if context insufficient)
        """
        original_caption = image_chunk.get("content", "")
        image_page = image_chunk.get("source_page_physical", -1)

        # Get Y-coordinate for positioning (may not always be available)
        image_bbox = image_chunk.get("metadata", {}).get("location", {}).get("bbox", [])
        image_y = image_bbox[1] if len(image_bbox) >= 2 else 0

        # Step 1: Get section context from hierarchy
        hierarchy = image_chunk.get("hierarchy", {})
        section_context = " > ".join(
            str(hierarchy[k]) for k in sorted(hierarchy.keys()) if hierarchy.get(k)
        )

        # Step 2: Find text chunks on same page, sorted by Y position
        same_page_chunks = [
            c for c in all_chunks
            if c.get("source_page_physical") == image_page
            and c.get("content_type") in ("paragraph", "list", "header")
            and c.get("chunk_id") != image_chunk.get("chunk_id")
        ]

        # Sort by Y position if available
        same_page_chunks.sort(
            key=lambda c: c.get("metadata", {}).get("location", {}).get("bbox", [0, 0])[1]
        )

        # Step 3: Find the closest preceding text chunk
        preceding_text = ""
        for chunk in reversed(same_page_chunks):
            chunk_bbox = chunk.get("metadata", {}).get("location", {}).get("bbox", [0, 9999])
            chunk_y = chunk_bbox[1] if len(chunk_bbox) >= 2 else 0

            # Check if this chunk is above the image
            if chunk_y < image_y or image_y == 0:
                preceding_text = chunk.get("content", "")[:300]
                break

        # Step 4: Check if the preceding text has a figure reference with description
        figure_description = self._extract_figure_description(preceding_text)

        # Step 5: Also check the chunk immediately after the image (captions often appear below)
        following_text = ""
        for chunk in same_page_chunks:
            chunk_bbox = chunk.get("metadata", {}).get("location", {}).get("bbox", [0, 0])
            chunk_y = chunk_bbox[1] if len(chunk_bbox) >= 2 else 0

            if chunk_y > image_y or image_y == 0:
                following_text = chunk.get("content", "")[:300]
                break

        # Check following text for figure description too
        if not figure_description and following_text:
            figure_description = self._extract_figure_description(following_text)

        # Step 6: Also scan ±1 page for figure references (they might be on adjacent pages)
        if not figure_description:
            nearby_chunks = [
                c for c in all_chunks
                if abs(c.get("source_page_physical", -99) - image_page) <= 1
                and c.get("content_type") == "paragraph"
            ]
            for c in nearby_chunks[:20]:  # Limit search to avoid performance issues
                desc = self._extract_figure_description(c.get("content", ""))
                if desc:
                    figure_description = desc
                    break

        # Step 7: Build contextual caption
        parts = []

        # Always include section context if available
        if section_context:
            parts.append(f"[{section_context}]")

        # Add figure description if found
        if figure_description:
            parts.append(figure_description)
        elif preceding_text:
            # Use first sentence of preceding paragraph as context
            sentences = re.split(r'(?<=[.!?])\s+', preceding_text)
            first_sentence = sentences[0] if sentences else preceding_text[:150]

            # Only use if it's substantive (not just a heading)
            if len(first_sentence) > 20 and not first_sentence.isupper():
                parts.append(f"Visual related to: {first_sentence}")

        # If we still have nothing useful, tag the original
        if not parts:
            if section_context:
                return f"[Image in {section_context}] {original_caption}"
            else:
                return f"[Document image] {original_caption}"

        return " ".join(parts)

    def _extract_figure_description(self, text: str) -> Optional[str]:
        """
        Extract figure description from text that references a figure.

        Args:
            text: Text to search for figure references

        Returns:
            Extracted description or None
        """
        if not text:
            return None

        for pattern in self._ref_patterns:
            match = pattern.search(text)
            if match:
                # If the pattern captured a description group, use it
                if match.lastindex and match.lastindex >= 1:
                    desc = match.group(1).strip()
                    # Clean up the description
                    if len(desc) > 10:
                        return desc

                # Otherwise, look for the sentence containing the reference
                # Find sentence boundaries around the match
                match_start = match.start()
                match_end = match.end()

                # Find sentence start (look backward for period/start)
                sentence_start = max(0, text.rfind('.', 0, match_start) + 1)

                # Find sentence end (look forward for period)
                sentence_end = text.find('.', match_end)
                if sentence_end == -1:
                    sentence_end = len(text)
                else:
                    sentence_end += 1

                sentence = text[sentence_start:sentence_end].strip()

                # Return the full sentence if it's informative
                if len(sentence) > 20 and len(sentence) < 200:
                    return sentence

        return None

    def replace_generic_captions(
        self,
        child_chunks: List[Dict],
        parent_chunks: List[Dict],
    ) -> Tuple[int, int]:
        """
        Batch-replace generic captions across all child chunks.
        Modifies child_chunks in place.

        Args:
            child_chunks: List of child chunk dicts
            parent_chunks: List of parent chunk dicts

        Returns:
            Tuple of (total_images, replaced_count)
        """
        image_chunks = [
            c for c in child_chunks
            if c.get("content_type") == "image_caption"
        ]

        replaced = 0

        for img in image_chunks:
            original_caption = img.get("content", "")

            if self.is_generic_caption(original_caption):
                new_caption = self.generate_contextual_caption(
                    img, child_chunks, parent_chunks
                )

                # Replace if the new caption is different and has added context
                # Check for context markers like [Section] or substantive improvement
                has_context = (
                    "[" in new_caption  # Has hierarchy context
                    or "Figure" in new_caption  # Has figure reference
                    or "Visual related to" in new_caption  # Has preceding text context
                    or len(new_caption) > len(original_caption)  # Is longer (more info)
                )

                if new_caption != original_caption and has_context:
                    img["content"] = new_caption

                    # Track provenance in metadata
                    if "metadata" not in img:
                        img["metadata"] = {}
                    img["metadata"]["caption_source"] = "contextual"
                    img["metadata"]["original_caption"] = original_caption

                    replaced += 1

        return len(image_chunks), replaced

    def get_statistics(self, child_chunks: List[Dict]) -> Dict[str, Any]:
        """
        Get caption quality statistics for a document.

        Args:
            child_chunks: List of child chunk dicts

        Returns:
            Statistics dict with counts and percentages
        """
        image_chunks = [
            c for c in child_chunks
            if c.get("content_type") == "image_caption"
        ]

        if not image_chunks:
            return {
                "total_images": 0,
                "generic_count": 0,
                "contextual_count": 0,
                "generic_rate": 0.0,
            }

        generic_count = sum(
            1 for img in image_chunks
            if self.is_generic_caption(img.get("content", ""))
        )

        contextual_count = sum(
            1 for img in image_chunks
            if img.get("metadata", {}).get("caption_source") == "contextual"
        )

        generic_rate = (generic_count / len(image_chunks)) * 100 if image_chunks else 0.0

        return {
            "total_images": len(image_chunks),
            "generic_count": generic_count,
            "contextual_count": contextual_count,
            "generic_rate": round(generic_rate, 2),
            "replacement_success_rate": round((contextual_count / len(image_chunks)) * 100, 2) if image_chunks else 0.0,
        }
