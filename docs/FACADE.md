# Local CUA task tools

The `cua-task` MCP server makes the configured models available as ordinary agent tools. Cua Driver runs on the Mac and retains observation/execution. Model inference follows external runtime configuration; remote GPU inference does not move desktop control remotely.

## Install

Requires Python 3.10+, the installed and authorized Cua Driver, and providers configured per [setup](../skills/cua-capability-dispatch/references/setup.md). Reuse the normal browser profile and existing Driver setup.

From the runtime checkout:

```sh
python3 -m venv .venv-facade
.venv-facade/bin/pip install -r facade/requirements.txt
codex mcp add cua-task -- "$PWD/.venv-facade/bin/python" "$PWD/facade/server.py"
codex mcp get cua-task --json
```

Start a fresh agent session to discover the tools. Skill installation alone does not register an MCP server. `CUA_DRIVER` overrides the default `~/.local/bin/cua-driver`. Runtime commands, endpoints and secrets stay outside this repository. No model starts merely to list tools.

## Tools

| Tool | Contract |
|---|---|
| `cua_windows` | Local Driver inventory; reuse the requested window |
| `cua_observe` | Fresh AX elements/parent IDs, screenshot, quality, opaque snapshot |
| `cua_read` | NuExtract fields and predicates over nonoverlapping observed record roots |
| `cua_choose` | Configured Jev/Julia contextual alternatives, qualified GLiNER2 spans, visual choice, or unique exact name/role |
| `cua_act` | One opaque selection; no caller-supplied Driver arguments |
| `cua_verify` | Independent fresh exact or screenshot postcondition check |
| `cua_trace` | Content-free actual routes, startup/decision timing and outcomes |
| `cua_finish` | Close task workers and invalidate handles; preserve Driver and user windows |

`fields` maps field names to `{description, type}`. Use dispatcher types such as `text`, `number`, `money`; `string` aliases `text` for reads; money fields also require `currency: USD`. Predicates use `{field, op, value}`. Describe meanings without injecting expected answers. Choose a separate observed root for every logical record. Table rows preserve cell boundaries; there is no inferred header/value mapping. Coverage is the caller's assertion about the requested scope, not a claim that a site has no more results.

For record-backed actions, pass the returned `reading` to `cua_choose`. Map every eligible root to an observed descendant through `record_actions` when necessary. Unknown or incomplete filtered scopes defer. All eligible records must survive until selection. A semantic singleton without a complete filtered reading defers: it cannot serve as model confirmation of a caller's preselected winner.

Exact mode searches the whole observed scope even if a caller supplies fewer candidates. Duplicate AX projections remain ambiguous; the facade does not merge controls by equal labels. Exact bypasses and singleton filtered choices are not chooser accuracy evidence.

## Binding and limits

Selections retain immutable server-owned requests/arguments. Before acting, the facade recaptures the window and compares the full AX content, hierarchy and frames (excluding expiring Driver tokens). Changed content refuses execution. Only an unchanged observation permits rebinding tokens to the fresh Driver snapshot. Visual choices additionally require unchanged screenshot bytes. Selections are single-use even when delivery fails. This narrows but cannot eliminate a UI race between observation and execution.

The facade supports native AX click and text entry. Keyboard shortcuts, browser-specific navigation and canvas coordinates still require a declared raw Driver fallback. It cannot establish terminal readiness from AX alone. Tool delivery is not success; verification remains mandatory before reporting an effect. Missing evidence and provider failures produce unknown, never success. Read-only annotations describe intended tool effects; observations can still foreground a window.

Provider deadlines are bounded; use at most one retry after reconciling state. Observe/act calls may contain multiple bounded Driver operations. Caller task deadlines must cover the whole workflow. Close workers with `cua_finish`; server shutdown also closes them. This server is local stdio, not a network HTTP service.

## Verification

```sh
python3 -m unittest discover -s facade -p 'test_*.py'
```

See [adoption evidence](FACADE-ADOPTION.md). Tool discovery and safe binding passed the local trial; model accuracy and autonomous sequencing are not established by that result.
