# Arc versus current Cua Driver — 2026-10-05

## Current result

Both candidates were checked against upstream before this rerun: the installed Cua Driver was updated to **0.33.4**, the latest component release, and Arc remains **0.1.1** at upstream head `6ca19d62c95106732fad28f488ecd458c08e02f4`. MCP initialization independently confirms the running servers' versions. The original 0.31.0 comparison was outdated for a current head-to-head; it is preserved as [historical evidence](ARC-CUA-COMPARISON-0.31.0-2026-10-05.md), not the basis for the figures here.

Arc's native form loop uses **8.1× less MCP time**, and its WebKit form loop **7.6× less**, at equal 3/3 completion in both cases. Cua is faster on the menu case (0.58 s versus Arc's 0.80 s). These are local driver-loop measurements with scripted selections, not autonomous-agent accuracy or measured model-token savings. The user-selected Arc default remains useful for these qualified macOS controls, with exact-window binding, controller-side record matching and independent outcome verification.

## Candidates and method

macOS 27.0.1, Python 3.12.12. Cua's canonical updater verified the universal release archive against SHA256SUMS, replaced the 0.31.0 signed app bundle, and preserved Accessibility and Screen Recording grants. Its updated standalone daemon was relaunched under the same `com.trycua.driver` identity. Arc uses the clean upstream checkout in the qualification environment; the optional guard PR is not part of either baseline. The installed Arc source pin remains unchanged.

The same public-MCP harnesses, exact-window targets and synthetic AppKit/WKWebView fixtures were reused. Independent app state and renderer JavaScript establish actual effects. Three repetitions alternate driver order. **All 72 scheduled cases ran: 66 native and six renderer trials, with zero fixture-setup failures.** No virtual displays, user documents, logins or browser profiles were used. Early front-app telemetry can be cached or include fixture launch; it is not scored as proof of attention isolation.

Times below are median summed MCP latency, including observations and Arc's `settle: true`; fixture startup, MCP initialization, release and model reasoning are excluded. Each case's independent oracle also waits for actual effects. Additional Cua observations retain the same verification loop as the original comparison. There was no foreground text recovery in either driver's renderer trials.

## Matched completion and efficiency

| Task | Arc completion | Cua 0.33.4 completion | Arc / Cua MCP time | Arc / Cua calls |
| --- | --- | --- | --- | --- |
| Native form: two fields, checkbox, submit | 3/3 | 3/3 | 1.19 / 9.70 s | 5 / 9 |
| Native popup selection | 3/3 | 3/3 | 0.91 / 4.81 s | 3 / 5 |
| Menu counter command | 3/3 | 3/3 | 0.80 / 0.58 s | 3 / 3 |
| Exact first window after second window appears | 3/3 | 3/3 | 0.32 / 2.74 s | 3 / 4 |
| Hidden app: checkbox, remains hidden | 3/3 | 3/3 | 0.28 / 2.50 s | 2 / 3 |
| Minimized window: checkbox, remains minimized | 3/3 | 3/3 | 0.22 / 1.19 s | 2 / 3 |
| WebKit: text, custom degree dropdown, submit | 3/3 | 3/3 | 1.48 / 11.20 s | 8 / 9 |

## Refusal boundaries

Adversarial trials deliberately reuse saved handles after app-side mutations. Expected success is refusal with zero submission; these are driver-mechanism checks rather than instructions for a controller to ignore changed task context.

| Mutation | Arc 0.1.1 | Cua 0.33.4 |
| --- | --- | --- |
| Submit label changes | Refused 3/3; zero submissions | Allowed 3/3; submitted through changed label |
| Submit becomes disabled | Refused 3/3; zero submissions | Refused 3/3; zero submissions |
| Attached sheet opens above Submit | Refused 3/3; zero submissions | Allowed 3/3; submitted behind sheet |
| Sheet opens 800 ms after the initiating click | Later cached action refused 2/3; one behind-sheet submission | Cached underlying action allowed 3/3 |
| Surrounding record changes A → B; Submit itself unchanged | Allowed 3/3; submitted B | Allowed 3/3; submitted B |

The delayed-sheet result weakens the earlier three-of-three Arc refusal claim. UI quiet is not proof that future modal state has arrived, and notification-based revalidation is not a universal modal interlock. The failed trial is retained in the scored evidence. Three additional fresh-server trials reproduced one behind-sheet submission and two refusals. See the [confirmation evidence](../experiments/arc-cua-comparison-2026-10-05/latest-0334/delayed-sheet-followup.json) and [review packet](ARC-CUA-REVIEW-2026-10-05.md). Neither baseline guarantees same-record submission; the optional [Arc context-guard PR](https://github.com/shhivv/arc-cua/pull/3) remains separate, with explicit anchors and independent verification still owned by the controller.

## Lifecycle, menu and review limits

Hidden and minimized checkbox tasks preserved their original state in all three trials per driver; Arc reports no parking. The preserved display lifecycle fault remains in place, and no new virtual display was created. The updated Cua daemon remains available after benchmark clients and owned fixtures close.

The separately controlled menu test kept an owned sentinel active in five of five trials and recorded zero target activation notifications. The earlier activation observation remains attribution-uncertain, not an established Arc menu bug. This qualifies the synthetic command, not every application's menus. Global Apple menu trees and screenshots are excluded from saved observations.

The two Cua fixes, [#4677](https://github.com/trycua/cua/pull/4677) and [#4678](https://github.com/trycua/cua/pull/4678), remain independent drafts pending their required full canonical matrix. Their native focused regressions pass; this benchmark uses the official release rather than either candidate patch. Display ownership, Electron, real authenticated flows and decision-model accuracy remain unqualified by these synthetic results.

## Always update comparison candidates

Every new head-to-head must update all candidates to their current upstream release/source first. The harness now makes a fresh Cua component-update query, rejects differing current/latest versions, checks Arc against current upstream head and clean tracked source, verifies the imported package path, and checks each actual MCP server version. A new CLI with an old daemon is refused. Exact versions/commits and query timestamps are saved; a failed update lookup is not permission to compare an old candidate. This rule is also recorded in AGENTS.md. Five offline preflight regressions cover stale CLI/server versions and failed-initialization cleanup.

Evidence: [current native results](../experiments/arc-cua-comparison-2026-10-05/latest-0334/results.json), [current renderer results](../experiments/arc-cua-comparison-2026-10-05/latest-0334/web-results.json), [current schemas](../experiments/arc-cua-comparison-2026-10-05/latest-0334/schemas.json), [native harness](../experiments/arc-cua-comparison-2026-10-05/run.py), [renderer harness](../experiments/arc-cua-comparison-2026-10-05/web_run.py), [preflight tests](../experiments/arc-cua-comparison-2026-10-05/test_candidate_preflight.py), [review packet](ARC-CUA-REVIEW-2026-10-05.md).
