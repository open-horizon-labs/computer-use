#!/usr/bin/env bash
# Desktop-side setup. Requires git, Python >=3.10, uv, and a supported browser.
set -euo pipefail
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
client_root=${CUA_DECIDER_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/fleet-cua-decider}
revision=$(cat "$here/upstream-revision.txt")
mkdir -p "$client_root"
if [[ ! -e "$client_root/cua.env" ]]; then
    cat > "$client_root/cua.env" <<'EOF'
# Per-selector Qwen reasoning mode: none, low, medium, or xhigh.
CUA_QWEN_THINKING=none
EOF
    chmod 0600 "$client_root/cua.env"
fi
if [[ ! -d "$client_root/cua/.git" ]]; then
    git clone --filter=blob:none --no-checkout https://github.com/trycua/cua.git "$client_root/cua"
fi
git -C "$client_root/cua" sparse-checkout init --cone
git -C "$client_root/cua" sparse-checkout set libs/cua-driver/examples/jev-use
git -C "$client_root/cua" checkout --detach "$revision"
cd "$client_root"
uv venv --allow-existing --python 3.12 "$client_root/.venv"
uv pip install --python "$client_root/.venv/bin/python" \
    cua-driver==0.28.2 mcp==1.30.0 typesafe-sdk==0.7.1
# Copy the adapter so the launcher remains usable after the checkout moves.
install -m 0644 "$here/decider_adapter.py" "$here/run_fixture.py" "$here/verify_fixture.py" "$here/cascade.py" "$here/decision_providers.py" "$client_root/"
cat > "$client_root/verify" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
client_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
export PATH="$client_root/.venv/bin:$PATH"
export CUA_JEV_USE_DIR="$client_root/cua/libs/cua-driver/examples/jev-use"
export DECIDER_URL=${DECIDER_URL:-http://192.168.1.104:8010}
exec "$client_root/.venv/bin/python" "$client_root/verify_fixture.py" "$@"
EOF
chmod +x "$client_root/verify"
printf 'Installed. From an unlocked desktop, run:\n  %q --output-dir proof-decider\n' "$client_root/verify"

cat > "$client_root/select" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
client_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec "$client_root/.venv/bin/python" "$client_root/cascade.py" "$@"
EOF
cat > "$client_root/select-fleet" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
client_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ -f "$client_root/cua.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$client_root/cua.env"
    set +a
fi
export CUA_QWEN_THINKING=${CUA_QWEN_THINKING:-none}
case "$CUA_QWEN_THINKING" in
    none|low|medium|xhigh) ;;
    *) printf 'Invalid CUA_QWEN_THINKING: %s (expected none, low, medium, or xhigh)\n' "$CUA_QWEN_THINKING" >&2; exit 2 ;;
esac
export TYPESAFE_CONNECT_SSH=${TYPESAFE_CONNECT_SSH:-homelab-personal-assembler}
export QWEN_SECRET_SSH=${QWEN_SECRET_SSH:-homelab-personal-stock}
exec "$client_root/select" "$@"
EOF
chmod +x "$client_root/select" "$client_root/select-fleet"
printf 'Bounded selector: %q (JSON lines); Fleet SSH credentials: %q\n' "$client_root/select" "$client_root/select-fleet"
