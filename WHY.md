# Why use computer-use

computer-use gives an agent one interface for work that crosses browsers, native apps, phones and terminal programs. `look` returns current evidence; `do` binds a plan to that evidence, executes it through a driver and checks the result. Use it when that common contract and its checks help your task. It does not make every task faster or cheaper.

The [benchmark](docs/BENCHMARK.md) compares actual execution, wall time and reported tokens. Keep the experiments separate: the October 1 Claude comparison used a locally implemented screenshot tool as one baseline; the October 2 Codex comparison uses OpenAI’s installed `cua_repl` and native terminal tools. Neither experiment establishes a general reliability rate.

## One contract across drivers

| Surface | Execution route | What the common interface adds |
|---|---|---|
| Web | Cua Driver with current AX/DOM evidence | Exact control binding, record filters, batched plans and checked postconditions |
| Native Mac app | Cua Driver | Fresh window resolution, bound controls and checked results |
| Android and iOS | mobile-mcp | Device identity, fresh elements before input and separate verification |
| Agent-owned terminal TUI | terminal-use | Rendered text, styles and cursor; exact session binding; input and result checks |
| VNC through noVNC | Browser and canvas/perception route | The same targeting and verification rules, subject to canvas input limits |

A route being implemented does not mean it can finish a task in every environment. The live benchmark records failures and unavailable capabilities alongside completions. Existing GUI terminal tabs stay on the native-app route; the PTY driver creates task-owned sessions and does not attach to arbitrary running user terminals.

The default tool surface is just `look` and `do`. A plan can contain several steps, avoiding a separate model decision for each mechanical action. Before each action the server refreshes state, resolves its target and retains the actual driver arguments. Afterward it checks the declared `expect`. A delivered action whose result was not proved is reported as unverified; it is not blindly replayed.

That design has a cost. Bad or invented expectations can consume verification waits and force another model turn. Ambiguous controls can stop a whole plan. A compact observation is useful only if it preserves the distinctions needed to act. The benchmark’s failures are work to fix, not evidence that a refusal is a successful task.

## Choose whose session the agent uses

With no context argument, the facade defaults to an isolated agent session. Its browser is Chrome for Testing with a separate profile, placed on a virtual display. It has no inherited user logins. Supported background routes let the person keep using their apps.

For delegated work in the user’s apps and logins, pass `context={"session":"user"}` to `look` or `do`. Visible presentation is the default for that context and includes routine foreground delivery for the delegated task. Add `"presentation":"background"` when the user wants their Space preserved. Reuse the returned `context_id` or `look_id`; this is an MCP request choice, with no environment switch or server restart.

A routine recovery belongs to the agent. A missing OS permission or an unavailable session may still need the user. The facade returns a typed reason and recovery guidance; it should not turn every recoverable failure into an approval question. A background request does not authorize moving the user into another Space. A locked-screen test also does not qualify visible OBO behavior.

## Read what the task needs

Plain text `look` uses the available accessibility tree, browser DOM, device elements or terminal renderer without an extraction-model call. `look(screen=True, ...)` returns pixels from the bound target when text evidence misses drawn content. The controlling agent can inspect those pixels; requesting them does not itself create safe action coordinates or solve an unavailable capture.

For more structured work, the dispatcher can extract source-grounded fields and compare them on the same record. Qualified short English field requests use GLiNER2 with a typed reducer; bounded semantic selection uses the configured Jev or Julia-1 route, with configured escalation. Optional NuExtract page extraction has a separate cost. Its current adapter reads text records; the model family’s image capability does not imply image extraction is integrated here.

The default fleet profile can send page content to configured hosted providers. `local-mac` is an explicit alternative with its own capability limits. See [provider profiles](docs/PROVIDERS.md).

## What to compare before adopting it

Completion comes first. Measure whether the intended item was changed, the submitted values were right and the result was independently visible. Then compare elapsed time and tokens for those outcomes. A quick refusal is not a faster completion, and a small output does not imply a small cumulative input bill.

The preliminary Codex runs exposed an unresolved OH dropdown problem ([#100](https://github.com/open-horizon-labs/computer-use/issues/100)) and intermittent native browser connection failures. Their timing comparison was contaminated by inherited host guidance and was rerun with verified project-document exclusion; global user guidance remained and is explicitly qualified. Read the [full results and limitations](docs/BENCHMARK.md) before treating the shared facade as a performance improvement.

Keep the native tools available where they work well. Choose OH for the common evidence/action contract, task isolation, structured matching or a useful specialist driver—and use measured outcomes to decide whether those benefits repay the extra machinery on your workload.
