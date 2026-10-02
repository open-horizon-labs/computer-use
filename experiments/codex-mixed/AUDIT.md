# Trace audit and improvement decisions

User request: audit every case where OH did not win and address the three largest latency or token bottlenecks. Baseline runtime is frozen at `0745718`; implementation work is isolated in `codex/mixed-driver-improvements` until baseline collection ends. Only the replacement primary batch determines the ranking, with the global-guidance qualification below. Preliminary failures supply reproductions, not clean comparative timing.

## Frame and selection criteria

The aim is successful multi-step work with less waiting and model context. Completion and exact target binding are constraints: an early refusal, an unverified action, or a weaker success check cannot be counted as an optimization. Audit every OH task that loses completion, median wall time or median reported tokens. Missing usage is not a token win. Among those losses, select three bottlenecks with the largest measured latency/token burden and a demonstrated causal path in the trace. Prefer fixes that apply beyond one fixture; record both absolute burden and excess against native. Do not change the model, task prompt, fixture or expected answer to manufacture a win.

## Solution space

| Candidate | Frame | Advantage | Cost or reason to reject |
|---|---|---|---|
| Improve observation and guidance so existing specialist routes are discoverable | The capability works but the agent cannot identify it from look/schema | Small change; may remove repeated failed calls without changing action policy | Must show fresh agents actually use it; examples alone can overfit |
| Repair deterministic routing and bounded verification | The server repeats expensive or impossible work | Can remove driver/model work while preserving the same goal and proof | Must distinguish impossible evidence from delayed evidence; never shorten waits into false success |
| Use a better driver path for the surface behind the same facade | The current transport is the bottleneck | May make a currently blocked off-screen surface usable | New binding/coordinate/lifecycle risks; requires independent live proof and captured regressions |
| Leave a task on native tools and state the limitation | OH’s abstraction adds cost without a useful benefit here | Honest and cheap operational choice | Does not satisfy the requested implementation improvement by itself; retain as a fallback if no safe fix measures better |

## Dissent before choosing patches

The strongest case for optimizing OH is a shared interface that can remove repeated model decisions and execute through the right specialist driver. The counterevidence is already concrete: native PTY tools can do simple TUIs quickly, the existing OH select adapter can work when called correctly, and inherited host instructions contaminated the first batch. The bottleneck is not automatically missing code, model quality or a need to loosen verification.

Three failure scenarios to guard against:

1. Functional failure: a faster patch declares success from input echo, a stale snapshot or the wrong duplicate control. Required checks reject each of those shortcuts and preserve independent task oracles.
2. Adoption failure: the low-level route is fixed but agents still cannot discover it and keep making the same unsuccessful calls. Required evidence is a fresh-agent rerun with the same task prompt, not only a scripted happy path.
3. Opportunity cost: extensive new driver machinery is built to solve a small synthetic loss while a simpler observation or batching fix would remove more cost. Rank measured losses before choosing implementation scope; compare simpler alternatives explicitly.

## Risk-retirement checklist

| Risk or alternate explanation | Required evidence | Tempting wrong patch the check must fail |
|---|---|---|
| Host guidance or harness permissions explain the comparison | Canary-proved project-document exclusion, explicit retained global-guidance qualification, same sandbox, retained excluded batches | Rebrand contaminated native runs as driver failures |
| A refusal is faster only because it abandoned the goal | Independent task events/device state and completion shown with speed | Optimize median failure time and claim task efficiency |
| Repeated control labels are real competing targets | Captured realistic trees plus duplicate/stale adversarial cases | Pick the first matching label or hide uncertainty |
| An expectation is just the input echoed back | Fresh independent evidence scoped to the declared step; no goal-level success from transport acknowledgement | Accept typed text or a button label as proof that a workflow completed |
| A slow postcondition is legitimate delayed UI | Delayed-success and unchanged-state regressions with bounded observation | Cut timeout or replay input blindly |
| Token cost is inflated by avoidable schema/response/turn volume | Actual trace payloads and reported before/after usage | Replace real usage with a guessed bytes-to-token conversion |
| A new transport changes foreground/session or coordinate scope | Exact target/session binding, fresh capture, background placement evidence and independent real UI result | Bypass a refusal with arbitrary raw coordinates or a different user profile |
| Improvements only fit these prompts | Same-prompt fresh-agent reruns and separate adversarial regressions | Put benchmark names, field values or task-specific selectors in runtime code |

Model-checkable risks must pass before integration. The smallest credible change is preferred; if it needs weaker proof or undocumented authority, reconsider the route. Statistical generalization beyond these synthetic tasks remains unclaimed.

## Baseline ranking, chosen fixes and results

The three selected causal bottlenecks are mobile binding/state, forms affordance/verification information, and terminal schema/redundant observations. Mobile and forms cause failed or 240-second tasks; terminal has the largest fully reported baseline token excess. These are causal groups spanning tasks, not three claimed qualified head-to-head wall-time losses. Final results below retain setup blocks and missing usage.

## Interim evidence and candidate patches

The completed primary terminal cells show 3/3 independent completions in each arm. OH median wall is 80.882 seconds versus native 56.844, and median reported total tokens are 370,875 versus 272,498. The third OH trial has about 0.210 seconds of observed MCP time across nine completed calls: driver wait reductions cannot explain most of its wall time. A terminal type call supplied an invalid control field, so the candidate schema change explicitly says terminal type omits control.

The completed primary web cells show native 2/3 completions and OH 0/3, with median wall 107.616 versus 240.021 seconds. OH timeout rows lack final usage; they are not token wins. The first two OH traces spend about 71–72 seconds inside MCP calls and repeatedly use typed text as a postcondition, then press globally duplicated select options. The existing select adapter can independently verify a selected value, but the look does not identify the control as a select. Plan responses also discard verification reasons such as `expect_echoes_typed_text`. Candidate changes expose select affordances, preserve typed verification reasons, and show input values up to the normal line bound with explicit truncation instead of silently cutting at 30 characters.

The primary VNC pairs show native completes while OH stops at `novnc_typing_unavailable`. This is a capability loss, even when OH uses fewer tokens. The live Driver catalog has ref-bound `browser_type` but no browser key tool; Perception exposes text/icon regions, not editable-field geometry. A guessed offset from a Project label would violate the binding constraint and is rejected. A dedicated transport or a properly grounded input route needs qualification; shortening or hiding the refusal does not fix completion.

Candidate `a156b17` is frozen in `/Users/muness1/.codex/worktrees/mixed-driver-improvements/computer-use` for post-change measurements and integrated as `08e1df4` after all baseline cells completed. Installed Codex and Claude registrations both point to the original checkout, so fresh connections use the integrated runtime. Final offline evidence and fresh-agent results are recorded below.

### iOS ancestry audit and qualification

The context-only candidate removed the `KeyError: 'pid'` but still completed 0/3 iOS tasks (two timeouts, one partial). The fresh agents launched Settings directly, so app launch discoverability was not sufficient. All three left appearance light; repeated switch presses did not change it.

The native mobilecli hierarchy shows why: the labeled `Dark Appearance` Switch is a wide parent (x=36, y=184, width=330, height=28), with a separate unlabeled Switch child (x=305, y=183, width=63, height=28). Mobile MCP 1.0.6 flattens away that ancestry. Ref-based tapping of the labeled parent targets its center, away from the actual toggle. A guessed right-edge offset and relaxed verification were rejected. The candidate instead reads the complete fresh raw hierarchy on affected iOS switch screens, keeps the semantic parent and binds activation to its unique observed child. A custom/remote backend must explicitly provide its hierarchy reader; offline tests never start local providers.

Adversarial checks reject duplicate children, conflicting state, missing refs, unrelated labels, disabled children and a geometrically nearby switch outside the parent. Geometry, refusal and state changes alter the semantic progress signature; reference renumbering alone does not establish progress. Input references are freshly bound. `expect: checked|unchecked` verifies only the freshly matched target switch; another checked toggle, missing value and tap acknowledgement cannot prove it. The real controlled fixture passed both directions: the child-bound press produced checked plus independent `simctl` dark; the reverse press was verified unchecked by the facade. This is route qualification, not an agent benchmark result. The unchanged three-run agent task is retained separately in `post-ios-child` with frozen Python hashes.

The first hierarchy candidate agent run completed the unchanged iOS task in 238.512 seconds, 21 calls and 762,034 reported total tokens; independent dark/About/version checks all passed. The second reached dark mode and About but timed out before reporting the version (partial). Restoring an actionable target does not by itself retire the excessive-turn risk. The first trace still has seven unverified deliveries and one missing-look refusal. Of its 21 completed calls, 19 have complete passive timings totaling 49.288 seconds; the first two started before the observer, so that sum is incomplete. Do not equate it with total tool time or claim a broad speed win.

The mutation gate's first rerun applied 198/200 old patches: two source patterns no longer matched the changed `_read`/`settle` lines. The same stale-read and acknowledgement-trust mutations were updated to the new lines; both are still caught by assertions. Four new mutations (parent activation, first competing child, ignored conflicting state, unchecked without value) are also caught. The complete 204-mutation gate passed before integration.

### Independent review and isolation qualification

A fresh subagent review, required by the installed computer-use skill before integration, exposed three blockers: geometric collapse could hide conflicting state targets; child validation admitted negative dimensions, contradictory flags and duplicate refs; malformed child lists escaped typed refusal. Each was repaired with an adversarial regression. The reviewer independently ran 169 focused tests and found no remaining blocker. The optional buffered-output memory limitation is accepted for this scoped repair with an explicit provider-documentation limitation; response-size rejection, timeout and tree traversal limits remain enforced. No streaming-memory guarantee is claimed.

The native mixed first trial attempted to read the missing capability-dispatch skill before using its allowed PTY command. The task oracle passed, but this is correctly scored protocol-violation. Native mixed trials two and three completed with no extra command. The local canary established only project-document exclusion. Global computer-use guidance is present in the user's Codex home; the actual trace proves that guidance can still influence behavior. Both arms retain that same host setup for before/after comparability. This is a benchmark in the user's configured Codex environment, not a claim that all user customization is absent or a pristine tool-only model comparison. Official instruction-discovery context: https://learn.chatgpt.com/docs/agent-configuration/agents-md. No user instructions were modified to run the benchmark.

The revised regular Mac fixture completed OH 3/3. The native benchmark processes returned an actual `Invalid app: OH Benchmark` and an inventory missing the app in all three runs, although the main desktop connection could see it and bind by bundle ID. Export marks this target-inventory setup block from tool evidence, separately from an explicit app-permission refusal. Do not call native's short refusal a speed win or OH's completion a qualified head-to-head speed result.

The Applications-directory qualification (owned symlink, no app activation/input) fixed native discovery of the synthetic Mac fixture. A fresh native agent then found its bundle ID but received the explicit tool refusal `Computer Use was not approved to use OH Benchmark`. This isolates discovery from the remaining app grant; no alternate driver was used to bypass that native refusal. The local qualification trace remains outside Git.

Terminal token nuance: baseline median uncached input, computed per row before taking the median, is 69,022 native versus 27,242 OH. OH still has more cumulative total tokens and slower wall, but that is not evidence of greater dollar billing. Cached-token subsets and missing timeout usage must remain visible.

### Reviewed candidate and final mobile evidence

Runtime candidate `a156b17` passed 1,290 facade tests, unchanged default call-budget checks, and all 204 adversarial mutations. The independent reviewer reran 169 focused tests after fixes. The final unchanged iOS task completed 3/3, versus baseline 0/3. Median attempt wall time was 214.497 seconds versus the baseline 240-second limit. Median final reported total tokens were 770,176; baseline usage is unavailable, so no token reduction is claimed. Earlier context-only and hierarchy iterations remain separate from this reviewed candidate.

### Android follow-up from the frozen candidate

The primary Android OH cells all failed before acting because mobile `look` expected desktop `pid` metadata. The first reviewed-candidate Android task progressed to the Dark theme page but refused its switch with `toggle_state_unseen` despite a fresh look displaying unchecked. The mobile-mcp JSON formatter omits false checked flags. The facade must not display missing state as unchecked or silently infer unchecked from absence. This is retained as failed candidate evidence; qualify raw provider state before a follow-up repair. Native Android returned real inventory/permission blocks, so there is no qualified native speed comparison.

## Every baseline non-win

| Task | OH evidence | Native qualification | Decision |
|---|---|---|---|
| Terminal | 3/3 correct; median 80.882s and 370,875 cumulative tokens | 3/3 correct; 56.844s and 272,498 tokens | Selected: schema friction and redundant observations; tool spans are too small to explain most wall time |
| Web | 0/3; 240s limits; usage unavailable; repeated echo expectations and duplicate option targeting | 2/3 correct | Selected with mixed: expose existing select route, values and actionable verification reasons |
| Mixed | 0/3; TUI completed, forms stalled; usage unavailable | 2/3 valid; one oracle-correct protocol violation | Same forms cause plus terminal guidance; retain invalid native row as diagnostic only |
| iOS | 0/3; mobile look binding crash, costly pixel fallback and no-op parent Switch taps | 0/3, actual native app grants denied | Selected mobile group: device binding and fresh native child activation; no qualified native speed ranking |
| Android | 0/3; mobile look binding crash | 0/3, actual inventory/permission blocks | Same mobile binding group; post candidate revealed absent false state and requires separate qualification |
| VNC | 0/3; `novnc_typing_unavailable`; 95.224s median attempt | 3/3 correct, 87.187s | Capability gap remains issue #102. Lower failure tokens are not efficiency. Guessed label offsets rejected |
| Native Mac | OH 3/3 correct; 127.654s median | Native 0/3 inventory miss; discovery qualification then explicit denied grant | OH capability works; comparative speed/token verdict unavailable |

Three priorities are causal groups selected for failed-task wall burden (mobile/forms) and fully reported token excess (terminal). The VNC gap is audited and recorded, but has neither the 240-second repeated-turn burden nor terminal’s measured cumulative-token excess. This does not excuse its missing capability or claim an OH win. Global guidance, native grants, unavailable timeout usage and the small synthetic sample remain accepted reporting limitations, not silently retired risks.

### Android state follow-up qualification

The pinned mobilecli raw Android hierarchy preserves explicit false checked state that its normal JSON and mobile-mcp formatter omit. The follow-up candidate reads that complete fresh raw tree only when an Android toggle has unknown state. It never joins it to the older flat list, infers false from absence, or guesses a location from the label. Fresh observed switch bounds use the existing coordinate transport because this raw tree has no refs. A missing/conflicting state is now displayed as unknown. Hidden/disabled ancestry is conservatively excluded; rejecting a descendant Android may enable independently is an accepted scope trade-off, not proof of platform-wide disable semantics.

Controlled two-direction qualification passed: the same facade exact switch press verified checked and the independent device appearance was dark; a fresh reverse action verified unchecked. Independent review caught hidden-ancestor and overflow handling defects; explicit regressions were added. These manual qualification actions did not overlap Android benchmark cells and do not count as agent task results.

## Bounded closeout

The user stopped broad optimization after scope drift. Final a156b17 reruns: iOS 3/3; terminal 3/3 with 34.2% fewer cumulative tokens but slower median wall; Android/web/mixed 0/3. Android raw-state and field-value follow-ups are archive drafts, not a new benchmark win. Native becomes the default; mobile and isolated off-screen work remain explicit opt-ins. No automatic route is promoted. The broader runtime, unfinished drafts and evidence are preserved on a Git archive branch instead of a maintained experimental directory.
