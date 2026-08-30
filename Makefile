# pai-stack convenience commands
#
# Provisioning is done ONLY via Ansible (./deploy.sh) — it installs Docker,
# Tailscale, the stack, and seeds OmniRoute from bare SSH.
# These targets wrap that, plus day-to-day runtime helpers.

.PHONY: help deploy deploy-local seed logs status stop restart update clean

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

deploy:  ## Remote provision via containerized Ansible (from your Mac/any Docker host)
	./deploy.sh

deploy-local:  ## Provision THIS host via containerized Ansible (--local)
	./deploy.sh --local

seed:   ## Re-seed OmniRoute model combos
	docker compose exec -T omniroute /app/seed-combos.sh

logs:   ## Tail logs for all services
	docker compose logs -f

status: ## Show running services
	docker compose ps

stop:   ## Stop the stack (keeps data)
	docker compose stop

restart: ## Restart the stack
	docker compose restart

update: ## Pull latest images & rebuild
	docker compose pull && docker compose up -d --build

clean:  ## Stop stack and DELETE all persisted data (named volumes) — DESTRUCTIVE
	docker compose down -v
