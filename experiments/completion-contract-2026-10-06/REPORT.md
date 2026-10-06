# Separating dispatch, supervision and application completion

Execution complete for the offline protocol experiment. Tested supervision alone, application completion evidence alone, and their combination against the serial-wait baseline. No desktop, driver daemon, app focus, cursor or keyboard was operated. This prototype changes no production API or PR #4762.

## Outcome

Supervision alone removes repeated blocking waits but cannot prove transaction completion: it accepted an optimistic value whose rejection arrived after its horizon, and accepted a write with no application acknowledgement. Application evidence alone refused both cases. The combination retains supervision ownership and also requires the application's final commit/reject acknowledgement. Missing acknowledgements produce `ack_unavailable`, not completion. It preserves partial writes for inspection and never retries or claims rollback.

The application is a separate process reached through a pipe. It echoes values immediately but independently schedules transaction commitment or rejection and owns record identity and generation. Acknowledgements bind transaction ID, field, record and generation; both the acknowledgement and a fresh observed value must agree. These guarantees exist because this fixture explicitly implements them. Arbitrary AX read-back, quiet notifications or renderer events are not substitutes for such an application contract.

| Approach | Late rejection after supervision horizon | Missing commit acknowledgement | Caller cancellation |
|---|---|---|---|
| Serial horizon | Accepts optimistic echo | Accepts optimistic echo | Watcher survives |
| Overlapping supervision | Accepts optimistic echo | Accepts optimistic echo | Watcher survives |
| Application evidence | Refuses rejection | Refuses completion | No watcher in this arm |
| Combined | Refuses rejection | Refuses completion | Watcher survives |

The independent stable matrix uses ten scored alternating repetitions per approach after one warmup. The fixture uses a 100 ms supervision horizon and 25 ms application commit delay to exercise ordering without long sleeps. See benchmark.json for measured decision times and all 44 rows. Those timings include process startup/transport overhead and are **not Cua or Arc performance measurements**, nor a prediction of production gains. Serial waiting has two horizons; overlapping/combined supervision has overlapping horizons; application evidence waits for two committed acknowledgements without a generic timer. No comparison candidate version claim is made because neither driver executes these experiments.

## Declared scope and checks

Aim: test whether the selected completion contracts can remove the per-action blocking floor without confusing dispatch with completion. Preserve fresh process context, exact transaction binding, no dependent input before proof, no replay, explicit partial failure, and watcher ownership after request cancellation. Stop an approach on false completion; do not promote untested native focus safety. Success is a reproducible matrix, adversarial keeper tests and rejected shortcut implementations.

Run `python3 -m unittest discover -s experiments/completion-contract-2026-10-06 -v`, then study.py and bench.py from that directory. Ten owner tests pass. The matrix covers early and late rejection, record change, dependent input, partial failure, absent acknowledgement, cancellation and stable exact final values. Additional tests corrupt acknowledgement transaction, field, record and generation. Three deliberately wrong variants are detected: trusting optimistic echo, skipping the supervision fence, and cancelling watcher tasks with their caller. The corresponding ordinary keeper assertions fail for those variants.

A first prototype exposed two real implementation defects: concurrent pipe receives needed serialization, and unshielded caller cancellation killed supervisor tasks. Both were corrected before the final matrix; failed-process cleanup was completed. No test masks them as driver defects.

## Risk retirement

| Risk | Status | Tempting wrong implementation rejected | Evidence or remaining boundary |
|---|---|---|---|
| Quiet/echo is mistaken for completion | Retired for the evidence contract; triggered for supervision alone | Return complete on immediate matching value | Rejection beyond the horizon is refused only by evidence/combined |
| Missing acknowledgement treated as success | Retired for evidence/combined | Fall back silently to optimistic AX-style echo | Exact `ack_unavailable` owner |
| Ack belongs to another transaction/context | Retired in process protocol | Accept any committed-looking payload | Four corrupted acknowledgement bindings refuse |
| Later success hides an earlier failure | Retired in protocol | Check only the final field | Partial failure refuses despite successful second write |
| Dependent input precedes proof | Retired in tested executor | Submit after dispatch acknowledgement | Rejected first transaction leaves write count at one |
| Cancellation stops supervision | Retired in prototype | Let cancelling gather cancel its watchers | Shielded ownership keeper and cancelling mutant |
| Record binding races | Retired within atomic process write contract | Write against old record/generation | Independent app comparison refuses context change |
| Foreground interference / failed native observer | Accepted boundary; remains a production blocker | Treat mock watcher ownership as macOS focus proof | No host trials; native focus isolation is not tested here |
| Real apps lack final transaction acknowledgements | Accepted boundary | Invent completion evidence from immediate read-back | Evidence path unavailable until a qualified application adapter supplies it |
| Generic horizon proves no future rejection | Triggered; claim rejected | Equate a finite deadline with completion | Late-rejection and missing-ack controls |

## Execution handoff

Selected direction: combine a promptly returned dispatch receipt, independently owned bounded supervision, dependent-action fences and qualified application completion evidence. These two mechanisms add different guards; one cannot replace the other. A generic timer is a fallback observation horizon, never definitive application completion.

The prototype qualifies ordering and refusal semantics, not production delivery, OS event handling, permissions or application compatibility. Native focus preservation and exact AX binding require separate qualification on an isolated surface before desktop execution resumes. No Lume guest is provisioned. A public receipt/supervision contract requires dissent and the Cua RFC process before production implementation. The 800 ms timer overlap is separate local work and does not remove the setter floor.
