# Desktop-free CESS simulation — 2026-09-27

The simulation exposed and repaired projection defects without browser or native computer use. Current projection passes the controlled corpus; actual inference exposes one remaining sketch-policy question. This is bounded falsification, not proof of general CUA correctness.

## Simulator and reproducibility

`../simulation.py` supplies observations, invokes the real dispatch projection, applies bound operations to sandbox state, and compares resulting effects with separately stored expected effects. Expected effects are never provider inputs. Controlled providers inject faults; `../simulate_live.py` replaces them with actual GLiNER2 and the persistent Fleet Jev selector (including its existing Qwen escalation). GPU inference used GPU1/3060Ti in guest 210; no training was needed. Qwen/SystemOne were not stopped or reconfigured.

Run from repository root:

```sh
~/.local/share/fleet-cua-decider/.venv/bin/python inference/cua-decider/capability-dispatch/simulation_gate.py
```

The gate includes a recorded actual extraction failure to reproduce the pending policy boundary. Live reruns require existing Fleet credentials and remote inference setup; they are not prerequisites for the controlled gate.

## Results

| Evidence | Result | Meaning |
|---|---:|---|
| Original controlled baseline | 15/24 | Nine failures retained in `baseline.json` |
| Repaired controlled corpus | 28/28 | Includes four added cases; not directly an accuracy comparison with baseline |
| Metamorphic variants | 40/40 | Arbitrary IDs, field names and record order |
| Unit/contract gate | 20/20 | Prior 19 plus upstream description-schema contract |
| Deliberately wrong repairs | 7/7 rejected | Always Jev, no recovery, accept NaN, weak binding, discarded hybrid evidence, false success, lost descriptions |
| Historical evidence replay | 35/35 | Current projection over prior captured provider outputs |
| Fresh inference on saved booking requests | 35/35 | Corrected GLiNER2 adapter; no desktop actions |
| Current policy, actual providers | 3/4 | Product identity boundary still fails |
| Proposed policy, actual providers | 4/4 | Opt-in Jev recheck fixes that case; small diagnostic sample |

Actual-provider numbers are correctness observations, not stable latency estimates or broad model benchmarks. The current and proposed runs are separate inference runs, not a controlled statistical comparison. All provider requests, responses and sandbox effects are preserved in the JSON traces.

## CESS cycles and accepted repairs

`../COUNTEREXAMPLES.json` is accepted archive A. `../SKETCH.md` is S; dispatch/provider code is P. The unit cases, controlled scenarios and mutation checks form curated R/G. `SKETCH-REVIEW.json` records a separate case-by-case capable-model self-review against S. The reviewer is the implementing assistant, not an independent reviewer; final review is not backdated to intermediate cycles.

| CE | Classification and authority | Projection correction / retained protection |
|---|---|---|
| CE-CAP-003 | User-approved Jev default/fallback, S4.3 | Default and bounded recovery; healthy specialist stays specialized; cycles 01–02 |
| CE-SIM-001 | Existing S4.2.6 implementation defect | Full request binding digest; reject changed arguments and stale execution; cycle 03 |
| CE-SIM-002 | Existing S4.2.3–4 implementation defect | Reject nonfinite and invalid probabilities; cycle 04 |
| CE-SIM-003 | Existing S4.2.4–5 implementation defect | Permit caller-specified ordering without an invented predicate; cycle 05 |
| CE-SIM-004 | Existing S4.3 implementation defect | Retain partial hybrid evidence and known exclusions during recovery; cycle 06 |
| CE-SIM-005 | Existing S4.2.3 implementation defect | Encode caller descriptions in GLiNER2 `entity_descriptions`; cycle 07 |

The description bug is material: passing descriptions as the values of raw `entities` did not condition the model as intended. The installed upstream schema builder uses separate `entities` and `entity_descriptions` mappings. Original description probes had identical confidence values; corrected probes changed them. Historical successful actions remain historical successes, but do not establish the intended description mechanism was operating.

The first live stock assertion wrongly demanded a specialist-only route despite real missing evidence. `ADJUDICATION.json` records correction of that review error under existing S4.3, preserving the expected effect and original failed trace.

## Pending CE-SIM-006: extracted identity boundary

For `Acme product: $12` and `Acme product: $7`, GLiNER2 extracts `Acme product` as brand, rather than `Acme`, with high confidence. Exact equality excludes both. Current S4 prohibits reviving known exclusions; confidence and valid offsets do not establish correct semantic boundaries.

[PROPOSED-SKETCH.md](PROPOSED-SKETCH.md) evaluates a narrow rule: whole-value overlap in an over-wide text span makes that field uncertain and allows Jev to recheck the original observation and constraints. It never makes substring equality sufficient. The simulation-only `boundary_recheck=True` flag defaults off.

Actual-provider simulation passes 4/4 with this candidate, including the $7 product through GLiNER2 → Jev. Deterministic safeguards confirm: no generic provider means no action; word-internal substrings stay excluded; another known failing predicate still excludes; default behavior still reproduces the unresolved failure. Neighboring identities such as Acme Pro can also reach review, which is why this is a proposed policy change rather than an automatic implementation repair.

## Risk retirement and boundaries

- Binding, malformed scores, provider failure, partial evidence, tie authority, exact-operation scope, and false-success shortcuts are covered by controlled cases, mutation checks, and sketch review.
- Model quality is sampled only for GLiNER2 and the generic selector. Controlled route coverage for GLiNER, GLiNER2.5 and Decide does not qualify those checkpoints.
- No real accessibility freshness, native execution, or full visual grounding was exercised. The three-frame exact-control flow does not establish semantic confirmation-extraction coverage.
- No clean-room regeneration of P from S+K was performed. Sketch sufficiency remains an explicit open validation item.
- No training, production installation, or infrastructure changes were needed for this run.

Next active failure is CE-SIM-006 pending policy authority. Accepted projection repairs pass the exercised deterministic gate and current self-review; the entire generic CUA problem is not declared solved.


## Subsequent approval

The user approved CE-SIM-006. Its rule is now S4.4 and enabled by default in the experimental Engine; the earlier pending status above describes the original run. All controlled gates pass after promotion. See JEV-COMPARISON.md for the subsequent paired inference comparison.
