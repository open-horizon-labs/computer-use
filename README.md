# Computer-use capability dispatch

A companion to stock computer-use tools and skills. The stock driver observes and executes; this repository supplies typed request guidance, capability routing, evidence matching, bounded semantic recovery, and a CESS simulation loop.

The driving LLM describes intent and evidence requirements. Dispatcher code follows the sketch to choose providers. Models return evidence or an offered ID; the controller retains executable arguments, validates the current binding, and independently verifies progress.

## Multiple models, one request

The stock driver supplies current controls. The driving LLM describes the request and required evidence. **Dispatcher code chooses the route**, using rules in the CESS sketch; the skill teaches the LLM how to construct that request. There is no trained router in this version.

| Request / model | What the provider receives | What happens afterward | Current status |
|---|---|---|---|
| Exact control / no model | Unique current role/name or ID | Validate and bind the control | Implemented |
| Simple entities / GLiNER | Record text and simple entity labels | Match extracted values against explicit criteria | Contract tested; live adapter needs qualification |
| Described fields / GLiNER2 | Per-record text, field descriptions and types | Normalize, compare within the same record, apply caller ordering | Live span adapter and measured examples |
| Structured, relational or multilingual extraction / GLiNER2.5 | Scoped text and requested schema | Preserve grouping/relations before matching | Provisional routes; structured adapters need qualification |
| Bounded classification / Decide | Evidence and described categories | Map accepted class to a caller-authorized action | Contract tested; live adapter needs qualification |
| Semantic choice or recovery / Jev | Goal, current candidate descriptions, constraints and available evidence | Select an offered ID or defer | Live adapter |
| Escalation / Qwen | Goal and offered candidates via the bounded selector | Handle weak/failed Jev choices; verify after action | Existing selector integration |

For example: the LLM requests provider name, appointment duration and start time, with explicit predicates and ordering. GLiNER2 extracts those fields; code selects the matching record. If an extracted name has an uncertain boundary, Jev can recheck it. A selected ID never supplies arbitrary executable arguments. The driver executes the stored current binding and observes the result independently.

CESS preserves the sketch, accepted counterexamples and executable regression checks. A failure either calls for repairing code to existing policy or proposing a policy change. Tests alone do not authorize a new rule.

## Install the skill

This repository is private. Authenticate Git/GitHub CLI or SSH with an account that has access, then:

```sh
npx skills add open-horizon-labs/computer-use --skill cua-capability-dispatch
```

For global Codex use, append `--agent codex --global`. The [skills CLI](https://github.com/vercel-labs/skills#private-repositories) supports authenticated private repositories. Installation includes the skill's **[setup reference](skills/cua-capability-dispatch/references/setup.md)** and bundled sketch. It installs guidance, not GPU models or a running dispatcher.

## Set up the runtime

```sh
gh repo clone open-horizon-labs/computer-use
cd computer-use
export CUA_CAPABILITY_ROOT="$PWD"
python3 inference/cua-decider/capability-dispatch/simulation_gate.py
```

The offline check needs only Python 3.10+. For real inference, follow the [setup reference](skills/cua-capability-dispatch/references/setup.md): provision a cached GLiNER2 CUDA worker, configure `CUA_SPAN_COMMAND`, configure the Jev/Qwen selector with `CUA_SELECTOR_COMMAND` and runtime credential access, then connect the dispatcher to the stock driver. The active `described-span-match/en` route and measured inference recipe are documented in [WORKING-RECIPE.md](inference/cua-decider/capability-dispatch/WORKING-RECIPE.md). Installing the skill does not deploy services or modify the standalone Fleet selector.

## Jev API and endpoint setup

Get a TypeSafe API key through your [TypeSafe account](https://console.typesafe.ai) or administrator. Configure it separately from the Qwen fallback:

```sh
export TYPESAFE_API_KEY_FILE="$HOME/.config/computer-use/jev-api-key"
export TYPESAFE_BASE_URL='https://api.typesafe.ai'
export TYPESAFE_DEFAULT_MODEL='jev-latest'
```

The file must already contain your key. `TYPESAFE_API_KEY` is the direct-environment alternative. Jev's SDK calls `https://api.typesafe.ai/v1/systemone`; the base URL has **no `/v1` suffix**. Qwen instead uses `QWEN_BASE_URL` **with `/v1`**, plus its own `QWEN_API_KEY` or `QWEN_API_KEY_FILE`. Both providers need configuration for the cascade.

See [full key/endpoint setup and Jev-only smoke check](skills/cua-capability-dispatch/references/setup.md#jev-api-key-endpoint-and-model), including secret-file precedence and optional Fleet retrieval. Installing the skill does not create API accounts or credentials.

## Start here

- [Custom skill](skills/cua-capability-dispatch/SKILL.md): request construction and safe integration with stock tools.
- [Sketch S](inference/cua-decider/capability-dispatch/SKETCH.md): authorized routing and matching policy, including approved boundary recheck.
- [Counterexamples A](inference/cua-decider/capability-dispatch/COUNTEREXAMPLES.json): accepted failures and their authority.
- [Projection P](inference/cua-decider/capability-dispatch/dispatch.py): dispatch, matching, recovery and binding.
- [Decide precision experiments](experiments/decide-precision-2026-09-27/RESULTS.md): six epochs, label descriptions and reviewed hard negatives, with a paired Jev control.
- [Gradual specialist rollout](docs/SPECIALIST-ROLLOUT.md): shadow Jev, qualify a task contract, then propose selective takeover.
- [Salvage](docs/SALVAGE.md): what to retain, mistakes to avoid, next experiments.
- [Evidence](inference/cua-decider/capability-dispatch/simulation/JEV-COMPARISON.md): bounded comparison, not a general CUA benchmark.

## Offline validation

Python 3.10+; no models, credentials, GPU, browser or third-party packages needed:

```sh
python3 inference/cua-decider/capability-dispatch/simulation_gate.py
python3 -m unittest discover -s inference/cua-decider -p 'test_*.py'
```

The simulation gate checks 28 scenarios, 40 metamorphic variants, 20 unit/contract tests, 35 recorded decisions and seven deliberately wrong repairs. It writes results into the simulation directory. Exact-output checks and capable-model sketch review are separate; retained review is a historical self-review, not fresh independent certification.

## Integration

The installed skill is self-contained guidance; keep a separate runtime checkout for execution. Its bundled sketch is synchronized with `python3 scripts/sync_skill_references.py`; `--check` detects drift. It supplements the stock skill and does not install or replace the driver.

The Python interface is `Engine(providers).decide(request, current_snapshot)`, followed by `execute_bound(request, selection, fresh_snapshot, execute_callback)` only when authorized. `execute_callback` is the stock driver's operation adapter. Observe again to verify the intended postcondition. See the [request example](inference/cua-decider/capability-dispatch/booking-request.json) and [controlled caller examples](inference/cua-decider/capability-dispatch/simulation.py). This is currently a Python component, not a deployed HTTP API.

The CESS strangler wrapper is `Strangler.from_config(providers)`. Its tracked [rollout record](inference/cua-decider/capability-dispatch/ROLLOUT.json) defaults to `shadow`: it runs Jev and GLiNER2 in parallel for the described English span-matching contract, returns Jev, and emits sanitized disagreement evidence for independent outcome checking and CESS review. The explicit `stage='active'` override returns the specialist decision only when the record names an accepted CESS CE, an existing qualification report, a full checkpoint digest, and the authorizing user. GLiNER2 defers and Jev handles one recovery call under S4.3. `Strangler` never executes; continue to use the current `execute_bound` and stock Driver verification path.

Providers are injected callables `(step, request) -> grounded evidence or offered choice`. The included live adapters cover GLiNER2 spans and the installed Jev→Qwen selector. Original GLiNER, structured GLiNER2.5 and Decide routes have controlled contract coverage but require qualified live adapters for their respective roles. The span adapter's GLiNER2.5 option is not a structured-record/relationship adapter.

## Live inference configuration

[Provider setup](docs/PROVIDERS.md) explains explicit worker and selector commands. Live inference and live desktop testing are separate from the offline gate. No services are started by the gate.

Historical files retain their original experiment paths, local hardware descriptions, and pre-approval wording where relevant. S4.4 and the accepted archive carry current policy. The original `inference/` layout is retained so captured replays remain resolvable without the homelab repository. Only required fixture code and evidence were extracted; training datasets, deployment infrastructure and credentials stay outside this repo.

This repository is private under `open-horizon-labs`. No upstream license is inferred for third-party tools or model weights; they remain external dependencies under their own terms.
