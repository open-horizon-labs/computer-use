# Preregistration: is the stack stronger than native?

Status: committed BEFORE any suite result exists. Written 2026-09-28. Any change to
this file after the first suite run must be a new commit that names the change and
the reason, and results gathered before the change are re-judged under the rules
that were in force when they were gathered.

## Why this exists

About 20 live A/B runs (native Cua Driver MCP tools vs the `cua-task` facade) on
three synthetic tasks were all correct in both arms with no wrong click. That data
cannot say whether the stack is stronger than native. It says only that the stack
cost more LLM turns (tools were 13% of run time; LLM turns, about 2.9 s each, were
87%). This suite exists to turn "is the stack stronger" into a number, and these
rules exist so nobody can rationalize the number afterwards.

## Design

- Arms: `native` (stock `cua-driver mcp`, no Skill), `stack` (facade server as
  configured in the checkout, default tool surface), `stack-advanced` (same, with
  `CUA_TASK_ADVANCED=1`). Optional `native-skill` (native plus the stock skill) is
  the baseline the invalidation condition names; see "Invalidation".
- Models (drivers): `claude-haiku-4-5-20251001` (cheap driver, primary),
  `claude-sonnet-5-5` (default), `claude-opus-5-5`.
- Tasks: `tasks.json`, at least 12 tasks, with category tags. Ground truth is only
  the fixture server's event log, never the model's report.
- Runs: at least 3 per (arm, model, task) cell. Arm order within a block and block
  order are shuffled with a fixed seed recorded in the manifest.
- A "run" is valid unless it is an infrastructure failure: nonzero return code, no
  MCP tool call and no event. Invalid runs are excluded from aggregates, listed in
  the report, and rerun once. Every other run counts, including timeouts.

## Metrics

Per run: outcome (correct | wrong | no-action | timeout | partial), wrong_clicks
(count of forbidden events), turns, LLM-visible MCP tool calls, wall seconds,
input/output/cache-read/cache-write tokens, cost (USD), model, arm, task, seed.

Outcome rules: any forbidden event makes the outcome `wrong`. Otherwise all expected
events in order is `correct`; some but not all is `partial`; none is `timeout` if the
agent timed out, else `no-action`.

Primary metrics, computed per (arm, model): success rate (correct / valid runs),
wrong-click rate (runs with at least one forbidden event / valid runs), turns, wall
seconds, cost, cost-per-success (total cost / number of correct runs).

## Noise band

The noise band is the amount a metric may move without counting as a difference.

- Continuous metrics (turns, wall, cost, cost-per-success): for each task compute the
  ratio of medians r = stack / native. The suite summary G is the geometric mean of
  r across tasks with data in both arms (cost-per-success uses the single pooled
  ratio of total cost / total successes instead). The band b is the median across
  tasks of (native IQR / native median), clamped to [0.10, 0.50], when every task
  cell has at least 3 native runs. With fewer, b = 0.25.
- Rate metrics (success rate, wrong-click rate): pooled over the suite, the band is
  an absolute 0.10.

A stack "beats" native on a continuous metric when G < 1 - b, and is "worse" when
G > 1 + b. On a rate metric it beats when the success rate is higher by at least 0.10
(or the wrong-click rate is lower by at least 0.10), and is worse when the difference
is at least 0.10 the other way. Otherwise the metric is a tie.

## Decision rules

1. Minimum data. No verdict is issued unless at least 12 tasks each have at least 3
   valid runs in every compared arm for the model in question. Otherwise the verdict
   is `insufficient-data` and none of the rules below fire.
2. STACK STRONGER. The stack (either `stack` or `stack-advanced`, judged separately)
   is stronger than native, with the Haiku driver, if it beats native on at least one
   of turns, wall, cost, success rate, wrong-click rate, or cost-per-success, and is
   worse on none by more than the noise band. The claim is labelled `established`
   only if the Wilson 95% intervals of at least one beating rate metric do not
   overlap; otherwise it is labelled `directional`. Results for the other models are
   reported the same way but do not decide the claim.
3. INVALIDATION. The claim that the stack helps is invalidated if native plus the
   stock skill matches or beats the stack on every metric across the suite, including
   hard-surface and cheap-driver tasks. Mechanically: there is no metric on which the
   stack beats the baseline, computed separately over (a) all tasks, (b) the
   hard-surface subset (tasks tagged `canvas`), and (c) all tasks with the Haiku
   driver. Until a `native-skill` arm has been run, invalidation is provisional and
   evaluated against `native`, and the report says so.
4. STOP / PIVOT TRIGGERS.
   - No advantage anywhere: the stack beats native on no metric in any of: all tasks
     per model, the hard-surface subset, or any category table. Action: salvage to the
     thin layer plus Perception, and stop investing in the mediated tool surface.
   - Large cheap-driver lift: with the Haiku driver the stack's success rate is at
     least 0.20 higher than native's, or its cost-per-success is at least 30% lower,
     while it is not worse on success rate by more than the band. Action: pursue the
     server-side agent (D), where the cheap driver does more of the work.
   - Anything else: mixed result. Report per-category deltas and decide on the
     evidence, but do not describe it as a win.

## Exploratory arm (not part of any decision rule)

`stack-agent` runs the experimental server-side agent (option D, `cua_agent`; only that tool is allowed, so the driving LLM cannot fall back to `cua_do`). It is reported descriptively next to the other arms, added after the rules above were written, and **it never decides the preregistered claim, the invalidation condition or the stop/pivot triggers** (`metrics.verdict` excludes it by default). Whether D deserves its own preregistered question depends on what this first look shows and is a separate decision.

## Caveats (always reported with any number)

- The tasks are synthetic and the fixtures are our own; the stack was tuned against
  the first three of them, so those are not held-out.
- n is small. With 3 runs per cell a single run moves a rate by 0.33. Wilson intervals
  are wide and will usually overlap; the decision rules use point differences with a
  band, so "directional" is the honest label for most outcomes.
- Cost and latency include hosted specialist latency (Jev, NuExtract, GLiNER2) that
  can vary by day and load, and the LLM turn time dominates run time.
- Model behavior drifts; a rerun on another day is a different sample.
- Ground truth is the server-side event log. A run that reaches the right state by a
  path the log cannot see is counted by the log alone.
- This preregistration does not cover real-world sites, non-browser apps, or tasks
  longer than the per-task turn limit.
