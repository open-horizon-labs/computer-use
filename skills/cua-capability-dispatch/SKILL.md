---
name: cua-capability-dispatch
description: Supplement stock computer-use tools with typed evidence requests, specialist dispatch, grounded matching and Jev recovery. Use when selecting among current UI controls through this repository's dispatcher.
---

# CUA capability dispatch

Use the stock computer-use skill and driver for fresh observations and execution. This skill adds selection guidance, not an alternative driver or expanded action permission.

Read [setup](references/setup.md) first to locate or install the runtime and configure providers. Read [the bundled sketch](references/sketch.md) for request semantics and policy. These references travel with `npx skills` installs; do not assume the runtime repository is next to the installed skill. The runtime checkout’s sketch is authoritative when available.

## Active stack

Use **NuExtract3 for page reading/filtering → Julia-1 for contextual finite choice**, with the qualified GLiNER2 route for described spans and screenshot-capable SystemOne/Qwen for terminal perception. This is the user's selected default, not an opt-in trial. Create providers through `generic_from_config()`, never hardcode `FleetGeneric()` for the normal path. The factory and observation helpers automatically read `~/.config/computer-use/runtime.json`; explicit environment settings can override it. Preserve runtime credentials outside observations and source.

For record-backed reading or choice, supply caller-described extraction fields and explicit predicates in `page_filter`, retaining unknowns and original Driver IDs. Pure reads use NuExtract directly and need no Julia choice. For terminals, use `VisualTerminal` and the bounded observation helper with the configured SystemOne screenshot endpoint. Missing visual evidence remains unknown. Keep one worker per task and close it afterward; being the default does not require leaving GPU workers resident between tasks.

## Build the request; code selects the route

Provide a current `snapshot_id`, desired `operation`, and offered `actions` with opaque IDs, roles, enabled state, scoped evidence text and stored driver arguments. Do not pass expected answers from a fixture.

Choose a semantic request kind from the sketch:

- Exact unique control: `exact`; no model needed.
- Field matching: `match`; supply field types/descriptions, candidate IDs, coverage, predicates and any explicit ordering. Simple labels route to GLiNER; described spans to GLiNER2; structured/relational/multilingual requests to qualified GLiNER2.5 adapters.
- Described bounded categories mapped to actions: `classify`; Decide.
- Contextual choice: `semantic` or default; Julia-1 through the configured generic provider. Jev/Qwen remains an explicit alternative.

These are dispatcher rules, not a learned router. Check adapter availability: several specialist roles are still provisional. An unavailable specialist may recover through Jev under the sketch; never report an uncalled specialist as measured.

For extraction, describe each field's meaning. Keep desired values in caller predicates and ordering. Do not ask NER to rank entire actions against a goal. The matcher applies constraints to one record at a time. The LLM owns intent interpretation; the code must not contain task-specific answers.

For structured fields read from live page records, prefer the task-shaped SystemOne `/v1/extract-page` route backed by NuExtract3 when configured. Supply only records and IDs from a fresh Cua Driver snapshot, plus caller-requested fields and task. The endpoint sends page text and the field template to the extractor, then joins values to its retained record IDs and snapshot ID. The model must never choose or invent Cua click IDs, coordinates, or Driver arguments. Use GLiNER2 for described span matching, Julia-1 for contextual action choices, and no model for exact unique controls. Missing, conflicting, unavailable, or ungrounded page data is a blocker/defer; model scores are not calibrated confidence.

For large record-backed candidate sets, use `NuExtractPage`/`ExtractThenChoose` from `page_candidates.py` (runtime guide: `docs/PAGE-CANDIDATES.md`). `CUA_PAGE_EXTRACTION=1` enables the wrapper through `generic_from_config`; the caller must supply `page_filter` fields, predicates, record IDs and honest coverage. Chunk extraction, merge every record, then filter. Do not tournament-rank Julia chunks, drop unknown records, or infer a used condition from a search heading. Reports can read/filter without any chooser. Oversized surviving scopes defer or use an explicitly configured larger-capacity provider.

## Select, bind, verify

Call `Strangler.from_config` with the configured providers, then `decide` with the typed request and current snapshot. The active config sends only `described-span-match/en` to the qualified GLiNER2 extractor and typed matcher. Exact-control and successful specialist paths need no generic call. Missing evidence or approved boundary uncertainty can invoke the configured generic chooser once while preserving known exclusions. Overlapping text does not itself establish equality. Ties or missing scope do not grant new permission.

Before execution, validate a fresh snapshot and the unchanged request with `execute_bound`. Keep model outputs separate from tool arguments. `reobserve` and `abstain` never execute. Independently observe the result before reporting success or retrying. Bound attempts and reconcile uncertain side effects.

Keep one installed selector process per ongoing task; independent tasks need independent state. Send truthful verification feedback using the selector guide at `inference/cua-decider/README.md#reusable-bounded-selector` in the runtime checkout. Credentials are runtime provider configuration, never observation data or logs.

## Terminal surfaces and Julia

Lean on the configured models for their supported roles: NuExtract for structured reading, GLiNER2 for described spans, a generic chooser for contextual actions, and a screenshot-capable model for visual terminal evidence. Do not substitute AX polling for visual interpretation. Inspect the first fresh screenshot after launching a TUI: it may already be ready. An unchanged AX tree does not establish a stall, and changed pixels do not establish progress. Keep missing observations explicit.

Use the runtime's `terminal_observation.py` helper and `docs/TERMINALS.md` in the runtime checkout. It exposes observation quality, combines fresh AX and screenshot evidence, and bounds the whole wait to 20 seconds with time reserved for a final inspection. Missing visual capability or a deadline produces unknown, not an application failure. Do not send Ctrl+C solely because AX text stayed unchanged. Verify the installed CLI and explicitly scope directory tools (for example, `swamp ui .` when the requested scope is the current directory). Reconcile effects before at most one retry.

`generic_from_config()` defaults to NuExtract preparation and `JuliaGeneric`; the local configuration selects `CUA_GENERIC_PROVIDER=julia-1`. The qualified GLiNER2 route stays unchanged. Jev/Qwen requires an explicit override; see setup. Julia is text-only, limited to 18 action candidates plus two defer choices, and cannot substitute for screenshot perception. Do not truncate or tournament-rank oversized scopes. Report an input-limit deferral separately from a model abstention. Keep worker processes per task and close them in `finally`.

## Improve from failure

Retain input/output traces without secrets. Compare behavior against the sketch: repair projection defects under existing policy; propose genuinely new rules separately for user approval. Preserve accepted CEs and a curated regression rejecting the tempting wrong repair. Run the offline gate and separately review active/regression traces against the sketch. Green finite tests do not establish general computer-use correctness. See `docs/SALVAGE.md` in the runtime checkout.
