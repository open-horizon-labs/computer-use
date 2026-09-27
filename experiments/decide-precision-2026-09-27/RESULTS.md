# Precision experiments: no replacement qualified

All three requested fits completed on the RTX 3060 Ti within the 11-minute cap. No production routing or specialist policy changed. The original three-epoch adapter remains the strongest of these four on the original pairwise precision measure. More epochs did not improve that measure; descriptions and this small hard-negative intervention regressed it.

## Original 200-pair comparison

Balanced 100 positive / 100 negative labels, retained from the earlier exploratory validation. Precision means labeled true positives divided by predicted positives; recall uses the 100 labeled positives.

| Adapter | Fit time | Epochs | Accuracy | Precision | Recall | TP / FP |
|---|---:|---:|---:|---:|---:|---:|
| Original pilot | 4m46s | 3 | 78.5% | 83.5% | 71% | 71 / 14 |
| More epochs | 9m31s | 6 | 78.5% | 81.3% | 74% | 74 / 17 |
| Label descriptions | 5m27s | 3 | 76.5% | 77.9% | 74% | 74 / 21 |
| Reviewed hard negatives | 4m45s | 3 | 69.5% | 68.2% | 73% | 73 / 34 |

All new fits started from the base with r8/alpha16 LoRA, dropout .05, batch4, encoder LR1e-5 and task LR5e-4. Six epochs also stretches the learning-rate schedule, so this is not an isolated schedule-controlled epoch experiment. Each arm has one seed; no claim of statistical significance or general failure of hard-negative training follows.

## Full candidate pools, same 24 test tasks

A separate 24-task calibration set was frozen before scoring. Both partitions are application-disjoint from training and each other. They come from previously used exploratory validation data, not an untouched external test.

The following uses the fixed diagnostic default: a unique maximum match score >=.5, with no additional margin. These are **demonstrated-target matches**, not independently verified desktop outcomes. Alternative valid controls can count as mismatches.

| Model | Target matches / selections | Mismatches | Coverage | Selection precision | Median scoring/request time |
|---|---:|---:|---:|---:|---:|
| Original pilot | 9 / 14 | 5 | 58.3% | 64.3% | 710 ms |
| Six epochs | 8 / 10 | 2 | 41.7% | 80.0% | 710 ms |
| Descriptions | 8 / 14 | 6 | 58.3% | 57.1% | 926 ms |
| Hard negatives | 2 / 9 | 7 | 37.5% | 22.2% | 708 ms |
| Jev 1.13.0 | 11 / 14 | 3 | 58.3% | 78.6% | 175 ms |

The six-epoch model's 80% versus Jev's 78.6% is not a win: it selected fewer tasks, matched fewer targets, and was slower on this small sample. It matched one target Jev missed, while Jev matched four it missed. This does not establish a routable specialist slice.

Five of 24 test tasks exceeded the specialist's 512-token experiment budget and deferred in every arm. Those tasks remain in the coverage denominator. Jev received all 24. Restricting Jev to the same 19 input-eligible tasks gives eight target matches from 11 selections (72.7% precision), median 172 ms. On that restricted set the six-epoch adapter matched the same eight targets in aggregate with ten selections; the sample and failed calibration do not establish a reliable advantage. Specialist times cover warm batched scoring of the full offered pool (up to 32 candidates), excluding loading and the separate length audit; Jev times cover the API request. These are not like-for-like model-throughput measurements or Cua task-completion latency. They do show that this candidate-by-candidate implementation is not a demonstrated speed improvement.

## Frozen calibration gate

Threshold/margin choices were selected only on calibration, requiring at least five accepted tasks, >=95% empirical precision and zero acceptances after the demonstrated target was removed. **No adapter qualified; the gated policy defers all tasks.** This is zero coverage, not perfect accuracy.

Even without the removed-target condition, the best calibration precision with at least five accepts was 80.0% for the pilot, 53.8% for six epochs, 61.5% for descriptions and 14.3% for hard negatives. Thus the abstention stress requirement alone did not disqualify an otherwise 95%-precision slice.

On test at the diagnostic default, removed-target acceptance counts were 11/24, 6/24, 11/24 and 8/24 for the four adapters; Jev accepted 8/24. These are stress indicators, **not proven invalid actions**: removing the demonstrated target does not prove every remaining control is invalid. Specialist removals reuse independent pair scores; Jev sees the altered candidate set in a fresh call.

## What to do with this

Keep Jev as incumbent. Use the [gradual rollout design](../../docs/SPECIALIST-ROLLOUT.md) to identify recurring, independently verified task contracts and shadow one narrow specialist at a time. Favor contracts that can be handled in one extraction/classification call. This experiment repeatedly scores a broad goal against each control, which costs more and still does not establish reliable acceptance.

The next training dataset should be scoped to a named contract, with reviewed acceptable alternatives, explicit no-action examples and sufficient verified examples from that contract. A specialist can improve on a narrow role without becoming a universal action ranker. The current results do not justify more blind epochs, a learned router, or deleting the Decide option.

The hard-negative arm changed only 41 texts among 750 negatives; all 750 positives and class labels were preserved. Those 43 reviewed proposals were judged by Codex, not an independent reviewer. The unchanged labels were not comprehensively audited. The regression cannot tell us whether the dominant cause is remaining label ambiguity, distribution shift, optimization sensitivity or the task formulation. Do not generalize it to “hard negatives do not work.”

## Evidence and review

- `comparison.json`, `*-evaluation.json`, `jev-control.json`: aggregate and per-task model evidence, including captured description schemas. Original pair result reproduced exactly after adapter reload.
- `*-training.json`, `*-config.json`, `environment.json`: completed epochs/steps, timers, settings and package versions. Saved adapters remain under `/training-run/decide-precision-20260927/{six,described,hard}/adapter/final` on NAS.
- `manifest.json`, `data-audit.json`: frozen hashes, split disjointness and exact changed-row count. Full source texts/review remain on NAS.
- Six selection tests reject ties resolved by order, confidence-as-correctness, hidden overflow coverage and ignored removed-target alternatives. Python compilation and skill-reference consistency checks pass.
- GPU verification after evaluation: 3060 Ti released (1 MiB); existing 3090 Ti service allocation retained (20,208 MiB). No Qwen/SystemOne stop or reconfiguration was issued.

Self-review against the aim: the requested bounded comparisons and rollout design are complete; an improved production specialist was **not** obtained. Policy authority remains with the user. The rollout is a proposal, not an accepted CE, amended governing sketch or completed CESS cycle. No deterministic gate is presented as semantic certification.

Risk disposition: schema loss, split overlap, changed-positive labels, absent checkpoints and cap overrun were checked and did not occur. High-confidence/pool-selection failures were observed and block promotion. Independent label adjudication, unseen tasks and actual driver outcomes remain necessary before a specialist takeover; this offline experiment cannot establish them. Existing CESS policy/projection/accepted archive stayed unchanged.
