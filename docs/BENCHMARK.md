# Benchmark: nine everyday jobs, three ways

Run on 2026-10-01 with Claude Sonnet 5.5 (`claude-sonnet-5-5`) on one Mac. Each job ran once per arm. The raw rows are in [experiments/surfaces-ab/results-2026-10-01.jsonl](../experiments/surfaces-ab/results-2026-10-01.jsonl); the harness is [experiments/surfaces-ab](../experiments/surfaces-ab/README.md).

| | Vanilla computer use | Stock Cua Driver tools | computer-use |
|---|---|---|---|
| Correct | 7 of 9 | 8 of 9 | **9 of 9** |
| Turns | 156 | 154 | **86** |
| Output tokens | 23.5k | 35.8k | **20.2k** |
| Wall time | **483 s** | 643 s | 529 s |
| Cost | $2.70 | $7.16 | **$1.95** |
| Where it runs | your screen, your mouse and keyboard | agent display, background input | agent display, background input |

## The three arms

- **Vanilla computer use.** What a plain Claude does: a `computer` tool with the Anthropic API tool's actions (screenshot, click at x/y, type, key, scroll), screenshots of the main display scaled to fit 1280x800, real mouse and keyboard events. Claude Code's built-in computer use cannot run under `claude -p`, so the arm uses a small local server with the same contract ([vanilla_cu.py](../experiments/surfaces-ab/vanilla_cu.py)).
- **Stock Cua Driver tools.** The Cua Driver MCP server on its own (`cua-driver mcp`): accessibility tree, screenshots, background clicks and typing.
- **computer-use.** This repository's server: `look`, then `do`, with the agent browser and app windows on the virtual agent display.

Each run is a headless `claude -p` agent that sees only its arm's tools. The prompt states the user's goal and nothing about how to do it.

## The jobs

| Job | Surface | What the agent is asked | How it is scored |
|---|---|---|---|
| booking | web fixture | book one appointment among 12 similar ones | the fixture server's click log |
| orders | web fixture | cancel one order, with a confirm dialog | the click log |
| form | web fixture | fill and send an intake form (text, a dropdown, a checkbox) | the submitted fields |
| upload | web fixture | attach a given file and send | the received file's name and size |
| compare | web fixture | find the cheapest in-stock item across three pages | the answer against the fixture |
| wikipedia | real web, read-only | read one value from a Wikipedia infobox | the answer against the fetched page |
| calculator | macOS app | work out a sum in Calculator | the answer against the sum |
| android | Android emulator | read the Android version from Settings | the answer against `getprop` |
| ios | iPhone simulator | read the iOS version from Settings | the answer against `simctl` |

## Per job

| Job | Vanilla | Stock Cua Driver | computer-use |
|---|---|---|---|
| booking | correct, 6 turns, 23 s, $0.25 | correct, 13 turns, 58 s, $0.89 | correct, 5 turns, 32 s, $0.17 |
| orders | correct, 6 turns, 24 s, $0.13 | correct, 12 turns, 55 s, $0.93 | correct, 12 turns, 54 s, $0.26 |
| form | failed, 64 turns, 162 s, $0.86 | correct, 27 turns, 135 s, $1.40 | correct, 17 turns, 89 s, $0.29 |
| upload | failed, 12 turns, 47 s, $0.23 | failed, 14 turns, 49 s, $0.69 | correct, 8 turns, 43 s, $0.19 |
| compare | correct, 25 turns, 68 s, $0.39 | correct, 15 turns, 47 s, $0.66 | correct, 7 turns, 61 s, $0.18 |
| wikipedia | correct, 3 turns, 10 s, $0.09 | correct, 7 turns, 27 s, $0.35 | correct, 4 turns, 45 s, $0.15 |
| calculator | correct, 13 turns, 42 s, $0.22 | correct, 20 turns, 78 s, $0.56 | correct, 11 turns, 77 s, $0.25 |
| android | correct, 20 turns, 81 s, $0.39 | correct, 31 turns, 128 s, $0.96 | correct, 16 turns, 70 s, $0.30 |
| ios | correct, 7 turns, 26 s, $0.15 | correct, 15 turns, 67 s, $0.73 | correct, 6 turns, 56 s, $0.16 |

## What the numbers say

- computer-use finished every job, in the fewest turns, at the lowest total cost, without using your screen.
- Vanilla is fast and cheap on simple read-only jobs: one small screenshot is often enough. It fails where text and dialogs matter: it dropped a character typing a name and gave up after 64 turns, and the path it typed never reached the file dialog.
- The stock Cua Driver tools cost the most. Every call returns a full-resolution screenshot and the accessibility tree, and the agent carries those forward each turn.
- Upload failed for both other arms: the native file picker. computer-use sets the file on the page's file input directly, so no picker opens.
- computer-use is slower than vanilla on the simplest jobs: each `do` re-reads the page and checks its `expect` before it answers.

## Interruptions

computer-use and the stock Cua Driver tools ran on the virtual agent display with background input, so neither put a window on your screen. computer-use took focus once per web job, when its browser started: about 3.5 s each since the 0.1.2 fix ([#97](https://github.com/open-horizon-labs/computer-use/issues/97) tracks removing it). Vanilla uses your real pointer and keyboard on your main screen for the whole run; you cannot use the machine while it works.

## Limits of this run

- One run per job and arm: read the direction, not the decimals.
- The vanilla arm uses our own executor with the API tool's interface, not Anthropic's. Some of its typing failures may come from our key-event pacing.
- The stock arm's Android row comes from an earlier batch of the same day: the emulator window could not be moved to the agent display, so it ran on the main screen.
- TextEdit was not run: the user's TextEdit was open, and the harness never touches the user's documents.
- The first stock and computer-use iOS runs may have started on the About screen left by an earlier run; the harness now resets Settings before every iOS run, and the vanilla iOS row is from a run after that fix.

## Next

Each failure and slow step here is a candidate fix in a later release: the goal is better tools, measured on this suite, not a higher score on it.
