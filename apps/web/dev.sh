#!/usr/bin/env bash
export NVM_DIR="$HOME/.nvm"
# shellcheck source=/dev/null
source "$NVM_DIR/nvm.sh"
nvm use 20 --silent
exec pnpm dev
