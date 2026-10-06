# Review

Aim: measure separately owned supervision and qualified application completion evidence on current patched Cua, independently and together, against current Arc, without weakening binding or concealing failure.

Decision: research qualification complete; production implementation remains unqualified. The packet contains actual native inputs, exact backend/source identities, alternating matched trials and adversarial refusals. The final combined commit milestone is 443 ms against Arc's 502 ms; the same combined task's full supervision fence is 1,492 ms. The mechanism is clear: release action locks after dispatch and own the remaining watcher separately, while a bound application acknowledgment and fresh AX proof establish value commitment.

The important rejected alternative is evidence-only as a generic default: its delayed activation control stole foreground despite successful value commitment. Supervision-only also falsely accepted late rejection and missing acknowledgment. Combined guards cover different failures. The original callback restore failure is preserved rather than omitted from the positive native qualification.

Risk evidence is mapped in REPORT.md. Native first-write rejection actually prevented the planned second input; native partial failure retained both writes for inspection. Orderly client EOF kept the native observer alive through delayed activation, but no final success was claimed through the closed transport. Protocol cancellation/misbound acknowledgments and wrong variants passed their independent keeper checks. No native arbitrary-crash durability claim is made.

No policy or production API changed. The new evidence narrows the claim from “finish every action faster” to “prove application commit promptly while explicitly owned supervision remains pending.” Reporting the latter as globally fenced completion would be misleading. This is a justified refinement of the completion contract, recorded in both the timings and explicit receipt state.

Human review is needed before adopting a production receipt/owner API, trusting a real application's immutable transaction evidence, or using exact-window restoration outside the owned sentinel fixture. Those require implementation and application-specific qualification, not an inference from this research. General completion, crash durability and ordinary foreground restoration are not marked ready for shipping. The 150 GB guest was not provisioned.

Issue: https://github.com/open-horizon-labs/computer-use/issues/109
