# Native completion and supervision experiment

Both approaches and their combination ran through the real current Cua macOS backend with the existing AX batching patch. The combined path reached independently verified application commit in 443 ms versus current Arc's 502 ms, 12% less time. Its supervisor remained owned and running; the full supervision fence finished at 1.49 seconds. These are different milestones, not interchangeable claims of completion.

## Measured result

Owned native AppKit fixture, two explicit text writes, fresh exact targets and record checks before each input, transaction acknowledgments and independent final AX/value proof. No model or JEV calls. Cua main 5227ad637590a15976413b1a33f8693fac0e9a7e plus the broad AX patch and private research patch; actual SDK backend 0.34.0. Arc source 74ffae1108b1cb4b1f6b161084af12646f544ba5, actual server 0.1.1. Upstream checks ran before every scored trial and failed on earlier upstream movement until Cua was rebuilt. See manifest and raw server metadata for exact source/binary identities. Rust 1.97.1; unstripped release build worked around malformed stripped macro-library metadata.

| Native arm | Median task decision | Versus serial | Completion criterion |
|---|---:|---:|---|
| Serial native wait | 2,639 ms | baseline | Original per-action observation horizon plus final value read |
| Separately owned supervision | 1,519 ms | 42% less time, 1.74× | Overlapping full horizons, final value read |
| Application evidence alone | 534 ms | 80% less time, 4.94× | Bound application commit acknowledgment plus fresh value proof |
| Combined, full fence | 1,573 ms | 40% less time, 1.68× | Application proof and completed full supervision |

This first alternating matrix has three scored repetitions per arm after one warmup; 16/16 rows passed values, owned foreground and competing-input checks. The separate acknowledgment-only comparison has four scored alternating pairs after warmup: Cua 435 ms, Arc 517 ms; 10/10 qualified rows. The final combined comparison also has four scored alternating pairs after warmup: combined commit 443 ms, Arc acknowledgment task 502 ms; 10/10 qualified rows. Combined full-fence median in that final run was 1,492 ms. Small samples on one fixture establish feasibility, not general application or model performance.

## Why the original concurrency patch saved little

Releasing the per-process mutation lease was insufficient. The registry's global desktop-action coordinator remained held until native Tool::invoke returned, including its approximately one-second detector wait. The initial native pilot therefore still took roughly 2.4–2.6 seconds in the queued arms. The working research patch returns after dispatch, focus handling and immediate readback, so both input locks release normally. A separate owned task retains the original full detector snapshot and protection lease. A fence joins those tasks. It does not label an immediate echo as a committed transaction or silently shorten the detector.

The application contract separately binds transaction ID, field, value, PID, exact window, record and generation. Only that app contract and a fresh AX read establish value commitment. Observation supervision is an additional lifecycle obligation. The commit milestone explicitly records `pending_owned`; ordinary synchronous completion still waits for the full fence. Returning committed values earlier requires a durable owner that survives the caller and later reports supervision failures.

## Adversarial results

| Check | Evidence alone | Combined | Supervision alone |
|---|---|---|---|
| Rejection after 450 ms | Refused | Refused | Final value mismatch |
| Rejection after 1.4 s | Refused | Refused | Falsely accepted optimistic value |
| Missing acknowledgment | `ack_unavailable` | `ack_unavailable` | Accepted optimistic value |
| Wrong transaction acknowledgment | `ack_binding`, one write | `ack_binding`, one write | Not an application-proof contract |
| Changed record | `context_changed`, one write | `context_changed`, one write | Not qualified here |
| First write rejected in a two-step plan | Refused before second input | Refused before second input | Not qualified for dependent plans |
| Second write rejected | Handoff, two writes preserved | Handoff, two writes preserved | Not qualified for application completion |
| App requests activation after 450 ms | Target became foreground: unsafe | Actual activation request, foreground preserved | Disconnect control preserved foreground |

Eight native binding/dependent-plan/partial-failure guard rows passed expected refusal checks. Both fields remained in the planned executor; acknowledgment failure stopped the first-write rejection before the second input. Partial failure left the successful first value and rejected second value visible; no rollback or replay was claimed.

The combined positive activation control delivered a real Cocoa callback, restored the exact owned sentinel PID/window and preserved foreground independently through Cocoa, WindowServer and app state. An earlier callback-only restore attempt failed and remains recorded. The private exact-window restore helper is necessary for this result; this does not qualify ordinary production Cua foreground restoration. Evidence alone confirmed the value but failed the foreground requirement, so its fast result cannot become the general default.

Closing the native client input immediately after dispatch retained supervision: host exit waited 1,529 ms, the delayed app activation occurred, foreground was preserved, and host exited normally. The task remained a handoff because the closed transport prevented its final AX proof. No success or blind retry was reported. This qualifies that private host's orderly EOF path; arbitrary host crashes and cancellation of a production fence require a durable receipt registry and additional checks.

473 macOS library tests passed, six ignored. Ten independent protocol owner tests passed, including three wrong variants that trust optimistic echo, skip a dependent-action fence, or cancel watchers with the caller. Deterministic protocol tests are separate evidence from the real native trials.

## Scope and remaining production work

This is a reviewable research packet, not a production-ready Driver API. Only the owned fixture supplies immutable transaction outcomes; generic AX readback, quiet notifications and renderer events do not supply them. Field plans remain limited to writes whose context can be freshly bound and independently verified. Generic apps must keep the normal supervision fallback.

A production design needs durable per-receipt supervision ownership, explicit committed/pending/fenced/error states, terminal failure routing, a qualified app-evidence provider, atomic record semantics where required, and ordinary foreground restoration qualification. The private registry and known-sentinel restoration helper must not be shipped as generic policy. No arbitrary actions, production daemon, Lume VM, GPU job or user document was operated. All owned test processes closed; recorded cleanup restored the original foreground. The primary dirty checkout was preserved.

## Risk retirement

| Risk | Status | Falsifying evidence or boundary |
|---|---|---|
| Global lock hides the gain | Retired for private native host | Queued-only pilot stayed slow; deferred invocation measurably overlaps full watchers |
| Echo or a timer is mistaken for transaction completion | Retired for evidence/combined; triggered for supervision alone | Late rejection and absent ACK controls |
| Wrong record or transaction permits dependent input | Retired for native evidence executor | Wrong-ACK/changed-record/first-rejection plans stop with one write |
| Later success hides partial failure | Retired in independent protocol; native failed second step retained | Protocol keeper plus native first-success/second-rejection handoff |
| Caller disconnect kills watcher | Retired for orderly native EOF | Exit latency, actual delayed activation and independent foreground proof |
| Foreground safety inferred from callbacks | Triggered for original restore and evidence-only | Failed restore pilot and delayed activation control; private exact-sentinel combined path passes |
| General app completion capability is invented | Accepted scope boundary | Fixture-only immutable ACK contract; unavailable for generic apps |
| Arbitrary cancellation/crash loses receipt | Production blocker | Native EOF is narrower; protocol cancellation keeper passes, production durable ownership remains required |
| Outdated candidates or competing input taint results | Retired for scored rows | Per-trial upstream preflight, running metadata, independent monitor; invalid earlier pilot retained separately |

Run the native harness with the recorded Python 3.12 environment and fixture dependencies, rebuilding the private host against the current candidates first. The scripts retain explicit absolute experiment paths; the packet records the dependencies rather than pretending it is a portable production test suite. All failed setup/pilot attempts are excluded from medians.
