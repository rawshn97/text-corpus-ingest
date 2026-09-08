#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

mkdir -p staging
touch staging/.gitkeep

echo "Setup complete."
echo "  1. Edit config/irc.yaml (host, nick, channels)"
echo "  2. Optional: cp .env.example .env"
echo "  3. Run: ./scripts/run_fetch.sh --query \"SEARCH_TERMS\""
