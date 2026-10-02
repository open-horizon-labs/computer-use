# Setup

Native computer use is the default. Install this optional supplement only for explicitly requested mobile or isolated off-screen work.

The Claude and Codex MCP registration runs /Users/muness1/src/open-horizon-labs/computer-use/.venv-facade/bin/python with /Users/muness1/src/open-horizon-labs/computer-use/computer_use/server.py. Restart/reconnect the client after a server or skill update. Only look and do are exposed; CUA_TASK_ADVANCED cannot revive archived tools.

Mobile uses @mobilenext/mobile-mcp@1.0.6 by default. CUA_MOBILE_MCP can supply an external command. The local Android raw hierarchy adapter uses CUA_MOBILECLI_COMMAND, a JSON argv array, or @mobilenext/mobilecli@1.0.16. A custom provider disables local raw-hierarchy reads so devices are not silently crossed. Install device agents and grants through the provider's documented setup. Missing state remains unknown.

Off-screen requires Cua Driver, an installed Chromium executable and a working virtual display. CUA_AGENT_BROWSER_PATH can point to an installed Chromium. The server forces an isolated browser and required display: it ignores legacy user-browser and physical-display fallback mode settings. It does not install Chrome, grant permissions or unlock the Mac automatically. Provider commands and credentials remain external configuration; never print or commit their values.

Offline checks do not launch apps, devices, model workers or GPU jobs. See docs/FACADE.md and docs/BENCHMARK.md in the checkout for the active contract and measured limits. The broader implementation is preserved at codex/archive-general-facade-2026-10-02 (a531b43).
