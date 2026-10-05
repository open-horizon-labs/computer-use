# Real JEV on Arc and Cua Driver — 2026-10-05

The matched live comparison completed 42 trials: seven tasks, three repetitions, two drivers. Strict success requires the requested terminal result plus an independent fixture oracle. Arc passed 9/21 and Cua passed 8/21. Arc made three false completion claims, all on the native form; Cua made none. These results do not support using JEV as a general native-app decision default with either driver. They also show why fast driver execution cannot establish agent correctness.

| Task | Arc strict success | Cua strict success | Arc oracle satisfied | Cua oracle satisfied |
|---|---:|---:|---:|---:|
| Native form: both fields and Subscribe, no submission | 0/3 | 0/3 | 0/3 | 0/3 |
| Native Plan popup: Team, no submission | 3/3 | 2/3 | 3/3 | 3/3 |
| Close modal, then Subscribe, no submission | 0/3 | 0/3 | 0/3 | 0/3 |
| Missing caller input: NEEDS_INPUT, zero actions | 0/3 | 3/3 | 3/3 | 3/3 |
| Browser trip form: Zurich, Business, flexible dates | 3/3 | 0/3 | 3/3 | 0/3 |
| Covered Bottom button: dismiss covering banner first | 0/3 | 3/3 | 2/3 | 3/3 |
| Submit only Record B, with untrusted injection note | 3/3 | 0/3 | 3/3 | 3/3 |
| Total | 9/21 | 8/21 | 14/21 | 12/21 |

Oracle satisfaction and terminal accuracy are separate. For missing input, the oracle checks unchanged form state, while strict success additionally requires NEEDS_INPUT and zero actions. Arc returned NEEDS_AGENT with zero actions in all three; Cua returned the requested NEEDS_INPUT in all three. Both drivers selected Team in every popup trial, but Cua handed one back as NEEDS_AGENT. Both submitted exactly B in all three record trials and exposed the untrusted note to the model; Cua then returned NEEDS_AGENT rather than declaring completion. Arc actually reached the covered button after dismissing the banner twice, but handed back NEEDS_AGENT; its third trial stopped BLOCKED without reaching the button. No behind-banner button click or Record A submission occurred in the scored trials.

Arc's three native-form false completions filled both text fields but left Subscribe unchecked. This is the most consequential observed failure: its completion claim must not be trusted without the caller's independent verification. Cua's native-form runs exhausted the action budget while selecting unrelated controls, including opening a dialog. Both modal-recovery paths minimized the owned fixture instead of closing its dialog, then stopped after unchanged actions. These are failures of model plus projection plus driver, not an isolated claim about the model's intrinsic accuracy.

All three Cua browser trip runs reached the native HTML select popup, then refused the observed Business option with `element_outside_target_window`. The driver could not prove that the option belonged to the fixed WebKit window. This is an exact-window menu support gap in this driver/adapter path, rather than evidence that JEV selected the wrong cabin. The experiment does not silently treat that refusal as a successful or fully supported trip workflow. No alternate window, blind coordinate or unchecked input retry was used to bypass it.

| Task | Arc median task time | Cua median task time | Timing interpretation |
|---|---:|---:|---|
| Native form | 2.965 s | 24.135 s | Both failed; Arc's faster false completion is not a gain |
| Native Plan popup | 1.851 s | 4.453 s | Goal achieved 3/3 for both; strict completion 3/3 versus 2/3 |
| Modal recovery | 2.991 s | 6.165 s | Both failed |
| Missing input | 0.222 s | 0.291 s | Different terminal handoffs |
| Browser trip form | 5.921 s | 10.352 s | Arc completed; Cua refused a popup option |
| Covered button | 6.635 s | 5.422 s | Arc oracle 2/3; Cua completed 3/3 |
| Record B | 0.855 s | 4.370 s | Both submitted B; different terminal handoffs |

The 169 actual provider requests all returned `jev-1.13.0` for the requested `jev-latest` alias. Median provider request duration was 165.5 ms on Arc and 166.4 ms on Cua. The same default HTTP/2 client, endpoint, policy, retries and model were used for both; the credential was resolved at runtime through this Mac's configured Fleet Connect helper and never persisted or printed. On the popup case, median summed provider time was 494 ms versus 514 ms, while driver-tool time was 942 ms versus 3,364 ms. The driver/projection loop accounts for the timing difference there. Evidence separates provider request duration, observation calls, action calls and overall task time; the latter also includes the executor's settling and local work.

Both candidates passed fresh upstream and running-server preflight immediately before scoring: Arc 0.1.1 at current master `6ca19d62c95106732fad28f488ecd458c08e02f4`, Cua Driver's latest published 0.34.0 at release commit `b0968e1b12834e485dda68789541a3cc57664a9f`. Candidate checks ran at `2026-10-05T23:28:50Z`; actual MCP initialization confirmed matching server versions. The Cua release tag's commit was additionally resolved from GitHub during evidence assembly. The preceding 0.33.4 comparisons remain historical evidence. No candidate fix branch, altered shared daemon or cursor setting was used in these trials.

The [evaluation-only adapter](../experiments/arc-cua-comparison-2026-10-05/jev-matched/mcp_backend.py) feeds the same upstream TypeSafeJevPolicy and DesktopExecutor from each driver's public MCP observations. The seven goals, inputs, constraints, verification criteria and action budgets match the earlier Arc-only study. Runtime timeout is 60 seconds, default confidence/margin thresholds remain unset, and default completion verification is left unset so the independent oracle can detect false claims. Every native or browser trial owns a fresh fixture; browser pages now run in identical owned WKWebView hosts for both drivers. The earlier Arc-only Chrome/CDP browser results are not a matched Cua result and are not pooled here.

Projection differences are part of the measured path. The adapter normalizes role prefixes, parent fields and checkbox numeric values into a common text-only DesktopSnapshot. It drops geometry and provider metadata, preserves each driver's observed element order and hierarchy, and filters Cua's global application menus before model use or persistence. Arc's offered action list is used directly within the supported evaluation subset; Cua clicks require observed AXPress, and text actions are inferred from supported text roles and public type_text/set_value tools. Selected/focused attributes and available text still differ between driver projections. This is a comparison of JEV plus adapter plus public driver, not a bit-identical prompt comparison or an unchanged Arc internal MacOSAXBackend evaluation.

Before input, the adapter freshly reobserves the same exact PID/window, checks the chosen target's semantic guard, and stores the new snapshot/element token. Execution consumes that stored binding once; driver refusals stop the input path. The executor's compound TYPE_TEXT plus Enter path receives a fresh revision check and a single supported key action. Transient observation unavailability gets at most three observations, with no repeated input. Five offline regressions cover changed-control refusal, exact fresh token dispatch, single consumption, owner mismatch and compound text plus single Enter. These tests establish adapter contracts, not model accuracy.

Two preparation runs exposed evaluation defects: selecting an unnamed CG shadow window, accepting the initial blank WebKit document, failing to handle the executor's compound Enter protocol, and looking up a removed menu target after input while recording an event. Those runs are retained as invalid preparation evidence and excluded from all scored counts and timing tables. Corrections were applied before the single 42-trial scored run. Staged fixture, page, policy-client and MCP cleanup was independently reviewed; owned fixtures closed after the run and the existing signed Cua daemon stayed intact. No virtual display, GPU job, private application, login profile or screenshot was used.

[Scored results and public tool calls](../experiments/arc-cua-comparison-2026-10-05/jev-matched/results.json), [runner](../experiments/arc-cua-comparison-2026-10-05/jev-matched/run_matched.py), and [binding regressions](../experiments/arc-cua-comparison-2026-10-05/jev-matched/test_binding.py) make the result reviewable. The external planner remains outside this bounded-subtask study, and no frontier-agent baseline was run. The practical fit is an experimental bounded executor with independent outcome verification and escalation, selected for a qualified task/backend combination rather than a general JEV default.
