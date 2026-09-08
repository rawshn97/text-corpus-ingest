#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  echo "Missing .venv: run ./scripts/setup.sh first" >&2
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate
export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"

exec pytest "$@"
