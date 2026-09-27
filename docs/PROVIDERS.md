# Provider configuration

Offline tests use injected responses. Live calls require explicit runtime configuration and credentials; extracting this repo does not deploy anything.

`RemoteSpans` reads `CUA_SPAN_COMMAND`, a JSON argv array, and appends the model ID. Example on a CUDA worker with pre-cached weights and installed `torch`/`gliner2`:

```sh
export CUA_SPAN_COMMAND='["python3", "/absolute/path/computer-use/workers/span_worker.py"]'
```

For a remote worker, use an operator-managed launcher executable as the array's first element. It must accept the model ID, launch the included worker, and forward stdin/stdout. The worker emits readiness followed by one JSON response per input line. It uses cached weights, CUDA, and four CPU threads. Logs belong on stderr. Provision the worker environment separately; this extraction does not pin a newly tested model environment or install one.

`FleetGeneric` defaults to the pre-existing `~/.local/share/fleet-cua-decider/select-fleet --fast jev`. Override `CUA_SELECTOR_COMMAND` with a JSON argv array for another installation. The command must implement the included cascade's JSON-lines protocol. Keep one process per task, close it when done, and do not share verification state across independent fixtures.

The copied `inference/cua-decider/setup.sh` is the original Fleet-specific optional installer. It retains original network/credential defaults and is not run automatically. Review the accompanying README for Fleet access, feedback semantics and pinned stock Cua dependencies. Qwen configuration and credentials remain runtime concerns in `decision_providers.py`; never commit values. Homelab service deployment remains owned by homelab-infra.

The live booking harness also requires the installed stock Cua Driver/jev-use checkout. It is retained for future integration validation, not exercised by the offline test command. Other benchmark references in historical documentation are provenance, not bundled executable dependencies.
