# arc-cua evaluation and salvage — 2026-10-05

> The requested live follow-up is complete at the bounded driver-comparison scope: see [the empirical comparison](ARC-CUA-EMPIRICAL-COMPARISON-2026-10-05.md). This document preserves the initial source evaluation; its statement that no live work was performed applies to that initial phase only.

Recommendation: qualify the standalone macOS driver as an explicitly selected native OBO capability for background work in existing user apps. Do not replace the routing skill, adopt its decision-model executor by default, or treat its invisible display as a guest environment or a fix for our display lifecycle incidents.

Reviewed upstream commit `6ca19d62c95106732fad28f488ecd458c08e02f4` (version 0.1.1) through a temporary source checkout. This was a static source/documentation evaluation: no installation, MCP registration, desktop input, virtual display creation or live benchmarks. Upstream measurements remain upstream evidence. Existing local work was left untouched.

## Salvage report

**Reason:** Extract useful mechanisms from a candidate stack without restarting the broad native facade retired by this repo. This evaluation did not identify a failed current session requiring a restart.

**Original aim:** Complete delegated computer use with intent-based routing, fresh exact targets, bounded recovery and independently verified effects, while reducing interaction overhead.

## Learnings

1. The separable driver is the useful boundary. `Driver` and its MCP server work without the decision model. Exact PID/window targets, AX-first actions, structural notification tracking, typed stale/changed results and explicit settling are compatible with our operational intent. Background control can preserve the actual user app/session rather than substituting a new profile.
2. Upstream's benchmark compares arc 0.1.1 with Cua Driver 0.32.0 on one M5 Mac running macOS 26.6.2. It reports 63/68 versus 55/68 web variants and a 5.1× geometric speed advantage on the 50 both solved. These tasks informed arc's development; they are not held-out general reliability evidence or a benchmark of our installed client tool. Driver timings omit an actual planner's reasoning cost.
3. Trade-offs are concrete: upstream reports 13 versus 380 Obsidian elements, no HTML5 drag-and-drop support, and delayed sheets absent from the settled view. Refusing a later stale action can protect input without making that earlier observation complete.
4. Source is less absolute than the driver prose. `Driver._check` consults the structural journal, then refuses when fresh element-ID sets differ; equal sets permit continuation. The journal is best effort and can be unavailable. Raw input accepts `snapshot=None`. These mechanisms need tests against semantic target changes and notification loss; structural freshness is not proof of record identity.
5. `run_command` operates on the app's key window, rather than binding command execution to the observed window. `_observe_after` may return another window after the original closes. Both require explicit ownership handling by a caller.
6. `DesktopExecutor` accepts model completion when no `RuntimeConfig.verify` callback is supplied. Typed choices and caller-owned input literals are useful, but do not establish independent task verification or enforce every prose constraint. The model selection role would need separate qualification.
7. Background event delivery uses private SkyLight/WindowServer APIs. Minimized/hidden input can park real windows on a virtual display. Upstream documents that a killed server can reveal those windows on the user's screen. This is host interaction, not guest isolation, and must be evaluated against the lifecycle faults in the current SpaceO empirical report.

## Frame shift

“Another fast autonomous CUA stack” → “A potentially useful native driver with a separately optional decision layer.” Driver speed, decision accuracy and display safety need separate evidence. Our earlier salvage already says to qualify specialists before training or adopting a router; this candidate does not change that lesson.

## Reusable fragments and guardrails

Retain the notification journal, cheap event-driven settling, exact window identity, AX menu discovery and independent fixture scoring as mechanisms worth studying. Require snapshot-bound raw input, same-record semantic revalidation, explicit handling of app-wide commands and changed post-action windows, and independent expected-effect checks. Use a single display/window owner and verify retirement externally. Preserve fault records; do not bypass current host recovery requirements for an arc trial.

## Fresh start recommendation

After operator recovery establishes a safe reserved host, compare the standalone driver against the actual current native tool on matched tasks: native form, multi-window document, Electron/custom listbox, delayed sheet, changed target, hidden/minimized app, cancellation and teardown. Record independent completion, unintended effects, focus/pointer disturbance, wall time, agent-visible calls and tokens where available. Separate AX-only trials from virtual-display trials. Promote only the measured capability that wins without weaker binding, completion or ownership guarantees. Keep native-first routing and the optional OH adapter's existing tool budget unchanged.

Sources: [upstream driver](https://github.com/shhivv/arc-cua/blob/6ca19d62c95106732fad28f488ecd458c08e02f4/docs/driver.md), [benchmark](https://github.com/shhivv/arc-cua/blob/6ca19d62c95106732fad28f488ecd458c08e02f4/BENCHMARKS.md), [driver implementation](https://github.com/shhivv/arc-cua/blob/6ca19d62c95106732fad28f488ecd458c08e02f4/src/arc_cua/driver.py), [runtime](https://github.com/shhivv/arc-cua/blob/6ca19d62c95106732fad28f488ecd458c08e02f4/src/arc_cua/runtime.py), [structural journal](https://github.com/shhivv/arc-cua/blob/6ca19d62c95106732fad28f488ecd458c08e02f4/src/arc_cua/backends/macos_changes.py), [local lifecycle evidence](SPACEO-EMPIRICAL-COMPARISON-2026-10-03.md), [existing salvage](SALVAGE.md).
