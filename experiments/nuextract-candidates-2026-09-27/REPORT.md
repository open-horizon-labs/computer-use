# NuExtract-first candidate preparation

Implemented an opt-in NuExtract page reader, whole-batch validation and same-record predicate filter before finite choice. Default Jev/Qwen and qualified GLiNER2 paths remain unchanged. The source endpoint is in homelab-infra; its mixed JSON/Python null parser was repaired and deployed for this test.

## Live results

| Check | Source and model | Result | Extraction | Chooser |
|---|---|---|---:|---:|
| 27 candidates, missing condition | Synthetic records → deployed NuExtract3 | 1 eligible, 25 excluded, 1 unknown; complete=false | 9.146 s | Not called |
| 27 candidates, complete conditions | Synthetic records → deployed NuExtract3 → actual Julia-1 | 26 excluded; Julia chose remaining ID 26; original request binding verified with a no-op callback | 8.079 s | 0.472 s round trip; 0.467 s inference |
| Browser extraction smoke | Fresh Cua Driver Chrome snapshot → deployed NuExtract3 | 56 heading-link records read; 0 eligible, 13 excluded, 43 unknown; incomplete scope, no chooser or product click | 13.650 s | Not called |

The complete synthetic case took 8.558 seconds for extraction plus choice, excluding worker startup. Extraction latency measures endpoint round trips, not pure model compute. Six chunks preserved all 27 input IDs; nothing was truncated or ranked as chunk winners. Julia's pinned checkpoint identity was checked by the adapter, and its worker was closed afterward. Qwen/default preference was unchanged.

The synthetic records intentionally make outcomes unambiguous; this tests transport, predicates, binding and capacity rather than shopping or chooser accuracy. A choice among one surviving candidate is not evidence for switching defaults. For a report, this extraction needs no chooser at all.

The browser smoke's heading-based record grouping included Amazon footer links even after requiring AXList parents. It is **not a clean product-listing evaluation**. The unknown/incomplete-scope result correctly blocked selection. The broad first pass covered 59 heading links in 14.393 seconds and also deferred; it is excluded from accuracy claims. Titles alone do not establish used condition, shipping or price. No prices were inferred and no purchase/cart actions occurred. This leaves complete product-card observation as an integration limitation, not an extractor success claim.

## Endpoint defect found and fixed

The initial live request returned HTTP 502 because NuExtract emitted `{'condition': null}`: Python-style quotes with JSON null. JSON parsing and plain `ast.literal_eval` both rejected it. The parser now transforms only AST name nodes for null/true/false, then uses literal_eval. Quoted text remains unchanged, and executable expressions or other names are rejected. The loaded NuExtract and Qwen model services were not restarted; only the SystemOne facade was restarted to load the parser repair.

## Verification

- 17 candidate-preparation tests pass, including six-chunk preservation, a winner in the final chunk, unknown condition, accessories, identity overlaps, cross-record contamination, stale/changed bindings, malformed endpoint responses, duplicate IDs, oversized survivors and timeout cleanup.
- Full capability-dispatch unit suite: 46 tests pass (includes the 17 above).
- Parent decider suite: 15 tests pass.
- Serving-endpoint suite: 12 tests pass (existing scorer contracts plus parser and extraction endpoint checks), run using its provisioned Python environment against staged source.
- Offline simulation gate: 28/28 scenarios, 40/40 metamorphic checks, 35/35 historical decisions; all seven deliberate bad mutations rejected.

## Execution review

Aim: shrink a large current candidate set through grounded reading and explicit predicates, preserving unknowns and action binding. Implementation and evidence are aligned; no generic default switch or GLiNER2 policy change was made.

| Risk | Evidence that rejects the tempting shortcut |
|---|---|
| Drop later chunks to fit Julia | Real 27-record case retains winner at index 26; unit test verifies six chunk sizes and all IDs |
| Treat missing condition as excluded | Real missing-condition case remains unknown; unit test prevents chooser call |
| Match accessories by model-name substring | Product-type predicate excludes case in real and unit cases; boundary overlap stays unknown |
| Borrow another record's fields | Cross-record test keeps target's missing condition unresolved |
| Invent price/confidence | Local source-quote validation and endpoint tests null an unsupported price; no confidence synthesized |
| Lose action binding | Original-request execute_bound check succeeds; changed arguments are rejected |
| Hide malformed/partial response | Missing, duplicate, stale, schema and HTTP-error tests fail closed |
| Tournament-rank too many survivors | Capacity test defers without generic call; explicit overflow receives every survivor |
| Hang while extracting | Real subprocess timeout test closes worker; one extraction deadline spans all chunks |
| Overstate live shopping success | Browser grouping limitation recorded; incomplete scope cannot authorize action |

This is a self-review, not independent certification of extraction accuracy. Future shopping qualification needs full product-card observations and independently reviewed expected fields; the current evidence supports the implementation contract and capacity fix.
