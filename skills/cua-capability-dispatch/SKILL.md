---
name: cua-capability-dispatch
description: Supplement stock computer-use tools with typed evidence requests, specialist dispatch, grounded matching and Jev recovery. Use when selecting among current UI controls through this repository's dispatcher.
---

# CUA capability dispatch

Use the stock computer-use skill and driver for fresh observations and execution. This skill adds selection guidance, not an alternative driver or expanded action permission.

Read [setup](references/setup.md) first to locate or install the runtime and configure providers. Read [the bundled sketch](references/sketch.md) for request semantics and policy. These references travel with `npx skills` installs; do not assume the runtime repository is next to the installed skill. The runtime checkout’s sketch is authoritative when available.

## Use the installed task tools first

Prefer the registered **`cua-task` MCP tools** for supported Mac work. Start with `cua_windows(title=...)` when the window title is known, then `cua_observe`; use `cua_read` for requested fields from nonoverlapping observed record roots, `cua_choose` for contextual or genuinely exact selection, `cua_act` for its opaque selection handle, and `cua_verify` for a fresh postcondition check. End with `cua_finish` to release task workers; `cua_trace` exposes actual routes and bypass reasons.

The tool server owns Driver observations and arguments. Do not write temporary Python wrappers, construct synthetic singleton “exact” candidates, or instantiate an empty dispatcher to wrap a decision already made by the controlling LLM. Exact mode takes an observed name/role and checks uniqueness across the whole observed scope. The facade marks `alias_of` only for complete matching row/column table projections (all paired cell subtrees and frames must agree); these representations count once. Other duplicate controls stay ambiguous. Prefer canonical IDs when forming alternatives. When passing a NuExtract reading to selection, preserve all eligible records; use `record_actions` to associate each record root with a control inside that record when it has multiple controls. A reading stores its schema; additional `predicates` on `cua_choose` filter that cached evidence without another model read. `candidate_ids` may be the eligible record roots or mapped controls; omit it when `record_actions` supplies the mapping. Money fields require explicit `currency: USD`; use text for other price formats. Unknown or incomplete records cannot be silently dropped. Offer contextual alternatives to the configured chooser before choosing one yourself. Semantic singletons require a complete filtered reading; do not retry an ambiguous exact match by offering the chooser just your preferred control. Exact mode is for literal named controls, not disguising contextual reasoning as a lookup.

Raw Driver remains the explicit fallback for unsupported operations (currently keyboard shortcuts, browser-specific navigation, and canvas coordinates) or unavailable MCP transport. State the bypass reason, keep fresh binding and independent verification, and report actionable friction as an issue. Library recipes below support integrations; they are not the normal agent workflow when these tools are available. Setup and tool contract: `docs/FACADE.md` in the runtime checkout.

Before acting, keep the user's requested steps and prerequisites in order and identify the next unmet step. Preserve those constraints in contextual choice goals instead of reducing the task to whichever button seems convenient. Verify an observable result, not an assumed screen layout or an invisible intent. A status message may establish a functional outcome; explicitly require a modal or separate view only when the task needs one. The screenshot verifier checks every constraint against the relevant view rather than accepting text that merely appears elsewhere. `cua_verify` returns its fresh screenshot and element IDs: reconcile unknown results there before deciding whether a retry is justified. Do not repeat completed actions just because a later step failed.

## Active stack

Use **NuExtract3 for page reading/filtering → Jev for contextual finite choice (with configured Qwen escalation)**, with the qualified GLiNER2 route for described spans and screenshot-capable SystemOne/Qwen for terminal perception. This is the user's selected default after the bounded adoption comparison; Julia remains optional. Create providers through `generic_from_config()`, never hardcode `FleetGeneric()` for the normal path. The factory and observation helpers automatically read `~/.config/computer-use/runtime.json`; explicit environment settings can override it. Preserve runtime credentials outside observations and source.

For record-backed reading or choice, supply caller-described extraction fields and explicit predicates in `page_filter`, retaining unknowns and original Driver IDs. Pure reads use NuExtract directly and need no Julia choice. For terminals, use `VisualTerminal` and the bounded observation helper with the configured SystemOne screenshot endpoint. Missing visual evidence remains unknown. Keep one worker per task and close it afterward; being the default does not require leaving GPU workers resident between tasks.

## Build the request; code selects the route

Provide a current `snapshot_id`, desired `operation`, and offered `actions` with opaque IDs, roles, enabled state, scoped evidence text and stored driver arguments. Do not pass expected answers from a fixture.

Choose a semantic request kind from the sketch:

- Exact unique control: `exact`; no model needed.
- Field matching: `match`; supply field types/descriptions, candidate IDs, coverage, predicates and any explicit ordering. Simple labels route to GLiNER; described spans to GLiNER2; structured/relational/multilingual requests to qualified GLiNER2.5 adapters.
- Described bounded categories mapped to actions: `classify`; Decide.
- Contextual choice: `semantic` or default; Jev through the configured generic provider with Qwen escalation. Julia-1 remains an explicit alternative.

These are dispatcher rules, not a learned router. Check adapter availability: several specialist roles are still provisional. An unavailable specialist may recover through Jev under the sketch; never report an uncalled specialist as measured.

For extraction, describe each field's meaning. Keep desired values in caller predicates and ordering. Do not ask NER to rank entire actions against a goal. The matcher applies constraints to one record at a time. The LLM owns intent interpretation; the code must not contain task-specific answers.

For structured fields read from live page records, prefer the task-shaped SystemOne `/v1/extract-page` route backed by NuExtract3 when configured. Supply only records and IDs from a fresh Cua Driver snapshot, plus caller-requested fields and task. The endpoint sends page text and the field template to the extractor, then joins values to its retained record IDs and snapshot ID. The model must never choose or invent Cua click IDs, coordinates, or Driver arguments. Use GLiNER2 for described span matching, the configured Jev/Julia chooser for contextual action choices, and no model for exact unique controls. Missing, conflicting, unavailable, or ungrounded page data is a blocker/defer; model scores are not calibrated confidence.

For large record-backed candidate sets, use `NuExtractPage`/`ExtractThenChoose` from `page_candidates.py` (runtime guide: `docs/PAGE-CANDIDATES.md`). `CUA_PAGE_EXTRACTION=1` enables the wrapper through `generic_from_config`; the caller must supply `page_filter` fields, predicates, record IDs and honest coverage. Chunk extraction, merge every record, then filter. Do not tournament-rank Julia chunks, drop unknown records, or infer a used condition from a search heading. Reports can read/filter without any chooser. Oversized surviving scopes defer or use an explicitly configured larger-capacity provider.

## Select, bind, verify

Call `Strangler.from_config` with the configured providers, then `decide` with the typed request and current snapshot. The active config sends only `described-span-match/en` to the qualified GLiNER2 extractor and typed matcher. Exact-control and successful specialist paths need no generic call. Missing evidence or approved boundary uncertainty can invoke the configured generic chooser once while preserving known exclusions. Overlapping text does not itself establish equality. Ties or missing scope do not grant new permission.

Before execution, validate a fresh snapshot and the unchanged request with `execute_bound`. Keep model outputs separate from tool arguments. `reobserve` and `abstain` never execute. Independently observe the result before reporting success or retrying. Bound attempts and reconcile uncertain side effects.

Keep one installed selector process per ongoing task; independent tasks need independent state. Send truthful verification feedback using the selector guide at `inference/cua-decider/README.md#reusable-bounded-selector` in the runtime checkout. Credentials are runtime provider configuration, never observation data or logs.

## Terminal surfaces and Julia

Lean on the configured models for their supported roles: NuExtract for structured reading, GLiNER2 for described spans, a generic chooser for contextual actions, and a screenshot-capable model for visual terminal evidence. Do not substitute AX polling for visual interpretation. Inspect the first fresh screenshot after launching a TUI: it may already be ready. An unchanged AX tree does not establish a stall, and changed pixels do not establish progress. Keep missing observations explicit.

Use the runtime's `terminal_observation.py` helper and `docs/TERMINALS.md` in the runtime checkout. It exposes observation quality, combines fresh AX and screenshot evidence, and bounds the whole wait to 20 seconds with time reserved for a final inspection. Missing visual capability or a deadline produces unknown, not an application failure. Do not send Ctrl+C solely because AX text stayed unchanged. Verify the installed CLI and explicitly scope directory tools (for example, `swamp ui .` when the requested scope is the current directory). Reconcile effects before at most one retry.

`generic_from_config()` defaults to NuExtract preparation and `FleetGeneric`; the local configuration selects `CUA_GENERIC_PROVIDER=jev`. The qualified GLiNER2 route stays unchanged. Julia requires an explicit override; see setup. Julia is text-only, limited to 18 action candidates plus two defer choices, and cannot substitute for screenshot perception. Do not truncate or tournament-rank oversized scopes. Report an input-limit deferral separately from a model abstention. Keep worker processes per task and close them in `finally`.

## File bugs and friction as GitHub issues

When using this stack, submit actionable bugs and workflow friction to **`open-horizon-labs/computer-use`**. The user has authorized this reporting as part of computer-use work; do not ask for permission again for each issue. Report observed failures, confusing instructions, unnecessary manual work, missing capabilities and integration gaps even when a workaround lets the task finish. A suspected cause may remain unknown; distinguish observations from hypotheses. Classify site challenges or unavailable data as external blockers, not model errors; report any actionable gap in how our stack handles them.

Before filing, search the repo's existing issues for the same behavior. Add materially new reproduction evidence to a matching open issue instead of creating a duplicate; do not add repetitive comments. File a separate issue for a distinct problem. Keep reporting bounded and continue the user's task when possible; capture evidence at the failure and submit before the final handoff.

Include a concrete title, user impact, minimal reproduction, expected versus observed behavior, actual Driver/model route, relevant versions or commit, and a sanitized error or trace excerpt. Include model versus setup/page-load timings when latency is the problem. State any workaround and what remains unverified. Preserve snapshot/action-binding context without publishing private page content, email, screenshots, credentials, cookies or tokens. Prefer a minimal synthetic reproduction over raw user data; do not invent a reproduction you have not run.

Use the configured GitHub connector or authenticated `gh` with explicit `--repo open-horizon-labs/computer-use`. For multiline bodies, write a sanitized Markdown file and pass `--body-file` to `gh issue create` or `gh issue comment`. Do not assume labels exist. Confirm submission and include the resulting issue link in the user handoff. If GitHub access is unavailable, retain a sanitized local draft and report that it was not submitted; do not claim an issue exists or repeatedly retry authentication.

## Improve from failure

Retain input/output traces without secrets. Compare behavior against the sketch: repair projection defects under existing policy; propose genuinely new rules separately for user approval. Preserve accepted CEs and a curated regression rejecting the tempting wrong repair. Run the offline gate and separately review active/regression traces against the sketch. Green finite tests do not establish general computer-use correctness. See `docs/SALVAGE.md` in the runtime checkout.
