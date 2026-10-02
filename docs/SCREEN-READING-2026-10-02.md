# Reading screens without AX

Aim: agents can inspect visible content through the same MCP facade when accessibility information is absent, including the isolated browser on a virtual display. User explicitly skipped live OBO testing while the desktop is locked. This work reads synthetic isolated fixtures; it does not qualify live user-app or phone behavior.

## Fact check

| Claim | Status | Evidence and correction |
|---|---|---|
| NuExtract3 accepts screenshots as image inputs and can extract structured fields. | Verified with edit | The [official model card](https://huggingface.co/numind/NuExtract3) documents image/text inputs and an OpenAI-compatible image extraction example. This establishes input support, not UI-reading accuracy or action grounding. |
| The installed NuExtract adapter already reads screen pixels. | Incorrect | `page_candidates.NuExtractPage`, `workers/page_extract_worker.py` and the deployed `/v1/extract-page` schema accept `{id,text}` records. The current adapter enforces verbatim substring presence in the source record. It does not send images. |
| No native AX means there is no way to read a browser. | Incorrect | Earlier DOM fixture runs already established text access. This probe additionally captured and visually inspected a readable 1840×857 browser viewport through Driver 0.31.0 on the isolated virtual display. |
| Driver can take a native window screenshot without walking AX. | Verified | Installed `cua-driver describe get_window_state`: `include_accessibility_tree:false`. A correctly targeted capture can still be blank; that is not evidence of page content. |
| Browser screenshots require activating the tab or window. | Incorrect for this route | Installed `get_browser_state(include_screenshot:true)` captures the exact bound tab through CDP. The returned metadata reports `tab_activation:not_requested` and `window_foregrounding:not_requested`. [Driver reference](https://github.com/trycua/cua/blob/main/docs/content/docs/reference/cua-driver/mcp-tools.mdx). |
| OCR provides the same exact-value evidence as AX/DOM. | Incorrect | Existing local Cua Perception probes produced `60 min`→`600 min` and `Starts 1:30 PM`→`Starts 130 PM`; OCR remains a separate evidence source, not an authoritative numeric transcription. |
| mobile-mcp can return images even though this facade previously retained only text. | Verified | Installed `@mobilenext/mobile-mcp@1.0.6/lib/server.js` defines `mobile_take_screenshot`, returning PNG/JPEG MCP image content. The new facade transport preserves that image block. Live device reading remains untested. |
| NuExtract is faster, cheaper or more reliable than direct screenshot reading for these tasks. | Unsupported | No paired screenshot benchmark exists here. The configured service advertises text extraction only; the separate multimodal endpoint probe was unreachable. No accuracy, price or speed advantage is claimed. |

No high-stakes factual claims require domain-expert review. Remaining evidence gaps are empirical: live native/mobile readability, NuExtract image service availability and task-specific paired accuracy/latency/cost. Vendor document benchmarks do not retire those gaps.

## Solution space

Criteria: usable pixels without AX, exact target attribution, unchanged ordinary-call cost, compatibility across drivers, and no invented action bindings. Critical assumption: a supported driver can produce readable pixels for the requested surface; no reader can reconstruct a black capture.

| Option | Frame | Decision-changing trade-off | Disposition |
|---|---|---|---|
| Keep DOM and Perception only | Missing AX is a text-observation problem | Cheap and already useful, but canvas/native/device pixels can remain unavailable to the controlling agent. | Preserve existing routes, insufficient alone. |
| OCR → existing NuExtract text extraction | All evidence can be flattened into text | Easy reuse, but digit corruption becomes apparently verbatim evidence and visual grouping is lost. | Reject as authoritative extraction. |
| Shared explicit screenshot read through existing look | Observation delivery is the missing capability | Works with the controlling model and keeps capture separate from interpretation. Adds image cost only when requested. | Selected. |
| Dedicated NuExtract image service for all reading | Specialist extraction is the main bottleneck | Could return compact fields, but needs a deployed image endpoint and paired task measurements; it cannot establish Driver action bindings. | Deferred pending actual image-service access and measurement. |

Interpretive variety: the first two options assume text is sufficient; the third tests whether missing pixel access is the immediate failure; the fourth tests specialization. If a correctly bound screenshot is still unreadable, changing the extractor will not repair the capture. If direct screenshots work but their cost dominates, measure specialist extraction on the same captured cases.

## Dissent and execution decision

The strongest argument for immediate NuExtract integration is compact structured output from a small multimodal model. Contrary evidence: our deployed endpoint is text-only, screenshot extraction has no verbatim-substring validator equivalent to text, and the missing screenshot path prevents even the controlling model from seeing pixels. Functional failure would be confident extraction from a blank image; adoption failure would be a separate tool or setup ritual agents never use; opportunity cost would be building a service before testing browser CDP capture.

Decision: adjust to one optional `screen` argument on `look`, with one shared image-validation contract behind desktop and mobile adapters. Keep the ordinary text route and all existing action rules. Hidden assumptions are checked below. Do not add a speculative provider configuration or claim a nonexistent deployed image extractor. No new tool, mandatory caller step or CALL_BUDGET value changes. CE-FACADE-014 records the behavior; the tool description was shortened to stay inside the existing response ceiling.

Success criteria: a real isolated browser screenshot is readable; native and mobile adapters have bounded read-only paths; MCP carries the image rather than base64 in text; ordinary text looks start no image/model work; mismatched targets and blank captures refuse; screen observations never authorize record filters or clicks. The scope excludes additional OBO live tests, GPU deployment, and unqualified screenshot-to-coordinate actions.

## Risk retirement

| Risk / invalidation trigger | Disposition | Tempting wrong patch rejected by evidence |
|---|---|---|
| Pixels unavailable despite DOM success | Retired for the isolated browser | Captured real Driver viewport, visually inspected booking strings; a text-only adapter would fail to return the PNG fixture. A later native capture was also readable after preserving transparent rounded corners; genuinely blank captures remain a typed limitation. |
| Wrong target/tab or native owner | Retired by offline checks | `test_screen` changes target/tab/owner while preserving pixels; rejects a patch that accepts any screenshot or hides a target mismatch with fallback. |
| Blank/corrupt/excessive captures enter inference | Retired by offline checks | Uniform black/white/gray, malformed payloads, wrong MIME and size limits fail before model/image delivery. Nonuniform error screens still require reader judgment. |
| Images gain record/action authority | Retired by offline checks | No look_id, selection, snapshot or record is created; source/action_binding metadata is explicit. Existing binding/verification checks are retained. |
| Context remembers an unrelated earlier window | Retired by offline checks | A second targetless screenshot call reuses the exact capture target, with a new observation identity. |
| Mobile transport silently drops images | Retired by protocol check | Real stdio MCP roundtrip returns the PNG through the production mobile transport. Device errors cannot leak raw diagnostic text. Live device capture is accepted as unmeasured because no device task was selected. |
| Added work increases ordinary call cost | Retired by budget and route checks | Existing captured-Chrome call budgets pass. Default text look cannot enter the screenshot route or start a reader; optional screen calls start no provider. |
| NuExtract service really supports images today | Triggered: do not integrate the text endpoint | Endpoint schema and source inspection contradict that assumption. Direct-image extraction needs a distinct deployment/probe, then paired measurements. |
| Nonuniform capture guarantees readable content | Accepted with rationale | This cannot be proven by an image validator. Return the actual image, never inferred text; controlling reader must report unreadable/locked content honestly. |

## Verification and review

`computer_use/test_screen.py` covers the shared boundary and real MCP image transport using the actual Driver booking capture. The capture contains synthetic fixture data only. Native capture was also inspected live on the isolated synthetic browser; mobile adapter tests are contract checks, not measured live device reliability. Final validation: 1,255 facade tests, 26 dispatcher tests, 15 decider tests, 22 script tests and 52 experiment tests passed. Protocol, simulation, skill synchronization, call/response budget and look-comparison checks passed. All 194 negative mutations were caught by named assertions (189 existing plus five new screenshot cases). Independent capable-model certification and comparative screen-reader accuracy are not claimed; this is a self-review against the existing facade contract.

The live isolated probe is recorded in `experiments/screen-reading/live-capture.json`. The final browser read took 517 ms and returned 88,412 base64 image bytes; image interpretation time is excluded. Browser and native images were inspected directly. This is a small read-only fixture probe, not a native-vs-NuExtract bakeoff. No OBO test, real-account action, or GPU service change was performed.

Review outcome: aligned after one correction. Transparent macOS window corners must be ignored when testing uniformity, rather than treated as missing pixels; real native and browser PNGs are now retained as regression fixtures. The optional read path supplies pixels without expanding action authority. NuExtract service deployment and comparative reader measurements remain separate unverified work. Claude Code and Codex MCP configurations already point to this checkout; Pillow was installed and all three local skill copies were refreshed. Existing clients need an MCP reconnect to reload the schema.
