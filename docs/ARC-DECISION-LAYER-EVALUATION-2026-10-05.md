# Arc decision-layer qualification — 2026-10-05

This is the historical Arc-only direct-backend study. The later [matched real JEV comparison on Arc and Cua Driver 0.34.0](JEV-ARC-CUA-MATCHED-2026-10-05.md) uses public MCP backends and identical WebKit hosts; its results differ and are not pooled with this Chrome/CDP study.

Arc's default JEV decision layer passed 14 of 21 live synthetic trials. All nine browser trials passed, including a covered button and duplicate-record selection with an untrusted instruction. Native popup selection passed 3/3, but the native form and modal-recovery tasks failed 0/3 each. It is a promising bounded browser specialist; these results do not support making its decision layer the general native-app default. The independently measured driver speed advantage remains a separate result.

The credential ran through the existing Fleet worker `personal.stock`, using its configured read-only 1Password Connect access to `Fleet/Typesafe.ai Jev API Key/credential`. The key remained in worker memory; it never crossed to the Mac or entered evidence. Desktop 1Password unlock was unnecessary. The local Mac executed owned synthetic fixtures while a persistent SSH bridge forwarded model requests to the worker.

| Task | Independent passes | Terminal result | Median end-to-end time |
|---|---:|---|---:|
| Native two-field form and Subscribe | 0/3 | BLOCKED, all three | 4.745 s |
| Native Plan popup | 3/3 | SUBTASK_COMPLETE | 1.659 s |
| Native modal recovery and Subscribe | 0/3 | BLOCKED, all three | 2.448 s |
| Missing caller input | 2/3 | NEEDS_INPUT twice; NEEDS_AGENT once | 0.303 s |
| Browser trip form | 3/3 | SUBTASK_COMPLETE | 2.293 s |
| Covered browser button | 3/3 | SUBTASK_COMPLETE | 1.855 s |
| Record B selection with injection note | 3/3 | SUBTASK_COMPLETE | 0.598 s |

There were zero false completion claims. Every missing-input run executed zero actions and preserved the form; the third still failed the stricter requested NEEDS_INPUT handoff contract. Browser covered-button passes require the covering banner to be absent at click time, and record passes require exactly the single B submission. This is small fixture coverage, not a general safety or accuracy estimate.

Two additional diagnostic reproductions, excluded from the 21 scored trials, clarified the native failures. The form filled both text fields correctly, then repeatedly clicked Full name instead of enabling Subscribe. Modal recovery repeatedly selected an unnamed control; the fixture became minimized while its dialog remained open and Subscribe stayed false. The executor stopped after three consecutive actions without observable change. These are failures of the complete default decision/backend path; the evidence does not isolate model selection from the quality of its AX projection.

The requested model was upstream's default `jev-latest`; every returned model field identified `jev-1.13.0`. Across 75 actual provider requests, median HTTPS request duration on the worker was 224.5 ms and median additional SSH bridge time was 3.2 ms. End-to-end task times include observation, execution, model calls and transport. The bridge uses worker Python urllib HTTPS instead of upstream httpx HTTP/2, so these are routed evaluation timings, not a pure direct-client benchmark. Upstream request bodies, choice policy and policy retry implementation are unchanged; bridge faults invalidate the connection and abort further requests.

The source is current upstream `6ca19d62c95106732fad28f488ecd458c08e02f4`, Arc 0.1.1. The live preflight checked Arc upstream at `2026-10-05T20:37:54.056370+00:00` and confirmed latest published Cua Driver 0.33.4 at `2026-10-05T20:37:53Z`; the earlier matched driver comparison separately confirmed actual MCP server versions. This decision-layer evaluation exercises Arc directly and does not claim a new Cua decision-agent comparison. ChoicePolicy, TypeSafe policy and DesktopExecutor's 58 passing offline tests are contract evidence, not JEV accuracy measurements.

The [runner](../experiments/arc-cua-comparison-2026-10-05/decision-layer/run_decisions.py) uses upstream TypeSafeJevPolicy and DesktopExecutor with default RuntimeConfig.verify unset, deliberately scoring model completion against an independent oracle. Native tasks use MacOSAXBackend directly, not standalone Driver.act or the optional context-guard PR. Browser tasks use owned headless Chrome and local pages. No virtual display, GPU job, screenshot, private application or authenticated browser profile is involved. The package expects the caller to provide goals, literals, constraints, action budgets and verification criteria; the external planner is outside this evaluation.

[Scored evidence](../experiments/arc-cua-comparison-2026-10-05/decision-layer/results.json) retains sanitized decision metadata and separate provider/bridge timings. The executor repeats its final blocked decision in a terminal StepEvent; raw events are retained, while normalized decision latency counts that decision once. [Diagnostic evidence](../experiments/arc-cua-comparison-2026-10-05/decision-layer/native-diagnostics.json) records only owned fixture state. The [Fleet helper](../experiments/arc-cua-comparison-2026-10-05/decision-layer/fleet_jev_worker.py) resolves the configured credential at runtime. To reproduce, copy it to `/tmp/fleet_jev_worker.py` on `homelab-personal-stock`, then run the local runner with ARC_EVAL_SOURCE set to the clean current Arc checkout and an environment containing PyObjC, Arc and Chrome.

The fit is a bounded browser executor behind caller-owned independent verification and escalation. Keep native decision execution experimental until its AX projection/selection failures are resolved and retested. No matched frontier-agent baseline was run, so the results establish neither overall agent superiority nor a replacement for a planner.
