# pai-stack

Hermes Agent + OmniRoute + SilverBullet on Raspberry Pi 4B (4GB).

## Quick Start

```bash
# 1. Create data directories (must be done before docker compose up)
mkdir -p hermes-data omniroute-data ~/Personal/silverbullet

# 2. Create .env from template
cp .env.example .env
# Edit .env with your secrets

# 3. Start services (config.yaml is synced automatically on startup)
docker compose up -d

# 4. Seed the model routing combo (after omniroute is healthy)
./seed-combos.sh
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
| silverbullet | 7070 | Knowledge base & note-taking (SilverBullet) |

## Resources (RPi 4B)

| Container | Memory | CPU |
|-----------|--------|-----|
| omniroute | 512MB | 1 core |
| hermes | 1536MB | 2 cores |
| silverbullet | 256MB | 0.5 core |
| OS/headroom | ~1696MB | 0.5 core |

## Manual Combo Seeding

OmniRoute combos are not seeded automatically. After starting the stack:

```bash
./seed-combos.sh
```

This creates the `personal/gemini-fallback` combo that routes requests through antigravity (paid Gemini) first, falling back to opencode free models on exhaustion.

To re-seed after a database reset, run the same command again.

## Knowledgebase (SilverBullet)

Access at `http://<pi-ip>:7070`

- Username: from `SB_USER` in `.env`
- Password: from `SB_PASSWORD` in `.env`

Notes are stored at `~/Personal/silverbullet/` on the host. Hermes has read access to this directory at `/opt/data/Personal/silverbullet/`, so any notes you create in SilverBullet are automatically available as Hermes knowledgebase content.

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
├── omniroute-data/        # OmniRoute persistent data (git-ignored)
└── ~/Personal/silverbullet/  # SilverBullet notes space (shared with Hermes)
```
