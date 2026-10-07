# pai-stack — AI agent dev environment (Hermes + LLM Gateway)
# Full reference: docs/operations.md

.DEFAULT_GOAL := help

.PHONY: help check-workspace \
	up down restart logs status build clean config sync \
	all-up all-down all-clean \
	design-up design-down design-logs design-config design-build design-perms design-import \
	dsh-up dsh-down dsh-logs dsh-config dsh-build dsh-perms dsh-sync-models dsh-ensure-web dsh-password dsh-clean \
	terrain-up terrain-down terrain-logs terrain-config terrain-build terrain-perms terrain-index terrain-ask \


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

# Docker socket GID for dsh `group_add` (host daemon reuse). Docker Desktop
# forwards the socket as root:root (0); Linux is typically root:docker.
# `user:` preserves supplementary groups (the old setpriv drop did not,
# which is why a proxy socket used to exist — now deleted).
DOCKER_GID ?= $(shell stat -c %g /var/run/docker.sock 2>/dev/null || echo 0)
export DOCKER_GID

COMPOSE := docker compose -f docker-compose.yaml
DESIGN_COMPOSE := docker compose -f docker-compose.yaml -f docker-compose.opendesign.yaml
DSH_COMPOSE := docker compose -f docker-compose.yaml -f docker-compose.dsh.yaml
TERRAIN_COMPOSE := docker compose -f docker-compose.yaml -f docker-compose.terrain.yaml
# Merged view of every profile — all-clean uses it so no container or named
# volume is left behind (core `down -v` only knows hermes-data).
ALL_COMPOSE := docker compose -f docker-compose.yaml -f docker-compose.dsh.yaml -f docker-compose.opendesign.yaml -f docker-compose.terrain.yaml
ALL_PROFILES := --profile dsh --profile design --profile terrain

# Deterministic open-design volume name: $(COMPOSE_PROJECT_NAME)_open_design_data.
# The *-perms targets stamp both compose labels at `docker volume create` so
# compose recognises these volumes as its own (otherwise every up prints
# 'already exists but was not created by Docker Compose'). Labels do NOT make
# them external: down -v still removes them (verified with a throwaway volume).
COMPOSE_PROJECT_NAME ?= pai-stack
export COMPOSE_PROJECT_NAME
DESIGN_VOLUME := $(COMPOSE_PROJECT_NAME)_open_design_data

# Deterministic dsh volume names: $(COMPOSE_PROJECT_NAME)_dsh_{data,toolchains}.
# No more dsh_programs volume — DSH program is baked into the image.
DSH_DATA_VOLUME := $(COMPOSE_PROJECT_NAME)_dsh_data
DSH_TOOLCHAINS_VOLUME := $(COMPOSE_PROJECT_NAME)_dsh_toolchains

# Deterministic terrain volume name: $(COMPOSE_PROJECT_NAME)_terrain_data.
# Holds ~/.terrain/registry.json — terrain's project registry, which lives
# outside any repo and must stay off the shared workspace bind mount.
TERRAIN_DATA_VOLUME := $(COMPOSE_PROJECT_NAME)_terrain_data

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
	@echo "\033[1;34mAll:\033[0m"
	@printf "  \033[36m%-16s\033[0m %s\n" "all-up" "Start everything: core + design + dsh + terrain"
	@printf "  \033[36m%-16s\033[0m %s\n" "all-down" "Stop everything (volumes untouched)"
	@printf "  \033[36m%-16s\033[0m %s\n" "all-clean" "Stop + wipe ALL volumes (destroys all state)"
	@echo ""
	@echo "\033[1;34mDesign:\033[0m"
	@printf "  \033[36m%-16s\033[0m %s\n" "design-up" "Start open-design (docs/opendesign.md)"
	@printf "  \033[36m%-16s\033[0m %s\n" "design-import" "Import folder: d=/workspace/<dir> [n=<name>]"
	@echo ""
	@echo "\033[1;34mDSH:\033[0m"
	@printf "  \033[36m%-16s\033[0m %s\n" "dsh-up" "Start DSH agent (docs/dsh.md)"
	@printf "  \033[36m%-16s\033[0m %s\n" "dsh-sync-models" "Push synced models into live DSH (restarts only on change)"
	@printf "  \033[36m%-16s\033[0m %s\n" "dsh-password" "Print one-time first-boot admin password"
	@printf "  \033[36m%-16s\033[0m %s\n" "dsh-clean" "Stop dsh + wipe dsh volumes (destroys dsh state)"
	@echo ""
	@echo "\033[1;34mCode intel:\033[0m"
	@printf "  \033[36m%-16s\033[0m %s\n" "terrain-up" "Start terrain index service (docs/terrain.md)"
	@printf "  \033[36m%-16s\033[0m %s\n" "terrain-build" "Build terrain image from Rust source (slow first build)"
	@printf "  \033[36m%-16s\033[0m %s\n" "terrain-index" "Index a project: d=/opt/data/<dir> [n=<slug>]"
	@echo ""
	@echo "\033[1;34mPair:\033[0m"
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

# ── All (core + every opt-in profile) ──

all-up: check-workspace  ## Start everything: core + design + dsh + terrain
	$(MAKE) up
	$(MAKE) design-up
	$(MAKE) dsh-up
	$(MAKE) terrain-up

all-down:  ## Stop everything (profile containers + core, volumes untouched)
	$(MAKE) dsh-down
	$(MAKE) design-down
	$(MAKE) terrain-down
	$(MAKE) down

all-clean:  ## Stop everything + wipe ALL volumes (destroys hermes/dsh/design/terrain state)
	$(ALL_COMPOSE) $(ALL_PROFILES) down -v --remove-orphans

# ── OpenDesign (see docs/opendesign.md) ──

design-up: check-workspace design-perms  ## Start open-design alongside core stack
	@BIND="$${OPEN_DESIGN_BIND_IP:-$$(grep -E '^OPEN_DESIGN_BIND_IP=' .env 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'")}"; \
	TOKEN=$$(grep -E '^OD_API_TOKEN=' .env | cut -d= -f2- | tr -d '"' | tr -d "'"); \
	if [ "$$BIND" = "0.0.0.0" ] || [ "$$BIND" = "::" ]; then \
		if [ -z "$$TOKEN" ] || [ "$$TOKEN" = "admin" ]; then \
			echo "\033[31m[WARN]\033[0m OPEN_DESIGN_BIND_IP=$$BIND exposes open-design to the LAN with default/empty OD_API_TOKEN. Set a strong token (openssl rand -hex 32), or keep 127.0.0.1."; \
		fi; \
		echo "\033[33m[INFO]\033[0m LAN mode: browse via http://<host-ip>:$${OPEN_DESIGN_PORT:-$$(grep -E '^OPEN_DESIGN_PORT=' .env | cut -d= -f2- | tr -d '"' | tr -d "'")}, and list it in OPEN_DESIGN_ALLOWED_ORIGINS or /api calls get 403."; \
	fi
	$(DESIGN_COMPOSE) --profile design up -d --build open-design

design-perms:  ## Create volume + fix ownership to host UID:GID
	docker volume create --label com.docker.compose.project=$(COMPOSE_PROJECT_NAME) --label com.docker.compose.volume=open_design_data $(DESIGN_VOLUME) >/dev/null
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

# ── DSH (see docs/dsh.md) ──

dsh-up: check-workspace dsh-perms  ## Start dsh alongside core stack
	$(DSH_COMPOSE) --profile dsh up -d --build dsh
	$(MAKE) dsh-ensure-web

dsh-perms:  ## Create volumes + fix ownership once to host UID:GID
	docker volume create --label com.docker.compose.project=$(COMPOSE_PROJECT_NAME) --label com.docker.compose.volume=dsh_data $(DSH_DATA_VOLUME) >/dev/null
	docker volume create --label com.docker.compose.project=$(COMPOSE_PROJECT_NAME) --label com.docker.compose.volume=dsh_toolchains $(DSH_TOOLCHAINS_VOLUME) >/dev/null
	docker run --rm -v $(DSH_DATA_VOLUME):/data alpine chown -R $(UID):$(GID) /data
	docker run --rm -v $(DSH_TOOLCHAINS_VOLUME):/data alpine chown -R $(UID):$(GID) /data
	# Fresh volumes inherit the image-baked /data/dsh ownership instead;
	# this only repairs pre-existing root-owned volumes. The entrypoint
	# never chowns (it runs as `user:` and owns what it creates).

dsh-sync-models:  ## Push regenerated provider config into live volume (restarts only on change)
# Seed (dsh/settings.yaml) is rebuilt by every `make sync` from the live
# gateway alias list. This target merges it into the running volume's
# profiles/web/cordis.patch.yml: the managed entries are replaced
# wholesale, every other entry (managed auth block, UI edits elsewhere) is
# preserved byte-for-byte. Restarts only when the models list actually changed.
	@OUT=$$(python3 scripts/push-dsh-models.py --volume $(DSH_DATA_VOLUME) --uid $(UID) --gid $(GID) | tail -n 1); \
	echo "dsh models: $$OUT"; \
	if [ "$$OUT" = "RESULT:CHANGED" ]; then docker restart dsh >/dev/null && $(MAKE) dsh-ensure-web; fi

dsh-ensure-web:  ## Wait for dsh web boot to be healthy
	@for i in $$(seq 1 60); do \
	  if docker exec dsh node -e "require('net').connect(3081,'127.0.0.1').on('connect',()=>process.exit(0)).on('error',()=>process.exit(1))" 2>/dev/null; then \
	    echo "dsh web profile healthy"; exit 0; \
	  fi; \
	  sleep 5; \
	done; \
	echo "[ERROR] dsh web did not become healthy in time (see: docker logs dsh)"; exit 1

dsh-password:  ## Print the one-time login token URL (host port)
	@TOKEN=$$(docker logs dsh 2>&1 | grep -o '?token=[^[:space:]]*' | tail -1 | sed 's/.*token=//'); \
	if [ -z "$$TOKEN" ]; then echo "[ERROR] No token in 'docker logs dsh' yet — is dsh booted?"; exit 1; fi; \
	PORT="$${DSH_PORT:-$$(grep -E '^DSH_PORT=' .env 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'")}"; \
	PORT="$${PORT:-9229}"; \
	echo "http://127.0.0.1:$$PORT/?token=$$TOKEN"

dsh-build:  ## Build dsh image (from official @deepseek-ai/dsh npm package)
	$(DSH_COMPOSE) --profile dsh build dsh

dsh-down:  ## Stop dsh only (workspace + volumes untouched)
	$(DSH_COMPOSE) stop dsh

dsh-clean:  ## Stop dsh + wipe dsh volumes (destroys sessions, auth, plugin state)
	docker rm -f dsh >/dev/null 2>&1 || true
	docker volume rm $(DSH_DATA_VOLUME) $(DSH_TOOLCHAINS_VOLUME) >/dev/null

dsh-logs:  ## Tail dsh logs
	$(DSH_COMPOSE) logs -f dsh

dsh-config:  ## Validate merged DSH compose configuration
	$(DSH_COMPOSE) --profile dsh config

# ── Terrain code intel (see docs/terrain.md) ──

terrain-up: check-workspace terrain-perms  ## Start terrain alongside core stack
	$(TERRAIN_COMPOSE) --profile terrain up -d --build terrain

terrain-perms:  ## Create volume + fix ownership to the container's terrain uid
	docker volume create --label com.docker.compose.project=$(COMPOSE_PROJECT_NAME) --label com.docker.compose.volume=terrain_data $(TERRAIN_DATA_VOLUME) >/dev/null
# NOT $(UID):$(GID) like dsh-perms. terrain runs as the fixed in-image user
# `terrain` (uid 1000, set by USER in terrain/Dockerfile), so chowning the
# volume to the host uid would leave it unable to write its project registry at
# ~/.terrain/registry.json. dsh instead runs as the host uid via compose
# `user:` with image-baked ownership + this one-time perms fix.
	docker run --rm -v $(TERRAIN_DATA_VOLUME):/data alpine chown -R 1000:1000 /data

terrain-build:  ## Build terrain image (Rust from source — slow first build)
	$(TERRAIN_COMPOSE) --profile terrain build terrain

terrain-down:  ## Stop terrain only (workspace + volume untouched)
	$(TERRAIN_COMPOSE) stop terrain

terrain-logs:  ## Tail terrain logs
	$(TERRAIN_COMPOSE) logs -f terrain

terrain-config:  ## Validate merged terrain compose configuration
	$(TERRAIN_COMPOSE) --profile terrain config

# `scan` only — no LLM, no token cost. Writes .terrain/ inside the repo.
terrain-index:  ## Index a project: d=/opt/data/workspace/<dir> [n=<slug>]
	@if [ -z "$(d)" ]; then echo "Usage: make terrain-index d=/opt/data/workspace/<folder> [n=<slug>] (container path, not host path)"; exit 1; fi
	@SLUG=""; if [ -n "$(n)" ]; then SLUG="--slug $(n)"; fi; \
	docker exec terrain terrain scan "$(d)" $$SLUG

# Needs TERRAIN_ALLOW_LLM=1 — keyless Zen models via opencode acp,
# NOT the gateway and NOT your tokens.
terrain-ask:  ## Knowledge Q&A: q="<question>" [n=<slug>]  (keyless, no tokens)
	@if [ -z "$(q)" ]; then echo "Usage: make terrain-ask q=\"<question>\" [n=<slug>]"; exit 1; fi
	@SLUG=""; if [ -n "$(n)" ]; then SLUG="--project $(n)"; fi; \
	docker exec terrain terrain ask query "$(q)" $$SLUG

# ── Models (see docs/llm-gateway.md) ──

sync:  ## Sync models from keyed providers (liveness-probed), reload gateway
	python3 scripts/sync-models.py
	@echo "DSH seed regenerated — push live with: make dsh-sync-models"

sync-dry:  ## Preview synced models without writing config or reloading gateway
	python3 scripts/sync-models.py --dry-run
