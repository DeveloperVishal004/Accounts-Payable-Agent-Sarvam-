#!/usr/bin/env bash
# Start backend (FastAPI :8000) and frontend (Next.js :3000). Ctrl+C stops both.
# First run: ./run.sh --setup   (creates venv, installs deps, generates demo invoices)
# Fresh demo: ./run.sh --reset  (wipes invoices; keeps Sarvam cache + usage so re-runs are free)
set -e
cd "$(dirname "$0")"
if [[ "$1" == "--setup" ]]; then
  (cd backend && uv venv --python 3.12 -q && uv pip install -q -r pyproject.toml pytest pillow && .venv/bin/python -m seed.make_invoices)
  (cd frontend && npm install --silent)
fi
if [[ "$1" == "--setup" || "$1" == "--reset" ]]; then
  (cd backend && .venv/bin/python -m seed.seed_erp)
fi
[[ -f backend/.env ]] || { echo "Create backend/.env from backend/.env.example and set SARVAM_API_KEY"; exit 1; }
trap 'kill 0' EXIT
(cd backend && .venv/bin/uvicorn app.main:app --port 8000) &
(cd frontend && npm run dev) &
wait
