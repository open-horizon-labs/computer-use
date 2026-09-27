# Computer-use capability dispatch

A companion to stock computer-use tools and skills. The stock driver observes and executes; this repository supplies typed request guidance, capability routing, evidence matching, bounded semantic recovery, and a CESS simulation loop.

The driving LLM describes intent and evidence requirements. Dispatcher code follows the sketch to choose providers. Models return evidence or an offered ID; the controller retains executable arguments, validates the current binding, and independently verifies progress.

## Start here

- [Custom skill](skills/cua-capability-dispatch/SKILL.md): request construction and safe integration with stock tools.
- [Sketch S](inference/cua-decider/capability-dispatch/SKETCH.md): authorized routing and matching policy, including approved boundary recheck.
- [Counterexamples A](inference/cua-decider/capability-dispatch/COUNTEREXAMPLES.json): accepted failures and their authority.
- [Projection P](inference/cua-decider/capability-dispatch/dispatch.py): dispatch, matching, recovery and binding.
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

Use the skill in place from this checkout, or symlink its folder into your tool's skills directory. Keep the repository available: the skill's relative links intentionally reference the implementation and authoritative sketch here. It supplements the stock skill; it does not install or replace the driver.

The Python interface is `Engine(providers).decide(request, current_snapshot)`, followed by `execute_bound(request, selection, fresh_snapshot, execute_callback)` only when authorized. `execute_callback` is the stock driver's operation adapter. Observe again to verify the intended postcondition. See the [request example](inference/cua-decider/capability-dispatch/booking-request.json) and [controlled caller examples](inference/cua-decider/capability-dispatch/simulation.py). This is currently a Python component, not a deployed HTTP API.

Providers are injected callables `(step, request) -> grounded evidence or offered choice`. The included live adapters cover GLiNER2 spans and the installed Jev→Qwen selector. Original GLiNER, structured GLiNER2.5 and Decide routes have controlled contract coverage but require qualified live adapters for their respective roles. The span adapter's GLiNER2.5 option is not a structured-record/relationship adapter.

## Live inference configuration

[Provider setup](docs/PROVIDERS.md) explains explicit worker and selector commands. Live inference and live desktop testing are separate from the offline gate. No services are started by the gate.

Historical files retain their original experiment paths, local hardware descriptions, and pre-approval wording where relevant. S4.4 and the accepted archive carry current policy. The original `inference/` layout is retained so captured replays remain resolvable without the homelab repository. Only required fixture code and evidence were extracted; training datasets, deployment infrastructure and credentials stay outside this repo.

This extraction is a local repository. No upstream license is inferred for third-party tools or model weights; they remain external dependencies under their own terms.
