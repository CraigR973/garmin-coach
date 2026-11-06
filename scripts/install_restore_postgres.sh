#!/usr/bin/env bash
# Ephemeral Ubuntu runners only. Keep native restore tests and real proof on PG17.
set -euo pipefail
sudo install -d /etc/apt/keyrings
curl --fail --retry 3 https://www.postgresql.org/media/keys/ACCC4CF8.asc -o /tmp/coach-pgdg.asc
sudo install -m 644 /tmp/coach-pgdg.asc /etc/apt/keyrings/pgdg.asc
. /etc/os-release
echo "deb [signed-by=/etc/apt/keyrings/pgdg.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" | sudo tee /etc/apt/sources.list.d/pgdg.list > /dev/null
sudo apt-get update -qq
sudo apt-get install -y age postgresql-17
