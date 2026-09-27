# Native Decide binary LoRA pilot — 2026-09-27

The user's quoted fixed-label LoRA recipe produced a useful improvement on this computer-use matching slice: 48% to 78.5% held-out binary accuracy after three epochs in 285.67 seconds. This is candidate matching, not a 78.5% desktop-task completion rate.

| Metric | Base | Fine-tuned |
|---|---:|---:|
| Correct / 200 | 96 | 157 |
| Accuracy | 48% | 78.5% |
| False positives / 100 negatives | 7 | 14 |
| False negatives / 100 positives | 97 | 29 |

The final training probe was 109/128 (85.2%); it is a small training subset, not full training accuracy. No Jev comparison was run on these exact pairs. Existing Jev candidate-pool results are a different task and denominator.

## Recipe and data

- Base: fastino/GLiNER2.5-Decide, cached weights.
- Native ExtractorTrainer, InputExample, Classification; task `label`, fixed labels `matches` and `does_not_match` at train/inference. No custom loss or learned router.
- LoRA rank8, alpha16, dropout0.05, encoder/span representation/classifier targets. Actual encoder and classifier trainable names verified; 3,833,864 trainable parameters.
- Encoder LR1e-5; task LR5e-4; batch4; three complete epochs, 1125 optimizer steps. No early stopping, no skipped error/nonfinite steps. Final adapter saved, not a validation-selected checkpoint.
- 1500 balanced training pairs from750 source observations;200 balanced evaluation pairs from100 other observations. One demonstrated target plus one randomly selected alternative per observation. Existing quick-pilot native-Mac prepared data; source/group/application separation asserted. This is an exploratory reused split, not a new untouched benchmark.
- Actual schema-encoded lengths checked before selection, max378 tokens, ceiling384; no truncation. Excluded35 overlong training source groups and9 validation groups encountered during sampling. The initial requested256 validation pairs was reduced to200 before inference because only222 fit the filter.
- The 3060Ti was free; Qwen occupied about20GB on the3090Ti and was preserved. No Mac training or endpoint changes.

A non-demonstrated control may also be a reasonable action. Negative labels express the dataset's demonstrated target, not proof of universal incorrectness. Sampling one negative makes this easier than choosing among a whole UI's controls. No threshold tuning or automatic execution follows this result.

## Validation and limits

Trainer-native evaluation was disabled because prior work exposed a classification-collator issue. Base/final evaluation used the public batched classification API, unchanged labels and frozen inputs. Training alone took4m46s; evaluation, preparation and reload are additional. Batched evaluation time is not interactive per-action latency.

The raw report's `epochs: 2` is the trainer's zero-based final epoch index; `training_result.total_epochs: 3` and1125 steps confirm three complete passes. The saved runner now labels the index and count separately. The initial reload check had an output-shape parsing error after evaluation; the corrected check accepts the public API's direct task mapping as the main evaluator does. This did not change training or predictions.

## Artifacts and next use

Adapter and frozen pair data remain on NFS at guest210 `/training-run/decide-binary-20260927` (the recipes experiment submount). Root `/training-sets` access was denied, so no permission changes were made. Local source, training config, aggregate report and reload audit accompany this document. Data and model weights are not copied into Git.

The recipe merits further qualification as a binary matching specialist. Its14% false-positive rate on the sampled negatives rules out promoting it as an automatic correctness gate. Next evaluate full candidate pools and calibrate acceptance on a separate split; retain the existing dispatcher until that evidence exists.

Reload audit:157/200 again,200/200 predictions identical to in-memory final evaluation; reversed-label order agrees32/32. Adapter hash and exact package versions are in reload-check.json. These checks retire save/load and small-sample label-order risks, not generalization or action-safety risks.
