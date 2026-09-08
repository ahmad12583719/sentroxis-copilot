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
# By default, the Wazuh deployment is stored in .wazuh beside this script, so
# the project can be cloned and run from any directory.
#
# Usage:
#   sudo ./wazuh_installation.sh
#   sudo ./wazuh_installation.sh --dry-run
#
set -Eeuo pipefail
IFS=$'\n\t'

readonly SCRIPT_NAME="$(basename "$0")"
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly DEFAULT_VERSION="v4.7.5"
readonly DEFAULT_HOME="${SCRIPT_DIR}/.wazuh"
readonly OFFICIAL_REPO="https://github.com/wazuh/wazuh-docker.git"
readonly MIN_PASSWORD_LENGTH=20

WAZUH_VERSION="${WAZUH_VERSION:-$DEFAULT_VERSION}"
WAZUH_HOME="${WAZUH_HOME:-$DEFAULT_HOME}"
WAZUH_API_BIND_ADDRESS="${WAZUH_API_BIND_ADDRESS:-127.0.0.1}"
WAZUH_OPENSEARCH_JAVA_OPTS="${WAZUH_OPENSEARCH_JAVA_OPTS:--Xms1g -Xmx1g}"
HOST_OS="$(uname -s)"
HOST_ARCH="$(uname -m)"
WSL2_HOST=0
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
  WAZUH_HOME                    Installation directory; defaults to .wazuh beside this script.
  WAZUH_API_BIND_ADDRESS        Host bind address for API port 55000; defaults to 127.0.0.1.
  WAZUH_OPENSEARCH_JAVA_OPTS    JVM options; must remain at or below 2 GiB.
  WAZUH_INDEXER_PASSWORD        Non-default indexer admin password.
  WAZUH_DASHBOARD_PASSWORD      Non-default dashboard/kibanaserver password.
  WAZUH_API_PASSWORD            Non-default Wazuh API password.

Supported host execution:
  Linux AMD64/x86-64 with Docker Engine.
  Windows AMD64/x86-64 through WSL 2 with Docker Desktop WSL integration.
  macOS, ordinary Windows PowerShell, Git Bash, ARM64, and unsupported Linux
  distributions are rejected clearly rather than partially installing Wazuh.

Passwords may be supplied through the environment for automation, but protected
interactive prompts are preferred. Passwords must be printable, contain no whitespace,
and include uppercase, lowercase, a number, and a special character. Never put
credentials in source control.
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
  case "$HOST_OS" in
    Linux) ;;
    Darwin)
      fatal "macOS is not a supported host for this Bash/Docker Wazuh installer. Use a supported Linux VM or Windows WSL 2 with Docker Desktop."
      ;;
    MINGW*|MSYS*|CYGWIN*)
      fatal "Run this installer inside a WSL 2 Linux distribution with Docker Desktop WSL integration enabled; do not run it from Git Bash or PowerShell."
      ;;
    *)
      fatal "Unsupported host kernel: $HOST_OS. Use Linux or Windows through WSL 2."
      ;;
  esac

  [[ -r /etc/os-release ]] || fatal "Cannot identify the Linux distribution. Run inside a supported Linux system or WSL 2 distribution."
  # shellcheck disable=SC1091
  . /etc/os-release
  case "${ID:-}" in
    ubuntu|debian|fedora|rhel|rocky|almalinux|amzn|centos|ol) ;;
    *) fatal "Unsupported Linux distribution: ${ID:-unknown}. Use Ubuntu, Debian, Fedora, RHEL/Rocky/AlmaLinux, Amazon Linux, or CentOS Stream." ;;
  esac

  case "$HOST_ARCH" in
    x86_64|amd64) ;;
    aarch64|arm64)
      fatal "This pinned Wazuh 4.7.5 Sentroxis deployment targets AMD64/x86-64. ARM64 requires matching Wazuh images and is not enabled by this pinned stack."
      ;;
    *) fatal "Unsupported CPU architecture: $HOST_ARCH. Use a 64-bit AMD64/x86-64 host." ;;
  esac

  if [[ -n "${WSL_DISTRO_NAME:-}" || -n "${WSL_INTEROP:-}" || -f /proc/sys/fs/binfmt_misc/WSLInterop ]]; then
    WSL2_HOST=1
  fi
}

check_resources() {
  local mem_gib disk_gib cpu_count map_count
  mem_gib="$(awk '/MemTotal:/ {printf "%d", $2/1024/1024}' /proc/meminfo)"
  disk_gib="$(df -Pk / 2>/dev/null | awk 'NR==2 {printf "%d", $4/1024/1024}')"
  cpu_count="$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null || printf '0')"
  map_count="$(cat /proc/sys/vm/max_map_count 2>/dev/null || printf '0')"
  if (( cpu_count < 4 )); then
    (( DRY_RUN )) && warn "Wazuh Docker recommends at least 4 CPU cores; detected ${cpu_count}." || fatal "At least 4 CPU cores are required for this Wazuh Docker deployment; detected ${cpu_count}."
  fi
  if (( mem_gib < 12 )); then
    (( DRY_RUN )) && warn "SRS preflight: at least 12 GiB RAM is recommended; detected ${mem_gib} GiB." || fatal "At least 12 GiB RAM is recommended for the SRS primary node; detected ${mem_gib} GiB."
  fi
  if [[ -z "$disk_gib" || "$disk_gib" -lt 80 ]]; then
    (( DRY_RUN )) && warn "SRS preflight: at least 80 GiB free disk space is recommended; detected ${disk_gib:-unknown} GiB." || fatal "At least 80 GiB free disk space is required under $WAZUH_HOME."
  fi
  if [[ "$map_count" =~ ^[0-9]+$ ]] && (( map_count < 262144 )); then
    if (( DRY_RUN )); then
      warn "Wazuh Indexer requires vm.max_map_count >= 262144; detected ${map_count}."
    elif command_exists sysctl && sysctl -w vm.max_map_count=262144 >/dev/null; then
      log "Set vm.max_map_count to 262144 for the Wazuh Indexer."
      if [[ -d /etc/sysctl.d ]]; then printf 'vm.max_map_count=262144\n' > /etc/sysctl.d/99-sentroxis-wazuh.conf; fi
    else
      fatal "vm.max_map_count is ${map_count}; set it to 262144, then rerun the installer. On Windows, run 'wsl -d <distribution> -- sysctl -w vm.max_map_count=262144' inside WSL 2."
    fi
  fi
}

install_docker_if_needed() {
  if command_exists docker && docker compose version >/dev/null 2>&1; then
    log "Docker Engine and Compose plugin are already available."
    if (( WSL2_HOST )); then log "Detected WSL 2; using Docker Desktop through WSL integration."; fi
    return
  fi
  (( DRY_RUN )) && { log "DRY-RUN: would install Docker Engine and Docker Compose plugin."; return; }
  if (( WSL2_HOST )); then
    fatal "Docker is unavailable inside WSL 2. Install Docker Desktop on Windows, enable WSL 2 integration for this distribution, then rerun this installer."
  fi
  check_os
  log "Installing Docker Engine and the Compose plugin from the host distribution."
  case "$ID" in
    ubuntu|debian)
      apt-get update
      DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io docker-compose-plugin git openssl curl ca-certificates python3-bcrypt
      ;;
    fedora|rhel|rocky|almalinux)
      if command_exists dnf; then dnf install -y docker docker-compose-plugin git openssl curl ca-certificates python3-bcrypt; else yum install -y docker git openssl curl ca-certificates python3-bcrypt; fi
      systemctl enable --now docker
      ;;
  esac
  systemctl enable --now docker
  docker compose version >/dev/null 2>&1 || fatal "Docker Compose V2 is unavailable after installation."
}

ensure_bcrypt() {
  if python3 -c 'import bcrypt' >/dev/null 2>&1; then return; fi
  (( DRY_RUN )) && { log "DRY-RUN: would install the python3-bcrypt package."; return; }
  log "Installing the host bcrypt library required to secure Wazuh credentials."
  case "$ID" in
    ubuntu|debian) apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y python3-bcrypt ;;
    fedora|rhel|rocky|almalinux) if command_exists dnf; then dnf install -y python3-bcrypt; else yum install -y python3-bcrypt; fi ;;
  esac
  python3 -c 'import bcrypt' >/dev/null 2>&1 || fatal "The Python bcrypt library is unavailable after installation."
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
  [[ "$value" =~ ^[[:graph:]]+$ ]] || fatal "$var_name must contain printable non-whitespace characters only."
  [[ "$value" =~ [A-Z] && "$value" =~ [a-z] && "$value" =~ [0-9] && "$value" =~ [^[:alnum:]] ]] || fatal "$var_name must include uppercase, lowercase, a number, and a special character."
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
  # Previous failed runs may have left malformed customized files behind. The
  # installer owns these four files, so restore only them from the pinned tag;
  # certificates, volumes, and other operator files remain untouched.
  git -C "$WAZUH_HOME" checkout -- single-node/docker-compose.yml single-node/config/wazuh_indexer/internal_users.yml single-node/config/wazuh_dashboard/wazuh.yml single-node/config/wazuh_dashboard/opensearch_dashboards.yml
  # The custom image owns /etc/filebeat; the upstream named volume would hide
  # that baked layer and reintroduce stale, uncustomized configuration.
  sed -i '\#filebeat_etc:/etc/filebeat#d' "$WAZUH_HOME/single-node/docker-compose.yml"
  patch_filebeat_templates
  cd "$WAZUH_HOME/single-node"
}

patch_filebeat_template() {
  local file="$1"
  [[ -f "$file" ]] || fatal "Filebeat template is missing: $file"
  if ! grep -q '^# SENTROXIS_CUSTOM_ARCHIVE_INPUT$' "$file"; then
    cat >> "$file" <<'EOF'

# SENTROXIS_CUSTOM_ARCHIVE_INPUT
filebeat.inputs:
  - type: log
    enabled: true
    paths:
      - /var/ossec/logs/archives/archives.json
    tags: ["wazuh-archives"]
EOF
  fi
  if ! grep -q '^# SENTROXIS_FILEBEAT_ARCHIVE_ROUTING$' "$file"; then
    sed -i '/^output\.\(elasticsearch\|opensearch\):[[:space:]]*$/a\
  # SENTROXIS_FILEBEAT_ARCHIVE_ROUTING\
  indices:\
    - index: "wazuh-archives-%{+yyyy.MM.dd}"\
      when.contains:\
        tags: "wazuh-archives"\
    - index: "wazuh-alerts-%{+yyyy.MM.dd}"' "$file"
  fi
  grep -q '/var/ossec/logs/archives/archives.json' "$file" || fatal "Archive input was not added to $file"
  grep -q 'wazuh-archives-%{+yyyy.MM.dd}' "$file" || fatal "Archive routing was not added to $file"
  grep -q 'wazuh-alerts-%{+yyyy.MM.dd}' "$file" || fatal "Alert routing was not added to $file"
}

patch_filebeat_templates() {
  local build_template="${WAZUH_HOME}/build-docker-images/wazuh-manager/config/filebeat.yml"
  local single_node_template="${WAZUH_HOME}/single-node/config/wazuh_cluster/filebeat.yml"
  mkdir -p "$(dirname "$build_template")"
  if [[ ! -f "$build_template" && -f "$single_node_template" ]]; then
    cp -p "$single_node_template" "$build_template"
  fi
  [[ -f "$build_template" ]] || fatal "Could not provision the Filebeat build template."
  mkdir -p "$(dirname "$single_node_template")"
  [[ -f "$single_node_template" ]] || cp -p "$build_template" "$single_node_template"
  patch_filebeat_template "$single_node_template"
  patch_filebeat_template "$build_template"
  cat > "${WAZUH_HOME}/build-docker-images/wazuh-manager/Dockerfile.sentroxis" <<'DOCKERFILE'
FROM wazuh/wazuh-manager:4.7.5
COPY config/filebeat.yml /etc/filebeat/filebeat.yml
RUN chmod go-w /etc/filebeat/filebeat.yml
DOCKERFILE
  # The upstream wazuh-indexer image lacks curl, so the authenticated HTTPS
  # cluster-health healthcheck (NFR-22) cannot run in it. Provision a custom
  # image with curl baked in so Docker can probe /_cluster/health with --insecure
  # and basic auth during startup.
  cat > "${WAZUH_HOME}/build-docker-images/wazuh-indexer/Dockerfile.sentroxis" <<'DOCKERFILE'
FROM wazuh/wazuh-indexer:4.7.5
USER root
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*
USER wazuh-indexer
DOCKERFILE
  local indexer_compose_dir="${WAZUH_HOME}/single-node/build-docker-images/wazuh-indexer"
  mkdir -p "$indexer_compose_dir"
  cp -p "${WAZUH_HOME}/build-docker-images/wazuh-indexer/Dockerfile.sentroxis" "$indexer_compose_dir/Dockerfile.sentroxis"
  # The upstream wazuh-dashboard image likewise lacks curl; bake it in so the
  # HTTPS dashboard healthcheck runs instead of failing with "curl: not found".
  cat > "${WAZUH_HOME}/build-docker-images/wazuh-dashboard/Dockerfile.sentroxis" <<'DOCKERFILE'
FROM wazuh/wazuh-dashboard:4.7.5
USER root
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*
USER wazuh-dashboard
DOCKERFILE
  local dashboard_compose_dir="${WAZUH_HOME}/single-node/build-docker-images/wazuh-dashboard"
  mkdir -p "$dashboard_compose_dir"
  cp -p "${WAZUH_HOME}/build-docker-images/wazuh-dashboard/Dockerfile.sentroxis" "$dashboard_compose_dir/Dockerfile.sentroxis"
  local manager_compose_dir="${WAZUH_HOME}/single-node/build-docker-images/wazuh-manager"
  mkdir -p "$manager_compose_dir"
  if [[ ! -f "$manager_compose_dir/Dockerfile.sentroxis" ]]; then
    cp -p "${WAZUH_HOME}/build-docker-images/wazuh-manager/Dockerfile.sentroxis" "$manager_compose_dir/Dockerfile.sentroxis"
  fi
  if [[ -f "${WAZUH_HOME}/build-docker-images/wazuh-manager/config/filebeat.yml" && ! -f "$manager_compose_dir/config/filebeat.yml" ]]; then
    mkdir -p "$manager_compose_dir/config"
    cp -p "${WAZUH_HOME}/build-docker-images/wazuh-manager/config/filebeat.yml" "$manager_compose_dir/config/filebeat.yml"
  fi
}

generate_bcrypt_hash() {
  local password="$1"
  # bcrypt is generated locally; the password is supplied through stdin and
  # never placed in a command-line argument or stored in a temporary file.
  # Python bcrypt emits $2b$ hashes; Wazuh/OpenSearch 2.8 expects the
  # $2a$/$2y$ variants used by the official internal_users.yml template.
  printf '%s' "$password" | python3 -c 'import bcrypt,sys; print(bcrypt.hashpw(sys.stdin.buffer.read(), bcrypt.gensalt()).decode().replace("$2b$", "$2y$", 1))'
}

configure_credentials() {
  local compose="docker-compose.yml" users="config/wazuh_indexer/internal_users.yml" dashboard_api="config/wazuh_dashboard/wazuh.yml" admin_hash dashboard_hash
  prompt_secret WAZUH_INDEXER_PASSWORD "Wazuh indexer admin password"
  prompt_secret WAZUH_DASHBOARD_PASSWORD "Wazuh dashboard password"
  prompt_secret WAZUH_API_PASSWORD "Wazuh Server API password"

  if (( DRY_RUN )); then log "DRY-RUN: would apply protected, non-default credentials to Compose and indexer users."; return; fi
  umask 077
  cp -p "$compose" "$compose.sentroxis-backup"
  cp -p "$users" "$users.sentroxis-backup"
  cp -p "$dashboard_api" "$dashboard_api.sentroxis-backup"

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

  API_PASSWORD="$WAZUH_API_PASSWORD" python3 - "$dashboard_api" <<'PY'
import json, os, pathlib, re, sys
path = pathlib.Path(sys.argv[1])
text = path.read_text()
updated = re.sub(r'(?m)^(\s+password:\s*)["\'][^"\']*["\']\s*$', lambda m: m.group(1) + json.dumps(os.environ['API_PASSWORD']), text, count=1)
if updated == text:
    raise SystemExit("Could not locate Wazuh dashboard API password in wazuh.yml")
path.write_text(updated)
PY

  COMPOSE_FILE="$compose" INDEXER_PASSWORD="$WAZUH_INDEXER_PASSWORD" API_PASSWORD="$WAZUH_API_PASSWORD" DASHBOARD_PASSWORD="$WAZUH_DASHBOARD_PASSWORD" API_BIND_ADDRESS="$WAZUH_API_BIND_ADDRESS" JVM_OPTS="$WAZUH_OPENSEARCH_JAVA_OPTS" python3 - <<'PY'
import json, os, pathlib, re
path = pathlib.Path(os.environ['COMPOSE_FILE'])
lines = path.read_text().splitlines(keepends=True)
output = []
skip_dashboard_ports = False
current_service = None
for line in lines:
    indent = re.match(r'^(\s*)', line).group(1)
    service_match = re.match(r'^  ([A-Za-z0-9_.-]+):\s*$', line)
    if service_match:
        current_service = service_match.group(1)
    if current_service == 'wazuh.dashboard' and re.match(r'^    ports:\s*$', line):
        skip_dashboard_ports = True
        continue
    if skip_dashboard_ports:
        if re.match(r'^      -\s+', line):
            continue
        skip_dashboard_ports = False
    if re.match(r'^\s*-\s*["\']?(INDEXER_PASSWORD|API_PASSWORD|DASHBOARD_PASSWORD)(?::|=)', line):
        key = re.search(r'(INDEXER_PASSWORD|API_PASSWORD|DASHBOARD_PASSWORD)', line).group(1)
        output.append(indent + '- ' + json.dumps(key + '=' + os.environ[key]) + '\n')
    elif re.match(r'^\s*-\s*["\']?OPENSEARCH_JAVA_OPTS(?::|=)', line):
        output.append(indent + '- ' + json.dumps('OPENSEARCH_JAVA_OPTS=' + os.environ['JVM_OPTS']) + '\n')
    elif '55000:55000' in line and re.match(r'^\s*-\s*["\']?[^\n]*55000:55000', line):
        output.append(indent + '- ' + json.dumps(os.environ['API_BIND_ADDRESS'] + ':55000:55000') + '\n')
    else:
        output.append(line)
path.write_text(''.join(output))
PY
  # The indexer container runs as UID 1000 and must read this bind-mounted
  # file during securityadmin. It contains bcrypt hashes, not plaintext secrets.
  chmod 644 "$users" "$dashboard_api"
  chmod 600 "$compose.sentroxis-backup" "$users.sentroxis-backup" "$dashboard_api.sentroxis-backup"

  local runtime_env owner
  runtime_env="${SCRIPT_DIR}/runtime/wazuh-api.env"
  owner="${SUDO_USER:-root}"
  mkdir -p "${SCRIPT_DIR}/runtime"
  cat > "$runtime_env" <<EOF
WAZUH_MANAGER_API_URL=https://127.0.0.1:55000
WAZUH_INDEXER_URL=https://127.0.0.1:9200
WAZUH_API_USER=wazuh-wui
WAZUH_API_PASSWORD=$(printf '%q' "$WAZUH_API_PASSWORD")
WAZUH_DASHBOARD_PASSWORD=$(printf '%q' "$WAZUH_DASHBOARD_PASSWORD")
WAZUH_INDEXER_USER=admin
WAZUH_INDEXER_PASSWORD=$(printf '%q' "$WAZUH_INDEXER_PASSWORD")
EOF
  chown "$owner:$owner" "$runtime_env" 2>/dev/null || true
  chmod 600 "$runtime_env"
}

configure_local_proxy() {
  (( DRY_RUN )) && { log "DRY-RUN: would configure the local HTTPS proxy for the embedded Wazuh dashboard."; return; }
  cat > docker-compose.sentroxis.yml <<'YAML'
services:
  wazuh.indexer:
    build:
      context: ./build-docker-images/wazuh-indexer
      dockerfile: Dockerfile.sentroxis
    image: sentroxis/wazuh-indexer:4.7.5-healthcheck
    ports:
      - "9200:9200"
    healthcheck:
      test: ["CMD-SHELL", "curl -kfsS --max-time 10 -u 'admin:${WAZUH_INDEXER_PASSWORD}' https://127.0.0.1:9200/_cluster/health >/dev/null || exit 1"]
      interval: 10s
      timeout: 8s
      retries: 30
      start_period: 30s
  wazuh.manager:
    build:
      context: ./build-docker-images/wazuh-manager
      dockerfile: Dockerfile.sentroxis
    image: sentroxis/wazuh-manager:4.7.5-archives
    depends_on:
      wazuh.indexer:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "code=$$(curl -ksS --max-time 5 -o /dev/null -w '%{http_code}' https://127.0.0.1:55000/ || true); test \"$$code\" = 401"]
      interval: 10s
      timeout: 8s
      retries: 30
      start_period: 30s
  wazuh.dashboard:
    build:
      context: ./build-docker-images/wazuh-dashboard
      dockerfile: Dockerfile.sentroxis
    image: sentroxis/wazuh-dashboard:4.7.5-healthcheck
    expose:
      - "5601"
    depends_on:
      wazuh.indexer:
        condition: service_healthy
      wazuh.manager:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "curl -kfsS --max-time 5 https://127.0.0.1:5601/ >/dev/null || exit 1"]
      interval: 10s
      timeout: 8s
      retries: 30
      start_period: 30s
  wazuh.dashboard_proxy:
    image: nginx:1.27-alpine
    hostname: wazuh.dashboard_proxy
    restart: always
    ports:
      - "443:443"
    volumes:
      - ./config/wazuh_dashboard/sentroxis-nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - ./config/wazuh_indexer_ssl_certs/wazuh.dashboard.pem:/etc/nginx/certs/wazuh-dashboard.pem:ro
      - ./config/wazuh_indexer_ssl_certs/wazuh.dashboard-key.pem:/etc/nginx/certs/wazuh-dashboard-key.pem:ro
    depends_on:
      wazuh.dashboard:
        condition: service_healthy
YAML
  sed -i.bak 's#<logall_json>no</logall_json>#<logall_json>yes</logall_json>#' config/wazuh_cluster/wazuh_manager.conf
  cat > config/wazuh_dashboard/sentroxis-nginx.conf <<'NGINX'
server {
    listen 443 ssl;
    server_name _;

    ssl_certificate /etc/nginx/certs/wazuh-dashboard.pem;
    ssl_certificate_key /etc/nginx/certs/wazuh-dashboard-key.pem;

    # The upstream Wazuh dashboard uses SAMEORIGIN, which blocks the local
    # Sentroxis iframe because the development frontend uses port 5173.
    # This scoped local proxy permits only local Sentroxis origins.
    proxy_hide_header X-Frame-Options;
    proxy_hide_header Content-Security-Policy;
    add_header Content-Security-Policy "frame-ancestors 'self'" always;

    location /wazuh/ {
        proxy_pass https://wazuh.dashboard:5601/;
        proxy_ssl_verify off;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-Prefix /wazuh;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_redirect https://wazuh.dashboard:5601/ /wazuh/;
    }

    location / {
        proxy_pass https://wazuh.dashboard:5601;
        proxy_ssl_verify off;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_cookie_flags ~ secure samesite=none;
    }
}
NGINX
  # Write .env so Docker Compose can interpolate ${WAZUH_INDEXER_PASSWORD} in
  # the healthcheck CMD-SHELL of docker-compose.sentroxis.yml.  Without this,
  # the indexer healthcheck probes without credentials and the container is
  # marked unhealthy, which blocks startup of all dependent services.
  umask 077
  printf 'WAZUH_INDEXER_PASSWORD=%s\n' "$WAZUH_INDEXER_PASSWORD" > .env
}
repair_wazuh_ownership() {
  local owner="${SUDO_USER:-${USER:-}}" group
  [[ -n "$owner" && "$owner" != root ]] || return 0
  group="$(id -gn "$owner" 2>/dev/null || printf '%s' "$owner")"
  chown -R "$owner:$group" "$WAZUH_HOME" 2>/dev/null || warn "Could not fully repair ownership under $WAZUH_HOME."
}

compose() {
  docker compose -f docker-compose.yml -f docker-compose.sentroxis.yml "$@"
}

generate_certificates() {
  [[ -d config/wazuh_indexer_ssl_certs ]] && [[ -f config/wazuh_indexer_ssl_certs/root-ca.pem ]] && { log "Wazuh TLS certificates already exist; preserving them."; return; }
  (( DRY_RUN )) && { log "DRY-RUN: would generate Wazuh self-signed certificates with the official generator."; return; }
  docker compose -f generate-indexer-certs.yml run --rm generator
}

initialize_indexer_security() {
  log "Initializing Wazuh indexer security configuration."
  local attempt
  for attempt in {1..3}; do
    if       compose exec -T wazuh.indexer bash -lc '

      export JAVA_HOME="/usr/share/wazuh-indexer/jdk"
      export OPENSEARCH_JAVA_HOME="$JAVA_HOME"
      export PATH="$JAVA_HOME/bin:$PATH"
      export CACERT="/usr/share/wazuh-indexer/certs/root-ca.pem"
      export CERT="/usr/share/wazuh-indexer/certs/admin.pem"
      export KEY="/usr/share/wazuh-indexer/certs/admin-key.pem"
      if ! output="$(bash /securityadmin.sh -cd /usr/share/wazuh-indexer/opensearch-security/ -nhnv -cacert "$CACERT" -cert "$CERT" -key "$KEY" -p 9200 -icl 2>&1)"; then
        printf "%s\\n" "$output"
        exit 1
      fi
      printf "%s\\n" "$output"
      grep -q "Configuration for 'internalusers' created or updated" <<<"$output"
      ! grep -q "ERR:" <<<"$output"
    '; then
      log "Wazuh indexer security configuration initialized."
      return
    fi
    (( attempt < 3 )) && sleep 10
  done
  fatal "Wazuh indexer security initialization failed; inspect: docker compose logs --tail=200 wazuh.indexer"
}

wait_for_wazuh_http() {
  local name="$1" url="$2" expected="$3" attempts="$4" code attempt
  log "Waiting for $name to become ready."
  for (( attempt=1; attempt<=attempts; attempt++ )); do
    code="$(curl --silent --show-error --insecure --connect-timeout 3 --max-time 5 --output /dev/null --write-out '%{http_code}' "$url" 2>/dev/null || true)"
    if [[ "$code" =~ $expected ]]; then
      log "$name is ready (HTTP $code)."
      return 0
    fi
    sleep 5
  done
  compose ps
  fatal "$name did not become ready; inspect: docker compose logs --tail=200 wazuh.indexer wazuh.manager wazuh.dashboard"
}

validate_stack() {
  (( DRY_RUN )) && { log "DRY-RUN: would run docker compose config and health checks."; return; }
  compose config >/dev/null || fatal "Generated Compose configuration is invalid."
  # Stop the complete stack before changing credentials. This prevents the
  # Dashboard, Manager/Filebeat, and Indexer from retaining mixed credentials
  # during a rerun. `down` preserves named volumes and indexed Wazuh data.
  compose down --remove-orphans
  # Bootstrap the indexer before starting dashboard and manager. The official
  # image entrypoint intentionally leaves securityadmin disabled by default.
  compose up -d wazuh.indexer
  wait_for_wazuh_http "Wazuh OpenSearch indexer" "https://127.0.0.1:9200/" '^(200|401|403)$' 36
  initialize_indexer_security
  if ! INDEXER_AUTH_USER=admin INDEXER_AUTH_PASSWORD="$WAZUH_INDEXER_PASSWORD" python3 - <<'PY'
import base64
import os
import ssl
import urllib.request

credentials = f"{os.environ['INDEXER_AUTH_USER']}:{os.environ['INDEXER_AUTH_PASSWORD']}".encode()
request = urllib.request.Request("https://127.0.0.1:9200/")
request.add_header("Authorization", "Basic " + base64.b64encode(credentials).decode())
context = ssl._create_unverified_context()
with urllib.request.urlopen(request, context=context, timeout=5) as response:
    if response.status != 200:
        raise SystemExit(response.status)
PY
  then
    fatal "Indexer admin authentication failed after security bootstrap; refusing to start dependent services."
  fi
  log "Indexer admin authentication verified."
  # Recreate dependent services after securityadmin so dashboard migrations do
  # not retain the pre-bootstrap 503 state from an earlier failed attempt.
  compose up -d --build --force-recreate wazuh.manager wazuh.dashboard wazuh.dashboard_proxy
  wait_for_wazuh_http "Wazuh Manager API" "https://127.0.0.1:55000/" '^401$' 36
  wait_for_wazuh_http "Wazuh dashboard" "https://127.0.0.1/" '^[23][0-9][0-9]$' 36
  compose ps
  log "Dashboard: https://$(hostname -I | awk '{print $1}')/ (self-signed certificate warning is expected for MVP/private-LAN use)."
  log "Sentroxis iframe access: local proxy enabled on the same HTTPS endpoint."
  log "API bind address: $WAZUH_API_BIND_ADDRESS:55000. Keep this port private and place it behind a firewall or private network for the secondary node."
}

main() {
  check_os
  check_resources
  if (( DRY_RUN )); then
    log "DRY-RUN: version=$WAZUH_VERSION home=$WAZUH_HOME api_bind=$WAZUH_API_BIND_ADDRESS JVM='$WAZUH_OPENSEARCH_JAVA_OPTS'"
  fi
  install_docker_if_needed
  ensure_bcrypt
  prepare_stack
  configure_credentials
  generate_certificates
  configure_local_proxy
  repair_wazuh_ownership
  validate_stack
  log "Wazuh installation completed. No active response or endpoint enrollment was enabled."
}

main "$@"
