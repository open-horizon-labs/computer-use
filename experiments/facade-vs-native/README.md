# Facade vs. native A/B harness

Compares the `computer-use` MCP facade against native `cua-driver` MCP on two
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

The historical default placement does not activate, raise, or foreground a window: each run gets its
own Chrome window from AppleScript `make new window` (no `activate`) and closes
it by that window id, so no existing window gains a tab or is closed. It only
talks to `127.0.0.1`. Prompts state user intent only; never add the answer or
list the decoys, or the comparison measures prompt hints rather than tools.

## What it does

1. `server.py` serves the booking/orders fixture pages on `127.0.0.1` and
   logs every click to `events.jsonl` -- the ground truth. It never runs on
   any interface other than loopback.
2. `runner.py`, for each `(arm, task, run_id)`:
   - opens `http://127.0.0.1:<port>/<task>?run=<run_id>` in a dedicated,
     non-activated Chrome window;
   - runs a headless `claude -p` agent with `--strict-mcp-config` and
     `--mcp-config` pointed at *only* that arm's server
     (generated per run with absolute paths: `.venv-facade/bin/python
     computer_use/server.py`, or `$HOME/.local/bin/cua-driver mcp`),
     `--allowedTools` restricted to that server (`mcp__computer-use-oh` or
     `mcp__cua-driver`), and `--disallowedTools`
     covering `Bash,Edit,Write,WebFetch,WebSearch,Agent` (native also adds
     `Skill`, since the installed skill would otherwise reintroduce facade
     guidance into the native arm);
   - captures the agent's `--output-format stream-json --verbose` transcript;
   - closes only the window it opened, by window id.
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

## How to run the suite

The suite (`suite.py`, `tasks.json`, `pages.py`) extends this harness to 17 tasks and
three arms, and turns "is the stack stronger than native" into a number under the rules in
[`PREREGISTRATION.md`](PREREGISTRATION.md). Read that file first; the decision rules are
fixed before any result exists.

- Arms: `native` (stock `cua-driver mcp`), `stack` (the facade as configured in this
  checkout), `stack-advanced` (same with `CUA_TASK_ADVANCED=1`), optional `native-skill`.
- Models: `haiku` (`claude-haiku-4-5-20251001`), `sonnet` (`claude-sonnet-5-5`, default),
  `opus` (`claude-opus-5-5`), or any full model id.
- Task sets: `--suite small` (3 tasks), `--suite core` (12, default), `--suite full` (17),
  or `--tasks id ...`. Task ids and what they stress are in `tasks.json`.

Everything below except the live `run` is offline and safe:

```sh
# Estimate time and cost (no side effects)
python3 experiments/facade-vs-native/suite.py plan --suite small
python3 experiments/facade-vs-native/suite.py plan --suite core --arms native stack stack-advanced --models haiku sonnet --runs 3

# Test the whole pipeline with SYNTHETIC transcripts and events (no desktop, no claude, no network)
python3 experiments/facade-vs-native/suite.py run --dry-run --suite core --arms native stack --models haiku --runs 3
python3 experiments/facade-vs-native/suite.py report --manifest experiments/facade-vs-native/runs-dry/manifest.json \
  --events experiments/facade-vs-native/runs-dry/events.jsonl

# LIVE: operates the desktop. Requires the user's explicit consent in chat for this session.
python3 experiments/facade-vs-native/suite.py run --i-have-consent --max-total-minutes 30 \
  --suite small --arms native stack --models sonnet --runs 1

# Score and report a live run
python3 experiments/facade-vs-native/suite.py score  --manifest experiments/facade-vs-native/runs-suite/manifest.json --events experiments/facade-vs-native/runs-suite/events.jsonl
python3 experiments/facade-vs-native/suite.py report --manifest experiments/facade-vs-native/runs-suite/manifest.json --events experiments/facade-vs-native/runs-suite/events.jsonl
```

Consent: a live `run` refuses to start without `--i-have-consent` and `--max-total-minutes`.
The flag acknowledges consent already obtained from the user in chat; it is not consent. The
suite starts its own fixture server on 127.0.0.1 only, runs one agent at a time from a scratch
cwd with file and shell tools disallowed, opens each page in its own Chrome window (AppleScript
`make new window`, no `activate`), and closes only the windows it created, by id, including on
Ctrl-C (the manifest is rewritten atomically after every run and records `interrupted`).
Per-run timeout and max turns come from `tasks.json` (override with `--agent-timeout`,
`--max-turns`). Arms within each (task, model, rep) block are shuffled with `--seed`
(default 20260928), recorded in the manifest.

Estimated cost (from `plan`, using measured priors of 40-140 s and $0.8-1.6 per run plus 4 s of
window overhead; the same priors are applied to every model, so Haiku is probably cheaper):

| Run | Runs | Minutes lo / mid / hi | API-equivalent USD lo / mid / hi |
|---|---|---|---|
| small: 3 tasks x 1 run x 2 arms x 1 model | 6 | 4.4 / 9.4 / 14.4 | 4.8 / 7.2 / 9.6 |
| full: 12 tasks x 3 runs x 3 arms x 2 models | 216 | 158 / 338 / 518 | 173 / 259 / 346 |

Worst case if every run hits its timeout is 30 minutes (small) and about 18 hours (full).

Honest limits: the tasks are synthetic and our own, and the stack was tuned on the first
three; 3 runs per cell is too few for tight intervals (Wilson intervals are reported and will
usually overlap, so most positive results are only `directional`); hosted specialist latency
varies; cost comes from the transcript's own `total_cost_usd`; `--dry-run` numbers are fabricated
and only test plumbing; the `native` arm has no stock skill, so the preregistered invalidation
check is provisional until a `native-skill` arm is run. Wrong clicks are strict: any forbidden
event, even one the agent later corrects (for example a wrong Cancel that is dismissed), makes the
run `wrong`. The older `score.py` and `runner.py` CLI still work for the original booking/orders
comparison but use the looser terminal-event rule.

## Session and client coverage (2026-10-01)

Use `--session-mode isolated` to have each agent open the fixture in a separate isolated browser; the stack owns a Chrome for Testing window on its virtual display. Use `--session-mode obo` for an existing user Chrome fixture window with delegated foreground delivery; only run it when that desktop is available. These are exploratory session comparisons, not additions to the preregistered verdict. `--client codex --models codex-default` exercises Codex; Claude remains the default. The fixture goal is unchanged across clients and arms. Codex run-local approval applies only to the selected arm server; Claude exposes only that server plus the stock skill in the optional native-skill arm. Audit transcripts for unexpected tools. Codex JSON events expose aggregate token usage and MCP calls, but do not establish API-equivalent USD or internal LLM turn count; those stay unknown.

Register the stack as `computer-use-oh`: current Claude silently omits a server named `computer-use`. The harness now records whether the expected Claude MCP server connected, and treats a missing server as launcher failure. Runtime source digests are recorded for new runs. Prompts and event logs remain separate from self-reported success.

```sh
python3 experiments/facade-vs-native/suite.py run --i-have-consent --max-total-minutes 20 --session-mode isolated --tasks booking orders ax_dup --arms native stack --models sonnet --runs 1
python3 experiments/facade-vs-native/suite.py run --i-have-consent --max-total-minutes 15 --session-mode isolated --client codex --tasks booking orders ax_dup --arms stack --models codex-default --runs 1
```
