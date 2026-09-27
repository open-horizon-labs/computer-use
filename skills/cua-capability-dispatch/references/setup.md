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

## 4. Connect the stock driver

Use the stock computer-use skill and driver to observe the actual desktop. Build the typed request from the fresh observation. Import `Engine` and `execute_bound` from `inference/cua-decider/capability-dispatch/dispatch.py`; inject configured providers. The examples in `simulation.py` show request shapes; `run_booking.py` is a task-specific integration example, not a general API server.

Call `Engine.decide(request, current_snapshot)`. Before any action, obtain a current snapshot and pass the unchanged request and selection through `execute_bound` with a driver callback. Independently verify the result. Keep one generic selector process per task; close it after the task and do not share feedback state across independent tasks.

The controller must bind and verify: installing this skill alone does not cause tool calls to use the dispatcher. A one-call hosted API is not deployed by this repository.
