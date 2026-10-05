# Historical comparison — Cua Driver 0.31.0

Superseded for current selection by the [latest-candidate rerun](ARC-CUA-EMPIRICAL-COMPARISON-2026-10-05.md). The original observations below remain historical evidence; their speed ratios do not describe the latest Cua release.

# arc-cua — empirical comparison and salvage

## Decision

**Default selection follow-up:** The user selected arc as the default after this comparison. The skill now prefers the connected arc standalone driver for macOS app/window work, with native fallback and the controller retaining record matching and verification. The tested revision is installed in a durable local environment and registered for Codex and Claude Code. Installed skill copies were synchronized and independently reviewed; this updates the prior opt-in recommendation below. New MCP connections require client reconnection. The display fault remains preserved.

arc-cua earns consideration as an opt-in native macOS driver selected by our routing skill, especially for background AX controls and embedded web forms. It demonstrated a substantial speed advantage over the installed Cua Driver and stronger refusal of changed controls and modal state. Keep the controller's record matching and independent outcome checks. Do not put the broad native facade back into the optional OH adapter, replace guest Spaces, or adopt the decision-model executor by default.

The live work requested after the source evaluation is complete at this bounded scope. Display-lifecycle qualification, Electron parity, real authenticated application flows and decision-model accuracy remain outside the evidence. The existing display fault prevented virtual-display trials; it was preserved, not bypassed.

## What ran

On this Mac, macOS 27.0.1: arc-cua 0.1.1 at `6ca19d62c95106732fad28f488ecd458c08e02f4`, versus the installed Cua Driver 0.31.0 through its existing daemon. Both were called through their public MCP stdio tools. arc ran in a temporary Python 3.12.12 environment, without global installation or MCP registration. The native driver was not upgraded; these results do not compare against its newer releases or every native tool available in Codex.

The native fixture is a synthetic AppKit form extending upstream's fixture, with its own atomic state file and explicit app-side fault injection. The web fixture is a real WKWebView with input-event logging and a custom dropdown; a separate Unix-socket JavaScript oracle reads what the renderer received. All text and submissions were synthetic. Selected controls were grounded in current exact-window observations. Adversarial tests deliberately submitted saved handles after controlled mutations to measure the driver's refusal boundary, rather than an agent's willingness to act through a modal dialog.

Three repetitions alternated driver order. There were 72 scheduled driver cases, 70 completed, and two fixture-readiness failures before driver input: the first minimized fixture for each driver failed to minimize. Later minimized cases passed twice per driver. Setup failures are retained separately and are not counted as driver failures. Earlier exploratory runs with an unoffered popup action and an early menu oracle were excluded from the scored comparison. The corrected popup opens the observed control and selects an observed menu item; the menu oracle waits up to three seconds for the actual counter change.

Initial web observation sometimes exposed only the window shell. The final web harness allows up to three fresh observations, spaced 0.2 seconds apart, before refusing an unavailable target. The earlier one-observation failures do not establish native inability to drive the form. Both drivers completed the corrected web case without foreground text recovery.

## Matched task results

Times are median summed MCP tool latency, including observations and arc's `settle: true`. They exclude fixture launch, release and model reasoning. These are driver-loop measurements with scripted selections, not measured LLM token savings or autonomous-agent accuracy. The independent oracle separately establishes actual task effects.

| Task | arc completion | Installed Cua Driver completion | arc / native MCP time | arc / native calls |
| --- | --- | --- | --- | --- |
| Native form: two fields, checkbox, submit | 3/3 | 3/3 | 1.05 / 9.73 s | 5 / 9 |
| Native popup selection | 3/3 | 3/3 | 0.88 / 4.85 s | 3 / 5 |
| Menu counter command | 3/3 | 3/3 | 0.69 / 0.91 s | 3 / 3 |
| Exact first window after second window appears | 3/3 | 3/3 | 0.39 / 2.76 s | 3 / 4 |
| Hidden app: checkbox, remains hidden | 3/3 | 3/3 | 0.21 / 2.41 s | 2 / 3 |
| Minimized window: checkbox, remains minimized | 2/2 completed | 2/2 completed | 0.22 / 1.22 s | 2 / 3 |
| WebKit: text, custom degree dropdown, submit | 3/3 | 3/3 | 1.40 / 10.72 s | median 8 / 9 |

For the native form this is about 9.2× less MCP time; for the web form about 7.6×. Three runs on an actively used Mac establish a local advantage on these cases, not a universal multiplier. arc's initial per-fixture driver setup is included. Extra native observations are part of its documented action/verification loop; arc can return the settled observation with the action. Both are scored from the independent fixture, not their acknowledgments.

## Refusal boundaries

Each cell covers three completed repetitions. The expected result is refusal without submission.

| Mutation after the selected observation | arc | Installed Cua Driver |
| --- | --- | --- |
| Submit button label changes | Refused 3/3; no submissions | Allowed 3/3; submitted through changed label |
| Submit button becomes disabled | Refused 3/3; no submissions | Refused 3/3; no submissions |
| Sheet opens above Submit | Refused 3/3; no submissions | Allowed 3/3; submitted beneath sheet |
| Sheet opens 800 ms after a click | Returned before sheet; later stale action refused 3/3 | Returned after sheet; cached underlying Submit allowed 3/3 |
| Surrounding record changes A → B; Submit itself unchanged | Allowed 3/3; submitted record B | Allowed 3/3; submitted record B |

arc's last row is the decisive reason to retain our semantic contract. An unchanged actionable node can now belong to the wrong record. A target's label/value guard and a structural journal do not replace current same-record predicates. These tests measure driver mechanisms; a controller could avoid all these actions by rereading and checking the task context itself.

## Background and lifecycle evidence

Hidden/minimized actions reported `parked: false` and preserved those states. No virtual display was created. The independent CoreGraphics inventory retained the initial three online and three active displays; the existing fault record was unchanged. All trial fixture and MCP processes exited; the pre-existing Cua Driver daemon remained running.

Background guarantees are narrower than task completion. The fixture's own 5 ms state timer sampled app activation; activation was seen during all three native menu trials and one arc menu trial. Endpoint front-app comparisons did not change. Four cursor endpoint changes without a recent HID mouse event were recorded in native menu trials, while none were recorded in the other native cases or arc cases. The host was actively used, and the watcher includes observation/launch settling; this is not enough to attribute every transient or certify attention isolation. It is contrary to treating completed menu tasks as proof of an absolute no-disturbance guarantee. A reserved-host test with per-action frontmost sampling is required before promising that guarantee.

Virtual-display behavior was deliberately not exercised. The preserved fault still reports uncertain owner teardown. arc's private WindowServer calls and window parking must pass an independent lifecycle/recovery matrix before that capability is selected. Source-level similarity cannot clear an existing incident or demonstrate safe retirement.

## Additional qualification

The upstream non-browser suite passed 368 tests with its browser module initially skipped because the optional WebSockets dependency was absent. After installing that dependency in the temporary environment, all 14 upstream Chrome tests passed against an owned headless Chrome and local pages. These include changed-target rejection, covered controls, form submission, dropdowns, shadow DOM/iframes, delayed network settling, JavaScript dialogs and tab following. This supports a potential lightweight isolated-browser role, but it is not a matched performance comparison with our off-screen adapter and does not establish access to the user's login.

The Jev/choice policy was not live-qualified. Driver speed does not establish decision accuracy, prose-constraint enforcement or independent completion verification; the latter remains optional in `DesktopExecutor` unless supplied by the caller.

## Salvage and next decision

The useful frame is now supported by live evidence: adoptable driver mechanisms, separately qualified perception/selection, and separately qualified display ownership. The initial static assessment understated how useful the driver could be; source review alone was insufficient for the requested evaluation.

Retain arc's exact-window targets, label/value revalidation, modal change refusal and combined action/settled-observation response. Retain our same-record checks because the wrong-record case still acted in every repetition. Keep bounded observation recovery: the early WebKit shell was a readiness condition, not final evidence of missing capability. Keep transport completion separate from app effects: menu dispatch can return before the app's counter is updated.

The concrete fit is a native-driver option in the skill, with the controller owning semantic checks and independent verification. The Chrome backend is a secondary candidate for small isolated browser work. The decision-model loop and virtual-display ownership should remain separate candidates until measured. No routing defaults, installed skills, runtime projection or fault records were changed by this evaluation.

Evidence and reproduction: [native results](../experiments/arc-cua-comparison-2026-10-05/results.json), [renderer results](../experiments/arc-cua-comparison-2026-10-05/web-results.json), [cleanup](../experiments/arc-cua-comparison-2026-10-05/cleanup.json), [harness](../experiments/arc-cua-comparison-2026-10-05/run.py), [web harness](../experiments/arc-cua-comparison-2026-10-05/web_run.py), [fixture](../experiments/arc-cua-comparison-2026-10-05/fixture.py), [initial source evaluation](ARC-CUA-EVALUATION-2026-10-05.md). Global Apple/menu trees are excluded from saved observations because they can contain recent user documents. Screenshots and private host inventories are not saved in the repository.

## Follow-up qualification and review

A controlled follow-up kept a separate owned sentinel active throughout five arc menu-command trials; the target counter advanced once in each trial and no target activation notification occurred. The earlier observation remains attribution-uncertain and does not establish an arc menu bug. Optional record-anchor guards blocked all three live Record A-to-B submissions; the unguarded baseline still submitted B in all three. See the [review packet](ARC-CUA-REVIEW-2026-10-05.md) for methods, results and upstream PRs.
