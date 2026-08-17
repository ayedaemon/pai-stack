# pai-stack

Hermes Agent + OmniRoute on Raspberry Pi 4B (4GB).

## Quick Start

```bash
# 1. Create .env from template
cp .env.example .env
# Edit .env with your secrets and IDs (run `id -u` and `id -g` on the Pi)

# 2. Start services
docker compose up -d

# 3. Seed the model routing combo (after omniroute is healthy)
docker exec omniroute /app/data/seed-combos.sh
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
├── config.yaml            # Hermes configuration
├── seed-combos.sh         # Combo seeding script
├── .env                   # Secrets (git-ignored)
├── .env.example           # Template for .env
├── hermes-data/           # Hermes persistent data (git-ignored)
└── omniroute-data/        # OmniRoute persistent data (git-ignored)
```
