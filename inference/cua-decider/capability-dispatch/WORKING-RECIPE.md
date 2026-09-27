# Working recipe: described-field action matching with GLiNER2

This is the inference and dispatch recipe behind the successful specialist
replay. It is **not** a fine-tuning recipe: the qualified model is the cached
`fastino/gliner2-base-v1` checkpoint. The in-house Decide LoRA adapters were
evaluated separately and did not qualify for this role.

## Qualified task contract

Dispatch here only when the controller supplies a fresh snapshot ID, the
complete current candidate set, candidate IDs and exact operation, source text
scoped to each candidate, short English fields with a description per field,
explicit typed predicates and/or ordering, and `coverage_complete: true`. Any
business fallback is a separate, currently offered candidate.

The extractor recovers spans from each candidate's own text. The typed reducer
validates source offsets and text, normalizes each field, applies every
predicate to the same candidate, and selects only a unique best match. Missing,
conflicting, or ambiguous evidence recovers through Jev once; Jev cannot resolve
an incomplete scope or invent a tie-breaker. Requests outside this contract
continue through the generic dispatcher (Jev, with its existing Qwen escalation).
Duration normalization accepts `30 minutes` and the common adjective form
`30-minute`.

## Model and schema

Run the persistent worker on the CUDA host with the checkpoint already cached:

```sh
python3 workers/span_worker.py fastino/gliner2-base-v1
```

Configure the host-specific launcher as a JSON argv array, for example:

```sh
export CUA_SPAN_COMMAND='["python3", "/absolute/path/computer-use/workers/span_worker.py"]'
```

The selector appends the exact model ID. One long-lived worker batches all
candidate texts for a decision. Keep stdout for JSON-lines and send diagnostics
to stderr. Do not print or store credentials in this worker.

For each described field, pass its description separately from the entity name.
The GLiNER2 schema is equivalent to:

```json
{
  "entities": {"duration": "", "start_time": ""},
  "entity_descriptions": {
    "duration": "Appointment duration in minutes",
    "start_time": "Appointment start time"
  }
}
```

Batch one schema per candidate text and request source spans and confidence.
Raw `entities` values are labels, not descriptions; placing descriptions there
silently loses the caller's definitions. `providers.span_schema()` implements
the correct wire format and `RemoteSpans` performs the batch.

## Dispatch and verification

Create `RemoteSpans()` and one `FleetGeneric()` process for the task, then
construct the dispatcher with `{"gliner2": spans, "incumbent_jev": jev}` and
load `ROLLOUT.json` with `Strangler.from_config(...)`. The committed config
activates only `described-span-match/en`. Keep the same dispatcher and Jev
process for the task; close both at task end. The caller must still use
`execute_bound(...)` against the same fresh snapshot and stored Driver
arguments, then observe afresh and independently verify the requested
postcondition.

```python
from providers import FleetGeneric, RemoteSpans
from rollout import Strangler

spans = RemoteSpans("fastino/gliner2-base-v1")
jev = FleetGeneric()
selector = Strangler.from_config({"gliner2": spans, "incumbent_jev": jev})
try:
    decision = selector.decide(typed_request, current_snapshot_id)
    # Revalidate and execute only with execute_bound and the stock Driver.
    # Observe again and verify the caller-declared postcondition.
finally:
    jev.close()
    spans.close()
```

## Measured result and limits

On the saved 20-task booking trace, GLiNER2 matched 35/35 decisions and all
20/20 complete tasks; direct Jev matched 21/35 decisions and 8/20 complete
tasks. Warm median model decision time was 29.4 ms for GLiNER2 and 135.2 ms for
Jev. GLiNER2 startup (4.58 seconds) is excluded. Four controlled simulator
cases were also correct for both. See [the full trial and caveats](STRANGLER-TRIAL.md).

These are saved-fixture results, not a fresh live Driver qualification. They
support this narrow routing contract only. The repo dispatcher uses this config
when its caller loads it; changing this file does not modify the separately
installed `~/.local/share/fleet-cua-decider/select-fleet` process or the Cua
Driver installation. See [provider setup](../../../docs/PROVIDERS.md) and the
[skill setup reference](../../../skills/cua-capability-dispatch/references/setup.md).
