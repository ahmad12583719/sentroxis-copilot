#!/usr/bin/env bash
#
# Sentroxis Wazuh all-in-one installer.
#
# Deploys the primary-node Wazuh stack required by Sentroxis:
#   - Wazuh manager, indexer, and dashboard via Docker Compose
#   - Wazuh 4.7.x (default: 4.7.5, override with WAZUH_VERSION=v4.7.x)
#   - Self-signed TLS certificates for private-LAN/MVP use
#   - OpenSearch JVM capped at 2 GiB (default 1 GiB)
#   - Non-default admin, dashboard, and Wazuh API credentials
#
# This script does not enroll endpoints, alter firewall rules, enable active
# response, or publish secrets. Run it on the Sentroxis primary Linux node.
#
# Usage:
#   sudo ./wazuh_installation.sh
#   sudo ./wazuh_installation.sh --dry-run
#
set -Eeuo pipefail
IFS=$'\n\t'

readonly SCRIPT_NAME="$(basename "$0")"
readonly DEFAULT_VERSION="v4.7.5"
readonly DEFAULT_HOME="/opt/sentroxis/wazuh"
readonly OFFICIAL_REPO="https://github.com/wazuh/wazuh-docker.git"
readonly MIN_PASSWORD_LENGTH=20

WAZUH_VERSION="${WAZUH_VERSION:-$DEFAULT_VERSION}"
WAZUH_HOME="${WAZUH_HOME:-$DEFAULT_HOME}"
WAZUH_API_BIND_ADDRESS="${WAZUH_API_BIND_ADDRESS:-127.0.0.1}"
WAZUH_OPENSEARCH_JAVA_OPTS="${WAZUH_OPENSEARCH_JAVA_OPTS:--Xms1g -Xmx1g}"
DRY_RUN=0

log() { printf '[wazuh-install] %s\n' "$*"; }
warn() { printf '[wazuh-install] WARNING: %s\n' "$*" >&2; }
fatal() { printf '[wazuh-install] ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Install and configure the Sentroxis primary-node Wazuh stack.

Options:
  --dry-run  Validate host prerequisites and print planned actions only.
  -h, --help Show this help.

Environment overrides:
  WAZUH_VERSION                 Wazuh Docker tag; defaults to v4.7.5.
  WAZUH_HOME                    Installation directory; defaults to /opt/sentroxis/wazuh.
  WAZUH_API_BIND_ADDRESS        Host bind address for API port 55000; defaults to 127.0.0.1.
  WAZUH_OPENSEARCH_JAVA_OPTS    JVM options; must remain at or below 2 GiB.
  WAZUH_INDEXER_PASSWORD        Non-default indexer admin password.
  WAZUH_DASHBOARD_PASSWORD      Non-default dashboard/kibanaserver password.
  WAZUH_API_PASSWORD            Non-default Wazuh API password.

Passwords may be supplied through the environment for automation, but protected
interactive prompts are preferred. Never put credentials in source control.
EOF
}

while (($#)); do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage; exit 0 ;;
    *) fatal "Unknown argument: $1" ;;
  esac
  shift
done

[[ $EUID -eq 0 ]] || fatal "Run as root (for example: sudo $SCRIPT_NAME)."

if [[ ! "$WAZUH_VERSION" =~ ^v4\.7\.[0-9]+$ ]]; then
  fatal "WAZUH_VERSION must be a Wazuh 4.7.x tag (received: $WAZUH_VERSION)."
fi
if [[ ! "$WAZUH_API_BIND_ADDRESS" =~ ^(127\.0\.0\.1|([0-9]{1,3}\.){3}[0-9]{1,3})$ ]]; then
  fatal "WAZUH_API_BIND_ADDRESS must be localhost or an IPv4 address."
fi
if [[ "$WAZUH_OPENSEARCH_JAVA_OPTS" =~ -Xms([0-9]+)([mg])\ -Xmx([0-9]+)([mg]) ]]; then
  jvm_min="${BASH_REMATCH[1]}${BASH_REMATCH[2]}"
  jvm_max="${BASH_REMATCH[3]}${BASH_REMATCH[4]}"
else
  fatal "WAZUH_OPENSEARCH_JAVA_OPTS must look like '-Xms1g -Xmx1g'."
fi

command_exists() { command -v "$1" >/dev/null 2>&1; }

check_os() {
  [[ -r /etc/os-release ]] || fatal "Cannot identify the operating system."
  # shellcheck disable=SC1091
  . /etc/os-release
  case "${ID:-}" in
    ubuntu|debian|fedora|rhel|rocky|almalinux) ;;
    *) fatal "Supported hosts are Ubuntu/Debian or Fedora/RHEL-family Linux; found ${ID:-unknown}." ;;
  esac
  case "${ARCH:-$(uname -m)}" in
    x86_64|amd64) ;;
    *) fatal "The Sentroxis SRS specifies an x86-64 primary node; found $(uname -m)." ;;
  esac
}

check_resources() {
  local mem_gib disk_gib
  mem_gib="$(awk '/MemTotal:/ {printf "%d", $2/1024/1024}' /proc/meminfo)"
  disk_gib="$(df -Pk / 2>/dev/null | awk 'NR==2 {printf "%d", $4/1024/1024}')"
  if (( mem_gib < 12 )); then
    (( DRY_RUN )) && warn "SRS preflight: at least 12 GiB RAM is recommended; detected ${mem_gib} GiB." || fatal "At least 12 GiB RAM is recommended for the SRS primary node; detected ${mem_gib} GiB."
  fi
  if [[ -z "$disk_gib" || "$disk_gib" -lt 80 ]]; then
    (( DRY_RUN )) && warn "SRS preflight: at least 80 GiB free disk space is recommended; detected ${disk_gib:-unknown} GiB." || fatal "At least 80 GiB free disk space is required under $WAZUH_HOME."
  fi
}

install_docker_if_needed() {
  if command_exists docker && docker compose version >/dev/null 2>&1; then
    log "Docker Engine and Compose plugin are already available."
    return
  fi
  (( DRY_RUN )) && { log "DRY-RUN: would install Docker Engine and Docker Compose plugin."; return; }
  check_os
  log "Installing Docker Engine and the Compose plugin from the host distribution."
  case "$ID" in
    ubuntu|debian)
      apt-get update
      DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io docker-compose-plugin git openssl curl ca-certificates
      ;;
    fedora|rhel|rocky|almalinux)
      if command_exists dnf; then dnf install -y docker docker-compose-plugin git openssl curl ca-certificates; else yum install -y docker git openssl curl ca-certificates; fi
      systemctl enable --now docker
      ;;
  esac
  systemctl enable --now docker
  docker compose version >/dev/null 2>&1 || fatal "Docker Compose V2 is unavailable after installation."
}

prompt_secret() {
  local var_name="$1" label="$2" value confirm
  if [[ -n "${!var_name:-}" ]]; then value="${!var_name}"; else
    while :; do
      read -r -s -p "$label: " value; printf '\n'
      read -r -s -p "Confirm $label: " confirm; printf '\n'
      [[ "$value" == "$confirm" ]] || { warn "Passwords did not match."; continue; }
      break
    done
    printf -v "$var_name" '%s' "$value"
  fi
  (( ${#value} >= MIN_PASSWORD_LENGTH )) || fatal "$var_name must contain at least $MIN_PASSWORD_LENGTH characters."
  [[ "$value" =~ ^[A-Za-z0-9._@%+=:,/-]+$ ]] || fatal "$var_name contains unsupported characters; use letters, digits, and . _ @ % + = : , / -."
}

prepare_stack() {
  if (( DRY_RUN )); then
    log "DRY-RUN: would clone or update the official Wazuh Docker repository at $WAZUH_HOME."
    return
  fi
  mkdir -p "$WAZUH_HOME"
  if [[ -d "$WAZUH_HOME/.git" ]]; then
    git -C "$WAZUH_HOME" remote get-url origin | grep -qx "$OFFICIAL_REPO" || fatal "$WAZUH_HOME is not the official Wazuh Docker repository."
    git -C "$WAZUH_HOME" fetch --tags --depth 1 origin "$WAZUH_VERSION"
    git -C "$WAZUH_HOME" checkout --detach "$WAZUH_VERSION"
  else
    [[ -z "$(find "$WAZUH_HOME" -mindepth 1 -maxdepth 1 -print -quit)" ]] || fatal "$WAZUH_HOME is not empty and is not a Wazuh checkout."
    git clone --depth 1 --branch "$WAZUH_VERSION" "$OFFICIAL_REPO" "$WAZUH_HOME"
  fi
  [[ -f "$WAZUH_HOME/single-node/docker-compose.yml" ]] || fatal "Pinned Wazuh release lacks the expected single-node Compose files."
  cd "$WAZUH_HOME/single-node"
}

generate_bcrypt_hash() {
  local password="$1"
  # The official Wazuh indexer image ships the supported bcrypt utility. The
  # password is passed through stdin rather than exposed in process arguments.
  printf '%s\n' "$password" | docker run --rm -i --entrypoint bash "wazuh/wazuh-indexer:${WAZUH_VERSION#v}" -c 'IFS= read -r password; bash plugins/opensearch-security/tools/hash.sh -p "$password"' | tail -n 1
}

configure_credentials() {
  local compose="docker-compose.yml" users="config/wazuh_indexer/internal_users.yml" admin_hash dashboard_hash
  prompt_secret WAZUH_INDEXER_PASSWORD "Wazuh indexer admin password"
  prompt_secret WAZUH_DASHBOARD_PASSWORD "Wazuh dashboard password"
  prompt_secret WAZUH_API_PASSWORD "Wazuh Server API password"

  if (( DRY_RUN )); then log "DRY-RUN: would apply protected, non-default credentials to Compose and indexer users."; return; fi
  umask 077
  cp -p "$compose" "$compose.sentroxis-backup"
  cp -p "$users" "$users.sentroxis-backup"

  admin_hash="$(generate_bcrypt_hash "$WAZUH_INDEXER_PASSWORD")"
  dashboard_hash="$(generate_bcrypt_hash "$WAZUH_DASHBOARD_PASSWORD")"
  [[ "$admin_hash" != "*" && "$dashboard_hash" != "*" ]] || fatal "Could not generate bcrypt password hashes."

  ADMIN_HASH="$admin_hash" DASHBOARD_HASH="$dashboard_hash" python3 - "$users" <<'PY'
import os, pathlib, re, sys
path = pathlib.Path(sys.argv[1])
text = path.read_text()
text = re.sub(r'(?ms)(^admin:\n\s+hash: )"[^"]+"', lambda m: m.group(1) + '"' + os.environ['ADMIN_HASH'] + '"', text, count=1)
text = re.sub(r'(?ms)(^kibanaserver:\n\s+hash: )"[^"]+"', lambda m: m.group(1) + '"' + os.environ['DASHBOARD_HASH'] + '"', text, count=1)
path.write_text(text)
PY

  COMPOSE_FILE="$compose" INDEXER_PASSWORD="$WAZUH_INDEXER_PASSWORD" API_PASSWORD="$WAZUH_API_PASSWORD" DASHBOARD_PASSWORD="$WAZUH_DASHBOARD_PASSWORD" API_BIND_ADDRESS="$WAZUH_API_BIND_ADDRESS" JVM_OPTS="$WAZUH_OPENSEARCH_JAVA_OPTS" python3 - <<'PY'
import os, pathlib
path = pathlib.Path(os.environ['COMPOSE_FILE'])
text = path.read_text()
replacements = {
    'INDEXER_PASSWORD=SecretPassword': 'INDEXER_PASSWORD=' + os.environ['INDEXER_PASSWORD'],
    'API_PASSWORD=MyS3cr37P450r.*-': 'API_PASSWORD=' + os.environ['API_PASSWORD'],
    'DASHBOARD_PASSWORD=kibanaserver': 'DASHBOARD_PASSWORD=' + os.environ['DASHBOARD_PASSWORD'],
    '- "55000:55000"': '- "' + os.environ['API_BIND_ADDRESS'] + ':55000:55000"',
    'OPENSEARCH_JAVA_OPTS=-Xms512m -Xmx512m': 'OPENSEARCH_JAVA_OPTS=' + os.environ['JVM_OPTS'],
}
for old, new in replacements.items():
    text = text.replace(old, new)
path.write_text(text)
PY
  chmod 600 "$users" "$compose.sentroxis-backup"
}

generate_certificates() {
  [[ -d config/wazuh_indexer_ssl_certs ]] && [[ -f config/wazuh_indexer_ssl_certs/root-ca.pem ]] && { log "Wazuh TLS certificates already exist; preserving them."; return; }
  (( DRY_RUN )) && { log "DRY-RUN: would generate Wazuh self-signed certificates with the official generator."; return; }
  docker compose -f generate-indexer-certs.yml run --rm generator
}

validate_stack() {
  (( DRY_RUN )) && { log "DRY-RUN: would run docker compose config and health checks."; return; }
  docker compose config >/dev/null || fatal "Generated Compose configuration is invalid."
  docker compose up -d
  log "Waiting for Wazuh containers to initialize (up to 180 seconds)."
  local i
  for i in {1..36}; do
    if docker compose ps --format json 2>/dev/null | grep -q 'running'; then
      if curl --silent --show-error --insecure --connect-timeout 3 "https://127.0.0.1:55000/" >/dev/null 2>&1; then break; fi
    fi
    sleep 5
  done
  docker compose ps
  curl --silent --show-error --insecure --fail --connect-timeout 5 "https://127.0.0.1:55000/" >/dev/null || warn "Wazuh API is not responding yet; inspect: docker compose logs --tail=200 wazuh.manager"
  log "Dashboard: https://$(hostname -I | awk '{print $1}')/ (self-signed certificate warning is expected for MVP/private-LAN use)."
  log "API bind address: $WAZUH_API_BIND_ADDRESS:55000. Keep this port private and place it behind a firewall or private network for the secondary node."
}

main() {
  check_os
  check_resources
  if (( DRY_RUN )); then
    log "DRY-RUN: version=$WAZUH_VERSION home=$WAZUH_HOME api_bind=$WAZUH_API_BIND_ADDRESS JVM='$WAZUH_OPENSEARCH_JAVA_OPTS'"
  fi
  install_docker_if_needed
  prepare_stack
  configure_credentials
  generate_certificates
  validate_stack
  log "Wazuh installation completed. No active response or endpoint enrollment was enabled."
}

main "$@"
