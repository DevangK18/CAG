"""
Shared Gemini Client Initialization
====================================

Centralized client initialization for Google Gemini Enterprise Agent Platform.
All modules should use get_gemini_client() to ensure consistent configuration.

Configuration:
- Uses vertexai=True for Gemini Enterprise Agent Platform (GCP billing)
- Uses location="global" as required by Enterprise API
- Falls back to API key if GCP project not configured
"""

import logging
import os
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Global client cache
_gemini_client = None
_client_mode: Optional[str] = None


def get_gemini_client(force_new: bool = False):
    """
    Get or create a Gemini client configured for Enterprise Agent Platform.

    Priority:
    1. Gemini Enterprise (vertexai=True) with GCP project - bills to GCP
    2. API key fallback - bills to API key account

    Args:
        force_new: Force creation of new client (don't use cache)

    Returns:
        Configured genai.Client instance

    Raises:
        ValueError: If no credentials are available
        ImportError: If google-genai package is not installed
    """
    global _gemini_client, _client_mode

    if _gemini_client is not None and not force_new:
        return _gemini_client

    try:
        from google import genai

        project = os.getenv("GOOGLE_CLOUD_PROJECT")
        api_key = os.getenv("GOOGLE_API_KEY")

        # Try Gemini Enterprise first (GCP project billing)
        if project:
            try:
                import google.auth
                credentials, auth_project = google.auth.default(
                    scopes=["https://www.googleapis.com/auth/cloud-platform"]
                )
                project = project or auth_project

                # Use vertexai=True with location="global" (google-genai 1.x has no `enterprise` kwarg; it is the 2.x alias)
                # This is the correct configuration as of 2025 (formerly Vertex AI)
                _gemini_client = genai.Client(
                    vertexai=True,
                    project=project,
                    location="global",
                    credentials=credentials
                )
                _client_mode = "enterprise"
                logger.info(f"Gemini client initialized with Enterprise (project={project})")
                return _gemini_client

            except Exception as e:
                logger.warning(f"Enterprise init failed: {e}, trying API key fallback...")
                if api_key:
                    _gemini_client = genai.Client(api_key=api_key)
                    _client_mode = "api_key"
                    logger.info("Gemini client initialized with API key (fallback)")
                    return _gemini_client
                else:
                    raise

        # API key mode
        elif api_key:
            _gemini_client = genai.Client(api_key=api_key)
            _client_mode = "api_key"
            logger.info("Gemini client initialized with API key")
            return _gemini_client

        else:
            raise ValueError(
                "No Gemini credentials found. Set GOOGLE_CLOUD_PROJECT for Enterprise "
                "or GOOGLE_API_KEY for direct API access."
            )

    except ImportError:
        raise ImportError("google-genai package required. Install: pip install google-genai")


def get_client_mode() -> Optional[str]:
    """Get the current client mode ('enterprise' or 'api_key')."""
    return _client_mode


def reset_client():
    """Reset the cached client (useful for testing)."""
    global _gemini_client, _client_mode
    _gemini_client = None
    _client_mode = None
