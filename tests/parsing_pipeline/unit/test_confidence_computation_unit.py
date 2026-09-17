"""
Unit tests for P3-4: Confidence Propagation

Tests composite confidence computation including:
1. Layout confidence weighting
2. TOC quality score weighting
3. Content quality heuristics
4. Composite scoring
"""

import pytest
from pathlib import Path
from src.parsing_pipeline.modules.assembly_service import AssemblyService


@pytest.fixture
def assembly_service():
    """Fixture providing an AssemblyService instance."""
    output_dir = Path("/tmp/test_assembly")
    output_dir.mkdir(exist_ok=True)
    return AssemblyService(output_dir=output_dir)


@pytest.fixture
def sample_parent_chunks():
    """Fixture providing sample parent chunks."""
    return [
        {
            "chunk_id": "parent_1",
            "page_range_physical": [1, 10],
            "toc_entry": "Chapter 1"
        },
        {
            "chunk_id": "parent_wide",
            "page_range_physical": [1, 60],
            "toc_entry": "Entire Report"
        }
    ]


# ==================== LAYOUT CONFIDENCE TESTS ====================


def test_layout_confidence_high(assembly_service, sample_parent_chunks):
    """Test confidence with high layout confidence."""
    child = {
        "content": "This is a well-extracted paragraph with good layout confidence.",
        "metadata": {
            "extraction": {
                "layout_confidence": 0.95
            }
        },
        "content_type": "paragraph"
    }

    confidence = assembly_service._compute_chunk_confidence(child, sample_parent_chunks, 80.0)

    # With layout=0.95, toc=0.8, content=1.0: 0.95*0.4 + 0.8*0.3 + 1.0*0.3 = 0.38 + 0.24 + 0.3 = 0.92
    assert confidence >= 0.90


def test_layout_confidence_low(assembly_service, sample_parent_chunks):
    """Test confidence with low layout confidence."""
    child = {
        "content": "This paragraph has low layout confidence.",
        "metadata": {
            "extraction": {
                "layout_confidence": 0.3
            }
        },
        "content_type": "paragraph"
    }

    confidence = assembly_service._compute_chunk_confidence(child, sample_parent_chunks, 80.0)

    # With layout=0.3, toc=0.8, content=1.0: 0.3*0.4 + 0.8*0.3 + 1.0*0.3 = 0.12 + 0.24 + 0.3 = 0.66
    assert confidence < 0.7


def test_layout_confidence_missing(assembly_service, sample_parent_chunks):
    """Test confidence when layout confidence is missing (defaults to 0.5)."""
    child = {
        "content": "This paragraph has no layout confidence metadata.",
        "content_type": "paragraph"
    }

    confidence = assembly_service._compute_chunk_confidence(child, sample_parent_chunks, 80.0)

    # With layout=0.5 (default), toc=0.8, content=1.0: 0.5*0.4 + 0.8*0.3 + 1.0*0.3 = 0.2 + 0.24 + 0.3 = 0.74
    assert 0.7 <= confidence <= 0.8


# ==================== TOC QUALITY TESTS ====================


def test_toc_quality_high(assembly_service, sample_parent_chunks):
    """Test confidence with high TOC quality."""
    child = {
        "content": "Paragraph with excellent TOC quality.",
        "content_type": "paragraph"
    }

    confidence = assembly_service._compute_chunk_confidence(child, sample_parent_chunks, 95.0)

    # With layout=0.5, toc=0.95, content=1.0: 0.5*0.4 + 0.95*0.3 + 1.0*0.3 = 0.2 + 0.285 + 0.3 = 0.785
    assert confidence >= 0.75


def test_toc_quality_low(assembly_service, sample_parent_chunks):
    """Test confidence with low TOC quality."""
    child = {
        "content": "Paragraph with poor TOC quality.",
        "content_type": "paragraph"
    }

    confidence = assembly_service._compute_chunk_confidence(child, sample_parent_chunks, 40.0)

    # With layout=0.5, toc=0.4, content=1.0: 0.5*0.4 + 0.4*0.3 + 1.0*0.3 = 0.2 + 0.12 + 0.3 = 0.62
    assert confidence < 0.7


def test_toc_quality_capped_at_one(assembly_service, sample_parent_chunks):
    """Test that TOC quality is capped at 1.0 even if score > 100."""
    child = {
        "content": "Paragraph with TOC quality over 100.",
        "content_type": "paragraph"
    }

    confidence = assembly_service._compute_chunk_confidence(child, sample_parent_chunks, 150.0)

    # TOC should be capped at 1.0
    # With layout=0.5, toc=1.0, content=1.0: 0.5*0.4 + 1.0*0.3 + 1.0*0.3 = 0.2 + 0.3 + 0.3 = 0.8
    assert confidence == 0.8


# ==================== CONTENT QUALITY HEURISTICS TESTS ====================


def test_content_quality_short_content(assembly_service, sample_parent_chunks):
    """Test penalty for very short content (<20 chars)."""
    child = {
        "content": "Short",  # 5 chars
        "content_type": "paragraph"
    }

    confidence = assembly_service._compute_chunk_confidence(child, sample_parent_chunks, 80.0)

    # Content score *= 0.5 due to short content
    # With layout=0.5, toc=0.8, content=0.5: 0.5*0.4 + 0.8*0.3 + 0.5*0.3 = 0.2 + 0.24 + 0.15 = 0.59
    assert confidence < 0.65


def test_content_quality_table_fragment(assembly_service, sample_parent_chunks):
    """Test penalty for high number-to-word ratio (table fragment)."""
    child = {
        "content": "123 456 789 101 202 303 404 505 word anotherword",  # Many numbers, few words
        "content_type": "paragraph"
    }

    confidence = assembly_service._compute_chunk_confidence(child, sample_parent_chunks, 80.0)

    # 8 numbers, 2 words -> ratio > 2 -> content_score *= 0.7
    # With layout=0.5, toc=0.8, content=0.7: 0.5*0.4 + 0.8*0.3 + 0.7*0.3 = 0.2 + 0.24 + 0.21 = 0.65
    assert confidence < 0.7


def test_content_quality_generic_image_caption(assembly_service, sample_parent_chunks):
    """Test penalty for generic image captions."""
    child = {
        "content": "the image shows a black background with some text",
        "content_type": "image_caption"
    }

    confidence = assembly_service._compute_chunk_confidence(child, sample_parent_chunks, 80.0)

    # Content score *= 0.3 due to generic image caption
    # With layout=0.5, toc=0.8, content=0.3: 0.5*0.4 + 0.8*0.3 + 0.3*0.3 = 0.2 + 0.24 + 0.09 = 0.53
    assert confidence < 0.6


def test_content_quality_contextual_image_caption(assembly_service, sample_parent_chunks):
    """Test no penalty for contextual (non-generic) image captions."""
    child = {
        "content": "[Chapter 3] Figure 3.1 shows revenue trends from 2018 to 2023",
        "content_type": "image_caption"
    }

    confidence = assembly_service._compute_chunk_confidence(child, sample_parent_chunks, 80.0)

    # No penalty for non-generic caption
    # With layout=0.5, toc=0.8, content=1.0: 0.5*0.4 + 0.8*0.3 + 1.0*0.3 = 0.74
    assert confidence >= 0.7


def test_content_quality_orphan_assignment(assembly_service, sample_parent_chunks):
    """Test penalty for orphan-like assignment (parent with wide page range)."""
    child = {
        "content": "This paragraph is assigned to a parent covering 60 pages.",
        "content_type": "paragraph",
        "parent_chunk_id": "parent_wide"
    }

    confidence = assembly_service._compute_chunk_confidence(child, sample_parent_chunks, 80.0)

    # Content score *= 0.6 due to wide parent (>50 pages)
    # With layout=0.5, toc=0.8, content=0.6: 0.5*0.4 + 0.8*0.3 + 0.6*0.3 = 0.2 + 0.24 + 0.18 = 0.62
    assert confidence < 0.7


def test_content_quality_good_assignment(assembly_service, sample_parent_chunks):
    """Test no penalty for good parent assignment (narrow page range)."""
    child = {
        "content": "This paragraph is assigned to a parent covering 10 pages.",
        "content_type": "paragraph",
        "parent_chunk_id": "parent_1"
    }

    confidence = assembly_service._compute_chunk_confidence(child, sample_parent_chunks, 80.0)

    # No orphan penalty (parent span = 9 pages < 50)
    # With layout=0.5, toc=0.8, content=1.0: 0.5*0.4 + 0.8*0.3 + 1.0*0.3 = 0.74
    assert confidence >= 0.7


# ==================== COMPOSITE SCORING TESTS ====================


def test_composite_perfect_score(assembly_service, sample_parent_chunks):
    """Test composite score with all factors at maximum."""
    child = {
        "content": "This is an excellent paragraph with perfect extraction quality.",
        "metadata": {
            "extraction": {
                "layout_confidence": 1.0
            }
        },
        "content_type": "paragraph",
        "parent_chunk_id": "parent_1"
    }

    confidence = assembly_service._compute_chunk_confidence(child, sample_parent_chunks, 100.0)

    # With layout=1.0, toc=1.0, content=1.0: 1.0*0.4 + 1.0*0.3 + 1.0*0.3 = 1.0
    assert confidence == 1.0


def test_composite_poor_score(assembly_service, sample_parent_chunks):
    """Test composite score with all factors at minimum."""
    child = {
        "content": "Bad",  # Very short
        "metadata": {
            "extraction": {
                "layout_confidence": 0.2
            }
        },
        "content_type": "paragraph"
    }

    confidence = assembly_service._compute_chunk_confidence(child, sample_parent_chunks, 30.0)

    # With layout=0.2, toc=0.3, content=0.5 (short penalty): 0.2*0.4 + 0.3*0.3 + 0.5*0.3 = 0.08 + 0.09 + 0.15 = 0.32
    assert confidence < 0.4


def test_composite_rounding(assembly_service, sample_parent_chunks):
    """Test that confidence is rounded to 3 decimal places."""
    child = {
        "content": "This paragraph will produce a non-round confidence score.",
        "metadata": {
            "extraction": {
                "layout_confidence": 0.777
            }
        },
        "content_type": "paragraph"
    }

    confidence = assembly_service._compute_chunk_confidence(child, sample_parent_chunks, 83.3)

    # Result should be rounded to 3 decimals
    assert isinstance(confidence, float)
    # Check that it has at most 3 decimal places
    assert confidence == round(confidence, 3)


# ==================== EDGE CASES TESTS ====================


def test_empty_content(assembly_service, sample_parent_chunks):
    """Test confidence with empty content."""
    child = {
        "content": "",
        "content_type": "paragraph"
    }

    confidence = assembly_service._compute_chunk_confidence(child, sample_parent_chunks, 80.0)

    # Empty content triggers short content penalty (* 0.5)
    assert confidence < 0.7


def test_no_parent_assignment(assembly_service, sample_parent_chunks):
    """Test confidence when chunk has no parent assignment."""
    child = {
        "content": "This paragraph has no parent assignment.",
        "content_type": "paragraph"
        # No parent_chunk_id
    }

    confidence = assembly_service._compute_chunk_confidence(child, sample_parent_chunks, 80.0)

    # No orphan penalty since no parent
    # With layout=0.5, toc=0.8, content=1.0: 0.74
    assert confidence >= 0.7


def test_parent_not_found(assembly_service, sample_parent_chunks):
    """Test confidence when parent_chunk_id doesn't match any parent."""
    child = {
        "content": "This paragraph's parent doesn't exist.",
        "content_type": "paragraph",
        "parent_chunk_id": "nonexistent_parent"
    }

    confidence = assembly_service._compute_chunk_confidence(child, sample_parent_chunks, 80.0)

    # No orphan penalty since parent not found
    assert confidence >= 0.7


def test_invalid_page_range(assembly_service, sample_parent_chunks):
    """Test confidence when parent has invalid page range format."""
    parent_chunks = [
        {
            "chunk_id": "invalid_parent",
            "page_range_physical": None,  # Invalid
            "toc_entry": "Invalid Parent"
        }
    ]

    child = {
        "content": "Paragraph with invalid parent page range.",
        "content_type": "paragraph",
        "parent_chunk_id": "invalid_parent"
    }

    confidence = assembly_service._compute_chunk_confidence(child, parent_chunks, 80.0)

    # No crash, should handle gracefully
    assert 0.0 <= confidence <= 1.0


def test_multiple_penalties_compound(assembly_service, sample_parent_chunks):
    """Test that multiple penalties compound multiplicatively."""
    child = {
        "content": "123 456",  # Short + high number ratio
        "content_type": "paragraph"
    }

    confidence = assembly_service._compute_chunk_confidence(child, sample_parent_chunks, 80.0)

    # Content score: 1.0 * 0.5 (short) * 0.7 (number ratio) = 0.35
    # With layout=0.5, toc=0.8, content=0.35: 0.5*0.4 + 0.8*0.3 + 0.35*0.3 = 0.2 + 0.24 + 0.105 = 0.545
    assert 0.5 <= confidence <= 0.6


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
