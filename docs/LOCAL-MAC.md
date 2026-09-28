# Local Mac provider profile

The `local-mac` profile is the default provider policy. It selects Julia-1 for finite choices and refuses hosted chooser, extraction, and visual endpoints. Cua Driver and the facade remain local to the controlled Mac. Select the existing homelab-backed setup with `{"profile":"fleet"}` in `~/.config/computer-use/runtime.json`, or set `CUA_PROFILE=fleet` for one process.

## Current support

- Julia-1 is a local finite-choice model. Its reference Python runtime supports CPU inference; it does not require CUDA. This repo's worker accepts `--device cpu`, checks the pinned checkpoint SHA-256 and revision, and retains the existing 18-action plus two defer limit.
- The GLiNER worker accepts CPU execution with `--device cpu`; the existing described-span contract and same-record reducer do not change. CPU dependencies and checkpoint must be installed locally.
- NuExtract3 page extraction and screenshot interpretation are not yet available through a bundled MLX worker. The profile rejects the existing hosted endpoints and therefore reports those calls as unavailable instead of transmitting page or screenshot evidence remotely.
- Cua Perception (`scripts/install_perception.py`, on by default via `scripts/setup_facade.sh`) now provides on-device screenshot regions (OCR text + icon boxes) fully locally, independent of this profile choice — it runs through cua-driver's own signed extension, not a chooser/extraction/visual endpoint this profile gates. It only ever supplies description/corroboration context and a bounded fuzzy verification check (see [docs/FACADE.md](FACADE.md#cua-perception-screenshot-regions)); it does not replace the still-missing local NuExtract3 page reader, which remains the only typed-value source and is still unavailable locally.

## Configure local model workers

Use a dedicated Python 3.11+ environment with the Julia package/runtime and CPU PyTorch, and cache the verified Julia checkpoint outside the repository. Configure the runtime file with JSON argv arrays pointing to that environment and checkpoint:

```json
{
  "profile": "local-mac",
  "CUA_GENERIC_PROVIDER": "julia-1",
  "CUA_JULIA_COMMAND": "[\"/absolute/path/to/python\", \"/absolute/path/to/computer-use/workers/julia_worker.py\", \"/absolute/path/to/Julia-1\", \"--device\", \"cpu\"]",
  "CUA_SPAN_COMMAND": "[\"/absolute/path/to/python\", \"/absolute/path/to/computer-use/workers/span_worker.py\", \"--device\", \"cpu\"]"
}
```

The span adapter appends the selected checkpoint ID to its command. Runtime configuration values are strings; the worker commands are JSON arrays encoded as strings. Keep model code and weights outside the checkout and verify checkpoint identity before use.

This is not yet a turnkey all-local experience: no installer provisions the model environments, the local NuExtract3 reader and local visual provider remain to be implemented, and the local profile has not been qualified end-to-end on a Mac. Until those gaps are closed, use only workflows whose required providers are installed locally; missing provider capability is a blocker, never a reason to switch to Jev/Qwen or a hosted endpoint.
