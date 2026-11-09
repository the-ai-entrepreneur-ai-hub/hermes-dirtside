#!/usr/bin/env bash
# Owner-run only. Uses the specified image, one unique --rm container and loopback.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HERMES_SRC="${HERMES_SRC:-$(dirname "$ROOT")/hermes-agent-main}"
PYTHON="${HERMES_PYTHON:-$HERMES_SRC/venv/bin/python}"
export HERMES_SRC
export PYTHONPATH="$HERMES_SRC:$ROOT:$ROOT/tools"
printf 'Termux check: real userland, no Termux:API or physical phone claim.\n'
exec nice -n 10 "$PYTHON" "$ROOT/tools/termux_check.py"
