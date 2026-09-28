#!/usr/bin/env bash
# Set up the facade runtime: .venv-facade, its requirements, and (by default)
# the pinned Cua Perception extension. See docs/FACADE.md.
#
# Usage: scripts/setup_facade.sh [--no-perception]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

INSTALL_PERCEPTION=1
for arg in "$@"; do
  case "$arg" in
    --no-perception) INSTALL_PERCEPTION=0 ;;
    *) echo "unknown argument: $arg" >&2; exit 1 ;;
  esac
done

if [ ! -d .venv-facade ]; then
  echo "Creating .venv-facade ..."
  if command -v uv >/dev/null 2>&1; then
    uv venv --python 3.12 .venv-facade
  else
    python3 -m venv .venv-facade
  fi
fi

echo "Installing facade requirements ..."
if command -v uv >/dev/null 2>&1; then
  uv pip install --python .venv-facade/bin/python -r facade/requirements.txt
else
  .venv-facade/bin/python -m pip install -r facade/requirements.txt
fi

if [ "$INSTALL_PERCEPTION" -eq 1 ]; then
  echo "Installing/verifying Cua Perception (default step; pass --no-perception to skip) ..."
  python3 scripts/install_perception.py
else
  echo "Skipping Cua Perception install (--no-perception); perception-dependent facade tools will report a Gap naming this installer."
fi

echo "Done. Register the server: codex mcp add cua-task -- \"$ROOT/.venv-facade/bin/python\" \"$ROOT/facade/server.py\""
