# Gradually replace Jev on qualified task types

Status: rollout design requested by the user; no trained specialist is promoted by this document. Current dispatcher behavior remains unchanged. Jev is the generic fallback, with its existing Qwen escalation.

## Start with tasks Jev already handles

Identify repeated request contracts from verified task traces. A slice is a semantic contract—such as selecting a control with explicit attributes—not an application name, fixture seed, or action ID. Preserve enough context to identify all candidates and independently verify the effect. Jev's choice alone is not ground truth.

| Candidate slice | First specialist to evaluate | Evidence needed before taking over |
|---|---|---|
| Unique exact control | Existing deterministic binding | Current uniqueness/role/operation; no inference needed |
| Short explicit attributes | GLiNER2 plus typed matcher | Grounded fields, complete scope, correct unique match and verified effect |
| Task/control compatibility | Fine-tuned Decide binary classifier | Full-pool ranking, precision/coverage, ambiguity and missing-target behavior |
| Bounded category to action | Decide | Described classes, caller mapping, evaluated abstention |
| Simple entity types | GLiNER | Role-specific comparison with GLiNER2 and Jev |
| Records/relations/multilingual | Qualified GLiNER2.5 adapter | Preserved relationships/record scope and role-specific evaluation |
| Open semantic navigation/recovery | Jev, then Qwen | Generic baseline; no specialist replacement assumed |

The binary Decide experiments are a candidate for one row, not a new universal next-click model.

## Four stages

1. **Observe:** retain task request, provider/version, latency, choice and independently observed outcome. Redact before storage. Known failures become proposed CEs; log uncertainty rather than inventing labels.
2. **Shadow:** run the specialist on the same request alongside the incumbent. Only the incumbent path may authorize the action. Measure disagreement and full decision latency. Missing capability, input overflow or failed evidence stays with Jev. Shadow inference costs extra compute and is an evaluation stage, not a speed claim.
3. **Selective takeover:** after explicit approval for a named contract and versioned evidence, let the specialist handle only its validated acceptance region. All other requests go to Jev. Evaluate completed task correctness and accepted precision at useful coverage, with uncertainty bounds and latency including fallback. A raw confidence such as .999 is not a correctness guarantee.
4. **Expand or roll back:** add neighboring contracts only through reviewed evidence and CESS approval. Retain the incumbent path and last qualified specialist version. Verified regressions can disable the affected specialist pending review; do not silently broaden another specialist's scope.

Use the existing deterministic dispatcher. Do not train another router until routing itself has a measured problem that static request contracts cannot address.

## Promotion evidence

Each proposed promotion record names: request-contract version, provider/checkpoint hash, train/calibration/test splits and lineage, accepted-region rule, comparison against Jev on the same requests, precision/coverage/latency, independent outcome checks, accepted CEs and regressions, known holes, approval authority and rollback target. Candidate record state is `shadow`; a benchmark script cannot change it to active.

A slice does not qualify because Jev and the specialist agree. Both can be wrong. A slice also does not qualify solely from a balanced one-positive/one-negative test: real UIs have many alternatives, sometimes no valid action, and sometimes several acceptable actions. Label ambiguity needs review before being counted as a model failure.

## CESS loop

S is the current capability sketch and approved contract boundaries. P is the dispatcher/provider implementation. A preserves approved counterexamples. R contains cases rejecting distinct wrong repairs; G checks explicit expected fields. A capable model or user separately reviews the same traces against S.

For each failure: retain the request and observed effect; distinguish bad projection from missing policy; repair existing-policy violations or propose the smallest policy change; rerun active case and R; review against S. Extra epochs do not authorize a scope change. Newly discovered evaluation cases may join training only after that evaluation is retired and a fresh holdout is frozen.

Next step after these runs: identify a narrow slice with sufficient independently verified examples, compare its specialist with Jev in shadow, and submit a concrete promotion record. There is no automatic rollout from the present exploratory scores.

## Proposed counterexamples for the rollout boundary

- A candidate classifier reports .999 confidence on a wrong control. Required protection: confidence alone never promotes a specialist; use measured precision/coverage and verified outcomes. Observed in the binary pilot, not a hypothetical calibration guarantee.
- The demonstrated target is removed but another control still receives a high match score. Required protection: qualify abstention/full-scope behavior, not only pair accuracy. Target-removed probes expose a risk but need label review before being treated as proof that no valid action existed.
- Two Cancel controls have different IDs. Required protection: review context and acceptable alternatives before labeling one a hard negative. ID disagreement alone cannot train the specialist to reject a valid action.
- A narrow field-matching specialist is invoked for open semantic navigation. Required protection: preserve its declared input contract and hand off requests outside it to Jev.

These are rollout design cases, not automatic additions to the accepted policy archive. New policy wording and promotion remain reviewable user decisions; existing binding/exclusion protections continue to apply.

## First experiment outcome

The [precision comparison](../experiments/decide-precision-2026-09-27/RESULTS.md) did not qualify a broad Decide compatibility classifier for takeover. Six epochs, descriptions and 41 reviewed negative replacements did not improve the original pairwise precision. No calibration policy qualified, and candidate-by-candidate scoring was slower than Jev. Use these failures to prioritize a narrow, verified contract with a cheaper one-call formulation; none of these checkpoints is active.
