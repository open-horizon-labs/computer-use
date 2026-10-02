# Benchmark: actual Codex across six drivers and a mixed workflow

The 2026-10-02 experiment compares the installed OpenAI `cua_repl` plus Codex’s native PTY tools with OH’s `look`/`do`. Both arms use Codex CLI 0.159.2, `gpt-6-astra` with `ultra` reasoning, fresh conversations and the same disposable fixtures. The OH runtime is frozen at `0745718` for the measured batch. This is a different experiment from the Claude comparison below.

The [protocol and harness](../experiments/codex-mixed/README.md) cover terminal, web, real VNC, Android, iOS, a native Mac app, and a terminal-to-web receipt handoff. Each task has several actions and an independent completion check. There are three repetitions per arm, run serially with alternating order. The physical Mac remains locked; virtual displays were attempted for synthetic GUI targets, with placement/creation failures retained. Visible OBO is not measured.

## Baseline at `0745718`

| Task | Arm | Valid completion | All-attempt median wall (s) | Permission/setup blocks | Usage rows | All-attempt median input | All-attempt median cached input | All-attempt median output |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| terminal | native | 3/3 | 56.8 | 0 | 3/3 | 271,810 | 202,112 | 688 |
| terminal | oh | 3/3 | 80.9 | 0 | 3/3 | 369,281 | 332,288 | 1,594 |
| web | native | 2/3 | 107.6 | 0 | 2/3 | 434,554 | 396,480 | 1,506 |
| web | oh | 0/3 | 240.0 | 0 | 0/3 | unavailable | unavailable | unavailable |
| vnc | native | 3/3 | 87.2 | 0 | 3/3 | 378,358 | 342,528 | 1,320 |
| vnc | oh | 0/3 | 95.2 | 0 | 3/3 | 170,582 | 154,496 | 940 |
| android | native | 0/3 | 60.0 | 3 | 3/3 | 206,196 | 171,776 | 934 |
| android | oh | 0/3 | 86.7 | 0 | 3/3 | 172,180 | 156,032 | 1,213 |
| ios | native | 0/3 | 33.5 | 3 | 3/3 | 120,801 | 88,704 | 550 |
| ios | oh | 0/3 | 240.0 | 0 | 0/3 | unavailable | unavailable | unavailable |
| mac | native | 0/3 | 47.4 | 3 | 3/3 | 185,638 | 151,040 | 658 |
| mac | oh | 3/3 | 127.7 | 0 | 3/3 | 354,976 | 326,400 | 1,521 |
| mixed | native | 2/3 | 87.2 | 0 | 3/3 | 364,086 | 323,456 | 1,248 |
| mixed | oh | 0/3 | 240.0 | 0 | 0/3 | unavailable | unavailable | unavailable |

All-attempt medians include failed and protocol-invalid attempts and are diagnostic, not medians of completed tasks. Permission/setup blocks remain in the denominators and their wall time is refusal time, not completed-task performance. Android and iOS native access could not be qualified; the Mac fixture was missing from native inventory. Subsequent owned Applications-directory discovery qualification found the Mac app but its native app grant was denied. OH Mac completion is therefore useful capability evidence, not a fair speed comparison.

Native mixed has two valid completions; the third reached the correct fixture state but attempted a forbidden local skill read. OH VNC’s lower token count accompanied 0/3 completion because off-screen typing was unavailable. Neither is a cost win.

## Reviewed candidate at `a156b17`

| OH task | Baseline completion | Candidate completion | Baseline median attempt wall | Candidate median attempt wall | Candidate median total tokens |
|---|---:|---:|---:|---:|---:|
| iOS | 0/3 | 3/3 | 240.0s | 214.5s | 770,176 |
| Android | 0/3 | 0/3 | 86.7s | 240.0s | unavailable for two timeouts |
| Web | 0/3 | 0/3 | 240.0s | 240.0s | unavailable for two timeouts |
| Terminal | 3/3 | 3/3 | 80.9s | 86.7s | 244,079 |
| Mixed | 0/3 | 0/3 | 240.0s | 100.7s | 274,897 |

Terminal cumulative tokens fell from median 370,875 to 244,079 (34.2%), but wall time did not improve and billed cost is not established. iOS completion improved; baseline usage is unavailable. Android exposed missing false switch state. Two web trials stalled on typed-echo expectations; the third and all mixed web portions failed to create the agent display. Mixed’s shorter partial attempts are not speed wins. Native comparisons remain qualified by grants, discovery and protocol compliance as described below.

Sanitized [candidate rows](../experiments/codex-mixed/post-reviewed-remaining-2026-10-02.jsonl), [call audit](../experiments/codex-mixed/post-reviewed-remaining-audit-2026-10-02.jsonl), and [iOS rows](../experiments/codex-mixed/post-reviewed-ios-2026-10-02.jsonl) preserve failures. Subsequent Android raw-state and explicit field-value drafts were manually/offline qualified only, with no fresh-agent performance claim. They are retained on the full-runtime archive branch.

## Product decision

Native tools are the default. No OH route from this experiment earns automatic preference. Mobile and isolated off-screen capabilities remain explicit opt-ins. Terminal, VNC, generic user-app automation and specialist-model orchestration are removed from the active MCP surface; the full implementation and follow-up drafts are recoverable on the archive branch. Shared binding internals required by the opt-ins remain in source. No further broad bakeoff is planned.

## What was measured

| Task | Required result | Independent evidence |
|---|---|---|
| Terminal | Select Birch, quantity 3, review, confirm, read receipt | Exact TUI event sequence and `BIRCH-3-OK` receipt |
| Web | Complete six fields/options and submit | Exact server-side submitted values, once |
| VNC | Fill a Tk form, include manifest, review and confirm | Xvfb/x11vnc/noVNC application events, not a simulated canvas oracle |
| Android | Enable Dark theme, then read About phone | Device appearance, reported version and fresh About-screen observation |
| iOS | Enable Dark appearance, then read General → About | Simulator appearance, reported version and fresh About-screen observation |
| Native Mac | Fill the AppKit form, include manifest, review and confirm | Exact native application events |
| Mixed | Complete the TUI and submit its displayed receipt through the web form | Both TUI events and exact web submission in one conversation |

Native UI runs use the actual installed OpenAI MCP plugin, not a local recreation of its API. OH routes to Cua Driver 0.31.0, terminal-use 1.4.1 and mobile-mcp 1.0.6. Native Android/iOS runs drive their GUI emulator/simulator windows; OH uses the dedicated mobile driver. VNC is reached through noVNC in a browser by both arms. This evaluates the available stacks, not a controlled comparison of two selectors over identical low-level actions.

## Reading the measurements

- Wall time includes agent startup, tool work and final response. Fixture reset and independent scoring are outside that interval. Each run has a 240-second limit. A failed task’s shorter wall time is not a speed advantage.
- Tokens come from the CLI’s cumulative usage event. Cached input is a subset of input; reasoning output is a subset of output. Total tokens are input plus output. They include repeated conversation context across model requests, not just the unique task text. Dollar billing is not inferred.
- If termination prevents a usage event, usage is unavailable, never zero. Medians over available usage rows are labeled with their denominator; they cannot establish a total-cost win when failures have missing usage.
- The CLI aggregates interactive terminal writes into command records. Native terminal/mixed tool-call totals are unavailable. MCP calls and command-item counts in the metrics are diagnostics, not comparable model-turn totals.
- Correct fixture state and protocol compliance are checked separately. Reading an oracle, fixture source, local files through the REPL, using another driver or executing extra shell commands invalidates a run even if its final state is right. Raw inventory-bearing traces stay local; sanitized rows retain their SHA-256 hashes.
- The persisted `no-action` label means no scored fixture event. It can include a filled but unsubmitted web form or TUI navigation before confirmation. The report does not call that zero UI activity.

## Limits and preparation

These are small, synthetic, development-visible tasks on one Mac, not a held-out accuracy estimate. The web form was reused from the earlier experiment. Caches, model service latency and the desktop/browser environment vary across repetitions. The native browser prompt selects Chrome; other browser providers are outside this run. Locked-screen results do not establish what either stack can do in an unlocked foreground session.

Device creation, boot, driver installation, VNC image build, AppKit compilation and native tool preflight are not in per-task timing. The dedicated iOS simulator’s first boot alone took about eight minutes. Per-cell reset time is recorded separately. Only test resources were created or reset; existing user device sessions were not benchmark targets.

An initial native terminal pilot failed because the CLI’s default read-only sandbox prevented the fixture from writing its receipt. That pilot is excluded as harness interference and retained separately. All primary cells use `workspace-write` in a disposable task directory with the same approval setting for both arms. The following OH pilot was interrupted during the correction. Runtime failures in the primary batch are retained; there are no silent task retries or in-batch runtime fixes.

The first workspace-write batch also inherited global `AGENTS.md` guidance: `--ignore-rules` only disables exec-policy rules. It was stopped after 14 complete rows and retained in the [preliminary archive](../experiments/codex-mixed/preliminary-with-host-guidance-2026-10-02.jsonl). The replacement primary batch uses `project_doc_max_bytes=0` in both arms. A live canary confirmed that injected project instructions were absent with that setting. The canary establishes project-document exclusion only; global user guidance remains. A native mixed primary run attempted a missing skill read and is scored protocol-violation despite correct fixture state. Both arms retain the same global setup. These are measurements in the user’s configured Codex environment, not a pristine tool-only comparison.

# Earlier experiment: nine everyday jobs with Claude

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
