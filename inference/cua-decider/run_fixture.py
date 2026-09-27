"""Run the pinned upstream jev-use browser fixture with the LAN Decider provider.

Set CUA_JEV_USE_DIR to the upstream examples/jev-use directory, then pass the
normal upstream run.py arguments. Cua Driver must be installed on this desktop.
"""

import asyncio
import os
from pathlib import Path
import sys

from decider_adapter import choose_decider

root = Path(os.environ["CUA_JEV_USE_DIR"]).resolve()
if not (root / "python/run.py").is_file():
    raise RuntimeError("CUA_JEV_USE_DIR must contain python/run.py")
sys.path.insert(0, str(root / "python"))
import run

run.choose_live = choose_decider
# MCP's default environment allowlist drops Linux display/session variables.
# Pass only desktop plumbing; do not forward unrelated credentials.
_stdio_parameters = run.StdioServerParameters


def desktop_stdio_parameters(**kwargs):
    keys = (
        "DISPLAY",
        "WAYLAND_DISPLAY",
        "XAUTHORITY",
        "DBUS_SESSION_BUS_ADDRESS",
        "XDG_RUNTIME_DIR",
        "XDG_SESSION_TYPE",
        "LIBGL_ALWAYS_SOFTWARE",
        "__EGL_VENDOR_LIBRARY_FILENAMES",
    )
    kwargs["env"] = {k: os.environ[k] for k in keys if k in os.environ}
    return _stdio_parameters(**kwargs)


run.StdioServerParameters = desktop_stdio_parameters
if "--provider" not in sys.argv:
    sys.argv += ["--provider", "live"]
if __name__ == "__main__":
    args = run.parse_args()
    if args.provider != "live":
        raise ValueError("This entrypoint requires the live Decider provider")
    outcome = asyncio.run(run.run(args))
    raise SystemExit(0 if outcome == "verified" else 1)
