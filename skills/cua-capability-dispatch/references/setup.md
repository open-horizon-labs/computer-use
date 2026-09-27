# Setup

The skill installs guidance and references. Running the dispatcher also requires a checkout of the private `open-horizon-labs/computer-use` repository. It does not install models or replace stock computer-use tools.

## 1. Install the skill

Requirements: Node.js/npm and Git authentication with access to the private repository. For GitHub CLI users, authenticate with `gh auth login` if needed.

```sh
npx skills add open-horizon-labs/computer-use --skill cua-capability-dispatch
```

For a global Codex installation:

```sh
npx skills add open-horizon-labs/computer-use --skill cua-capability-dispatch --agent codex --global
```

The [skills CLI](https://github.com/vercel-labs/skills#private-repositories) uses existing Git/GitHub CLI or SSH authentication. A private repository remains accessible only to authorized users. No token belongs in skill files.

## 2. Get the runtime and run offline checks

Choose a durable checkout directory:

```sh
gh repo clone open-horizon-labs/computer-use
cd computer-use
export CUA_CAPABILITY_ROOT="$PWD"
python3 inference/cua-decider/capability-dispatch/simulation_gate.py
python3 -m unittest discover -s inference/cua-decider -p 'test_*.py'
```

Python 3.10+ is sufficient for these offline checks. They do not require models, credentials, a browser or third-party Python packages. `CUA_CAPABILITY_ROOT` is a location convention for the agent/integration, not an environment variable consumed by Engine. Set it to the actual checkout in future sessions or supply the checkout path explicitly.

The installed skill includes a sketch snapshot in `references/sketch.md`. When developing or running the checkout, its `inference/cua-decider/capability-dispatch/SKETCH.md` is authoritative. Update skill and checkout together when policy changes.

## 3. Configure providers

Start with injected providers for simulations. For real inference, read `docs/PROVIDERS.md` in the checkout.

- **GLiNER2 spans:** provision a CUDA Python environment containing compatible `torch` and `gliner2`, and pre-cache the selected checkpoint (`fastino/gliner2-base-v1`). The bundled worker uses offline loading; it will not fetch missing weights. Choose the appropriate PyTorch build for the worker's GPU. A fully pinned, portable GPU environment is not yet supplied.
- **Jev/Qwen:** use the existing bounded selector installation, or review and run `bash inference/cua-decider/setup.sh` on the desktop. That optional installer needs `git`, `uv`, network access and Python 3.12 provisioning. It installs pinned Cua/SDK dependencies and preserves Fleet-specific network defaults; configure your own endpoints and credential access before live use. See `inference/cua-decider/README.md#reusable-bounded-selector` in the checkout.

Example with a provisioned local CUDA environment (replace absolute paths):

```sh
export CUA_SPAN_COMMAND='["/absolute/path/worker-venv/bin/python", "/absolute/path/computer-use/workers/span_worker.py"]'
export CUA_SELECTOR_COMMAND='["/absolute/path/select-fleet", "--fast", "jev"]'
```

These are JSON argv arrays, not shell command strings. The span adapter appends the model ID. For a remote GPU, point the array at a launcher that forwards stdin/stdout and accepts that final model argument. The Mac can remain the controller while the worker runs remotely. Startup metadata and responses use stdout; diagnostics use stderr.

The included selector supports runtime `TYPESAFE_API_KEY`/`QWEN_API_KEY`, credential files, or the documented Fleet SSH retrieval. Prefer configured secret retrieval; never put credentials in observations, committed files or logs. Configure `QWEN_BASE_URL`, `QWEN_MODEL`, and `CUA_QWEN_THINKING` for your backend when applicable.

Original GLiNER, structured/relational GLiNER2.5 and Decide are dispatch contracts requiring qualified live adapters, not automatically installed services. Do not infer complete multi-model deployment from a successful skill install.

### Jev: API key, endpoint and model

Obtain a Jev API key through your [TypeSafe account](https://console.typesafe.ai) or organization administrator. This is a TypeSafe key, not an OpenAI or Qwen key. The hosted API uses bearer authentication and `POST /v1/systemone`; see the [official API reference](https://api.typesafe.ai/docs).

| Setting | Value / purpose |
|---|---|
| `TYPESAFE_API_KEY` | Jev API key supplied at runtime |
| `TYPESAFE_API_KEY_FILE` | Alternative: absolute path to a file containing only the key |
| `TYPESAFE_BASE_URL` | `https://api.typesafe.ai` (SDK default; no `/v1` suffix) |
| `TYPESAFE_DEFAULT_MODEL` | `jev-latest` (SDK default); use an available model ID to pin a version |

The SDK appends `/v1/systemone`. Do not set the base URL to the full endpoint or to your local Qwen server. There is no separate Jev “endpoint key”: the TypeSafe API key authenticates requests to this endpoint. The adapter checks the direct key first, then the key file, then optional Fleet SSH retrieval.

Recommended file-based configuration (replace the path with your existing secret file):

```sh
export TYPESAFE_API_KEY_FILE="$HOME/.config/computer-use/jev-api-key"
export TYPESAFE_BASE_URL='https://api.typesafe.ai'
export TYPESAFE_DEFAULT_MODEL='jev-latest'
```

Store only the key in that file, outside the checkout, with permissions limited to your user (`chmod 600`). Alternatively, export `TYPESAFE_API_KEY` from your secret manager into the process environment. The adapter reads the file; the SDK itself does not implement the `_FILE` convention.

After installing the selector dependencies, test Jev directly from the runtime checkout:

```sh
"$HOME/.local/share/fleet-cua-decider/.venv/bin/python" scripts/check_jev.py
```

This makes one small hosted inference call, prints only the offered choice and confidence, and never invokes Qwen or clicks anything. It uses the same credential resolver as the adapter. If authentication fails, check that the key belongs to TypeSafe and that the account has API access; if a pinned model fails, consult `GET /v1/models` in the API reference. The default alias can change versions over time.

### Qwen escalation: separate endpoint and key

The shipped cascade can escalate even its first Jev request. Configure Qwen before using the cascade; the Jev-only check above does not require it.

```sh
export QWEN_BASE_URL='http://YOUR-QWEN-HOST:8080/v1'
export QWEN_API_KEY_FILE="$HOME/.config/computer-use/qwen-api-key"
export QWEN_MODEL='YOUR-SERVED-MODEL-ID'
export CUA_QWEN_THINKING='none'
```

`QWEN_BASE_URL` **includes `/v1`**; the adapter appends `/chat/completions`. `QWEN_API_KEY` is the direct-environment alternative to the file. This key belongs to your Qwen gateway and is independent of the hosted Jev key. The backend must accept this adapter's chat-completion and thinking parameters. Replace both example host and model ID with actual service values.

### Fleet credential retrieval (optional)

Existing Fleet users can omit direct keys/files and set `TYPESAFE_CONNECT_SSH` to the authorized SSH host that can run `op read 'op://Fleet/Typesafe.ai Jev API Key/credential'`. Qwen's `QWEN_SECRET_SSH` host must expose the documented `~/.codex/secrets/fleet-inference-key`. The `select-fleet` launcher supplies the original homelab host defaults; external users should supply direct keys/files or their own credential integration. Secrets are captured internally, never printed. If you already exported a direct key, it takes precedence over a file or SSH lookup.

## 4. Connect the stock driver

Use the stock computer-use skill and driver to observe the actual desktop. Build the typed request from the fresh observation. Configure `RemoteSpans` with a cached `fastino/gliner2-base-v1` CUDA worker and `FleetGeneric` with the Jev/Qwen selector. Import `Strangler` from `inference/cua-decider/capability-dispatch/rollout.py` and `execute_bound` from `dispatch.py`; load `ROLLOUT.json` so only the qualified described-English-span contract uses GLiNER2, with Jev as one recovery call. See the [working recipe](../../../inference/cua-decider/capability-dispatch/WORKING-RECIPE.md). The examples in `simulation.py` show request shapes; `run_booking.py` is a task-specific integration example, not a general API server.

Call `Strangler.from_config(providers).decide(request, current_snapshot)`. Before any action, obtain a current snapshot and pass the unchanged request and selection through `execute_bound` with a driver callback. Independently verify the result. Keep one generic selector process per task; close it after the task and do not share feedback state across independent tasks.

The controller must bind and verify: installing this skill alone does not cause tool calls to use the dispatcher. A one-call hosted API is not deployed by this repository.
