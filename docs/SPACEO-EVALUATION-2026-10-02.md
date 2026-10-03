# SpaceO backend evaluation — 2026-10-02

Evaluated source: [b3e40c20781f2374f062291fb21867ba8212f4e1](https://github.com/ParthJadhav/SpaceO/tree/b3e40c20781f2374f062291fb21867ba8212f4e1). Static source inspection only: no installation, display creation, app launch, or runtime qualification. The checkout was read in /tmp; no upstream code was copied into our runtime.

## Decision

Retain our existing display backend for the current optional Chromium route. SpaceO is a credible candidate for a later session/display provider, particularly if multiple concurrent agents or a human Viewer becomes an actual requirement. Its broader input surface is not a drop-in replacement for our observation bindings. Adopt the lifecycle and evidence lessons now; do not promote the backend from static inspection.

## Contract comparison

| Contract | Pinned source evidence | Integration consequence |
|---|---|---|
| Headless display | Sources/SpaceOKit/Stage.swift creates and retains private virtual-display backing | Same underlying macOS dependency; no independent security boundary |
| Ownership | Sources/SpaceOMCP/MCPServer.swift stores connection-local controller leases and rejects ambiguous implicit sessions | Bind one lease/session to our task; never infer ownership from app name alone |
| Native element binding | Sources/SpaceOKit/AgentSession.swift element(at:for:) delegates to the snapshot cache with explicit window and live process identity | Potentially compatible, but preserve our independent fresh read before delivery |
| Browser element binding | Sources/SpaceOKit/ChromiumBridge.swift elementCenter(index:) evaluates the nth current interactive element; SessionManager+Ergonomics.swift explicitly says wN indices use current page order | A stale wN ordinal can describe a different element after DOM changes. An adapter must revalidate semantic identity/content and exact page before delivery; do not translate saved look handles directly to ordinals |
| Snapshot preflight | Sources/SpaceOKit/SessionManager.swift checks request.snapshotID against the native snapshot generation when supplied | A native snapshot token is not proof of unchanged DOM element identity |
| Isolation evidence | Sources/SpaceOKit/IsolationSnapshot.swift separates observed, inferred, unknown coverage and reports missing input-route evidence | Carry coverage into our reports; never reduce partial coverage to an all-clear |
| Lifecycle containment | Sources/SpaceOKit/Stage.swift and docs/DISPLAY_SAFETY.md use latches, allocation ownership, reuse, creation budgets and health admission | Useful design evidence; specific thresholds are policy choices, not verified safe limits for our runtime |
| Supported apps | README excludes managed Electron apps, while AppLauncher.swift contains Electron controller/semantic adapter paths | Pin source and release contracts separately; implementation presence does not prove released support |

## Blocking evidence

The pinned README says the WindowServer/ColorSync freeze remains unresolved and release 1.0.5 has no new live qualification. Its safeguards cannot cancel calls already inside macOS. More code and a signed release do not establish an improvement in task completion, focus isolation, or host stability relative to our backend.

## Qualification plan

Use a reserved Mac with an eligible logged-in desktop and known recovery access. Do not run this qualification on the user's working desktop. Compare pinned SpaceO and our candidate on the same Chromium tasks, display geometry, OS build, and installed Driver; keep permission/setup failures distinct from execution results.

1. Lifecycle: create once, reuse across tasks, verify placement and independent display absence after healthy cleanup. Inject uncertain startup and teardown in fakes first. Live timeout experiments stop on unknown state; no repeated creation, automatic owner kill, or preference deletion. Record host health and any WindowServer/ColorSync symptoms separately from task success.
2. Binding: change DOM order between observation and action; open a second page; replace the browser process or window; move/resize a window. Every stale target must refuse or freshly rebind to the intended semantic target. An adapter that still clicks the old ordinal fails qualification.
3. Isolation: keep a second user app active and deliberately switch it during launch. Record frontmost app, cursor and active Space where observable; keyboard and text-route getters remain unknown unless independently established. A successful input receipt cannot prove full attention isolation.
4. Outcomes: complete the captured booking and form tasks with independently observed final state. Compare completion, wall time and total agent-visible tool calls on the same prompts; preserve look/do and its measured budgets.
5. Recovery: pause, reconnect and lose the session lease; stale sessions cannot authorize mutations. Verify cleanup does not touch user windows or profiles and that human intervention preserves target/session identity.

Promotion requires independent review of these results, a CE for any changed facade contract/call budget, and a demonstrated practical benefit without reduced completion. This evaluation is complete as a source audit; runtime backend qualification remains unperformed.
