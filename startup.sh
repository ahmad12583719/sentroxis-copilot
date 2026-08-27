#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# Wazuh is an optional external integration. This startup script does not
# install, require, or start Wazuh services. Configure its API variables only
# when Wazuh telemetry is available for this deployment.

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

printf '\n==> Running backend tests\n'
PYTHONPATH="$ROOT_DIR" pytest -q backend/tests

printf '\n==> Running frontend lint\n'
cd frontend
npm run lint

printf '\n==> Running frontend tests\n'
npm test -- --run

printf '\n==> Building frontend\n'
npm run build
cd "$ROOT_DIR"

printf '\n==> Running shell and whitespace checks\n'
bash -n start.sh startup.sh
git diff --check

printf '\n==> All validation checks passed. Starting development servers\n'
cleanup() {
  jobs -p | xargs -r kill 2>/dev/null || true
}
trap cleanup EXIT INT TERM

PYTHONPATH="$ROOT_DIR" backend/.venv/bin/uvicorn backend.main:app --reload --reload-dir "$ROOT_DIR/backend" --host 0.0.0.0 --port 8000 &
cd frontend
VITE_HTTPS_KEY="$ROOT_DIR/runtime/sentroxis-dev-tls/localhost.key" VITE_HTTPS_CERT="$ROOT_DIR/runtime/sentroxis-dev-tls/localhost.crt" npm run dev -- --host 0.0.0.0 &
cd "$ROOT_DIR"
printf 'Backend:  http://localhost:8000\nFrontend: https://localhost:5173\nWazuh:    optional external integration\nPress Ctrl+C to stop both servers.\n'
wait
