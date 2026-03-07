#!/bin/bash
# ============================================
# CAG Gateway Production Deployment Script
# ============================================
# Usage: ./scripts/deploy.sh [build|up|down|logs|rebuild]
#
# This script ensures VITE_* environment variables
# are properly passed to the Docker build process.
# ============================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
ENV_FILE=".env.production"
COMPOSE_FILE="docker-compose.prod.yml"

# Check if env file exists
if [ ! -f "$ENV_FILE" ]; then
    echo -e "${RED}Error: $ENV_FILE not found${NC}"
    echo "Copy .env.example to .env.production and fill in your values"
    exit 1
fi

# Source environment variables so they're available for docker-compose interpolation
echo -e "${YELLOW}Loading environment from $ENV_FILE...${NC}"
set -a
source "$ENV_FILE"
set +a

# Verify critical VITE_ variables are set
echo -e "${YELLOW}Checking VITE_ variables...${NC}"
if [ -z "$VITE_ACCESS_CODE" ]; then
    echo -e "${RED}Warning: VITE_ACCESS_CODE not set, will use default${NC}"
else
    echo -e "${GREEN}  VITE_ACCESS_CODE: ${VITE_ACCESS_CODE}${NC}"
fi

if [ -z "$VITE_PUBLIC_POSTHOG_KEY" ]; then
    echo -e "${RED}Warning: VITE_PUBLIC_POSTHOG_KEY not set, PostHog disabled${NC}"
else
    echo -e "${GREEN}  VITE_PUBLIC_POSTHOG_KEY: ${VITE_PUBLIC_POSTHOG_KEY:0:20}...${NC}"
fi

# Command handling
case "${1:-up}" in
    build)
        echo -e "${YELLOW}Building containers...${NC}"
        docker compose -f "$COMPOSE_FILE" build
        echo -e "${GREEN}Build complete!${NC}"
        ;;

    rebuild)
        echo -e "${YELLOW}Rebuilding containers (no cache)...${NC}"
        docker compose -f "$COMPOSE_FILE" build --no-cache
        echo -e "${GREEN}Rebuild complete!${NC}"
        ;;

    up)
        echo -e "${YELLOW}Starting containers...${NC}"
        docker compose -f "$COMPOSE_FILE" up -d
        echo -e "${GREEN}Containers started!${NC}"
        docker compose -f "$COMPOSE_FILE" ps
        ;;

    down)
        echo -e "${YELLOW}Stopping containers...${NC}"
        docker compose -f "$COMPOSE_FILE" down
        echo -e "${GREEN}Containers stopped!${NC}"
        ;;

    logs)
        docker compose -f "$COMPOSE_FILE" logs -f "${2:-app}"
        ;;

    restart)
        echo -e "${YELLOW}Restarting containers...${NC}"
        docker compose -f "$COMPOSE_FILE" restart
        echo -e "${GREEN}Containers restarted!${NC}"
        ;;

    deploy)
        echo -e "${YELLOW}Full deployment: rebuild + restart...${NC}"
        docker compose -f "$COMPOSE_FILE" down
        docker compose -f "$COMPOSE_FILE" build --no-cache
        docker compose -f "$COMPOSE_FILE" up -d
        echo -e "${GREEN}Deployment complete!${NC}"
        docker compose -f "$COMPOSE_FILE" ps
        ;;

    verify)
        echo -e "${YELLOW}Verifying VITE_ variables in built bundle...${NC}"
        # Check if access codes are in the bundle
        if docker exec cag-app grep -q "cag-sister" /app/static/assets/*.js 2>/dev/null; then
            echo -e "${GREEN}  Access codes: Found in bundle${NC}"
        else
            echo -e "${RED}  Access codes: NOT found (only default 'cag-test-2025')${NC}"
        fi
        # Check if PostHog key is in the bundle
        if docker exec cag-app grep -q "phc_" /app/static/assets/*.js 2>/dev/null; then
            echo -e "${GREEN}  PostHog key: Found in bundle${NC}"
        else
            echo -e "${RED}  PostHog key: NOT found${NC}"
        fi
        ;;

    *)
        echo "Usage: $0 [build|rebuild|up|down|logs|restart|deploy|verify]"
        echo ""
        echo "Commands:"
        echo "  build    - Build containers"
        echo "  rebuild  - Build containers without cache"
        echo "  up       - Start containers"
        echo "  down     - Stop containers"
        echo "  logs     - Follow logs (default: app, or specify service)"
        echo "  restart  - Restart containers"
        echo "  deploy   - Full rebuild and restart"
        echo "  verify   - Check if VITE_ vars are in the bundle"
        exit 1
        ;;
esac
