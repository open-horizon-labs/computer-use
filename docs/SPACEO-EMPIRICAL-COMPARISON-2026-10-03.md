# SpaceO versus our virtual screen — empirical comparison

## Recommendation

Keep our observation binding and invest in a small, guarded virtual-display backend. Contribute the narrow SpaceO admission fixes upstream. Do not switch wholesale, adopt SpaceO's live ordinals as saved target references, or commit to a permanent broad fork. The opt-in hybrid is now implemented and deterministically tested: our binding and verification above SpaceO's ownership and teardown machinery. Live qualification still must establish health-transition behavior, cleanup and recovery before any switch. Neither backend is qualified for unattended desktop isolation by these trials.

The immediate priority is retirement and launch focus, followed by a reserved-host lifecycle/capture/recovery matrix. The renderer experiment supports preserving our binding contract; it does not establish model accuracy, general task success, latency advantage or production driver superiority.

## Evidence

Tests ran on this Apple Silicon Mac, macOS 27.0. The SpaceO contribution derives from upstream `a858236cc3ca57653b49a244a3876f20a766bd71`; native idle parity is committed as `8ec798d`. The live build additionally contained a temporary research patch. That patch allowed only two exact, privately reviewed historical diagnostic metadata records under a boot-bound, expiring manifest. Current pressure, swap, new/changed reports, service uncertainty and lifecycle faults remained blocking. The temporary research allowance is excluded from the upstream contribution and from this hybrid PR. No diagnostic records or persistent safety journals were deleted or reset.

### Controlled real-renderer experiment

Both arms used the same headless Chromium binary, synthetic loopback fixture and 1280×800 viewport. SpaceO used its actual public ChromiumBridge. OH used unchanged Facade selection/revalidation with a research CDP-backed observation/input adapter, rather than the stock Cua Driver. Initial selections were scripted. An independent HTTP event log scored effects; receipt of a click was insufficient. Three repetitions covered nine cases per arm, 54 completed cases total. An earlier harness run with an adapter exception was excluded.

| Case | SpaceO, three repetitions | OH, three repetitions |
| --- | --- | --- |
| Unchanged unique button | Intended effect | Intended effect |
| Duplicate labels, record selected by context | Intended effect | Intended effect |
| Form with exact submitted values | Intended effect | Intended effect |
| Rows reordered after observation | Unintended effect | Refused, no effect |
| Control inserted before observed target | Unintended effect | Refused, no effect |
| Target meaning changed | Unintended effect | Refused, no effect |
| Observed target removed | Unintended effect | Refused, no effect |
| Document navigation after observation | Unintended effect | Refused, no effect |
| Target disabled | Input sent, browser produced no effect | Refused, no effect |

Totals: both completed nine unchanged task runs correctly. SpaceO produced 15 unintended effects and three safe no-effect runs; OH refused all 18 changed-target runs without effects. Both viewport captures were nonblank (330 colors). SpaceO documents `wN` as a live ordinal, so these results identify a contract difference, rather than a violation of its documented semantics. A caller that rereads and reselects immediately would be a different experiment. For our saved-observation contract, substituting those ordinals loses a measured safeguard.

The two arms' timing boundaries differed and are not comparable. No agent-visible call, token, model accuracy, native Driver or virtual-display performance claim follows from this experiment. [Sanitized renderer evidence](../experiments/spaceo-comparison-2026-10-03/renderer-results.json) preserves case outcomes and synthetic event meanings.

### Attended real-display and stock-driver trials

An initial SpaceO wrapper preflight refused four swap-ins before creating a display. After builds completed, six five-second samples stayed at normal memory pressure with zero swap. The subsequent supervised app-free SpaceO create/destroy case passed; XCTest checked online removal and unchanged user monitor settings, and a separate CoreGraphics probe confirmed restored topology. Helper postflight passed with zero swap and no new reports/timeouts. The case took 107.686 seconds including mandatory 90-second pacing; this is not comparable to helper create latency.

Our unchanged helper then created a 1280×800 display in about 0.95 seconds including retirement, restored topology independently, and passed health before/after. This is a single app-free smoke, not repeated reliability evidence.

SpaceO's next supervised Chrome case refused before browser launch because its persistent journal recorded `host health: host_health_unknown`. The exact runtime sample causing that latch was not captured. An idle/running service transition is a plausible hypothesis; native fixtures demonstrate that such transitions refuse and latch, but do not establish this incident's cause. The journal remains intact. Passing the first XCTest and helper postflight therefore did not establish continued native readiness. SpaceO browser input/capture on a virtual display was not completed.

Our stock Cua Driver 0.31.0 trial initially refused because no daemon was running, then because browser attachment consent was absent. After starting an owned trial daemon with the required grant, the actual OH Facade navigated an owned Google Chrome profile, selected an observed exact control, revalidated it, and delivered the intended synthetic click. The independent server recorded only `target`. Capture was nonblank (1280×693, 2,677 colors); topology and helper health passed after cleanup. Launch focus was `agent_app` with restoration `unconfirmed`, so task completion did not establish attention isolation.

A local follow-up uses native AppKit activation, rechecks the current front app inside activation, and independently verifies restoration. A real launch with unknown or still agent-owned focus now closes the owned browser and refuses task input. Its unit and adversarial mutation checks pass. The live recheck captured rendered content but failed during cleanup before persisting the task/focus verdict, so it is unscored. The helper owner had exited, yet the independent inventory still showed its display online, with a serial matching that owner. The durable OH fault latched and remains preserved. A later independent probe showed only the original built-in display online and active again, with the original topology restored. This delayed recovery occurred without force-kill, service/preference changes or journal reset; it does not turn the earlier failed bounded cleanup check into a pass. No further creation occurred.

Recovery inspection also found 37 older display-serving processes from another worktree, all started on October 1. Their owners are outside this trial and were left alone. The observed extra display's serial matched our exited trial owner, rather than those processes, but their presence means this Mac cannot be treated as a fully isolated qualification host. The built-in display was inactive during the failed recheck's recovery observations; whether the Mac had locked/slept is pending user confirmation. This confound prevents attributing the failure solely to the focus change or claiming a clean repeated comparison. The owned Driver daemon was stopped normally; no trial Chrome renderer remained on the later scan.

[Sanitized live evidence](../experiments/spaceo-comparison-2026-10-03/live-results.json) separates the successful smokes, setup refusals, later latch and unscored cleanup failure. Private screenshots and raw process/diagnostic inventories are not committed. Full headless, locked-host, sustained workload, crash recovery and freeze-prevention qualification remain unproven.

## What to contribute and what to build here

| Choice | Decision and reason |
| --- | --- |
| Narrow upstream contribution | Proceed: readable empty/inactive display baselines, retained headless adopted-window ownership, and exact stable idle ColorSync evidence in both native and Python samplers. [PR #37](https://github.com/ParthJadhav/SpaceO/pull/37) is ready for review; [issue #38](https://github.com/ParthJadhav/SpaceO/issues/38) tracks live qualification. The PR does not contain the research incident allowance. |
| Snapshot-bound browser references | Offer as a separate, optional contract with the adversarial fixture corpus. Keep live ordinals explicitly live. Qualification must reject reordered, changed, removed and navigated targets without unintended effects. |
| Persistent health/readiness diagnostics | Keep investigating the unresolved live trigger. PR #37 now reports idle/running transitions and checks the native journal/circuit after cleanup; issue #38 tracks supervised end-to-end evidence. Do not clear or ignore unknown health simply to make the next test run. |
| Wholesale switch | Reject now: no successful SpaceO live browser/capture comparison, a measured binding-contract mismatch, and a persistent readiness refusal after a passing smoke. |
| Permanent broad fork | Defer: no demonstrated benefit warrants owning the whole app/daemon/release surface. Keep the small contribution branch while upstream reviews it. |
| Hybrid backend | The opt-in adapter is implemented and deterministic-tested. Qualify it on a recovered, owner-free host with matched tasks and cleanup/recovery cases; do not adopt it from offline tests alone. |
| Invest in ours | Select: fail closed on focus takeover/unknown restoration, verified retirement across active and online inventories, detection of other owners before creation, and explicit operator recovery. Keep the native-first product defaults and optional off-screen scope. |

## Verification and risk retirement

The production-only SpaceO contribution passed `make verify-release`: 1,708 Swift tests, 16 Python host-health tests, safe script checks, 15 Node tests and the 35-tool MCP smoke. Six earlier deliberate display regressions failed their intended assertions. Native idle tests reject crash evidence, nested fields, process races, changed launch counts, idle/running transitions and busy running peers. The temporary research patch/tests were removed before the final release check.

Our local hardening passed 1,281 Facade tests without skips, dispatcher/decider/script/scorer checks, simulation, protocol smoke, sketch synchronization, call budget, and 206 existing assertion-based mutations. The additional focus-continuation mutation was separately caught by its named assertion, giving 207 distinct wrong patches checked. A hint-catalog failure and oversized hint were fixed before the final Facade pass. Source changes remain local and require independent review before integration; this report does not claim semantic self-review is independent review.

| Risk | Disposition | Evidence or next action |
| --- | --- | --- |
| Live ordinals preserve our saved binding | Retired by contrary evidence | Fifteen unintended effects; retain our binding, offer optional snapshot references. |
| Helper-only idle fix admits native Stage | Retired by source/tests | Native parity is implemented and checked; unknown/transitional evidence still blocks. |
| One passing smoke proves continued readiness | Triggered | SpaceO's next case refused on persisted unknown health. |
| Task completion proves focus isolation | Triggered | Stock task passed while launch focus remained unconfirmed; local guard added, live follow-up unscored. |
| Owner exit proves display retirement | Triggered | Independent inventory retained our display after its owner exited; fault preserved. |
| This Mac was fully reserved | Triggered | Older foreign owners discovered; use explicit recovery review and a verified owner-free host for further qualification. |
| Headful smoke proves no-monitor/locked behavior | Accepted boundary | Baseline had an active built-in monitor. Separate controlled qualification required; no user monitor was disabled for a test. |
| Quiet counters clear historical watchdog | Accepted boundary | Exact research allowance enabled bounded experiments only; root cause and recovery remain unresolved. |

The empirical comparison and recommendation are complete at this scope. Full backend qualification and host recovery are not complete. Independent inventory eventually confirmed restoration. Further live creation remains blocked by the preserved faults and unresolved older owners until operator recovery establishes a safe baseline; neither fault record is automatically reset.

The opt-in hybrid implementation and available-toolchain qualification are recorded in [the execution report](SPACEO-HYBRID-EXECUTE-2026-10-03.md). It is compiled and deterministically tested, but is not yet live-qualified; issue #38 tracks the remaining host trials.
