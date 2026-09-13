# pai-stack Makefile
# Manages base services: hermes, graft, mcp-server
# and optional extended stack: surrealdb and open-notebook

.PHONY: help check-workspace \
	up down restart logs status build clean config \
	up-all down-all restart-all logs-all status-all build-all clean-all config-all

WORKSPACE_DIR ?= $(shell grep -E '^WORKSPACE_DIR=' .env 2>/dev/null | cut -d= -f2- | tr -d '\"' | tr -d "'")

# Compose file definitions
COMPOSE_BASE := -f docker-compose.yaml
COMPOSE_NOTEBOOK := -f docker-compose.open-notebook.yml
COMPOSE_ALL := $(COMPOSE_BASE) $(COMPOSE_NOTEBOOK)

DOCKER_COMPOSE_BASE := docker compose $(COMPOSE_BASE)
DOCKER_COMPOSE_ALL := docker compose $(COMPOSE_ALL)

# Dynamic stack selector: pass ALL=1 or STACK=all to any base command
ifeq ($(ALL),1)
  COMPOSE := $(DOCKER_COMPOSE_ALL)
else ifeq ($(STACK),all)
  COMPOSE := $(DOCKER_COMPOSE_ALL)
else
  COMPOSE := $(DOCKER_COMPOSE_BASE)
endif

help:  ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

check-workspace:  ## Verify that WORKSPACE_DIR exists on the host
	@if [ -z "$(WORKSPACE_DIR)" ]; then \
		echo "\033[31m[ERROR]\033[0m WORKSPACE_DIR is not set in .env. Please define WORKSPACE_DIR in your .env file."; \
		exit 1; \
	fi
	@if [ ! -d "$(WORKSPACE_DIR)" ]; then \
		echo "\033[31m[ERROR]\033[0m WORKSPACE_DIR '$(WORKSPACE_DIR)' does not exist on the host."; \
		echo "Please create the directory on your host machine or configure a valid path in .env."; \
		exit 1; \
	fi

# ── Base Stack (or Dynamic via ALL=1) ─────────────────────────────────────────

up: check-workspace  ## Start services in background (use ALL=1 for full stack, s=<service>)
	$(COMPOSE) up -d $(s)

down:  ## Stop services (use ALL=1 for full stack)
	$(COMPOSE) down

restart:  ## Restart services (optional: s=<service>, ALL=1)
	$(COMPOSE) restart $(s)

logs:  ## Tail logs for services (optional: s=<service>, ALL=1)
	$(COMPOSE) logs -f $(s)

status:  ## Show running containers and health status (optional: s=<service>, ALL=1)
	$(COMPOSE) ps $(s)

build:  ## Build container images (optional: s=<service>, ALL=1)
	$(COMPOSE) build $(s)

clean:  ## Stop containers and remove persisted base volumes (destroys hermes & graft state)
	$(COMPOSE) down -v

config:  ## Validate and view compose config (use ALL=1 for full stack)
	$(COMPOSE) config

# ── Open Notebook (optional extended stack) ───────────────────────────────────
# Explicit targets for base stack + Open Notebook research stack

up-all: check-workspace  ## Start base stack + Open Notebook research stack (optional: s=<service>)
	$(DOCKER_COMPOSE_ALL) up -d $(s)

down-all:  ## Stop base stack + Open Notebook
	$(DOCKER_COMPOSE_ALL) down

restart-all:  ## Restart all services including Open Notebook (optional: s=<service>)
	$(DOCKER_COMPOSE_ALL) restart $(s)

logs-all:  ## Tail logs for all services including Open Notebook (optional: s=<service>)
	$(DOCKER_COMPOSE_ALL) logs -f $(s)

status-all:  ## Show status of all services including Open Notebook (optional: s=<service>)
	$(DOCKER_COMPOSE_ALL) ps $(s)

build-all:  ## Build images for all services (optional: s=<service>)
	$(DOCKER_COMPOSE_ALL) build $(s)

clean-all:  ## Stop and remove ALL volumes including Open Notebook data (DESTRUCTIVE)
	$(DOCKER_COMPOSE_ALL) down -v

config-all:  ## Validate and view merged compose config for all services
	$(DOCKER_COMPOSE_ALL) config
