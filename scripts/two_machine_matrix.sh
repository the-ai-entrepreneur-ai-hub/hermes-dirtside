#!/usr/bin/env bash
# Eight real-core reliability rows, with isolated homes and owned processes.
# --loopback needs only the adjacent core checkout and its installed interpreter.
# For remote operation, see tools/run_matrix.py --help.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HERMES_SRC="${HERMES_SRC:-$(dirname "$ROOT")/hermes-agent-main}"
PYTHON="${HERMES_PYTHON:-$HERMES_SRC/venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  printf 'Missing installed core interpreter: %s\n' "$PYTHON" >&2
  exit 2
fi
export HERMES_SRC
export PYTHONPATH="$HERMES_SRC:$ROOT:$ROOT/tools"
exec "$PYTHON" "$ROOT/tools/run_matrix.py" "$@"
