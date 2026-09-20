"""
Configuration management with environment variables.

Supports both local development and Cloud Run deployment with GCS.
"""

from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import computed_field
from typing import List, Optional
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
    GOOGLE_API_KEY: str = ""

    # LLM Settings - Default to Gemini for GCP credit billing
    LLM_PROVIDER: str = "gemini"
    OPENAI_MODEL: str = "gpt-4o"
    CLAUDE_MODEL: str = "claude-sonnet-5"
    GEMINI_MODEL: str = "gemini-1.5-flash"  # Latest Gemini for GCP billing

    # GCS Storage Configuration (for Cloud Run deployment)
    DATA_BUCKET: str = ""  # GCS bucket name (e.g., "cag-data-project-id")
    DATA_DIR: str = ""  # Override data directory (set by Cloud Run/Docker)

    # Environment
    ENVIRONMENT: str = "development"

    @computed_field
    @property
    def is_cloud_run(self) -> bool:
        """Check if running on Cloud Run (GCS-backed storage)."""
        return bool(self.DATA_BUCKET)

    @computed_field
    @property
    def BASE_DIR(self) -> Path:
        """Base directory (CAG/)"""
        return _BASE_DIR

    @computed_field
    @property
    def _data_root(self) -> Path:
        """Root directory for data files.

        In Cloud Run: uses DATA_DIR env var (e.g., /app/data)
        In local dev: uses BASE_DIR/data
        """
        if self.DATA_DIR:
            return Path(self.DATA_DIR)
        return _BASE_DIR / "data"

    @computed_field
    @property
    def PDF_DIR(self) -> Path:
        """Directory containing PDF files"""
        return self._data_root / "raw"

    @computed_field
    @property
    def PROCESSED_DIR(self) -> Path:
        """Directory containing processed JSON files"""
        return self._data_root / "processed"

    @computed_field
    @property
    def MANIFEST_PATH(self) -> Path:
        """Path to manifest.json"""
        return self._data_root / "processed" / "manifest.json"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


# Create singleton instance
settings = Settings()
