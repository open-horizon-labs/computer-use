# Solution space

Problem: dispatch each CUA request to a suitable evidence capability and execute the correctly grounded action. Binding constraint: preserve the controlling LLM's intent, current action bindings, and correctness; do not ask an extractor to reason over a goal. Working story: typed semantic requests make model boundaries explicit. Success: full request taxonomy projects to testable routing, and extract-match completes the booking fixture using actual NER evidence.

Decision criteria: semantic fit and verified correctness first; generic reuse and diagnostic trace second; latency and model count third. Assumptions: the controller can express the needed fields/criteria; observations can associate evidence with records and their controls; providers can satisfy an explicit evidence contract.

| Option | Level | Approach | Decision-changing trade-off |
|---|---|---|---|
| A | Status quo | Jev/LLM chooses among all actions from freeform goal | Broad flexibility, but repeatedly reasons about deterministic comparisons; observed errors remain |
| B | Local optimum | Improve prompts/fits of a universal classifier/router | Preserves the mistaken all-requests-as-action-classification frame; previous 5/20 is not an NER test; rejected for extraction requests |
| C | Reframe | Typed semantic requests compile into a capability plan, grounded evidence, generic matching, execution, verification | Selected. Controller supplies intent; interpretable dispatch works before a learned router exists. Must keep task data out of engine code |
| D | Redesign | Train a unified router and experts end to end for every request | Possible later, but data/labels and qualified specialist coverage are absent. Deferred until C exposes measured deficiencies |

Interpretive variety: A/B assume model judgment should choose entire actions. C tests a division into intent, evidence, comparison and execution. D changes training architecture but could retain the wrong task framing. Failure of C must be localized to request design, extraction, association, matching or Driver execution before changing models.

| Risk/assumption | Disposition | Tempting wrong patch rejected | Required evidence | Pivot trigger |
|---|---|---|---|---|
| Another booking-only implementation | Retired by evidence, pending gate | Hardcode Alex/30/earliest or parse fixture labels directly | Changed names, arbitrary field keys, product-price matching, reverse ranking and ID/order permutations through same matcher | Generic matcher depends on domain strings |
| Models selected by version ladder | Retired by evidence, pending gate | Send everything to GLiNER2 or newest model | Route cases for exact, simple entities, described fields, structured, multilingual, classification, semantic and hybrid requests | Any capability represented by wrong evidence operation |
| Correct spans attached to wrong record/operation | Retired by evidence, pending gate | Flatten UI text then select first matching row | Two partial-match records, wrong sibling operation, conflicting spans and source offsets | Cross-record evidence authorizes click |
| Missing evidence mistaken for no match | Retired by evidence, pending gate | Always take fallback when extractor returns nothing | Omitted required span, incomplete scope, tied rows | Fallback or tie-break silently selected |
| Controller supplied wrong intent/spec | Accepted with rationale for bounded test | N/A | Store exact caller contract authored from goal; do not claim arbitrary-goal translation benchmarked | Broader use requires controller-contract evaluation |
| Unqualified specialists assumed good | Accepted with rationale | N/A | Separate route-contract tests from live provider evidence; mark untested adapters unavailable | No production promotion without role-specific measurement |

Selected C, with the full family matrix and Jev as an explicit semantic path. Training, threshold optimization and production deployment are deferred. No repository Problem Weave governs this isolated experiment; no invented S&T lineage. Preserve inherited Driver safety and archived experiment evidence. Execution handoff: compile S4 + anchors; run routing and adversarial evidence gates, live booking, then separate sketch review of the same cases. Stop automatic actions on unsupported contracts or uncertainty. No new human permission is needed for the already-authorized local synthetic fixture.
