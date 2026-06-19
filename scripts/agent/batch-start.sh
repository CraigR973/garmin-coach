#!/usr/bin/env bash
set -euo pipefail

ROOT="/Users/craigrobinson/wc_2026_predictor"
BATCH="${1:-}"

if [[ -z "$BATCH" ]]; then
  echo "usage: $0 <batch-id>" >&2
  exit 2
fi

case "$BATCH" in
  U[0-9]*)
    FILE="$ROOT/docs/polish-batches.md"
    PREFIX="feat"
    SECTION_RE="^## $BATCH "
    ;;
  R[0-9]*)
    FILE="$ROOT/docs/review-batches.md"
    PREFIX="fix"
    SECTION_RE="^## $BATCH "
    ;;
  M[0-9]*)
    FILE="$ROOT/docs/phase-batches.md"
    PREFIX="feat"
    SECTION_RE=""
    ;;
  E[0-9]*)
    FILE="$ROOT/docs/env-batches.md"
    PREFIX="feat"
    SECTION_RE="^## $BATCH "
    ;;
  [0-9]*)
    FILE="$ROOT/docs/phase-batches.md"
    PREFIX="feat"
    SECTION_RE=""
    ;;
  *)
    echo "Invalid batch id '$BATCH'" >&2
    exit 2
    ;;
esac

BRANCH="$(git -C "$ROOT" symbolic-ref --short HEAD)"
if [[ "$BRANCH" != "main" ]]; then
  echo "Refusing to start from '$BRANCH'. Check out main first." >&2
  exit 1
fi

STATUS="$(git -C "$ROOT" status --porcelain)"
TRACKED="$(printf '%s\n' "$STATUS" | grep -Ev '^[?][?] ' || true)"
if [[ -n "$TRACKED" ]]; then
  echo "Tracked working-tree changes exist. Commit/stash them before batch-start:" >&2
  printf '%s\n' "$TRACKED" >&2
  exit 1
fi

git -C "$ROOT" fetch origin
git -C "$ROOT" pull --ff-only origin main

TITLE="$BATCH"
if [[ -n "$SECTION_RE" && -f "$FILE" ]]; then
  TITLE_LINE="$(grep -E "$SECTION_RE" "$FILE" | head -1 || true)"
  if [[ -n "$TITLE_LINE" ]]; then
    TITLE="$(printf '%s' "$TITLE_LINE" | sed -E "s/^## $BATCH[[:space:]]+[—-][[:space:]]+//; s/[[:space:]]+[🟢🔴].*$//")"
  fi
fi

SLUG="$(printf '%s' "$TITLE" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//' | cut -c1-40 | sed -E 's/-+$//')"
if [[ -z "$SLUG" ]]; then
  SLUG="$(printf '%s' "$BATCH" | tr '[:upper:]' '[:lower:]')"
fi

BRANCH_NAME="$PREFIX/$(printf '%s' "$BATCH" | tr '[:upper:]' '[:lower:]')-$SLUG"
git -C "$ROOT" checkout -b "$BRANCH_NAME"

echo "Started $BRANCH_NAME for $BATCH"
echo "Source: $FILE"
echo "After implementation: /batch-verify $BATCH, push, then /phase-closeout $BATCH"
