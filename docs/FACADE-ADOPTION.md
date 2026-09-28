# CUA facade execution and adoption — 2026-09-27

## Aim and decision

Make supported CUA work discoverable as first-class tools so agents use the configured reading/selection models without authoring temporary wrappers. Selected approach: a local stdio facade that owns fresh Driver evidence and executable bindings. Alternative considered: stronger prose alone; the fresh-agent result tests whether direct tools improve adoption. Stock Driver remains responsible for desktop operations. Provider setup stays external.

## Fresh-agent test

User explicitly authorized one bounded fresh agent on a local synthetic demo. A normal Chrome window served three product records plus Inspect, Keep selection, Clear selection and Open summary controls. No purchases, account data or remote sites. Agent deadline: five minutes; at most one retry per failed step. It finished in approximately 140 seconds including agent startup, reasoning and MCP startup (not model latency).

Observed direct calls: inventory, observe, NuExtract read, choose, act, verify and finish. No temporary action wrappers. Final screenshot displayed `Summary ready: Alder` after selecting the used $80 power bank.

| Step | Actual route | Result / qualification |
|---|---|---|
| Read three records | NuExtract3 | 1.113 s endpoint time; Cedar category incorrectly extracted as Cedar; two names included container labels |
| Inspect Alder exact match | Exact, no model | Deferred: duplicate button entries in AX table projections |
| Inspect retry | Julia-1 | Selected supplied singleton; 458 ms inference, 463 ms round trip/decision, 4.932 s startup; **not comparative chooser evidence** |
| Visual verification | SystemOne worker | Invalid response; no successful specialist verification |
| Summary / keep / summary | Exact, no model | Agent opened summary too early, observed unmet precondition, then kept and reopened |
| Final state | Fresh Driver screenshot interpreted by controlling agent | Summary ready: Alder; task workers closed |

Fresh-agent adoption passed for tool discovery/use. Planning and specialist-only verification did not pass. The agent's final response omitted the premature summary action; this report uses tool evidence, not that summary alone.

## Adjustments and bounded follow-up

- Preserve AX table cell boundaries instead of flattening container labels into fields. A follow-up read with explicit cell descriptions returned all 12 fields correctly in 1.064 s. Both representation and descriptions changed; this does not isolate causality or prove general extraction accuracy.
- Semantic singletons now require a complete filtered reading. Regression rejects the fresh agent's preselected singleton retry. Exact ambiguity stays an abstention, never an arbitrary first match.
- Invalid visual responses now return and trace unknown; they cannot become success.
- Accept `string` as the read-field alias for `text`.

A separate read-only live chooser check offered Keep selection, Clear selection and Open summary from a fresh Driver observation. Goal: keep the current selection, do not clear it or open summary. **Julia chose Clear selection**, a wrong choice. No action was executed. Inference 465 ms, decision excluding startup 471 ms, startup 5.088 s. Scores were uncalibrated. Screenshot verification failed again and was traced unknown. Whole follow-up: 7.736 s; two Driver captures: 364/374 ms. Julia remains the user's configured preference; this result does not recommend its accuracy.

## Risk retirement and review

| Risk | Disposition and evidence | Tempting wrong repair rejected |
|---|---|---|
| Tools still bypassed | Fresh agent used MCP directly; one run only | Claim adoption from registration alone |
| Caller-created exact winner | Exact checks all observed controls; synthetic IDs and hidden duplicates rejected | Wrap synthetic singleton in empty dispatcher |
| Caller-selected semantic winner | New singleton regression; filtered read required | Call Julia only to ratify a winner |
| Cross-record evidence | Overlap, descendant join, excluded-record and same-record tests | Borrow another row's price or action |
| Stale/edited/replayed action | Fresh full-content comparison, immutable server args, single-use tests | Trust caller arguments or refresh a token without checking evidence |
| Missing AX / vision evidence | Unknown outcome tests and actual visual failure | Infer success/stall from absent AX text |
| Model accuracy | **Triggered:** real extraction and Julia failures retained | Count endpoint invocation or high scores as correctness |
| Task worker lifetime | Explicit finish and shutdown cleanup; mocked close checks | Leave task workers resident |
| Native coverage | Accepted scope: AX clicks/text only; raw fallback documented | Pretend keyboard/canvas/browser APIs are implemented |

Self-review verdict: deliver the facade as a tool-adoption improvement with explicit model/verification limitations. Do not claim reliable autonomous completion. No independent code review was performed. General adoption across tasks and the suitability of Julia as default require further measured use, not human approval of this synthetic fixture.

Offline evidence: 28 facade regression tests, 46 capability-dispatch tests and 15 parent-decider tests passed. Existing simulation gate covers 28 scenarios, 40 metamorphic cases, 35 historical decisions and seven deliberately wrong repairs. Mutation logs intentionally contain failing tests; their detection is the passing condition. SDK initialize/list-tools exposed all eight tool schemas. Live endpoint failures remain actionable issues.

## User-authorized Jev comparison and final configuration

After the user authorized returning to Jev, a paired read-only comparison sent the **same request binding and same snapshot** to Julia and Jev. Observed alternatives were Keep selection, Clear selection and Open summary. Julia again chose Clear (448 ms inference, 453 ms decision, 4.617 s startup); Jev 1.13.0 chose Keep (1.059 s provider, 1.103 s decision, 3 ms adapter startup). Neither action was executed. A preceding separate Jev check also chose Keep. This is bounded counterexample evidence, not a general benchmark.

Changed repository fallback and installed runtime configuration to NuExtract → Jev, retaining configured Qwen escalation and optional Julia. Updated installed skill and setup reference. The facade attributes the actual provider trace, not its compatibility slot name.

The screenshot failure was an integration error: the visual worker included a 34,445-character AX dump in state, exceeding the existing endpoint's 8,000-character state limit. Removed AX duplication from visual requests while retaining the screenshot, postcondition, candidates and constraints. Added a regression asserting those inputs survive, plus a check that a response must confirm vision processing. HTTP errors now include sanitized status codes. A positive live check returned ready for Summary ready: Alder; a false Beryl postcondition returned unknown. No model swap was required for this repair. Jev is text-only per https://docs.typesafe.ai/models and is not substituted for screenshot perception.

Tracking: [adoption #1](https://github.com/open-horizon-labs/computer-use/issues/1), [visual integration #2](https://github.com/open-horizon-labs/computer-use/issues/2), [Julia counterexample #3](https://github.com/open-horizon-labs/computer-use/issues/3). Earlier trial descriptions above retain their actual routes; final runtime default is Jev.
