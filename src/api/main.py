"""
CAG Interactive Gateway - FastAPI Backend
==========================================

Main application entry point.
Provides REST API and SSE streaming for the CAG RAG system.

Usage:
    uvicorn services.api.main:app --reload --port 8000

Or run directly:
    python -m services.api.main
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import logging
import os
import sys
from pathlib import Path

from slowapi.errors import RateLimitExceeded

from .config import settings
from .routes import health, reports, chat, assets, series, overview, summaries
from .services.streaming_wrapper import initialize_rag_service
from .services.report_service import initialize as initialize_reports
from .rate_limit import limiter, get_real_ip

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def initialize_report_registry():
    """Initialize the report registry for time series support."""
    try:
        # Calculate path to rag_pipeline (inside services/, not at project root)
        # This file is at: services/api/main.py
        # rag_pipeline is at: services/rag_pipeline/
        THIS_FILE = Path(__file__).resolve()
        API_DIR = THIS_FILE.parent  # services/api/
        SERVICES_DIR = API_DIR.parent  # services/
        RAG_PIPELINE_DIR = SERVICES_DIR / "rag_pipeline"  # services/rag_pipeline/

        if RAG_PIPELINE_DIR.exists():
            if str(RAG_PIPELINE_DIR) not in sys.path:
                sys.path.insert(0, str(RAG_PIPELINE_DIR))

            from report_registry import init_registry

            registry = init_registry(settings.PROCESSED_DIR)
            stats = registry.get_stats()
            logger.info(
                f"Report registry: {stats['total_reports']} reports, {stats['total_series']} series"
            )
            for sid, info in stats.get("series", {}).items():
                logger.info(
                    f"  - {sid}: {info['report_count']} reports {info['years']}"
                )
        else:
            logger.warning(f"rag_pipeline not found at {RAG_PIPELINE_DIR}")

    except Exception as e:
        logger.warning(f"Report registry init failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Initialize services on startup, cleanup on shutdown.
    """
    # Startup
    logger.info("=" * 60)
    logger.info("CAG Interactive Gateway API Starting...")
    logger.info("=" * 60)

    logger.info(f"Base directory: {settings.BASE_DIR}")
    logger.info(f"PDF directory: {settings.PDF_DIR}")
    logger.info(f"Processed directory: {settings.PROCESSED_DIR}")

    # Initialize report metadata
    logger.info("Loading report metadata...")
    initialize_reports()

    # Initialize report registry for time series
    logger.info("Initializing report registry...")
    initialize_report_registry()

    # Initialize RAG service
    logger.info("Initializing RAG service...")
    initialize_rag_service()

    # Log environment configuration
    logger.info("-" * 60)
    logger.info("[CONFIG] Environment: %s", os.environ.get("ENVIRONMENT", "development"))
    logger.info("[CONFIG] Data dir: %s", os.environ.get("DATA_DIR", "./data"))
    logger.info("[CONFIG] Static dir: %s", os.environ.get("STATIC_DIR", "not set"))
    logger.info("-" * 60)

    # Log active configuration
    from .services.streaming_wrapper import get_rag_service
    rag = get_rag_service()
    if rag:
        provider = rag.config.llm.provider.value
        if provider == "claude":
            model = rag.config.llm.claude_model
        elif provider == "gemini":
            model = rag.config.llm.gemini_model
        else:
            model = rag.config.llm.openai_model

        logger.info("-" * 60)
        logger.info("[CONFIG] Generation: %s/%s", provider, model)
        logger.info("[CONFIG] Embeddings: openai/%s (fixed)", rag.config.embedding.model)
        logger.info("[CONFIG] Reranking: %s/%s",
                    rag.config.retrieval.reranker_type.value,
                    rag.config.retrieval.cohere_model if rag.config.retrieval.reranker_type.value == "cohere" else "N/A")
        logger.info("-" * 60)

    logger.info("=" * 60)
    logger.info("API Ready! Endpoints available at http://localhost:8000")
    logger.info("=" * 60)
    logger.info("Endpoints:")
    logger.info("  - GET  /health                      - Health check")
    logger.info("  - GET  /api/reports                 - List all reports")
    logger.info("  - GET  /api/reports/{id}            - Get report details")
    logger.info("  - GET  /api/reports/{id}/charts     - Get charts from report")
    logger.info("  - GET  /api/reports/{id}/tables     - Get tables from report")
    logger.info("  - GET  /api/series                  - List time series")
    logger.info("  - GET  /api/series/{id}             - Get series details")
    logger.info("  - POST /api/series/{id}/query       - Query across series")
    logger.info("  - POST /api/chat                    - Synchronous chat")
    logger.info("  - POST /api/chat/stream             - Streaming chat (SSE)")
    logger.info("  - GET  /api/files/{name}            - Serve PDF files")
    logger.info("=" * 60)

    yield

    # Shutdown
    logger.info("Shutting down CAG Interactive Gateway...")


# Create FastAPI app
app = FastAPI(
    title="CAG Interactive Gateway API",
    description="""
API for querying CAG (Comptroller and Auditor General) audit reports.

## Features

- **Report Browsing**: List and view details of indexed audit reports
- **Charts & Tables**: Extract and navigate to charts and tables in reports
- **Time Series**: Analyze trends across multiple years of reports
- **AI-Powered Q&A**: Ask questions and get cited answers from reports
- **Streaming Responses**: Real-time token streaming with citation metadata

## Key Endpoints

### Reports
- `GET /reports` - List all available reports
- `GET /reports/{id}` - Get report details
- `GET /reports/{id}/charts` - Get charts/figures
- `GET /reports/{id}/tables` - Get tables

### Time Series
- `GET /series` - List all time series
- `GET /series/{id}` - Get series details  
- `POST /series/{id}/query` - Query across series

### Chat
- `POST /chat` - Ask a question (synchronous)
- `POST /chat/stream` - Ask a question (streaming SSE)

### Files
- `GET /api/files/{filename}` - Serve PDF files
    """,
    version="2.2.0",
    lifespan=lifespan,
)

# CORS - Allow frontend origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Attach rate limiter to app
app.state.limiter = limiter


# Custom rate limit exception handler
@app.exception_handler(RateLimitExceeded)
async def custom_rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """
    Custom handler for rate limit exceeded (429) responses.

    Logs the violation and returns a user-friendly JSON response.
    """
    client_ip = get_real_ip(request)
    logger.warning(
        f"[RATE_LIMIT] Exceeded: {client_ip} | "
        f"Endpoint: {request.url.path} | "
        f"Method: {request.method}"
    )

    return JSONResponse(
        status_code=429,
        content={
            "error": "Rate limit exceeded",
            "message": "You have made too many requests. Please wait before trying again.",
            "detail": "This endpoint is rate-limited to prevent abuse and manage API costs.",
        },
        headers=getattr(exc, "headers", {}),
    )


# Static file serving for PDFs (under /api/files to match frontend expectations)
if settings.PDF_DIR and settings.PDF_DIR.exists():
    app.mount("/api/files", StaticFiles(directory=str(settings.PDF_DIR)), name="files")
    logger.info(f"Mounted PDF directory at /api/files: {settings.PDF_DIR}")
else:
    logger.warning(f"PDF directory not found: {settings.PDF_DIR}")

# Include routers
# Health stays at root level for Docker healthcheck
app.include_router(health.router, tags=["Health"])
# All other routes under /api prefix
app.include_router(reports.router, prefix="/api/reports", tags=["Reports"])
app.include_router(assets.router, prefix="/api/reports", tags=["Charts & Tables"])
app.include_router(series.router, prefix="/api/series", tags=["Time Series"])
app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
app.include_router(overview.router, prefix="/api")
app.include_router(summaries.router, prefix="/api")


# Root endpoint - only in non-production (so "/" falls through to static mount in production)
if os.environ.get("ENVIRONMENT") != "production":
    @app.get("/", tags=["Root"])
    async def root():
        """Root endpoint with API information."""
        return {
            "name": "CAG Interactive Gateway API",
            "version": "2.2.0",
            "docs": "/docs",
            "health": "/health",
            "features": [
                "Report browsing and details",
                "Charts and tables extraction",
                "Time series analysis",
                "AI-powered Q&A with citations",
                "Streaming responses (SSE)",
            ],
        }


# Serve frontend static files in production (must be LAST — catch-all)
static_dir = os.environ.get("STATIC_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "static"))
if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("services.api.main:app", host="0.0.0.0", port=8000, reload=True)
