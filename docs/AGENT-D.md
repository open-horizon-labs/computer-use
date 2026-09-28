# Option D: the server-side task agent (experimental)

Status: prototype behind a flag, off by default. Counterexample: CE-FACADE-004 (proposed). Nothing here is measured.

## What it is

`cua_agent(goal, title, expect, text=None, confirm=None, max_steps=8, budget_s=60)` runs the whole multi-step loop on the server with a fast model. The driving frontier LLM states the goal and the success condition once and gets back `done`, or `escalated` with evidence. Live runs showed our tools at 13% of run time and the driving LLM's turns at 87%; `cua_do` removes hops for single-shot tasks but defers when discovery is ambiguous. D moves the remaining perception and choice work off the driving LLM.

Code: `facade/agent.py` (loop, pure and injectable), `facade/experimental.py` (`register(mcp, facade)`), two small additive methods in `facade/core.py` (`Facade.agent_bind`, `Facade.agent_run`), a guarded import in `facade/server.py`.

## Enable

    CUA_TASK_EXPERIMENTAL_AGENT=1 python facade/server.py

Without the flag the tool is not registered, the default surface is unchanged and `facade/CALL_BUDGET.json` is untouched. The lint in `facade/call_budget.py` fails if the experimental module is imported outside the flag guard or if the tool's docstring does not start with "Experimental".

`expect` is required: it is the only way a run can end `done`. It must be text that is absent before the action and appears in exactly one element when the goal is met (the same exact/contains rules as `cua_do`). `text` is accepted but refused in this prototype (no type_text steps).

## The loop

Each iteration, at most `max_steps` clicks and `budget_s` of non-click time (hard cap 3x counting click time):

1. Observe the window (`Facade.observe`).
2. Check `expect` against the fresh tree. Satisfied: `done`. Present before any action: escalate (unproven).
3. Candidates: scoped to the page, by the same helpers `cua_do` uses (`_content_ids`, `_column_copies`, `_is_control`, `CONTROL_ROLES`, `record_context`, and `discover_records` for records `record_context` cannot find). That means enabled press-capable button, link, menu item, radio and checkbox controls inside the single top-level web area (an iframe's web area belongs to its page); the browser menu bar, toolbar, tab strip and AXColumn copies of table cells are never candidates. Several top-level web areas escalate `web_area_ambiguous`. No page control at all escalates `no_page_candidates` with the page and non-page control counts. Lexical prefilter: keep controls sharing a goal word with the label or record text; if more than 18 remain, keep only the top tier by matched goal words; if still more than 18, escalate `too_many_candidates` with the count. Nothing is ever truncated. The model sees each candidate's record text (bounded to 240 characters) and the goal.
4. Exact path: a quoted goal label equal to exactly one candidate label resolves through `Facade.choose(mode='exact')`, no model. A singleton candidate whose label the goal does not quote still goes to the policy and needs its authorization.
5. Policy: `Policy.choose(ctx) -> {choice, confidence, model}` picks a candidate id, `done` or `abstain`. The real adapter (`ChooserPolicy`) calls the generic chooser through `Facade.provider('generic')`; tests use a fake. A pick outside the offered set is an escalation.
6. Act: `Facade.agent_bind` builds a single-use selection bound to the content scope, `Facade.act` revalidates and clicks. A stale refusal re-observes and re-plans once per step with a NEW selection; a second stale escalates.
7. Progress: the bound scope digest before and after is recorded as `scope_changed`; two consecutive unchanged steps escalate `no_progress`.
8. A new dialog: only with `confirm` (exact label, exactly one enabled control with it, the clicked record's identifier-like lines displayed in the dialog), once per run.

## Response

`{status: done|escalated|failed, stage, steps: [{n, action{id,label}, model, confidence, ms, scope_changed}], evidence, escalation{reason, hint, observation{snapshot,...}}, cost{model_calls, model_ms, driver_ms, llm_visible_calls: "n/a"}, delivery}`. Failed adds `retryable` and `reason`.

## Escalation table (no further clicks in every row)

| reason | when |
|---|---|
| expect_present_before_action | expect text already on the page |
| dialog_already_open | a dialog existed before the first step |
| no_page_candidates | no enabled control in the page content (counts of page and non-page controls; try `cua_choose mode=regions`) |
| no_candidate | page controls exist but none share a word with the goal |
| web_area_ambiguous | several top-level web areas in the window |
| too_many_candidates | more than 18 after the prefilter; carries the count |
| policy_abstained / low_confidence / policy_invalid_choice / done_unverified | the model abstains, confidence below 0.5, names a control not offered, or claims done without expect |
| policy_unavailable | policy transport failed twice (one bounded retry) |
| destructive_control | a chosen or confirm control matches delete, remove, erase, discard, reset, sign out and the goal does not |
| dialog_needs_confirm / dialog_ambiguous / dialog_still_open | a dialog appeared without `confirm`, was replaced or multiple, or stayed open |
| confirm_control_not_found / confirm_dialog_ambiguous / confirm_identity_mismatch / confirm_identity_unknown | the confirm label is not exactly one enabled control, or the dialog does not show the clicked record |
| no_progress | two clicks in a row changed nothing in the bound scope |
| navigation | the address field changed and the goal has no navigate/go to/open/visit/browse |
| ui_changed_repeatedly / act_refused | second stale refusal, or `act` refused (needs_foreground, visual evidence changed) |
| step_budget / time_budget | `max_steps` reached, or `budget_s` / 3x cap exhausted |

`failed`: `driver_call_failed` (retryable only when nothing was clicked; after a possible delivery it is never retryable and no selection is returned), `bad_request`, `provider_failure`, `refused`.

## Safety

Preserved from the facade, unchanged: current-snapshot binding and scope revalidation, single-use selections, a click is never retried, no selection returned after a delivered click, answer-leak guard on the goal, unknown or ambiguous escalates, DriverCallFailed typing, hard wall budget counting click time, no window moves. OCR never feeds typed values (no typing at all here). Confirm dialogs only through the exact `confirm` label.

## Evaluate against the suite

Add an arm that calls `cua_agent` (driver LLM states goal, title, expect once) beside `cua_do` and native tools, on the same scenarios, with the flag set in the server environment. Compare, per success: wall time, cost (frontier tokens plus model_calls and model_ms from `cost`), and the escalation reasons. Include a cheap or absent frontier driver arm and lists larger than the LLM context. Report `escalated` as its own outcome, not as failure.

## Expected trade-off (honest, unmeasured)

Each fast-model step through the hosted chooser costs about 1 to 3 s, similar to a frontier turn (about 2.9 s). On simple tasks D may be slower than the frontier LLM, and `cua_do` already handles single-shot cases. D's case is cost per success with a cheap or absent frontier driver, and lists too large for the LLM's context. None of this is measured. The real chooser usually reports no confidence, so the threshold rarely bites; only authorization applies. If the suite shows no cheap-driver or scale advantage, retire D (CE-FACADE-004 invalidation condition).

## Not covered

type_text steps, Perception regions inside the loop (the loop escalates `no_candidate` and points at `cua_choose mode=regions`), multi-dialog flows, any live measurement.
