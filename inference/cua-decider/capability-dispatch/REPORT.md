# S4 capability dispatch: CESS cycle report

The full request-to-capability sketch is in `SKETCH.md`; `dispatch.py` is its replaceable executable projection. The first live extract-match route completed **20/20 booking tasks**, with no wrong actions or deferrals, across 35 decisions. Median caller decision time was **23.4 ms**, GPU extraction **18.2 ms**, and complete browser task **1,732 ms**. Inference used the RTX 3060 Ti, then unloaded. Qwen/SystemOne services were not altered.

The result establishes the user's proposed decomposition on this fixture: the controlling LLM supplies field descriptions and selection rules; GLiNER2 extracts values from per-control evidence; generic typed comparisons find the match; Driver executes and reobserves. GLiNER2 was never asked to choose between entire actions or reason about the goal.

## Full dispatch coverage versus live qualification

| Request | Projected route | Evidence this round |
|---|---|---|
| Unique exact control | No model | Contract, payload and stale-execution tests |
| Simple entity labels | GLiNER | Dispatch contract test; no live adapter installed in this prototype |
| Described short fields | GLiNER2 | Dispatch/grounding gates plus 20 live browser tasks |
| Structured/relational/long or multilingual extraction | GLiNER2.5 | Dispatch contract test; structured/relationship adapter remains to be connected and evaluated; span adapter interface can load an explicit boundary checkpoint |
| Described class → caller-mapped action | Decide | Classification/rejection reducer tests using controlled provider responses; no live Decide quality claim |
| Semantic offered-action choice | Jev | Allowed-choice reducer test; existing installed selector is the integration anchor, not replaced/deployed by this prototype |
| Mixed described fields and class fields | GLiNER2 + Decide in parallel | Same-record join and selection test using controlled responses |

Model family capabilities overlap. These provisional defaults are a policy to test, not a speed/quality ordering of generations. All branches exist in the projected algorithm and use injectable provider contracts; only the GLiNER2 provider was connected for live inference here. Unavailable adapters return explicit deferral. Deployment, context-limit qualification beyond these short inputs, provider calibration, and multilingual/relational accuracy remain unestablished.

## Live corpus and comparison limits

Raw traces: `../../benchmarks/cua-capability-dispatch-2026-09-27/booking-100-119.json` and its `-evidence.json` companion. Seeds 100–119 were an already-used development fixture, not a new generalization holdout. The result includes five waitlist cases, ten booking confirmations, and five disappearing-slot cases. The selector receives fresh UI evidence and an assistant-authored fixed caller contract; only the harness reads the hidden oracle after the task.

`booking-request.json` contains task-specific names, values, visible operation descriptions and scope selectors. The engine contains none of them. This is a caller contract authored by the controlling LLM before execution; natural-language contract generation and its latency were not benchmarked. Confirmation evidence is scoped to the current confirmation heading and compared against the previous selected record. A lost slot is rematched from the next current candidate list.

The prior direct GLiNER2 classifier's 5/20 is a result for a different task formulation, not evidence against NER extraction. The recent clear-policy Jev control got 16/20 at 164 ms median decision time; another earlier Jev arm supplied with explicit structured task constraints already got 20/20, with the extraction gate disabled. Therefore this run demonstrates a fast extraction-and-comparison path, not a new correctness gain over every structured Jev configuration. End-to-end task timing still contains browser observation/action latency.

## CESS cycle CAP-002

- Active case: CE-CAP-002, the user's correction that the sketch must cover all request kinds and requested model families. Classification: missing sketch rule. Retained regression: CE-CAP-001, the user's correction from whole-action classification to extraction plus caller-specified comparison.
- Authority: the user's explicit corrections recorded in `COUNTEREXAMPLES.json`. No later CE is used to justify an earlier proposal.
- Before: a GLiNER2-only fixture path / whole-action classification framing. After: S4.1's complete semantic request matrix, including exact controls and hybrids; S4.2's compile, evidence, compare, bind, execute, verify order.
- Projection: `dispatch.py`, `providers.py`, `run_booking.py`. No model training or router fitting. Provider connections are separate from the typed plan and deterministic reducers.
- Generalization limit of the authorized rule: field descriptions and criteria are caller data; inference must fit the semantic request. The correction does not establish the best checkpoint, thresholds, unseen-goal interpretation, visual grounding or new action permissions.
- Deterministic gate: `GATE.json` records 19 passing tests. It covers the active taxonomy and retained extract-match CE, hybrid joins, arbitrary field/name changes, reverse ranking, ID/order changes, same-record matching, malformed/missing/conflicting evidence, wrong operations, ties, disabled controls, stale bindings, invalid units, provider failure and visual-only refusal.
- Wrong repairs: mutation checks explicitly reject always-GLiNER2 dispatch, first-candidate choice and unconditional fallback. The non-booking Morgan/Taylor inventory case rejects hardcoded Alex/30-minute selection.
- Current projection replay: the final engine replays all 35 captured live decisions to the same selected action. Disabled-control and provider-error hardening followed the live run; this replay and the new tests verify those changes preserve the exercised behavior.
- Sketch review: `SKETCH-REVIEW.json` records capable-model review of the active/retained cases and the actual booking traces separately from the gate. Reviewer is the implementing assistant, not an independent second agent. Both checks pass for the stated corpus.
- Next active failure: none in this bounded corpus. Open qualification work is explicit above. No production replacement or general CUA reliability claim is made.

Fresh-projection sufficiency: S4 and its stable contracts contain the complete policy, without relying on archive examples to recover it. A second independent regeneration has not been performed in this round; the periodic sufficiency exercise remains untested rather than silently passed.

## Reproduce

```sh
python3 inference/cua-decider/capability-dispatch/gate.py
~/.local/share/fleet-cua-decider/.venv/bin/python \
  inference/cua-decider/capability-dispatch/run_booking.py \
  --start 100 --count 20 --output /tmp/cua-s4-booking.json
```

The benchmark caller invokes one `Engine.decide(request, current_snapshot)` API per decision. The projected plan launches independent evidence operations in parallel and returns one snapshot-bound action or explicit deferral. The Driver controller retains action arguments and performs independent verification. This experiment adds no background service and changes no production endpoint.


## Subsequent simulation correction (2026-09-27)

The desktop-free simulation found that the original GLiNER2 adapter did not put caller descriptions in the upstream `entity_descriptions` field. The historical 20/20 browser outcome remains a measured result, but it is not evidence that description conditioning worked. The corrected adapter passes fresh inference on all 35 saved booking requests. See [simulation report](simulation/REPORT.md) for repairs, limitations and the pending identity-boundary policy.
