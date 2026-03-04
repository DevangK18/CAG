"""
Configuration management with environment variables.
"""

from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import computed_field
from typing import List
import os


# Compute base directory at module level
_BASE_DIR = Path(__file__).resolve().parent.parent.parent  # CAG/


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    # CORS
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
    ]

    # API Keys (loaded from environment)
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    COHERE_API_KEY: str = ""

    # LLM Settings
    LLM_PROVIDER: str = "openai"
    OPENAI_MODEL: str = "gpt-4o"
    CLAUDE_MODEL: str = "claude-sonnet-4-20250514"

    @computed_field
    @property
    def BASE_DIR(self) -> Path:
        """Base directory (CAG/)"""
        return _BASE_DIR

    @computed_field
    @property
    def PDF_DIR(self) -> Path:
        """Directory containing PDF files"""
        return _BASE_DIR / "data" / "raw"

    @computed_field
    @property
    def PROCESSED_DIR(self) -> Path:
        """Directory containing processed JSON files"""
        return _BASE_DIR / "data" / "processed"

    @computed_field
    @property
    def MANIFEST_PATH(self) -> Path:
        """Path to manifest.json"""
        return _BASE_DIR / "data" / "processed" / "manifest.json"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


# Create singleton instance
settings = Settings()
