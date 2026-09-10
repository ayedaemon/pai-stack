# pai-stack convenience commands
# Single .env, explicit flag: --local (default) → docker compose, --remote → ansible (tailscale+syncthing+compose)
# See docs/SETUP_FLOW.md for the 2-mode model.

.PHONY: help deploy deploy-renew logs status stop restart update clean

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

deploy:  ## Local deploy (default, no flag → docker compose)
	./deploy.sh --local

deploy-remote:  ## Remote deploy to Pi (requires TARGET_HOST in .env)
	./deploy.sh --remote

deploy-renew:  ## Local FRESH reinstall (delete volumes) — add --remote for Pi fresh
	./deploy.sh --local --renew

deploy-remote-renew:  ## Remote FRESH reinstall on Pi
	./deploy.sh --remote --renew

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
