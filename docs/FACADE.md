# Local CUA task tools

The facade gives an agent one coherent, evidence-first interface to desktop work. It joins fresh Cua Driver observations, page reading, action selection, execution and independent verification while keeping each boundary explicit. Agents should use these tools directly instead of writing task-specific shell wrappers around model endpoints or Driver calls.

Cua Driver still observes and acts on the Mac. The default `local-mac` profile selects Julia-1 and refuses hosted chooser, extraction, or visual endpoints; `fleet` opts into the configured NuExtract3, Jev/Qwen, GLiNER2 and SystemOne services. Exact unique name/role selection bypasses a chooser by design. See [profile support](LOCAL-MAC.md) before relying on local page reading or visual interpretation, which are not yet bundled. Check `cua_trace` when you need the route and timing actually used.

**Minimum cua-driver: 0.29.1.** The server detects the installed Driver's version once (`<driver> --help`) and refuses to start tools against an older build, because older Drivers refuse `background_input` routes with `off_space_or_ax_unresolved` instead of resolving them (fixed in [trycua/cua#4068](https://github.com/trycua/cua/issues/4068)). An unparsed/unknown version string is not blocked. The detected `driver_version` is reported by `cua_trace` and `cua_finish`.

## Agent workflow

Treat a UI task as an ordered sequence of evidence, decision, action and verification steps. Keep the user's prerequisites intact, select only the next unmet step, and verify its visible result before continuing. For each state transition:

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

`fields` maps field names to `{description}`. Readings are the displayed strings (sketch S4.8): a supplied `type` or `currency` is ignored and echoed back as `types_ignored`, and no reading value is normalized into minutes, clock times or money. The controlling LLM interprets "half-hour" or "$80" itself. Predicates on a reading are text operations, `{field, op, value}` with `op` one of `eq`, `neq` (alias `ne`), `contains`, `not_contains` (default `eq`). After a read, pass the records you judge eligible as `candidate_ids` (record IDs) or `record_actions`. They must be records of that reading; stated predicates can only narrow them, and any unknown record you skipped is reported as `unknown_competitors`. A single judged or filter-unique record binds directly (route `grounded_singleton`, no chooser call). A third reading of the same records for one observation is refused with the extracted strings, because re-reading to fix a format is a defect, not recovery. Typed normalization and ordering remain only in spans mode. Describe meanings without injecting expected answers. Choose a separate observed root for every logical record. Table rows preserve cell boundaries; there is no inferred header/value mapping. Coverage is the caller's assertion about the requested scope, not a claim that a site has no more results.

For record-backed actions, pass the returned `reading` to `cua_choose`. Map every eligible root to an observed descendant through `record_actions` when necessary. Additional `predicates` on the choice conjunctively filter the cached reading without another extraction. They cannot revive earlier exclusions. Candidate IDs can name all eligible record roots or their mapped controls; omit them when the mapping already describes the scope. The original complete mapping is also accepted when an additional predicate narrows it. Every provided join is checked, and an eligible record with no compatible enabled control blocks selection. Put schemas on `cua_read`; ordering remains a spans-mode feature. Criteria supplied to incompatible modes are rejected, never silently ignored. A semantic singleton without a complete filtered reading defers: it cannot serve as model confirmation of a caller's preselected winner.

An unknown or incomplete filtered scope (`cua_read` or `cua_choose`) defers with reason `unknown_or_incomplete_scope` plus actionable detail: `unknown_ids`, `eligible_ids`, `excluded_count`, and `missing_fields` naming, per unknown record, which requested fields NuExtract left missing/unparsed, plus a short `hint`. All eligible records must survive until selection.

Exact mode searches the whole observed scope even if a caller supplies fewer candidates. Complete rectangular AX tables may expose matching cell subtrees through both rows and columns. The facade annotates those aliases and counts each once only when every paired cell subtree, observed attribute and positive frame agrees. It does not merge by labels or coordinates alone. Missing cells, structural/content/frame differences and genuine repeated controls remain ambiguous. Driver object identity is not exposed: this is a qualified table-projection rule, not general node equivalence. Exact bypasses and singleton filtered choices are not chooser accuracy evidence.

### Candidate descriptions carry record context

Each offered action's `description` (what the chooser sees) is its own label/value plus ` — record: ...`, the text of the outermost ancestor that still contains exactly one control of that role/label (falling back to role alone for distinctly labelled controls) — i.e. the enclosing record such as a table row rather than its actions cell, never the parent's full listing text and never a sibling record's text. Twelve identical "Book" buttons each get their own row's provider/service/time text; they never see each other's.

### Goals describe criteria, never the answer

`cua_choose` in `semantic`/`visual` mode rejects a `goal` that names an observed element ID (`\be\d+\b` matching an ID actually in the current observation) or states the answer ("the correct one is ...", "the answer is ..."). Describe the distinguishing evidence instead; the chooser evaluates it against current candidates, it does not confirm a preselected winner. Separately, if `candidate_ids` narrows the scope to a strict subset of the observed same-kind controls with no `reading` grounding that scope, the result and `cua_trace` mark `caller_preselected: true` so a caller-narrowed win is never counted as chooser accuracy, and a caller-narrowed visual pick can never be corroborated by its own quoted text.

This guard is best-effort against a cooperative agent's habits, not a security boundary: paraphrase evades it, and a goal that legitimately contains an ID-shaped token matching a live element is rejected (rephrase it). Real protection comes from the scope rules above and from independent verification.

### Visual choice requires corroboration

A `visual`-mode pick from the screenshot model never authorizes execution by itself — a plausible-sounding `evidence` string or a high score is not proof. It is corroborated, and only then issued a selection handle, when either: (a) a `reading` was supplied — the offered candidates are already the reading's mapped, filtered controls, so the pick is consistent with grounded evidence by construction (`reading` is now accepted in `visual` mode, not only `semantic`); or (b) deterministically, every `"quoted"` token in the `goal` appears in the picked candidate's own record context (see above) and in no other offered candidate's record context, and the offered scope was not caller-narrowed (`caller_preselected`). Otherwise `cua_choose` returns `status: defer`, `reason: visual_uncorroborated`, and a non-executable `suggested_id` — no selection handle is issued.

## Binding and limits

Selections retain immutable server-owned requests/arguments. Before acting, the facade recaptures the window and compares the content scope the selection was bound in: the offered actions' common ancestor, widened to the enclosing web area for a browser page, otherwise the whole window (AX content, hierarchy and frames, excluding expiring Driver tokens). Any change inside that scope refuses execution; browser chrome outside it, such as a tab strip's live memory readout, does not (proposed S4.8 clause, CE-FACADE-002). Only an unchanged observation permits rebinding tokens to the fresh Driver snapshot. Visual choices additionally require unchanged screenshot bytes. Selections are single-use even when delivery fails. This narrows but cannot eliminate a UI race between observation and execution.

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
