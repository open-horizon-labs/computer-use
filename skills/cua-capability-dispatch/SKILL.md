---
name: cua-capability-dispatch
description: Supplement stock computer-use tools with typed evidence requests, specialist dispatch, grounded matching and Jev recovery. Use when selecting among current UI controls through this repository's dispatcher.
---

# CUA capability dispatch

Use the stock computer-use skill and driver for fresh observations and execution. This skill adds selection guidance, not an alternative driver or expanded action permission.

Read [setup](references/setup.md) first to locate or install the runtime and configure providers. Read [the bundled sketch](references/sketch.md) for request semantics and policy. These references travel with `npx skills` installs; do not assume the runtime repository is next to the installed skill. The runtime checkout’s sketch is authoritative when available.

## Build the request; code selects the route

Provide a current `snapshot_id`, desired `operation`, and offered `actions` with opaque IDs, roles, enabled state, scoped evidence text and stored driver arguments. Do not pass expected answers from a fixture.

Choose a semantic request kind from the sketch:

- Exact unique control: `exact`; no model needed.
- Field matching: `match`; supply field types/descriptions, candidate IDs, coverage, predicates and any explicit ordering. Simple labels route to GLiNER; described spans to GLiNER2; structured/relational/multilingual requests to qualified GLiNER2.5 adapters.
- Described bounded categories mapped to actions: `classify`; Decide.
- Contextual choice: `semantic` or default; Jev, with configured Qwen escalation.

These are dispatcher rules, not a learned router. Check adapter availability: several specialist roles are still provisional. An unavailable specialist may recover through Jev under the sketch; never report an uncalled specialist as measured.

For extraction, describe each field's meaning. Keep desired values in caller predicates and ordering. Do not ask NER to rank entire actions against a goal. The matcher applies constraints to one record at a time. The LLM owns intent interpretation; the code must not contain task-specific answers.

## Select, bind, verify

Call `Strangler.from_config` with the configured providers, then `decide` with the typed request and current snapshot. The active config sends only `described-span-match/en` to the qualified GLiNER2 extractor and typed matcher. Exact-control and successful specialist paths need no generic call. Missing evidence or approved boundary uncertainty can invoke Jev once while preserving known exclusions. Overlapping text does not itself establish equality. Ties or missing scope do not grant new permission.

Before execution, validate a fresh snapshot and the unchanged request with `execute_bound`. Keep model outputs separate from tool arguments. `reobserve` and `abstain` never execute. Independently observe the result before reporting success or retrying. Bound attempts and reconcile uncertain side effects.

Keep one installed selector process per ongoing task; independent tasks need independent state. Send truthful verification feedback using the selector guide at `inference/cua-decider/README.md#reusable-bounded-selector` in the runtime checkout. Credentials are runtime provider configuration, never observation data or logs.

## Improve from failure

Retain input/output traces without secrets. Compare behavior against the sketch: repair projection defects under existing policy; propose genuinely new rules separately for user approval. Preserve accepted CEs and a curated regression rejecting the tempting wrong repair. Run the offline gate and separately review active/regression traces against the sketch. Green finite tests do not establish general computer-use correctness. See `docs/SALVAGE.md` in the runtime checkout.
