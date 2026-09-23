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


_TRANSIENT_MARKERS = (
    "429", "500", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "DEADLINE_EXCEEDED", "Empty response",
)


def generate_with_retry(client=None, max_retries: int = 5, **kwargs):
    """
    client.models.generate_content with exponential backoff on transient errors.

    Agent Platform serves Gemini from shared capacity (Dynamic Shared Quota), so
    429 RESOURCE_EXHAUSTED can occur on paid projects when a model is busy; it is
    not a fixed quota and succeeds on retry. Empty responses are retried too.

    Args:
        client: genai.Client to use (default: shared Agent Platform client)
        max_retries: Retries after the first attempt (~5s, 10s, 20s, 40s, 80s)

    Returns:
        GenerateContentResponse with non-empty text

    Raises:
        The last error once retries are exhausted, or immediately if non-transient
    """
    import random
    import time

    client = client or get_gemini_client()
    for attempt in range(max_retries + 1):
        try:
            response = client.models.generate_content(**kwargs)
            if not response.text:
                finish_reason = (
                    response.candidates[0].finish_reason if response.candidates else None
                )
                if "MAX_TOKENS" in str(finish_reason):
                    # Deterministic: output budget spent (often on thinking), retrying won't help
                    raise ValueError("No text: max_output_tokens exhausted (finish_reason=MAX_TOKENS)")
                raise ValueError(f"Empty response (finish_reason={finish_reason})")
            return response
        except Exception as e:
            transient = any(marker in str(e) for marker in _TRANSIENT_MARKERS)
            if not transient or attempt == max_retries:
                raise
            delay = 5 * 2 ** attempt * random.uniform(0.8, 1.2)
            logger.warning(f"Gemini call failed ({e}), retry {attempt + 1}/{max_retries} in {delay:.0f}s")
            time.sleep(delay)


def get_client_mode() -> Optional[str]:
    """Get the current client mode (always 'enterprise' once initialized)."""
    return _client_mode


def reset_client():
    """Reset the cached client (useful for testing)."""
    global _gemini_client, _client_mode
    _gemini_client = None
    _client_mode = None
