# Computer use: smart defaults

A skill for choosing the smallest useful computer-use route and completing delegated work reliably.

- **OBO:** native tools in the user's apps and logged-in browser. Routine foreground interaction is part of the delegation; recover from ordinary friction without asking again.
- **Light off-screen:** an available isolated browser for small tasks without user logins. The retained OH virtual-display browser is optional when its prerequisites work; it uses a virtual monitor, not a Mission Control move.
- **Guest desktop:** Cua Spaces with only three MCP tools and Driver schemas discovered by name.
- **Mobile:** native support where available; the retained OH adapter is optional.

Start with [the skill](skills/computer-use/SKILL.md). It loads route-specific guidance only when needed. Native tools remain the overall default; no OH route has earned automatic performance preference. [Why](WHY.md) and [benchmark evidence](docs/BENCHMARK.md) explain the limits.

## Install

From the checkout, with Python 3.11 or newer:

~~~sh
python3 scripts/install_smart_defaults.py --client codex
python3 scripts/install_smart_defaults.py --client codex --check
~~~

Use --client claude for Claude Code or --client both (the default). This installs the skill, retires only this checkout's legacy OH registration and preserves unrelated client configuration. Native browser/app tools come from the client; skill-only installation needs no Cua CLI or Spaces server.

For a separate guest desktop, install Cua CLI and add --with-spaces to both commands. This registers the slim three-tool Spaces profile; guest creation and authentication remain separate setup. Reconnect after MCP changes and confirm the skill is discovered.

Use the installer for upgrades: replaced skill packages are backed up outside skill discovery, retired files are removed from the active package, and obsolete global instruction references fail verification. --check verifies local files/configuration; it does not establish live tool access or install anything into a ChatGPT workspace.

[Setup](skills/computer-use/references/setup.md) contains the client paths, migration details, optional Spaces/OH commands and ChatGPT execution boundaries.

## Optional runtime and evidence

computer_use/server.py remains available for explicitly selected mobile and lightweight virtual-display browsing. It exposes look/do, fresh binding, typed refusals and independent verification; it is not registered/enabled by default. It does not perform OBO, terminal, VNC or specialist model orchestration. [Runtime contract](docs/FACADE.md), [salvage](docs/SALVAGE.md) and [routing policy](computer_use/ROUTES.json) govern that adapter.

The full pre-reduction runtime is preserved on codex/archive-general-facade-2026-10-02 at a531b43. Historical fixtures are evidence, not instructions to revive it. Spaces passed a bounded form qualification; this does not prove mobile parity, logged-in teleport, locked-host execution or token superiority. [Progressive Spaces evidence](docs/SPACES-PROGRESSIVE-2026-10-02.md).

## Validate

Skill/setup changes use .github/workflows/skill-checks.yml: isolated installer regressions, valid skill metadata and progressive reference links. Review routing with realistic OBO, lightweight, guest and mobile scenarios. These checks do not claim live computer-use accuracy.

Runtime/projection changes additionally use .github/workflows/offline-gates.yml. Its large legacy suite, simulations and mutation checks cover optional adapters and retained experiments, not the skill product. Path filters keep that suite out of ordinary skill/setup edits; workflow_dispatch allows an intentional full run. Retained call budgets apply to the optional OH adapter; Spaces metadata measurements are separate. Preserve current binding, no blind coordinates, bounded recovery and independent outcome verification.
