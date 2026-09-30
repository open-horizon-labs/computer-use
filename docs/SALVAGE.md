# Salvage — 2026-09-27

Original aim: improve generic computer-use correctness and speed. Repeated training/router experiments accumulated in infrastructure code. This extraction gives the reusable policy, projection and evidence their own home while preserving the original working tree.

## Learning to retain

- NER extracts caller-described fields; it does not rank whole actions against an open goal. Explicit same-record comparisons made the GLiNER2 path useful without another training run.
- Validate provider payloads before diagnosing training quality. Raw GLiNER2 `entities` values did not carry descriptions; `entity_descriptions` did.
- Grounded offsets and high confidence do not guarantee the intended semantic boundary. Approved S4.4 permits Jev review of whole-value overlaps without accepting substring equality or bypassing other exclusions.
- Qualify specialists before training a router. The current request-kind dispatcher is code implementing the sketch. Several model-family routes remain unqualified live hypotheses.
- Preserve selector feedback state within a task, never across independent cases. A rejected comparison accidentally escalated through inherited unverified progress.
- Missing prose goals in typed historical requests caused adapter errors, not model errors. Retain invalid-run provenance without counting it as accuracy evidence.
- Startup and warm decision latency answer different questions. The measured extraction advantage assumes enough reuse to amortize loading.

## Ownership and guardrails

The controller owns task interpretation; providers return evidence; the matcher applies explicit constraints; the stock driver executes current bound arguments; independent observation verifies effects. The user authorizes sketch changes. A passing gate cannot approve a new identity policy. Semantic self-review is not independent review.

Retain S, K, P, A, R/G distinctions from the sketch. Accepted CE provenance is in COUNTEREXAMPLES.json. Regression and mutation checks reject known wrong implementations. Historical reports and manifests describe their original runs; use current sketch and tests for current policy.

## Restart kit

Start with skills/computer-use/SKILL.md and the sketch. Run the offline gate, broaden beyond booking, then qualify through real Driver tasks. Add fine-tuning only after a measured role failure survives adapter and input-contract checks. Keep infrastructure, datasets and model deployment separate.

Reusable fragments: typed dispatch/matcher, span schema adapter and worker, bounded generic recovery, full-request binding, controlled simulator, real-provider comparison harness, accepted CE archive and historical review. No stock skill or tool was overwritten. No original source was deleted.

## Import provenance

ORIGIN.json records original working-tree file hashes and base commit, including untracked experiment files. Retained inference paths make original replay references work. Portability edits replace the hard-coded span-worker launch with explicit CUA_SPAN_COMMAND and permit CUA_SELECTOR_COMMAND. The custom skill packages guidance previously spread across the guide and sketch; no standalone custom skill file was found in the installed skill directories.
