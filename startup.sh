#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

repair_wazuh_ownership() {
  local wazuh_dir="$ROOT_DIR/.wazuh" owner group
  [[ -d "$wazuh_dir" ]] || return 0
  owner="${SUDO_USER:-${USER:-}}"
  [[ -n "$owner" && "$owner" != root ]] || return 0
  group="$(id -gn "$owner" 2>/dev/null || printf '%s' "$owner")"
  if [[ "$EUID" -eq 0 ]]; then
    chown -R "$owner:$group" "$wazuh_dir" 2>/dev/null || true
  elif command -v sudo >/dev/null 2>&1; then
    sudo -n chown -R "$owner:$group" "$wazuh_dir" 2>/dev/null ||
      printf 'WARNING: Could not automatically repair ownership under %s\n' "$wazuh_dir" >&2
  fi
}
repair_wazuh_ownership

wait_for_wazuh_endpoint() {
  local name="$1" url="$2" pattern="$3" attempt code
  printf '==> Waiting for %s\n' "$name"
  for attempt in {1..36}; do
    code="$(curl --silent --show-error --insecure --connect-timeout 3 --max-time 5 --output /dev/null --write-out '%{http_code}' "$url" 2>/dev/null || true)"
    if [[ "$code" =~ $pattern ]]; then
      printf '    %s ready (HTTP %s)\n' "$name" "$code"
      return 0
    fi
    sleep 5
  done
  printf 'ERROR: %s did not become ready at %s\n' "$name" "$url" >&2
  return 1
}

wait_for_indexer() {
  local attempt
  printf '==> Waiting for OpenSearch cluster health\n'
  for attempt in {1..36}; do
    if curl --silent --show-error --insecure --fail --user "admin:${WAZUH_INDEXER_PASSWORD}" \
      --connect-timeout 3 --max-time 10 \
      https://127.0.0.1:9200/_cluster/health >/dev/null 2>&1; then
      printf '    OpenSearch cluster health is ready\n'
      return 0
    fi
    sleep 5
  done
  printf 'ERROR: OpenSearch cluster health did not become ready\n' >&2
  return 1
}

ensure_wazuh_build_context() {
  local wazuh_dir="$ROOT_DIR/.wazuh/single-node"
  local build_dir="$ROOT_DIR/.wazuh/build-docker-images/wazuh-manager"
  local build_config="$build_dir/config"
  local single_template="$wazuh_dir/config/wazuh_cluster/filebeat.yml"
  local build_template="$build_config/filebeat.yml"
  mkdir -p "$build_config"
  if [[ ! -f "$build_template" && -f "$single_template" ]]; then
    cp -p "$single_template" "$build_template"
  fi
  [[ -f "$build_template" ]] || {
    printf 'ERROR: Cannot provision Filebeat build context; template missing: %s\n' "$single_template" >&2
    return 1
  }
  if [[ ! -f "$build_dir/Dockerfile.sentroxis" ]]; then
    cat > "$build_dir/Dockerfile.sentroxis" <<'DOCKERFILE'
FROM wazuh/wazuh-manager:4.7.5
COPY config/filebeat.yml /etc/filebeat/filebeat.yml
RUN chmod go-w /etc/filebeat/filebeat.yml
DOCKERFILE
  fi
}

start_and_check_wazuh() {
  local wazuh_dir="$ROOT_DIR/.wazuh/single-node"
  [[ -f "$wazuh_dir/docker-compose.yml" ]] || {
    printf 'ERROR: Wazuh Compose file is missing: %s\n' "$wazuh_dir/docker-compose.yml" >&2
    return 1
  }
  [[ -f "$wazuh_dir/docker-compose.sentroxis.yml" ]] || {
    printf 'ERROR: Sentroxis Compose override is missing: %s\n' "$wazuh_dir/docker-compose.sentroxis.yml" >&2
    printf 'Run ./install.py first to provision the Wazuh stack.\n' >&2
    return 1
  }
  command -v docker >/dev/null 2>&1 || {
    printf 'ERROR: Docker is required to start the Wazuh stack.\n' >&2
    return 1
  }
  if [[ -f "$ROOT_DIR/runtime/wazuh-api.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$ROOT_DIR/runtime/wazuh-api.env"
    set +a
  fi
  [[ -n "${WAZUH_INDEXER_PASSWORD:-}" ]] || {
    printf 'ERROR: WAZUH_INDEXER_PASSWORD is unavailable for the indexer healthcheck.\n' >&2
    printf 'Run ./install.py first or provide runtime/wazuh-api.env.\n' >&2
    return 1
  }
  printf '==> Starting the Wazuh Compose stack\n'
  ensure_wazuh_build_context
  (cd "$wazuh_dir" && docker compose -f docker-compose.yml -f docker-compose.sentroxis.yml config >/dev/null)
  (cd "$wazuh_dir" && docker compose -f docker-compose.yml -f docker-compose.sentroxis.yml config --services | grep -qx 'wazuh.dashboard_proxy') || {
    printf 'ERROR: Sentroxis Compose override does not define wazuh.dashboard_proxy.\n' >&2
    return 1
  }
  (cd "$wazuh_dir" && docker compose -f docker-compose.yml -f docker-compose.sentroxis.yml up -d --build)
  wait_for_indexer
  wait_for_wazuh_endpoint "Wazuh Manager API" "https://127.0.0.1:55000/" '^401$'
  wait_for_wazuh_endpoint "Wazuh dashboard" "https://127.0.0.1/" '^[23][0-9][0-9]$'
  (cd "$wazuh_dir" && docker compose -f docker-compose.yml -f docker-compose.sentroxis.yml ps --status running --services | grep -qx 'wazuh.dashboard_proxy') || {
    printf 'ERROR: wazuh.dashboard_proxy is not running after startup.\n' >&2
    (cd "$wazuh_dir" && docker compose -f docker-compose.yml -f docker-compose.sentroxis.yml ps) >&2 || true
    return 1
  }
}
start_and_check_wazuh

# Wazuh is an optional external integration. When its local Compose deployment
# exists, startup.sh starts it and waits for all required health endpoints.

VELOCIRAPTOR_DIR="$ROOT_DIR/backend/runtime/velociraptor"
VELOCIRAPTOR_BIN="$VELOCIRAPTOR_DIR/velociraptor"
VELOCIRAPTOR_CONFIG="$VELOCIRAPTOR_DIR/server.config.yaml"
VELOCIRAPTOR_LOG="$VELOCIRAPTOR_DIR/velociraptor-server.log"
VELOCIRAPTOR_PID="$VELOCIRAPTOR_DIR/velociraptor-server.pid"
VELOCIRAPTOR_STARTED_PID=""
VELOCIRAPTOR_REUSED_PID=""

find_running_velociraptor() {
  local pid args
  while read -r pid args; do
    [[ -z "$pid" || "$pid" == "$$" ]] && continue
    if [[ "$args" == *"$VELOCIRAPTOR_BIN"* && "$args" == *"--config $VELOCIRAPTOR_CONFIG"* && "$args" == *" frontend"* ]] && kill -0 "$pid" 2>/dev/null; then
      printf '%s\n' "$pid"
      return 0
    fi
  done < <(ps -eo pid=,args=)
  return 1
}

prepare_velociraptor_log_directory() {
  local output_directory
  output_directory="$(sed -n '/^Logging:/,/^[^[:space:]]/{s/^[[:space:]]*output_directory:[[:space:]]*//p}' "$VELOCIRAPTOR_CONFIG" | head -n 1)"
  [[ -z "$output_directory" ]] && return 0
  if ! mkdir -p "$output_directory"; then
    printf 'WARNING: Velociraptor logging directory is not writable: %s\n' "$output_directory" >&2
    printf 'WARNING: Regenerate server.config.yaml with a user-writable directory, such as ~/.sentroxis/velociraptor.\n' >&2
    return 1
  fi
}

start_velociraptor() {
  if [[ ! -x "$VELOCIRAPTOR_BIN" || ! -f "$VELOCIRAPTOR_CONFIG" ]]; then
    printf '==> Velociraptor local server is not configured; dashboard controls remain available after setup.\n'
    return 0
  fi
  if ! prepare_velociraptor_log_directory; then
    return 0
  fi
  local existing_pid
  existing_pid="$(find_running_velociraptor || true)"
  if [[ -n "$existing_pid" ]]; then
    VELOCIRAPTOR_REUSED_PID="$existing_pid"
    printf '%s\n' "$existing_pid" > "$VELOCIRAPTOR_PID"
    chmod 600 "$VELOCIRAPTOR_PID"
    printf '==> Velociraptor server already running (PID %s); reusing it\n' "$existing_pid"
    return 0
  fi
  rm -f "$VELOCIRAPTOR_PID"
  printf '==> Starting project-local Velociraptor server\n'
  printf '    Command: %s --config %s frontend -v\n' "$VELOCIRAPTOR_BIN" "$VELOCIRAPTOR_CONFIG"
  (cd "$VELOCIRAPTOR_DIR" && exec "$VELOCIRAPTOR_BIN" --config "$VELOCIRAPTOR_CONFIG" frontend -v) >> "$VELOCIRAPTOR_LOG" 2>&1 &
  VELOCIRAPTOR_STARTED_PID="$!"
  printf '%s\n' "$VELOCIRAPTOR_STARTED_PID" > "$VELOCIRAPTOR_PID"
  chmod 600 "$VELOCIRAPTOR_PID"
  local attempt
  for attempt in 1 2 3 4 5 6 7 8; do
    if kill -0 "$VELOCIRAPTOR_STARTED_PID" 2>/dev/null; then
      printf '==> Velociraptor server started (PID %s); GUI status is available in the Velociraptor dashboard.\n' "$VELOCIRAPTOR_STARTED_PID"
      return 0
    fi
    sleep 1
  done
  if ! kill -0 "$VELOCIRAPTOR_STARTED_PID" 2>/dev/null; then
    printf 'WARNING: Velociraptor server exited during startup; inspect: %s\n' "$VELOCIRAPTOR_LOG" >&2
    if [[ -f "$VELOCIRAPTOR_LOG" ]]; then
      printf '%s\n' '--- Velociraptor startup log (last 30 lines) ---' >&2
      tail -n 30 "$VELOCIRAPTOR_LOG" >&2 || true
      printf '%s\n' '--- end Velociraptor startup log ---' >&2
    fi
    rm -f "$VELOCIRAPTOR_PID"
    VELOCIRAPTOR_STARTED_PID=""
    return 0
  fi
}

if ! grep -q '^pydantic>=2.12,<3$' backend/requirements.txt; then
  printf 'ERROR: This checkout has the pre-Python-3.14 dependency manifest. Run: git pull origin main\n' >&2
  exit 1
fi

printf '==> Preparing Python environment\n'
python3 --version
rm -rf backend/.venv
python3 -m venv backend/.venv
# shellcheck disable=SC1091
source backend/.venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --only-binary=:all: -r backend/requirements.txt
python -m pip check

prepare_frontend_tls() {
  local tls_dir="$ROOT_DIR/runtime/sentroxis-dev-tls"
  if [[ -f "$tls_dir/localhost.key" && -f "$tls_dir/localhost.crt" ]]; then
    return
  fi
  printf '\n==> Creating local HTTPS certificate for the Sentroxis frontend\n'
  mkdir -p "$tls_dir"
  chmod 700 "$tls_dir"
  openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 825 \
    -keyout "$tls_dir/localhost.key" \
    -out "$tls_dir/localhost.crt" \
    -subj '/CN=localhost' \
    -addext 'subjectAltName=DNS:localhost,IP:127.0.0.1'
  chmod 600 "$tls_dir/localhost.key"
  chmod 644 "$tls_dir/localhost.crt"
}

prepare_frontend_tls
start_velociraptor

printf '\n==> Installing frontend dependencies\n'
cd frontend
npm install
cd "$ROOT_DIR"

if [[ -f "$ROOT_DIR/runtime/wazuh-api.env" ]]; then
  printf '==> Loading project-local Wazuh API connection settings\n'
  set -a
  source "$ROOT_DIR/runtime/wazuh-api.env"
  set +a
else
  printf '==> Wazuh integration is optional and not configured; continuing without Wazuh telemetry.\n'
fi

if [[ "${SENTROXIS_RUN_VALIDATION:-0}" == "1" ]]; then
  printf '\n==> Running backend tests\n'
  PYTHONPATH="$ROOT_DIR" timeout 120s backend/.venv/bin/pytest -q backend/tests
  printf '==> Backend tests passed; continuing with frontend validation\n'

  printf '\n==> Running frontend lint\n'
  cd frontend
  npm run lint

  printf '\n==> Running frontend tests\n'
  npm test -- --run
  printf '==> Frontend tests passed; building frontend\n'

  printf '\n==> Building frontend\n'
  npm run build
  cd "$ROOT_DIR"
else
  printf '\n==> Skipping full validation for development startup\n'
  printf '    Run SENTROXIS_RUN_VALIDATION=1 ./startup.sh to run backend/frontend tests and build checks.\n'
fi

printf '\n==> Running shell and whitespace checks\n'
bash -n start.sh startup.sh
git diff --check

printf '\n==> All validation checks passed. Starting development servers\n'
BACKEND_LOG="$ROOT_DIR/runtime/sentroxis-backend.log"
FRONTEND_LOG="$ROOT_DIR/runtime/sentroxis-frontend.log"
mkdir -p "$ROOT_DIR/runtime"
: > "$BACKEND_LOG"
: > "$FRONTEND_LOG"
cleanup() {
  jobs -p | xargs -r kill 2>/dev/null || true
  if [[ -n "$VELOCIRAPTOR_STARTED_PID" ]]; then
    kill "$VELOCIRAPTOR_STARTED_PID" 2>/dev/null || true
  fi
  rm -f "$VELOCIRAPTOR_PID"
}
trap cleanup EXIT INT TERM

PYTHONPATH="$ROOT_DIR" backend/.venv/bin/uvicorn backend.main:app --reload --reload-dir "$ROOT_DIR/backend" --host 0.0.0.0 --port 8000 >> "$BACKEND_LOG" 2>&1 &
BACKEND_PID="$!"
for attempt in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS --max-time 2 http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    printf 'ERROR: FastAPI stopped during startup. See %s\n' "$BACKEND_LOG" >&2
    tail -n 40 "$BACKEND_LOG" >&2 || true
    exit 1
  fi
  sleep 1
done
if ! curl -fsS --max-time 2 http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
  printf 'ERROR: FastAPI did not become ready on port 8000. See %s\n' "$BACKEND_LOG" >&2
  tail -n 40 "$BACKEND_LOG" >&2 || true
  exit 1
fi
cd frontend
VITE_HTTPS_KEY="$ROOT_DIR/runtime/sentroxis-dev-tls/localhost.key" VITE_HTTPS_CERT="$ROOT_DIR/runtime/sentroxis-dev-tls/localhost.crt" npm run dev -- --host 0.0.0.0 >> "$FRONTEND_LOG" 2>&1 &
FRONTEND_PID="$!"
cd "$ROOT_DIR"
for attempt in 1 2 3 4 5 6 7 8 9 10; do
  if curl -kfsS --max-time 2 https://127.0.0.1:5173/ >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
    printf 'ERROR: Vite stopped during startup. See %s\n' "$FRONTEND_LOG" >&2
    tail -n 40 "$FRONTEND_LOG" >&2 || true
    exit 1
  fi
  sleep 1
done
if ! curl -kfsS --max-time 2 https://127.0.0.1:5173/ >/dev/null 2>&1; then
  printf 'ERROR: Vite did not become ready on port 5173. See %s\n' "$FRONTEND_LOG" >&2
  tail -n 40 "$FRONTEND_LOG" >&2 || true
  exit 1
fi
printf 'Backend:       http://localhost:8000 (ready)\nFrontend:      https://localhost:5173 (ready)\nVelociraptor:  project-local process (see dashboard status)\nWazuh:         optional external integration\nLogs:          %s and %s\nPress Ctrl+C to stop all local processes.\n' "$BACKEND_LOG" "$FRONTEND_LOG"
wait
