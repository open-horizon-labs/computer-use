> Historical full-facade material. The active MCP is native-first with explicit mobile/off-screen capabilities only. Reproduce the broad benchmark using archive commit a531b43; these historical recipes are not active routing instructions.

# Actual Codex mixed-driver benchmark

This harness runs the installed Codex CLI against OpenAI’s bundled `cua_repl` or this checkout’s `computer-use-oh` MCP. Native terminal work uses Codex’s own PTY command/input tools. It does not emulate the native computer-use API or substitute Cua Driver for it.

Read [PLAN.md](PLAN.md) for the protocol, [docs/BENCHMARK.md](../../docs/BENCHMARK.md) for results, and `results-2026-10-02.jsonl` for sanitized measurements. The fixtures are synthetic and development-visible; this is an exploratory integration benchmark, not a held-out model evaluation.

## Fixtures and setup

Use disposable resources. Do not point the mobile arguments at a person’s working device. Each mobile run changes appearance and force-stops Settings to reset navigation. The UI agent never sees the scoring endpoints or result files; direct access to them invalidates a run.

- **Web:** run `experiments/surfaces-ab/server.py --port 8984 --events <local-event-file>`. Each run receives its own `run` query value. Server events prove the submitted fields; opening or filling the page alone does not pass.
- **Terminal:** `tui.py` runs on a real PTY. The agent must select Birch, enter 3, review and confirm. Its file records the exact sequence and receipt only at confirmation. A missing file does not prove the agent took no intermediate actions.
- **VNC:** build `Dockerfile` in this directory and run the image with `-p 127.0.0.1:8985:6080 -p 127.0.0.1:8986:9101`. This is a real Tk app on Xvfb, served by x11vnc and noVNC. The second port is harness-only reset/scoring. Both ports are loopback-only on the host.
- **Android:** create a dedicated AVD from an installed system image and start its GUI on a virtual display, with its own serial/port. OH can also use a headless emulator, but both arms get the same live device in this comparison. Pass the AVD name and serial explicitly on another host.
- **iOS:** create and boot a dedicated iPhone simulator. Install the mobilecli agent for that UDID. Open that exact simulator in Device Hub/Simulator on a virtual display for native Codex. Selecting it in the frontend and resetting Settings are setup, outside agent timing.
- **Mac:** compile `mac_fixture.swift` into a local app bundle named `OH Benchmark.app`, executable `OHBenchmark`, bundle ID `org.openhorizon.benchmark.dispatch`, `LSUIElement=false`. Place it at `/tmp/cua-mixed-bench/OH Benchmark.app` and run `mac_supervisor.py`. The supervisor owns a virtual display, launches the fixture and serves reset/scoring at loopback port 8987. It never kills another app. Native app discovery may require an owned Applications-directory symlink; qualify discovery and the native app grant before comparing performance. An inventory miss or denied grant is a setup block, not a completed-task speed result.
- **Mixed:** the same TUI and web form in one fresh conversation; the submitted web message must be the receipt read from the TUI. Both independent oracles must pass.

The October 2 run used Android 15 (`OHMixedBenchmark20261002`, serial `emulator-5570`) and iOS 26.5 (`OH Mixed Benchmark`). Device creation/boot, installs, image compilation and native tool preflight are excluded from task wall time. The iOS first boot took about eight minutes. Preparation is a real adoption cost even though it is not a per-task agent cost.

Run from the repository with its facade Python environment:

```sh
.venv-facade/bin/python experiments/codex-mixed/runner.py \
  --tasks terminal web vnc android ios mac mixed --reps 3 \
  --ios-device <dedicated-UDID> \
  --android-avd <dedicated-AVD-name> --android-serial <dedicated-serial> \
  --native-manifest <installed-unified-computer-use/.mcp.json> \
  --out /tmp/cua-mixed-bench/primary
```

Run agents serially. Every cell gets a fresh Codex process, disposable working directory and the same sandbox/model/reasoning settings. Arm order alternates per repetition. Defaults in `runner.py` record this machine’s experimental targets, so supply the flags elsewhere. Browser prompts select Chrome; this does not compare every native browser provider. Keep the runtime and fixtures fixed for a scored batch. A fix belongs in a separately labeled qualification run.

## Measurements and audit

Agent wall time includes Codex startup and final response, excludes fixture setup and independent scoring, and has a 240-second limit. `setup_s` reports per-cell reset time. Token usage is the CLI’s cumulative `turn.completed.usage`: input, cached-input subset, uncached input, output and reasoning-output subset. Total is input plus output, never input plus cache plus output. A terminated run may have no usage event; missing tokens stay null. No dollar cost is inferred. The summary table reports all-attempt diagnostic medians, including failures and protocol-invalid attempts; valid completions must be separated before making a completed-task speed or token comparison.

MCP calls are observable in the JSON trace. PTY writes are aggregated into command items, so native terminal/mixed tool-call totals are unavailable. `observed_tool_items` and `command_items` are diagnostic counts, not model turns. The harness rejects tools from the wrong arm, non-fixture shell commands and altered OH launch argv. Manual trace review must additionally check browser evaluate use and target scope; the automated audit cannot prove every possible command’s semantics.

The `no-action` oracle label means no scored fixture event was persisted. For web that can include a filled but unsubmitted form. For terminal it can include intermediate navigation before confirmation. Report failures in context rather than claiming those rows had zero UI interaction.

Export only the controlled metrics:

```sh
.venv-facade/bin/python experiments/codex-mixed/summarize.py \
  --source /tmp/cua-mixed-bench/primary \
  --output experiments/codex-mixed/results-2026-10-02.jsonl
.venv-facade/bin/python -m unittest discover -s experiments/codex-mixed -p 'test_*.py'
```

Automatic host skill discovery and project documents are disabled, but global user AGENTS guidance remains. See PLAN.md for the canary boundary and protocol-invalid native mixed run. Raw traces can contain unrelated app/browser inventory and remain local. The export replaces local repository/workspace paths, retains raw SHA-256 hashes and never embeds raw MCP responses. Preserve launch failures/pilots separately. Close test browser tabs and clean up only the specific container, emulator, simulator, fixture processes and displays created for the experiment; never stop all simulators, emulators or browser processes.
