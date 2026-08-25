#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

WAZUH_DIR="${WAZUH_HOME:-$ROOT_DIR/.wazuh}"
WAZUH_COMPOSE="$WAZUH_DIR/single-node/docker-compose.yml"
WAZUH_OVERRIDE="$WAZUH_DIR/single-node/docker-compose.sentroxis.yml"
run_privileged() {
  if [[ $EUID -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

start_wazuh() {
  if [[ "${SENTROXIS_SKIP_WAZUH:-0}" == "1" ]]; then
    printf '==> Skipping Wazuh startup because SENTROXIS_SKIP_WAZUH=1\n'
    return
  fi
  [[ -f "$WAZUH_COMPOSE" && -f "$WAZUH_OVERRIDE" ]] || {
    printf '%s\n' 'ERROR: Wazuh is not installed or has no Sentroxis proxy configuration. Run: sudo ./wazuh_installation.sh' >&2
    exit 1
  }
  printf '==> Starting installed Wazuh services\n'
  run_privileged docker compose -f "$WAZUH_COMPOSE" -f "$WAZUH_OVERRIDE" up -d
}

start_wazuh

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

printf '\n==> Installing frontend dependencies\n'
cd frontend
npm install
cd "$ROOT_DIR"

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
bash -n start.sh startup.sh wazuh_installation.sh
git diff --check

printf '\n==> All validation checks passed. Starting development servers\n'
cleanup() {
  jobs -p | xargs -r kill 2>/dev/null || true
}
trap cleanup EXIT INT TERM

PYTHONPATH="$ROOT_DIR" backend/.venv/bin/uvicorn backend.main:app --reload --reload-dir "$ROOT_DIR/backend" --host 0.0.0.0 --port 8000 &
cd frontend
npm run dev -- --host 0.0.0.0 &
cd "$ROOT_DIR"
printf 'Backend:  http://localhost:8000\nFrontend: http://localhost:5173\nPress Ctrl+C to stop both servers.\n'
wait
