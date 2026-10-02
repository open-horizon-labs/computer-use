# Computer-use supplement

Use native computer-use tools by default. OH currently has **no automatically preferred route**: the bakeoff did not establish a fair measured win that justifies one.

Two capabilities remain explicitly opt-in:

- **Mobile**: fresh device observations, exact control binding, typed refusals and independent verification through mobile-mcp.
- **Isolated off-screen browser**: an owned browser profile on a required virtual display. No user logins or physical-screen fallback.

The MCP surface exposes only `look` and `do`. Calls without an explicit capability return `native_default` without observing or acting. User-app/OBO, terminal, VNC and specialist model orchestration are archived. Shared observation, matching and verification internals remain where the two capabilities need them.

See [the API contract](docs/FACADE.md), [why use this](WHY.md), [benchmark evidence](docs/BENCHMARK.md), [salvage constraints](docs/SALVAGE.md) and [routing policy](computer_use/ROUTES.json).

## Archive

The full implementation and unpromoted follow-up drafts are preserved on `codex/archive-general-facade-2026-10-02` at `a531b43`. Use Git to recover them; there is no maintained experimental runtime. Sanitized benchmark evidence remains in `experiments/codex-mixed/`.

## Install

Create a Python environment and install `computer_use/requirements.txt`. Register `computer_use/server.py` as an MCP server. The bundled [skill](skills/computer-use/SKILL.md) and its [setup reference](skills/computer-use/references/setup.md) describe explicit capability selection and provider configuration. Reconnect clients after updating.

## Validate

Run the offline checks from `.github/workflows/offline-gates.yml`. They use fixtures and fakes, not the desktop or GPUs. `scripts/check_call_budget.py` preserves historical shared-projection regressions and measures the current MCP schema; those historical scenarios do not describe the active routing policy. `computer_use/check_protocol.py` and `test_native_first.py` check the real active MCP contract. Keep deterministic checks separate from semantic sketch review.
