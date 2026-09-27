# Reproduce the precision comparison

These scripts reproduce this experiment on the existing training guest; they are not a portable production trainer. Use Python from `/opt/gliner-decide-bench/.venv`, cached `fastino/GLiNER2.5-Decide`, and GPU 1 (RTX 3060 Ti). GPU 0 remains occupied by the Qwen service. Record dependency versions before comparing across installations.

Inputs on the NAS-mounted guest:

- `/training-run/decide-binary-20260927/{train,validation}.jsonl` and its original `adapter/final`.
- `/training-run/quick-1000-data/{train,validation}.jsonl` for the original full candidate pools.
- Output root: `/training-run/decide-precision-20260927`.

Run `prepare_proposals.py` then `freeze_data.py` once. The latter preserves the specific Codex-reviewed proposal indices used here. Those approvals apply to this exact input/order; never transfer them to another dataset. `manifest.json` records frozen input hashes. Raw texts and the full review record stay on NAS.

Run `fit.py six`, `fit.py described`, and `fit.py hard` sequentially, with `CUDA_VISIBLE_DEVICES=1 HF_HOME=/models/gliner-hf HF_HUB_OFFLINE=1`. Each fit starts from the base, uses its own output directory, and enforces a 660-second training alarm. The six-epoch comparison also lengthens its learning-rate schedule. Loading/token auditing and subsequent evaluation are outside the fit timer.

After fitting, run `evaluate.py` in the same environment, alongside `fit.py` and `selection.py`. It reloads saved adapters, captures serialized schemas, scores the original 200 pairs and both frozen full-pool splits, and selects thresholds using calibration only. It never substitutes a test-selected threshold when none qualifies. Complete offered pools are used; any oversized candidate defers the whole task.

For the hosted control, run `jev_control.py --input PATH_TO_POOL_SPLITS --output jev-control.json` from a checkout with configured Fleet access. Credentials are resolved at runtime by the existing adapter. No desktop actions occur. Its first request includes startup overhead; latency is not a driver task-completion measurement.

Copy `evaluation-summary.json` and `*-evaluation.json` from NAS to this directory, retain the Jev output, and run `summarize.py`. These outputs contain IDs/scores, not source UI text. `*-training.json` copies preserve completion, timing and trainer settings separately from the adapters on NAS.

Verify with `python3 -m unittest discover -s experiments/decide-precision-2026-09-27 -p 'test_*.py'` from the repository root. No production specialist is promoted by running these scripts.
