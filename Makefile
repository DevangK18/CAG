# ============================================
# CAG Gateway - Makefile
# ============================================
# Usage: make [target]
# ============================================

.PHONY: help build rebuild up down logs restart deploy verify

# Load .env.production for all targets
ifneq (,$(wildcard .env.production))
    include .env.production
    export
endif

COMPOSE_FILE := docker-compose.prod.yml

help:
	@echo "CAG Gateway Commands:"
	@echo "  make build    - Build containers"
	@echo "  make rebuild  - Build without cache"
	@echo "  make up       - Start containers"
	@echo "  make down     - Stop containers"
	@echo "  make logs     - Follow app logs"
	@echo "  make deploy   - Full rebuild + start"
	@echo "  make verify   - Check VITE_ vars in bundle"

build:
	docker compose -f $(COMPOSE_FILE) build

rebuild:
	docker compose -f $(COMPOSE_FILE) build --no-cache

up:
	docker compose -f $(COMPOSE_FILE) up -d
	docker compose -f $(COMPOSE_FILE) ps

down:
	docker compose -f $(COMPOSE_FILE) down

logs:
	docker compose -f $(COMPOSE_FILE) logs -f app

restart:
	docker compose -f $(COMPOSE_FILE) restart

deploy: down rebuild up
	@echo "Deployment complete!"

verify:
	@echo "Checking VITE_ variables in bundle..."
	@docker exec cag-app sh -c 'grep -l "phc_" /app/static/assets/*.js && echo "PostHog: OK" || echo "PostHog: NOT FOUND"'
	@docker exec cag-app sh -c 'grep -l "cag-sister" /app/static/assets/*.js && echo "Access codes: OK" || echo "Access codes: Only default"'
