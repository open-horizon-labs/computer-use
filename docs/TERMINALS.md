# Terminal observation and action integration

The Cua Driver binary still observes and executes locally. `terminal_observation.py` is a reusable controller helper around its `get_window_state` API. It does not replace the Driver or run terminal commands behind the UI. Configure the installed Driver executable and reuse its session/window.

## Why AX-only polling failed

A terminal can draw a ready TUI without changing the accessibility text being compared. The first sample can already be ready. Stable AX or pixels cannot prove a hang, and cursor blink cannot prove progress. A successful key-delivery response cannot prove the application consumed the command.

Also confirm the actual command's scope. For the installed swamp CLI, `swamp` defaults to `ui`, but omitting ROOT uses configured scope. To inspect the requested working directory, use `swamp ui .` after changing directories. Do not bake application names or key bindings into the Driver.

## Configure visual interpretation

Use a deployed **screenshot-capable** chat-completion endpoint. The adapter does not enable vision on a text-only model. Configure `QWEN_BASE_URL` (including `/v1`), `QWEN_MODEL`, and runtime `QWEN_API_KEY`/`QWEN_API_KEY_FILE` or documented Fleet secret retrieval. No keys belong in screenshots, traces, or configuration committed to Git.

```sh
export PYTHONPATH=/absolute/path/computer-use/inference/cua-decider/capability-dispatch
export CUA_VISUAL_COMMAND='["python3", "/absolute/path/computer-use/workers/visual_worker.py"]'
```

For a read-only invocation, supply IDs from a fresh Driver window inventory:

```sh
python3 scripts/observe_terminal.py --pid PID --window-id WINDOW_ID \
  --session EXISTING_SESSION --postcondition 'The directory listing and sort controls are visible'
```

This prints the assessments and timing records, omitting raw screenshot bytes and the full AX tree.

The worker uses the standard multimodal chat format and strictly parses a completed JSON response. It has no desktop access. An endpoint that rejects images or returns malformed output yields uncertainty; there is no text-only fallback pretending to see pixels. The outer transport terminates a stuck worker. Server-side cancellation depends on the endpoint.

```python
from terminal_observation import VisualTerminal, wait_for_terminal

vision = VisualTerminal()
try:
    outcome = wait_for_terminal(
        pid, window_id, session=existing_session,
        postcondition='The requested directory listing and its sort controls are visible.',
        visual=vision, budget=20,
    )
finally:
    vision.close()
```

This reads the first fresh screenshot immediately, not only after noticing a change. A positive assessment needs visible evidence for the caller's postcondition. `ready` is an observation assessment, not authorization to execute or proof the whole task succeeded.

The returned snapshot includes `observation_quality`:

- AX text availability and change; terminal content coverage remains explicitly unknown.
- Screenshot availability, SHA-256 and change (encoded image comparison, not semantic progress).
- A requirement for visual interpretation and progress initially unknown.
- Immutable screenshot data from that observation, paired with its Driver snapshot ID.

Screenshots are read immediately from a unique temporary file before that file is removed, so later observations cannot overwrite the image being evaluated. Handle the returned image and AX text as private task data; do not indiscriminately log them.

`records` separates Driver latency from visual endpoint latency, plus a total `wall_ms`. Model loading/endpoint startup happens outside this helper and must be reported separately. Endpoint latency is not isolated model compute.

## Bounded waits and recovery

The helper spends at most one configured budget (maximum 20 seconds) across capture, visual inference and polling. It reserves the final portion for a fresh capture and interpretation. Timeouts terminate the subprocess transport; OS process cleanup can add a small scheduling overhead. If the final capture/interpretation is unavailable, report `unknown` and its cause. Never claim the app stalled when observation failed.

No Ctrl+C, relaunch, or retry is automatic. Reconcile the current state before a caller-authorized recovery, and allow at most one retry. An interrupt is an application action and requires the same current-state grounding as other actions. Unknown state must not be converted into an instruction to kill a process.

## Choose from visible controls, then bind and verify

Once the screenshot identifies current key hints or controls, the controller constructs offered action IDs with stored Cua Driver arguments. A vision model may describe what it sees or choose an offered ID; it must not supply executable arguments. Keyboard choices must be grounded in the visible hints or verified application interface, not guessed from another app.

`VisualTerminal` also implements the dispatcher provider interface for visual choices. Construct a semantic request with the fresh snapshot's `snapshot_id`, `screenshot_data_url`, current AX text as `observation`, goal, and offered actions. Preserve all predicates, scope and exclusions. The request digest includes the screenshot and stored arguments.

```python
from dispatch import Engine, execute_bound
from terminal_observation import VisualTerminal

vision = VisualTerminal()
try:
    # request is built from the SAME fresh Driver observation and image.
    selection = Engine({'jev': vision}).decide(request, current_snapshot_id)
    # 'jev' is the existing generic interface slot. Actual output route is visual.
    execute_bound(request, selection, current_snapshot_id, driver_execute_callback)
    # Independently observe the resulting screen and check the desired sort order.
finally:
    vision.close()
```

Check authorization before calling `execute_bound`; it rejects deferrals. If the current snapshot changed before execution, reobserve and rebuild the request/selection. Never replace screenshot bytes or arguments after selection. Do not route screenshots to Julia: its optional chooser accepts only text and finite options.

## Verification status

The helpers implement the requested integration change; they have not been live-qualified against Ghostty or the configured vision endpoint in this commit. The earlier Ghostty run established an observation failure, not a swamp rendering failure. Offline tests and another live bakeoff are separate work; historical simulation results do not validate these helpers.
