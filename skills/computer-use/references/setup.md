# Setup

Install the computer-use skill into the client's skill directory. Native tools remain supplied by the client. Install Cua CLI separately, then register the slim Spaces server:

```sh
claude mcp add --scope user cua-spaces -- cua mcp --embedded --permissions spaces:list_spaces,spaces:list_tools,spaces:call_tool
codex mcp add cua-spaces -- cua mcp --embedded --permissions spaces:list_spaces,spaces:list_tools,spaces:call_tool
```

Reconnect clients. Fetch Driver schemas by name only after choosing a concrete guest. Lifecycle stays CLI/explicit setup; full Spaces MCP is opt-in. call_tool retains upstream execution authority: this is a small discovery surface, not a security sandbox. On this installation cua is /Users/muness1/.local/bin/cua. Downloaded images are retained unless the user requests removal.

## Optional OH adapter

The runtime is computer_use/server.py in the repository, using a Python environment with computer_use/requirements.txt installed. Register it only when mobile or the lightweight virtual-display browser is needed. On this installation it uses /Users/muness1/src/open-horizon-labs/computer-use/.venv-facade/bin/python and /Users/muness1/src/open-horizon-labs/computer-use/computer_use/server.py. Codex keeps computer-use-oh disabled by default; enable its enabled setting for a task and reconnect. Claude's default registration is removed; add that command as computer-use-oh for a task and remove it afterward. This adapter exposes look/do only. Legacy advanced settings do not revive archived tools.

Mobile defaults to @mobilenext/mobile-mcp@1.0.6; CUA_MOBILE_MCP supplies an external command. Local raw Android hierarchy uses CUA_MOBILECLI_COMMAND (JSON argv) or @mobilenext/mobilecli@1.0.16. A custom provider disables local hierarchy reads to avoid crossing devices. Install device agents/grants through provider setup; missing state remains unknown.

Light off-screen OH needs Cua Driver, an installed Chromium executable and a working virtual display. CUA_AGENT_BROWSER_PATH can supply Chromium. The adapter forces an owned browser and required display; legacy user-profile/fallback settings cannot select the host screen. It does not install Chrome, grant permissions or unlock the Mac automatically. Configuration and credentials are external; never print or commit secrets.

Repository README.md and docs/SALVAGE.md govern runtime projection changes. Historical experiments and the bundled sketch describe retained adapter internals, not automatic routing instructions. Offline tests do not launch desktops, device agents or GPU workers.

Optional adapter refusals use who=agent for supported agent-repairable setup or stale binding and who=user for unavailable grants/credentials the user must supply. These labels do not authorize archived routes. Reuse the returned context_id within a task; native/OBO and Spaces have their own binding contracts.
