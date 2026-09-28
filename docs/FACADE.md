# Local CUA task tools

The facade gives an agent one coherent, evidence-first interface to desktop work. It joins fresh Cua Driver observations, page reading, action selection, execution and independent verification while keeping each boundary explicit. Agents should use these tools directly instead of writing task-specific shell wrappers around model endpoints or Driver calls.

Cua Driver still observes and acts on the Mac. The default `local-mac` profile selects Julia-1 and refuses hosted chooser, extraction, or visual endpoints; `fleet` opts into the configured NuExtract3, Jev/Qwen, GLiNER2 and SystemOne services. Exact unique name/role selection bypasses a chooser by design. See [profile support](LOCAL-MAC.md) before relying on local page reading or visual interpretation, which are not yet bundled. Check `cua_trace` when you need the route and timing actually used.

**Minimum cua-driver: 0.29.1.** The server detects the installed Driver's version once (`<driver> --help`) and refuses to start tools against an older build, because older Drivers refuse `background_input` routes with `off_space_or_ax_unresolved` instead of resolving them (fixed in [trycua/cua#4068](https://github.com/trycua/cua/issues/4068)). An unparsed/unknown version string is not blocked. The detected `driver_version` is reported by `cua_trace` and `cua_finish`.

## Default path: cua_do

One call does the whole observe, read, match, choose, act, verify chain server-side. You state the intent once; the dispatcher runs the evidence chain and the specialist models do the reading, matching and choosing.

```
cua_do(goal, title | pid+window_id, records=None, operation='click', text=None,
       expect=None, accept_unknown=None, budget_s=20, confirm=None)
```

- `title` is an exact window title (0 or more than 1 match refuses with no Driver action); `pid`+`window_id` address a window directly.
- `goal` is the intent in words. Naming an element ID or writing "the correct one is ..." is refused before any Driver or model call.
- `records` (for lists): `{fields: {name: {description}}, predicates: [{field, op, value}], record_ids?, coverage_complete?}`. Values are the displayed strings (S4.8); ops are `eq`, `neq`, `contains`, `not_contains`. Without `record_ids`, one record is discovered per control of the single repeated (role, label) kind, using its inferred record; if discovery is ambiguous the call defers with `records_ambiguous` and what it found, never a guess.
- Without `records`, a quoted goal label that matches exactly one observed control resolves exactly (no model); otherwise the chooser picks among the offered controls; a page with no AX controls but healthy Cua Perception offers text regions (regions mode).
- `expect` is text that must appear in exactly one element of the fresh AX tree after the click (case-insensitive exact, else contains).
- `accept_unknown` names unknown records you judge ineligible (S4.2 section 4), used when a previous call deferred on them.
- `confirm` is OPT-IN and names the exact label of the control to press in a dialog that appears after the first click, e.g. `"Yes, cancel order"`. Without it a dialog is never pressed: your goal authorized the first click, not whatever a dialog then offers (a lone "Delete" whose text matches the record is still not authorization). With it the call presses the dialog control only if (a) the dialog's displayed identity matches the selected record COMPLETELY (every requested field read and equal) and (b) exactly one enabled control in the NEW dialog has that label (case and whitespace insensitive, exact); never the chooser, always a click. A dialog that was already open, was replaced, or came with others defers as `confirm_dialog_ambiguous`.

What happens inside the call: one fresh observation; one NuExtract read of the discovered records (`READ_BUDGET` still applies); the same-record filter; if exactly one record is eligible it is a grounded singleton with no chooser call; if several, ONE chooser call over the eligible controls only; an unknown competitor without `accept_unknown` defers; the selection is bound and acted through the existing `act` (S4.8 scope revalidation, single-use, no window moves); then independent verification. `cua_do` composes `observe`, `read`, `choose`, `act` and `verify`; it owns no selection policy.

The response is small and bounded: `status` (`done` only when verification is `satisfied`; otherwise `deferred`, `refused` or `failed`), `stage` (where it stopped), `selected` (id and short description), `judgment` (`filter`, `controller`, `chooser`, `exact`), `verification` (`status`, `route`), `evidence` (extracted strings, capped, on a deferral), `delivery` (`none`, `delivered`, `uncertain`), `observation` (the fresh snapshot handle, element count, top roles and up to 12 controls, so you can continue without another `cua_observe`), and `trace_summary` (`calls_by_route`, `ms_by_stage`, `passes`, `attempts`, and `follow_up_needed`, true unless the status is `done`). The tool does not claim how many LLM calls were made (it cannot know); the call budget measures that from outside. `cua_trace` and `cua_finish` still work: every stage and a `do` summary are traced content-free.

### Recovery inside the call (no LLM in the loop)

The driving LLM is not in the recovery loop (S4.2 section 7). Recovery is deterministic code, bounded, inside `budget_s` (click delivery is excluded from it) and a hard cap of 3x `budget_s` that counts everything including click and confirm time, after which no further non-click step runs (`budget_exceeded`, `delivery` says whether a click had landed). Each Driver observation gets a timeout of `min(20 s, remaining)`. Every attempt is listed in `trace_summary.attempts`.

| # | Situation | What cua_do does | Never |
|---|---|---|---|
| 1 | Stale-UI refusal at act (content changed inside the bound scope; nothing clicked) | Reobserve and re-run the whole pipeline; if the same record still uniquely matches, bind a NEW selection on the fresh snapshot and act. At most 2 passes per call. | Reuse or rebind the old selection or its element tokens (S4.3). |
| 2 | Element indices or tokens shifted, same content | Same as 1: the fresh pipeline finds the record by its fields, not by id. | Click the old id. |
| 3 | Driver failure BEFORE the click (observe, read, choose, act's revalidation) | Retry that stage once after a 300 ms backoff. | Retry a click, or anything after a click may have been delivered. |
| 4 | A field unknown or garbled | Re-read once (`READ_BUDGET` caps it at 2), then stop and defer with the extracted strings. | A re-read loop. |
| 5 | Verification unknown | AX exact/contains on the fresh tree, then Perception exact presence (never satisfies on digits), then the screenshot model if configured. `unverified` only when no step applies. | Report delivery as success. Text that was already on the page before the click, or the text just typed into the target field, proves nothing: it is `unproven` and no presence-based step (AX, Perception, screenshot) may satisfy it. |
| 6 | A dialog appears after the click (orders) | Without `confirm`: defer `confirm_dialog_present` with the dialog's control labels (bounded) and the identity-match result; the first click is done, so do not repeat the goal (press the control with a fresh `cua_do` whose goal quotes its exact label, or `cua_choose` exact + `cua_act`). With `confirm`: press it only on a complete identity match and exactly one exact-label control (see above). | Press anything the goal did not authorize; use the chooser; press a lone control by default; treat an unchanged, replaced or extra dialog as the confirm dialog. |

The LLM gets `deferred` or `failed` back only for: (A) a click that may have been delivered but could not be verified (`delivery_unverified`; never click again blindly, inspect `observation.snapshot`); (B) ambiguity (several eligible records the chooser cannot settle, an unknown competitor without `accept_unknown`, `records_ambiguous`); (C) a real content change inside the bound scope that alters which record matches (`record_changed`, `no_eligible_record`, `ui_changed_repeatedly`), or a record that cannot be re-identified by its fields after a stale refusal (`record_changed_unverifiable`: a requested field was missing, or two records read the same, so recovery is not attempted). A dialog after the click is also returned (`confirm_dialog_present`, `confirm_dialog_ambiguous`, `confirm_identity_*`). Once any click has been delivered, no selection is ever handed back and any confirm selection is dropped. Other stops are `budget_exceeded` (stage reported, nothing clicked after it), and `failed` when a bounded retry is exhausted (`stage`, `attempts`, `retryable`). `retryable: true` only ever means nothing was clicked; a failure at the click is `retryable: false` with `delivery: uncertain`.

### When to drop to the primitives

Only when `cua_do` defers and you need finer control, or for an operation it does not cover (keyboard shortcuts, navigation). `cua_windows`, `cua_observe`, `cua_read`, `cua_choose`, `cua_act`, `cua_verify`, `cua_trace` and `cua_finish` are Advanced and behave exactly as before; the `observation.snapshot` from a deferral is a current handle for them.

### Why: 13% of the time, 87% of the turns

Across 15 live runs the facade's tools were 13% of agent wall time (138 s of 1,099 s); the other 87% was the driving LLM (about 2.9 s per turn, 374 turns). With read, choose, act and verify as separate tools the LLM mediated every hop: a clean booking took 9 LLM-visible calls where native tools take about 5. The sketch's design is that the dispatcher runs the evidence chain and the LLM states intent once (S4.1-S4.2, S4.6, S4.8). A clean `cua_do` run is one LLM-visible call, with the specialists still doing the reading and choosing. The improvement is a hypothesis until the live A/B against the native arm is run; the offline tests establish call counts, not accuracy or latency.

**Known limits of `expect` and the budget.** `expect` proves *presence* of a text in exactly one element after the click, and text that was already on the page or that the tool typed itself is ruled out. It cannot prove causation: an unrelated update that adds an element containing the same text (a toast) can still satisfy it, so choose an `expect` string specific to the outcome. The wall budget binds every stage that can precede a click, including the confirm dialog's read and choose, and the hard cap counts click time; a stage already running when the cap passes can overshoot by at most that one stage, and no click starts after it.

## Call budget

`facade/CALL_BUDGET.json` is the machine-readable ceiling on LLM-visible calls. It is measured, not assumed: `facade/call_budget.py` drives the real server tool functions through a counting wrapper under a minimal LLM policy (call `cua_do`; on a deferral follow its recovery hint once, or naively repeat once; stop at done or after 4 calls) on fake fixtures. The scenarios are a booking list (1 call), orders with `confirm=` (1), canvas/regions (1), a 400-element page (1, responses under 6 KB), stale-UI recovery (1), a transient Driver failure before the click (1), an unknown competitor then `accept_unknown` (2), a dialog without `confirm` then a fresh `cua_do` quoting its control (2) and an abstaining chooser then narrowed predicates (2), each also capped at its measured reader and chooser calls (none of the chooser for a grounded singleton or a dialog). The default-path tool list is `["cua_do"]` and at most 9 tools are allowed. `python3 scripts/check_call_budget.py` (offline; needs the facade requirements) prints a table of scenario, calls, budget and PASS/FAIL, also checks the tool surface (`cua_do` first, every other tool's docstring beginning "Advanced") and lints the skill's default-workflow section. CI runs it on every pull request and fails if any facade test was skipped. `experiments/facade-vs-native/score.py` counts `llm_visible_calls` per live run from the transcript, prints `over_budget`, accepts `--fail-over-budget`, and prints the facade-versus-native ratio of calls and turns.

To change a number legitimately: write or extend a CE (proposed, then approved) that records the new number in its `call_budget` under the same dotted name, then set the number and its `changed_by` in CALL_BUDGET.json in the same change; `facade/test_budget.py` fails on a number with no CE, or one that differs from its CE. Adding a tool, or a mandatory step to the default path, is such a change. `.github/CODEOWNERS` routes CALL_BUDGET.json, SKETCH.md, COUNTEREXAMPLES.json, the workflows and AGENTS.md to the policy owner for review.

## Advanced: the primitives step by step

Use these only when `cua_do` defers and you need finer control. Treat a UI task as an ordered sequence of evidence, decision, action and verification steps. Keep the user's prerequisites intact, select only the next unmet step, and verify its visible result before continuing. For each state transition:

1. Use `cua_windows` to find the relevant existing window, then `cua_observe` to obtain a fresh screenshot and accessibility tree. The returned snapshot and element IDs define the only evidence currently available.
2. If the task depends on page content, call `cua_read` with the observed record roots and only the fields/predicates needed. NuExtract3 returns grounded values tied to those source records; missing or ambiguous values remain unknown. Keep records separate and avoid whole-page roots that combine several results.
3. Call `cua_choose` for the next action. Use semantic mode for contextual alternatives, spans for the qualified typed-field contract, visual mode when image evidence is needed, or exact mode only for a genuinely unique observed name/role. Model scores are not calibrated confidence. A bypass, singleton, unsupported request, provider failure or incomplete evidence is not chooser success; reconcile the state or report a blocker.
4. Execute only the opaque selection handle with `cua_act`. The facade retains the original Driver arguments and checks that the observed state is unchanged before acting. Never invent element IDs, coordinates or Driver arguments.
5. Call `cua_verify` with a concrete visible postcondition. Treat delivery as an attempted action, not proof it worked. Use the returned fresh observation to reconcile failures and ground the next step.
6. Keep retries bounded and close task-scoped model workers with `cua_finish` when done. This preserves Cua Driver and the user's windows.

Each step must be grounded again after the UI changes. An old candidate, reading or selection does not authorize a later action. If a route cannot establish the requested evidence, stop at unknown/blocker rather than guessing. Do not use raw shell or direct Driver/model wrappers as an alternate path for ordinary UI decisions; use a documented capability gap only when the facade explicitly cannot express the operation, and preserve fresh observation, bound arguments and independent verification.

## Install

Requires Python 3.10+, the installed and authorized Cua Driver, and providers configured per [setup](../skills/cua-capability-dispatch/references/setup.md). Reuse the normal browser profile and existing Driver setup.

From the runtime checkout, run the setup entrypoint (creates `.venv-facade`, installs facade requirements, and installs/verifies the pinned Cua Perception extension by default):

```sh
scripts/setup_facade.sh          # add --no-perception to skip the perception install
python3 scripts/set_profile.py fleet
codex mcp add cua-task -- "$PWD/.venv-facade/bin/python" "$PWD/facade/server.py"
codex mcp get cua-task --json
```

Run the profile switch command any time to change providers: `python3 scripts/set_profile.py local-mac` or `python3 scripts/set_profile.py fleet`. Settings are stored separately per profile and switching preserves both sets. If `cua-task` is already registered, skip the `codex mcp add` command. Start a fresh Codex session after installation or a profile change so the server reloads its runtime configuration. `CUA_DRIVER` overrides the default `~/.local/bin/cua-driver`. Runtime commands, endpoints and secrets stay outside this repository. No model starts merely to list tools.

### Cua Perception (screenshot regions)

`scripts/install_perception.py` installs the pinned `cua-perception-v0.2.1` extension through cua-driver's signed catalog lifecycle (download, SHA-256 verify, `extension inspect`/`install`/`status --self-test`); it is idempotent and safe to rerun. It never runs as part of `cua_observe`/`cua_choose`/`cua_verify` themselves — the facade only reads `extension status cua-perception` and, when perception is missing/unhealthy, returns a Gap naming this installer rather than installing anything itself. Use `--check` to report without mutating, and `--version cua-perception-v<x.y.z>` to pin a different release.

**License notice:** the bundled OmniParser icon detector and its Ultralytics components are AGPL-3.0-only; the PP-OCR detector/recognizer are Apache-2.0. `install_perception.py` prints the AGPL notice before installing; read it, and the extension's own third-party notices, before redistributing or hosting this over a network service.

Startup probes `extension status cua-perception --self-test`; `perception_version`/`perception_state` (`healthy`/`not_installed`/`unhealthy`) are reported by `cua_trace` and `cua_finish`.

**OCR values are never a source of truth.** A real offline parse of a synthetic booking page (1021x1280, 86 regions, Perception 0.2.1) got layout right but values wrong: `"60 min"`→`"600 min"`, `"Starts 1:30 PM"`→`"Starts 130 PM"`, `"45 min"`→`"4min"`, `"Follow-up"`→`"Follwupe"`. So perception text never feeds `cua_read`/NuExtract fields or exact verification; NuExtract3 on the AX tree stays the only typed-value reader. Perception is used for two things only:

- **Record grouping fallback** (`Facade.record_context_perception` in `facade/core.py`): when AX `record_context`/`sibling_record` find nothing (flat/ambiguous tree), map the control's AX frame into perception's screenshot-pixel space — only when that scale is provably a uniform ratio between the actual PNG size and the Driver's reported window bounds, never assumed 1:1 — then band text regions vertically between this control and its nearest same-role/label siblings. The result is labelled `record_basis: perception_layout` and used only in `cua_choose` candidate descriptions/corroboration, never as a `cua_read` value.
- **Fuzzy visual-verify presence check** (`Facade._perception_fuzzy_check`): after `cua_verify(mode='visual', ...)`'s AX quoted-text check fails and before calling the hosted vision model, a healthy perception route checks the quoted text against OCR regions. A quote containing a digit, or one that matches more than one region, or only a fuzzy/substring match, can only ever return `status: unknown, evidence: ocr_candidate` (plus the matched region) — never satisfied. Only a short, digit-free quote matching exactly once after whitespace/case normalization may return `status: satisfied, route: perception_ocr_fuzzy`.

### `cua_choose(mode='regions')` — capture-bound canvas/pixel targets

The installed cua-driver (0.30.3) documents a capture-bound contract for parsing and acting on canvas/pixel-only targets that have no AX control: `get_window_state`/`get_desktop_state` return a `capture_id`; `parse_visual_regions` takes that exact `capture_id`; and `click` accepts `capture_id` + `x`/`y` to atomically admit and consume that same capture before dispatch (refusing `capture_not_found`/`capture_expired`/`capture_generation_mismatch`/etc. rather than falling back to an unbound click). `cua_choose(mode='regions')` offers the current observation's parsed regions (text/icon, with bounds) as candidates under the same answer-leak rejection and quoted-text corroboration rules as `mode='visual'`. `cua_act` on a region selection is delivered via that same `capture_id` — **never rebound to a fresher capture** the way AX `element_token`s are rebound, since the Driver's capture registry (not this facade) is the source of truth for the capture's freshness; the facade still performs its usual AX-fingerprint-unchanged safety check first. This path is built strictly from the documented tool schemas (`cua-driver describe click`/`parse_visual_regions` and upstream `perception-extension.md`'s "Capture-bound parse and action" section) since operating a live desktop window is outside this repository's constraints for verifying it end-to-end; treat it as unverified against a real window until exercised live.

## Tools

| Tool | Contract |
|---|---|
| `cua_windows` | Local Driver inventory; optional exact `title` filter; reuse the requested window |
| `cua_observe` | Fresh AX elements/parent IDs, screenshot, quality, opaque snapshot |
| `cua_read` | NuExtract fields and predicates over nonoverlapping observed record roots |
| `cua_choose` | Configured Jev/Julia contextual alternatives, qualified GLiNER2 spans, visual choice, regions (perception, capture-bound), or unique exact name/role |
| `cua_act` | One opaque selection; no caller-supplied Driver arguments |
| `cua_verify` | Independent fresh exact or screenshot postcondition check, returning that observation and screenshot |
| `cua_trace` | Content-free actual routes, startup/decision timing, `caller_preselected` flags, `driver_version`/`perception_version`/`perception_state` and outcomes |
| `cua_finish` | Close task workers and invalidate handles; preserve Driver and user windows |

`fields` maps field names to `{description}`. Readings are the displayed strings (sketch S4.8): a supplied `type` or `currency` is ignored and echoed back as `types_ignored`, and no reading value is normalized into minutes, clock times or money. The controlling LLM interprets "half-hour" or "$80" itself. Predicates on a reading are text operations, `{field, op, value}` with `op` one of `eq`, `neq` (alias `ne`), `contains`, `not_contains` (default `eq`). After a read, pass the records you judge eligible as `candidate_ids` (record IDs) or `record_actions`. They must be records of that reading; stated predicates can only narrow them, and if your verdict skips a record the reading left unknown, the call defers (`unknown_competitors_unacknowledged`, showing that record's extracted strings) until you name exactly those IDs in `accept_unknown`; IDs that are not unknown in the reading are rejected, and the acknowledgement is traced. A single judged or filter-unique record binds directly (route `grounded_singleton`, no chooser call). A third reading of the same records for one observation is refused with the extracted strings, because re-reading to fix a format is a defect, not recovery. Typed normalization and ordering remain only in spans mode. Describe meanings without injecting expected answers. Choose a separate observed root for every logical record. Table rows preserve cell boundaries; there is no inferred header/value mapping. Coverage is the caller's assertion about the requested scope, not a claim that a site has no more results.

For record-backed actions, pass the returned `reading` to `cua_choose`. Map every eligible root to an observed descendant through `record_actions` when necessary. Additional `predicates` on the choice conjunctively filter the cached reading without another extraction. They cannot revive earlier exclusions. Candidate IDs can name all eligible record roots or their mapped controls; omit them when the mapping already describes the scope. The original complete mapping is also accepted when an additional predicate narrows it. Every provided join is checked, and an eligible record with no compatible enabled control blocks selection. Put schemas on `cua_read`; ordering remains a spans-mode feature. Criteria supplied to incompatible modes are rejected, never silently ignored. A semantic singleton without a complete filtered reading defers: it cannot serve as model confirmation of a caller's preselected winner.

An unknown or incomplete filtered scope (`cua_read` or `cua_choose`) defers with reason `unknown_or_incomplete_scope` plus actionable detail: `unknown_ids`, `eligible_ids`, `excluded_count`, and `missing_fields` naming, per unknown record, which requested fields NuExtract left missing/unparsed, plus a short `hint`. All eligible records must survive until selection.

Exact mode searches the whole observed scope even if a caller supplies fewer candidates. Complete rectangular AX tables may expose matching cell subtrees through both rows and columns. The facade annotates those aliases and counts each once only when every paired cell subtree, observed attribute and positive frame agrees. It does not merge by labels or coordinates alone. Missing cells, structural/content/frame differences and genuine repeated controls remain ambiguous. Driver object identity is not exposed: this is a qualified table-projection rule, not general node equivalence. Exact bypasses and singleton filtered choices are not chooser accuracy evidence.

**Candidates and corroboration (2026-09-28 live findings).** Regions are offered as the parse's *text* regions only; icons are never bulk-offered. The parse call must carry the facade's `session`, because Driver captures are session-scoped. If more than 18 text regions remain, the scope is narrowed by the label you quoted in the goal (e.g. `"Export"`), and if it is still too large the call defers with `too_many_regions` and the count, never truncating. A pick is corroborated only by an **exact** label match: every quoted token equals the picked region's text and exactly one candidate has that text, so `"Export"` beats `Export All` while `Export All` cannot pass for `"Export"`. Uniqueness is measured across every text region in the window, not just the narrowed candidates, and any other region within one edit of the quoted label vetoes the pick: a decoy that reads exactly `Save` must not win when the real button's OCR is garbled (`Sove`). The cost is that labels differing by one character (`Option 1` / `Option 2`) cannot be corroborated in regions mode; use AX or a reading for those. Several quoted tokens must all equal the one picked text. Icon-only buttons are not offered in regions mode. A caller-narrowed `candidate_ids` still cannot corroborate itself. Whether a unique exact label may skip the chooser is not decided and needs the policy owner.
### Candidate descriptions carry record context

Each offered action's `description` (what the chooser sees) is its own label/value plus ` — record: ...`, the text of the outermost ancestor that still contains exactly one control of that role/label (falling back to role alone for distinctly labelled controls) — i.e. the enclosing record such as a table row rather than its actions cell, never the parent's full listing text and never a sibling record's text. Twelve identical "Book" buttons each get their own row's provider/service/time text; they never see each other's.

### Goals describe criteria, never the answer

`cua_choose` in `semantic`/`visual` mode rejects a `goal` that names an observed element ID (`\be\d+\b` matching an ID actually in the current observation) or states the answer ("the correct one is ...", "the answer is ..."). Describe the distinguishing evidence instead; the chooser evaluates it against current candidates, it does not confirm a preselected winner. Separately, if `candidate_ids` narrows the scope to a strict subset of the observed same-kind controls with no `reading` grounding that scope, the result and `cua_trace` mark `caller_preselected: true` so a caller-narrowed win is never counted as chooser accuracy, and a caller-narrowed visual pick can never be corroborated by its own quoted text.

This guard is best-effort against a cooperative agent's habits, not a security boundary: paraphrase evades it, and a goal that legitimately contains an ID-shaped token matching a live element is rejected (rephrase it). Real protection comes from the scope rules above and from independent verification.

### Visual choice requires corroboration

A `visual`-mode pick from the screenshot model never authorizes execution by itself — a plausible-sounding `evidence` string or a high score is not proof. It is corroborated, and only then issued a selection handle, when either: (a) a `reading` was supplied — the offered candidates are already the reading's mapped, filtered controls, so the pick is consistent with grounded evidence by construction (`reading` is now accepted in `visual` mode, not only `semantic`); or (b) deterministically, every `"quoted"` token in the `goal` appears in the picked candidate's own record context (see above) and in no other offered candidate's record context, and the offered scope was not caller-narrowed (`caller_preselected`). Otherwise `cua_choose` returns `status: defer`, `reason: visual_uncorroborated`, and a non-executable `suggested_id` — no selection handle is issued.

## Binding and limits

Selections retain immutable server-owned requests/arguments. Before acting, the facade recaptures the window and compares the content scope the selection was bound in: the offered actions' common ancestor, widened to the enclosing web area for a browser page, otherwise the whole window (AX content, hierarchy and frames, excluding expiring Driver tokens). Any change inside that scope refuses execution; the browser's address field is bound with the page, so a navigation refuses too, while other browser chrome, such as a tab strip's live memory readout, does not (S4.8, CE-FACADE-002, approved). Only an unchanged observation permits rebinding tokens to the fresh Driver snapshot. Visual choices additionally require unchanged screenshot bytes. Selections are single-use even when delivery fails, with one exception: a Driver failure (`driver_call_failed`) while re-observing, before anything was clicked, returns the selection so the same handle can be retried. A stale-UI refusal or any failure at or after the click keeps it consumed. Driver call failures are typed `driver_call_failed` errors carrying the tool name and exit code only, never stderr; a failed perception parse is cached per capture rather than retried per candidate. This narrows but cannot eliminate a UI race between observation and execution.

The facade supports native AX click and text entry. Keyboard shortcuts, browser-specific navigation and canvas coordinates still require a declared raw Driver fallback. It cannot establish terminal readiness from AX alone. Tool delivery is not success; verification remains mandatory before reporting an effect. Missing evidence and provider failures produce unknown, never success. Read-only annotations describe intended tool effects; observations can still foreground a window.

Provider deadlines are bounded; use at most one retry after reconciling state. Observe/act calls may contain multiple bounded Driver operations. Caller task deadlines must cover the whole workflow. Close workers with `cua_finish`; server shutdown also closes them. This server is local stdio, not a network HTTP service.

An unbound-looking Driver observation now distinguishes two causes instead of one generic message: `window_closed` when the target `pid`/`window_id` is no longer in the Driver's window list (call `cua_windows` again), or `driver_snapshot_unavailable` with the Driver's `refusal`/`degraded_reason` detail when the window is still listed but the Driver degraded or refused.

### Spaces, foreground and `background_input`

The facade reads the Driver's `background_input` block on every observation. Before `cua_act` delivers a click/type, it refuses with `needs_foreground` if `background_input.exact_window.status` is not `matched`, or a needed route was refused with reason `off_space_or_ax_unresolved` (a known cua-driver < 0.29.1 behavior when the window sits on another macOS Space). The facade **never** activates, raises or moves a window to work around this — it only refuses so the caller asks the user to bring the window forward, or upgrades cua-driver.

## Verification

```sh
python3 -m unittest discover -s facade -p 'test_*.py'
# Also check the actual MCP schema/response contract, without desktop or models:
.venv-facade/bin/python facade/check_protocol.py
```

### `cua_verify` match and quoted-text postconditions

`cua_verify(mode='exact', ...)` takes `match: 'equals' | 'contains'` (default `equals`); `contains` is a case-insensitive substring check over the observed label and value instead of full equality. `cua_verify(mode='visual', ...)` first extracts any `"quoted"` text from `postcondition` and checks it, case-insensitively and whitespace-normalized, against the fresh AX tree's labels/values. Only a purely textual postcondition (quotes plus filler words like "the page now shows") qualifies, and each quote must appear in exactly one element; if so, it returns `status: satisfied`, `route: exact_text_postcondition` without calling the vision model at all. Otherwise (no quote, repeated text, or other constraints such as which row or view) it falls back to SystemOne/Qwen. See [adoption evidence](FACADE-ADOPTION.md). Tool discovery and safe binding passed the local trial; model accuracy and autonomous sequencing are not established by that result.

[Second fresh-agent smoke](FACADE-SMOKE-2.md) covers the record/action contract fixes and their bounded adoption follow-up.

[Duplicate-control and visual-verification repair evidence](FACADE-REMAINING-FIXES.md) covers live positive/negative checks and rejected alternatives.

[Facade vs. native A/B evidence and the eight fixes above](FACADE-AB-2026-09-28.md) covers the 2026-09-28 bounded run that motivated record context, visual corroboration, answer-leak rejection, discoverable predicates, actionable defers, verification match/quoted-text, and the Spaces/foreground/driver-version refusal.
