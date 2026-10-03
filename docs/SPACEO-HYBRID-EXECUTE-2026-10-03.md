# Opt-in SpaceO lifecycle hybrid — execution record

The selected approach retains our facade’s fresh observation, exact binding and independent action verification while delegating display creation and retirement to a small worker built against SpaceOKit. It does not transfer browser ordinals or change the default native route. The empirical comparison remains in [the comparison report](SPACEO-EMPIRICAL-COMPARISON-2026-10-03.md).

## Implementation and scope

`CUA_DISPLAY_BACKEND=spaceo` selects the adapter; `CUA_SPACEO_DISPLAY_WORKER` must name an explicitly built worker. Build with `python3 scripts/build_spaceo_display_worker.py --spaceo-checkout /path/to/SpaceO --build-dir /path/to/build`. The builder records SDK revision, working diff hash, worker hash and installed Swift version. It never launches or installs the worker. Xcode 27 / Swift 6.4 are the available qualification tools; Xcode 26.3 qualification is not claimed.

The worker owns one Stage, reports bounded independent CoreGraphics online inventory, and publishes readiness only after native health checks. Retirement requires successful native teardown, a ready native circuit, owner exit and an independently restored baseline. Unknown effects retain ownership and latch a fault. No automatic reset, physical-screen fallback, build on first use or extra model-visible tool is added.

Both backends now refuse other known `space-mover display serve` or `OHSpaceODisplayWorker display serve` owners before creation. This bounded scan covers those names only; it is not a universal ownership proof or an atomic cross-process lock. Our helper exposes explicitly labelled online inventory so inactive online displays cannot masquerade as completed cleanup.

## Evidence and remaining boundaries

Disposable-worker tests cover reuse, durable exclusion, native journal refusal, malformed inventory, topology drift and a display remaining online after owner exit. Mutation checks deliberately remove those protections and require assertion failures. The native worker compiles against the patched SDK with the installed toolchain. Read-only protocol checks inspect actual online inventory without creating a display.

Live qualification remains stopped by durable faults from the recorded trials and 37 older foreign display owners. Their ownership and recovery were not established by this work; neither faults nor owners are cleared automatically. Compilation and deterministic tests do not prove unattended isolation, recovery, focus preservation or live hybrid superiority. Independent semantic review is required before integration.

## Risk retirement

| Risk | Check or boundary | Tempting shortcut rejected |
| --- | --- | --- |
| Exit mistaken for removal | Online inventory and disposable leak test | Clear ownership when the owner exits |
| Native fault hidden by helper success | Native circuit matrix and sticky transition test | Admit on helper success alone |
| Wrong display or topology change | Baseline comparison and malformed inventory tests | Trust the startup receipt alone |
| Dormant owners ignored | Shared bounded owner scan test | Count only current display graph entries |
| Binding weakened by backend switch | Existing facade tests and unchanged action path | Transfer live browser ordinals |
| Live focus and recovery | Triggered live fault boundary; no new live claim | Reset journals to obtain a passing run |
| Pinned release toolchain | Available toolchain compile/test, pinned qualification outstanding | Report a toolchain never run |

Recommendation: keep our binding and verification, donate the narrow upstream fixes, and qualify this opt-in lifecycle hybrid after reviewed host recovery. A wholesale switch is not supported by the empirical evidence.

## Completed available-toolchain verification

The facade suite passed 1,290 tests with no skips; dispatcher 26, decider 15, scripts 25 (including isolated installer checks), and experiment scorer 52. Protocol, simulation, call-budget, generated sketch consistency and look-structure checks passed. All 211 deliberate wrong patches were caught by assertion. Skill metadata and progressive links passed. SpaceO `make verify-release` passed 1,710 deterministic Swift tests, 16 Python tests, 15 Node tests and the 35-tool MCP smoke. Three new readiness regressions were caught by assertion; restored source passed the 18 focused tests. These are deterministic qualification results, not new live-display evidence.

SpaceO [PR #37](https://github.com/ParthJadhav/SpaceO/pull/37) now includes the readiness follow-up at `1c910c2942ac8dfa740d90dac519943592936ccd`. It is ready for review, and issue [#38](https://github.com/ParthJadhav/SpaceO/issues/38) tracks the remaining live qualification. The PR is ready for review; issue [#38](https://github.com/ParthJadhav/SpaceO/issues/38) tracks live qualification. Its description identifies the installed toolchain and outstanding live qualification. GitHub currently exposes no check rollup; no remote CI success is claimed.


## Live attempt after owner cleanup (2026-10-03)

The user confirmed the 37 old `space-mover display serve` processes were unintended. After rechecking each process identity, I sent SIGTERM to all 37. A fresh scan found zero remaining owners. Independent inventories then showed only the built-in display online and active. The fault records were preserved.

The live host-health probe sampled for 5.037 seconds. Memory pressure stayed normal, swap deltas were zero, ColorSync CPU was zero, and there were no service timeouts. It still refused admission because it found two WindowServer diagnostic reports from the current boot. SpaceO doctor continued to report the persistent `host_health_unknown` latch. The real hybrid adapter refused before starting a worker; online inventory and known-owner count were unchanged. No display was created, so this is evidence for the refusal path, not a successful lifecycle test.

SpaceO's recovery guide permits an operator to archive the lifecycle journal only after owners have exited, no orphan display remains, and physical-only display operation is stable. Those owner and inventory checks now pass. The current-boot diagnostic refusal remains, so the successful live trial requires reviewed recovery and a fresh passing health sample. Do not bypass either journal or diagnostic gate to force creation.
