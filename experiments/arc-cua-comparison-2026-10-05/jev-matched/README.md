# Matched real JEV trial evidence

The runner uses current-source Arc, the current signed Cua Driver daemon and the configured `fleet-op` credential helper. It runs owned AppKit/WebKit fixtures only. Set ARC_EVAL_SOURCE to the clean current Arc checkout and run run_matched.py with its Python environment containing Arc/PyObjC/HTTP2 support. JEV_MATCHED_REPS defaults to three.

The runner writes the complete results.json, including sanitized public-MCP observations and exact arguments. The checked-in results.json is a review summary that omits repeated tool snapshots and tool schemas; all other scored fields are preserved. The byte-for-byte original is results-full.json.gz. TRACE-MANIFEST.json records hashes and sizes of both raw and compressed data. Decode with `gzip -dc results-full.json.gz` to inspect or rescore full evidence. The two compressed invalid-smoke files are unscored preparation evidence; their corrections and exclusion are explained in the report.

Run test_binding.py through unittest discovery for five offline adapter contracts. These use no models, desktops or external services and do not establish model accuracy. The adapter is evaluation scaffolding, not a production integration or an optional OH runtime route.
