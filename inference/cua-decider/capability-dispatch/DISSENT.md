# Dissent: capability dispatch

Decision: a caller-authored semantic request compiles to appropriate model work and generic selection. Confidence before review: medium. Stakes: avoid yet another universal classifier or a benchmark-specific solver disguised as generic CUA.

Steel-man: the controller already reasons about the user goal. It can specify the wanted values and field descriptions. Small models can supply bounded evidence; code can compare evidence using explicit caller rules; Driver can execute and verify. Different evidence needs justify different model families.

Contrary evidence: the recent GLiNER2 whole-action classifier got 5/20, while earlier short-span extraction got 360/360 fields. These measure different capabilities. Prior specialist training transferred poorly; naming experts did not create qualified experts. The earlier span gate did not improve over Jev given the same structured task spec. These observations defeat a universal model/learned router prescription, but do not prove this new composition.

Pre-mortem:
1. Functional: perfect spans from separate rows are merged and the wrong control is clicked. Retire with row-binding, conflicting-evidence and wrong-operation tests.
2. Adoption: callers must handcraft a large DSL for every tiny interaction and stop using it. Keep exact controls direct, preserve freeform semantic Jev requests, and allow the controlling LLM to send the field schema in one call.
3. Opportunity cost: spend weeks deploying five models despite only one useful path. Project all capability branches and test their contracts, then activate/evaluate adapters for concrete cases. Do not claim five-way model accuracy from routing tests.

Hidden assumptions: short described spans favor GLiNER2 (local extraction evidence, not universal superiority); original GLiNER and 2.5 support overlapping tasks (vendor architectures, so no strict generation ladder); typed request is faithful to intent (controller responsibility, record it); observation preserves source/record grouping (must verify); model outputs include valid source offsets (gate against source text).

Reconstructed story: capability decomposition survives. The weakest assumption is reliable source-to-control association outside explicit labels. Confidence rises in the extraction hypothesis, not in general CUA reliability. The next action is a complete dispatch sketch/projection with adversarial routing/evidence tests and one live extract-match fixture.

Decision: ADJUST. Route by semantic work, not click/type verbs, benchmark family, or model version. Keep all requested model families in the sketch, include no-model and hybrid paths, and record adapter readiness separately. Missing evidence, unsupported types, ties and visual-only tasks return to the controller. Confidence after dissent: medium; this is a reversible experiment, not a committed public API or production rollout.
