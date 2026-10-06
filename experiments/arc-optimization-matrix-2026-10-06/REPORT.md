# Arc-inspired optimization results

Execution complete: independently tested observation batching, screenshot omission with fresh geometry, structural reuse, and notification wakeups; combined the two qualified approaches and verified completed tasks. The reviewable native change and complete reproduction packet are in [Cua PR #4762](https://github.com/trycua/cua/pull/4762), closing [#4761](https://github.com/trycua/cua/issues/4761). This extends and overlaps #4748; their gains must not be added.

## Current measurements

All timings below use latest upstream Cua `45775a9244df4a1e33090c1377eeb2448d2eb820`, actual embedded SDK server 0.34.0, and current Arc source `74ffae1108b1cb4b1f6b161084af12646f544ba5`. Preflight stopped and rebuilt candidates when upstream advanced. Each arm requests `full_output:true`, `max_elements:2000`; the new slim default was not silently substituted for complete binding evidence. Exact sources, binary hashes, timestamps and actual runtime metadata are in the manifests and raw traces.

| Median observation time | Small fixture | Large fixture |
|---|---:|---:|
| Baseline, full screenshot | 237.790 ms | 397.311 ms |
| Baseline, tree plus fresh geometry | 91.655 ms | 185.673 ms |
| String-only batching, tree plus geometry | 80.893 ms | 170.369 ms |
| Broader batching, full screenshot | 217.142 ms | 378.346 ms |
| Broader batching, tree plus geometry | 68.145 ms | 139.477 ms |

Twenty alternating repetitions per arm and fixture produced 240 scored observations, plus 24 warmups. All preserved normalized AX semantics and complete Markdown hashes. The combined path beat baseline full in 20/20 pairs for each fixture. Broader batching alone, holding the tree-plus-geometry mode constant, won 16/20 small and 18/20 large pairs; paired median reductions were 19.975 and 34.861 ms. With screenshots retained its wins were noisier: 12/20 and 11/20.

## Completed tasks

| Verified two-field task | Baseline full | Combined path | Reduction |
|---|---:|---:|---:|
| Small fixture | 3.465443 s | 2.542003 s | 26.6% |
| Large fixture | 4.078091 s | 2.913039 s | 28.6% |

All twelve trials passed final fresh AX values and the independent fixture oracle; zero false completions. The combined path won all six alternating matched pairs. Both arms used the unchanged PR #4751 caller-literal executor, retained both fresh reads before each setter, and performed five observations and two setters. Public calls increased from seven to twelve because screenshot-free observations independently refresh window identity and geometry. No model or JEV calls were timed: these are completed literal-plan tasks, not whole-agent planning results. Three pairs per fixture establish a promising fixture result, not broad application coverage.

The production patch batches typed AX values, geometry and actionable state. Screenshot omission is a guarded research wrapper, not a changed Driver default. It requires an exact unique owner, current root token and fresh window/frame agreement; it never invents capture validity. Four wrong-record live controls refused before any write.

## Rejected approaches

Conservative fresh structural reuse did not save native AX calls. Across 36 randomized triples it took 5.139 ms versus 4.954 ms full fresh and 4.907 ms identical fresh override. All semantic adversaries passed, but the earlier apparent gain did not reproduce. No port is proposed.

Arc’s optional cache was faster in its microbenchmark (6.114 to 3.468 ms), but a deliberately omitted notification feed left a renamed button stale. Independent application proof confirmed the change. This fails the freshness contract and is disqualified; it does not assert that the real fixture naturally failed to emit a notification.

Notification wakeups did not qualify. Latest-source native trials measured 1.208052 s baseline versus 1.221408 s candidate, with zero actual activation callback or wake receipts. All six trials failed focus preservation in both arms, although each submitted and requested delayed activation exactly once. Offline mechanism tests passed, but live delivery was not demonstrated. The unbundled fixture/embedded CLI context may affect delivery; these results do not establish a universal Cua defect. See negative-approaches.md and retained raw receipts. No PR for either negative prototype.

## Verification and risk retirement

Root independently reran the final candidate locally: 473 platform-macos tests passed, six ignored; all five wrapper tests passed. No VM, GPU, production daemon replacement or permanent settings changes. Owned fixtures and test daemons closed, and fresh foreground restoration was independently confirmed.

| Risk | Status | Tempting wrong patch rejected | Evidence |
|---|---|---|---|
| Batched slots lose types or move errors | Retired | Shift error slots or decode everything as strings | Actual mixed CF values, fallback tests, slot-shift mutant fails |
| Screenshot omission weakens target eligibility | Retired within fixture contract | Invent capture flags or accept missing/ambiguous geometry | Five keeper checks; removed owner/frame guards fail mutants |
| Narrow trees hide record context | Triggered; narrow projection rejected | Filter to Email and assume uniqueness | Sibling context lost; four live wrong-record handoffs before writes |
| Cache misses silent changes | Triggered; cache rejected | Trust retained dynamic values | Rename/missed-feed stale-control proof |
| Safe topology reuse is worthwhile | Triggered; port rejected | Attribute first timing difference to reuse | 36 randomized triples, identical AX call counts |
| Notification hints justify early success | Retired offline; live benefit unqualified | Treat hint as success or shorten fallback horizon | Storm mutant fails; zero live delivery and focus failures retained |
| Combined gain reflects correct tasks | Retired within fixture contract | Count setters as completion | Twelve fresh final AX plus independent app proofs |
| Gains generalize to real apps/model planning | Accepted boundary | Extrapolate fixtures to whole-agent performance | No such claim; broader desktop qualification remains outstanding |

The upstream PR is draft pending maintainer review and broader canonical desktop qualification. The earlier Lume waiver is not treated as qualification for this new production patch. The experiment itself is complete; no credentials or human input are needed to interpret the owned-fixture results.
