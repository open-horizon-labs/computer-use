# Setup

Choose the client and execution environment first. A local skill supplies instructions; browser/app tools, permissions, MCP connections and service authentication come from that environment. Installing this folder does not install a driver or connect a ChatGPT workspace to this computer.

## Local skill installation and upgrades

From the repository checkout, with Python 3.11 or newer:

~~~sh
python3 scripts/install_smart_defaults.py --client codex
python3 scripts/install_smart_defaults.py --client codex --check
~~~

Use --client claude for Claude Code, or --client both (the default) for both clients. Codex receives the skill in ~/.agents/skills/computer-use and the compatibility directory ~/.codex/skills/computer-use; Claude Code receives it in ~/.claude/skills/computer-use. Ordinary native tasks need no Cua CLI, Spaces server, OH adapter or model dispatcher.

Use this installer for upgrades too. It removes this checkout's legacy OH registration from Claude and disables it in Codex, preserving unrelated servers and existing Spaces configuration. It replaces the complete skill package when contents differ, including retired files, and backs up the old package under ~/.local/state/computer-use/install-backups/. Backups are outside skill discovery. A differing symlink or unrecognized skill directory requires an explicit resolution; the installer does not modify its target.

The installer checks selected clients' global instructions for the retired cua-capability-dispatch/SKILL.md reference. If found, update that instruction to the current skill and remove obsolete mandatory selector setup, then rerun. It reports the file rather than rewriting unrelated instructions. Repository-level instructions must also agree with the current skill.

--check makes no changes and compares the whole installed package, checks known obsolete global references and verifies that this checkout's legacy OH adapter is inactive. It checks Spaces configuration only with --with-spaces. Passing this check does not prove live tool access, OS grants, account login or ChatGPT workspace installation. After installation, confirm the client discovers computer-use; restart it if needed. Reconnect after MCP configuration changes.

## Optional Cua Spaces

Use Spaces when a separate guest desktop is needed. Install the CLI using the [upstream Cua CLI instructions](https://cua.ai/docs/cua-cli), then verify that cua mcp --help supports --embedded and --permissions. From this checkout:

~~~sh
python3 scripts/install_smart_defaults.py --client codex --with-spaces
python3 scripts/install_smart_defaults.py --client codex --with-spaces --check
~~~

This registers only spaces:list_spaces, spaces:list_tools and spaces:call_tool. It does not create a guest, sign in or install a guest runtime. Set up a usable guest through the [Spaces quickstart](https://cua.ai/docs/spaces/quickstart), then reconnect the client.

For an already migrated installation, the equivalent manual registrations are:

~~~sh
claude mcp add --scope user cua-spaces -- cua mcp --embedded --permissions spaces:list_spaces,spaces:list_tools,spaces:call_tool
codex mcp add cua-spaces -- cua mcp --embedded --permissions spaces:list_spaces,spaces:list_tools,spaces:call_tool
~~~

These commands alone do not retire old OH registrations or update the skill. Prefer the installer when upgrading. Manual registrations require cua on the client's PATH; the installer stores the resolved executable path. On new registrations the installer also sets CUA_CACHE_AUTO_GC=0 and CUA_TELEMETRY=0 (and preserves existing Codex Spaces options).

Fetch Driver schemas by name only after choosing a concrete guest. Lifecycle remains CLI/explicit setup; full Spaces MCP is opt-in. call_tool retains upstream execution authority: a small discovery surface is not a security sandbox. Downloaded images are retained unless the user requests removal.

## Optional OH adapter

Register this adapter only for an explicitly selected mobile or lightweight virtual-display task. From the checkout:

~~~sh
python3 -m venv .venv-facade
.venv-facade/bin/python -m pip install -r computer_use/requirements.txt
TASK_REPO_DIR="$(pwd)"
codex mcp add computer-use-oh -- "$TASK_REPO_DIR/.venv-facade/bin/python" "$TASK_REPO_DIR/computer_use/server.py"
~~~

For Claude Code, use the same interpreter and script with claude mcp add --scope user computer-use-oh -- followed by those two paths. On an existing disabled Codex registration, set its enabled value to true instead of adding it again. Reconnect for the task. Afterwards remove the registration with codex mcp remove computer-use-oh or claude mcp remove --scope user computer-use-oh, or restore Codex's enabled = false.

The adapter exposes look/do by default. It does not perform native/OBO, terminal, VNC or specialist-model orchestration. Legacy advanced settings do not revive archived routes.

Mobile defaults to @mobilenext/mobile-mcp@1.0.6; CUA_MOBILE_MCP supplies an external command. Local raw Android hierarchy uses CUA_MOBILECLI_COMMAND (JSON argv) or @mobilenext/mobilecli@1.0.16. A custom provider disables local hierarchy reads to avoid crossing devices. Install device agents/grants through provider setup; missing state remains unknown.

Light off-screen OH needs Cua Driver, installed Chromium and a working virtual display. CUA_AGENT_BROWSER_PATH can supply Chromium. The adapter forces an owned browser and required display; legacy user-profile/fallback settings cannot select the host screen. It does not install Chrome, grant permissions or unlock the Mac automatically. Configuration and credentials are external; never print or commit secrets.

Repository README.md and docs/SALVAGE.md govern runtime projection changes. Historical experiments and the bundled sketch describe retained adapter internals, not automatic routing instructions. Offline tests do not launch desktops, device agents or GPU workers.

Optional adapter refusals use who=agent for supported agent-repairable setup or stale binding and who=user for unavailable grants/credentials the user must supply. These labels do not authorize archived routes. Reuse the returned context_id within a task; native/OBO and Spaces have their own binding contracts.

## ChatGPT installation

Local filesystem skills, ChatGPT workspace skills and plugins have separate installation and access controls. See [official skill controls](https://learn.chatgpt.com/docs/enterprise/skills). These commands configure local Claude Code/Codex clients; they do not install a workspace skill or grant ChatGPT access to this Mac.

For ChatGPT using an authorized connected computer, verify the skill and required tools are available on that execution host. For cloud-only execution, local stdio commands, loopback services and the Mac's secret store require a supported connection or a service reachable from that environment. Uploading a skill archive supplies its contents, not those connections.
