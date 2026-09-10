#!/usr/bin/env bash
# ==============================================================================
# pai-stack — One env, two deploys
# ==============================================================================
# Purpose:
#   Deploys the entire pai-stack from a SINGLE .env file.
#   New devs: you only edit .env, then run one command.
#
#   - Local (default, no flag or --local):
#       Uses your machine's Docker. Starts hermes, codegraph, mcp-server.
#       Ignores TARGET_HOST / TAILSCALE / SYNCTHING — they are Pi-only.
#       Good for: coding on Mac/Linux, testing without a Pi.
#
#   - Remote (--remote):
#       SSHes into a Pi (via Tailscale or LAN), installs everything from bare OS:
#       Tailscale → Docker → Syncthing (host) → Secrets → Docker containers.
#       Requires TARGET_HOST in .env (e.g. rpi.burro-smelt.ts.net).
#       Good for: headless Pi that runs 24/7.
#
# How it decides:
#   MODE is explicit via flag, NOT auto-detected. Default is --local so you
#   cannot accidentally deploy to Pi. Use --remote when you mean Pi.
#
# Env file:
#   REPO_DIR/.env is the single source of truth. Copy from .env.example:
#     cp .env.example .env && edit STACK_ROOT
#   If .env is missing, this script creates it and exits so you can fill it.
#
#   Required: STACK_ROOT (absolute path, e.g. $HOME/stack_root)
#   Optional with sane defaults: CODEGRAPH_ENABLED, KB_DIRS, ports, etc.
#   Secrets (API_SERVER_KEY, dashboard passwords) are auto-generated on first
#   run if blank — written back to .env so both modes share the same keys.
#
# Safety:
#   - UID/GID in .env are NOT exported to the shell (bash marks UID readonly).
#     We filter them before sourcing; docker compose reads .env directly.
#   - STACK_ROOT must be absolute — prevents "mount ./stack_root" surprises.
#   - --renew is destructive: docker compose down -v (deletes named volumes).
#
# Examples:
#   ./deploy.sh                    # local, build & up
#   ./deploy.sh --local --renew    # local fresh (delete volumes first)
#   ./deploy.sh --remote           # remote Pi (needs TARGET_HOST)
#   ./deploy.sh --remote --renew   # remote fresh
#   make deploy                    # alias for --local
#   make deploy-remote             # alias for --remote
# ==============================================================================

set -euo pipefail

# ------------------------------------------------------------------------------
# 0. Locate repo and env files
#    REPO_DIR = directory containing this script (pai-stack root)
#    ENV_FILE = REPO_DIR/.env (your edited config, gitignored, 0600 on Pi)
#    EXAMPLE_ENV = REPO_DIR/.env.example (committed template)
# ------------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$SCRIPT_DIR"
ENV_FILE="${REPO_DIR}/.env"
EXAMPLE_ENV="${REPO_DIR}/.env.example"

# ------------------------------------------------------------------------------
# 1. Parse flags
#    --local  = docker compose only (default)
#    --remote = ansible to Pi (requires TARGET_HOST)
#    --renew  = delete volumes/data before deploy (destructive)
#    -h/--help = usage
#    Unknown flags exit 1 so typos are caught early.
# ------------------------------------------------------------------------------
MODE="local"
RENEW=0
for arg in "$@"; do
  case "$arg" in
    --remote) MODE="remote" ;;
    --local)  MODE="local" ;;
    --renew)  RENEW=1 ;;
    -h|--help) echo "Usage: $0 [--local|--remote] [--renew]"; echo "  --local: docker compose (default)"; echo "  --remote: ansible to Pi (requires TARGET_HOST)"; exit 0 ;;
    *) echo "Unknown: $arg (use --local, --remote, --renew, --help)" >&2; exit 1 ;;
  esac
done

# ------------------------------------------------------------------------------
# 2. Ensure .env exists — if not, seed from example and exit
#    This prevents running with an empty/missing config and shows the user
#    what to edit (STACK_ROOT) before any Docker/Ansible side effects.
# ------------------------------------------------------------------------------
if [[ ! -f "${ENV_FILE}" ]]; then cp "${EXAMPLE_ENV}" "${ENV_FILE}" 2>/dev/null || true; echo "Created .env from .env.example — EDIT STACK_ROOT then re-run."; exit 1; fi

# ------------------------------------------------------------------------------
# 3. Load .env into shell env
#    We use `set -a` so every VAR=val becomes exported.
#    UID/GID are filtered out because bash marks $UID as readonly — sourcing
#    them would abort with "readonly variable". Docker compose reads .env
#    directly, so filtering here is safe; the values stay in the file.
#    We write to a temp file then source it (avoids process substitution
#    quirks that fail `bash -n` with `|| true` inside `<(...)`).
# ------------------------------------------------------------------------------
grep -vE '^(UID|GID)=' "${ENV_FILE}" > /tmp/pai_filtered_env 2>/dev/null || true
set -a; source /tmp/pai_filtered_env; set +a
rm -f /tmp/pai_filtered_env

# ------------------------------------------------------------------------------
# 4. Validate core config
#    STACK_ROOT is the ONLY required var (both modes). It is the host path
#    that becomes /stack_root inside every container (Hermes KB, CodeGraph).
#    Must be absolute (no `stack_root` or `./stack_root`) — relativeness is
#    inside the container, not on the host.
# ------------------------------------------------------------------------------
if [[ -z "${STACK_ROOT:-}" ]]; then echo "ERROR: STACK_ROOT required in .env (e.g. STACK_ROOT=\$HOME/stack_root)" >&2; exit 1; fi
STACK_ROOT_EXPANDED="${STACK_ROOT/#\~/$HOME}"
if [[ "${STACK_ROOT_EXPANDED}" != /* ]]; then echo "ERROR: STACK_ROOT must be absolute path (got: ${STACK_ROOT})" >&2; exit 1; fi

# ------------------------------------------------------------------------------
# 5. Auto-generate secrets if blank (both modes)
#    ensure_secret VAR LEN:
#      - Reads VAR from .env (cut after first `=`, strips quotes/spaces)
#      - Also checks already-exported env (in case .env had VAR="" but shell
#        still has old value)
#      - If BOTH are empty, generates `openssl rand -hex LEN`, writes
#        VAR="hex" back to .env (sed replace or append), and exports it.
#      - Idempotent: re-running preserves existing keys (no rotation).
#    Why here and not in Ansible?
#      - Local and remote share the same .env file. Generating here ensures
#        local `docker compose up` gets the same API_SERVER_KEY as remote Pi
#        would, without duplicating logic.
#    Remote-only secret (SYNCTHING_GUI_PASSWORD) is only generated in --remote.
# ------------------------------------------------------------------------------
ensure_secret(){
  local n="$1" l="$2"
  local line; line=$(grep -E "^${n}=" "${ENV_FILE}" 2>/dev/null || true)
  local val; val=$(echo "$line" | cut -d= -f2-)
  val=$(echo "$val" | tr -d '"' | tr -d "'" | tr -d ' ')
  local envv; envv="${!n:-}"
  envv=$(echo "$envv" | tr -d '"' | tr -d "'" | tr -d ' ')
  if [[ -z "$val" ]] && [[ -z "$envv" ]]; then
    local g; g=$(openssl rand -hex "$l" | tr -d '\n')
    if grep -qE "^${n}=" "${ENV_FILE}"; then sed -i.bak "s|^${n}=.*|${n}=\"${g}\"|" "${ENV_FILE}"; rm -f "${ENV_FILE}.bak"; else echo "${n}=\"${g}\"" >> "${ENV_FILE}"; fi
    export "${n}=${g}"
    echo "[deploy] Generated ${n} and wrote to .env"
  fi
}
ensure_secret "API_SERVER_KEY" 32 || true
ensure_secret "HERMES_DASHBOARD_BASIC_AUTH_SECRET" 32 || true
ensure_secret "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD" 12 || true
if [[ "${MODE}" == "remote" ]]; then ensure_secret "SYNCTHING_GUI_PASSWORD" 12 || true; fi

# Reload after generation so newly written keys are available for routing below
grep -vE '^(UID|GID)=' "${ENV_FILE}" > /tmp/pai_filtered_env 2>/dev/null || true
set -a; source /tmp/pai_filtered_env; set +a
rm -f /tmp/pai_filtered_env

# ------------------------------------------------------------------------------
# 6. Route to local or remote
# ------------------------------------------------------------------------------
if [[ "${MODE}" == "local" ]]; then
  # ----- LOCAL MODE -----------------------------------------------------------
  # Only Docker Compose. No Ansible, no Syncthing, no Tailscale.
  # Remote-only vars are ignored with a helpful note so you don't wonder
  # why TAILSCALE_AUTH_KEY did nothing locally.
  # ----------------------------------------------------------------------------
  echo "[deploy] MODE=local -> docker compose only (ignores TARGET_HOST/TAILSCALE/SYNCTHING)"
  echo "[deploy] STACK_ROOT=${STACK_ROOT} -> /stack_root inside containers"
  mkdir -p "${STACK_ROOT_EXPANDED}"
  # Validate compose can render (catches bad STACK_ROOT before building images)
  docker compose -f "${REPO_DIR}/docker-compose.yaml" config >/dev/null 2>&1 || { echo "[deploy] ERROR: docker compose config failed — check STACK_ROOT and .env" >&2; docker compose -f "${REPO_DIR}/docker-compose.yaml" config 2>&1 | head -n 50 || true; exit 1; }
  if [[ -n "${TAILSCALE_AUTH_KEY:-}" ]]; then echo "[deploy] Note: TAILSCALE_AUTH_KEY set but ignored in --local."; fi
  if [[ -n "${TARGET_HOST:-}" ]]; then echo "[deploy] Note: TARGET_HOST=${TARGET_HOST} ignored in --local. Use --remote to deploy to Pi."; fi
  if [[ "${RENEW}" -eq 1 ]]; then echo "[deploy] --renew: docker compose down -v locally (DELETE volumes)"; docker compose -f "${REPO_DIR}/docker-compose.yaml" down -v || true; fi
  docker compose -f "${REPO_DIR}/docker-compose.yaml" up -d --build --remove-orphans
  echo ""
  echo "[deploy] Local stack up:"
  echo "  Hermes Dashboard: http://localhost:9119 (admin / \$HERMES_DASHBOARD_BASIC_AUTH_PASSWORD)"
  echo "  Hermes API:       http://localhost:8642 (Bearer \$API_SERVER_KEY)"
  echo "  CodeGraph:        http://localhost:20128/health"
  echo "  MCP Server:       http://localhost:8000/health"
  docker compose -f "${REPO_DIR}/docker-compose.yaml" ps

else
  # ----- REMOTE MODE ----------------------------------------------------------
  # Ansible to Pi. Installs/configures everything that local skips:
  #   1) Tailscale (if TAILSCALE_AUTH_KEY set), 2) Docker, 3) Syncthing host
  #   4) Secrets templated to Pi's .env, 5) Docker containers.
  # Requires TARGET_HOST (Pi address). Fails fast if missing so you don't
  # accidentally wait for an SSH timeout.
  # ----------------------------------------------------------------------------
  TARGET_HOST_TRIMMED=$(echo "${TARGET_HOST:-}" | tr -d ' ')
  if [[ -z "${TARGET_HOST_TRIMMED}" ]]; then echo "ERROR: --remote requires TARGET_HOST in .env (e.g. TARGET_HOST=\"rpi.burro-smelt.ts.net\")" >&2; exit 1; fi
  echo "[deploy] MODE=remote -> TARGET_HOST=${TARGET_HOST_TRIMMED} (ansible + syncthing + tailscale + compose)"
  echo "[deploy] STACK_ROOT=${STACK_ROOT} (local) -> Pi ~/stack_root via Syncthing"
  command -v ansible-playbook >/dev/null || { echo "[deploy] ERROR: ansible-playbook not found. Install: pip install ansible-core" >&2; exit 1; }
  TARGET_USER_CLEAN="${TARGET_USER:-pi}"
  # -i "host," = ad-hoc inventory (no inventory file)
  # -u user   = SSH user
  # -e @.env  = pass every .env var as Ansible extra_vars (so Pi gets same keys)
  # -k/-K     = ask for SSH/sudo passwords only if you set SSH_PASSWORD/BECOME_PASSWORD
  ANSIBLE_ARGS=(-i "${TARGET_HOST_TRIMMED}," -u "${TARGET_USER_CLEAN}" ansible/playbook.yml -e "@${ENV_FILE}")
  if [[ -n "${SSH_PASSWORD:-}" ]]; then ANSIBLE_ARGS+=(-k); fi
  if [[ -n "${BECOME_PASSWORD:-}" ]]; then ANSIBLE_ARGS+=(-K); fi
  if [[ "${RENEW}" -eq 1 ]]; then echo "[deploy] --renew: will force git clone and re-template on Pi (playbook force: yes)"; fi
  (cd "${REPO_DIR}" && ansible-playbook "${ANSIBLE_ARGS[@]}")
  echo ""
  echo "[deploy] Remote deploy done:"
  echo "  Hermes Dashboard: https://${TARGET_HOST_TRIMMED}:9119"
  echo "  Syncthing GUI:    https://${TARGET_HOST_TRIMMED}:8384"
  echo "  CodeGraph (via Pi): https://${TARGET_HOST_TRIMMED}:20128 (or http://codegraph:20128 inside Docker)"
fi
