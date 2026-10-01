# Surfaces A/B: stock Cua Driver vs. look/do, with an interruption monitor

Compares two ways of driving the same ten everyday jobs across surfaces (web, macOS apps, an Android emulator, an iOS
simulator), scored from independent ground truth, with one extra core metric: **how much each arm interrupts the person
sitting at the Mac**.

- `native`: `$HOME/.local/bin/cua-driver mcp` only (stock Cua Driver MCP tools).
- `computer-use`: this repo's server (`computer_use/server.py`, tools `look` and `do`) only, run with the main checkout's
  `.venv-facade` (override with `CUA_FACADE_PYTHON`).

Both through `claude -p --model claude-sonnet-5-5`, max 60 turns, 600 s timeout, `--strict-mcp-config` with exactly one
server, file/shell/web tools disallowed (and `Skill` in native), run from a scratch cwd. Reuses the patterns of
[`../facade-vs-native`](../facade-vs-native/README.md): per-arm MCP config, stream-json transcripts, a server-side event log
as ground truth, prompts that state user intent only (a test lints every prompt for answers, decoys and tool names).

## Consent required: this operates the desktop

`runner.py` opens real windows (a Chrome for Testing window, an Android emulator, Simulator, Calculator) and runs an agent
that clicks in them. It refuses to start without `--i-have-consent`; that flag is the maintainer's record that the user
consented in chat, **not** consent itself. Consent for the 2026-10-01 smoke run was given by the user in chat.
**Do not touch the mouse or keyboard during a run**: the monitor cannot tell your input from the agent's.

## The ten jobs

| # | id | surface | what the user asks | judged by |
|---|---|---|---|---|
| 1 | `booking` | web (fixture) | book the earliest 30-minute slot with a named doctor after 2 PM | server event log (reused fixture, decoys) |
| 2 | `orders` | web (fixture) | cancel the unshipped walnut desk lamp order (cancel + confirm) | server event log (reused fixture) |
| 3 | `form` | web (new fixture) | fill and send an intake form (text, select, checkbox, textarea) | submitted field values, exact |
| 4 | `upload` | web (new fixture) | attach a local file (path in the prompt) and send | server logs filename, size, sha256 vs the prepared file |
| 5 | `compare` | web (new fixture) | read 3 product pages, name the cheapest one in stock | final text vs fixture constants (cheapest overall is out of stock) |
| 6 | `wikipedia` | real web, read-only | one infobox value (Mount Everest elevation) | final text vs a value the harness fetches from the MediaWiki API before the run |
| 7 | `calculator` | macOS | compute `47 x 28`, report the display | final text vs 1316 |
| 8 | `textedit` | macOS | new document with a given sentence, left unsaved | harness reads the document through AppleScript, then closes it WITHOUT saving |
| 9 | `android` | emulator `androidnaa-api35` | Android version from Settings > About | `adb shell getprop ro.build.version.release` |
| 10 | `ios` | booted iPhone 17 Pro simulator | iOS version from Settings > General > About | `simctl list devices -j` runtime of the device |

Outcomes: `correct`, `wrong`, `no-action` (the agent never acted) or `timeout`. Text answers are strict: `compare` is wrong if

**Changed after the first run (2026-10-01):** `compare` was scored wrong whenever the reply mentioned a decoy price. Both arms named the right lamp and price and mentioned the decoys only to explain the choice, so the rule is now: correct if the reply names the right lamp and price and does not lead with a decoy. Results report both the strict and the relaxed score.
the reply also mentions a decoy price; numbers ignore thousands separators; versions ignore a trailing `.0`.

## Surfaces and where windows go

| | native | computer-use |
|---|---|---|
| web | a dedicated **Chrome for Testing** (`~/.cache/computer-use/browsers/chrome/*/chrome-mac-arm64/`) with its own temp `--user-data-dir`, opened on the main screen by the harness, killed after. Never the user's Google Chrome. | the facade's own agent browser on the agent (virtual) display; the prompt gives the URL |
| macOS apps | launched by the harness (`open -g`), quit after; refused if the app is already running (the user's documents are never at risk) | same |
| Android | emulator started windowed by the harness, killed after | emulator started `-no-window`, killed after; `device=<AVD name>` |
| iOS | drives the Simulator.app window (opened by the harness only if it was not running) | `device=<UDID>`; Simulator.app is not started |

Asymmetry to keep in mind when reading results: native is *handed an open window* and computer-use *a URL or device id*,
because that is how each tool is meant to be addressed. The harness only starts and cleans what a job needs; it diffs the
process list before and after every run, kills strays it can attribute (Chrome for Testing, emulator, space-mover,
mobile-mcp) and records anything still running.

## The interruption monitor (`monitor.py`, `sampler.swift`)

A sampler (compiled once to `~/.cache/computer-use/surfaces-ab/sampler`, read-only, never posts events) logs every 200 ms
the frontmost app, the cursor, the displays (the agent display is recognised by its vendor/model ids) and on-screen
windows. It starts after the harness has opened the surface, so the harness's own setup is not counted. Per run:

- `focus_changes` / `focus_steals`: frontmost app changed; a steal is a change to an app other than the one frontmost at the start.
- `new_user_windows`: a window not present at the start that overlaps a real display. A window wholly inside the agent display
  does not count; one straddling both does. `windows_to_user_display`: a window that began on the agent display and moved onto
  a real one. Full-screen Cua Driver overlays are counted apart (`overlay_windows`).
- `cursor_move_samples`, `cursor_bursts`, `cursor_px`: pointer moves over 2 px. **It cannot separate user moves from agent
  moves**, so a number is an upper bound valid only if the user kept their hands off.
- A timeline (`*.monitor.jsonl`) and plain-English `annoyances` derived from it.

Limits: flickers shorter than 200 ms can be missed; window titles are empty without Screen Recording permission (owner and
bounds still identify a window); the sampler needs `swiftc`.

## Running it

```sh
# Offline: tests, and the cost/time estimate (no side effects)
python3 -m unittest discover -s experiments/surfaces-ab -p 'test_*.py'
python3 experiments/surfaces-ab/runner.py --plan

# LIVE (needs the user's consent in chat; do not touch the mouse): the full suite, 10 jobs x 2 arms
python3 experiments/surfaces-ab/runner.py --i-have-consent --max-total-minutes 120

# One job, one arm, or a re-score of a finished run
python3 experiments/surfaces-ab/runner.py --i-have-consent --tasks calculator --arms native
python3 experiments/surfaces-ab/score.py --manifest experiments/surfaces-ab/runs/<stamp>/manifest.json
```

Each run directory holds `manifest.json` (prompt, truth values, monitor summary, cleanup report), `events.jsonl` (server
ground truth), `<run>.transcript.jsonl` (stream-json with screenshots and base64 removed and long strings capped),
`<run>.monitor.jsonl`, `results.json` and `results.md`. No secrets are written: the arms inherit your environment but the
runner records only the MCP config (commands and paths).

Arm order within each task is shuffled with `--seed`. `--runs N` repeats each cell. TextEdit is skipped (and recorded as
skipped) when TextEdit is already running; an Android emulator already running skips the Android job.

## Phase 1 smoke (2026-10-01, job 1 only, one run per arm)

`runs/smoke-booking/`: native booked `s10` correctly (10 turns, 8 MCP calls, $0.97, 50 s, 0 focus steals, 0 new windows on the
user's screen, 0 cursor movement). The **computer-use record in that directory is a harness defect, not a measurement**: the
arm's MCP server was keyed `computer-use`, a name Claude Code drops, so the agent started with no tools (`mcp_servers: []`),
made no tool call and stopped after 8 s. The key is now `cua-task` (verified: init lists `mcp__cua-task__do` and `look`); the
computer-use arm has not yet been re-run. Rerun it with:

```sh
python3 experiments/surfaces-ab/runner.py --i-have-consent --tasks booking --arms computer-use --out-dir experiments/surfaces-ab/runs/smoke-booking-cu
```

## What this is not

One run per cell is directional evidence, not a benchmark. The fixtures are ours, the Wikipedia value is read live, the
iOS and Android jobs depend on the local simulator and AVD, and phase 1 exercised only job 1 live: the mac, Android and iOS
setup code is covered offline for argv and process-diff logic only.
