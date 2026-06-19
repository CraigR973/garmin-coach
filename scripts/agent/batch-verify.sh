#!/usr/bin/env bash
set -euo pipefail

ROOT="/Users/craigrobinson/wc_2026_predictor"
BATCH="${1:-batch}"
NODE_PATH="$HOME/.nvm/versions/node/v20.20.2/bin:$PATH"
PY="/Users/craigrobinson/wc_2026_predictor/apps/api/.venv/bin/python"

BRANCH="$(git -C "$ROOT" symbolic-ref --short HEAD)"
if [[ "$BRANCH" == "main" ]]; then
  echo "Warning: verifying on main. /phase-closeout expects a feature branch." >&2
fi

CHANGED="$(git -C "$ROOT" diff --name-only main...HEAD; git -C "$ROOT" diff --name-only)"

run_frontend=0
run_backend=0
run_shared=0

if printf '%s\n' "$CHANGED" | grep -Eq '^(apps/web|packages/shared)/'; then
  run_frontend=1
fi

if printf '%s\n' "$CHANGED" | grep -Eq '^(apps/api|migrations|packages/shared)/'; then
  run_backend=1
fi

if printf '%s\n' "$CHANGED" | grep -Eq '^packages/shared/'; then
  run_shared=1
fi

if [[ "$run_frontend" == "1" ]]; then
  PATH="$NODE_PATH" pnpm --dir "$ROOT/apps/web" lint
  PATH="$NODE_PATH" pnpm --dir "$ROOT/apps/web" typecheck
  PATH="$NODE_PATH" pnpm --dir "$ROOT/apps/web" build
  PATH="$NODE_PATH" pnpm --dir "$ROOT/apps/web" test
fi

if [[ "$run_backend" == "1" ]]; then
  PYTHONPATH="$ROOT/apps/api" "$PY" -m ruff check "$ROOT/apps/api"
  PYTHONPATH="$ROOT/apps/api" "$PY" -m ruff format --check "$ROOT/apps/api"
  PYTHONPATH="$ROOT/apps/api" "$PY" -m mypy "$ROOT/apps/api/src"
  PYTHONPATH="$ROOT/apps/api" "$PY" -m pytest "$ROOT/apps/api/tests"
fi

if [[ "$run_shared" == "1" ]]; then
  if PATH="$NODE_PATH" pnpm --dir "$ROOT/packages/shared" run | grep -q '^  test'; then
    PATH="$NODE_PATH" pnpm --dir "$ROOT/packages/shared" test
  else
    echo "packages/shared has no test script; covered through consuming app tests."
  fi
fi

if [[ "$run_frontend" == "0" && "$run_backend" == "0" && "$run_shared" == "0" ]]; then
  echo "No code gates inferred from changed files; review docs-only changes manually."
fi

echo "Ready for /phase-closeout $BATCH: yes"
