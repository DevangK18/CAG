# ============================================
# Stage 1: Build Frontend (Vite + React)
# ============================================
FROM node:20-alpine AS frontend-build

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./

# Configure npm for better timeout handling and install dependencies
RUN npm config set fetch-timeout 300000 && \
    npm config set fetch-retries 3 && \
    npm config set fetch-retry-mintimeout 20000 && \
    npm config set fetch-retry-maxtimeout 120000 && \
    npm ci

COPY frontend/ ./

# Build-time environment variables for Vite
# These get baked into the JS bundle during build
ARG VITE_PUBLIC_POSTHOG_KEY
ARG VITE_PUBLIC_POSTHOG_HOST=https://us.i.posthog.com
ARG VITE_ACCESS_CODE=cag-test-2025

# Create .env.production with all VITE_ vars needed at build time
# VITE_API_BASE_URL is empty so api.ts adds /api prefix for relative URLs
RUN echo "VITE_API_BASE_URL=" > .env.production && \
    echo "VITE_PUBLIC_POSTHOG_KEY=${VITE_PUBLIC_POSTHOG_KEY}" >> .env.production && \
    echo "VITE_PUBLIC_POSTHOG_HOST=${VITE_PUBLIC_POSTHOG_HOST}" >> .env.production && \
    echo "VITE_ACCESS_CODE=${VITE_ACCESS_CODE}" >> .env.production

RUN npm run build

# ============================================
# Stage 2: Python Backend (FastAPI)
# ============================================
FROM python:3.11-slim

WORKDIR /app

# Minimal system deps for runtime only
# (no tesseract, no poppler, no build tools for ML)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies (slim export — no parsing/ML deps)
COPY requirements.docker.txt ./
RUN pip install --no-cache-dir -r requirements.docker.txt

# Copy ONLY runtime source code
# Do NOT copy src/parsing_pipeline/ or src/batch_pipeline/
COPY src/api/ ./src/api/
COPY src/rag_pipeline/ ./src/rag_pipeline/
COPY src/core/ ./src/core/

# Copy built frontend from stage 1
COPY --from=frontend-build /app/frontend/dist ./static/

# Tell the app where static files live
ENV STATIC_DIR=/app/static

# Data directory is volume-mounted at runtime
ENV DATA_DIR=/app/data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
