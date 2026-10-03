> Superseded for current results and recommendation by [the empirical comparison](SPACEO-EMPIRICAL-COMPARISON-2026-10-03.md). This note preserves earlier decision context; its preflight and implementation status are historical.

# Solution Space

## Solution Space Analysis

**Problem:** Obtain a meaningful SpaceO display/capture/cleanup trial and comparison without destabilizing the user's working Mac or interpreting admission changes as proof of compatibility.

**Key Constraint:** This host has a WindowServer service-process watchdog record in its current boot. The runtime has an independent Swift health sampler as well as the Python live-test helper. Passing only the helper does not admit Stage creation.

**Working Story:** There were three different issues: an unnecessarily strict active-user-display requirement; an absent-process ambiguity for launchd-recorded idle ColorSync services; and independent resource/incident evidence. The first has a proposed fix, the Python half of the second has a proposed fix, and the third must be assessed on its own evidence.

**Success Signal:** Both health implementations agree on known idle versus unknown/failing services; an eligible, reserved graphical session completes one supervised display creation, nonblank capture and verified retirement with unchanged user topology and passing pre/post health. That is smoke evidence only; a switch still requires matched task trials and recovery qualification.

**Decision Criteria:** Preserve the user's desk and unrelated apps; preserve real failure detection; remove demonstrably false refusals consistently across production and tests; prefer bounded, reversible actions with independently checked results; avoid altering system preferences, services or safety journals to force admission.

**Critical Assumptions:** The watchdog record is relevant to display-system recovery even though its age alone does not prove current malfunction; the same idle-service contract can be implemented safely in both health paths; a quiet sample cannot by itself establish recovery; a separately reserved Mac may be available but access is unconfirmed.

### Evidence gathered

- The first revised admission found pressure level 2, four interval swap-ins and two diagnostic reports.
- A later read-only five-second diagnostic sample found pressure level 1 before/after, zero swap deltas, two idle ColorSync services and zero matching WindowServer/ColorSync timeout messages over the preceding five minutes. This retires the claim that memory/swap were persistent blockers; it does not establish host recovery.
- Boot age was approximately 188 hours. The two matching reports were modified approximately 36.8 and 32.7 hours earlier, outside the last 24 hours but inside the current boot. Creation ages were approximately 36.8 hours. The exclusion is the intentional `min(boot, now - 24h)` rule in both implementations, rather than a timestamp decoding failure.
- A bounded private header inspection identifies the spin report's event as `service process watchdog`, with a 5.54-second sampled duration. It is concrete watchdog evidence, not merely an arbitrary filename. This sample duration is not the watchdog's missed-check-in duration and does not establish a cause.
- The Python helper now accepts only exact launchd evidence of a memory-idle exit. At this point in the investigation, native parity was still outstanding. PR #37 later added exact idle-service handling and a regression for readiness transitions; see its validation and remaining live-test limits.
- No live display, app, daemon or input workload was launched during this investigation. Raw report paths, identities, stacks and content stay private.

## Candidates Considered

| Option | Level | Approach | Does it solve the problem / assumed frame? | Main cost and second-order effect |
| --- | --- | --- | --- | --- |
| A — Relax/bypass remaining thresholds | Band-Aid | Allow warning pressure, swap or current-boot reports so the trial starts | Assumes refusals are false positives; does not produce trustworthy qualification after actual watchdog evidence | Fast but loses detection of the documented failure mode. Rejected; real watchdog evidence triggers this risk. |
| B — Recover and reserve this Mac | Local Optimum | Review the private incident and present responsiveness; reduce only agreed workload; after work is saved, perform owner-managed recovery if warranted, then run one supervised case | Assumes recoverable local state. Potential path to a desktop smoke trial, not root-cause resolution or headless qualification | Interrupts user work. Reboot can change the admission result without fixing recurrence; recovery needs independent evidence and owner judgment. Deferred pending review. |
| C — Use a separately reserved Mac | Reframe | Qualify the candidate in another graphical login with clean incident history and suitable grants/toolchain | Treats the personal desktop as a poor qualification environment rather than the gate as the obstacle | Requires another host/access. Protects the desk but cannot establish recovery of this Mac or erase the broader incident. Selected for live qualification when available. |
| D — Complete health parity and investigate first | Local Optimum | Port the narrow idle-state contract into the native sampler with fixtures; review bounded watchdog evidence and recovery criteria before choosing B or C | Tests whether admission is actually consistent and whether a current-host trial has defensible evidence | More source work, but it removes a demonstrable production gap without weakening pressure/history checks. Does not itself make this host eligible. Selected immediate work. |

## Interpretive Variety Check

- A assumes the gate is the problem; concrete watchdog evidence challenges that assumption. B assumes the host can be recovered. C changes the test environment. D separates code correctness from host eligibility and checks the two admission paths.
- D most directly tests the present frame. Its adversarial fixtures must reject an idle-to-running transition, a crash and a missing service, even while allowing a stable registered memory-idle exit.
- If native parity passes but health still blocks, the lesson is that source readiness and host recovery are separate. If B yields recurring watchdogs/timeouts, route to incident diagnosis and C, not broader admission relaxations.

## Risk Retirement Plan

Disposition labels below describe planned checks unless evidence is explicitly recorded as completed.

| Risk / assumption / alternate frame | Planned disposition | Tempting patch this must fail | Required evidence or rationale | Stop/pivot if |
| --- | --- | --- | --- | --- |
| Memory/swap refusal was transient or induced by unrelated workload | Retired by evidence for the later sample only | Pretend warning pressure or observed swap is healthy by raising thresholds | Both pressure samples equal 1 and interval swap deltas equal zero, while fixtures still reject pressure 2/4 and any positive swap | Pressure/swap returns; stop admission rather than close unrelated apps automatically |
| Diagnostic exclusion is merely a timestamp/filename false positive | Triggered | Count only the last 24 hours or ignore current-boot reports to admit this host | Header evidence identifies an actual service-process watchdog; creation/modification ages explain the current-boot rule. Retain conservative refusal pending recovery review | Any new report or matching timeout; stop live work |
| Python idle-service fix also fixes production Stage admission | Retired by evidence, planned | Change only the harness and call the feature working | Native fixtures and Python fixtures using shared sanitized shapes; stable idle admits in both; missing identity, crash, launch-count change, nested misleading state and process races refuse in both; continuous sampler/watchdog latching stays intact | Either path admits a bad state or native state remains unknown |
| Reboot / quiet current counters imply the incident is resolved | Accepted with rationale | Erase reports, clear the circuit or reboot until admission turns green | Root cause and recovery need incident evidence and human judgment. A recovery event and quiet sampling are explicitly insufficient by themselves. No autonomous restart or safety-state reset | Recurring symptoms, watchdogs/timeouts, or unverified recovery; use C and continue diagnosis |
| Another host will make SpaceO stable or prove this host recovered | Accepted with rationale | Treat a passing smoke case elsewhere as a fix or production-switch recommendation | Another host isolates the desk and provides qualification evidence only for that host/build/workload; preserve the unresolved incident and run matched task/recovery trials before switching | Any failed health, capture or cleanup evidence; retain owner when cleanup is uncertain |
| A headful desk trial proves empty/inactive-baseline support | Retired by evidence, planned | Label normal-monitor smoke success as headless qualification | Record the actual baseline and perform a separate eligible no-active-user-monitor trial, without changing the user's active monitor during the desk run | Required baseline cannot be obtained safely; defer headless qualification |
| Cleanup acknowledgment establishes safe retirement | Retired by evidence, planned | Accept `destroy` success without confirming removal/topology | Independent online/active inventory and user topology comparison, zero leaked sessions/displays and passing final health; wrapper must fail a fake successful receipt with an attached display | Inventory/topology uncertainty or retained owner; stop and inspect, no force kill |

## Recommendation

**Selected:** D now; C for live qualification. B remains a possible owner-reviewed local smoke path, and A is rejected.

**Level:** Local Optimum for code parity and investigation; Reframe for qualification environment.

**Rationale:** The latest observation removes persistent memory/swap from the immediate blocker list, but the watchdog is real and native admission parity is incomplete. Completing parity and understanding recovery provide concrete progress. Changing pressure/history thresholds just to pass this host would discard the evidence that the gate was added to detect.

**Accepted trade-offs:** The desk trial does not run immediately. A separate host needs access. A normal-monitor smoke trial cannot prove headless behavior. Neither reboot nor one successful trial closes the unresolved incident or establishes a switch recommendation.

## S&T Selection

No Problem Weave or candidate S&T lineage is in use for this contribution. No issue planning or invented lineage is introduced. Immediate selected work is native idle-state parity and private incident/recovery review; separately reserved live qualification depends on access. Broad gate relaxation is rejected; current-host recovery and a future recovery-clearance design remain deferred.

**Selected-step sufficiency:** D is sufficient to make the admission contract consistent, not to establish live compatibility. Qualification remains conditional on an eligible host and independently verified results. This gap is explicit.

## Execution Handoff

- Preserve: bounded fixed read-only helper commands; exact registered service identity; process/start identity when running; idle launch-count continuity; failures/unknowns/pressure/swap/diagnostic refusals; continuous sampler timeout/staleness and persistent failure latching; display/window ownership, independent retirement checks and the user's apps/preferences.
- Verify via: focused native health fixtures plus safe full verification; one supported supervised app-free create/destroy case before capture/app work on an admitted reserved host; pre/post health and topology evidence retained privately.
- Decision criteria: meaningful admission evidence, minimum desk interruption, consistency across production/harness, and no false success from skipped tests or a different baseline.
- Critical assumptions: reviewed recovery or separate-host eligibility; fixture evidence is source-level and cannot establish macOS/private-API compatibility.
- Accepted trade-offs: access/recovery delay; separate headless qualification; no current-host repair by force and no production switch based on smoke alone.
- Risk retirement checks: all table rows above carry forward. The native parity check must fail harness-only fixes, fabricated idle counters, crash acceptance and service-transition acceptance. Retirement checks must fail false successful teardown receipts. Headless qualification must fail a normal-monitor-only claim.
- Invalidated if: the native sampler cannot distinguish idle state safely with bounded evidence, or live results show topology drift, missing capture, instability or cleanup uncertainty.
- Stop/pivot triggers: health refusal, user-reported slowdown, new diagnostic/timeout, first live assertion failure or ownership/topology uncertainty; investigate and change host/scope rather than retry creation.
- Needs human verification: saved work and reserved-desktop status before a local recovery/test; present desk responsiveness; reviewed recovery sufficiency; access to a separately reserved Mac. No reboot, service restart, profile deletion or safety-state reset is authorized merely by this recommendation.

## Execute — sustained comparison

The user explicitly selected this Mac after recovery review and requested continuing through empirical comparison. Immediate work: finish native idle-service parity, privately review incident context and current health, use bounded exact-record research clearance if justified for the reviewed history only, and run matched lifecycle/capture/task trials. No automatic reboot, profile deletion, service restart or incident-record deletion. Current pressure, swap, new incidents, service transitions, expiry, topology drift and uncertain teardown remain stop conditions. Source fixes can be offered upstream; a research-only history allowance must remain visibly distinct from the proposed production behavior.

### Dissent: reviewed historical-report allowance

**Steel-man:** A current-boot report from roughly 37 hours ago need not permanently prevent an attended, app-free research trial when current samples are quiet and the owner has chosen this Mac after review. An exact-record, expiring allowance can retain detection of new/changed incidents without deleting evidence.

**Contrary evidence:** The incident was a real watchdog. Quiet samples previously failed to predict SpaceO stalls upstream. The native monitor is sticky and can retain an owner when a later sample is unhealthy. Therefore no generic ignore-history flag, timestamp-window shortening, or automatic circuit reset is acceptable.

**Pre-mortem:** Functional failure: an allowlist matches a replacement incident. Adoption failure: research clearance becomes a convenient permanent bypass. Opportunity cost: clearance work overwhelms the small comparison. Checks: metadata fingerprints must change on inode/path/size/mtime/ctime changes; bind the review to this boot and short expiration, strict private-file parsing, and a fixed reviewed set; keep this code in a clearly separate temporary research patch, run one app-free case first, and preserve new-report/current-health refusal.

**Decision: ADJUST.** Research evidence may support a narrowly reviewed trial, but it cannot establish system recovery. If quiet current evidence cannot be obtained, report identity cannot be bound, or the first supervised case fails, abandon this route and keep meaningful browser/contract experiments separate from display qualification. Root-cause closure and sustained/locked/headless qualification remain unproven. No experimental allowance is offered as a default upstream policy.

### Pre-flight and risk checks

- Aim: an evidence-based recommendation among keeping ours, switching, maintaining a fork, and combining components.
- Criteria: independently observed task correctness, stale-target safety, capture, ownership/cleanup, attention isolation, call counts, timing where comparable, and practical maintenance burden.
- Scope: selected native health fix plus bounded research trials; no production switch, merged release, GPU/legacy dispatcher, general policy relaxation or user-state repair.
- Adversarial checks: native idle fixtures must fail harness-only fixes and crash/restart acceptance; review clearance must fail broad ignore-history, new/changed-report allowance, wrong-boot and expired review; task scoring must fail stale-ordinal substitution and false input acknowledgments; lifecycle scoring must fail success receipts with still-attached displays. Preserve exact API/schema bindings and no uncertain input retry.
- Human boundary: the user selected the local Mac after review. Do not claim an experiment resolves the underlying incident or establishes safe production/locked-host use.
