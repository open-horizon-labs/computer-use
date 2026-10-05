# Cua cursor ablation, 2026-10-05

Disabling Cua Driver's named session cursor did not recover the form-loop speed gap. A cursor-animation optimization is not supported by these measurements; no upstream animation PR was created.

| Task | Cua cursor enabled | Cua cursor disabled | Arc | Independent passes |
|---|---:|---:|---:|---:|
| Native AppKit form | 9.773 s | 9.943 s | 1.242 s | 9/9 |
| WebKit renderer form and custom dropdown | 11.115 s | 11.151 s | 1.455 s | 9/9 |

These are median sums of public MCP tool-call durations across three repetitions per mode. Orders alternate enabled/disabled/Arc and Arc/disabled/enabled. AppKit completion comes from fixture-owned JSON state; WebKit completion comes from the renderer's submitted record and input event log. Every action uses an observed exact token, with fresh observation before subsequent actions. No raw coordinates or inferred success from transport acknowledgements are used.

Each task had its own named Cua session. The public set_agent_cursor_enabled tool acknowledged the requested enabled/disabled state before every trial; all native calls that expose a session argument used that label. A separate verification session's get_agent_cursor_state returned enabled=false after disabling. The final setting was restored to enabled=true, and closing the MCP client ended only its owned session. The existing signed daemon remained running. No daemon replacement, virtual displays, user documents, screenshots or private menu trees were involved.

Both candidates passed the comparison harness's fresh upstream preflight: latest published stable Cua Driver 0.33.4, release commit ba0033a661101669c60ce05f1fe5753bf8bad748; Arc 0.1.1, current master 6ca19d62c95106732fad28f488ecd458c08e02f4. MCP initialization independently confirmed running server versions. Exact check timestamps and server provenance are in each result JSON. Cua main had advanced to b0968e1 (0.34.0 release preparation), but the uncached upstream release check still reported 0.33.4 as the latest published stable release; these timings measure that release, not unreleased main.

The disabled condition was 1.7% slower for AppKit and 0.3% slower for WebKit; with only three repetitions, these small differences are not treated as meaningful. The result rejects cursor disabling as a useful gain for this configuration. It does not prove animation is free in every configuration: rendered cursor pixels and arrival timing were not instrumented. In particular, the public registry state does not establish whether an animation actually ran in the enabled condition.

Source inspection finds another cost to profile: platform-macos WindowChangeDetector defaults to a 1000 ms post-action observation deadline. It holds a focus-suppression lease throughout that window. Shortening or removing it changes protection against delayed activation/window creation; it is not an equivalent safe optimization without additional evidence and regression coverage. No guard or settling policy was changed by this experiment. The remaining approximately 2.2–2.4 seconds per native form action has not yet been apportioned to individual internal stages.

Files: results.json (native), web-results.json (renderer), run.py and web.py (execution scripts). The scripts reuse the existing comparison harness at /tmp/computer-use-arc-review-20261005/experiments/arc-cua-comparison-2026-10-05 and require ARC_EVAL_SOURCE to identify its clean current Arc checkout. Run with the existing /tmp/arc-cua-eval-venv/bin/python. The reusable scripts now generate fresh session labels and check get_agent_cursor_state before every trial; these additions passed syntax checks and are not retroactively presented as observations from the scored runs. ARC_COMPARISON_HARNESS can override the harness directory when the packet is moved. The daemon refuses reuse of ended session labels unless explicitly restarted with start_session.
