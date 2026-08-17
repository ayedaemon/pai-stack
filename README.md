# pai-stack

Hermes Agent + OmniRoute on Raspberry Pi 4B (4GB).

## Quick Start

```bash
# 1. Create data directories (must be done before docker compose up)
mkdir -p hermes-data omniroute-data

# 2. Create .env from template
cp .env.example .env
# Edit .env with your secrets

# 3. Start services (config.yaml is synced automatically on startup)
docker compose up -d

# 4. Seed the model routing combo (after omniroute is healthy)
docker exec omniroute /app/data/seed-combos.sh
```

## Updating config.yaml

Edit `config.yaml` then restart — it syncs automatically:

```bash
docker compose restart hermes
```

## Services

| Service | Port | Purpose |
|---------|------|---------|
| omniroute | 20128 | AI model routing gateway (OpenAI-compatible API) |
| hermes | 9119 | Hermes dashboard |
| hermes | 8642 | Hermes API server |

## Resources (RPi 4B)

| Container | Memory | CPU |
|-----------|--------|-----|
| omniroute | 512MB | 1 core |
| hermes | 1536MB | 2 cores |
| OS/headroom | ~1952MB | 1 core |

## Manual Combo Seeding

OmniRoute combos are not seeded automatically. After starting the stack:

```bash
docker exec omniroute /app/data/seed-combos.sh
```

This creates the `personal/gemini-fallback` combo that routes requests through antigravity (paid Gemini) first, falling back to opencode free models on exhaustion.

To re-seed after a database reset, run the same command again.

## Dashboard

Access at `http://<pi-ip>:9119`

- Username: from `HERMES_DASHBOARD_BASIC_AUTH_USERNAME` in `.env`
- Password: from `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD` in `.env`

## Files

```
├── docker-compose.yaml    # Service definitions
├── config.yaml            # Hermes configuration (source of truth)
├── seed-combos.sh         # Combo seeding script
├── .env                   # Secrets (git-ignored)
├── .env.example           # Template for .env
├── hermes-data/           # Hermes persistent data (git-ignored, contains config copy)
└── omniroute-data/        # OmniRoute persistent data (git-ignored)
```
