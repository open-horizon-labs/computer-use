# Computer use with Cua Driver and a bounded model cascade

For reusable computer use, follow [the selector pattern](#reusable-bounded-selector):
Cua Driver observes and executes; **Decider or Jev selects an action, with Qwen
as fallback**. The setup and `verify` command below also provide a standalone
Decider form smoke test.

Decider runs on the homelab RTX 3060 Ti. Cua Driver runs on the desktop being
controlled, including a Mac. The desktop sends compact text/DOM observations
and described candidate actions to `http://192.168.1.104:8010/v1/systemone`.
The standalone Decider smoke test needs no TypeSafe credential, local model
download, or second GPU model. The cascade additionally uses the existing Qwen
service; selecting hosted Jev requires its Fleet credential.

The adapter retains the upstream `jev-use` loop: fresh browser observations,
immutable candidate actions, snapshot-bound references, explicit `reobserve`
and `abstain`, and an independent result check. Decider selects an ID; the model
cannot invent tool names or arguments. A malformed or incomplete probability
vector is rejected before execution. There is no implicit action retry.

## Current service compatibility

`/v1/systemone` now serves optimized **Qwen 27B for text and screenshots**.
The dedicated 9B services are stopped and disabled. The 27B evaluates one output
position with reasoning and drafting disabled; images use its own vision encoder.
See [SystemOne usage and deployment](../systemone/README.md).

Responses include an allowed choice and separately labeled raw `scores`;
`confidence` and `probabilities` are null. The adapter accepts this verified
response format without manufacturing confidence. The existing confidence-gated
cascade consequently escalates these choices. Call SystemOne directly when you
want bounded non-reasoning selection, and independently verify the action.
Text and image choices currently support 2–26 candidates. Historical setup and
benchmark sections below describe earlier backends; query `/health` for the live one.

## Setup from a fleet-connected desktop

Run these commands on the **device whose desktop you want to control**. Running
Driver inside an SSH session, Coder container, or fleet worker controls that
machine's available desktop, not the Mac displaying the terminal. A headless
worker can call Decider but needs a real/virtual desktop for Driver actions.

### 1. Reach Decider

The Fleet tailnet is `open-horizon-labs.org.github` (`tail434280.ts.net`). Decider
currently listens on the Columbus LAN address, not a separate Fleet hostname.
Fleet does not advertise that LAN subnet. Being connected to Fleet therefore
does not by itself make `192.168.1.104` reachable.

**On the Columbus LAN (or with an existing approved route):**

```bash
export DECIDER_URL=http://192.168.1.104:8010
curl --fail "$DECIDER_URL/health"
```

**From a remote Fleet device with authorized operator SSH access:** keep this
command running in one terminal:

```bash
ssh -N -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -L 127.0.0.1:18010:192.168.1.104:8010 \
  root@9950x-columbus.tail434280.ts.net
```

Use your existing authorized SSH identity/configuration. If an explicit key is
needed, add `-i /path/to/your/authorized/key`; do not put a private key in the
repository. Confirm the host key through your existing trusted Fleet setup.
This route was tested over `100.105.185.104`, the host's current Fleet address.
Fleet membership does **not** grant root SSH rights. If you lack that access,
use an already authorized LAN-reachable workspace/bastion account as the SSH
destination; verify that account can reach the Decider LAN endpoint first. Do
not enroll the Mac in the personal tailnet just to follow this guide.

In the terminal where you will run the client:

```bash
export DECIDER_URL=http://127.0.0.1:18010
export NO_PROXY="${NO_PROXY:+$NO_PROXY,}127.0.0.1,localhost"
curl --fail "$DECIDER_URL/health"
```

Expected fields are `"ok":true`, `"model":"decider-2b-v10"`, `"backend":"gguf"`,
and `"precision":"f16"`. Keep the SSH tunnel running throughout the proof.
It listens only on your device's loopback address. There is no new public port,
Tailscale Serve/Funnel configuration, or LAN subnet advertisement.

The normal tunnel command assumes OS-level Tailscale connectivity. Userspace
Fleet runners may instead have only a local HTTP proxy; that proxy can carry
HTTP but cannot make ordinary SSH work. Use the runner's configured SOCKS5 SSH
route or run this desktop setup on a normal Tailscale-connected desktop. See
[Fleet networking](../../network/fleet-tailnet.md).

### 2. Install the desktop client

Use an unlocked desktop with a supported Chromium browser. On macOS, use a
signed browser such as Google Chrome. Prerequisites are `git` and
[uv](https://docs.astral.sh/uv/getting-started/installation/). Obtain this repository
with your existing GitHub access, then run from its root:

```bash
git clone https://github.com/open-horizon-labs/homelab-infra.git
cd homelab-infra
bash inference/cua-decider/setup.sh
~/.local/share/fleet-cua-decider/.venv/bin/cua-driver doctor
```

If you already have this checkout, skip the clone and change into it. The setup
provisions Python 3.12 through uv, pins the upstream example source, and installs
Driver 0.28.2 and its dependencies. `CUA_DECIDER_DIR` overrides the client directory.
When `XDG_DATA_HOME` is set, the default is `$XDG_DATA_HOME/fleet-cua-decider`;
adjust the example launcher path accordingly. No inference packages/model weights
are installed on this desktop, and no TypeSafe API key is requested.

On macOS, the Python package alone is insufficient: install the matching signed
app bundle as well. `doctor` can pass even when `/Applications/CuaDriver.app`
is missing; it does not verify macOS desktop permission readiness.

```bash
curl -fsSL https://cua.ai/driver/install.sh -o /tmp/cua-driver-install.sh
CUA_DRIVER_RS_VERSION=0.28.2 bash /tmp/cua-driver-install.sh
open -n -g -a CuaDriver --args serve
~/.local/bin/cua-driver permissions grant
~/.local/bin/cua-driver permissions status
```

In System Settings → Privacy & Security, enable **CuaDriver** under both
**Accessibility** and **Screen & System Audio Recording**. Opening the settings
panel alone does not grant access. Accept a quit/reopen request if macOS shows
one, and rerun the launch/grant commands if only one permission was requested.
On macOS 27, the Accessibility permission appears under **Device Control and
Data Access**. If both toggles are on but Driver still reports
`permissions_pending`, quit and relaunch CuaDriver so the grants take effect.
Confirm both grants through the running Driver before proceeding. An `unknown`
status with `daemon_running: false` is not a successful readiness check.
Run from the unlocked interactive desktop session. See the
[official Driver installation guide](https://cua.ai/docs/how-to-guides/driver/install).
On Linux, use an accessible X11/Wayland desktop and supported system browser;
Driver must run as that desktop's user. The test container's Xvfb/Openbox setup
is recorded separately in the benchmark, not required on an existing desktop.

### 3. Prove the complete loop

Use the same terminal with `DECIDER_URL` set in step 1:

```bash
~/.local/share/fleet-cua-decider/verify --output-dir proof-decider
```

Use a new output directory for every attempt. The verifier checks model readiness,
starts a loopback-only form, launches a Driver-owned isolated browser profile,
asks Decider to choose each action, and independently reads the submitted value.
The fixture closes on completion or failure. The run is bounded to 180 seconds
and four decisions; it never attaches to your existing browser profile.

Success requires all three:

- `summary.json` contains `"complete": true` and `"returncode": 0`.
- `summary.json`'s `state.submitted` exactly equals its generated `token`.
- `events.jsonl` ends in a verified outcome. A `reobserve` before submit is valid.

`runner.log` contains diagnostics, and `events.jsonl` contains actual model
choices and probabilities. No hosted TypeSafe request is made. The existing
LAN API has no additional application authentication; access is via your LAN
or the authorized SSH route above.

### Troubleshooting and cleanup

| Symptom | Check |
|---|---|
| LAN address times out on a Fleet-only device | Use the tunnel; Fleet does not route the LAN subnet. |
| SSH permission denied | Use an authorized SSH account/key; tailnet membership alone is insufficient. |
| `Address already in use` for 18010 | Pick another local port and update `DECIDER_URL` to match. |
| Health connection refused | Check the tunnel and model service; wait for health before retrying with a new proof directory. |
| `open -n -g -a CuaDriver` fails / MCP connection closes | Install the signed macOS app bundle using step 2; the Python wheel and a passing `doctor` are insufficient. |
| Driver permissions/display failure | Run `cua-driver doctor` as the unlocked desktop user; grant macOS permissions there. |
| Browser launch refused | Use a supported signed/system browser, not an arbitrary user-installed executable. |
| `abstained`, `budget_exhausted`, or `complete:false` | Read the recorded choices/log. Do not count a click response alone as success. |

After the proof, stop the SSH tunnel with Ctrl-C. The client remains installed;
no desktop background service is enabled. The verifier and Driver own their
fixture/session lifecycle. Keep proof files if you need the audit trail.

## What is proven

The real Driver 0.28.2, system Chrome, and live F16 Decider passed the isolated
Linux/Xvfb form task: type the token, submit, verify the exact HTTP state.
The documented installer and its generated verifier also passed on that Linux
desktop. See [recorded evidence](../benchmarks/decider-cua-2026-09-23/README.md).
The Mac procedure was attempted on macOS 27.0 (Apple Silicon) on 2026-09-23.
The complete Mac loop passed after installing the signed app bundle, enabling
its permissions, and restarting Driver. Decider selected typing and submission
in two decisions (89.51 ms and 69.75 ms); the independent HTTP check confirmed
the exact token and the verifier returned `complete: true`, `returncode: 0`. See [Mac evidence](../benchmarks/decider-cua-macos-2026-09-23/README.md).

This is a working browser integration, not a general desktop agent. The included
candidate builder is specific to the fixture. For another application, an agent
must supply the goal, compact observation, bounded action candidates, and an
independent success check; `decider_adapter.choose` is the reusable provider
boundary. Decider 2B here is text-only. Screenshot perception, arbitrary coordinate
grounding, and broad multi-application reliability were not tested.

## Development

```bash
python3 -m unittest discover -s inference/cua-decider -p 'test_*.py'
```

`run_fixture.py` adapts the pinned upstream runner without changing Driver. It
also forwards an explicit allowlist of desktop session variables because the
MCP SDK's default environment omits Linux DISPLAY/D-Bus settings. It does not
forward unrelated credentials or relax Driver action validation.

## Reusable bounded selector

`setup.sh` now also installs **select** and **select-fleet**. These are JSON-lines
selection interfaces: they return one of the caller's action IDs and never invent
or execute tools. Keep one process per task to retain routing state. Your Driver
adapter owns fresh observations, immutable action arguments, execution, and
independent verification. This is a reusable selection component, not a general
website agent with automatic field discovery or success detection.

### Observe → select → execute → verify

1. Read a fresh semantic browser snapshot or native accessibility tree with Cua
   Driver. Use the browser debugger route when available; use native controls for
   desktop UI. The models here receive text observations, not screenshots.
2. Build a compact goal/observation and 2–32 candidate IDs with descriptions,
   including `reobserve` and `abstain`. Keep the current snapshot's exact tool
   arguments in your controller, keyed by those IDs.
3. Send one JSON line to the running `select-fleet` process and read one response.
   The configured fast model gets the first attempt. A confident allowed action
   returns immediately; otherwise the selector asks Qwen before returning.
4. Handle errors and control decisions before execution. For an ordinary action,
   validate that its snapshot is still current and execute its stored arguments
   through Driver. Qwen's choice needs the same validation as the fast model's.
5. Observe again and independently check the intended result. Send the next
   request to the **same process**, with feedback as described below. Stop once
   the goal is verified, and bound the overall task's steps/time in your controller.

The default is **one cheap attempt, then Qwen**. `--max-fast-attempts 3` allows
up to three cheap attempts only with changed evidence and explicit `safe_retry`
feedback; low confidence already escalates immediately. The selector does not
blindly repeat a click or roll back its effects. For an uncertain side effect,
reconcile the actual state before proposing another action.

### What the booking results show

| Standalone selector | Correct booking tasks |
|---|---:|
| Decider | 2/20 |
| Hosted Jev | 13/20 |
| Qwen | 20/20 |

**Qwen succeeded on the harder booking fixture.** The installed Jev → Qwen
controller has a live two-request escalation check, but has **not** been run
through the complete booking benchmark. Do not interpret Qwen's standalone
20/20 as a measured Jev → Qwen cascade score. These are small, single-run fixture
results with provider-specific prompts, not general reliability guarantees.
See [results and limitations](../benchmarks/cua-cascade-2026-09-23/README.md).

### Run the selector

On this Mac, `select-fleet` uses the existing `homelab-personal-assembler` SSH
alias to read `op://Fleet/Typesafe.ai Jev API Key/credential` through Connect when
Jev is selected. It reads the existing Qwen credential through
`homelab-personal-stock`. Secrets are cached only in the selector process's memory;
they are not printed or copied to disk. SSH must already be authorized.
Override the aliases with `TYPESAFE_CONNECT_SSH` and `QWEN_SECRET_SSH` if needed.

```sh
~/.local/share/fleet-cua-decider/select-fleet --fast jev <<'JSON'
{"goal":"Choose the earliest available appointment with Alex after 2 PM.","observation":"Alex has appointments at 2:05 PM and 2:30 PM.","candidates":{"early":"Book Alex 2:05 PM","late":"Book Alex 2:30 PM","reobserve":"Refresh the page","abstain":"Stop"}}
JSON
```

This one-request example exits after its response. For a multi-step task, keep
the command running with stdin/stdout pipes and exchange one line per decision;
starting a new process for every step would discard the retry/escalation state.

Use `--fast decider` for the local model (the default), or `--fast jev` for hosted
TypeSafe/Jev. `--threshold 0.95` and `--max-fast-attempts 1` are the initial defaults.
**0.95 is an experimental starting threshold, not a calibrated safety guarantee.**
Jev's reported confidence is distinct from its candidate probability; the
selector does not pretend they are the same quantity.

The response includes `choice`, `route`, `reason`, `requires_verification`, and
provider timing/choice traces. A malformed input or failed fallback returns
`action_authorized: false` and an error class, without raw upstream error text.
Treat `abstain` and `reobserve` as control decisions, never as clicks. No selector
response proves that an action achieved its goal.

For subsequent requests in the same process, provide `feedback`:

- `verified_progress`: your independent check confirmed the intended progress;
  a changed observation resets the cheap-model budget.
- `safe_retry`: you verified a reversible/no-effect failure and have a changed
  observation; another cheap attempt is allowed only within the configured budget.
- `no_progress`, `failed`, `uncertain`, or omitted feedback after the first
  request: escalate to Qwen.

An unchanged semantic observation and candidate map escalates even if the caller
claims progress. Keep candidate IDs stable across equivalent observations and
exclude transient timestamps/snapshot IDs from the semantic observation. Bind
returned IDs to the current snapshot's immutable execution arguments separately.
Escalation persists until verified progress. Low confidence, abstention,
reobservation requests, malformed fast-model output, and fast-provider errors also
escalate. Provider HTTP calls are not silently retried. If Qwen fails, no action
is authorized; escalation does not mean an uncertain prior action can be repeated.

For non-Fleet callers, use `select` and provide `QWEN_API_KEY` or
`QWEN_API_KEY_FILE`; hosted Jev additionally needs `TYPESAFE_API_KEY` or
`TYPESAFE_API_KEY_FILE`. Optional `QWEN_BASE_URL`, `QWEN_MODEL`, and `DECIDER_URL`
override the endpoints. Qwen also requires network access to its LAN endpoint
(default `http://192.168.1.104:8080/v1`); SSH credential access alone does not
provide that route. If using an authorized SSH tunnel, forward port 8080 as well
and set `QWEN_BASE_URL` to the loopback URL. Only choose Jev for observations you intend to send to
TypeSafe; the local Decider/Qwen path remains available.

`select-fleet` loads `~/.local/share/fleet-cua-decider/cua.env` on each new
selector process. The installer creates it with `CUA_QWEN_THINKING=none` and
preserves it on upgrades. Set it to `low` to allow brief reasoning, or use
`medium`/`xhigh` for higher effort. A one-run environment override takes
precedence, for example `CUA_QWEN_THINKING=low ~/.local/share/fleet-cua-decider/select-fleet --fast jev`.
This setting affects only Cua's Qwen fallback; other clients retain the
inference server's global default. Existing selector processes must be
restarted to read a changed file.

Python callers can import `Cascade` from `cascade.py` and call
`select(goal, observation, candidates, feedback=..., history=...)`. The class
accepts injected fast/fallback callables for other providers and deterministic
tests. `python3 -m unittest discover -s inference/cua-decider -p 'test_*.py'`
checks the routing boundary, including fail-closed fallback and bounded retry.

Live Jev results and installed CLI escalation evidence are recorded in
[the cascade experiment](../benchmarks/cua-cascade-2026-09-23/README.md).
