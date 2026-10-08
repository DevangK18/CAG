"""
Gemini models for Phase 10, kept apart from src.core.config so the parsing
pipeline can read them without loading the RAG/API configuration (which
requires API-only settings such as ENTITY_GRAPH_DSN at import time).
"""

import os
from dataclasses import dataclass


@dataclass
class Phase10ModelConfig:
    """
    Gemini models for Phase 10: the one place to change them.

    Each can be overridden with PHASE10_MODEL_<ROLE>, e.g. PHASE10_MODEL_SIMPLE.
    Prices for every model used here must be in gemini_client.MODEL_PRICES_USD_PER_1M.
    """

    overview: str = "gemini-3.1-pro-preview"
    executive: str = "gemini-3.1-pro-preview"
    journalist: str = "gemini-3.1-pro-preview"
    deep_dive: str = "gemini-3.1-pro-preview"
    policy: str = "gemini-3.1-pro-preview"
    simple: str = "gemini-3.8-flash"
    # RAPTOR chapter and section summaries
    chapter_summary: str = "gemini-3.8-flash"
    section_summary: str = "gemini-3.8-flash"
    # Phase 10b chart and table extraction
    visual: str = "gemini-3.8-flash"

    def __post_init__(self):
        for role in self.__dataclass_fields__:
            override = os.getenv(f"PHASE10_MODEL_{role.upper()}")
            if override:
                setattr(self, role, override)


# Gemini thinking level per role; None leaves the model's default. Set from the
# PR 9 thinking comparison (a lower level is kept only where quality held).
# Override with PHASE10_THINKING_<ROLE>; "default" restores the model's default.
THINKING_LEVELS = {
    "chapter_summary": None,
    "section_summary": None,
    "visual": None,
}


def thinking_level(role: str):
    override = os.getenv(f"PHASE10_THINKING_{role.upper()}")
    if override:
        return None if override.lower() == "default" else override.lower()
    return THINKING_LEVELS.get(role)
