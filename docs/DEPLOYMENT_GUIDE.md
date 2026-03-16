# CAG-GATEWAY: Deployment Guide

## Hetzner Plan

**You were looking at Hetzner Webhosting (shared PHP hosting). That's the wrong product.**

You need **Hetzner Cloud** — a VPS where you get a full Linux server with Docker.

Go to: https://console.hetzner.cloud

**Plan: CX22** — €3.79/month
- 2 vCPU (shared Intel), 4 GB RAM, 40 GB NVMe SSD
- 20 TB traffic/month
- More than enough: your app is I/O-bound (waiting on LLM APIs), not CPU-bound

CX22 is fine because your heavy compute (LLM inference, embeddings, reranking) happens on external APIs. The VPS just runs FastAPI + serves static files.

---

## Architecture

```
User → http://VPS_IP → Caddy (:80) → FastAPI (:8000)
                                        ├── /api/*    → API routes
                                        ├── /health   → healthcheck
                                        └── /*        → React SPA (static files)
```

Single container: FastAPI serves both the API and the built frontend.
Caddy handles reverse proxy, gzip, security headers, and later HTTPS.
Data (JSONs) is volume-mounted, not baked into the image.

---

## File Placement

Drop these files into your repo root (on `develop` branch):

```
CAG/
├── Dockerfile                    ← REPLACE (new)
├── docker-compose.prod.yml       ← REPLACE (new)
├── Caddyfile                     ← REPLACE (new)
├── .env.production.template      ← REPLACE (new, committed)
├── .dockerignore                 ← REPLACE (new, committed)
├── requirements.docker.txt       ← KEEP (already generated)
├── .env.production               ← CREATE on VPS only (gitignored)
├── src/api/                      ← existing (code changes below)
├── src/rag_pipeline/             ← existing
├── src/core/                     ← existing
├── frontend/                     ← existing (code changes below)
└── data/                         ← NOT in git, uploaded to VPS separately
```

---

## Phase 1: Code Changes (Local, on `develop`)

These are the changes to your actual source code that make it production-ready.
All changes are backwards-compatible — local dev is unaffected.

### 1A. Backend: Static File Serving

**Claude Code prompt (Sonnet):**

```
Read @src/api/main.py

At the BOTTOM of the file, AFTER all router includes (app.include_router(...)),
add static file serving for the production frontend build.

Add these imports at the top if not already present:
- import os
- from fastapi.staticfiles import StaticFiles

Add this block at the very end of the file (MUST be after all route registrations):

```python
# Serve frontend static files in production (must be LAST — catch-all)
static_dir = os.environ.get("STATIC_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "static"))
if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
```

This only activates when the static/ directory exists (i.e., inside Docker).
Locally, the directory doesn't exist, so nothing changes.
The html=True enables SPA fallback (returns index.html for client-side routes).

DO NOT move any existing route registrations. The mount must come LAST because
it's a catch-all that would swallow /api/* and /health if placed first.
```

### 1B. Backend: Startup Logging

**Claude Code prompt (Sonnet):**

```
Read @src/api/main.py and find the lifespan/startup function.

Add a logging block at startup that prints the active configuration.
This helps verify which LLM provider is active when the container starts.

After the existing initialization calls, add:

```python
import logging
logger = logging.getLogger(__name__)

# In the startup/lifespan function, after existing init:
logger.info(f"[CONFIG] Environment: {os.environ.get('ENVIRONMENT', 'development')}")
logger.info(f"[CONFIG] Data dir: {os.environ.get('DATA_DIR', './data')}")
logger.info(f"[CONFIG] Static dir: {os.environ.get('STATIC_DIR', 'not set')}")
```

If the LLM provider config is accessible at startup, also log:
```python
logger.info(f"[CONFIG] LLM Provider: {config.llm.provider}/{config.llm.model}")
```

Keep it simple — just enough to verify config on `docker logs`.
```

### 1C. Backend: Health Endpoint Verification

**Claude Code prompt (Sonnet):**

```
Read @src/api/routes/health.py

The /health endpoint must return HTTP 200 WITHOUT depending on Qdrant or any
external service. Docker uses this for healthchecks — if it fails because Qdrant
is cold-starting, Docker will restart the container in a loop.

If the health endpoint currently calls Qdrant or any external service:
1. Keep the simple /health returning {"status": "ok"} unconditionally
2. Move any detailed checks (Qdrant connectivity, report counts) to
   a SEPARATE /health/detailed endpoint

If /health already returns a simple 200 without external dependencies, leave it alone.

DO NOT break the existing response schema — just ensure it doesn't
depend on external services for the basic /health check.
```

### 1D. Backend: Data Directory Paths

**Claude Code prompt (Sonnet):**

```
Search the codebase for hardcoded data directory paths:

grep -rn "data/processed\|data/batch_jobs\|data/extraction_images\|data/raw" \
  src/api/ src/rag_pipeline/ src/core/ --include="*.py"

Also check:
grep -rn "DATA_DIR\|PROCESSED_DIR\|data_dir\|processed_dir" \
  src/api/ src/core/ --include="*.py"

Report what you find. I need to know:
1. Is DATA_DIR already configurable via env var in src/api/config.py or src/core/config.py?
2. Are there any hardcoded absolute paths like "/Users/dev/..." ?
3. Do the paths use relative references (like "data/processed") that will resolve
   correctly when the working directory is /app inside Docker?

If DATA_DIR is already in config and paths are relative, no changes needed.
If there are hardcoded paths, make them relative to DATA_DIR.
```

### 1E. Frontend: API Base URL

**Claude Code prompt (Sonnet):**

```
Search the frontend codebase for API URL construction:

grep -rn "localhost:8000\|API_BASE\|VITE_API\|baseURL\|base_url" \
  frontend/src/ frontend/lib/ --include="*.ts" --include="*.tsx"

Also specifically check these files:
- frontend/lib/api.ts (or wherever the API client is defined)
- frontend/hooks/useChatStream.ts (SSE streaming URL)
- frontend/hooks/useSeriesChat.ts (series chat streaming URL)

For each file that constructs API URLs, ensure it uses:
```ts
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';
```

IMPORTANT: Use ?? (nullish coalescing), NOT || (logical OR).
In production, VITE_API_BASE_URL is set to "" (empty string).
|| would treat "" as falsy and fall back to localhost.
?? only falls back on null/undefined, so "" works correctly.

Check streaming endpoints carefully — SSE/EventSource connections often
construct URLs independently from the main API client.

If the pattern is already correct, leave it alone.
```

### 1F. Frontend: Vite Config Check

**Claude Code prompt (Sonnet):**

```
Read @frontend/vite.config.ts

Verify:
1. There is NO `base` property set (default "/" is correct), OR it's set to "/"
2. The dev server proxy (if any) points to localhost:8000

If base is set to something other than "/", change it to "/" —
any other value will break routing behind Caddy.

No other changes needed.
```

---

## Phase 2: Local Docker Test

After all Phase 1 changes, test locally before touching the VPS.

```bash
# 1. Build the image
docker compose -f docker-compose.prod.yml build

# 2. Create a local .env.production with your real API keys
cp .env.production.template .env.production
# Edit with your actual keys

# 3. Run it
docker compose -f docker-compose.prod.yml up

# 4. Test in browser:
#    http://localhost         → React frontend (via Caddy)
#    http://localhost/health  → {"status": "ok"}
#    http://localhost/api/reports → JSON report list

# 5. Test streaming:
#    Open the chat UI and send a message
#    Verify SSE streaming works through Caddy

# 6. Check image size
docker images | grep cag
# Should be ~400-700MB, not 3-4GB

# 7. If anything fails, check logs:
docker compose -f docker-compose.prod.yml logs app
docker compose -f docker-compose.prod.yml logs caddy
```

**Common issues at this stage:**
- `ModuleNotFoundError` → A dependency is missing from requirements.docker.txt.
  Add it to the main group in pyproject.toml, re-export, rebuild.
- Frontend shows blank page → Check browser console. Likely a VITE_API_BASE_URL issue.
- Streaming doesn't work → Caddy's `flush_interval -1` is missing (included in new Caddyfile).
- Health check fails → The endpoint depends on Qdrant (fix per 1C).
- Can't find data files → DATA_DIR env var or volume mount path mismatch.

---

## Phase 3: VPS Setup (One-Time)

### 3A. Provision the Server

1. Go to https://console.hetzner.cloud
2. Create a new project → "CAG-Gateway"
3. Add your SSH public key (Settings → SSH Keys)
4. Create a server:
   - **Location**: Nuremberg (nbg1) or Helsinki (hel1)
   - **Image**: Ubuntu 24.04
   - **Type**: Shared vCPU → CX22
   - **SSH Key**: Select the one you added
   - **Name**: cag-gateway
5. Note the IP address

### 3B. Initial Server Setup

```bash
# SSH in
ssh root@YOUR_VPS_IP

# Update system
apt update && apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sh

# Verify
docker --version
docker compose version

# Firewall
ufw allow 22    # SSH
ufw allow 80    # HTTP
ufw allow 443   # HTTPS (for later)
ufw --force enable

# Create app directory
mkdir -p /opt/cag-gateway
```

### 3C. Deploy

```bash
# From your LOCAL machine:

# Clone repo to VPS (or set up deploy key for private repos)
ssh root@YOUR_VPS_IP "cd /opt && git clone https://github.com/YOUR_USER/CAG.git cag-gateway"

# Upload data (NOT in git)
scp -r ./data root@YOUR_VPS_IP:/opt/cag-gateway/

# SSH in and configure
ssh root@YOUR_VPS_IP
cd /opt/cag-gateway

# Create production env file
cp .env.production.template .env.production
nano .env.production
# Fill in all API keys

# Build and start
docker compose -f docker-compose.prod.yml up -d --build

# Verify
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f app
```

### 3D. Verify

From your browser:
- `http://YOUR_VPS_IP` → React frontend
- `http://YOUR_VPS_IP/health` → `{"status": "ok"}`
- `http://YOUR_VPS_IP/api/reports` → JSON list
- Open chat, send a question → Verify streaming works

---

## Phase 4: Qdrant Setup

### Option A: Qdrant Cloud (recommended for MVP)

1. Sign up at https://cloud.qdrant.io
2. Create a free cluster (1GB — enough for 14+ reports)
3. Copy URL and API key into `.env.production` on the VPS
4. Run your indexer once, pointing at the cloud URL:
   ```bash
   # From your LOCAL machine (where parsing deps are installed):
   QDRANT_URL=https://your-cluster.cloud.qdrant.io \
   QDRANT_API_KEY=your-key \
   python -m src.rag_pipeline.indexer --all
   ```

### Option B: Self-hosted on VPS

1. Uncomment the `qdrant` service in `docker-compose.prod.yml`
2. Set `QDRANT_URL=http://qdrant:6333` in `.env.production`
3. `docker compose -f docker-compose.prod.yml up -d --build`
4. Run indexer pointing at the VPS Qdrant

---

## Updating After Code Changes

```bash
# One-liner from local machine:
ssh root@YOUR_VPS_IP "cd /opt/cag-gateway && git pull && docker compose -f docker-compose.prod.yml up -d --build"
```

Or create `deploy.sh` at repo root (not committed):
```bash
#!/bin/bash
set -e
VPS_IP="YOUR_VPS_IP"
ssh root@$VPS_IP "cd /opt/cag-gateway && git pull && docker compose -f docker-compose.prod.yml up -d --build"
echo "Deployed. Check: http://$VPS_IP/health"
```

---

## Adding a Domain Later

1. Buy a domain (Cloudflare ~$10/year, or any registrar)
2. Add DNS A record: `yourdomain.com → YOUR_VPS_IP`
3. Edit `Caddyfile` on the VPS: change `:80` to `yourdomain.com`
4. Restart: `docker compose -f docker-compose.prod.yml restart caddy`
5. Caddy auto-provisions HTTPS via Let's Encrypt. Done.

---

## Monitoring

```bash
# View logs
docker compose -f docker-compose.prod.yml logs -f app      # API logs
docker compose -f docker-compose.prod.yml logs -f caddy     # Access logs

# Restart
docker compose -f docker-compose.prod.yml restart

# Rebuild after code changes
docker compose -f docker-compose.prod.yml up -d --build

# Disk usage
df -h
du -sh /opt/cag-gateway/data/

# Container resource usage
docker stats
```

---

## Checklist

```
LOCAL PREP:
[ ] Deployment files placed at repo root
[ ] Static file serving added to src/api/main.py (Phase 1A)
[ ] Startup logging added (Phase 1B)
[ ] /health endpoint is independent of external services (Phase 1C)
[ ] Data paths are relative or configurable (Phase 1D)
[ ] Frontend API base URL uses ?? not || (Phase 1E)
[ ] vite.config.ts has base: "/" (Phase 1F)
[ ] Local Docker test passes (Phase 2)
[ ] .env.production is in .gitignore
[ ] requirements.docker.txt is up to date
[ ] All changes committed to develop, squash-merged to main

VPS:
[ ] Hetzner Cloud CX22 provisioned
[ ] Docker installed
[ ] Firewall configured (22, 80, 443)
[ ] Repo cloned to /opt/cag-gateway
[ ] Data uploaded via scp
[ ] .env.production created with all keys
[ ] docker compose up -d --build succeeds
[ ] Frontend loads in browser
[ ] /health returns 200
[ ] /api/reports returns data
[ ] Chat streaming works
[ ] Qdrant connected (Cloud or self-hosted)
```
