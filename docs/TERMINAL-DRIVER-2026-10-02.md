# Terminal driver qualification — 2026-10-02

The selected addition is **terminal-use (`tu`) 1.4.1 for explicitly launched agent-owned terminal apps**. It supplies a PTY and Alacritty-backed terminal emulator, so the facade can read the rendered grid, cursor and styles directly. It does not need a display, AX, OCR or a vision model for these reads. Existing GUI terminal windows remain Cua Driver targets. The implementation is optional behind the same two MCP tools, `look` and `do`.

## Decision and execution criteria

Aim: agents can operate interactive terminal apps with current rendered evidence, exact session binding, bounded delivery and separate verification, while avoiding unnecessary screenshots/model calls. Success means an actual TUI launch/read/input/verify/close through MCP, no changes to the default browser/mobile call budget, no foreground operation, literal argv/cwd, and tests that reject cross-task/stale evidence, false success and input replay.

The accepted trade-off is ownership: this driver launches new PTYs; it cannot attach arbitrary existing GUI sessions. Existing-session support would require an app-specific API or a multiplexer the user already runs. The default remains non-OBO. A headless PTY cannot satisfy an OBO context's user-window presentation; that context retains the Driver route.

Alternatives considered:

| Candidate | Fit | Decision |
|---|---|---|
| terminal-use 1.4.1 | Named headless PTYs; rendered text/cells/cursor/PNG; literal executable/argv and explicit cwd; no screen dependency | Implemented and live-tested on this Mac. Private daemon/socket per facade context. |
| tmux | `capture-pane`, `send-keys`, stable pane IDs and control mode for programs running inside tmux | Strong candidate for a later adapter when attaching an existing tmux pane is the actual need. Not installed or benchmarked here. Does not attach an arbitrary GUI terminal's existing PTY. |
| iTerm2 Python API | Reads an iTerm session's screen and sends text, with transaction guidance for consistency | Useful for existing iTerm2 sessions. App-specific; iTerm2 is not the installed Ghostty app. Not live-tested here. |
| Termwright | Headless PTY automation with rendered text/cells and PNG | Relevant alternative; inspected its official documentation, not live-tested. No measured superiority claim for either implementation. |

Dissent: terminal-use is not automatically the best answer when the user means an already-running terminal tab. Treating a new empty shell as that tab would lose its process, environment and interaction state. Explicit `terminal="new"` is the boundary; no transparent rerouting from a GUI target. The first invalidation check was a real TUI: if rendered state or key delivery failed, we would stop the adapter and retain the Driver path. Menu and Vim probes passed. Incomplete/stale identity, uncertain delivery and unmet postconditions stop the affected plan without replay.

## Accuracy report

| Claim | Status | Evidence | Wording / limits |
|---|---|---|---|
| terminal-use offers headless named PTYs, key/text input, rendered grid/cursor and PNG | Verified | [Official repository](https://github.com/flipbit03/terminal-use), pinned [1.4.1 source](https://github.com/flipbit03/terminal-use/tree/v1.4.1), local live probe below | Agent-owned sessions only; not arbitrary GUI attachment. |
| Its emulator uses Alacritty and processes terminal state rather than stripping raw stdout | Verified | [Pinned Cargo manifest](https://github.com/flipbit03/terminal-use/blob/v1.4.1/Cargo.toml) and [session implementation](https://github.com/flipbit03/terminal-use/blob/v1.4.1/src/daemon/session.rs) | Local fixture exercises alternate screen, cursor addressing, erasure and style-only selection. Not all terminal protocols qualified. |
| A private `XDG_RUNTIME_DIR` isolates its socket | Verified | [Pinned daemon source](https://github.com/flipbit03/terminal-use/blob/v1.4.1/src/daemon/server.rs), two-daemon live check | Child-process environment only. This is session isolation, not a security sandbox. |
| Upstream checks and writes are atomic | Incorrect | [Protocol](https://github.com/flipbit03/terminal-use/blob/v1.4.1/src/daemon/protocol.rs) has separate Status, ScreenshotCells, Cursor, Press and Type requests | Adapter checks before delivery and reads afterward; it cannot eliminate the intervening race. |
| tmux can read and send input to its panes | Verified | [Official 3.7c manual](https://github.com/tmux/tmux/blob/3.7c/tmux.1), capture-pane/send-keys/control-mode sections | Existing tmux panes; no local latency comparison. |
| iTerm2 has session screen reading and text delivery APIs | Verified | [Official Session API](https://iterm2.com/python-api/session.html) | App-specific; local Ghostty state is not an iTerm session. |
| Termwright supplies PTY text/cell/PNG automation | Verified from documentation | [Official repository](https://github.com/fcoury/termwright) | Not exercised here. |
| terminal-use is generally faster or more reliable than native computer use, tmux or iTerm2 | Unsupported | No matched agent bakeoff was run | Do not claim this. These local tool timings exclude LLM reasoning and general task accuracy. |

No unresolved high-risk publication claims or required domain-expert rulings remain for this narrow addition. Source gaps remain for arbitrary TUI compatibility, existing-GUI attachment, downstream multiprocess cleanup behavior, and comparative agent cost/accuracy. Existing OBO live tests were skipped as requested. No screenshots were sent to a model. The earlier terminal documentation's “standard multimodal chat” wording was corrected to describe the configured finite SystemOne screenshot endpoint.

The installed ARM macOS binary comes from release v1.4.1, source commit `05d6a5346f7e1324000be0c5b14dd586add79547`; SHA-256 `851b1f6f54fba5f82008279632d88b75d9ef27368dc6f1aa3261a82b1b17f75d`. The installer pins release-API digests for that asset and Linux x86_64/aarch64. It downloads no code during a tool call. The adapter checks `tu 1.4.1` at first launch because its private protocol is version-specific.

## Live evidence

Reproduce with `.venv-facade/bin/python experiments/terminal-driver/probe.py`. This is an opt-in live test, not part of offline CI. It starts owned terminal processes; it never operates the GUI or starts model/GPU jobs. [Full results](../experiments/terminal-driver/live-results.json) contain tool latencies and response sizes, not arbitrary terminal content or credentials. [Captured grid fixture](../computer_use/fixtures/terminal_menu.json) came from the real terminal-use driver, with PID/name replaced by fixture identities.

Five real MCP stdio menu trials all accepted **Beta**, independently verified from each fixture's result file. The recorded inputs were one Down (`1b4f42`) and one Enter (`0d`). A shell-looking argument arrived unchanged as literal argv. The selection changed only in styling, so plain text alone could not identify it. Five tool calls per trial cover launch, look, Down, look, Enter; the follow-up close and optional PNG are measured separately. Across these five tiny trials, summed tool wall time ranged from **118.78 to 131.50 ms**. Across all recorded MCP calls, median latency was **1.79 ms**, maximum **115.78 ms**. These are local synthetic tool measurements; they exclude model thinking, MCP initialization and a matched native baseline.

A PNG was returned as an MCP image block. A real Vim session entered insert mode, received literal text, left insert mode and saved; the separate file contained exactly the requested line. All six MCP sessions were closed and the task's empty inventory was observed. Two further real private daemons were launched; closing the first left the second Vim alive, then the second was closed. No OBO window was activated.

One initial Vim probe expected `[New File]`; the installed Vim displayed `[New]`, and the adapter correctly returned unverified. The probe was corrected to the observed wording. That was a test assumption error, not evidence that input failed or a reason to weaken verification.

## Risk retirement and review

| Risk / tempting wrong patch | Status | Check / boundary |
|---|---|---|
| Strip stdout and miss overwritten cells or selected styles | Retired for tested shapes | Real alternate-screen menu and captured ScreenshotCells fixture; style-only mutation rejected. General terminal-protocol coverage remains unqualified. |
| Accept another task's handle, terminal name or replacement PID | Retired | Cross-context/PID/handle tests; real two-daemon lifecycle check. |
| Send input after text, style or cursor changed | Retired for observable changes | Fresh fingerprint tests and mutations. Atomicity accepted with rationale: upstream has no compare-and-send primitive. |
| Expand caller argv through a shell | Retired | Unit assertion, shell-expansion mutant, live literal-argv ground truth. |
| Treat Enter acknowledgement, old READY text, delayed echo or silence as completion | Retired for explicit literal contract | Adversarial tests, old-text/echo mutations, post-action-read mutation, and independently saved Vim/menu files. Echo memory is bounded to 8192 typed characters; semantic task verification remains the caller's responsibility. |
| Validate only the first step and send before discovering malformed later input | Retired | Whole-plan rejection tests with zero writes. |
| Retry a timed-out key or silently replace a lost daemon | Retired for input | One-attempt uncertain-delivery test and dead-daemon no-respawn check. Optional PNG CLI may try to auto-start on daemon loss; its process group is reaped and capture is rejected if the original daemon died. |
| Kill another task during cleanup | Retired for directly owned sessions | Real separate-daemon test, close/inventory unit test; daemon child/grandchild process trees beyond Vim/menu are not qualified. |
| Add mandatory tools/model calls to ordinary browser/mobile tasks | Retired | Default two-tool call and response-budget gates; no provider/GUI call in terminal unit tests. |
| Claim one local probe proves universal speed, cost or reliability | Accepted with explicit limit | No such claim; no paired agent bakeoff. Further app qualification is needed before extending the measured claims. |

Review decision: **continue**. Aim and scope remain aligned. This adds a bounded explicit PTY path and preserves the existing GUI path. Deterministic checks validate implementation boundaries; they do not establish model accuracy or all-TUI reliability. Human verification is still appropriate for any specific user application and for the read/send race in time-sensitive interactions; neither is claimed qualified here.

Offline validation passed: 1,276 facade tests, 26 dispatcher tests, 15 decider tests, 25 script tests and 52 experiment tests; simulation gate; MCP protocol smoke; skill snapshot sync; call/response budgets; look comparison; all 200 mutation checks. The old-text mutant initially escaped a test that removed READY after input; preserving READY made the tempting wrong patch fail, and the final full gate passed. No default CALL_BUDGET or RESPONSE_BUDGET ceiling changed. CE-FACADE-015 and sketch S4.5.1 preserve the driver boundary and evidence limits.
