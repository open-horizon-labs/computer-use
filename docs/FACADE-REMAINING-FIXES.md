# Duplicate-control and visual-verification fixes — 2026-09-28

## Objective and current-state inspection

Fix the two remaining limitations reported after the second fresh-agent smoke, then test the fixes. The previous turn made progress (two completed smokes and committed contract fixes). This continuation inspected the current clean checkout and live Driver state. Driver was stopped; restarted the existing installed v0.28.2 daemon without changing setup or browser profile. The existing local demo window remained available.

## Table projections

The live Driver returned two `Inspect Alder` buttons: one under a row cell, one under a column cell. The full cell subtrees and screen frames matched. `ax_aliases.py` now qualifies a complete rectangular table by comparing every paired row/column cell subtree. It ignores only snapshot/index/parent/depth bookkeeping; other observed attributes must agree, including positive finite frames. Observations expose `alias_of`, and exact/global candidate construction counts the redundant projection once. Semantic alternatives also avoid offering the same qualified control twice. Execution still uses an original current Driver token; fresh-state comparison includes the entire raw tree.

This is a qualified projection rule. The Driver does not expose native AX object identity. Matching labels or coordinates alone is insufficient. Partial grids, spanned/irregular cells, missing frames, changed content/actions/enabled state and genuine repeated controls remain ambiguous. No first-match fallback was introduced.

## Visual verification

The old finite-choice prompt embedded the requested outcome in the ready option and used a generic assessment question. It returned unknown for a broad but valid summary outcome while accepting literal status text.

The repaired request puts the requested outcome in state and asks one explicit verification question: status messages can support functional outcomes; do not invent extra layout requirements; explicit modal requirements still apply; every constraint must hold in the relevant status/view, not merely occur somewhere on the page. Ready/waiting/unknown options describe outcomes without repeating the desired answer. It uses the same image-confirming SystemOne/Qwen endpoint, with the same bounded transport and uncalibrated scores.

Rejected alternative: a direct generative Qwen chat probe invented a tree-details panel and accepted a false Beryl outcome. It was not integrated or configured. This counterexample prevented promoting plausible generated explanations as visual evidence. The retained scorer's returned assessment text is a classification explanation, not an OCR quote.

## Verification evidence

Recorded screenshot probe (no actions executed from replay): broad Alder summary → ready; wrong Beryl summary → unknown; nonexistent separate Details modal → unknown; literal Alder status → ready. Endpoint times approximately 1.34–1.38 seconds.

Live Driver sequence, using fresh observations and stored action bindings:

| Action / check | Result | Visual assessment + transport |
|---|---|---:|
| Clear selection | Exact action; independent No selection check passed | No model |
| Inspect Alder | Exact alias resolution selected original row control; selected item verified | 1.495 s |
| Keep selection | Exact action; kept selection verified | 1.351 s |
| Open summary | Exact action; original broad summary wording verified | 1.321 s |
| Summary shows Beryl (false) | Unknown; no action | 1.349 s |
| Separate Details modal open (false) | Unknown; no action | 1.349 s |

Fresh Driver captures took 271–385 ms, separate from those assessment times. Temporary task providers closed. Driver remains available; existing demo window preserved. Exact actions are not evidence about Jev or Julia accuracy.

Offline checks: 45 facade tests + 46 capability tests + 15 parent-decider tests (106 total), MCP protocol check, existing simulation gate (28 scenarios, 40 metamorphic cases, 35 historical decisions, seven detected wrong repairs).

## Dissent and completion audit

| Requirement / tempting wrong fix | Evidence |
|---|---|
| Resolve the observed table duplicate, without first-match lookup | Live exact Inspect action and qualified-table unit test |
| Do not collapse true duplicates or incomplete observations | Repeated-label, missing-cell/frame, changed geometry/content/actions/enabled tests |
| Preserve current bindings | Existing changed/stale/replayed/mutated-action regressions plus live fresh revalidation |
| Fix the original broad summary check | Same wording passed on recorded and independently captured live screenshots |
| Do not force all checks to ready | Wrong-name and explicitly required nonexistent-modal negatives remained unknown |
| Do not substitute convincing hallucinated prose | Generative probe rejected before integration |
| Preserve deployed provider preferences | NuExtract/Jev defaults and optional Julia unchanged; SystemOne/Qwen retains verified image processing |

Self-review: fixes satisfy the two reproduced defects under their observed contracts. They do not claim general AX identity equivalence or universal visual-verification accuracy. Unknown remains valid when evidence is insufficient. No dispatcher matching-policy change, new model deployment or independent human review is claimed.
