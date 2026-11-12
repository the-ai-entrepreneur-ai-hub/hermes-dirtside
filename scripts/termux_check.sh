#!/usr/bin/env bash
# Signed lifecycle check using one unique --rm container and loopback.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HERMES_SRC="${HERMES_SRC:-$(dirname "$ROOT")/hermes-agent-main}"
PYTHON="${HERMES_PYTHON:-$HERMES_SRC/venv/bin/python}"
export HERMES_SRC
export PYTHONPATH="$HERMES_SRC:$ROOT:$ROOT/tools"
printf 'Termux check: real userland, no Termux:API or physical phone claim.\n'
exec "$PYTHON" "$ROOT/tools/termux_check.py"
