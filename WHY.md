# Why use this?

Use this skill to choose a route that fits the user's intent without loading a large tool catalog or building another general driver stack.

For work in the user's apps and logins, use native OBO tools: prefer arc-cua for macOS app/window interaction when connected. The [local live comparison](docs/ARC-CUA-EMPIRICAL-COMPARISON-2026-10-05.md) measured faster native and WebKit form loops and stronger changed-control/immediate-sheet refusals, while a delayed-sheet trial exposed an Arc submission race against current Cua Driver 0.33.4; the user selected arc as the default. It still needs controller-side record matching and independent verification, and does not establish virtual-display safety or universal superiority. For small isolated browser tasks, use lightweight isolation. Use Spaces when a separate desktop is useful, with three discovery/execution tools and schemas fetched by name. Mobile support remains optional. Keep fresh bindings and independently verify results on every route.

The value is routing and operational guidance, not a claim that OH beats native. Our bakeoff did not establish an automatic OH winner. The retained adapters cover capability gaps; they are disabled/unregistered by default. The slim Spaces test passed a five-action form, but has not established lower total agent tokens or better general reliability.

Keep [benchmark evidence](docs/BENCHMARK.md) and [Spaces qualification](docs/SPACES-PROGRESSIVE-2026-10-02.md). Recover broader experiments from codex/archive-general-facade-2026-10-02 (a531b43) only when a concrete gap warrants it. Promotion requires a fair same-task comparison with better completion or efficiency without lowering completion.
