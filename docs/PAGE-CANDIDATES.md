# NuExtract before finite-choice selection

**Current default:** NuExtract3 page reading/filtering → Julia-1 finite choice, with GLiNER2 spans and SystemOne/Qwen screenshots. Runtime helpers load `~/.config/computer-use/runtime.json` automatically. Jev/Qwen remains an explicit alternative.

Use extraction to reduce a large **observed** candidate set under explicit caller predicates. Chunk the reading, not the chooser's comparison. This is the selected default; the qualified GLiNER2 route is unchanged.

```sh
export CUA_PAGE_EXTRACTION=1
export CUA_EXTRACT_URL='http://YOUR-SYSTEMONE-HOST:8010/v1/extract-page'
# Selected default generic chooser.
export CUA_GENERIC_PROVIDER=julia-1
# Configure CUA_JULIA_COMMAND as documented in PROVIDERS.md.
```

`generic_from_config()` then constructs `ExtractThenChoose(NuExtractPage(), generic)`. Requests without `page_filter` pass through unchanged. Keep this wrapper in the existing `incumbent_jev` slot of `Strangler.from_config`; exact controls and successful qualified GLiNER2 requests continue to bypass it. Close the wrapper once per task in `finally`; it owns its extractor and generic worker.

For a semantic request, include:

```python
request['page_filter'] = {
    'task': 'Read product model, product type, and explicit item condition.',
    'candidate_ids': [action['id'] for action in request['actions']],
    'fields': {
        'model': {'type': 'text', 'description': 'Explicit model of the product sold'},
        'kind': {'type': 'text', 'description': 'Product type actually sold, such as case or power bank'},
        'condition': {'type': 'text', 'description': 'Explicit item condition; null if absent'},
    },
    'predicates': [
        {'field': 'model', 'value': 'Anker 737'},
        {'field': 'kind', 'value': 'power bank'},
        {'field': 'condition', 'value': 'Used'},
    ],
    'coverage_complete': True,  # Only when the controller established this scope.
}
```

The example's values are caller criteria, not rules hardcoded into the adapter. All offered actions must be record-backed candidates in this filter scope. Do not mix navigation buttons into listing records. Each action retains `evidence_text` and its original Driver arguments. Record text must come from one fresh snapshot; group fields within the same listing. A search page heading or a neighboring listing's price is not evidence for a candidate.

## Processing and authorization

1. Send chunks of five records by default (configurable 1–30). The endpoint accepts at most 30 records per call. One 20-second budget covers the entire extraction, including transport and all chunks; timeout closes the worker and discards the partial batch.
2. Check every returned record ID, snapshot ID, field schema and source quote locally. Restore original input order after merging chunks. Missing or ungrounded values become unknown, with no invented confidence score.
3. Apply supported typed predicates conjunctively within each record. A known contradiction excludes that record even if another field is missing. Missing fields and identity-boundary overlaps remain unresolved. Extraction's semantic correctness still requires review: verbatim copying alone cannot prove the model picked the right source span.
4. If coverage is incomplete or any possible competitor remains unknown, defer without a chooser call. If no candidates qualify, report no match. Do not silently drop unknowns to fit Julia.
5. Send at most 18 eligible candidates to Julia plus its two defer options. The wrapper preserves the original goal, history, constraints and retained source evidence. It never tournaments chunks or silently trims text. If more candidates survive, defer; a caller may explicitly inject a larger-capacity `overflow` provider. That provider must receive every survivor and enforce its own input limits.
6. Validate the chosen ID against retained candidates. The outer Engine binds the result to the original full request, including stored Driver arguments; call `execute_bound` with the unchanged request and current snapshot, then independently verify.

Extraction and chooser are separate bounded phases: 20 seconds for the complete extraction, then the selected provider's decision bound. A full operation can therefore take longer than 20 seconds while making progress. Report extraction endpoint latency separately from chooser latency and worker setup. Transport timeout closes the client worker; upstream cancellation depends on the serving endpoint.

## Reading without choosing

For reports, call `NuExtractPage.extract(...)` and `filter_records(...)` directly. Return eligible records and disclose unresolved ones; no generic chooser is needed. Extract visible price, shipping, condition and listing link as additional described fields when the record actually contains them. Keep missing fields null and the original Driver-bound link association. Never report a new/accessory price as a used device price.

`coverage_complete` describes the declared observed scope, not the entire marketplace. Title-only observations cannot establish condition, price or shipping. The live test deliberately reports that limitation rather than treating unknown listings as exclusions.

## Verification

See [live and contract results](../experiments/nuextract-candidates-2026-09-27/REPORT.md). Tests cover later-chunk survivors, unknowns, accessories, identity overlap, source grounding, malformed batches, same-record comparisons, stale/changed bindings, capacity deferral and transport timeout. They do not establish broad shopping accuracy.
