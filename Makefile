# pai-stack — AI agent dev environment (Hermes + LLM Gateway)
# Full reference: docs/operations.md

.DEFAULT_GOAL := help

.PHONY: help check-workspace \
	up down restart logs status build clean config sync \
	design-up design-down design-logs design-config design-build design-perms design-import

WORKSPACE_DIR ?= $(shell grep -E '^WORKSPACE_DIR=' .env 2>/dev/null | cut -d= -f2- | tr -d '\"' | tr -d "'")
# Expand a leading ~ to $HOME: neither make recipes nor compose tilde-expand raw
# .env values. Exported so compose uses the expanded path instead of .env's raw one.
WORKSPACE_DIR := $(patsubst ~%,$(HOME)%,$(WORKSPACE_DIR))
export WORKSPACE_DIR

# Host UID:GID so bind-mounted files stay owned by you. Override: `make up UID=1000 GID=1000`.
UID ?= $(shell id -u)
GID ?= $(shell id -g)
export UID
export GID

COMPOSE := docker compose -f docker-compose.yaml
DESIGN_COMPOSE := docker compose -f docker-compose.yaml -f docker-compose.opendesign.yaml

# Deterministic open-design volume name: $(COMPOSE_PROJECT_NAME)_open_design_data.
COMPOSE_PROJECT_NAME ?= pai-stack
export COMPOSE_PROJECT_NAME
DESIGN_VOLUME := $(COMPOSE_PROJECT_NAME)_open_design_data

# ── Help ──

help:  ## Show this help message
	@echo "\033[1mpai-stack\033[0m — AI Agent Development Environment"
	@echo ""
	@echo "\033[1;34mCore:\033[0m"
	@printf "  \033[36m%-16s\033[0m %s\n" "up" "Start hermes + llm-gateway (s=<service>)"
	@printf "  \033[36m%-16s\033[0m %s\n" "down" "Stop all services"
	@printf "  \033[36m%-16s\033[0m %s\n" "restart" "Restart (s=<service>)"
	@printf "  \033[36m%-16s\033[0m %s\n" "status" "Containers + health (s=<service>)"
	@printf "  \033[36m%-16s\033[0m %s\n" "logs" "Tail logs (s=<service>)"
	@printf "  \033[36m%-16s\033[0m %s\n" "sync" "Sync models, reload gateway"
	@echo ""
	@echo "\033[1;34mDesign:\033[0m"
	@printf "  \033[36m%-16s\033[0m %s\n" "design-up" "Start open-design (docs/opendesign.md)"
	@printf "  \033[36m%-16s\033[0m %s\n" "design-import" "Import folder: d=/workspace/<dir> [n=<name>]"
	@echo ""
	@echo "\033[1;34mMaintenance:\033[0m"
	@printf "  \033[36m%-16s\033[0m %s\n" "build" "Rebuild images (s=<service>)"
	@printf "  \033[36m%-16s\033[0m %s\n" "clean" "Stop + wipe volumes (destroys state)"
	@printf "  \033[36m%-16s\033[0m %s\n" "config" "Validate compose"
	@echo ""
	@echo "Full reference: docs/operations.md"

# ── Workspace guard (validates only — never creates anything on the host) ──

check-workspace:
	@if [ ! -f .env ]; then \
		echo "\033[31m[ERROR]\033[0m .env not found. Create it yourself: cp .env.example .env"; \
		exit 1; \
	fi
	@WS="$(WORKSPACE_DIR)"; \
	if [ -z "$$WS" ]; then \
		echo "\033[31m[ERROR]\033[0m WORKSPACE_DIR is not set in .env. Point it at your existing workspace directory."; \
		exit 1; \
	fi; \
	if [ ! -d "$$WS" ]; then \
		echo "\033[31m[ERROR]\033[0m WORKSPACE_DIR '$$WS' does not exist. Create it yourself, then re-run."; \
		exit 1; \
	fi

# ── Core (see docs/operations.md) ──

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

clean:  ## Stop containers and remove persisted volumes (destroys hermes state)
	$(COMPOSE) down -v --remove-orphans

config:  ## Validate and view compose config
	$(COMPOSE) config

# ── OpenDesign (see docs/opendesign.md) ──

design-up: check-workspace design-perms  ## Start open-design alongside core stack
	$(DESIGN_COMPOSE) --profile design up -d --build open-design

design-perms:  ## Create volume + fix ownership to host UID:GID
	docker volume create $(DESIGN_VOLUME) >/dev/null
	docker run --rm -v $(DESIGN_VOLUME):/data alpine chown -R $(UID):$(GID) /data

design-import:  ## Link a workspace folder: make design-import d=/workspace/<dir> [n=<name>]
	@if [ -z "$(d)" ]; then echo "Usage: make design-import d=/workspace/<folder> [n=<name>] (container path, not host path)"; exit 1; fi
	@TOKEN=$$(grep -E '^OD_API_TOKEN=' .env | cut -d= -f2- | tr -d '"' | tr -d "'"); \
	NAME_ARG=""; if [ -n "$(n)" ]; then NAME_ARG="--name $(n)"; fi; \
	docker exec -e OD_API_TOKEN="$$TOKEN" open-design node /app/apps/daemon/bin/od.mjs project import "$(d)" $$NAME_ARG

design-build:  ## Build open-design image (bundled linux opencode)
	$(DESIGN_COMPOSE) --profile design build open-design

design-down:  ## Stop open-design only (workspace + volume untouched)
	$(DESIGN_COMPOSE) stop open-design

design-logs:  ## Tail open-design logs
	$(DESIGN_COMPOSE) logs -f open-design

design-config:  ## Validate merged OpenDesign compose configuration
	$(DESIGN_COMPOSE) --profile design config

# ── Models (see docs/llm-gateway.md) ──

sync:  ## Sync models from keyed providers (liveness-probed), reload gateway
	python3 scripts/sync-models.py
