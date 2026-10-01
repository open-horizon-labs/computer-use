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
  uv pip install --python .venv-facade/bin/python -r computer_use/requirements.txt
else
  .venv-facade/bin/python -m pip install -r computer_use/requirements.txt
fi

if [ "$INSTALL_PERCEPTION" -eq 1 ]; then
  echo "Installing/verifying Cua Perception (default step; pass --no-perception to skip) ..."
  python3 scripts/install_perception.py
else
  echo "Skipping Cua Perception install (--no-perception); perception-dependent facade tools will report a Gap naming this installer."
fi

if command -v npm >/dev/null 2>&1; then
  echo "Pre-fetching mobile-mcp 1.0.6 for Android/iOS device targets (optional: the server fetches it itself on first device use) ..."
  npm cache add "@mobilenext/mobile-mcp@1.0.6" >/dev/null 2>&1 || echo "  could not pre-fetch; it will be fetched on first use"
else
  echo "Node.js (npm/npx) not found: Android/iOS device targets need Node.js 18+ (the server answers mobile_backend_unavailable until then); Mac windows are unaffected."
fi

echo "Done. Register the server: codex mcp add computer-use-oh -- \"$ROOT/.venv-facade/bin/python\" \"$ROOT/computer_use/server.py\""

echo
echo "Checking the environment (python -m computer_use doctor; bootstrap fixes what it can) ..."
.venv-facade/bin/python -m computer_use doctor || echo "doctor reported blockers: see the fix lines above (python -m computer_use bootstrap does the fixable ones)."
