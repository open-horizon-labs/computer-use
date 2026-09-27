# Julia-1 on saved CUA decisions

## Result

Julia-1 is **not a replacement for Jev or the current GLiNER2 route on this
trace**. On 35 booking decisions, Julia selected the recorded action 15 times
(42.9%), compared with Jev's 21 (60.0%) and the GLiNER2 extraction plus typed
reducer's 35 (100%). Julia's median warm request round trip to the 3060 Ti was
15.4 ms; its model-only median after the first warm-up request was 9.8 ms.
That speed does not compensate for the correctness loss. Across all 39 paired
cases, Julia was correct on 17, Jev on 25, and the current dispatcher on 39.

These are repeated decisions from the existing development fixtures, not a
held-out or live-browser evaluation. The 35 booking decisions belong to 20
tasks and are correlated. The other four cases are small dispatcher simulations.
No actions were executed in a live browser.

| Arm | Booking decisions | Correct | Median decision/round-trip time | All booking tasks complete |
| --- | ---: | ---: | ---: | ---: |
| Julia-1, finite-choice | 35 | 15/35 (42.9%) | 15.4 ms | 2/20 |
| Jev, saved direct baseline | 35 | 21/35 (60.0%) | 135.2 ms | 8/20 |
| GLiNER2 + typed reducer, saved active-dispatch baseline | 35 | 35/35 (100%) | 29.4 ms | 20/20 |

The timing columns are measurements from different paths: Julia includes a
resident remote worker round trip over SSH to the 3060 Ti, while Jev and the
dispatcher values are their recorded decision timings. Treat them as indicative,
not a controlled latency bake-off. Julia's 2.56-second model load is also outside
the warm-request median.

## Test protocol

The benchmark pairs exact request IDs and expected action IDs with the saved
Jev/dispatcher run. Julia receives the original recorded goal, accessibility
observation, and history as `state`; caller predicates and ordering as part of
the question; and action descriptions as finite-choice options. `reobserve` and
`abstain` are included as choices. Expected action IDs are used only after the
model responds. There are 3–9 choices per request.

The first harness pass omitted the original goal and accessibility observation
from Julia's state and returned 6/39. That run was invalid and is not used in the
comparison. The corrected pass preserves the complete recorded state and returns
17/39. Both runs used the same pinned weights; only the corrected run is saved
in `RESULTS.json`.

Julia ran on the RTX 3060 Ti (GPU 1) from the NAS-backed checkpoint at pinned
revision `a85b127321d580d65176c89ced8273f305745d85`. The checkpoint SHA-256 is
`df853bf7fe424420011f3d0c47a05d7341aa9eefa7fb9f203ea4aada4ad95b72`. The
published optimized `load_model`/FastEngine path had failed during setup, so the
comparison uses the package's `TransformerEngine` reference path with the same
weights. The runner process exited after the test; Qwen on GPU 0 was not touched.

Re-run with `JULIA_WORKER_COMMAND` set to a JSON argv array pointing to the
remote worker and pinned checkpoint, then:

```bash
python3 experiments/julia1-cua-2026-09-27/compare.py
```

The paired inputs and baseline are
[`booking-100-119.json`](../../inference/benchmarks/cua-capability-dispatch-2026-09-27/booking-100-119.json)
and
[`strangler-shadow-trial-2026-09-27.json`](../../inference/cua-decider/capability-dispatch/simulation/strangler-shadow-trial-2026-09-27.json).
Machine-readable row results are in [`RESULTS.json`](RESULTS.json).

## Scope of conclusion

This test does not establish Julia's value for CUA classification/routing tasks:
the paired CUA corpus contains no dedicated `classify` requests, and the four
simulation cases are not a meaningful classification benchmark. The published
Julia card reports 73.15% on its typed-decision suite versus a supplied 72.70%
Jev reference, a 0.45 percentage-point difference; it also reports 64% on its
Banking77 pilot versus the supplied 87% Jev reference. Those results justify
testing a purpose-built CUA classification fixture before considering Julia for
that role, but do not support replacing a currently working route. See the
[Julia-1 model card](https://huggingface.co/SupersonicLabs/Julia-1).

Julia also does not perform span extraction. This comparison deliberately tests
it as a direct finite-choice selector; it does not replace the GLiNER2 field
extraction and typed reducer with another extraction model.
