# CESS strangler trial: described span matching

This is the first executable specialist takeover cohort. The existing CESS sketch sends caller-described short English fields to GLiNER2, compares grounded values within their source control, and binds one current action. This trial wrapped that route in an explicit Jev shadow/active transition.

## Shadow result

`strangler-shadow-trial-2026-09-27.json` reruns actual inference over the saved 20-task booking trace (35 decisions) plus four controlled simulator cases. It uses the frozen caller contract and the saved independently checked task outcomes. No browser actions were run in this turn. The GLiNER2 worker used GPU1, the RTX 3060 Ti; Jev used the existing Fleet credential path. The Qwen service remained running.

| On the 35 booking decisions | GLiNER2 specialist | Hosted Jev alone |
|---|---:|---:|
| Correct recorded choices | **35/35** | 21/35 |
| Tasks with every step correct | **20/20** | 8/20 |
| Warm median decision time | **29.4 ms** | 135.2 ms |

The combined four simulator cases were 4/4 for each arm; the full set was 39/39 for the specialist and 25/39 for Jev. In shadow, Jev remained the returned selection. The specialist was observed in parallel. There were 14 disagreements: Jev abstained on 12 and chose a different control on two. All specialist choices matched the saved outcomes. Those records point back to accepted CE-CAP-001 and S4.1–S4.3, so this result supports the existing policy and needs no new sketch rule. Any new mismatch would remain a review proposal until an outcome was independently observed and CESS review classified it.

Warm decision latency excludes GLiNER2 model startup (4.58 seconds). The 35 steps are correlated within 20 booking tasks and come from an already-used development fixture. These numbers qualify only the described short-field English matching contract on this fixture. They do not establish general CUA accuracy or live desktop completion. Direct Jev abstentions count as non-completions in the 21/35 result.

## Active replay

The promotion record binds this cohort to accepted CE-CAP-001, this report, and the aggregate SHA-256 of the exact cached `fastino/gliner2-base-v1` checkpoint. `run_strangler_active.py` explicitly invoked `stage='active'` on the saved decisions. It selected 35/35 recorded actions across all 20 tasks, with 35/35 IDs still bound to their request snapshot. It did not issue desktop actions. The tracked default in `ROLLOUT.json` remains `shadow`; a caller must explicitly choose active mode for this request contract.

In active mode the specialist's valid unique match or authorized explicit fallback becomes the returned decision. Missing evidence, provider errors, and ambiguous matches go to Jev once under S4.3. All requests outside this contract keep the existing dispatcher behavior. `Strangler` never executes actions. The caller must still revalidate and execute through stock Cua Driver, then independently check progress.

## CESS disposition

- `S`: the current `SKETCH.md`; no policy edit was made.
- `P`: the existing typed dispatcher plus `rollout.py` shadow/active wrapper.
- `A/R/G`: existing accepted archive and gates, plus the shadow records as experiment evidence.
- Disagreements are telemetry, not accepted CEs. `counterexample_status` requires an independent outcome and CESS review.
- Active startup fails closed unless its promotion record names the authorizing user, an accepted archive CE, an existing qualification report, and a full checkpoint SHA-256.

The trial demonstrates the requested strangler step for one known Jev task contract: GLiNER2 takes the defined extraction/matching role, while Jev remains the default outside that scope and the single recovery route within it. The rollout config remains shadow by default; the active replay exercised the reviewed takeover record in the experimental dispatcher, without changing an installed service or stock Cua Driver.
