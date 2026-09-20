# pai-stack Makefile
# Intelligent local development environment for AI agents (Hermes + Graft + LiteLLM)
# with native file-based Research Brain.

.DEFAULT_GOAL := help

.PHONY: help setup check-workspace \
	up down restart logs status build clean config sync sync-all sync-models

WORKSPACE_DIR ?= $(shell grep -E '^WORKSPACE_DIR=' .env 2>/dev/null | cut -d= -f2- | tr -d '\"' | tr -d "'")

COMPOSE := docker compose -f docker-compose.yaml

# ── Help ──────────────────────────────────────────────────────────────────────

help:  ## Show this help message
	@echo "\033[1mpai-stack\033[0m — AI Agent Development Environment"
	@echo ""
	@echo "\033[1;34mCore Commands:\033[0m"
	@printf "  \033[36m%-16s\033[0m %s\n" "setup" "Initialize .env and default workspace folder"
	@printf "  \033[36m%-16s\033[0m %s\n" "up" "Start stack in background (hermes, graft, mcp, llm-gateway)"
	@printf "  \033[36m%-16s\033[0m %s\n" "down" "Stop all services"
	@printf "  \033[36m%-16s\033[0m %s\n" "restart" "Restart services (optional: s=<service>)"
	@printf "  \033[36m%-16s\033[0m %s\n" "status" "Show running containers, ports, and health"
	@printf "  \033[36m%-16s\033[0m %s\n" "logs" "Tail container logs (optional: s=<service>)"
	@printf "  \033[36m%-16s\033[0m %s\n" "sync" "Sync LLM models with upstream providers (auto-reloads gateway)"
	@printf "  \033[36m%-16s\033[0m %s\n" "sync-all" "Sync models and include all cloud provider templates"
	@echo ""
	@echo "\033[1;34mMaintenance:\033[0m"
	@printf "  \033[36m%-16s\033[0m %s\n" "build" "Build container images (optional: s=<service>)"
	@printf "  \033[36m%-16s\033[0m %s\n" "clean" "Stop containers and remove volumes (destroys hermes & graft state)"
	@printf "  \033[36m%-16s\033[0m %s\n" "config" "Validate and view resolved compose configuration"
	@echo ""

# ── Onboarding & Workspace Verification ───────────────────────────────────────

setup:  ## Initialize .env from .env.example and create default workspace directory
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "\033[32m[✓]\033[0m Created .env from .env.example"; \
	else \
		echo "\033[36m[ℹ]\033[0m .env already exists"; \
	fi
	@mkdir -p ./workspace
	@echo "\033[32m[✓]\033[0m Setup complete. Edit .env or run 'make up' to start."

check-workspace:
	@if [ ! -f .env ]; then \
		echo "\033[33m[!] .env not found, auto-initializing from .env.example...\033[0m"; \
		cp .env.example .env; \
	fi
	@WS=$$(grep -E '^WORKSPACE_DIR=' .env 2>/dev/null | cut -d= -f2- | tr -d '\"' | tr -d "'"); \
	if [ -z "$$WS" ]; then \
		WS="./workspace"; \
	fi; \
	if [ ! -d "$$WS" ]; then \
		echo "\033[36m[ℹ] Creating workspace directory at '$$WS'...\033[0m"; \
		mkdir -p "$$WS" 2>/dev/null || { \
			echo "\033[31m[ERROR]\033[0m Could not create WORKSPACE_DIR '$$WS'. Please create it manually."; \
			exit 1; \
		}; \
	fi

# ── Service Management ────────────────────────────────────────────────────────

up: check-workspace  ## Start services in background (supports s=<service>)
	$(COMPOSE) up -d $(s)

down:  ## Stop services
	$(COMPOSE) down --remove-orphans

restart:  ## Restart services (optional: s=<service>)
	$(COMPOSE) restart $(s)

logs:  ## Tail logs for services (optional: s=<service>)
	$(COMPOSE) logs -f $(s)

status:  ## Show running containers and health status (optional: s=<service>)
	$(COMPOSE) ps $(s)

build:  ## Build container images (optional: s=<service>)
	$(COMPOSE) build $(s)

clean:  ## Stop containers and remove persisted volumes (destroys hermes & graft state)
	$(COMPOSE) down -v --remove-orphans

config:  ## Validate and view compose config
	$(COMPOSE) config

# ── Model Synchronization ─────────────────────────────────────────────────────

sync:  ## Sync LLM models with upstream providers and auto-reload gateway
	python3 scripts/sync-models.py

sync-all:  ## Sync LLM models and include all cloud provider templates
	python3 scripts/sync-models.py --all

sync-models: sync  ## Alias for 'make sync'
