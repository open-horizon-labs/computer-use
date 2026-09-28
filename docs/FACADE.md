# Local CUA task tools

The facade gives an agent one coherent, evidence-first interface to desktop work. It joins fresh Cua Driver observations, page reading, action selection, execution and independent verification while keeping each boundary explicit. Agents should use these tools directly instead of writing task-specific shell wrappers around model endpoints or Driver calls.

Cua Driver still observes and acts on the Mac. The facade sends bounded evidence to the configured specialist for the task: NuExtract3 reads requested fields from observed page records; Jev (with configured Qwen escalation) or Julia chooses among contextual alternatives; qualified GLiNER2 spans handle the narrow typed-field matching route; SystemOne handles visual choice or screenshot verification. Exact unique name/role selection bypasses a chooser by design. Provider routing and credentials come from external runtime configuration, so remote inference does not move desktop control off the Mac. Check `cua_trace` when you need the route and timing actually used.

## Agent workflow

Treat a UI task as an ordered sequence of evidence, decision, action and verification steps. Keep the user's prerequisites intact, select only the next unmet step, and verify its visible result before continuing. For each state transition:

1. Use `cua_windows` to find the relevant existing window, then `cua_observe` to obtain a fresh screenshot and accessibility tree. The returned snapshot and element IDs define the only evidence currently available.
2. If the task depends on page content, call `cua_read` with the observed record roots and only the fields/predicates needed. NuExtract3 returns grounded values tied to those source records; missing or ambiguous values remain unknown. Keep records separate and avoid whole-page roots that combine several results.
3. Call `cua_choose` for the next action. Use semantic mode for contextual alternatives, spans for the qualified typed-field contract, visual mode when image evidence is needed, or exact mode only for a genuinely unique observed name/role. Model scores are not calibrated confidence. A bypass, singleton, unsupported request, provider failure or incomplete evidence is not chooser success; reconcile the state or report a blocker.
4. Execute only the opaque selection handle with `cua_act`. The facade retains the original Driver arguments and checks that the observed state is unchanged before acting. Never invent element IDs, coordinates or Driver arguments.
5. Call `cua_verify` with a concrete visible postcondition. Treat delivery as an attempted action, not proof it worked. Use the returned fresh observation to reconcile failures and ground the next step.
6. Keep retries bounded and close task-scoped model workers with `cua_finish` when done. This preserves Cua Driver and the user's windows.

Each step must be grounded again after the UI changes. An old candidate, reading or selection does not authorize a later action. If a route cannot establish the requested evidence, stop at unknown/blocker rather than guessing. Do not use raw shell or direct Driver/model wrappers as an alternate path for ordinary UI decisions; use a documented capability gap only when the facade explicitly cannot express the operation, and preserve fresh observation, bound arguments and independent verification.

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
| `cua_windows` | Local Driver inventory; optional exact `title` filter; reuse the requested window |
| `cua_observe` | Fresh AX elements/parent IDs, screenshot, quality, opaque snapshot |
| `cua_read` | NuExtract fields and predicates over nonoverlapping observed record roots |
| `cua_choose` | Configured Jev/Julia contextual alternatives, qualified GLiNER2 spans, visual choice, or unique exact name/role |
| `cua_act` | One opaque selection; no caller-supplied Driver arguments |
| `cua_verify` | Independent fresh exact or screenshot postcondition check, returning that observation and screenshot |
| `cua_trace` | Content-free actual routes, startup/decision timing and outcomes |
| `cua_finish` | Close task workers and invalidate handles; preserve Driver and user windows |

`fields` maps field names to `{description, type}`. Use dispatcher types such as `text`, `number`, `money`; `string` aliases `text` for reads; money fields also require `currency: USD`. Predicates use `{field, op, value}`. Describe meanings without injecting expected answers. Choose a separate observed root for every logical record. Table rows preserve cell boundaries; there is no inferred header/value mapping. Coverage is the caller's assertion about the requested scope, not a claim that a site has no more results.

For record-backed actions, pass the returned `reading` to `cua_choose`. Map every eligible root to an observed descendant through `record_actions` when necessary. Additional `predicates` on the choice conjunctively filter the cached reading without another extraction. They cannot revive earlier exclusions. Candidate IDs can name all eligible record roots or their mapped controls; omit them when the mapping already describes the scope. The original complete mapping is also accepted when an additional predicate narrows it. Every provided join is checked, and an eligible record with no compatible enabled control blocks selection. Put schemas on `cua_read`; ordering remains a spans-mode feature. Criteria supplied to incompatible modes are rejected, never silently ignored. Unknown or incomplete filtered scopes defer. All eligible records must survive until selection. A semantic singleton without a complete filtered reading defers: it cannot serve as model confirmation of a caller's preselected winner.

Exact mode searches the whole observed scope even if a caller supplies fewer candidates. Complete rectangular AX tables may expose matching cell subtrees through both rows and columns. The facade annotates those aliases and counts each once only when every paired cell subtree, observed attribute and positive frame agrees. It does not merge by labels or coordinates alone. Missing cells, structural/content/frame differences and genuine repeated controls remain ambiguous. Driver object identity is not exposed: this is a qualified table-projection rule, not general node equivalence. Exact bypasses and singleton filtered choices are not chooser accuracy evidence.

## Binding and limits

Selections retain immutable server-owned requests/arguments. Before acting, the facade recaptures the window and compares the full AX content, hierarchy and frames (excluding expiring Driver tokens). Changed content refuses execution. Only an unchanged observation permits rebinding tokens to the fresh Driver snapshot. Visual choices additionally require unchanged screenshot bytes. Selections are single-use even when delivery fails. This narrows but cannot eliminate a UI race between observation and execution.

The facade supports native AX click and text entry. Keyboard shortcuts, browser-specific navigation and canvas coordinates still require a declared raw Driver fallback. It cannot establish terminal readiness from AX alone. Tool delivery is not success; verification remains mandatory before reporting an effect. Missing evidence and provider failures produce unknown, never success. Read-only annotations describe intended tool effects; observations can still foreground a window.

Provider deadlines are bounded; use at most one retry after reconciling state. Observe/act calls may contain multiple bounded Driver operations. Caller task deadlines must cover the whole workflow. Close workers with `cua_finish`; server shutdown also closes them. This server is local stdio, not a network HTTP service.

## Verification

```sh
python3 -m unittest discover -s facade -p 'test_*.py'
# Also check the actual MCP schema/response contract, without desktop or models:
.venv-facade/bin/python facade/check_protocol.py
```

See [adoption evidence](FACADE-ADOPTION.md). Tool discovery and safe binding passed the local trial; model accuracy and autonomous sequencing are not established by that result.

[Second fresh-agent smoke](FACADE-SMOKE-2.md) covers the record/action contract fixes and their bounded adoption follow-up.

[Duplicate-control and visual-verification repair evidence](FACADE-REMAINING-FIXES.md) covers live positive/negative checks and rejected alternatives.
