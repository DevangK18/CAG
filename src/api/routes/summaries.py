"""
API Routes for Report Summaries (Phase 10)

Endpoints:
- GET /reports/{report_id}/summaries - List available summary variants
- GET /reports/{report_id}/summaries/{variant} - Get specific summary
- GET /reports/{report_id}/summaries/random - Get random variant (Surprise Me)
- GET /reports/{report_id}/summaries/{variant}/metadata - Get metadata only
"""

from fastapi import APIRouter, HTTPException
from pathlib import Path
import json
import random
from typing import Optional

router = APIRouter(tags=["summaries"])

# Configure data directory - use organized folder structure
BATCH_JOBS_DIR = Path("data/batch_jobs")
SUMMARIES_DIR = BATCH_JOBS_DIR / "summaries"

# Variant metadata with proper emoji encoding
VARIANT_INFO = {
    "executive": {
        "name": "Executive Brief",
        "icon": "📋",
        "description": "Boardroom-ready summary with key findings and action items",
        "audience": "Senior officials, decision-makers",
        "length": "~1500-2000 words",
    },
    "journalist": {
        "name": "Journalist's Take",
        "icon": "📰",
        "description": "News-style writeup with headlines and quotable findings",
        "audience": "General public, media",
        "length": "~1200-1500 words",
    },
    "deep_dive": {
        "name": "Deep Dive",
        "icon": "🔬",
        "description": "Comprehensive academic analysis for researchers",
        "audience": "Researchers, policy analysts, academics",
        "length": "~2500-3500 words",
    },
    "simple": {
        "name": "Simple Explainer",
        "icon": "💡",
        "description": "Plain language explanation for everyone",
        "audience": "General citizens, non-experts",
        "length": "~800-1200 words",
    },
    "policy": {
        "name": "Policy Brief",
        "icon": "🏛️",
        "description": "Actionable insights for government officials",
        "audience": "Ministry officials, compliance teams",
        "length": "~1500-2000 words",
    },
}

VARIANT_ORDER = ["executive", "journalist", "deep_dive", "simple", "policy"]


def get_summaries_path(report_id: str) -> Path:
    """
    Get path to summaries JSON file.

    Checks organized folder structure first, then falls back to flat structure.
    """
    # Check new organized path first: data/batch_jobs/summaries/{report_id}_summaries.json
    new_path = SUMMARIES_DIR / f"{report_id}_summaries.json"
    if new_path.exists():
        return new_path

    # Fallback to old flat structure: data/batch_jobs/{report_id}_summaries.json
    old_path = BATCH_JOBS_DIR / f"{report_id}_summaries.json"
    if old_path.exists():
        return old_path

    return new_path  # Return new path (will trigger 404 if not found)


def load_summaries(report_id: str) -> dict:
    """Load summaries data for a report."""
    summaries_path = get_summaries_path(report_id)

    if not summaries_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Summaries not found for report: {report_id}. Run Phase 10 batch processing first.",
        )

    with open(summaries_path, encoding="utf-8") as f:
        return json.load(f)


@router.get("/reports/{report_id}/summaries")
async def list_summaries(report_id: str):
    """
    List available summary variants for a report.

    Returns metadata for each variant including:
    - id: Variant identifier
    - name: Human-readable name
    - icon: Emoji icon
    - description: What this variant provides
    - audience: Target audience
    - available: Whether this variant was generated
    - word_count: Approximate word count
    """
    summaries = load_summaries(report_id)
    variants_data = summaries.get("variants", {})

    available_variants = []

    for variant_id in VARIANT_ORDER:
        info = VARIANT_INFO[variant_id].copy()
        variant_data = variants_data.get(variant_id)

        available_variants.append(
            {
                "id": variant_id,
                **info,
                "available": variant_data is not None,
                "word_count": variant_data.get("word_count", 0) if variant_data else 0,
            }
        )

    # Count errors if any
    errors = summaries.get("errors", [])

    return {
        "report_id": report_id,
        "generated_at": summaries.get("generated_at"),
        "total_variants": len(variants_data),
        "total_errors": len(errors) if errors else 0,
        "variants": available_variants,
    }


@router.get("/reports/{report_id}/summaries/random")
async def get_random_summary(report_id: str):
    """
    Get a random summary variant (Surprise Me feature).

    Randomly selects from available variants and returns the full summary.
    """
    summaries = load_summaries(report_id)
    variants_data = summaries.get("variants", {})

    # Get available variants
    available = [k for k, v in variants_data.items() if v is not None]

    if not available:
        raise HTTPException(
            status_code=404, detail="No summary variants available for this report"
        )

    # Pick random variant
    variant_id = random.choice(available)
    variant_data = variants_data[variant_id]
    info = VARIANT_INFO.get(variant_id, {})

    return {
        "report_id": report_id,
        "variant": variant_id,
        "name": info.get("name", variant_id),
        "icon": info.get("icon", "📄"),
        "description": info.get("description", ""),
        "audience": info.get("audience", ""),
        "content": variant_data.get("content", ""),
        "word_count": variant_data.get("word_count", 0),
        "thinking_used": variant_data.get("thinking_used", False),
        "generated_at": summaries.get("generated_at"),
        "is_random": True,
    }


@router.get("/reports/{report_id}/summaries/{variant}")
async def get_summary(report_id: str, variant: str):
    """
    Get a specific summary variant.

    Available variants:
    - executive: Executive Brief for decision-makers
    - journalist: News-style for general public
    - deep_dive: Academic analysis for researchers
    - simple: Plain language for everyone
    - policy: Action-oriented for government officials
    """
    # Validate variant
    if variant not in VARIANT_INFO:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid variant '{variant}'. Choose from: {list(VARIANT_INFO.keys())}",
        )

    summaries = load_summaries(report_id)
    variants_data = summaries.get("variants", {})

    variant_data = variants_data.get(variant)

    if not variant_data:
        # Check if any variants exist
        if variants_data:
            available = list(variants_data.keys())

            # Check if this variant had an error
            errors = summaries.get("errors", [])
            error_for_variant = next(
                (e for e in errors if e.get("variant") == variant), None
            )

            if error_for_variant:
                raise HTTPException(
                    status_code=500,
                    detail=f"Variant '{variant}' failed during generation: {error_for_variant.get('error', 'Unknown error')[:100]}",
                )

            raise HTTPException(
                status_code=404,
                detail=f"Variant '{variant}' not available. Available variants: {available}",
            )
        else:
            raise HTTPException(
                status_code=404, detail="No summaries generated for this report yet"
            )

    info = VARIANT_INFO[variant]

    return {
        "report_id": report_id,
        "variant": variant,
        "name": info.get("name", variant),
        "icon": info.get("icon", "📄"),
        "description": info.get("description", ""),
        "audience": info.get("audience", ""),
        "content": variant_data.get("content", ""),
        "word_count": variant_data.get("word_count", 0),
        "thinking_used": variant_data.get("thinking_used", False),
        "generated_at": summaries.get("generated_at"),
    }


@router.get("/reports/{report_id}/summaries/{variant}/metadata")
async def get_summary_metadata(report_id: str, variant: str):
    """
    Get metadata for a summary variant without the full content.

    Useful for displaying variant info before loading full content.
    """
    if variant not in VARIANT_INFO:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid variant '{variant}'. Choose from: {list(VARIANT_INFO.keys())}",
        )

    summaries = load_summaries(report_id)
    variants_data = summaries.get("variants", {})
    variant_data = variants_data.get(variant)

    info = VARIANT_INFO[variant]

    # Check for errors
    errors = summaries.get("errors", [])
    error_for_variant = next((e for e in errors if e.get("variant") == variant), None)

    return {
        "report_id": report_id,
        "variant": variant,
        "name": info.get("name", variant),
        "icon": info.get("icon", "📄"),
        "description": info.get("description", ""),
        "audience": info.get("audience", ""),
        "expected_length": info.get("length", ""),
        "available": variant_data is not None,
        "word_count": variant_data.get("word_count", 0) if variant_data else 0,
        "thinking_used": variant_data.get("thinking_used", False)
        if variant_data
        else False,
        "error": error_for_variant.get("error") if error_for_variant else None,
        "generated_at": summaries.get("generated_at"),
    }
