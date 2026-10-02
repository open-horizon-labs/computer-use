# Provider configuration

**Current default profile:** `fleet` (user decision 2026-09-30, "Jev is the default"): NuExtract3 page reading, Jev/Qwen choice, GLiNER2 spans, and SystemOne screenshots (the only visual route: without `CUA_SYSTEMONE_URL` the visual provider is unavailable and nothing is sent; there is no chat-completion fallback). **The fleet profile sends page content (record text, screenshots, candidate descriptions) to the hosted services you configure** (`CUA_EXTRACT_URL`, `CUA_SELECTOR_COMMAND`, `CUA_SYSTEMONE_URL`); a clean install configures none, so those routes are unavailable until you do, and nothing is sent. `local-mac`, with Julia-1 as the chooser and no hosted fallback, remains selectable by an explicit profile. Runtime helpers load `~/.config/computer-use/runtime.json` automatically.

## Provider profiles

The default is `fleet`: a clean install (no `runtime.json`) resolves to it, and so does a `runtime.json` that names Jev or a hosted endpoint without a `profile` key. A `runtime.json` without a `profile` key that names Julia-1 (`CUA_GENERIC_PROVIDER=julia-1` or `CUA_JULIA_COMMAND`) and no hosted endpoint keeps `local-mac`, so an existing Julia operator is never moved to a hosted profile by the default changing. Switch profiles from the repository checkout with `python3 scripts/set_profile.py local-mac` or `python3 scripts/set_profile.py fleet`. The script moves legacy flat settings under the inferred current profile and preserves them while selecting the new one. Use `CUA_PROFILE=fleet` for a one-process override. The local profile forces Julia-1 and rejects configured hosted selector, extraction, or visual endpoints rather than silently sending evidence off-device.

The profile is a provider policy, not an installer. Julia-1 CPU inference and GLiNER2 CPU inference need local Python environments and cached checkpoints. The current NuExtract page adapter and screenshot provider still require a separately implemented local MLX worker; in `local-mac`, those capabilities fail closed when unavailable. Do not configure hosted URLs in a local-only deployment. See [Mac local runtime status](LOCAL-MAC.md) for the supported subset and remaining work.

For hosted Jev, start with the [API key, endpoint and model setup](../skills/computer-use/references/setup.md#jev-api-key-endpoint-and-model). It also documents the separate Qwen key and endpoint, credential precedence, and a Jev-only smoke check.

Offline tests use injected responses. Live calls require explicit runtime configuration and credentials; extracting this repo does not deploy anything.

`RemoteSpans` reads `CUA_SPAN_COMMAND`, a JSON argv array, and appends the model ID. Example on a CUDA worker with pre-cached weights and installed `torch`/`gliner2`:

```sh
export CUA_SPAN_COMMAND='["python3", "/absolute/path/computer-use/workers/span_worker.py"]'
```

For a remote worker, use an operator-managed launcher executable as the array's first element. It must accept the model ID, launch the included worker, and forward stdin/stdout. The worker emits readiness followed by one JSON response per input line. It uses cached weights, CUDA, and four CPU threads. Logs belong on stderr. Provision the worker environment separately; this extraction does not pin a newly tested model environment or install one.

`FleetGeneric` defaults to the pre-existing `~/.local/share/fleet-cua-decider/select-fleet --fast jev`. Override `CUA_SELECTOR_COMMAND` with a JSON argv array for another installation. The command must implement the included cascade's JSON-lines protocol. Keep one process per task, close it when done, and do not share verification state across independent fixtures.

The copied `inference/cua-decider/setup.sh` is the original Fleet-specific optional installer. It retains original network/credential defaults and is not run automatically. Review the accompanying README for Fleet access, feedback semantics and pinned stock Cua dependencies. Qwen configuration and credentials remain runtime concerns in `decision_providers.py`; never commit values. Homelab service deployment remains owned by homelab-infra.

The live booking harness also requires the installed stock Cua Driver/jev-use checkout. It is retained for future integration validation, not exercised by the offline test command. Other benchmark references in historical documentation are provenance, not bundled executable dependencies.

## Julia-1 generic chooser

`generic_from_config()` loads the active profile (an explicit `CUA_GENERIC_PROVIDER` wins; with neither, the factory falls back to Jev). A clean install has no `runtime.json`, which resolves to `fleet`, so the out-of-the-box chooser is Jev (page content goes to the configured hosted services); `local-mac` (Julia-1, no hosted route) is selected explicitly with `python3 scripts/set_profile.py local-mac`, `{"profile":"local-mac"}` or `CUA_PROFILE=local-mac`, and a `runtime.json` that only names Julia-1 also resolves to it. `fleet` selects Jev with the configured Qwen escalation. Existing callers that explicitly construct `FleetGeneric()` deliberately remain Jev, but the local profile rejects that provider. The active replay entry point uses the factory; historical Jev comparison scripts remain fixed controls.

```sh
export CUA_GENERIC_PROVIDER=julia-1
export CUA_JULIA_COMMAND='["/absolute/path/worker-venv/bin/python", "/absolute/path/computer-use/workers/julia_worker.py", "/absolute/path/Julia-1-checkpoint"]'
```

The command is an argv array, not shell text. A remote launcher can forward JSON lines over SSH; choose `CUDA_VISIBLE_DEVICES` in that launcher. No host, GPU index, credentials, or service changes are embedded in the adapter. Keep existing Qwen workers on their assigned GPU.

Provision the `julia` package exposing `julia.inference.TransformerEngine`, compatible CUDA PyTorch and Transformers separately. The existing experiment used Transformers 5.0.0 and the reference engine; this is not a portable environment installer or an optimized FastEngine implementation. The worker takes a local checkpoint directory and verifies `model.safetensors` before model loading. Model: `SupersonicLabs/Julia-1`, revision `a85b127321d580d65176c89ced8273f305745d85`, SHA-256 `df853bf7fe424420011f3d0c47a05d7341aa9eefa7fb9f203ea4aada4ad95b72`. The adapter checks readiness identity too. Model code/weights remain external under their own terms.

```python
from providers import RemoteSpans, generic_from_config
from rollout import Strangler

spans = RemoteSpans()
try:
    generic = generic_from_config()
    try:
        policy = Strangler.from_config({'gliner2': spans, 'incumbent_jev': generic})
        selection = policy.decide(request, current_snapshot)
        # execute_bound with stored Driver arguments; independently observe afterward.
    finally:
        generic.close()
finally:
    spans.close()
```

`incumbent_jev` is a compatibility slot name, not proof of the actual model. Inspect `provider_outputs[].route/model` for attribution. Julia accepts at most 18 action candidates plus `reobserve` and `abstain` (20 total). It never truncates inputs: oversized/empty scopes return an explicit limit deferral without calling inference. The worker's strict tokenizer rejects option/context overflow (48-token options, 8192 total, 1024 head) rather than silently losing criteria. Re-scope from fresh evidence; do not split a global comparison into tournaments. Scores are uncalibrated, and no automatic Jev fallback is added. Keep one worker per task; 20-second transport timeouts close the worker. Remote launchers must terminate on stdin EOF/disconnect.

Julia does not read screenshots or extract spans. [Terminal perception](TERMINALS.md) uses a separate vision-capable endpoint. The saved Julia experiments and one successful paired Obsidian choice do not establish broad reliability.

## NuExtract candidate preparation

Set `CUA_PAGE_EXTRACTION=1` and `CUA_EXTRACT_URL` to your deployed `/v1/extract-page` endpoint. `generic_from_config()` wraps the preferred generic provider; only requests with an explicit `page_filter` invoke extraction. See [request shape, bounds and verification](PAGE-CANDIDATES.md). Model deployment and credentials remain external configuration.

### iOS switch ancestry

Mobile MCP 1.0.6 flattens the native hierarchy. For affected wide labeled iOS switches, the default local mobile backend reads a fresh complete hierarchy with pinned mobilecli 1.0.16 and binds only a unique, state-consistent actionable child. Custom mobile backends must explicitly supply a hierarchy reader; a local CLI is never silently attached to a remote or fake backend. Operators can configure `CUA_MOBILECLI_COMMAND` as a literal JSON argv prefix, for example `["/absolute/path/mobilecli"]`; the facade appends `dump ui --device <exact observed device>`. Reads have a timeout, a response-size acceptance limit and bounded tree traversal. The CLI output is buffered before the size check; this is not a streaming memory bound. Missing or malformed hierarchy refuses activation rather than inventing a coordinate offset.
