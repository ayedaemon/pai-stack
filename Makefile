# pai-stack Makefile
# Manages the 4 core services: hermes, codegraph, embeddings, and mcp-server

.PHONY: help check-workspace up down restart logs status build clean

WORKSPACE_DIR ?= $(shell grep -E '^WORKSPACE_DIR=' .env 2>/dev/null | cut -d= -f2- | tr -d '\"' | tr -d "'")
CODEGRAPH_SUBDIR ?= $(shell grep -E '^CODEGRAPH_SUBDIR=' .env 2>/dev/null | cut -d= -f2- | tr -d '\"' | tr -d "'")

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
	@if [ -n "$(CODEGRAPH_SUBDIR)" ] && [ "$(CODEGRAPH_SUBDIR)" != "." ] && [ ! -d "$(WORKSPACE_DIR)/$(CODEGRAPH_SUBDIR)" ]; then \
		echo "\033[31m[ERROR]\033[0m CODEGRAPH_SUBDIR '$(WORKSPACE_DIR)/$(CODEGRAPH_SUBDIR)' does not exist on the host."; \
		exit 1; \
	fi

up: check-workspace  ## Start all services in the background
	docker compose up -d

down:  ## Stop all services
	docker compose down

restart:  ## Restart all services
	docker compose restart

logs:  ## Tail logs for all services
	docker compose logs -f

status:  ## Show running containers and health status
	docker compose ps

build:  ## Build container images
	docker compose build

clean:  ## Stop containers and remove persisted volumes (destroys hermes & codegraph state)
	docker compose down -v

# ── Open Notebook (optional extended stack) ───────────────────────────────────
# Targets below use both compose files. Run `make up` for the base stack only.
NOTEBOOK_COMPOSE_FILE := docker-compose.yaml:docker-compose.open-notebook.yml

up-all: check-workspace  ## Start base stack + Open Notebook research stack
	COMPOSE_FILE=$(NOTEBOOK_COMPOSE_FILE) docker compose up -d

down-all:  ## Stop base stack + Open Notebook
	COMPOSE_FILE=$(NOTEBOOK_COMPOSE_FILE) docker compose down

logs-all:  ## Tail logs for all services including Open Notebook
	COMPOSE_FILE=$(NOTEBOOK_COMPOSE_FILE) docker compose logs -f

status-all:  ## Show status of all services including Open Notebook
	COMPOSE_FILE=$(NOTEBOOK_COMPOSE_FILE) docker compose ps

clean-all:  ## Stop and remove ALL volumes including Open Notebook data (DESTRUCTIVE)
	COMPOSE_FILE=$(NOTEBOOK_COMPOSE_FILE) docker compose down -v
