# CUA capability sketch S4

## Authority, aim, and scope

Authority: the user's current corrections: the controlling LLM describes wanted values per label; an extractor recovers evidence; an algorithm matches it to current controls and performs the action. The user explicitly requests a sketch covering GLiNER, GLiNER2, GLiNER2.5, GLiNER2.5-Decide, and Jev by CUA request kind, rather than a GLiNER2-only solution.

This experimental sketch supersedes S2.2's universal vanilla-Decide starting policy and the recent whole-goal GLiNER2 classifier experiment. It preserves S1's current-snapshot binding, offered actions, independent verification, bounded retries, correctness-first criteria, compute constraints, and S3's same-record identity plus exact operation rules. Generic comparisons explicitly supplied by the controlling LLM are now authorized; hidden benchmark-answer logic remains forbidden. Old experiment artifacts retain their historical policy.

Aim: one caller request carries intent, evidence requirements, selection rules, and the desired physical operation. A replaceable projection dispatches appropriate evidence tasks, combines grounded outputs, binds one current action, executes with Driver, and independently observes the result. The model family is an implementation choice; the physical operation alone does not select it.

## Request contract

The controller supplies a fresh snapshot ID; current action IDs, roles, and immutable Driver arguments; evidence scoped to each action/record; and one of the semantic requests below. It may also supply an ordered workflow of these requests. The request contains explicit field descriptions/types, match predicates, ordering, a tie rule if one is intended, and any authorized fallback. Values such as a person's name or desired duration are caller data, never projection constants.

The controller owns goal interpretation and task decomposition. The dispatcher validates the typed request; it does not ask an NER model to infer hidden constraints, plan a task, or select from entire candidate descriptions. Unclear intent returns to the controller.

## S4.1 Request → model → algorithm

These are provisional task-appropriate defaults, not a claim that model capabilities are exclusive or that a newer checkpoint is always better. A registry identifies exact checkpoint/API, supported languages and input limits, readiness, and task-specific evaluation evidence. Deployment promotion requires measurement on the role being used.

| Semantic request and caller example | Required output | Initial route | Deterministic or controller work after inference |
|---|---|---|---|
| **Exact control**: activate the unique current button named Save; type supplied text into a bound field | Current action binding | No model | Check unique role/name/ref, enabled state, snapshot and payload; execute |
| **Simple entity lookup**: extract named people/organizations from separately scoped records using simple type names | Grounded entity spans | Original GLiNER checkpoint qualified for those types/language | Join spans to their own record, apply supplied equality predicates, bind exact operation |
| **Described field match**: extract provider, duration and start time from each offered slot | Grounded short spans using per-label descriptions | GLiNER2 span model, initially `fastino/gliner2-base-v1` | Typed normalization; conjunctive predicates on one record; caller-specified ordering; unique best; explicit fallback only after all records are excluded |
| **Structured/long-span/relational extraction**: recover an address, a document record, or the assignee linked to each ticket | Grounded records or typed relations with source associations | GLiNER2.5 boundary checkpoint appropriate to language/schema | Preserve grouping/relations; apply the same match/bind algorithm; never flatten unrelated records into a bag of values |
| **Multilingual extraction**: same task with evidence in a supported non-English language | Grounded requested fields | Qualified multilingual extractor, provisional GLiNER2.5-multi default | Same generic matcher; do not infer language or date locale from a version number |
| **Bounded classification → mapped action**: classify a visible ticket as billing/technical and select its caller-mapped queue; classify a dialog as retryable/auth-required | One of the caller's described classes | GLiNER2.5-Decide | Validate class and caller's label-to-action mapping; enforce any configured abstention/acceptance policy; bind current control |
| **Semantic action choice**: choose the next navigation step, disambiguate a control from context, recover from an unfamiliar state | One offered action ID | Jev through the existing bounded selector; Qwen remains its authorized escalation | Current-snapshot binding and execution checks still apply; returned confidence is not proof of success |
| **Verification**: check whether an expected value/state is present after an action | Evidence for a declared postcondition | Exact check, extraction, classification, or Jev according to the evidence task above | Fresh independent observation; record verified progress, failure, or uncertainty; never infer completion merely from a model choice |

Examples of composition: GLiNER2 extracts identity fields while Decide classifies each record's category, then the matcher joins outputs by record ID. GLiNER2.5 can recover a relationship before the controller requests an action on its endpoint. Jev may resolve a semantic ambiguity, then an extractor grounds the named target. Independent evidence requests can run in parallel; dependencies remain ordered. This first projection exposes these as evidence steps rather than training a router.

## S4.2 Projection policy and order

1. Validate typed intent, scope completeness, supported values/operators, current snapshot and allowed action bindings. Exact unique controls bypass inference. Unsupported or contradictory requests defer with a reason.
2. Compile the evidence operations into a plan using S4.1. Prefer measured task fit before speed. Never substitute Decide for NER, or treat raw whole-action ranking as entity extraction. Do not send an absent/unsupported provider's request to an unrelated model silently.
3. Run each evidence step with its documented API. Keep labels/descriptions as supplied by the controller. Per-record batches preserve grouping. Providers return grounded spans/records or described class labels, not invented executable arguments. Validate their result count, record association, source offsets/text, and schema.
4. Merge evidence by current record/action ID. Apply **all** supplied predicates to the same record; then order eligible records using caller-specified typed keys. A missing, malformed, conflicting, or low-confidence required value is unknown, not evidence of absence. A known predicate failure excludes a record even if another field is unknown. Otherwise an unknown possible competitor prevents automatic selection/fallback.
5. A unique best yields the bound action. A tie, missing scope coverage, or an unsupported comparison returns an evidence gap to the controller. Invoke the explicit fallback only if all ordinary candidates are demonstrably excluded and the fallback is currently offered. Empty complete scope can use that fallback. Never use action ID or serialization order to break semantic ties.
6. Bind selection to the snapshot and requested operation (click, type, select, etc.). Revalidate snapshot and use the stored Driver arguments; a selected row cannot authorize a sibling operation. No action is executed on malformed evidence, stale binding, or an unresolved gap.
7. Observe afresh and check the declared postcondition independently. A changed page alone is not success. If a slot disappeared, reobserve and rematch remaining controls; a confirmation step must re-extract displayed identity and compare it with the selected record before confirming. Bound steps/time; reconcile uncertain side effects before retrying.

## S4.3 Jev default and specialist recovery

Authority: the user's explicit agreement that Jev is the default/fallback, followed by authorization to exercise and repair this projection through simulation. A well-formed freeform request with omitted kind or `auto` uses Jev. An unavailable or failed specialist, rejected classification, incomplete extraction, or ambiguous matching consults Jev once, preserving the original goal, current observation/controls, declared constraints, and usable evidence. This is a change of reasoning provider, not the business fallback action (such as joining a waitlist).

Preserve S4.2 and inherited anchors: never recover from stale/invalid requests by clicking anyway; do not revive a control already excluded by grounded constraints or wrong operation; do not let a generic choice fabricate a tie priority, unseen evidence, or permission. Unresolved identical ties or incomplete observation still require more information. Jev failure ends in explicit deferral with no recursive fallback. The installed Jev adapter may use its existing bounded Qwen escalation; the dispatcher itself makes one generic-provider invocation. Successful specialists and exact-control paths do not invoke Jev unnecessarily.

## S4.4 Extracted identity boundary recheck

Authority: user approval following the desktop-free simulation report ("y, I like that"). If an extracted text field fails exact equality but contains the requested value as a complete word or phrase, treat that field as uncertain boundary evidence. Preserve the source text and consult Jev with the original criteria. Overlap is never sufficient for acceptance; do not trim the span or equate substring matching with equality. Word-internal substrings do not qualify. Other known predicate failures remain exclusions; unavailable or unsuccessful generic resolution defers. This may bring genuinely distinct names such as Acme Pro to review, but does not automatically accept them.

## S4.5 Optional chooser and terminal perception

Authority: user request to commit terminal observation/deadline improvements and add Julia-1 support for users who prefer it (2026-09-27).

Jev/Qwen remains the default generic chooser. Explicit configuration may substitute the pinned Julia-1 finite-choice provider in the same generic slot, including its single specialist recovery invocation. This does not change GLiNER2 qualification, typed reducers, or action authorization. Report the actual provider from its output, not the historical `jev` slot name. Julia limits must defer explicitly without truncating candidates; scores are uncalibrated. No recursive fallback or automatic Julia promotion is authorized.

For terminal surfaces, an unchanged AX tree or screenshot is neither evidence of a stall nor evidence of success. Inspect a fresh screenshot immediately against the declared postcondition; expose AX availability, unknown terminal coverage, screenshot availability/change, and visual interpretation requirements separately. Use a configured screenshot-capable provider or the controlling visual LLM when text is insufficient. A vision response cannot invent executable arguments. Offered actions retain their stored Driver arguments and snapshot binding, including the screenshot in the bound request. Observe independently after execution.

The terminal observation helper uses one total deadline of at most 20 seconds across Driver calls, visual calls and polling, reserving time for final visual inspection. If capture or interpretation cannot complete, return unknown with the cause; do not label the app stalled or send an automatic interrupt. Recovery is a caller decision after reconciling state, with at most one retry. Confirm a terminal program's CLI and supply an explicit directory when its default scope differs from the shell's working directory.

## S4.6 NuExtract candidate preparation

Authority: user request to execute and test extractor-first filtering instead of chunking Julia choices (2026-09-27). An explicitly described `page_filter` may read fresh record-backed candidates through NuExtract3 in bounded chunks, merge all records, then apply caller predicates within each record. Preserve source quotes, IDs, original Driver arguments, unknowns and complete-scope requirements. An extracted value is source evidence, not calibrated confidence. Identity-boundary overlaps remain unknown under S4.4. Do not drop unknown competitors or choose per-chunk winners. The generic chooser receives only demonstrated eligible candidates; no match or unresolved scope defers, oversized surviving scope defers or uses an explicitly configured overflow provider with all survivors. The final selection remains bound to the original full request. Reporting can return extracted records without invoking a chooser. This opt-in preparation does not alter exact-control or qualified GLiNER2 paths.

## S4.7 Selected NuExtract/Julia default

Authority: user explicitly instructed “switch to nuextract, Julia, and our full changes” after the implementation and live endpoint tests. This supersedes the default-provider wording in S4.3/S4.5/S4.6: the factory now defaults to NuExtract candidate preparation plus Julia-1 generic choice; Jev/Qwen remains an explicit alternative. Read persistent operator configuration automatically. Keep the qualified GLiNER2 route and all binding/unknown/coverage checks. Use SystemOne/Qwen's screenshot capability for visual terminal assessments. A finite visual assessment is not a transcription or invented visible-control list. This is user selection of the stack, not a new claim of model accuracy.

## Explicit holes and nonclaims

- Optimal checkpoint/threshold per role, calibration of classification acceptance, broad CUA coverage, and whether GLiNER beats GLiNER2 on simple labels require role-specific measurements. Defaults above are routing hypotheses.
- Visual-only grounding needs a qualified visual path or the controlling LLM; text extraction cannot invent missing visual evidence.
- Freeform goals, undeclared tie priorities, locale/unit inference, implicit fallback, consequential ambiguous intent, and unresolved multi-record relations remain controller responsibilities.
- A registry entry and a deterministic routing test do not establish a model's accuracy or an installed adapter. Report unavailable adapters explicitly. The experimental projection is not automatically installed into the production selector.

## S4.8 Readings are strings; the controller interprets; revalidation scope

Authority: user instruction 2026-09-28 (/cess): "the schema you gave NuExtract is typed. That should be ignored. Strings. An LLM is driving, it can handle thirty minutes." Counterexample CE-FACADE-001 (live facade booking run: 144 s, 42 turns, five NuExtract readings of the same twelve records, one Jev→Qwen cascade; native tools 41 s, 13 turns).

NuExtract page readings return each requested field as the displayed string, or unknown only when nothing was extracted. The projection never normalizes reading strings into typed values (durations, clock times, money, numbers), never marks a present string unknown for failing a type, and ignores a supplied type while recording that it did. Reading predicates are text operations. Interpreting units, times and prices is the controlling LLM's responsibility: it may state which of a reading's records are eligible. The projection accepts only records of that reading, lets stated text predicates narrow the verdict but never widen it, reports unknown competitors the verdict skipped, and traces whose judgment produced the scope. A reading-grounded unique candidate binds without a generic chooser (S4.2 §5). Typed normalization and ordering remain only in the qualified GLiNER2 spans contract. S4.2 §7's bound applies to readings: at most two readings of the same records for one observation; a further reading is a projection defect and defers with the extracted strings, never with a re-read hint. Guardrails: a static check that the reading path carries no typed normalization, and runtime reporting of ignored types.

Revalidation before execution compares the observed content scope the selection was bound in: the offered actions' common ancestor, widened to the enclosing web area for a browser page, otherwise the window, together with the browser's address field, so a navigation refuses even when the new page's tree matches. Any change inside that scope refuses execution; a change outside it, such as a tab strip's live memory readout, does not. Authority: the user approved this clause (CE-FACADE-002, 2026-09-28).

## Anchors K and validation

Cua Driver observes/executes on the Mac; homelab GPU inference runs remotely. Preserve Qwen/SystemOne services. Generic engine source cannot contain appointment names, target times, seed IDs, fixture parsing rules or oracle access. Caller examples may describe those tasks. Credentials use the existing Fleet path and never enter logs. Bound input to each provider's actual limit; reject rather than silently truncate.

Gate G compares approved fields for the active CE and curated R, including route, selected current ID or explicit deferral, source associations, and action authorization. Sketch review by Codex/user independently assesses those same case traces against S4.1–S4.2. Both are required. Live fixture completion and latency are reported separately from mocked dispatch tests and extraction probes.

## Artifact register and change contract

S: this file. K: anchors above and `../README.md#reusable-bounded-selector`. P: `dispatch.py` and provider/Driver adapters. A: `COUNTEREXAMPLES.json`. R/G: `test_dispatch.py` and the live booking trace named in `REPORT.md`. Simulator: `simulation.py` provides desktop-free state transitions with controlled or real providers; `simulation_gate.py` preserves replay, metamorphic and mutation checks. See `simulation/REPORT.md` for results and pending policy. The original Cua Driver fixture remains integration evidence. Reviewer: Codex capable-model review; policy authority: user.

Compilation authority: CE-CAP-001/002 in the archive, approved by the user's explicit corrections. Preserve same-record matching, exact operation, fresh binding, no oracle, role-appropriate model APIs, no invented policy for ties/missing evidence, and the complete model-family table. Do not regress these to a classifier ranking whole actions or a single model used for every request. Keep unqualified provider accuracy and unresolved intent as holes. Fixed contracts: typed request → evidence plan → grounded evidence → action binding → independent verification. If authority conflicts, make no policy edit and return one precise question to the user.

Sources for capability boundaries: [original GLiNER](https://github.com/urchade/GLiNER), [GLiNER2 and boundary architectures](https://github.com/fastino-ai/GLiNER2), [GLiNER2 span checkpoint](https://huggingface.co/fastino/gliner2-base-v1), and the existing bounded Jev selector guide. Defaults and task decomposition above are this sketch's proposed operational policy, not vendor benchmarks.
