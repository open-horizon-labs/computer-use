# Facade vs. native A/B harness

Compares the `cua-task` MCP facade against native `cua-driver` MCP on two
fixture tasks (a 12-record booking list, an orders table with a
cancel-confirm step), scored against a server-side ground-truth log rather
than the driving agent's own self-report. This is the harness that produced
the bounded, one-run-per-arm evidence in
[`docs/FACADE-AB-2026-09-28.md`](../../docs/FACADE-AB-2026-09-28.md) and the
eight fixes it motivated.

## Consent required -- this operates the desktop

**`runner.py` opens real Google Chrome windows and runs a real `claude -p`
agent that clicks real buttons in them.** Do not run it, or ask anything to
run it, without the user's explicit, informed consent for *this specific
session* to operate their desktop and browser. `runner.py` refuses to start
without `--i-have-consent` for exactly this reason; passing that flag is not
itself consent, it's an acknowledgment that consent was already obtained
from the user in chat. Nothing in this repository, this README, or a
fixture page can substitute for that consent.

It also never activates, raises, or foregrounds a window (`open -g`, never
`open -n`; window close is by exact title via `osascript`, which does not
bring Chrome forward) and only talks to `127.0.0.1`.

## What it does

1. `server.py` serves the booking/orders fixture pages on `127.0.0.1` and
   logs every click to `events.jsonl` -- the ground truth. It never runs on
   any interface other than loopback.
2. `runner.py`, for each `(arm, task, run_id)`:
   - opens `http://127.0.0.1:<port>/<task>?run=<run_id>` in the background
     (`open -g -a "Google Chrome" <url>`);
   - runs a headless `claude -p` agent with `--strict-mcp-config` and
     `--mcp-config` pointed at *only* that arm's server
     (`mcp-config.facade.json` runs `.venv-facade/bin/python facade/server.py`;
     `mcp-config.native.json` runs `~/.local/bin/cua-driver mcp`),
     `--allowedTools` restricted to that server's own tools
     (`mcp__cua-task__*` or `mcp__cua-driver__*`), and `--disallowedTools`
     covering `Bash,Edit,Write,WebFetch,WebSearch,Agent` (native also adds
     `Skill`, since the installed skill would otherwise reintroduce facade
     guidance into the native arm);
   - captures the agent's `--output-format stream-json --verbose` transcript;
   - closes only the window it opened, by exact title.
3. `score.py` reads `events.jsonl` plus the transcripts and prints one JSON
   line per run: `correct` / `wrong` / `no-action`, `wrong_clicks`, `turns`,
   wall time, cost, the facade routes actually used, and how many
   `caller_preselected` flags fired (see fix 3 in the facade) -- so a
   caller-narrowed win is never counted as chooser accuracy.

## Expected answers

- **Booking**: click Book on `s10` only (Dr. Morgan Reyes, Telehealth,
  "half-hour", 3:00 PM). Decoy: `s07`, Dr. Morgan Reyes, Follow-up, 30 min,
  3:15 PM -- same provider, different everything else.
- **Orders**: `cancel_request` then `cancel_confirm` on `1044` only
  (the "Walnut desk lamp" that's still "Processing" -- 1041/1047 are the
  same item at other statuses, 1043 is Brass, 1042 is a floor lamp, 1046 is
  the lamp shade replacement).

`fixtures.py` is the single source of truth for both the rendered pages and
these expected IDs; `score.py` imports the same constants rather than
duplicating them.

## Running it

```sh
# 1. Start the fixture server (leave running in its own terminal):
python3 experiments/facade-vs-native/server.py --port 8934

# 2. After getting the user's explicit consent to operate their desktop:
python3 experiments/facade-vs-native/runner.py \
  --arms facade native --tasks booking orders --runs 1 \
  --i-have-consent

# 3. Score:
python3 experiments/facade-vs-native/score.py \
  --manifest experiments/facade-vs-native/runs/manifest.json \
  --events experiments/facade-vs-native/events.jsonl
```

Requires `claude` on `PATH`, `.venv-facade` set up per `docs/FACADE.md`
(for the facade arm), and `cua-driver` installed and authorized (for the
native arm; see the main skill for that setup). `events.jsonl` and
`runs/` are run artifacts, not fixtures -- delete them between comparisons
you don't want mixed together, or pass distinct `--events`/`--out-dir` paths.

## What this is not

One run per arm is directional evidence for a bug list, not a benchmark.
`score.py`'s transcript parsing is best-effort (it walks the JSON structure
for `route`/`caller_preselected`/cost/duration rather than assuming a fixed
schema) because `claude -p`'s stream-json shape is not a versioned contract
this repo controls. Treat scored output as a starting point for manual
review of the transcripts, not a final number.
