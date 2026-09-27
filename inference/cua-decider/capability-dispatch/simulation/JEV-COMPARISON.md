# Capability dispatch versus Jev alone

User approved CE-SIM-006; S4.4 and the experimental Engine now enable boundary recheck. No production selector installation occurred.

Fresh paired inference on 39 fixed observations: four simulation requests and 35 historical booking decisions. Alternated arm order, identical caller fields/predicates/order/scope/fallback, unchanged expected action IDs. Jev-only uses direct hosted Jev with no Qwen rescue. Capability dispatch uses GLiNER2 and the installed Jev→Qwen selector. Each independent case gets a fresh selector process to avoid inherited feedback state. The direct Jev HTTP client and extractor are reused. These are decisions on fixed observations, not new end-to-end browser completions.

| Arm | Correct next action | Abstentions | Wrong actions | Median decision latency | Mean |
|---|---:|---:|---:|---:|---:|
| Capability dispatch | 39/39 | 0 | 0 | 29 ms | 112 ms |
| Jev alone | 23/39 | 14 | 2 | 144 ms | 179 ms |

Jev's abstentions count as non-completion, not wrong clicks. No probability threshold was imposed on Jev-only: returned offered choices were evaluated directly. Both arms expose reobserve/abstain. Jev model reported jev-1.13.0. Capability used Qwen once, on the unavailable-specialist case; the product-boundary case was GLiNER2 then Jev, without Qwen. All 35 booking decisions used extraction without generic recovery.

Median speedup is about 4.9× on this selected corpus. Extractor loading took 4.56 seconds, excluded from decision latency. Including that startup, summed capability time is about 8.93 seconds versus 7.00 seconds for Jev-only. The speed benefit therefore assumes a resident extractor or enough requests to amortize loading. Generic recovery is not inherently faster: on the product case, capability took 859 ms versus 143 ms for Jev-only, both correct. Fresh selector initialization/credential access contributes to the recovery latency, while the direct Jev client is already warm; do not interpret that difference as inference-only cost.

This is a small, extraction-heavy development corpus (35 booking steps from 20 tasks, not 35 independent tasks), with one run per request and no held-out general-CUA qualification. It supports using extraction for explicit matching requests and retaining Jev for semantic work. It does not establish general dominance or replace the earlier differently prompted benchmarks. Prompt/serialization, explicit fallback rules and abstention options affect Jev's results.

## Audit and implementation

`jev-comparison.json` is the valid final run, including full decisions and timing. `../compare_jev.py` reproduces it. Two discarded harness runs remain for transparency:

- `jev-comparison-invalid-harness.json`: missing prose goal in typed booking requests caused adapter errors; these are not model errors.
- `jev-comparison-invalid-session-state.json`: independent cases reused selector progress state, causing unwarranted Qwen escalation. Not a valid cascade comparison.

Both adapters now include typed scope/fallback metadata and accept a typed request without a prose goal using a generic criteria-following instruction. No expected answers enter inference. The controlled gate still passes 28 scenarios, 40 variants, 20 unit tests, 35 captured replays and all seven wrong-repair mutations after policy promotion. Semantic review from the preceding simulation is retained; S4.4 now has explicit user authority.
