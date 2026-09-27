# Fixed binary Decide pilot

Try the user's cited recipe on computer-use candidate matching, not hosted Jev training. Use the native ExtractorTrainer with InputExample and Classification; same fixed label task at train/inference, rank8/alpha16/dropout.05, encoder1e-5/task5e-4, batch4, three epochs, adapter-only. Training cap660seconds; an interrupted run cannot be called three epochs.

Existing prepared native-Mac task/control data: sample one demonstrated target and one other control per source observation. Freeze1500 balanced training pairs and256 validation pairs, with source/group/application separation asserted. Audit actual schema token lengths <=384; exclude entire overlong pairs, never truncate. Record excluded counts and hashes. These are exploratory existing splits, not a fresh untouched test. A non-demonstrated control can be another reasonable action: labels mean match to the demonstrated target, not universal action correctness.

RTX3060Ti is idle and used for this smaller checkpoint; RTX3090Ti retains the user's running Qwen service. The NAS root export denied access; use the existing writable NFS submount /training-run/decide-binary-20260927. No endpoint changes.

Measure base and final binary accuracy, false positives/negatives, training time, native trainer steps/epochs, and a training probe. Verify actual encoder/classifier trainable targets; reject zero-target LoRA. Use final checkpoint, no selection on validation accuracy. Native eval disabled because the prior experiment encountered collator issues; evaluate through the public classification API separately.

Risks/checks: source/application leakage assertions; balanced-label baseline; actual encoded lengths; no skipped/nonfinite steps; parameter-target inspection; record model error versus harness failure distinctly. This experiment does not establish candidate-pool ranking, abstention calibration, generic desktop completion or deployment readiness. No training on Jev outputs or automatic promotion.

Preparation adjustment before any inference: only222 validation pairs passed the length filter; freeze200 pairs instead of256. Training still has1500.
