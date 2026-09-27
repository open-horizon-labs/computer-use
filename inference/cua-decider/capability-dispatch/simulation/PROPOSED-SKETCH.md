> Approved subsequently by the user; promoted to S4.4 and enabled in the experimental Engine. The text below preserves the original proposal and its rationale.

# Proposed CE-SIM-006: over-wide extracted identity

Status: proposed, not approved. Current S4 policy and default Engine behavior remain unchanged on this boundary. The candidate is opt-in through `boundary_recheck=True` for simulation only.

Observed input: two current products, `Acme product: $12` and `Acme product: $7`; caller requests cheaper Acme product, with explicit brand and price fields. Actual GLiNER2 returns `Acme product` as brand on both rows, with confidence above .99, even after descriptions are correctly encoded. Current projection excludes both because brand differs from `Acme`; no-match prevents Jev fallback. The desired simulated outcome is the $7 item.

Proposed clause: when an extracted text field fails an exact-equality predicate but contains the requested value as a complete word/phrase, treat that field as uncertain boundary evidence and consult the generic model with the original observation and criteria. Do not trim the value, accept a substring as equality, or bypass other established exclusions. Without generic resolution, defer. Substrings inside a different word do not trigger this rule.

Why this is a sketch decision: source offsets prove the text was present, not that the model found the right semantic boundary. But treating a previously excluded row as uncertain can also admit genuinely different identities such as Acme Pro to generic review. That is a new interpretation of the exclusion rule, not merely a byte-encoding repair.

Authority needed: user approval to promote this narrow ambiguity rule into S4.2/S4.3. This simulation request authorizes evaluating the candidate; it does not silently approve that policy trade-off. The capable-model reviewer can judge the candidate's conformance and outcomes but cannot invent broader fuzzy matching permission.

Tempting wrong repairs: automatically accept any substring; strip the literal word product; always ask Jev and discard all constraints; change the expected product; hide the failed input by relabeling the fixture. Required checks reject each relevant shortcut: no generic provider means no action; substrings inside another word remain excluded; unrelated known constraint failures remain excluded; inherited active/R cases retain their outputs.
