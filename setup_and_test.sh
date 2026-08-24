#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if ! grep -q '^pydantic>=2.12,<3$' backend/requirements.txt; then
  printf 'ERROR: This checkout has the pre-Python-3.14 dependency manifest. Run: git pull origin main\n' >&2
  exit 1
fi

printf '==> Preparing Python environment\n'
python3 --version
python3 -m venv backend/.venv
# shellcheck disable=SC1091
source backend/.venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --only-binary=:all: -r backend/requirements.txt

printf '\n==> Installing frontend dependencies\n'
cd frontend
npm install
cd "$ROOT_DIR"

printf '\n==> Running backend tests\n'
PYTHONPATH="$ROOT_DIR" pytest -q backend/tests

printf '\n==> Running frontend tests\n'
cd frontend
npm test -- --run
cd "$ROOT_DIR"

printf '\n==> All tests passed. Starting development servers\n'
cleanup() {
  jobs -p | xargs -r kill 2>/dev/null || true
}
trap cleanup EXIT INT TERM

PYTHONPATH="$ROOT_DIR" backend/.venv/bin/uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000 &
cd frontend
npm run dev -- --host 0.0.0.0 &
cd "$ROOT_DIR"
printf 'Backend:  http://localhost:8000\nFrontend: http://localhost:5173\nPress Ctrl+C to stop both servers.\n'
wait
