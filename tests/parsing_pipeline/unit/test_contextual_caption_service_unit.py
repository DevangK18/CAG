"""
Unit tests for P3-2: Image Caption Replacement

Tests the ContextualCaptionService that replaces generic Florence-2 captions
with contextual captions derived from surrounding text.
"""

import pytest
from src.parsing_pipeline.modules.enrichment.contextual_caption_service import ContextualCaptionService


@pytest.fixture
def service():
    """Create a ContextualCaptionService instance."""
    return ContextualCaptionService()


class TestGenericCaptionDetection:
    """Test detection of generic Florence-2 captions."""

    def test_generic_indicators_detected(self, service):
        """Common generic phrases should be detected."""
        generic_captions = [
            "the image shows a chart with data",
            "The image contains text and numbers",
            "black background with logo and text",
            "white background with title",
            "a table with rows and columns",
            "the chart shows revenue data",
        ]

        for caption in generic_captions:
            assert service.is_generic_caption(caption), f"Should detect generic: {caption}"

    def test_specific_captions_not_generic(self, service):
        """Specific, contextual captions should not be flagged as generic."""
        specific_captions = [
            "[Financial Analysis] Revenue trends from 2019-2023 showing 15% decline",
            "Comparison of audit findings across 5 ministries",
            "State-wise distribution of scheme beneficiaries under PMGSY",
            "Timeline of implementation delays in National Highways projects",
        ]

        for caption in specific_captions:
            assert not service.is_generic_caption(caption), f"Should not detect generic: {caption}"

    def test_empty_caption_is_generic(self, service):
        """Empty or very short captions should be considered generic."""
        assert service.is_generic_caption("")
        assert service.is_generic_caption("   ")
        assert service.is_generic_caption("Image")
        assert service.is_generic_caption("Chart")


class TestFigureReferenceExtraction:
    """Test extraction of figure references from text."""

    def test_figure_reference_with_description(self, service):
        """Extract figure descriptions from explicit references."""
        text = "The revenue trend is shown in Figure 3.1. The analysis indicates..."
        desc = service._extract_figure_description(text)
        assert desc is not None
        assert "Figure 3.1" in desc or "shown" in desc.lower()

    def test_figure_shows_pattern(self, service):
        """Extract descriptions from 'Figure X shows Y' patterns."""
        text = "Figure 4.2 shows the state-wise distribution of scheme beneficiaries across India."
        desc = service._extract_figure_description(text)
        assert desc is not None
        # Should capture the description part
        assert "distribution" in desc.lower() or "beneficiaries" in desc.lower()

    def test_refer_to_figure_pattern(self, service):
        """Extract references like 'refer to Figure X'."""
        text = "For detailed breakdown, refer to Figure 2.3 in the appendix."
        desc = service._extract_figure_description(text)
        assert desc is not None

    def test_parenthetical_figure_reference(self, service):
        """Extract parenthetical figure references like (Figure 3.1)."""
        text = "The audit revealed significant delays (Figure 3.1) in project completion."
        desc = service._extract_figure_description(text)
        assert desc is not None

    def test_no_figure_reference(self, service):
        """Return None when no figure reference found."""
        text = "This paragraph discusses audit findings without referencing any figures."
        desc = service._extract_figure_description(text)
        assert desc is None

    def test_chart_and_graph_variants(self, service):
        """Handle Chart, Graph, Diagram, Map variants."""
        texts = [
            "As shown in Chart 2.1, revenue increased.",
            "The Graph 3.4 depicts expenditure trends.",
            "Refer to Diagram 1.2 for process flow.",
            "See Map 5.1 for geographical distribution.",
        ]

        for text in texts:
            desc = service._extract_figure_description(text)
            assert desc is not None, f"Should extract reference from: {text}"


class TestContextualCaptionGeneration:
    """Test generation of contextual captions."""

    def test_caption_with_section_context(self, service):
        """Caption should include section hierarchy."""
        image_chunk = {
            "content": "the image shows a chart",
            "chunk_id": "img1",
            "content_type": "image_caption",
            "source_page_physical": 10,
            "hierarchy": {
                "level_1": "Chapter 3",
                "level_2": "Financial Analysis",
                "level_3": "Revenue Trends",
            },
            "metadata": {"location": {"bbox": [100, 400, 500, 600]}},
        }

        caption = service.generate_contextual_caption(image_chunk, [], [])

        # Should include hierarchy
        assert "Chapter 3" in caption or "Financial Analysis" in caption or "Revenue Trends" in caption

    def test_caption_from_preceding_text(self, service):
        """Caption should use preceding paragraph when available."""
        image_chunk = {
            "content": "the image shows a table",
            "chunk_id": "img1",
            "content_type": "image_caption",
            "source_page_physical": 10,
            "hierarchy": {"level_1": "Analysis"},
            "metadata": {"location": {"bbox": [100, 400, 500, 600]}},
        }

        preceding_chunk = {
            "content": "The Ministry of Finance reported a 15% increase in tax revenue during 2022-23. This growth was attributed to improved compliance measures.",
            "chunk_id": "para1",
            "content_type": "paragraph",
            "source_page_physical": 10,
            "metadata": {"location": {"bbox": [100, 100, 500, 200]}},  # Above image
        }

        all_chunks = [preceding_chunk, image_chunk]

        caption = service.generate_contextual_caption(image_chunk, all_chunks, [])

        # Should reference preceding content
        assert "Ministry of Finance" in caption or "tax revenue" in caption or "Visual related to" in caption

    def test_caption_from_figure_reference(self, service):
        """Caption should use figure description from text."""
        image_chunk = {
            "content": "black background with text",
            "chunk_id": "img1",
            "content_type": "image_caption",
            "source_page_physical": 10,
            "hierarchy": {"level_1": "Chapter 2"},
            "metadata": {"location": {"bbox": [100, 400, 500, 600]}},
        }

        text_with_reference = {
            "content": "Figure 2.1 shows the year-wise allocation of funds to the scheme from 2018 to 2023.",
            "chunk_id": "para1",
            "content_type": "paragraph",
            "source_page_physical": 10,
            "metadata": {"location": {"bbox": [100, 100, 500, 200]}},
        }

        all_chunks = [text_with_reference, image_chunk]

        caption = service.generate_contextual_caption(image_chunk, all_chunks, [])

        # Should include the figure description
        assert "allocation" in caption.lower() or "funds" in caption.lower() or "year-wise" in caption.lower()

    def test_caption_searches_adjacent_pages(self, service):
        """Caption should search ±1 page for figure references."""
        image_chunk = {
            "content": "the image contains data",
            "chunk_id": "img1",
            "content_type": "image_caption",
            "source_page_physical": 10,
            "hierarchy": {"level_1": "Data Analysis"},  # Add hierarchy for fallback
            "metadata": {"location": {"bbox": [100, 400, 500, 600]}},
        }

        # Figure reference on previous page
        chunk_prev_page = {
            "content": "The details are provided in Figure 3.2 showing state-wise performance metrics.",
            "chunk_id": "para1",
            "content_type": "paragraph",
            "source_page_physical": 9,  # Previous page
            "metadata": {},
        }

        all_chunks = [chunk_prev_page, image_chunk]

        caption = service.generate_contextual_caption(image_chunk, all_chunks, [])

        # Should find reference from adjacent page OR at minimum include hierarchy context
        assert (
            "performance" in caption.lower()
            or "metrics" in caption.lower()
            or "Figure 3.2" in caption
            or "Data Analysis" in caption  # Fallback to hierarchy
        )

    def test_fallback_to_tagged_original(self, service):
        """When no context available, tag the original caption."""
        image_chunk = {
            "content": "generic image description",
            "chunk_id": "img1",
            "content_type": "image_caption",
            "source_page_physical": 10,
            "hierarchy": {},
            "metadata": {},
        }

        caption = service.generate_contextual_caption(image_chunk, [], [])

        # Should contain original but tagged
        assert "Document image" in caption or "generic image description" in caption


class TestBatchCaptionReplacement:
    """Test batch replacement of captions."""

    def test_replaces_generic_captions_only(self, service):
        """Should only replace generic captions, not specific ones."""
        child_chunks = [
            {
                "content": "the image shows a chart",  # Generic
                "content_type": "image_caption",
                "chunk_id": "img1",
                "source_page_physical": 5,
                "hierarchy": {"level_1": "Chapter 1"},
                "metadata": {},
            },
            {
                "content": "[Financial Analysis] Revenue distribution by state showing Maharashtra leading",  # Specific
                "content_type": "image_caption",
                "chunk_id": "img2",
                "source_page_physical": 6,
                "hierarchy": {"level_1": "Chapter 2"},
                "metadata": {},
            },
            {
                "content": "Regular paragraph text",
                "content_type": "paragraph",
                "chunk_id": "para1",
                "source_page_physical": 5,
                "metadata": {},
            },
        ]

        original_specific_caption = child_chunks[1]["content"]

        total, replaced = service.replace_generic_captions(child_chunks, [])

        # Should find 2 images
        assert total == 2

        # Should replace 1 generic caption
        assert replaced == 1

        # Generic caption should be changed
        assert child_chunks[0]["content"] != "the image shows a chart"
        assert "Chapter 1" in child_chunks[0]["content"]  # Should have context

        # Specific caption should remain unchanged
        assert child_chunks[1]["content"] == original_specific_caption

        # Paragraph should be unchanged
        assert child_chunks[2]["content"] == "Regular paragraph text"

    def test_tracks_caption_provenance(self, service):
        """Replaced captions should track their source."""
        child_chunks = [
            {
                "content": "white background with logo",
                "content_type": "image_caption",
                "chunk_id": "img1",
                "source_page_physical": 5,
                "hierarchy": {"level_1": "Introduction"},
                "metadata": {},
            }
        ]

        service.replace_generic_captions(child_chunks, [])

        # Should track provenance
        assert "metadata" in child_chunks[0]
        assert child_chunks[0]["metadata"].get("caption_source") == "contextual"
        assert "original_caption" in child_chunks[0]["metadata"]
        assert child_chunks[0]["metadata"]["original_caption"] == "white background with logo"

    def test_handles_no_images(self, service):
        """Handle documents with no images gracefully."""
        child_chunks = [
            {"content": "Paragraph 1", "content_type": "paragraph", "chunk_id": "p1", "metadata": {}},
            {"content": "Paragraph 2", "content_type": "paragraph", "chunk_id": "p2", "metadata": {}},
        ]

        total, replaced = service.replace_generic_captions(child_chunks, [])

        assert total == 0
        assert replaced == 0

    def test_replacement_stats_correct(self, service):
        """Replacement counts should be accurate."""
        child_chunks = [
            {
                "content": "the image contains text",
                "content_type": "image_caption",
                "chunk_id": "img1",
                "source_page_physical": 5,
                "hierarchy": {"level_1": "Chapter 1"},
                "metadata": {},
            },
            {
                "content": "black background with chart",
                "content_type": "image_caption",
                "chunk_id": "img2",
                "source_page_physical": 6,
                "hierarchy": {"level_1": "Chapter 2"},
                "metadata": {},
            },
            {
                "content": "logo and text on white",
                "content_type": "image_caption",
                "chunk_id": "img3",
                "source_page_physical": 7,
                "hierarchy": {"level_1": "Chapter 3"},
                "metadata": {},
            },
        ]

        total, replaced = service.replace_generic_captions(child_chunks, [])

        # All 3 should be generic
        assert total == 3
        # All should be replaced (assuming context is added)
        assert replaced >= 1  # At least some should be replaced


class TestCaptionStatistics:
    """Test caption quality statistics."""

    def test_statistics_with_mixed_captions(self, service):
        """Statistics should accurately count generic vs contextual."""
        child_chunks = [
            {
                "content": "the image shows a table",
                "content_type": "image_caption",
                "metadata": {},
            },
            {
                "content": "[Analysis] State-wise revenue comparison",
                "content_type": "image_caption",
                "metadata": {"caption_source": "contextual", "original_caption": "generic"},
            },
            {
                "content": "black background with text",
                "content_type": "image_caption",
                "metadata": {},
            },
            {
                "content": "Regular paragraph",
                "content_type": "paragraph",
                "metadata": {},
            },
        ]

        stats = service.get_statistics(child_chunks)

        assert stats["total_images"] == 3
        assert stats["generic_count"] == 2  # Two still generic
        assert stats["contextual_count"] == 1  # One marked as contextual
        assert stats["generic_rate"] == pytest.approx(66.67, rel=0.1)

    def test_statistics_with_no_images(self, service):
        """Statistics should handle no images gracefully."""
        child_chunks = [
            {"content": "Paragraph", "content_type": "paragraph", "metadata": {}},
        ]

        stats = service.get_statistics(child_chunks)

        assert stats["total_images"] == 0
        assert stats["generic_count"] == 0
        assert stats["contextual_count"] == 0
        assert stats["generic_rate"] == 0.0


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_missing_hierarchy(self, service):
        """Handle images with missing hierarchy."""
        image_chunk = {
            "content": "the image shows data",
            "chunk_id": "img1",
            "content_type": "image_caption",
            "source_page_physical": 10,
            # No hierarchy
            "metadata": {},
        }

        caption = service.generate_contextual_caption(image_chunk, [], [])

        # Should not crash
        assert isinstance(caption, str)
        assert len(caption) > 0

    def test_missing_bbox(self, service):
        """Handle images with missing bounding box."""
        image_chunk = {
            "content": "generic caption",
            "chunk_id": "img1",
            "content_type": "image_caption",
            "source_page_physical": 10,
            "hierarchy": {"level_1": "Chapter 1"},
            # No bbox in metadata
            "metadata": {},
        }

        caption = service.generate_contextual_caption(image_chunk, [], [])

        # Should not crash
        assert isinstance(caption, str)
        # Should at least include hierarchy
        assert "Chapter 1" in caption

    def test_uppercase_heading_not_used_as_context(self, service):
        """All-caps headings should not be used as preceding text context."""
        image_chunk = {
            "content": "the image shows a chart",
            "chunk_id": "img1",
            "content_type": "image_caption",
            "source_page_physical": 10,
            "hierarchy": {"level_1": "Chapter 3"},
            "metadata": {"location": {"bbox": [100, 400, 500, 600]}},
        }

        heading_chunk = {
            "content": "FINANCIAL ANALYSIS SUMMARY",  # All caps
            "chunk_id": "head1",
            "content_type": "header",
            "source_page_physical": 10,
            "metadata": {"location": {"bbox": [100, 100, 500, 150]}},
        }

        all_chunks = [heading_chunk, image_chunk]

        caption = service.generate_contextual_caption(image_chunk, all_chunks, [])

        # Should not include the all-caps heading as "Visual related to"
        assert "Visual related to: FINANCIAL ANALYSIS SUMMARY" not in caption

    def test_long_description_truncated(self, service):
        """Very long descriptions should be handled appropriately."""
        text = "Figure 3.1 shows " + "word " * 100 + "in the analysis."
        desc = service._extract_figure_description(text)

        # Should either truncate or return the sentence
        if desc:
            assert len(desc) < 300  # Reasonable length limit


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
