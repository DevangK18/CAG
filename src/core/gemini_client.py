"""
Shared Gemini Client Initialization
====================================

Centralized client initialization for Google Gemini Enterprise Agent Platform.
All modules should use get_gemini_client() to ensure consistent configuration.

Configuration:
- Uses vertexai=True for Gemini Enterprise Agent Platform (GCP project billing)
- Uses location="global" as required by Enterprise API
- Authenticates with ADC (service account on GCE/Cloud Run, gcloud locally)
- No API key fallback: AI Studio keys bill separately and hit free-tier limits
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Global client cache
_gemini_client = None
_client_mode: Optional[str] = None


def get_gemini_client(force_new: bool = False):
    """
    Get or create a Gemini client on GCP Agent Platform (bills to the GCP project).

    Project is taken from GOOGLE_CLOUD_PROJECT, else from ADC.

    Args:
        force_new: Force creation of new client (don't use cache)

    Returns:
        Configured genai.Client instance

    Raises:
        ValueError: If no GCP project can be determined
        google.auth.exceptions.DefaultCredentialsError: If ADC is not configured
        ImportError: If google-genai package is not installed
    """
    global _gemini_client, _client_mode

    if _gemini_client is not None and not force_new:
        return _gemini_client

    try:
        from google import genai
        import google.auth
    except ImportError:
        raise ImportError("google-genai package required. Install: pip install google-genai")

    credentials, auth_project = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    project = os.getenv("GOOGLE_CLOUD_PROJECT") or auth_project
    if not project:
        raise ValueError(
            "No GCP project found. Set GOOGLE_CLOUD_PROJECT or configure ADC "
            "(gcloud auth application-default login)."
        )

    # Use vertexai=True with location="global" (google-genai 1.x has no `enterprise` kwarg; it is the 2.x alias)
    _gemini_client = genai.Client(
        vertexai=True,
        project=project,
        location="global",
        credentials=credentials,
    )
    _client_mode = "enterprise"
    logger.info(f"Gemini client initialized with Enterprise (project={project})")
    return _gemini_client


def get_client_mode() -> Optional[str]:
    """Get the current client mode (always 'enterprise' once initialized)."""
    return _client_mode


def reset_client():
    """Reset the cached client (useful for testing)."""
    global _gemini_client, _client_mode
    _gemini_client = None
    _client_mode = None
