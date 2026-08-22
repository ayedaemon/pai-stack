# pai-stack

Hermes Agent + OmniRoute + SilverBullet on Raspberry Pi 4B (4GB).

## Quick Start

```bash
# 1. Create data directories (must be done before docker compose up)
mkdir -p hermes-data omniroute-data caddy-data caddy-config ~/Personal/silverbullet

# 2. Create .env from template
cp .env.example .env
# Edit .env with your secrets

# 3. Allow Caddy to fetch Tailscale TLS certificates
# On the RPi host, set TS_PERMIT_CERT_UID to the caddy container user:
sudo tailscale set --operator=$USER
# Or add TS_PERMIT_CERT_UID=caddy to /etc/default/tailscaled and restart tailscaled

# 4. Start services (builds Caddy image on first run)
docker compose up -d --build

# 5. Seed the model routing combo (after omniroute is healthy)
./seed-combos.sh
```

## Updating config.yaml

Edit `config.yaml` then restart — it syncs automatically:

```bash
docker compose restart hermes
```

## Services

All services are accessible over HTTPS via Tailscale TLS at `rpi.burro-smelt.ts.net`.

| Service | URL | Purpose |
|---------|-----|---------|
| omniroute | `https://rpi.burro-smelt.ts.net:20128` | AI model routing gateway (OpenAI-compatible API) |
| hermes | `https://rpi.burro-smelt.ts.net:9119` | Hermes dashboard |
| hermes | `https://rpi.burro-smelt.ts.net:8642` | Hermes API server |
| silverbullet | `https://rpi.burro-smelt.ts.net:7070` | Knowledge base & note-taking (SilverBullet) |
| caddy | — | Reverse proxy with Tailscale TLS (internal) |

## Resources (RPi 4B)

| Container | Memory | CPU |
|-----------|--------|-----|
| caddy | 64MB | 0.5 core |
| omniroute | 512MB | 1 core |
| hermes | 1792MB | 2 cores |
| silverbullet | 256MB | 0.5 core |
| OS/headroom | ~1376MB | 0 core |

## Manual Combo Seeding

OmniRoute combos are not seeded automatically. After starting the stack:

```bash
./seed-combos.sh
```

This creates the `personal/gemini-fallback` combo that routes requests through antigravity (paid Gemini) first, falling back to opencode free models on exhaustion.

To re-seed after a database reset, run the same command again.

## SilverBullet Configuration

To configure SilverBullet with useful plugs like the **Obsidian-Style Visual Graph** (`silverbullet-graphview`), run the seed script:

```bash
./seed-silverbullet.sh
```

This script will initialize your SilverBullet `CONFIG.md` page with the required Lua configuration for the graph view. After running it, open SilverBullet and run the command `Plugs: Update` to install the plug.

## Knowledgebase & Vector Search

### SilverBullet (Note-taking UI)

Access at `https://rpi.burro-smelt.ts.net:7070`

- Username: from `SB_USER` in `.env`
- Password: from `SB_PASSWORD` in `.env`

### Hermes RAG (Retrieval-Augmented Generation)

Hermes indexes the entire `~/Personal` directory tree for vector search, which includes:
- SilverBullet notes (`~/Personal/silverbullet/`)
- All project directories under `~/Personal/`

**How it works:**
- Uses local embeddings (`all-MiniLM-L6-v2` via fastembed, ~80MB RAM, no API key)
- Stores vectors in sqlite-vec alongside Hermes's existing database
- `reindex_on_change: true` — file watcher picks up edits from SilverBullet and other tools automatically
- `auto_retrieve: true` — relevant chunks are injected into conversation context automatically

**Shared volume mapping:**

| Host | Hermes Container | SilverBullet Container |
|------|------------------|------------------------|
| `~/Personal/` | `/opt/data/Personal/` (read/write) | — |
| `~/Personal/silverbullet/` | `/opt/data/Personal/silverbullet/` | `/space` (read/write) |

## Dashboard

Access at `https://rpi.burro-smelt.ts.net:9119`

- Username: from `HERMES_DASHBOARD_BASIC_AUTH_USERNAME` in `.env`
- Password: from `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD` in `.env`

## Files

```
├── docker-compose.yaml    # Service definitions (includes Caddy)
├── Dockerfile.caddy       # Custom Caddy build with Tailscale TLS module
├── Caddyfile              # Reverse proxy configuration
├── config.yaml            # Hermes configuration (source of truth)
├── seed-combos.sh         # Combo seeding script
├── seed-silverbullet.sh   # SilverBullet configuration script
├── .env                   # Secrets (git-ignored)
├── .env.example           # Template for .env
├── hermes-data/           # Hermes persistent data (git-ignored, contains config copy)
├── omniroute-data/        # OmniRoute persistent data (git-ignored)
├── caddy-data/            # Caddy TLS certs & state (git-ignored)
├── caddy-config/          # Caddy runtime config (git-ignored)
└── ~/Personal/silverbullet/  # SilverBullet notes space (shared with Hermes)
```
