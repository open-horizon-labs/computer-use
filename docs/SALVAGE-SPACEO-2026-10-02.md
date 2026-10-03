# Salvage: SpaceO comparison

**Salvaged:** 2026-10-02. **Original aim:** compare SpaceO with our virtual screen and identify useful next work. **Reason:** preserve the findings before selecting an implementation; the comparison did not select a replacement backend or establish live reliability.

## Learnings

- Both approaches create real headless macOS displays through private CGVirtualDisplay APIs. A different wrapper does not remove the underlying WindowServer dependency.
- Our current exposed off-screen route is an owned Chromium browser with a required verified display and one context per server. Shared emulator and native-window internals do not expand that authorized route.
- SpaceO adds session leases, display pooling/tiling, a Viewer, clipboard brokerage, and explicit isolation coverage. These are separable capabilities, not a reason by themselves to replace our action contract.
- SpaceO reports an unresolved WindowServer/ColorSync freeze and no new live qualification for release 1.0.5. Its safeguards are mitigation designs, not proof the failure is fixed or that our helper suffers the same failure.
- Our SpaceMover startup timeout calls stop(), which terminates and potentially kills the display-owning helper. That bounds client waiting but does not establish safe cancellation of a private macOS operation. The helper also releases its display on termination. Teardown deserves explicit treatment before increasing display churn.
- Our browser launch restoration is best effort; virtual-display placement alone does not prove focus isolation. SpaceO distinguishes observed, inferred, and unknown input-isolation dimensions rather than treating unavailable getters as success.

## Frame shift

From comparing virtual-screen features to comparing two separate responsibilities: display lifecycle containment and task observation/action correctness. Keep our fresh binding, exact target ownership, typed refusals, and independent outcome verification regardless of the selected display backend.

## Guardrails

- Do not claim a virtual display or separate browser profile is a security sandbox: processes still run as the Mac user.
- Do not copy SpaceO's creation thresholds as measured safe limits for our runtime. Their documentation describes conservative admission policy, not macOS guarantees.
- Do not live-test display churn on the user's working desktop to qualify this comparison. Use a reserved host and explicit qualification scope.
- Do not revive archived native-app/OBO routes or add mandatory agent calls while changing display infrastructure. Preserve the optional adapter's look/do budget.

## Missing context and ownership

The user invoked salvage and execute, then explicitly selected all three scopes. This report preserves the pre-implementation comparison; subsequent runtime work and verification are recorded below. No install or live display operation was performed. The existing untracked HANDOFF.md was left untouched.

## Restart kit

Recommended next scope: harden the existing display lifecycle. Begin with timeout/owner-retention semantics and recovery admission; check the tempting wrong implementation that kills an uncertain display owner and immediately retries. Review persistent failure state, cross-process ownership, reuse, and cleanup evidence before choosing mechanisms. Keep backend replacement and Viewer work separate. Runtime changes require accepted CE/sketch provenance as applicable, the optional-adapter offline gate, call-budget and mutation checks, and independent route review. Offline checks cannot establish host-level freeze prevention.

Alternative scopes: evaluate SpaceO through a pinned source audit and reserved-host qualification, or add honest focus-isolation reporting with unknown coverage represented explicitly. The user subsequently selected all three; keep their deliverables and qualification claims distinct.

## Evidence

- Local: computer_use/spaces/space-mover.swift, computer_use/spaces_client.py, computer_use/agent_display.py, computer_use/agent_browser.py, computer_use/server.py, skills/computer-use/references/lightweight.md.
- [SpaceO README](https://github.com/ParthJadhav/SpaceO/blob/main/README.md), [architecture](https://github.com/ParthJadhav/SpaceO/blob/main/ARCHITECTURE.md), and [display safeguards](https://github.com/ParthJadhav/SpaceO/blob/main/docs/DISPLAY_SAFETY.md), read 2026-10-02 from main. These are moving references; pin a commit before implementing or qualifying integration.

## Execute pre-flight

Context and preservation constraints are loaded. Pre-flight passed after the user selected all three scopes. Success means bounded durable lifecycle containment, honest launch focus evidence, and a pinned source evaluation with explicit backend qualification criteria. Preserve the current capability allowlist, exact observation bindings, and look/do budgets. Backend replacement, a Viewer implementation, and live host-level reliability claims are outside this execution.

## Execute result

**Task:** deliver existing-backend lifecycle containment, launch focus evidence, and a pinned SpaceO backend evaluation. **Aim:** reduce unsafe retry/teardown and overstated isolation claims while making backend selection evidence-based. **Trade-off:** an interrupted controller now leaves a pending record requiring operator inspection; it cannot silently recreate a display. One lifecycle owner per configured cache directory is admitted. This does not coordinate older binaries, other cache directories, or other virtual-display software.

### Declared success criteria and delivered characteristics

- Bounded startup waiting and output: implemented with select/raw reads and a 16 KiB ceiling; partial, overflowing, malformed and deeply nested JSON refuse.
- Durable ownership and uncertainty: a private exclusive record precedes launch, blocks another creator/restarted controller, and persists on startup/teardown faults. Healthy ownership reuses one display. A timed-out owner is retained; shutdown does not escalate to kill. Independent display absence is required before clearing ownership.
- Honest focus evidence: launch trace reports independently observed frontmost-app restoration and unknown key/text routes. A concurrent observed user app switch is preserved. This is launch evidence, not continuous attention-isolation monitoring.
- SpaceO evaluation: pinned b3e40c20781f2374f062291fb21867ba8212f4e1 source audit and qualification plan in SPACEO-EVALUATION-2026-10-02.md. Keep the current backend; browser ordinal binding and unresolved upstream host-freeze qualification prevent a drop-in promotion.
- Preservation: only look/do remain exposed; fresh binding, owned profiles, independent outcomes, native defaults, explicit mobile/off-screen opt-ins, and measured agent-visible call budgets are unchanged. CE-FACADE-019 records authority and corrections; the installed-policy snapshot is synchronized.

### Verification

The optional-adapter offline gate ran with the configured facade Python: unit suites, dispatcher/decider/scorer/script checks, simulation/replay/metamorphic gates, MCP protocol, call budget, full mutation gate, and structure/size comparison. Skill metadata/progressive links and isolated installer checks passed. No skipped facade tests, live display operations, GPU jobs, real app input, installs, or host configuration changes were used. Final counts are recorded after the final regression pass below.

### Risk retirement

| Risk or alternate frame | Status | Tempting wrong repair rejected | Evidence |
|---|---|---|---|
| Partial startup output hangs | Retired offline | select then blocking readline | Partial-line test times out while retaining the fake owner |
| Restart bypasses uncertainty | Retired offline | Ignore pending state and overwrite its record | Corrupt/pending record and second-client tests; restart mutation |
| Private operation timeout implies safe cancellation | Retired at client boundary | Kill and retry the display owner | Stalled-owner test and kill mutation; no OS cancellation claimed |
| Process exit proves removal | Retired offline | Clear ownership immediately after wait | Remaining-display test and mutation |
| Bad startup/teardown data escapes typed refusal | Retired offline | Accept bool IDs or let JSON/signal errors escape | Invalid identity, deep JSON, signal error tests |
| User switches app during launch | Retired for observed switch | Restore the older app regardless | Concurrent-switch test and mutation |
| Input acknowledgment proves isolation | Retired for report semantics | Treat restore receipt as verified or mark input routes clear | Independent frontmost read, unknown-route tests, acknowledgment mutation |
| SpaceO ordinal references preserve a saved target | Retired for adoption decision | Replace look handles with wN indices | Pinned ChromiumBridge source resolves current ordinal; backend not promoted |
| Full input-route isolation and host freeze prevention | Accepted with rationale | N/A | Public frontmost observation cannot prove key/text routes; host-level qualification requires reserved hardware. Pending/fault records and retained processes are containment, not a macOS stability guarantee |
| Controller/process exit or blocked storage | Accepted with rationale | N/A | Process exit can release display backing; filesystem/fsync calls are not deadline bounded. A pending record is written before creation and remains conservative, but cannot guarantee host or storage survival |

### Review

Reviewed against the original aim, code failure paths, and separate realistic routing scenarios. OBO remains native with user sessions; lightweight OH requires an owned browser and verified display; guest work remains Cua Spaces; mobile keeps its existing driver/binding contract. No new automatic preference, tool, screenshot action authority, or physical-display fallback was introduced. Self-review is not independent semantic qualification. Needs human verification: reserved-host display stability, actual installed Driver/browser focus behavior, and any future SpaceO integration.

### Final offline results

1,280 facade tests passed with no skips and no remaining fake-process resource warnings. Dispatcher 26, decider 15, scripts 36 and scorer 52 tests passed. Simulation 28/28, metamorphic 40/40 and historical replay 35/35 passed; all simulation negative controls were rejected. The full plan mutation gate rejected all 206 wrong patches, including six new CE-FACADE-019 cases, by their named assertions. MCP protocol, call/response budget, look structure/size comparison, synchronized sketch, skill metadata/progressive links and whitespace checks passed. Generated simulation timing/order noise was restored rather than committed. HANDOFF.md remains untouched and untracked.
