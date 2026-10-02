# Computer use: smart defaults

A skill for choosing the smallest useful computer-use route and completing delegated work reliably.

- **OBO:** native tools in the user's apps and logged-in browser. Routine foreground interaction is part of the delegation; recover from ordinary friction without asking again.
- **Light off-screen:** an available isolated browser for small tasks without user logins. The retained OH virtual-display browser is an optional fallback when its prerequisites work.
- **Guest desktop:** Cua Spaces with only three MCP tools and Driver schemas discovered by name.
- **Mobile:** native support where available; the retained OH adapter is optional.

Start with [the skill](skills/computer-use/SKILL.md). It loads route-specific guidance only when needed. Native tools remain the overall default; no OH route has earned automatic performance preference. [Why](WHY.md) and [benchmark evidence](docs/BENCHMARK.md) explain the limits.

## Install

Copy skills/computer-use into the client's skill directory (~/.claude/skills for Claude, ~/.agents/skills for Codex). Install Cua CLI separately, then register the slim Spaces profile:

```sh
claude mcp add --scope user cua-spaces -- cua mcp --embedded --permissions spaces:list_spaces,spaces:list_tools,spaces:call_tool
codex mcp add cua-spaces -- cua mcp --embedded --permissions spaces:list_spaces,spaces:list_tools,spaces:call_tool
```

For a local installation of both clients, scripts/install_smart_defaults.py copies the skill, registers slim Spaces and disables/removes only this checkout's default OH adapter registration; --check verifies the result without changing it. It leaves unrelated native servers in place.

Reconnect clients. The skill keeps Spaces task-selected even though its three discovery tools are registered. Creation/deletion stays CLI setup. Do not fetch the full Driver catalog. call_tool retains broad upstream authority: fewer tool schemas are not a security boundary. [Setup](skills/computer-use/references/setup.md) covers optional adapters and local paths.

## Optional runtime and evidence

computer_use/server.py remains available for explicitly selected mobile and lightweight virtual-display browsing. It exposes look/do, fresh binding, typed refusals and independent verification; it is not registered/enabled by default. It does not perform OBO, terminal, VNC or specialist model orchestration. [Runtime contract](docs/FACADE.md), [salvage](docs/SALVAGE.md) and [routing policy](computer_use/ROUTES.json) govern that adapter.

The full pre-reduction runtime is preserved on codex/archive-general-facade-2026-10-02 at a531b43. Historical fixtures are evidence, not instructions to revive it. Spaces passed a bounded form qualification; this does not prove mobile parity, logged-in teleport, locked-host execution or token superiority. [Progressive Spaces evidence](docs/SPACES-PROGRESSIVE-2026-10-02.md).

## Validate

Run .github/workflows/offline-gates.yml checks for runtime/projection changes. They use fixtures/fakes, not desktops or GPUs. Retained call budgets apply to the optional OH adapter; Spaces metadata measurements are separate. Verify actual installed MCP schemas and skill routing independently of static lint. Preserve current binding, no blind coordinates, bounded recovery and independent outcome verification.
