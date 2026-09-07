#!/usr/bin/env bash
# ==============================================================================
# pai-stack Deployment Runner  (the ONLY way to provision this stack)
# Requires: ansible-core, sshpass (for password auth)
# Install:  pip install ansible-core && apt/brew install sshpass
#
# Point it at the target machine by IP/hostname — a LAN address
# (e.g. 192.168.1.50) OR a Tailscale address (MagicDNS name / 100.x.y.z).
# Ansible SSHes in and installs Docker, installs Tailscale (if absent) and
# joins your tailnet, generates secrets, and starts the stack.
#
# Usage:
#   ./deploy.sh          -> Deploy remotely (SSH to TARGET_HOST from .env)
#   ./deploy.sh --renew  -> Delete all stack containers/volumes/.env and reinstall fresh (DESTRUCTIVE)
# ==============================================================================

set -euo pipefail

# Escape a string for safe use inside a YAML double-quoted scalar.
escape_yaml() {
    local s="$1"
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    printf '%s' "$s"
}

# Temporary file holding SSH/sudo passwords (deleted on exit). Never committed.
SECRETS_FILE=""
cleanup() { [[ -n "${SECRETS_FILE:-}" ]] && rm -f "$SECRETS_FILE"; }
trap cleanup EXIT

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Check dependencies
if ! command -v ansible-playbook >/dev/null 2>&1; then
    echo "❌ Error: ansible-playbook is not installed."
    echo "   Install: pip install ansible-core"
    exit 1
fi

# sshpass is required for unattended password auth (SSH_PASSWORD / BECOME_PASSWORD)
if [[ -n "${SSH_PASSWORD:-}" || -n "${BECOME_PASSWORD:-}" ]]; then
    if ! command -v sshpass >/dev/null 2>&1; then
        echo "❌ Error: SSH_PASSWORD/BECOME_PASSWORD set but sshpass is not installed."
        echo "   macOS:  brew install hudochenkov/sshpass/sshpass"
        echo "   Debian: apt install sshpass"
        exit 1
    fi
fi

echo "=================================================================="
echo "  🚀 pai-stack Automated Deployment Runner                        "
echo "=================================================================="

# Check for --renew mode
RENEW=false
ARGS=()

for arg in "$@"; do
    case "$arg" in
        --renew)
            RENEW=true
            ;;
        *)
            ARGS+=("$arg")
            ;;
    esac
done

if [[ "$RENEW" == true ]]; then
    echo "⚠️  --renew requested: Ansible will DELETE docker, syncthing and their configs, the entire pai-stack directory, then reinstall everything fresh from scratch."
    echo "   KB files in \$PERSONAL_FOLDER/silverbulletKB are NOT deleted (Syncthing-synced)."
fi

# Load configuration from .env if it exists (auto-create from example if missing)
if [[ ! -f "${SCRIPT_DIR}/.env" && -f "${SCRIPT_DIR}/.env.example" ]]; then
    echo "📝 No .env found — creating one from .env.example..."
    cp "${SCRIPT_DIR}/.env.example" "${SCRIPT_DIR}/.env"
fi

if [[ -f "${SCRIPT_DIR}/.env" ]]; then
    echo "🔧 Loading configuration from .env..."
    # shellcheck disable=SC1091
    source "${SCRIPT_DIR}/.env"
else
    echo "⚠️  No .env file found. Defaults will be used. Consider copying .env.example to .env."
fi

# Set defaults
TARGET_HOST=${TARGET_HOST:-"localhost"}
TARGET_USER=${TARGET_USER:-"$USER"}
TAILSCALE_DOMAIN=${TAILSCALE_DOMAIN:-""}
LLAMACPP_BASE_URL=${LLAMACPP_BASE_URL:-"http://localhost:8080/v1"}
LLAMACPP_MODEL_NAME=${LLAMACPP_MODEL_NAME:-"nemotron-3-nano-omni-30b-a3b-reasoning-q4-k-m"}
OPENROUTER_API_KEY=${OPENROUTER_API_KEY:-""}
KILO_GATEWAY_API_KEY=${KILO_GATEWAY_API_KEY:-""}
MISTRAL_API_KEY=${MISTRAL_API_KEY:-""}
TAILSCALE_AUTH_KEY=${TAILSCALE_AUTH_KEY:-""}
HERMES_DASHBOARD_PASSWORD=${HERMES_DASHBOARD_PASSWORD:-""}
SYNCTHING_GUI_USER=${SYNCTHING_GUI_USER:-"admin"}
SYNCTHING_GUI_PASSWORD=${SYNCTHING_GUI_PASSWORD:-""}
CODEGRAPH_ENABLED=${CODEGRAPH_ENABLED:-"true"}
PERSONAL_FOLDER=${PERSONAL_FOLDER:-""}
# If PERSONAL_FOLDER is just the dev machine's ~/Personal (the historical default
# written into .env as PERSONAL_FOLDER="${HOME}/Personal"), it is NOT valid on the
# target Pi. Blank it so the playbook derives the *target* user's own
# ~/Personal instead.
if [ "${PERSONAL_FOLDER}" = "${HOME}/Personal" ]; then
  PERSONAL_FOLDER=""
fi
SSH_PASSWORD=${SSH_PASSWORD:-""}
BECOME_PASSWORD=${BECOME_PASSWORD:-""}

# Build Ansible extra vars JSON payload
EXTRA_VARS="{
  \"tailscale_domain\": \"${TAILSCALE_DOMAIN}\",
  \"tailscale_auth_key\": \"${TAILSCALE_AUTH_KEY}\",
  \"llamacpp_base_url\": \"${LLAMACPP_BASE_URL}\",
  \"llamacpp_model_name\": \"${LLAMACPP_MODEL_NAME}\",
  \"openrouter_api_key\": \"${OPENROUTER_API_KEY}\",
  \"kilo_gateway_api_key\": \"${KILO_GATEWAY_API_KEY}\",
  \"mistral_api_key\": \"${MISTRAL_API_KEY}\",
  \"hermes_dashboard_password\": \"${HERMES_DASHBOARD_PASSWORD}\",
  \"syncthing_gui_user\": \"${SYNCTHING_GUI_USER}\",
  \"syncthing_gui_password\": \"${SYNCTHING_GUI_PASSWORD}\",
  \"codegraph_enabled\": \"${CODEGRAPH_ENABLED}\",
  \"renew\": $([ "$RENEW" == true ] && echo "true" || echo "false")
}"
# Only pass pai_personal_dir when an explicit PERSONAL_FOLDER was provided. When
# blank, omit it so the playbook derives the target user's ~/Personal — an
# empty string here would override the playbook default (extra vars win).
if [ -n "${PERSONAL_FOLDER}" ]; then
  EXTRA_VARS="${EXTRA_VARS%?}, \"pai_personal_dir\": \"${PERSONAL_FOLDER}\"}"
fi

# ---- Optional unattended credentials (from .env) ----
# If SSH_PASSWORD / BECOME_PASSWORD are set, feed them to Ansible via a
# temporary vars file so the run never prompts. Otherwise keep -k / -K.
SECRETS_ARG=""
if [[ -n "${SSH_PASSWORD:-}" || -n "${BECOME_PASSWORD:-}" ]]; then
    SECRETS_FILE="${SCRIPT_DIR}/.deploy-secrets.$(date +%s).$$.yml"
    {
        [[ -n "${SSH_PASSWORD:-}" ]]    && echo "ansible_password: \"$(escape_yaml "${SSH_PASSWORD}")\""
        [[ -n "${BECOME_PASSWORD:-}" ]] && echo "ansible_become_pass: \"$(escape_yaml "${BECOME_PASSWORD}")\""
    } > "$SECRETS_FILE"
    SECRETS_ARG="-e @${SECRETS_FILE}"
fi

ASK_SSH="-k";     [[ -n "${SSH_PASSWORD:-}" ]]     && ASK_SSH=""
ASK_BECOME="-K";  [[ -n "${BECOME_PASSWORD:-}" ]] && ASK_BECOME=""

if [[ -n "$ASK_SSH" || -n "$ASK_BECOME" ]]; then
    echo "🌐 Remote target: ${TARGET_USER}@${TARGET_HOST}"
    echo "👉 You will be prompted for: ${ASK_SSH:+-k SSH password }${ASK_BECOME:+-K sudo password }"
else
    echo "🌐 Remote target: ${TARGET_USER}@${TARGET_HOST} (unattended, credentials from .env)..."
fi
echo ""

cd "${SCRIPT_DIR}/ansible"
ansible-playbook playbook.yml \
    -i "${TARGET_HOST}," \
    -u "${TARGET_USER}" \
    -e "$EXTRA_VARS" \
    ${SECRETS_ARG} \
    ${ASK_SSH} \
    ${ASK_BECOME} \
    "${ARGS[@]+"${ARGS[@]}"}"
