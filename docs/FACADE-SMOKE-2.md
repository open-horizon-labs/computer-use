# Fresh-agent MCP smoke and repairs — 2026-09-28

## Outcome

User requested another fresh-agent smoke and fixes for observed friction. Ran two isolated ephemeral agents through the installed MCP registration: first to expose failures, then one bounded follow-up after repairs. Same prompt and synthetic demo, normal Chrome profile and existing Driver session; no other windows observed or acted on. Reset demo state between runs. Each agent had five minutes, one retry per failed step and a 20-second stalled-step bound. The first agent unnecessarily repeated an already completed Inspect action while recovering, so its retry discipline was imperfect; the follow-up used one retry for ambiguous exact matching.

| Measure | Before repairs | Follow-up |
|---|---|---|
| Final outcome | Summary ready: Alder, after recovery | Summary ready: Alder |
| Approximate total wall time | 285 s | 112 s |
| NuExtract reads | 3; all 12 requested fields correct each time | 1; all 12 correct |
| Extraction endpoint time | 1.10 / 1.02 / 1.01 s | 1.04 s |
| Contextual selection | Jev 1.11 s; repeated Inspect escalated to Qwen 1.69 s | Jev 1.22 s then configured Qwen escalation 1.13 s |
| Chooser decision including transport, excluding adapter startup | 1.16 / 1.69 s | 2.39 s |
| Individual Driver captures | 329–367 ms | 327–390 ms |
| Action order | Inspect → premature Summary → Inspect again → Keep → Summary | Inspect → Keep → Summary |
| Agent-created action wrappers | None | None |
| Model workers | Closed with cua_finish | Closed with cua_finish |

Wall time is approximated from each retained JSONL file's creation/final-write timestamps and includes agent startup, reasoning and tool overhead; it is not model latency. One run per version is not a speed benchmark. Exact Keep/Summary operations bypassed models and are not chooser accuracy evidence. The follow-up Inspect scope had one survivor after typed filtering, so that choice is not a multi-option accuracy measurement either. Jev's experimental selector threshold caused escalation; scores are not calibrated confidence.

## Defects fixed

1. **Reading-to-choice contract:** caller supplied observed record IDs plus their descendant action mapping; the old facade required control IDs without making that distinction clear. Both complete representations now work. More seriously, semantic choice silently ignored the supplied typed predicates. Choice now filters stored extraction using stored schema and conjunctive old/new predicates. No repeat extraction is needed. It rejects criteria on modes that cannot execute them.
2. **Currency schema:** money fields require an explicit supported currency before model work. MCP exposes a typed field schema and actionable validation; text remains available for other currencies/unparsed prices. The follow-up supplied USD correctly.
3. **Window discovery scope:** the old tool ignored the attempted title argument and returned unrelated window titles. Optional exact-title filtering now returns only matching windows. The follow-up used it successfully. Driver still inventories locally; filtering is the agent-facing projection.
4. **Verification recovery:** verification now returns its fresh screenshot and element IDs along with the assessment. Unknown results can be reconciled against that same observation. Assessment/transport timing is logged separately from Driver capture and provider startup.
5. **Workflow guidance:** preserve ordered prerequisites, choose the next unmet step, verify observable outcomes, and do not repeat completed actions to recover from a later failure. Follow-up kept the selection before opening its summary.

## Remaining limitations

The native AX table exposes duplicate Inspect buttons through row/column projections. Exact matching appropriately abstained; the follow-up used the grounded row mapping. No controls were merged merely because labels matched.

Screenshot verification returned unknown for requests phrased as an inspection/details view or an open summary. The demo exposes status text rather than a separate details view. After Keep, the agent also checked the old literal `Selected: Alder` while the page said `Kept: Alder`; unknown was correct for that exact request. The controlling agent confirmed the final screenshot, and the final captured image was independently inspected during review.

A bounded read-only replay of that **same final screenshot**, with the concrete postcondition `The screenshot visibly contains the text Summary ready: Alder.`, returned ready in 1.345 s. No desktop action was executed from replay evidence. This narrows the issue to sensitivity to postcondition wording; it does not prove reliable semantic verification. Keep unknown explicit, use observable postconditions, and retain screenshot reconciliation. No model replacement or success-forcing heuristic was added.

## Risk retirement / review

| Risk | Evidence rejecting the tempting shortcut |
|---|---|
| Ignore supplied predicates and ask the model anyway | Regression requires only the typed eligible action to reach the chooser |
| Revive previously excluded records | Conjunctive predicate regression |
| Borrow another record's control | Cross-record joins rejected, even for records removed by new predicates |
| Drop unknown or disabled eligible records | Selection blocked before chooser |
| Infer currency from a bare amount | Schema validation before extraction |
| Claim progress from tool delivery | Independent verification returns unknown and fresh evidence |
| Claim adoption from registration only | Fresh agents used MCP directly with actual provider traces |
| Claim general accuracy from a successful demo | Exact/filtered singleton paths and remaining visual uncertainty explicitly excluded |

Self-review: changes serve the original tool-adoption aim; no dispatcher policy or stock Driver code changed. Tests: 37 facade regressions, 46 capability tests, 15 parent-decider tests (98 total), plus an offline MCP protocol check covering discovery schema, money validation, read/filter/action mapping and screenshot-bearing verification. Existing gate: 28 scenarios, 40 metamorphic variants and 35 historical decisions pass; mutation detection remains separate from semantic review. Broad model quality and adoption are not established by this bounded sample.

Issue tracking: reading/choice contract [#6](https://github.com/open-horizon-labs/computer-use/issues/6), scoped discovery [#7](https://github.com/open-horizon-labs/computer-use/issues/7), continuing adoption observations [#1](https://github.com/open-horizon-labs/computer-use/issues/1). Reused the already-open demo window; stopped its temporary HTTP server afterward. The prior window-close issue remains separate.
