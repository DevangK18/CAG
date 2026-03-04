"""
API Routes package.

Contains all route modules:
- health: Health check endpoint
- reports: Report listing and details
- chat: Chat endpoints (sync and streaming)
- assets: Charts and tables extraction
- series: Time series analysis
- overview: Report overview with LLM-extracted fields (Phase 10)
- summaries: AI-generated summary variants (Phase 10)
"""

from . import health
from . import reports
from . import chat
from . import assets
from . import series
from . import overview
from . import summaries

__all__ = ["health", "reports", "chat", "assets", "series", "overview", "summaries"]
