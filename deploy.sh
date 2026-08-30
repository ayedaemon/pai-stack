#!/usr/bin/env bash
# ==============================================================================
# pai-stack Deployment Runner  (the ONLY way to provision this stack)
# Runs Ansible in a zero-dependency container.
#
# Point it at the target machine by IP/hostname — a LAN address
# (e.g. 192.168.1.50) OR a Tailscale address (MagicDNS name / 100.x.y.z).
# Ansible SSHes in and installs Docker, installs Tailscale (if absent) and
# joins your tailnet, generates secrets, starts the stack, and seeds OmniRoute.
#
# Usage:
#   ./deploy.sh          -> Deploy remotely (SSH to TARGET_HOST from .env)
#   ./deploy.sh --local  -> Deploy directly on this host (localhost)
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
IMAGE_NAME="pai-stack-ansible:latest"

# Check Docker is available
if ! command -v docker >/dev/null 2>&1; then
    echo "❌ Error: Docker is not installed or not in PATH."
    echo "Please install and launch Docker."
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    echo "❌ Error: Docker daemon is not running."
    echo "Please start Docker."
    exit 1
fi

echo "=================================================================="
echo "  🚀 pai-stack Automated Deployment Runner                        "
echo "=================================================================="

# Check for --local mode
IS_LOCAL=false
REBUILD=false
ARGS=()

for arg in "$@"; do
    case "$arg" in
        --local)
            IS_LOCAL=true
            ;;
        --rebuild)
            REBUILD=true
            ;;
        *)
            ARGS+=("$arg")
            ;;
    esac
done

# Build runner container if needed
if [[ "$(docker images -q "${IMAGE_NAME}" 2> /dev/null)" == "" ]] || [[ "$REBUILD" == true ]]; then
    echo "📦 Building Ansible task container (with sshpass & python)..."
    docker build -t "${IMAGE_NAME}" -f "${SCRIPT_DIR}/ansible/Dockerfile" "${SCRIPT_DIR}/ansible"
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
OPENAI_API_KEY=${OPENAI_API_KEY:-""}
TAILSCALE_AUTH_KEY=${TAILSCALE_AUTH_KEY:-""}
HERMES_DASHBOARD_PASSWORD=${HERMES_DASHBOARD_PASSWORD:-""}
SB_PASSWORD=${SB_PASSWORD:-""}
STACK_ROOT=${STACK_ROOT:-""}
# If STACK_ROOT is just the dev machine's ~/Personal (the historical default
# written into .env as STACK_ROOT="${HOME}/Personal"), it is NOT valid on the
# target Pi. Blank it so the playbook derives the *target* user's own
# ~/Personal instead.
if [ "${STACK_ROOT}" = "${HOME}/Personal" ]; then
  STACK_ROOT=""
fi
SSH_PASSWORD=${SSH_PASSWORD:-""}
BECOME_PASSWORD=${BECOME_PASSWORD:-""}

# Build Ansible extra vars JSON payload
EXTRA_VARS="{
  \"tailscale_domain\": \"${TAILSCALE_DOMAIN}\",
  \"tailscale_auth_key\": \"${TAILSCALE_AUTH_KEY}\",
  \"openai_api_key\": \"${OPENAI_API_KEY}\",
  \"hermes_dashboard_password\": \"${HERMES_DASHBOARD_PASSWORD}\",
  \"sb_password\": \"${SB_PASSWORD}\"
}"
# Only pass pai_personal_dir when an explicit STACK_ROOT was provided. When
# blank, omit it so the playbook derives the target user's ~/Personal — an
# empty string here would override the playbook default (extra vars win).
if [ -n "${STACK_ROOT}" ]; then
  EXTRA_VARS="${EXTRA_VARS%?}, \"pai_personal_dir\": \"${STACK_ROOT}\"}"
fi

# ---- Optional unattended credentials (from .env) ----
# If SSH_PASSWORD / BECOME_PASSWORD are set, feed them to Ansible via a
# temporary vars file so the run never prompts. Otherwise keep -k / -K.
SECRETS_ARG=""
if [[ -n "${SSH_PASSWORD:-}" || -n "${BECOME_PASSWORD:-}" ]]; then
    SECRETS_FILE="${SCRIPT_DIR}/.deploy-secrets.$(date +%s).$$.yml"
    {
        [[ -n "${SSH_PASSWORD:-}" ]]    && echo "ansible_ssh_pass: \"$(escape_yaml "${SSH_PASSWORD}")\""
        [[ -n "${BECOME_PASSWORD:-}" ]] && echo "ansible_become_pass: \"$(escape_yaml "${BECOME_PASSWORD}")\""
    } > "$SECRETS_FILE"
    SECRETS_ARG="-e @/workspace/$(basename "$SECRETS_FILE")"
fi

ASK_SSH="-k";     [[ -n "${SSH_PASSWORD:-}" ]]     && ASK_SSH=""
ASK_BECOME="-K";  [[ -n "${BECOME_PASSWORD:-}" ]] && ASK_BECOME=""

if [[ "$IS_LOCAL" == true ]]; then
    if [[ -n "$ASK_BECOME" ]]; then
        echo "📍 Running local deployment on host..."
        echo "👉 Enter sudo password when prompted:"
    else
        echo "📍 Running local deployment on host (unattended, sudo password from .env)..."
    fi
    echo ""
    run_args=( playbook.yml -i "localhost," -c local -e "$EXTRA_VARS" )
    [[ -n "$SECRETS_ARG" ]] && run_args+=( $SECRETS_ARG )
    [[ -n "$ASK_BECOME" ]] && run_args+=( "$ASK_BECOME" )
    [[ ${#ARGS[@]} -gt 0 ]] && run_args+=( "${ARGS[@]}" )
    docker run --rm -it \
        --name pai-stack-ansible-runner \
        --network host \
        -v "${SCRIPT_DIR}:/workspace" \
        -v "/var/run/docker.sock:/var/run/docker.sock" \
        "${IMAGE_NAME}" \
        "${run_args[@]}"
else
    if [[ -n "$ASK_SSH" || -n "$ASK_BECOME" ]]; then
        echo "🌐 Remote target: ${TARGET_USER}@${TARGET_HOST}"
        echo "👉 You will be prompted for: ${ASK_SSH:+-k SSH password }${ASK_BECOME:+-K sudo password }"
    else
        echo "🌐 Remote target: ${TARGET_USER}@${TARGET_HOST} (unattended, credentials from .env)..."
    fi
    echo ""
    run_args=( playbook.yml -i "${TARGET_HOST}," -u "${TARGET_USER}" -e "$EXTRA_VARS" )
    [[ -n "$SECRETS_ARG" ]] && run_args+=( $SECRETS_ARG )
    [[ -n "$ASK_SSH" ]]    && run_args+=( "$ASK_SSH" )
    [[ -n "$ASK_BECOME" ]] && run_args+=( "$ASK_BECOME" )
    [[ ${#ARGS[@]} -gt 0 ]] && run_args+=( "${ARGS[@]}" )
    docker run --rm -it \
        --name pai-stack-ansible-runner \
        -v "${SCRIPT_DIR}:/workspace" \
        "${IMAGE_NAME}" \
        "${run_args[@]}"
fi
