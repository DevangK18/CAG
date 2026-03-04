"""
Rate limiting configuration for CAG Interactive Gateway API.

Uses slowapi to prevent API abuse and control LLM costs.
Configured for deployment behind Caddy reverse proxy.
"""

import logging
import os

from fastapi import Request
from slowapi import Limiter

logger = logging.getLogger(__name__)


def get_real_ip(request: Request) -> str:
    """
    Extract real client IP from X-Forwarded-For header (set by Caddy).

    Security: This trusts X-Forwarded-For because:
    1. Caddy is controlled infrastructure (not public proxy)
    2. Caddy SETS (not appends) the header, preventing client spoofing
    3. No untrusted proxies exist between clients and Caddy

    Fallback: Uses direct connection IP if header missing (local dev).

    Args:
        request: FastAPI Request object

    Returns:
        Client IP address as string
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # X-Forwarded-For format: "client, proxy1, proxy2"
        # Take first IP (original client)
        client_ip = forwarded.split(",")[0].strip()
        return client_ip

    # Fallback for local development (no reverse proxy)
    return request.client.host if request.client else "127.0.0.1"


# Rate limit values from environment
# Format: "count/period" where period = second, minute, hour, day
# Examples: "5/minute", "30/hour", "1000/day"
RATE_LIMIT_CHAT = os.getenv("RATE_LIMIT_CHAT", "30/hour")

# Initialize limiter
# Uses in-memory storage for single-container deployments
# For multi-container: set REDIS_URL env var to enable Redis storage
limiter = Limiter(
    key_func=get_real_ip,
    default_limits=[],  # No global limits; apply per-endpoint
    headers_enabled=True,  # Expose X-RateLimit-* headers
)

logger.info(f"Rate limiter initialized: CHAT={RATE_LIMIT_CHAT}, backend=memory")
